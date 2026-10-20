"""Web Push delivery for responder emergency offers (VAPID via pywebpush).

HONESTY CONTRACT
  Creating a dispatch offer does NOT mean a phone received anything. This module
  reports exactly one of the following per attempt, and never upgrades a status
  without evidence:

    NOT_CONFIGURED         VAPID keys/subject or the pywebpush library are missing.
    SUBSCRIPTION_REQUIRED  The responder has no registered push subscription.
    PERMISSION_DENIED      The browser denied notification permission (client-reported).
    SEND_FAILED            The push service rejected or could not be reached (safe reason).
    SEND_ATTEMPTED         The request was handed to the push service with HTTP 2xx.
    DELIVERED              Reserved. Standard Web Push returns NO delivery receipt to
                           the server, so this status is never produced here.

  Push is an ENHANCEMENT. An in-app offer is valid regardless of the push outcome,
  so a failure here never blocks the dispatch, the wave, or accept/decline.

SECRETS
  VAPID_PRIVATE_KEY is read from the environment, used only to sign the request, and
  never returned to any client, logged, or included in an exception message. Only
  VAPID_PUBLIC_KEY is served (to the browser, for PushManager.subscribe).

ENV (names only)
  VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT (must be mailto: or https: URL)

PAYLOAD (lock-screen safe)
  Title/body contain no victim PII, no incident location and no case id. The opaque
  dispatch id is included so the service worker can open the correct offer after
  authentication.
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("haven_backend")

VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
VAPID_SUBJECT = (os.getenv("VAPID_SUBJECT") or "").strip()

STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
STATUS_PERMISSION_DENIED = "PERMISSION_DENIED"
STATUS_SEND_FAILED = "SEND_FAILED"
STATUS_SEND_ATTEMPTED = "SEND_ATTEMPTED"
STATUS_DELIVERED = "DELIVERED"  # reserved; never produced (see contract)

_SUBJECT_RE = re.compile(r"^(mailto:[^\s@]+@[^\s@]+|https://[^\s]+)$")


def _pywebpush():
    try:
        import pywebpush  # type: ignore
        return pywebpush
    except Exception:
        return None


def is_configured() -> bool:
    """True only when the library AND a complete, well-formed VAPID set are present."""
    if _pywebpush() is None:
        return False
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return False
    return bool(_SUBJECT_RE.match(VAPID_SUBJECT))


def public_key_for_client() -> Optional[str]:
    """The ONLY VAPID value that may reach the browser. None when not configured."""
    return VAPID_PUBLIC_KEY if is_configured() else None


def endpoint_hash(endpoint: str) -> str:
    """Stable, non-reversible key for a push endpoint (used for dedupe/delete)."""
    return hashlib.sha256((endpoint or "").encode("utf-8")).hexdigest()


def validate_subscription(sub: Any) -> Optional[Dict[str, Any]]:
    """Return a clean {endpoint, keys:{p256dh,auth}} or None. Rejects anything else."""
    if not isinstance(sub, dict):
        return None
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 2048:
        return None
    if not isinstance(keys, dict):
        return None
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (isinstance(p256dh, str) and isinstance(auth, str)):
        return None
    if not (0 < len(p256dh) <= 256 and 0 < len(auth) <= 128):
        return None
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def build_payload(dispatch_id: str, priority: str, distance_m: Optional[float],
                  expires_at: Optional[datetime]) -> Dict[str, Any]:
    """Lock-screen-safe notification body. No PII, no location, no case id."""
    if distance_m is not None:
        dist_txt = f"{distance_m / 1000:.1f} km" if distance_m >= 1000 else f"{int(distance_m)} m"
    else:
        dist_txt = "unknown"
    expires_txt = ""
    if isinstance(expires_at, datetime):
        remaining = max(0, int((expires_at - datetime.utcnow()).total_seconds()))
        expires_txt = f"{remaining // 60:02d}:{remaining % 60:02d}"
    return {
        "title": "HAVEN EMERGENCY REQUEST",
        "body": f"Priority: {priority}. A verified emergency response is required. "
                f"Distance: {dist_txt}. Offer expires in: {expires_txt or 'soon'}.",
        "tag": f"haven-offer-{dispatch_id}",
        "dispatch_id": dispatch_id,
        "url": f"/responder?offer={dispatch_id}",
        "requireInteraction": True,
    }


def send(subscription: Dict[str, Any], payload: Dict[str, Any], ttl_seconds: int = 60) -> Dict[str, Any]:
    """Send one Web Push. Returns {status, reason}. Never raises.

    status is one of NOT_CONFIGURED / SEND_FAILED / SEND_ATTEMPTED. The reason is a
    short, secret-free code.
    """
    pw = _pywebpush()
    if pw is None or not is_configured():
        return {"status": STATUS_NOT_CONFIGURED, "reason": "vapid_not_configured"}
    clean = validate_subscription(subscription)
    if clean is None:
        return {"status": STATUS_SUBSCRIPTION_REQUIRED, "reason": "invalid_subscription"}
    try:
        resp = pw.webpush(
            subscription_info=clean,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=int(ttl_seconds),
            timeout=5,
        )
        code = getattr(resp, "status_code", None)
        if code is not None and 200 <= int(code) < 300:
            # The push service accepted the request. This is NOT device delivery.
            return {"status": STATUS_SEND_ATTEMPTED, "reason": f"push_service_{code}"}
        return {"status": STATUS_SEND_FAILED, "reason": f"push_service_{code}"}
    except Exception as exc:  # noqa: BLE001 - must never leak endpoint/keys
        # Subscription gone (404/410) is the expected lifecycle; report it as a failure.
        code = getattr(getattr(exc, "response", None), "status_code", None)
        reason = f"push_service_{code}" if code else type(exc).__name__
        logger.warning("web push send failed: %s", reason)
        return {"status": STATUS_SEND_FAILED, "reason": reason}
