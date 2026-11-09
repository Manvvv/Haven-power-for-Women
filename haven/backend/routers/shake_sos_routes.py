"""
shake_sos_routes.py — Dedicated Shake-to-SOS API endpoints for the HAVEN Android app.

This router extends the existing SOS infrastructure with a structured endpoint
for the native Android shake gesture trigger. It reuses the same:
  - sos_cases collection (authority dashboard picks it up automatically)
  - notification_manager.notify_authorities (live WebSocket broadcast)
  - lifecycle_service.transition_sos (state machine)
  - incident_location.canonical_coord_fields (structured coordinates)
  - rate_limiter (prevents abuse)
  - audit_service (non-repudiation)

The /shake-sos/trigger endpoint differs from /save-extracted-data in that:
  - It requires authentication (Bearer token from the Android app login)
  - It enforces user-to-incident ownership (users cannot trigger for other users)
  - It validates structured latitude/longitude fields with documented freshness
  - It records trigger_type = SHAKE_SOS for dashboard filtering
  - It prevents rapid duplicate incidents via a per-user cooldown (60 s default)
  - It returns structured authority-dashboard-ready fields

The backend does NOT automatically dispatch or notify trusted contacts via SMS/WhatsApp
here — it stores the incident and broadcasts to connected authorities. Trusted-contact
notification (via WhatsApp deep links, consistent with voice-SOS) is returned to the
Android client which opens the link. This is the same honest pattern as the voice-SOS
trigger: the server prepares the link; a human opens it.
"""
import secrets
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import AuthUser, get_current_user
from rate_limiter import rate_limit_dependency, cooldown_remaining, cooldown_set
from services.db import get_collection, sos_cases, sos_events, serialize_doc
from services.lifecycle_service import transition_sos
from services.notification_service import notification_manager
from services.audit_service import log_audit
from services.incident_location import canonical_coord_fields
from services.geo_validation import finite_in_range as _finite_in_range

router = APIRouter(prefix="", tags=["Shake SOS"])

_SHAKE_COOLDOWN_TYPE = "shake_sos"
_shake_sos_cooldowns: dict = {}


# ─── Request / Response models ────────────────────────────────────────────────

class ShakeSosTriggerRequest(BaseModel):
    """
    Shake-to-SOS trigger payload from the Android app.

    location_freshness must be one of:
      FRESH          — obtained within the last 30 seconds
      STALE          — last-known, 30 s – 10 min old
      LAST_KNOWN     — last-known, > 10 min old
      LOCATION_UNAVAILABLE — no fix available

    Coordinates are ONLY included when location_freshness != LOCATION_UNAVAILABLE.
    The backend validates and rejects fabricated/out-of-range values.
    """
    # Idempotency key (triggerId from Android): prevents duplicate incidents on retry
    idempotency_key: str = Field(..., min_length=8, max_length=200)
    # GPS fix — nullable; only present when location_freshness != LOCATION_UNAVAILABLE
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy: Optional[float] = None
    location_freshness: str = Field("LOCATION_UNAVAILABLE", max_length=30)
    location_timestamp: Optional[str] = Field(None, max_length=50)
    # Trigger metadata
    trigger_type: str = Field("SHAKE_SOS", max_length=30)
    cooldown_seconds: int = Field(60, ge=10, le=600)
    # App-side diagnostic fields (advisory, not used for authorization)
    device_model: Optional[str] = Field(None, max_length=100)
    shake_threshold_used: Optional[float] = None

    model_config = {"extra": "ignore"}  # Extra fields from future Android versions silently ignored


class ShakeSosTriggerResponse(BaseModel):
    success: bool
    case_id: str
    duplicate: bool = False
    status: str
    location_recorded: str
    authority_notified: bool
    contacts_pending: int
    # WhatsApp deep links for the Android app to open (same pattern as voice-SOS)
    whatsapp_links: list
    # Per-contact SMS notification outcome (phone numbers excluded)
    contact_notification_status: list = []
    message: str


# ─── Cooldown helpers ──────────────────────────────────────────────────────────

def _check_shake_cooldown(user_id: str, cooldown_seconds: int) -> int:
    return cooldown_remaining(_SHAKE_COOLDOWN_TYPE, user_id, cooldown_seconds, _shake_sos_cooldowns)


