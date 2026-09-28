import time
import secrets
import hmac
import re
import requests
from datetime import datetime
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, Body

from auth import (
    AuthUser,
    get_optional_user,
    get_current_user,
    require_self_or_authority,
    hash_safe_word_salted,
    verify_safe_word,
)
from models.schemas import VoiceSOSConfigModel, VoiceSOSTriggerModel, VoiceAnalyzeModel
from services.db import (
    voice_sos_config_collection,
    trusted_contacts_collection,
    sos_events_collection,
    sos_collection,
    serialize_doc,
)
from rate_limiter import rate_limit_dependency, cooldown_remaining, cooldown_set
from services.audit_service import log_audit
from services.contact_validation import (
    MAX_TRUSTED_CONTACTS,
    normalize_phone,
    valid_phone,
    valid_email,
)

router = APIRouter(prefix="", tags=["Voice SOS"])

# Durable cooldown tracker for voice triggers. Backed by the shared store
# (Redis TTL keys, namespaced haven:cooldown:voice_sos:<user_id>) when it is
# available, so cooldowns survive restarts and are enforced across every
# backend instance. This dict is the local-development mirror / fallback and is
# ALSO written on every set so single-process behavior is unchanged.
#
# Cooldowns intentionally NEVER fail closed: if the shared backend is
# unreachable, enforcement falls back to this mirror rather than blocking a
# legitimate emergency (SOS) trigger.
_voice_sos_cooldowns: Dict[str, float] = {}
_VOICE_COOLDOWN_TYPE = "voice_sos"


def cooldown_seconds_remaining(user_id: str, cooldown_seconds: int) -> int:
    """Seconds left on this user's voice cooldown (0 = free to trigger)."""
    return cooldown_remaining(_VOICE_COOLDOWN_TYPE, user_id, cooldown_seconds, _voice_sos_cooldowns)


def check_cooldown(user_id: str, cooldown_seconds: int) -> bool:
    """Returns True if within cooldown (should block)."""
    return cooldown_seconds_remaining(user_id, cooldown_seconds) > 0


def set_cooldown(user_id: str, cooldown_seconds: int = 60):
    # Per-user keying preserves emergency isolation: one user's cooldown never
    # blocks another user's SOS.
    cooldown_set(_VOICE_COOLDOWN_TYPE, user_id, cooldown_seconds, _voice_sos_cooldowns)


def format_emergency_alert(event_id: str, ts: str, lat: float, lng: float) -> str:
    # Build map link as plain text — it gets URL-encoded once by format_whatsapp_url's quote()
    # Do NOT pre-encode it here to avoid double-encoding
    if lat and lng:
        map_link = f"https://maps.google.com/?q={lat},{lng}"
        loc_str = f"{lat}, {lng}"
    else:
        map_link = "Location unavailable"
        loc_str = "Unknown"
    return (
        f"🚨 HAVEN EMERGENCY ALERT 🚨\n\n"
        f"A trusted contact has triggered an emergency SOS.\n\n"
        f"Time: {ts}\n"
        f"Location: {loc_str}\n"
        f"Map: {map_link}\n"
        f"SOS Event ID: {event_id}\n\n"
        f"Please respond immediately."
    )


def format_whatsapp_url(phone: str, text: str) -> str:
    """Build a WhatsApp direct-link URL with proper phone formatting and single encoding."""
    encoded_text = requests.utils.quote(text, safe='')
    if not phone:
        return f"https://api.whatsapp.com/send?text={encoded_text}"
    digits = re.sub(r'\D', '', phone)
    # Handle Indian 10-digit numbers without country code
    if len(digits) == 10 and digits[0] in ['6', '7', '8', '9']:
        digits = '91' + digits
    elif len(digits) == 11 and digits.startswith('0'):
        digits = '91' + digits[1:]
    if not digits:
        return f"https://api.whatsapp.com/send?text={encoded_text}"
    # WhatsApp requires + prefix on the phone parameter
    return f"https://api.whatsapp.com/send?phone=%2B{digits}&text={encoded_text}"


