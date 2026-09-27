"""Privacy routes for user data management and deletion requests."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from auth import AuthUser, get_current_user, require_self_or_authority
from services.db import (
    sos_cases, therapy_sessions, trusted_contacts,
    voice_sos_config, sos_events, privacy_records, serialize_doc
)
from services.audit_service import log_audit

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Privacy"])


@router.get("/privacy/my-data/{user_id}")
def get_user_privacy_data(
    user_id: str,
    request: Request,
    current_user: AuthUser = Depends(get_current_user)
):
    """Aggregate and return all stored data belonging to the user.

    Requires authentication; only the owner (or an authority/admin) may read.
    """
    require_self_or_authority(user_id, current_user)

    # Fetch user's cases
    cases_coll = sos_cases()
    user_cases = []
    if cases_coll is not None:
        user_cases = list(cases_coll.find({"user_id": user_id}, {"_id": 0, "embedding": 0}))

    # Fetch user's therapy sessions
    therapy_coll = therapy_sessions()
    sessions = []
    if therapy_coll is not None:
        sessions = list(therapy_coll.find({"user_id": user_id}, {"_id": 0}))

    # Fetch voice SOS config
    voice_coll = voice_sos_config()
    voice_cfg = None
    if voice_coll is not None:
        raw_cfg = voice_coll.find_one({"user_id": user_id}, {"_id": 0, "safe_word_hash": 0, "safe_word_salt": 0})
        if raw_cfg:
            voice_cfg = serialize_doc(raw_cfg)

    # Fetch trusted contacts
    contacts_coll = trusted_contacts()
    contacts = []
    if contacts_coll is not None:
        contacts = list(contacts_coll.find({"user_id": user_id}, {"_id": 0}))

    # Fetch user SOS events
    events_coll = sos_events()
    events = []
    if events_coll is not None:
        events = list(events_coll.find({"user_id": user_id}, {"_id": 0, "safe_word_matched": 0}).limit(20))

    # P2-1: record that PII was accessed (forensic accountability). Only the
    # actor, target user, and counts are logged — NEVER the returned PII itself.
    try:
        log_audit(
            actor_id=current_user.user_id,
            role=current_user.role,
            action="PRIVACY_DATA_ACCESSED",
            result="success",
            metadata={
                "target_user_id": user_id,
                "self_access": current_user.user_id == user_id,
                "cases": len(user_cases),
                "therapy_sessions": len(sessions),
                "trusted_contacts": len(contacts),
                "sos_events": len(events),
            },
            request=request,
        )
    except Exception:
        # Auditing must never break the user's data-access request.
        pass

    return {
        "user_id": user_id,
        "summary": {
            "total_sos_cases": len(user_cases),
            "total_therapy_sessions": len(sessions),
            "trusted_contacts_count": len(contacts),
            "total_sos_events": len(events)
        },
        "sos_cases": [serialize_doc(c) for c in user_cases],
        "therapy_sessions": [serialize_doc(s) for s in sessions],
        "voice_config": voice_cfg,
        "trusted_contacts": [serialize_doc(c) for c in contacts],
        "sos_events": [serialize_doc(e) for e in events]
    }


@router.delete("/privacy/therapy-sessions/{session_id}")
def delete_user_therapy_session(
    session_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Delete a therapy conversation session (owner or authority/admin only)."""
    coll = therapy_sessions()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    session = coll.find_one({"session_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Therapy session not found")

    # Ownership enforced against the VERIFIED identity (never a body/query value).
    require_self_or_authority(str(session.get("user_id", "")), current_user)

    coll.delete_one({"session_id": session_id})
    return {"success": True, "message": "Therapy session permanently deleted"}


@router.delete("/privacy/sos-history/{case_id}")
def delete_user_sos_case(
    case_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Allow a user to remove an eligible RESOLVED SOS case from their record."""
    coll = sos_cases()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    case_doc = coll.find_one({"case_id": case_id})
    if not case_doc:
        raise HTTPException(status_code=404, detail="Case not found")

    # Ownership enforced against the VERIFIED identity.
    require_self_or_authority(str(case_doc.get("user_id", "")), current_user)

    # Safety constraint: only RESOLVED cases can be deleted from user's view
    status = str(case_doc.get("status", "")).upper()
    if status not in ["RESOLVED", "CLOSED"]:
        raise HTTPException(status_code=400, detail="Only RESOLVED cases can be removed by users for legal compliance.")

    coll.delete_one({"case_id": case_id})
    return {"success": True, "message": f"Case {case_id} removed from user history"}


@router.post("/privacy/deletion-request")
def request_account_data_deletion(
    body: dict = Body(...),
    current_user: AuthUser = Depends(get_current_user)
):
    """Submit a formal GDPR/DPDP user data wipe request for the authenticated user."""
    # Identity comes ONLY from the verified token — a body user_id is never trusted.
    user_id = current_user.user_id

    coll = privacy_records()
    req_id = f"DEL-REQ-{int(datetime.utcnow().timestamp())}"
    doc = {
        "request_id": req_id,
        "user_id": user_id,
        "request_type": body.get("request_type", "ACCOUNT_WIPE"),
        "reason": body.get("reason", "User requested account wipe"),
        "status": "QUEUED",
        "created_at": datetime.utcnow()
    }
    if coll is not None:
        coll.insert_one(doc)

    log_audit(user_id, current_user.role, "DATA_DELETION_REQUESTED", metadata={"request_id": req_id})
    return {
        "success": True,
        "request_id": req_id,
        "message": "Data wipe request registered successfully. Records will be purged per DPDP compliance."
    }
