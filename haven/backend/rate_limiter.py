"""
In-memory sliding window rate limiter for FastAPI endpoints.
Protects AI endpoints, voice triggers, and public APIs from DoS and quota abuse.
"""

import time
from typing import Dict, List, Optional
from fastapi import Request, HTTPException, status


class SlidingWindowRateLimiter:
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


def get_client_ip(request: Request) -> str:
    """Extract client IP handling reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_dependency(max_requests: int = 30, window_seconds: int = 60):
    """
    Factory creating a FastAPI dependency for rate limiting.
    Example: Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
    """
    limiter = SlidingWindowRateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    async def _check_rate_limit(request: Request):
        client_id = get_client_ip(request)
        # Check if auth header exists to rate limit per user
        auth = request.headers.get("Authorization")
        if auth:
            client_id = f"{client_id}:{auth[:20]}"

        if limiter.is_rate_limited(client_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds.",
                headers={"Retry-After": str(window_seconds)},
            )
        return True

    return _check_rate_limit
