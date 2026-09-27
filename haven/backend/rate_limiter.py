"""
Rate limiting + durable security cooldowns for HAVEN.

Backends (chosen internally; callers keep the SAME interface):
  * Distributed  -> Redis (atomic sliding-window Lua script; shared across
                    every backend instance). Used when REDIS_ENABLED/REDIS_URL
                    are configured AND the `redis` package is importable and
                    reachable.
  * Local        -> in-memory SlidingWindowRateLimiter (single process only).
                    This is the local-development fallback and is preserved
                    verbatim as the original behavior.

Production safety:
  * REDIS_REQUIRED_IN_PRODUCTION (default: true in production) makes the
    rate-limit path FAIL CLOSED (HTTP 503) rather than silently degrade to an
    unbounded / single-process limit when Redis is missing or unreachable.
  * Security COOLDOWNS never fail closed: if the shared backend is unavailable
    they fall back to the in-memory mirror, because blocking a legitimate SOS
    trigger on an infra outage is worse than a locally-scoped cooldown.

Nothing sensitive is ever placed in a Redis key or value: no passwords, JWTs,
raw SOS payloads, or GPS. The per-user component of a rate-limit identity is a
SHA-256 digest of the Authorization header, never the raw token.
"""

import os
import time
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Tuple

from fastapi import Request, HTTPException, status

logger = logging.getLogger("haven_backend")

# ─── Environment / configuration ────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_ENABLED = _env_bool("REDIS_ENABLED", bool(REDIS_URL))
# In production we require a shared backend by default so security limits and
# cooldowns are actually distributed. Operators can opt out explicitly.
REDIS_REQUIRED_IN_PRODUCTION = _env_bool("REDIS_REQUIRED_IN_PRODUCTION", IS_PRODUCTION)

# Key namespaces (STEP 9).
_RL_NS = "haven:ratelimit"
_CD_NS = "haven:cooldown"

# Atomic sliding-window log implemented as a sorted set. A single Lua execution
# performs prune -> count -> (conditionally) add + expire, so there is no
# GET->increment->SET race across concurrent requests.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local maxr = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= maxr then
  return 1
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return 0
"""


class SlidingWindowRateLimiter:
    """Unchanged in-memory limiter — the local-development fallback."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key -> list of float timestamps
        self.requests: Dict[str, List[float]] = {}
        self._last_cleanup = time.time()

    def _cleanup(self, now: float):
        """Remove stale keys periodically."""
        if now - self._last_cleanup > 300:  # Every 5 minutes
            stale_keys = []
            for key, timestamps in self.requests.items():
                active = [t for t in timestamps if now - t < self.window_seconds]
                if not active:
                    stale_keys.append(key)
                else:
                    self.requests[key] = active
            for k in stale_keys:
                self.requests.pop(k, None)
            self._last_cleanup = now

    def is_rate_limited(self, client_identifier: str) -> bool:
        now = time.time()
        self._cleanup(now)

        window_start = now - self.window_seconds
        timestamps = self.requests.get(client_identifier, [])

        # Filter timestamps in current window
        active_timestamps = [t for t in timestamps if t > window_start]
        self.requests[client_identifier] = active_timestamps

        if len(active_timestamps) >= self.max_requests:
            return True

        self.requests[client_identifier].append(now)
        return False


