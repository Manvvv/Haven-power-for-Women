"""Authority-initiated provider registration & lifecycle review service.

Architecture & Security:
  - Authority personnel submit registration requests for emergency response units within
    their authorized jurisdiction.
  - Authority submission does NOT automatically create an active, verified, or dispatch-eligible
    account. It enters PENDING_REVIEW status.
  - Administrators review, verify credentials, and approve/reject registrations.
  - Upon approval, an inert responder account is created with a single-use setup token
    (matching the secure provisioning contract).
  - Authority personnel can submit suspension or revocation requests for providers;
    Administrators review and execute them.
  - Audit logs are maintained for every submission, review, approval, rejection, and request.
"""
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services.audit_service import log_audit
from services.db import provider_registrations, provider_requests, serialize_doc
from services import responder_service

logger = logging.getLogger("haven_backend")

# In-memory stores used when Mongo is unavailable (CI / isolated tests)
_registrations_memory: Dict[str, Dict[str, Any]] = {}
_requests_memory: Dict[str, Dict[str, Any]] = {}


class RegistrationValidationError(Exception):
    """Raised when registration data fails validation."""
    pass


class RegistrationConflictError(Exception):
    """Raised when proposed badge or unit is already registered."""
    pass


class RegistrationNotFoundError(Exception):
    """Raised when a requested registration ID does not exist."""
    pass


class RegistrationStateError(Exception):
    """Raised when an operation is invalid for current registration state."""
    pass


def _normalize_str(val: Any, max_len: int = 120) -> str:
    return str(val or "").strip()[:max_len]


def _normalize_caps(caps: Any) -> List[str]:
    if not isinstance(caps, list):
        return []
    out = []
    for c in caps[:20]:
        clean = str(c).strip().lower()[:40]
        if clean and clean not in out:
            out.append(clean)
    return out