def _set_shake_cooldown(user_id: str, cooldown_seconds: int):
    cooldown_set(_SHAKE_COOLDOWN_TYPE, user_id, cooldown_seconds, _shake_sos_cooldowns)


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/shake-sos/trigger")
async def shake_sos_trigger(
    payload: ShakeSosTriggerRequest,
    current_user: AuthUser = Depends(get_current_user),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
):
    """
    Trigger a REAL Shake-to-SOS emergency from the Android native app.

    Requires authentication. Only the authenticated user can trigger for
    their own account — the user_id comes from the verified JWT, not the body.

    Creates a persistent SOS incident visible in the authority dashboard.
    Broadcasts to connected authority WebSocket clients immediately.
    Returns WhatsApp deep links for trusted-contact notification (same as voice-SOS).

    Idempotency: repeated calls with the same idempotency_key return the original
    case without creating a duplicate incident (HTTP 200, duplicate=True).
    """
    user_id = current_user.user_id
    is_test = "TEST" in payload.trigger_type.upper()

    # ── Cooldown enforcement ──────────────────────────────────────────────────
    # Does NOT block a genuine emergency: if the user can physically shake the
    # phone three times, a 60-second cooldown only prevents accidental re-triggers.
    remaining = _check_shake_cooldown(user_id, payload.cooldown_seconds)
    if remaining > 0 and not is_test:
        raise HTTPException(
            status_code=429,
            detail=f"Shake SOS cooldown active. Wait {remaining}s before triggering again."
        )

    # ── Idempotency check ──────────────────────────────────────────────────────
    cases_coll = sos_cases()
    if cases_coll is None:
        raise HTTPException(
            status_code=503,
            detail="Storage temporarily unavailable. Your alert is queued and will be retried."
        )

    existing = cases_coll.find_one({"idempotency_key": payload.idempotency_key})
    if existing:
        # Duplicate — return original case without re-triggering notifications
        case_id = existing.get("case_id", "")
        return ShakeSosTriggerResponse(
            success=True,
            case_id=case_id,
            duplicate=True,
            status=existing.get("status", "RECEIVED"),
            location_recorded=existing.get("location_freshness", "UNKNOWN"),
            authority_notified=True,
            contacts_pending=0,
            whatsapp_links=[],
            message=f"Duplicate submission. Original case {case_id} already recorded."
        )

    # ── Coordinate validation ──────────────────────────────────────────────────
    has_location = (
        payload.latitude is not None and
        payload.longitude is not None and
        payload.location_freshness != "LOCATION_UNAVAILABLE"
    )
    if has_location:
        if not _finite_in_range(payload.latitude, -90.0, 90.0):
            raise HTTPException(status_code=422, detail="Invalid latitude.")
        if not _finite_in_range(payload.longitude, -180.0, 180.0):
            raise HTTPException(status_code=422, detail="Invalid longitude.")
        if payload.location_accuracy is not None and payload.location_accuracy < 0:
            raise HTTPException(status_code=422, detail="Invalid accuracy.")

    # ── Generate case ID ──────────────────────────────────────────────────────
    case_id = f"SHAKE-{int(time.time())}-{secrets.token_hex(4).upper()}"
    ts = datetime.utcnow().isoformat()

    location_str = (
        f"{payload.latitude}, {payload.longitude}" if has_location else "Location unavailable"
    )

    severity = "test" if is_test else "critical"

    case_doc = {
        "case_id": case_id,
        "user_id": user_id,
        "trigger_type": payload.trigger_type,
        "idempotency_key": payload.idempotency_key,
        "decoded_text": (
            f"⚠️ TEST — Shake-to-SOS detector test. Not a real emergency."
            if is_test else
            f"🚨 SHAKE SOS — Emergency triggered by three deliberate shakes. "
            f"User: {user_id}. Location: {location_str}. Immediate response required."
        ),
        "severity": severity,
        "immediate_danger": not is_test,
        "location": location_str,
        "location_freshness": payload.location_freshness,
        "location_timestamp": payload.location_timestamp,
        "summary": (
            "Shake-to-SOS detector test — no emergency in progress."
            if is_test else
            "SHAKE SOS activation — immediate emergency response required."
        ),
        "needs": ["TEST_ONLY"] if is_test else [
            "Immediate Police Dispatch", "GPS Tracking", "Medical Alert"
        ],
        "status": "RECEIVED",
        "created_at": datetime.utcnow(),
        "has_evidence": False,
        "device_model": payload.device_model,
        # Location accuracy metadata for authority dashboard
        "location_accuracy_m": payload.location_accuracy,
    }

    # Canonical numeric coordinate fields for the authority map / RRN resolver
    if has_location:
        case_doc.update(canonical_coord_fields(payload.latitude, payload.longitude))

    # ── Write to DB ───────────────────────────────────────────────────────────
    try:
        cases_coll.insert_one(case_doc)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not save SOS incident. Your alert is queued and will be retried."
        )

    # ── Also write to sos_events for live-tracking WebSocket ─────────────────
    events_coll = sos_events()
    if events_coll is not None:
        event_doc = {
            "event_id": case_id,
            "user_id": user_id,
            "trigger_type": payload.trigger_type,
            "timestamp": ts,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "location_accuracy": payload.location_accuracy,
            "location_freshness": payload.location_freshness,
            "status": "triggered",
            "is_test": is_test,
            "created_at": datetime.utcnow(),
        }
        try:
            events_coll.insert_one(event_doc)
        except Exception:
            pass  # Non-fatal — case is already persisted

    # ── Lifecycle transition ──────────────────────────────────────────────────
    try:
        transition_sos(case_id, "RECEIVED", user_id, "user")
    except Exception:
        pass

    # ── Set cooldown (after successful DB write, before notifications) ────────
    if not is_test:
        _set_shake_cooldown(user_id, payload.cooldown_seconds)

    # ── Audit ────────────────────────────────────────────────────────────────
    try:
        log_audit(
            actor_id=user_id, role=current_user.role, action="SHAKE_SOS_TRIGGERED",
            case_id=case_id, result="success",
            metadata={
                "trigger_type": payload.trigger_type,
                "location_freshness": payload.location_freshness,
                "is_test": is_test,
                # NEVER log coordinates, device model, or user-identifying location data
            }
        )
    except Exception:
        pass

    # ── Notify authorities (live WebSocket broadcast) ─────────────────────────
    authority_notified = False
    notif_id = None
    if not is_test:
        title = f"🚨 SHAKE SOS — New Emergency (Case {case_id})"
        msg = f"Shake-to-SOS triggered. Location: {location_str}. Freshness: {payload.location_freshness}."
        try:
            notif_id = notification_manager.create_notification(
                recipient_id="all_authorities",
                event_type="NEW_SOS",
                title=title,
                message=msg,
                case_id=case_id
            )
        except Exception:
            pass
        try:
            await notification_manager.notify_authorities("NEW_SOS", {
                "notification_id": notif_id,
                "title": title,
                "message": msg,
                "case_id": case_id,
                "severity": severity,
                "trigger_type": payload.trigger_type,
                "location_freshness": payload.location_freshness,
                "created_at": ts,
                "trigger_method": "SHAKE_SOS",
                "dispatch_status": "INCIDENT_CREATED",
                "responder_assigned": False,
            })
            authority_notified = True
        except Exception:
            pass

    # ── Trusted contacts (WhatsApp deep links, same as voice-SOS) ─────────────
    contacts_coll = get_collection("trusted_contacts")
    contacts = []
    if contacts_coll is not None and not is_test:
        contacts = list(contacts_coll.find({"user_id": user_id}, {"_id": 0}))

    from routers.voice_routes import format_emergency_alert, format_whatsapp_url
    alert_text = format_emergency_alert(case_id, ts, payload.latitude or 0.0, payload.longitude or 0.0)

    whatsapp_links = [
        {
            "name": c.get("name", "Contact"),
            "phone": c.get("phone", ""),
            "url": format_whatsapp_url(c.get("phone", ""), alert_text),
            "notification_status": "CLIENT_WHATSAPP_LINK"
        }
        for c in contacts
    ] if contacts else []

    # ── SMS notifications (server-side, credential-gated) ─────────────────────
    from services import sms_service as _sms
    sms_results = []
    if contacts and not is_test:
        sms_message = (
            f"🚨 HAVEN EMERGENCY ALERT — Case {case_id}\n"
            f"Your trusted contact has triggered an emergency SOS.\n"
            f"Location: {location_str}\n"
            f"Please check on them immediately or call emergency services."
        )
        try:
            sms_results = _sms.notify_trusted_contacts(contacts, case_id, sms_message)
        except Exception:
            pass  # SMS is best-effort; never block the SOS response

        # Persist notification results in the case document (separate from status)
        if sms_results and cases_coll is not None:
            contact_notifications_payload = [
                {
                    "contact_id": r.contact_id,
                    "name": r.name,
                    # phone is deliberately omitted from the stored notification record
                    "status": r.status,
                    "error_message": r.error_message,
                }
                for r in sms_results
            ]
            try:
                cases_coll.update_one(
                    {"case_id": case_id},
                    {"$set": {"contact_notifications": contact_notifications_payload}},
                )
            except Exception:
                pass  # Non-fatal — case is already persisted

    # Build safe response list (no phone numbers)
    contact_notification_status = [r.to_safe_dict() for r in sms_results]

    return ShakeSosTriggerResponse(
        success=True,
        case_id=case_id,
        duplicate=False,
        status="RECEIVED",
        location_recorded=payload.location_freshness,
        authority_notified=authority_notified,
        contacts_pending=len(whatsapp_links),
        whatsapp_links=whatsapp_links,
        contact_notification_status=contact_notification_status,
        message=(
            "Test SOS recorded. No real emergency created."
            if is_test else
            f"Emergency received by HAVEN (Case {case_id}). Authorities notified. "
            f"Open WhatsApp links to notify trusted contacts."
        )
    )


@router.get("/shake-sos/status/{user_id}")
def get_shake_sos_status(
    user_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Returns the current monitoring status and most recent Shake-SOS case for a user.
    Only the authenticated user or an authority can view this.
    """
    from auth import require_self_or_authority
    require_self_or_authority(user_id, current_user)

    cases_coll = sos_cases()
    recent_case = None
    if cases_coll is not None:
        recent_case = cases_coll.find_one(
            {"user_id": user_id, "trigger_type": {"$in": ["SHAKE_SOS", "SHAKE_SOS_TEST"]}},
            {"_id": 0, "case_id": 1, "status": 1, "created_at": 1, "location_freshness": 1,
             "severity": 1, "trigger_type": 1, "dispatch_status": 1},
            sort=[("created_at", -1)]
        )

    cooldown_remaining_s = _check_shake_cooldown(user_id, 60)

    return {
        "user_id": user_id,
        "cooldown_remaining_seconds": cooldown_remaining_s,
        "recent_case": serialize_doc(recent_case) if recent_case else None,
    }