def get_client_ip(request) -> str:
    """Extract client IP handling reverse proxies.

    Kept identical to the original trusted-proxy handling (X-Forwarded-For
    first hop, else the direct peer address). audit_service imports this too.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


# ─── Shared backend resolution (Redis vs in-memory) ─────────
_backend_resolved = False
_backend_mode = "memory"          # one of: "redis", "memory", "fail_closed"
_redis_client = None
_backend_lock = threading.Lock()


def _resolve_backend() -> Tuple[str, object]:
    """Resolve the shared backend once, then cache the decision.

    Returns (mode, client). mode is:
      * "redis"       -> distributed backend is live (use `client`)
      * "memory"      -> local in-memory fallback (dev / Redis intentionally off)
      * "fail_closed" -> Redis is required in production but unavailable; the
                         rate-limit path must reject requests (503).
    """
    global _backend_resolved, _backend_mode, _redis_client
    if _backend_resolved:
        return _backend_mode, _redis_client
    with _backend_lock:
        if _backend_resolved:
            return _backend_mode, _redis_client
        _backend_resolved = True

        if not (REDIS_ENABLED and REDIS_URL):
            if IS_PRODUCTION and REDIS_REQUIRED_IN_PRODUCTION:
                _backend_mode = "fail_closed"
                logger.error(
                    "Rate limiter: Redis is REQUIRED in production but "
                    "REDIS_URL/REDIS_ENABLED is not configured — rate-limited "
                    "endpoints will fail closed (503). Set REDIS_URL, or set "
                    "REDIS_REQUIRED_IN_PRODUCTION=false to accept single-process limits."
                )
            else:
                _backend_mode = "memory"
                logger.info("Rate limiter backend: in-memory (single process; Redis not enabled).")
            return _backend_mode, _redis_client

        # Redis requested — attempt a lazy, optional connection. The `redis`
        # package is an OPTIONAL dependency; if it is not installed the app
        # still runs on the in-memory fallback (or fails closed in prod).
        try:
            import redis  # optional import
            client = redis.Redis.from_url(
                REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            client.ping()
            _redis_client = client
            _backend_mode = "redis"
            logger.info("Rate limiter backend: Redis distributed backend initialized.")
        except Exception as e:  # ImportError, ConnectionError, etc.
            if IS_PRODUCTION and REDIS_REQUIRED_IN_PRODUCTION:
                _backend_mode = "fail_closed"
                logger.error(
                    "Rate limiter: Redis is REQUIRED in production but unavailable "
                    "(%s) — rate-limited endpoints will fail closed (503).",
                    type(e).__name__,
                )
            else:
                _backend_mode = "memory"
                logger.warning(
                    "Rate limiter: Redis unavailable (%s); using in-memory fallback "
                    "(single process only).",
                    type(e).__name__,
                )
        return _backend_mode, _redis_client


def backend_status() -> str:
    """Observable backend mode ('redis' | 'memory' | 'fail_closed'). No creds logged."""
    mode, _ = _resolve_backend()
    return mode


def _reset_backend_for_tests():
    """Test hook: force re-resolution (used by the standalone/pytest suites)."""
    global _backend_resolved, _backend_mode, _redis_client
    _backend_resolved = False
    _backend_mode = "memory"
    _redis_client = None


# ─── Rate-limit core (backend-agnostic) ─────────────────────
def _client_identity(request) -> str:
    """Rate-limit identity from the VERIFIED-credential + trusted IP strategy.

    Uses the client IP (via the existing trusted-proxy handling) and, when an
    Authorization header is present, a SHA-256 digest of it — never the raw
    JWT (STEP 9). A user-supplied body field is NEVER used as identity.
    """
    ip = get_client_ip(request)
    auth = request.headers.get("Authorization")
    if auth:
        digest = hashlib.sha256(auth.encode("utf-8")).hexdigest()[:16]
        return f"{ip}:tok_{digest}"
    return ip


def _redis_is_limited(client, scope: str, identity: str,
                      max_requests: int, window_seconds: int) -> bool:
    key = f"{_RL_NS}:{scope}:{identity}"
    now_ms = int(time.time() * 1000)
    window_ms = int(window_seconds * 1000)
    member = f"{now_ms}-{os.urandom(4).hex()}"
    res = client.eval(_SLIDING_WINDOW_LUA, 1, key,
                      now_ms, window_ms, max_requests, member)
    return int(res) == 1


def _is_rate_limited(scope: str, request, max_requests: int,
                     window_seconds: int, mem_fallback: SlidingWindowRateLimiter) -> bool:
    """Decide Redis vs in-memory and return whether this request is limited."""
    identity = _client_identity(request)
    mode, client = _resolve_backend()

    if mode == "fail_closed":
        # Do NOT silently degrade to unbounded: reject instead.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting backend unavailable.",
            headers={"Retry-After": str(window_seconds)},
        )

    if mode == "redis":
        try:
            return _redis_is_limited(client, scope, identity, max_requests, window_seconds)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Rate limiter: Redis op failed (%s).", type(e).__name__)
            if IS_PRODUCTION and REDIS_REQUIRED_IN_PRODUCTION:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Rate limiting backend unavailable.",
                    headers={"Retry-After": str(window_seconds)},
                )
            # local/dev: degrade to the in-memory fallback for this request.

    return mem_fallback.is_rate_limited(f"{scope}:{identity}")


# Deterministic per-endpoint scope: each rate_limit_dependency(...) call site
# gets its own bucket (mirrors "one in-memory limiter instance per endpoint"),
# so endpoints with identical limits do NOT share a bucket, and there is never
# one global bucket. Definition order is deterministic across identical
# deployments, keeping the scope stable across processes.
_scope_counter = 0
_scope_lock = threading.Lock()


def _next_scope() -> str:
    global _scope_counter
    with _scope_lock:
        _scope_counter += 1
        return f"ep{_scope_counter}"


def rate_limit_dependency(max_requests: int = 30, window_seconds: int = 60,
                          scope: Optional[str] = None):
    """
    Factory creating a FastAPI dependency for rate limiting.
    Example: Depends(rate_limit_dependency(max_requests=10, window_seconds=60))

    The public signature is unchanged; an OPTIONAL `scope` may be passed to pin
    a stable, human-readable bucket name (recommended for maximum cross-process
    robustness). The limiter internally chooses Redis or the in-memory fallback.
    """
    bucket = scope or _next_scope()
    # Per-instance in-memory limiter preserved as the local fallback.
    limiter = SlidingWindowRateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    async def _check_rate_limit(request: Request):
        if _is_rate_limited(bucket, request, max_requests, window_seconds, limiter):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds.",
                headers={"Retry-After": str(window_seconds)},
            )
        return True

    return _check_rate_limit


# ─── Durable security cooldowns (STEP 7) ────────────────────
# Shared across instances via Redis TTL keys; falls back to a caller-owned
# in-memory mirror dict. Cooldowns NEVER fail closed — an infra outage must not
# block a legitimate emergency (SOS) trigger.
def _cooldown_key(ctype: str, identity: str) -> str:
    return f"{_CD_NS}:{ctype}:{identity}"


def cooldown_remaining(ctype: str, identity: str, cooldown_seconds: int,
                       mirror: Dict[str, float]) -> int:
    """Seconds remaining on a cooldown (0 = not in cooldown). Never raises."""
    mode, client = _resolve_backend()
    if mode == "redis":
        try:
            ttl_ms = client.pttl(_cooldown_key(ctype, identity))
            if ttl_ms is not None and ttl_ms > 0:
                return int((ttl_ms + 999) // 1000)
            if ttl_ms == -1:  # key exists without expiry (shouldn't happen)
                return int(cooldown_seconds)
            return 0  # -2 => no key
        except Exception as e:
            logger.warning("Cooldown backend read failed (%s); using in-memory mirror.",
                           type(e).__name__)
            # fall through to mirror — never block an emergency on infra error
    last = mirror.get(identity, 0.0)
    remaining = int(cooldown_seconds - (time.time() - last))
    return remaining if remaining > 0 else 0


def cooldown_set(ctype: str, identity: str, cooldown_seconds: int,
                 mirror: Dict[str, float]) -> None:
    """Arm a cooldown for `identity`. Writes Redis (when live) AND the mirror."""
    mode, client = _resolve_backend()
    if mode == "redis":
        try:
            client.set(_cooldown_key(ctype, identity), "1",
                       px=int(cooldown_seconds * 1000))
        except Exception as e:
            logger.warning("Cooldown backend write failed (%s); using in-memory mirror.",
                           type(e).__name__)
    # Always mirror in-memory so single-process fallback and tests keep working.
    mirror[identity] = time.time()
