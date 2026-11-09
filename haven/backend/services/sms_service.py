"""
HAVEN SMS Notification Service.

Credential-gated: does nothing when TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
TWILIO_FROM_NUMBER are not set. Returns honest per-recipient statuses.

Status values:
    NOT_CONFIGURED   — Twilio credentials absent; SMS was not attempted
    QUEUED           — queued to Twilio API (async)
    SENT_TO_PROVIDER — Twilio accepted the message synchronously
    FAILED           — Twilio returned an error
"""
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("haven_backend")

# ─── Status constants ────────────────────────────────────────────────────────

STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_QUEUED = "QUEUED"
STATUS_SENT_TO_PROVIDER = "SENT_TO_PROVIDER"
STATUS_FAILED = "FAILED"


# ─── Result model ────────────────────────────────────────────────────────────

@dataclass
class ContactNotificationResult:
    """Per-recipient notification outcome.

    `phone` is intentionally kept out of the public response; it is used only
    internally for dispatch and is logged only as a masked suffix.
    """
    contact_id: str
    name: str
    phone: str          # full number — NEVER log or return to clients
    status: str         # one of the STATUS_* constants above
    error_message: Optional[str] = None

    def to_safe_dict(self) -> dict:
        """Return a client-safe dict — phone number omitted."""
        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "status": self.status,
        }


# ─── Credential loading ──────────────────────────────────────────────────────

def _load_credentials():
    """Read Twilio credentials from environment. Returns (sid, token, from) or None."""
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_num = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    if sid and token and from_num:
        return sid, token, from_num
    return None


# ─── Phone masking helper ────────────────────────────────────────────────────

def _mask_phone(phone: str) -> str:
    """Return only the last 4 digits preceded by asterisks for safe logging."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) >= 4:
        return f"***{digits[-4:]}"
    return "****"


# ─── Twilio dispatch (library or requests fallback) ──────────────────────────

def _send_via_twilio_library(sid: str, token: str, from_num: str, to: str, body: str) -> str:
    """Send via the official twilio package. Returns a status string."""
    from twilio.rest import Client  # guarded import — only called when configured
    client = Client(sid, token)
    message = client.messages.create(to=to, from_=from_num, body=body)
    # Twilio statuses: queued, sending, sent, delivered, failed, …
    tw_status = (message.status or "").lower()
    if tw_status in ("queued", "sending"):
        return STATUS_QUEUED
    if tw_status in ("sent", "delivered"):
        return STATUS_SENT_TO_PROVIDER
    # Any other status (failed, undelivered, etc.)
    return STATUS_FAILED


def _send_via_requests(sid: str, token: str, from_num: str, to: str, body: str) -> str:
    """Fallback: call Twilio REST API directly without the SDK package."""
    import requests  # stdlib-adjacent; always available in CPython
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    resp = requests.post(
        url,
        data={"From": from_num, "To": to, "Body": body},
        auth=(sid, token),
        timeout=10,
    )
    if resp.status_code in (200, 201):
        tw_status = (resp.json().get("status") or "").lower()
        if tw_status in ("queued", "sending"):
            return STATUS_QUEUED
        return STATUS_SENT_TO_PROVIDER
    return STATUS_FAILED


def _dispatch_sms(sid: str, token: str, from_num: str, to: str, body: str) -> str:
    """Try twilio library first, fall back to requests."""
    try:
        return _send_via_twilio_library(sid, token, from_num, to, body)
    except ImportError:
        logger.debug("sms_service: twilio package not installed, falling back to requests")
        return _send_via_requests(sid, token, from_num, to, body)


# ─── Public API ──────────────────────────────────────────────────────────────

def notify_trusted_contacts(
    contacts: List[dict],
    case_id: str,
    message: str,
) -> List[ContactNotificationResult]:
    """Send SMS notifications to a list of trusted contacts.

    Parameters
    ----------
    contacts:
        Each dict must have at least ``contact_id``, ``name``, and ``phone``
        keys (matching the ``trusted_contacts`` collection schema).
    case_id:
        The HAVEN case ID, embedded in audit logs only.
    message:
        The alert text to send. Must be plain text (no HTML).

    Returns
    -------
    List[ContactNotificationResult]
        One result per contact.  Never raises; all errors surface as FAILED.

    Security
    --------
    - Phone numbers are NEVER written to log output in full — only the last
      4 digits are logged (``***XXXX`` pattern).
    - Twilio credentials are read from the environment on every call so a
      credential rotation does not require a restart.
    """
    results: List[ContactNotificationResult] = []
    credentials = _load_credentials()

    for contact in contacts:
        cid = str(contact.get("contact_id", ""))
        name = str(contact.get("name", "Contact"))
        phone = str(contact.get("phone", "")).strip()

        if not credentials:
            results.append(ContactNotificationResult(
                contact_id=cid,
                name=name,
                phone=phone,
                status=STATUS_NOT_CONFIGURED,
            ))
            continue

        if not phone:
            results.append(ContactNotificationResult(
                contact_id=cid,
                name=name,
                phone="",
                status=STATUS_FAILED,
                error_message="No phone number on record for this contact",
            ))
            continue

        sid, token, from_num = credentials
        masked = _mask_phone(phone)
        try:
            sms_status = _dispatch_sms(sid, token, from_num, phone, message)
            logger.info(
                "sms_service: case=%s contact=%s phone=%s status=%s",
                case_id, cid, masked, sms_status,
            )
            results.append(ContactNotificationResult(
                contact_id=cid,
                name=name,
                phone=phone,
                status=sms_status,
            ))
        except Exception as exc:
            logger.warning(
                "sms_service: FAILED case=%s contact=%s phone=%s err=%s",
                case_id, cid, masked, type(exc).__name__,
            )
            results.append(ContactNotificationResult(
                contact_id=cid,
                name=name,
                phone=phone,
                status=STATUS_FAILED,
                error_message=type(exc).__name__,
            ))

    return results
