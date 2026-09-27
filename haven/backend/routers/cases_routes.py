"""Cases routes — view and manage SOS cases."""
import re
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from auth import AuthUser, require_authority, decrypt_evidence_payload
from services.db import sos_cases, sos_status_history, serialize_doc
from services.audit_service import log_audit
from services.lifecycle_service import transition_sos, VALID_TRANSITIONS, canonical_status, is_terminal_status
from models.schemas import CaseUpdateModel

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Cases"])


@router.get("/cases")
def get_cases(
    severity: str = Query(None),
    status: str = Query(None),
    current_user: AuthUser = Depends(require_authority)
):
    """Get all SOS cases (Authority Only, Decrypts Evidence)."""
    collection = sos_cases()
    if collection is None:
        return {"cases": [], "total": 0}
    query = {}
    if severity:
        # Case-insensitive exact match (data mixes 'critical' and 'CRITICAL').
        query["severity"] = {"$regex": f"^{re.escape(severity)}$", "$options": "i"}
    if status:
        query["status"] = {"$regex": f"^{re.escape(status)}$", "$options": "i"}
    cases = list(collection.find(query, {"_id": 0}).sort("created_at", -1).limit(50))
    decrypted_cases = []
    for c in cases:
        c_copy = dict(c)
        # Remove embeddings from response
        c_copy.pop("embedding", None)
        # Normalize status to the canonical lifecycle state so the UI never shows
        # legacy aliases ("active"/"triggered") or mixed casing. Read-only: the
        # stored document is untouched here (it self-heals on its next PATCH
        # transition via transition_sos); we only shape the response.
        c_copy["status"] = canonical_status(c_copy.get("status", "CREATED"))
        evid = c_copy.get("evidence")
        if evid and isinstance(evid, dict):
            if evid.get("is_encrypted"):
                if evid.get("audio_ciphertext"):
                    evid["audio_base64"] = decrypt_evidence_payload(
                        evid.get("audio_ciphertext", ""), evid.get("audio_nonce", ""))
                if evid.get("image_ciphertext"):
                    evid["image_base64"] = decrypt_evidence_payload(
                        evid.get("image_ciphertext", ""), evid.get("image_nonce", ""))
        decrypted_cases.append(serialize_doc(c_copy))
    log_audit(current_user.user_id, current_user.role, "CASE_VIEWED",
              result="success", metadata={"count": len(decrypted_cases)})
    return {"cases": decrypted_cases, "total": len(decrypted_cases)}


@router.patch("/cases/{case_id}")
def update_case(
    case_id: str,
    body: CaseUpdateModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Update case status (Authority Only + Mass-Assignment Guard)."""
    collection = sos_cases()
    if collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    all_fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not all_fields:
        raise HTTPException(status_code=400, detail="No valid update fields specified")

    # A status change is a lifecycle transition — route it through the state machine so
    # transitions are validated and recorded in status history + audit consistently.
    new_status = all_fields.pop("status", None)
    if new_status is not None:
        ok = transition_sos(
            case_id=case_id,
            new_status=new_status,
            actor_id=current_user.user_id,
            role=current_user.role,
            notes=body.dispatcher_notes or "",
        )
        if not ok:
            # Distinguish "case not found" from "illegal transition" for a clear 4xx.
            case = collection.find_one({"case_id": case_id}, {"_id": 0, "status": 1})
            if case is None:
                raise HTTPException(status_code=404, detail="Case ID not found")
            # Report the CANONICAL current state so the message + allowed-states
            # match the state machine even for legacy rows (e.g. "active").
            current = canonical_status(case.get("status", "CREATED"))
            allowed = VALID_TRANSITIONS.get(current, [])
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid lifecycle transition from '{current}' to "
                    f"'{canonical_status(new_status)}'. Allowed next states: {allowed or 'none (terminal)'}"
                ),
            )

        # On resolution (terminal state) stop live tracking: purge the in-memory
        # last-known location so no late WS subscriber gets a stale fix. The REST
        # location-update endpoint already rejects updates on terminal cases (409).
        # Historical location on the case/event rows is preserved (evidence).
        if is_terminal_status(canonical_status(new_status)):
            try:
                from main import tracking_manager
                purged = tracking_manager.purge_location(case_id)
                log_audit(current_user.user_id, current_user.role, "TRACKING_STOPPED",
                          case_id=case_id, result="success",
                          metadata={"reason": "case_resolved", "live_cache_purged": purged})
            except Exception:
                # Best-effort: the case is already resolved in the DB; never fail
                # the resolution because the in-memory cache purge/audit hiccuped.
                pass

    # Remaining non-status fields (notes, assigned unit, priority, severity) update directly.
    if all_fields:
        all_fields["updated_at"] = datetime.utcnow()
        all_fields["last_updated_by"] = current_user.user_id
        result = collection.update_one({"case_id": case_id}, {"$set": all_fields})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Case ID not found")
        log_audit(current_user.user_id, current_user.role, "CASE_UPDATED",
                  case_id=case_id, metadata={"updated_fields": list(all_fields.keys())})

    updated = list(all_fields.keys()) + (["status"] if new_status is not None else [])
    return {"success": True, "case_id": case_id, "updated": updated}


@router.get("/cases/{case_id}/lifecycle")
def get_case_lifecycle(
    case_id: str,
    current_user: AuthUser = Depends(require_authority)
):
    """Get full status history timeline for a case."""
    history_coll = sos_status_history()
    if history_coll is None:
        return {"case_id": case_id, "history": []}
    history = list(history_coll.find(
        {"case_id": case_id}, {"_id": 0}
    ).sort("timestamp", 1))
    return {"case_id": case_id, "history": [serialize_doc(h) for h in history]}