@router.post("/voice-sos/config")
def voice_sos_save_config(
    config: VoiceSOSConfigModel,
    current_user: AuthUser = Depends(get_current_user)
):
    """Create or update Voice SOS configuration. Hashes safe word with PBKDF2 salt.

    Requires authentication; the config always belongs to the verified caller
    (a body user_id is never trusted for write targeting).
    """
    if voice_sos_config_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    target_user_id = current_user.user_id

    existing = voice_sos_config_collection.find_one({"user_id": target_user_id})

    # A safe word is REQUIRED to create a config, but may be omitted when updating
    # an existing one (e.g. toggling `enabled` or editing contacts) — the stored
    # PBKDF2 hash+salt are then preserved instead of being overwritten, so a
    # settings-only save never silently clobbers the real safe word.
    new_safe_word = (config.safe_word or "").strip()
    if not new_safe_word and not (existing and existing.get("safe_word_hash")):
        raise HTTPException(
            status_code=400,
            detail="A safe word is required to set up Voice SOS.",
        )

    set_fields = {
        "user_id": target_user_id,
        "enabled": config.enabled,
        "cooldown_seconds": config.cooldown_seconds,
        "updated_at": datetime.utcnow(),
    }
    if new_safe_word:
        # Hash with PBKDF2 + per-record salt (unchanged security model).
        hash_result = hash_safe_word_salted(new_safe_word)
        set_fields["safe_word_hash"] = hash_result["hash"]
        set_fields["safe_word_salt"] = hash_result["salt"]

    voice_sos_config_collection.update_one(
        {"user_id": target_user_id},
        {"$set": set_fields, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )

    # Save trusted contacts
    if config.contacts and trusted_contacts_collection is not None:
        trusted_contacts_collection.delete_many({"user_id": target_user_id})
        for c in config.contacts:
            trusted_contacts_collection.insert_one({
                "user_id": target_user_id,
                "contact_id": f"CONTACT-{int(time.time())}-{secrets.token_hex(2)}",
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "priority": c.priority,
                "created_at": datetime.utcnow(),
            })

    return {"success": True, "message": "Voice SOS configuration securely saved"}


@router.get("/voice-sos/config/{user_id}")
def voice_sos_get_config(
    user_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get Voice SOS config. Never exposes the safe word hash or salt.

    Requires authentication; only the owner (or an authority/admin) may read.
    """
    require_self_or_authority(user_id, current_user)
    if voice_sos_config_collection is None:
        return {"configured": False}

    cfg = voice_sos_config_collection.find_one({"user_id": user_id}, {"_id": 0})
    if not cfg:
        return {"configured": False}

    contacts = []
    if trusted_contacts_collection is not None:
        contacts = list(trusted_contacts_collection.find(
            {"user_id": user_id}, {"_id": 0}
        ))

    return {
        "configured": True,
        "enabled": cfg.get("enabled", False),
        "has_safe_word": bool(cfg.get("safe_word_hash")),
        "cooldown_seconds": cfg.get("cooldown_seconds", 60),
        "contacts": [serialize_doc(c) for c in contacts],
        "updated_at": cfg.get("updated_at", "").isoformat() if hasattr(cfg.get("updated_at", ""), "isoformat") else "",
    }


@router.post("/voice-sos/trigger")
def voice_sos_trigger(
    trigger: VoiceSOSTriggerModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
):
    """
    Trigger a REAL Voice SOS emergency.
    Validates safe word with stored PBKDF2 salt, enforces cooldown and creates emergency record.
    """
    if voice_sos_config_collection is None or sos_events_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Emergency initiation may be anonymous (documented), but an AUTHENTICATED
    # caller can only ever trigger against their OWN config — a body user_id is
    # never used to target another authenticated user. The safe-word hash check
    # below is the authorization proof for the anonymous path.
    target_user_id = current_user.user_id if current_user else trigger.user_id

    cfg = voice_sos_config_collection.find_one({"user_id": target_user_id})
    if not cfg:
        raise HTTPException(status_code=404, detail="Voice SOS not configured")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="Voice SOS is disabled")

    # Validate safe word using stored salted hash
    stored_hash = cfg.get("safe_word_hash", "")
    stored_salt = cfg.get("safe_word_salt", "")

    matched = False
    if trigger.spoken_phrase and stored_salt:
        matched = verify_safe_word(trigger.spoken_phrase, stored_hash, stored_salt)
    elif trigger.hashed_safe_word:
        # Legacy/direct hash check fallback with constant-time comparison
        matched = hmac.compare_digest(trigger.hashed_safe_word, stored_hash)

    if not matched:
        raise HTTPException(status_code=403, detail="Safe word verification failed")

    # Check cooldown (durable across restarts / instances when Redis is live)
    cooldown = cfg.get("cooldown_seconds", 60)
    remaining = cooldown_seconds_remaining(target_user_id, cooldown)
    if remaining > 0:
        raise HTTPException(status_code=429, detail=f"Cooldown active. Wait {remaining}s")

    set_cooldown(target_user_id, cooldown)

    event_id = f"VSOS-{int(time.time())}-{secrets.token_hex(4)}"
    ts = trigger.timestamp or datetime.utcnow().isoformat()
    alert_message = format_emergency_alert(event_id, ts, trigger.latitude, trigger.longitude)

    contacts = []
    if trusted_contacts_collection is not None:
        contacts = list(trusted_contacts_collection.find(
            {"user_id": target_user_id}, {"_id": 0}
        ))

    contact_delivery = {c.get("name", "unknown"): "pending" for c in contacts}

    event_doc = {
        "event_id": event_id,
        "user_id": target_user_id,
        "trigger_type": "voice_code",
        "timestamp": ts,
        "latitude": trigger.latitude,
        "longitude": trigger.longitude,
        "location_accuracy": trigger.location_accuracy,
        "status": "triggered",
        "contact_delivery_status": contact_delivery,
        "is_test": False,
        "created_at": datetime.utcnow(),
    }
    # Attach optional voice-AI metadata if the client analysed the transcript first.
    # Only text/metadata is stored — never raw audio.
    if trigger.transcript or trigger.intent or trigger.severity or trigger.risk_score is not None:
        event_doc["voice_analysis"] = {
            "transcript": (trigger.transcript or "")[:2000],
            "intent": trigger.intent,
            "severity": trigger.severity,
            "risk_score": trigger.risk_score,
        }
    sos_events_collection.insert_one(event_doc)

    # Save to sos_cases so it appears in authority dashboard
    if sos_collection is not None:
        case_doc = {
            "case_id": event_id,
            "user_id": target_user_id,
            "trigger_type": "voice_sos",
            "decoded_text": f"🚨 EMERGENCY VOICE SOS TRIGGERED. Location: {trigger.latitude}, {trigger.longitude}",
            # Voice safe-word SOS is treated as critical by design; the AI severity
            # (if provided) is recorded separately for authority context, not used
            # to downgrade the response.
            "severity": "critical",
            "immediate_danger": True,
            "location": f"{trigger.latitude}, {trigger.longitude}" if trigger.latitude else "Unknown",
            "summary": "Voice SOS activation - immediate emergency response required",
            "needs": ["Immediate Police Dispatch", "GPS Tracking", "Medical Alert"],
            # Canonical lifecycle state (see lifecycle_service.SOS_STATES). A voice
            # SOS has been received by the system and is ready for authority triage,
            # so it enters the pipeline at RECEIVED — from which ACKNOWLEDGED /
            # IN_PROGRESS / RESOLVED are all valid. Previously wrote the
            # non-canonical "active", which broke transition/resolve (spurious 409).
            "status": "RECEIVED",
            "created_at": datetime.utcnow(),
            "has_evidence": False,
        }
        if trigger.transcript or trigger.intent or trigger.severity or trigger.risk_score is not None:
            case_doc["voice_analysis"] = {
                "transcript": (trigger.transcript or "")[:2000],
                "intent": trigger.intent,
                "ai_severity": trigger.severity,
                "risk_score": trigger.risk_score,
            }
        sos_collection.insert_one(case_doc)

    # Audit the emergency creation. Minimal, non-sensitive metadata only —
    # NEVER the safe word, transcript, contact numbers, or GPS coordinates.
    try:
        log_audit(
            actor_id=target_user_id, role="user", action="VOICE_SOS_CREATED",
            case_id=event_id, result="success",
            metadata={"event_id": event_id, "trigger_type": "voice_sos",
                      "contacts_prepared": len(contacts)},
        )
    except Exception:
        pass

    whatsapp_links = [
        {"name": c.get("name", "Contact"), "phone": c.get("phone", ""), "url": format_whatsapp_url(c.get("phone", ""), alert_message)}
        for c in contacts
    ] or [{"name": "Trusted Contact", "phone": "", "url": format_whatsapp_url("", alert_message)}]

    return {
        "success": True,
        "event_id": event_id,
        "status": "triggered",
        "alert_message": alert_message,
        # HONEST delivery state: the server does NOT auto-send anything here. It
        # prepares WhatsApp deep links the client/user must open, so contacts are
        # PENDING, not "notified". erss_auto_dispatched is False because no ERSS
        # (112) dispatch has actually been performed by this endpoint. Presenting
        # simulated behavior as real emergency action is forbidden by design.
        "contacts_notified": 0,
        "contacts_pending": len(contacts),
        "contact_delivery": "client_whatsapp_links",
        "whatsapp_links": whatsapp_links,
        "live_tracking_ws_url": f"/ws/track/{event_id}",
        "erss_auto_dispatched": False,
    }


@router.post("/voice-sos/analyze")
def voice_sos_analyze(
    body: VoiceAnalyzeModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Analyze a speech transcript: emergency intent + existing risk classifier.

    Decision-support ONLY — this endpoint never triggers an SOS. The frontend
    shows the result and a human confirms before calling /voice-sos/trigger.
    Reuses the existing risk-engine contract (no second severity model).
    """
    transcript = (body.transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript required")

    # 1) Emergency intent (swappable rule/LLM layer).
    from services.intent_service import detect_intent
    intent = detect_intent(transcript, recognition_confidence=body.recognition_confidence)

    # 2) Reuse the EXISTING risk classifier — do not create a second model.
    risk = None
    risk_available = True
    try:
        from services.risk_classifier import RiskClassifier
        risk = RiskClassifier().classify(transcript)
    except Exception as e:  # AI service unavailable — be honest, don't fake it.
        risk_available = False
        risk = {"error": "risk classifier unavailable", "detail": str(e)[:120]}

    # Optionally attach analysis to an existing case (no raw audio persisted).
    if body.case_id and sos_collection is not None:
        try:
            sos_collection.update_one(
                {"case_id": body.case_id},
                {"$set": {"voice_analysis": {
                    "transcript": transcript[:2000],
                    "intent": intent["intent"],
                    "intent_confidence": intent["confidence"],
                    "severity": (risk or {}).get("severity"),
                    "risk_score": (risk or {}).get("risk_score"),
                    "analyzed_at": datetime.utcnow(),
                }}},
            )
        except Exception:
            pass

    return {
        "transcript": transcript,
        "intent": intent,
        "risk": risk,
        "risk_available": risk_available,
        "needs_confirmation": intent.get("needs_confirmation", True) or not risk_available,
        "auto_action": False,  # analysis never auto-dispatches
    }


@router.post("/voice-sos/test")
def voice_sos_test(
    trigger: VoiceSOSTriggerModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Test mode Voice SOS without triggering real police alert."""
    if voice_sos_config_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Authenticated callers only test their OWN config; anonymous test path preserved.
    target_user_id = current_user.user_id if current_user else trigger.user_id
    cfg = voice_sos_config_collection.find_one({"user_id": target_user_id})
    if not cfg:
        raise HTTPException(status_code=404, detail="Voice SOS not configured")

    stored_hash = cfg.get("safe_word_hash", "")
    stored_salt = cfg.get("safe_word_salt", "")

    match = False
    if trigger.spoken_phrase and stored_salt:
        match = verify_safe_word(trigger.spoken_phrase, stored_hash, stored_salt)
    elif trigger.hashed_safe_word:
        match = hmac.compare_digest(trigger.hashed_safe_word, stored_hash)

    ts = trigger.timestamp or datetime.utcnow().isoformat()
    event_id = f"TEST-{int(time.time())}-{secrets.token_hex(4)}"

    if sos_events_collection is not None:
        sos_events_collection.insert_one({
            "event_id": event_id,
            "user_id": target_user_id,
            "trigger_type": "test",
            "timestamp": ts,
            "latitude": trigger.latitude,
            "longitude": trigger.longitude,
            "location_accuracy": trigger.location_accuracy,
            "status": "test_complete",
            "contact_delivery_status": {},
            "is_test": True,
            "safe_word_matched": match,
            "created_at": datetime.utcnow(),
        })

    return {
        "success": True,
        "is_test": True,
        "event_id": event_id,
        "safe_word_matched": match,
        "location_captured": bool(trigger.latitude or trigger.longitude),
        "latitude": trigger.latitude,
        "longitude": trigger.longitude,
        "message": "TEST MODE — Verified successfully. No real emergency alerts dispatched.",
    }


@router.get("/voice-sos/history/{user_id}")
def voice_sos_history(
    user_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get Voice SOS event history for a user (owner or authority/admin only)."""
    require_self_or_authority(user_id, current_user)
    if sos_events_collection is None:
        return {"events": [], "total": 0}

    events = list(sos_events_collection.find(
        {"user_id": user_id},
        {"_id": 0, "safe_word_matched": 0}
    ).sort("created_at", -1).limit(20))

    return {
        "events": [serialize_doc(e) for e in events],
        "total": len(events),
    }


@router.post("/trusted-contacts")
def save_trusted_contacts(
    body: dict = Body(...),
    current_user: AuthUser = Depends(get_current_user)
):
    """Save trusted contacts for the authenticated user (body user_id is ignored)."""
    if trusted_contacts_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Identity comes only from the verified token.
    user_id = current_user.user_id

    contacts = body.get("contacts", [])
    if len(contacts) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 contacts allowed")

    trusted_contacts_collection.delete_many({"user_id": user_id})
    saved = []
    for c in contacts:
        doc = {
            "user_id": user_id,
            "contact_id": f"CONTACT-{int(time.time())}-{secrets.token_hex(2)}",
            "name": str(c.get("name", ""))[:100],
            "phone": str(c.get("phone", ""))[:30],
            "email": str(c.get("email", ""))[:120],
            "priority": int(c.get("priority", 1)),
            "created_at": datetime.utcnow(),
        }
        trusted_contacts_collection.insert_one(doc)
        saved.append({"name": doc["name"], "contact_id": doc["contact_id"]})

    return {"success": True, "contacts_saved": len(saved), "contacts": saved}


@router.get("/trusted-contacts/{user_id}")
def get_trusted_contacts(
    user_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get trusted contacts for a user (owner or authority/admin only)."""
    require_self_or_authority(user_id, current_user)
    if trusted_contacts_collection is None:
        return {"contacts": []}

    contacts = list(trusted_contacts_collection.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("priority", 1))

    return {"contacts": [serialize_doc(c) for c in contacts]}


# ── Per-contact add / delete ─────────────────────────────────────────────────
# The legacy full-replace POST /trusted-contacts (above) is kept for the initial
# Voice-SOS setup flow, but the day-to-day contacts UI uses these single-item
# endpoints. Operating on ONE contact atomically server-side removes the
# full-list-replace fragility (a stale client could otherwise resurrect a deleted
# contact or wipe one it never loaded) that made add/delete unreliable.
# Validation rules live in services.contact_validation so they can be unit-tested
# without importing FastAPI/PyMongo.


@router.post("/trusted-contacts/add")
def add_trusted_contact(
    body: dict = Body(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Add ONE trusted contact for the authenticated user.

    Identity comes ONLY from the verified token (any body user_id/owner_id is
    ignored). Validates name + phone server-side, dedups by normalized phone,
    enforces the max-contacts cap, and returns the AUTHORITATIVE updated list so
    the client never has to reconstruct it. Atomic single insert — a stale client
    cannot clobber contacts it did not know about.
    """
    if trusted_contacts_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    user_id = current_user.user_id

    name = str(body.get("name", "")).strip()[:100]
    phone = str(body.get("phone", "")).strip()[:30]
    email = str(body.get("email", "")).strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="Contact name is required")
    if not valid_phone(phone):
        raise HTTPException(status_code=400, detail="A valid phone number is required")
    if not valid_email(email):
        raise HTTPException(status_code=400, detail="Email address is not valid")

    existing = list(trusted_contacts_collection.find({"user_id": user_id}, {"_id": 0}))
    if len(existing) >= MAX_TRUSTED_CONTACTS:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_TRUSTED_CONTACTS} contacts allowed")
    # Duplicate handling: same normalized phone for the same user is rejected
    # (409) rather than silently creating a second copy.
    norm = normalize_phone(phone)
    if any(normalize_phone(c.get("phone", "")) == norm for c in existing):
        raise HTTPException(status_code=409, detail="This phone number is already saved")

    try:
        priority = int(body.get("priority", len(existing) + 1))
    except (TypeError, ValueError):
        priority = len(existing) + 1

    doc = {
        "user_id": user_id,
        "contact_id": f"CONTACT-{int(time.time())}-{secrets.token_hex(3)}",
        "name": name,
        "phone": phone,
        "email": email,
        "priority": priority,
        "created_at": datetime.utcnow(),
    }
    trusted_contacts_collection.insert_one(doc)

    contacts = list(trusted_contacts_collection.find(
        {"user_id": user_id}, {"_id": 0}).sort("priority", 1))
    return {
        "success": True,
        "contact": {"name": doc["name"], "contact_id": doc["contact_id"]},
        "contacts_saved": len(contacts),
        "contacts": [serialize_doc(c) for c in contacts],
    }


@router.delete("/trusted-contacts/{contact_id}")
def delete_trusted_contact(
    contact_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Delete ONE trusted contact owned by the authenticated user.

    The delete filter is scoped to BOTH the contact_id AND the authenticated
    user_id, so a user can only ever delete their OWN contact; another user's
    contact_id simply matches nothing (404) and is never touched. Persists in
    MongoDB and returns the authoritative remaining list.
    """
    if trusted_contacts_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    user_id = current_user.user_id

    result = trusted_contacts_collection.delete_one(
        {"user_id": user_id, "contact_id": contact_id})
    if result.deleted_count == 0:
        # Not found for THIS user -> either it never existed or it belongs to
        # someone else. Either way we reveal nothing and change nothing.
        raise HTTPException(status_code=404, detail="Contact not found")

    contacts = list(trusted_contacts_collection.find(
        {"user_id": user_id}, {"_id": 0}).sort("priority", 1))
    return {
        "success": True,
        "deleted": contact_id,
        "contacts_saved": len(contacts),
        "contacts": [serialize_doc(c) for c in contacts],
    }