def submit_registration(
    unit_name: str,
    organization: str,
    provider_category: str,
    jurisdiction: str,
    contact: str,
    auth_reference: str,
    submitted_by: str,
    submitted_by_role: str,
    badge_number: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a provider registration for admin review.

    Authority-accessible. Enforces strict input validation and duplicate detection.
    Does NOT activate or verify the provider.
    """
    unit_name = _normalize_str(unit_name, 120)
    organization = _normalize_str(organization, 120)
    jurisdiction = _normalize_str(jurisdiction, 120)
    contact = _normalize_str(contact, 120)
    auth_reference = _normalize_str(auth_reference, 120)
    notes = _normalize_str(notes, 500)
    cat = responder_service._normalize_category(provider_category) or "police"

    if len(unit_name) < 2:
        raise RegistrationValidationError("Unit or provider name must be at least 2 characters.")
    if len(organization) < 2:
        raise RegistrationValidationError("Organization must be at least 2 characters.")
    if len(jurisdiction) < 1:
        raise RegistrationValidationError("Jurisdiction is required.")
    if len(contact) < 3:
        raise RegistrationValidationError("Official contact information is required.")
    if len(auth_reference) < 2:
        raise RegistrationValidationError("Registration or authorization reference is required.")
    if cat not in responder_service.PROVIDER_CATEGORIES:
        raise RegistrationValidationError(f"Invalid provider category '{provider_category}'.")

    # Generate or normalize badge number
    badge = _normalize_str(badge_number, 40)
    if not badge:
        # Default suggested badge prefix based on category
        prefix = "POL" if cat == "police" else "WSU" if cat == "women_safety_unit" else "NGO"
        badge = f"{prefix}-{secrets.token_hex(3).upper()}"

    # Check for duplicate badge against existing responders
    if responder_service.get_responder(badge) is not None:
        raise RegistrationConflictError(f"A provider with badge '{badge}' already exists.")

    # Check for duplicate badge against pending registrations
    coll = provider_registrations()
    if coll is not None:
        existing_pending = coll.find_one({"badge_number": badge, "status": "PENDING_REVIEW"})
        if existing_pending:
            raise RegistrationConflictError(f"A pending registration with badge '{badge}' is already under review.")
    else:
        for r in _registrations_memory.values():
            if r.get("badge_number") == badge and r.get("status") == "PENDING_REVIEW":
                raise RegistrationConflictError(f"A pending registration with badge '{badge}' is already under review.")

    reg_id = f"PREG-{int(datetime.utcnow().timestamp())}-{secrets.token_hex(3).upper()}"
    now = datetime.utcnow()
    caps = _normalize_caps(capabilities or ["general", "patrol"])

    doc: Dict[str, Any] = {
        "registration_id": reg_id,
        "unit_name": unit_name,
        "badge_number": badge,
        "organization": organization,
        "provider_category": cat,
        "jurisdiction": jurisdiction,
        "capabilities": caps,
        "contact": contact,
        "auth_reference": auth_reference,
        "notes": notes,
        "status": "PENDING_REVIEW",
        "rejection_reason": None,
        "submitted_by": submitted_by,
        "submitted_by_role": submitted_by_role,
        "submitted_at": now,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_responder_id": None,
        "setup_token": None,
        "setup_token_expires_at": None,
    }

    if coll is not None:
        coll.insert_one(doc)
    else:
        _registrations_memory[reg_id] = doc

    log_audit(
        actor_id=submitted_by,
        role=submitted_by_role,
        action="PROVIDER_REGISTRATION_SUBMITTED",
        metadata={
            "registration_id": reg_id,
            "badge_number": badge,
            "unit_name": unit_name,
            "jurisdiction": jurisdiction,
            "provider_category": cat,
        },
    )

    return serialize_doc(doc)


def get_registration(registration_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve registration by canonical registration_id."""
    coll = provider_registrations()
    if coll is not None:
        doc = coll.find_one({"registration_id": registration_id})
        return serialize_doc(doc) if doc else None
    doc = _registrations_memory.get(registration_id)
    return serialize_doc(doc) if doc else None


def list_registrations(
    submitted_by: Optional[str] = None,
    status: Optional[str] = None,
    jurisdiction: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List provider registrations with optional filters."""
    query: Dict[str, Any] = {}
    if submitted_by:
        query["submitted_by"] = submitted_by
    if status:
        query["status"] = status
    if jurisdiction:
        query["jurisdiction"] = jurisdiction

    coll = provider_registrations()
    if coll is not None:
        docs = list(coll.find(query).sort("submitted_at", -1))
    else:
        docs = list(_registrations_memory.values())
        if submitted_by:
            docs = [d for d in docs if d.get("submitted_by") == submitted_by]
        if status:
            docs = [d for d in docs if d.get("status") == status]
        if jurisdiction:
            docs = [d for d in docs if d.get("jurisdiction") == jurisdiction]
        docs.sort(key=lambda d: d.get("submitted_at") or datetime.min, reverse=True)

    results = []
    for doc in docs:
        sd = serialize_doc(doc)
        # If approved, enrich with the live provider state so operators can follow the full lifecycle
        resp_id = sd.get("created_responder_id")
        if resp_id:
            live = responder_service.get_responder_by_id(resp_id)
            if live:
                    sd["live_provider"] = {
                        "responder_id": live.get("responder_id"),
                        "provisioning_state": responder_service.provisioning_state(live),
                        "verified": bool(live.get("verified")),
                        "active": bool(live.get("active")),
                        "duty_status": live.get("duty_status"),
                        "status": live.get("status"),
                        "on_duty": responder_service.is_on_duty(live),
                        "location_fresh": responder_service.is_location_fresh(live),
                    }
        results.append(sd)

    return results


def approve_registration(
    registration_id: str,
    reviewed_by: str,
    reviewed_by_role: str,
) -> Dict[str, Any]:
    """Approve a pending provider registration (ADMIN only).

    Creates an INERT responder record and issues a single-use setup token.
    Transitions status to APPROVED.
    """
    coll = provider_registrations()
    doc = None
    if coll is not None:
        doc = coll.find_one({"registration_id": registration_id})
    else:
        doc = _registrations_memory.get(registration_id)

    if not doc:
        raise RegistrationNotFoundError(f"Registration '{registration_id}' not found.")
    if doc.get("status") != "PENDING_REVIEW":
        raise RegistrationStateError(f"Registration is not in PENDING_REVIEW state (currently '{doc.get('status')}').")

    badge = doc["badge_number"]
    if responder_service.get_responder(badge) is not None:
        raise RegistrationConflictError(f"A provider with badge '{badge}' already exists.")

    # Create the INERT responder record (verified=False, active=True, random unusable password)
    rec = responder_service.create_responder_inert(
        badge_number=badge,
        officer_name=doc["unit_name"],
        display_label=doc["unit_name"],
        capabilities=doc.get("capabilities", []),
        jurisdiction=doc.get("jurisdiction", ""),
        provider_category=doc.get("provider_category", "police"),
        organization=doc.get("organization", ""),
        contact=doc.get("contact", ""),
        active=True,
    )
    responder_id = rec.get("responder_id")
    responder_service.mark_password_unset(responder_id)

    try:
        setup_token = responder_service.issue_setup_token(responder_id)
    except responder_service.SetupStoreUnavailable:
        raise RuntimeError("Provider setup token store is currently unavailable.")

    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=responder_service.SETUP_TOKEN_TTL_SECONDS)

    update_fields = {
        "status": "APPROVED",
        "reviewed_by": reviewed_by,
        "reviewed_at": now,
        "created_responder_id": responder_id,
        "setup_token": None,
        "setup_token_expires_at": expires_at,
    }

    if coll is not None:
        coll.update_one({"registration_id": registration_id}, {"$set": update_fields})
        doc = coll.find_one({"registration_id": registration_id})
    else:
        doc.update(update_fields)

    log_audit(
        actor_id=reviewed_by,
        role=reviewed_by_role,
        action="PROVIDER_REGISTRATION_APPROVED",
        metadata={
            "registration_id": registration_id,
            "responder_id": responder_id,
            "badge_number": badge,
        },
    )
    log_audit(
        actor_id=reviewed_by,
        role=reviewed_by_role,
        action="PROVIDER_CREATED",
        metadata={
            "responder_id": responder_id,
            "badge_number": badge,
            "via_registration_id": registration_id,
        },
    )

    out = serialize_doc(doc)
    out["setup_token"] = setup_token  # Provided ONCE in-memory to the approving admin
    resp = responder_service.get_responder_by_id(responder_id)
    out["responder"] = serialize_doc(resp) if resp else None
    out["provisioning_state"] = responder_service.provisioning_state(resp)
    return out



def reject_registration(
    registration_id: str,
    reason: str,
    reviewed_by: str,
    reviewed_by_role: str,
) -> Dict[str, Any]:
    """Reject a pending provider registration (ADMIN only)."""
    reason = _normalize_str(reason, 500)
    if not reason:
        raise RegistrationValidationError("A clear reason for rejection must be provided.")

    coll = provider_registrations()
    doc = None
    if coll is not None:
        doc = coll.find_one({"registration_id": registration_id})
    else:
        doc = _registrations_memory.get(registration_id)

    if not doc:
        raise RegistrationNotFoundError(f"Registration '{registration_id}' not found.")
    if doc.get("status") != "PENDING_REVIEW":
        raise RegistrationStateError(f"Registration is not in PENDING_REVIEW state (currently '{doc.get('status')}').")

    now = datetime.utcnow()
    update_fields = {
        "status": "REJECTED",
        "rejection_reason": reason,
        "reviewed_by": reviewed_by,
        "reviewed_at": now,
    }

    if coll is not None:
        coll.update_one({"registration_id": registration_id}, {"$set": update_fields})
        doc = coll.find_one({"registration_id": registration_id})
    else:
        doc.update(update_fields)

    log_audit(
        actor_id=reviewed_by,
        role=reviewed_by_role,
        action="PROVIDER_REGISTRATION_REJECTED",
        metadata={
            "registration_id": registration_id,
            "reason": reason,
        },
    )

    return serialize_doc(doc)


# ─── Authority Suspension & Revocation Requests ─────────────────────────────────

def submit_provider_request(
    responder_id: str,
    request_type: str,
    reason: str,
    submitted_by: str,
    submitted_by_role: str,
) -> Dict[str, Any]:
    """Submit a request to suspend or revoke a provider account (Authority-accessible)."""
    req_type = str(request_type or "").strip().upper()
    if req_type not in ("SUSPENSION", "REVOCATION"):
        raise RegistrationValidationError("Request type must be SUSPENSION or REVOCATION.")

    reason = _normalize_str(reason, 500)
    if len(reason) < 3:
        raise RegistrationValidationError("A detailed reason for the action request is required.")

    target = responder_service.get_responder_by_id(responder_id)
    if not target:
        raise RegistrationNotFoundError(f"Provider '{responder_id}' not found.")

    req_id = f"PREQ-{int(datetime.utcnow().timestamp())}-{secrets.token_hex(3).upper()}"
    now = datetime.utcnow()

    doc: Dict[str, Any] = {
        "request_id": req_id,
        "responder_id": responder_id,
        "badge_number": target.get("badge_number"),
        "display_label": target.get("display_label"),
        "request_type": req_type,
        "reason": reason,
        "status": "PENDING_REVIEW",
        "submitted_by": submitted_by,
        "submitted_by_role": submitted_by_role,
        "submitted_at": now,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": None,
    }

    coll = provider_requests()
    if coll is not None:
        coll.insert_one(doc)
    else:
        _requests_memory[req_id] = doc

    log_audit(
        actor_id=submitted_by,
        role=submitted_by_role,
        action="PROVIDER_ACTION_REQUESTED",
        metadata={
            "request_id": req_id,
            "responder_id": responder_id,
            "request_type": req_type,
            "reason": reason,
        },
    )

    return serialize_doc(doc)


def list_provider_requests(
    submitted_by: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List provider suspension / revocation requests."""
    query: Dict[str, Any] = {}
    if submitted_by:
        query["submitted_by"] = submitted_by
    if status:
        query["status"] = status

    coll = provider_requests()
    if coll is not None:
        docs = list(coll.find(query).sort("submitted_at", -1))
    else:
        docs = list(_requests_memory.values())
        if submitted_by:
            docs = [d for d in docs if d.get("submitted_by") == submitted_by]
        if status:
            docs = [d for d in docs if d.get("status") == status]
        docs.sort(key=lambda d: d.get("submitted_at") or datetime.min, reverse=True)

    return [serialize_doc(d) for d in docs]


def review_provider_request(
    request_id: str,
    action: str,
    review_notes: Optional[str],
    reviewed_by: str,
    reviewed_by_role: str,
) -> Dict[str, Any]:
    """Admin review of a suspension or revocation request."""
    action = str(action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise RegistrationValidationError("Action must be 'approve' or 'reject'.")

    coll = provider_requests()
    doc = None
    if coll is not None:
        doc = coll.find_one({"request_id": request_id})
    else:
        doc = _requests_memory.get(request_id)

    if not doc:
        raise RegistrationNotFoundError(f"Request '{request_id}' not found.")
    if doc.get("status") != "PENDING_REVIEW":
        raise RegistrationStateError(f"Request is not PENDING_REVIEW (currently '{doc.get('status')}').")

    responder_id = doc["responder_id"]
    req_type = doc["request_type"]
    now = datetime.utcnow()
    notes = _normalize_str(review_notes, 500)

    if action == "approve":
        if req_type == "SUSPENSION":
            responder_service.set_active(responder_id, False)
            log_audit(
                actor_id=reviewed_by,
                role=reviewed_by_role,
                action="PROVIDER_DEACTIVATED",
                metadata={"responder_id": responder_id, "via_request_id": request_id},
            )
        elif req_type == "REVOCATION":
            responder_service.set_verified(responder_id, False)
            responder_service.set_active(responder_id, False)
            log_audit(
                actor_id=reviewed_by,
                role=reviewed_by_role,
                action="PROVIDER_VERIFICATION_REVOKED",
                metadata={"responder_id": responder_id, "via_request_id": request_id},
            )
        update_fields = {
            "status": "APPROVED",
            "review_notes": notes,
            "reviewed_by": reviewed_by,
            "reviewed_at": now,
        }
        log_audit(
            actor_id=reviewed_by,
            role=reviewed_by_role,
            action="PROVIDER_REQUEST_APPROVED",
            metadata={"request_id": request_id, "responder_id": responder_id, "request_type": req_type},
        )
    else:
        update_fields = {
            "status": "REJECTED",
            "review_notes": notes,
            "reviewed_by": reviewed_by,
            "reviewed_at": now,
        }
        log_audit(
            actor_id=reviewed_by,
            role=reviewed_by_role,
            action="PROVIDER_REQUEST_REJECTED",
            metadata={"request_id": request_id, "responder_id": responder_id, "request_type": req_type},
        )

    if coll is not None:
        coll.update_one({"request_id": request_id}, {"$set": update_fields})
        doc = coll.find_one({"request_id": request_id})
    else:
        doc.update(update_fields)

    return serialize_doc(doc)
