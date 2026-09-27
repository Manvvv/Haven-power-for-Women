"""Audit logging service — request-context aware and tamper-evident.

P2-1 hardening. This module keeps the SAME public entry point (`log_audit`)
that the rest of HAVEN already calls, so no caller is forced to change. New
capabilities are additive and optional:

  * Real client IP + user-agent are captured when a Request (or WebSocket) is
    passed, using the application's EXISTING trusted IP handling
    (`rate_limiter.get_client_ip`) rather than a new proxy scheme.
  * Every new record is linked into a SHA-256 hash chain
    (`event_hash = SHA256(previous_hash + canonical_event_json)`) so that any
    later edit to a record's content is detectable.

TAMPER EVIDENCE, NOT WORM: application-level hash chaining detects tampering of
individual records; it does NOT make a normal MongoDB collection immutable. A
privileged database administrator could recompute and rewrite the entire chain.
For true immutability, a WORM/append-only backend (e.g. Atlas Online Archive,
an external append-only log, or a signed external anchor) would be required —
see the P2-1 report. The hash chain never includes secrets, tokens, keys, or
raw sensitive payloads.
"""
import time
import json
import hashlib
import secrets
import logging
from datetime import datetime

logger = logging.getLogger("haven_backend")

# Genesis / empty-chain sentinel (64 hex chars, same width as a sha256 digest).
GENESIS_HASH = "0" * 64

# The ONLY fields that participate in the tamper-evidence hash. These are
# metadata fields — never tokens, passwords, keys, or raw sensitive payloads.
_HASH_FIELDS = (
    "audit_id", "actor_id", "role", "action", "case_id",
    "result", "reason", "ip_address", "user_agent", "metadata", "timestamp",
)


def _canonical_json(doc: dict) -> str:
    """Deterministic serialization of the hash-relevant fields only.

    sort_keys + fixed separators + str() fallback make this reproducible across
    processes so the same logical event always yields the same digest.
    """
    core = {k: doc.get(k) for k in _HASH_FIELDS}
    return json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(doc: dict, previous_hash: str = GENESIS_HASH) -> str:
    """event_hash = SHA256(previous_hash + canonical_event_json)."""
    prev = previous_hash or GENESIS_HASH
    payload = prev + _canonical_json(doc)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _latest_previous_hash(collection) -> str:
    """Best-effort previous hash: the most recent chained record's event_hash.

    Concurrency limitation: two simultaneous inserts can read the same previous
    hash and fork the chain. HAVEN's backend is effectively single-instance and
    uses synchronous pymongo, so this is acceptable for tamper EVIDENCE; it is
    documented in the report and is not claimed to be a strong global ledger.
    """
    try:
        last = collection.find_one(
            {"event_hash": {"$exists": True}},
            sort=[("timestamp", -1)],
            projection={"_id": 0, "event_hash": 1},
        )
        if last and last.get("event_hash"):
            return last["event_hash"]
    except Exception:
        # Never let chain bookkeeping break the actual audit write.
        pass
    return GENESIS_HASH


def _extract_ip(request) -> str:
    """Resolve the client IP using the app's EXISTING trusted handling.

    Reuses rate_limiter.get_client_ip (which honors the app's established
    X-Forwarded-For assumption, taking the first hop, else the direct peer).
    Works for both Starlette Request and WebSocket (both expose .headers/.client).
    """
    if request is None:
        return ""
    try:
        from rate_limiter import get_client_ip
        return get_client_ip(request) or ""
    except Exception:
        try:
            return request.client.host if getattr(request, "client", None) else ""
        except Exception:
            return ""


def _extract_user_agent(request) -> str:
    if request is None:
        return ""
    try:
        return (request.headers.get("user-agent") or "")[:256]
    except Exception:
        return ""


def log_audit(actor_id, role, action, case_id=None, result='success',
              reason='', ip='', metadata=None, request=None, user_agent=None):
    """Record an audit log entry (request-context aware, tamper-evident).

    Backward compatible: every existing positional/keyword call still works.
    New optional params:
      * request      — a Request or WebSocket; if given (and ip not supplied),
                       the real client IP + user-agent are captured.
      * user_agent   — explicit override; otherwise derived from request.

    NEVER pass tokens, passwords, JWT contents, encryption keys, full SOS/GPS
    payloads, or raw sensitive query text in `metadata` — use ids/hashes.
    """
    from services.db import audit_logs
    collection = audit_logs()
    if collection is None:
        return None

    # Request-derived context never overrides an explicitly supplied ip.
    if not ip and request is not None:
        ip = _extract_ip(request)
    if user_agent is None:
        user_agent = _extract_user_agent(request)

    doc = {
        'audit_id': f'AUDIT-{int(time.time())}-{secrets.token_hex(4)}',
        'actor_id': actor_id,
        'role': role,
        'action': action,
        'case_id': case_id,
        'result': result,
        'reason': reason,
        'ip_address': ip or '',
        'user_agent': user_agent or '',
        'metadata': metadata or {},
        'timestamp': datetime.utcnow(),
    }

    # Tamper-evidence hash chain (application level — see module docstring).
    previous_hash = _latest_previous_hash(collection)
    doc['previous_hash'] = previous_hash
    doc['event_hash'] = compute_event_hash(doc, previous_hash)

    collection.insert_one(doc)
    return doc['audit_id']


def verify_audit_chain(records):
    """Verify a time-ordered iterable of audit records' hash chain.

    Backward compatible: legacy records without `event_hash` (pre-P2-1) are
    treated as un-chained and skipped rather than failing verification.

    Returns (ok: bool, first_bad_audit_id: Optional[str]).
      * A record whose recomputed hash differs from its stored `event_hash`
        (i.e. its canonical content was modified) fails verification.
      * A broken link (a chained record whose `previous_hash` does not match the
        prior chained record's `event_hash`) also fails.
    """
    prev_hash = None
    for doc in records:
        if not doc.get("event_hash"):
            continue  # legacy / un-chained record
        stored_prev = doc.get("previous_hash") or GENESIS_HASH
        expected = compute_event_hash(doc, stored_prev)
        if expected != doc["event_hash"]:
            return False, doc.get("audit_id")
        if prev_hash is not None and stored_prev != prev_hash:
            return False, doc.get("audit_id")
        prev_hash = doc["event_hash"]
    return True, None
