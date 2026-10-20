"""Admin routes for system metrics, user roles, system config, and security audit logs."""
import os
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Body, HTTPException, Path
from services.db import audit_logs, sos_cases, get_db, sos_events, serialize_doc, voice_sos_config
from auth import AuthUser, require_admin
from services.audit_service import log_audit
from services.authority_service import (
    CANONICAL_ROLES, get_authority_by_id, set_role,
)
from services import responder_service
from models.schemas import ResponderAdminUpdateModel

logger = logging.getLogger("haven_backend")
router = APIRouter(prefix="", tags=["Admin"])


@router.get("/admin/audit-logs")
def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    action: Optional[str] = None,
    actor_id: Optional[str] = None,
    case_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: AuthUser = Depends(require_admin)
):
    """Retrieve filtered, paginated security and action audit logs.

    ADMIN-only (P1-4): the audit trail is admin-only data — an authority user
    can no longer read it. Authorization comes from the verified token via
    require_admin; no body/query/path/header field can grant access.
    """
    collection = audit_logs()
    if collection is None:
        return {"logs": [], "total": 0, "page": page, "limit": limit}

    query = {}
    if action:
        query["action"] = action
    if actor_id:
        query["actor_id"] = actor_id
    if case_id:
        query["case_id"] = case_id

    date_query = {}
    if date_from:
        try:
            date_query["$gte"] = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    if date_to:
        try:
            date_query["$lte"] = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
        except ValueError:
            pass

    if date_query:
        query["timestamp"] = date_query

    total = collection.count_documents(query)
    raw_logs = list(
        collection.find(query, {"_id": 0})
        .sort("timestamp", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )

    logs = [serialize_doc(l) for l in raw_logs]

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "limit": limit
    }


@router.get("/admin/users")
def list_admin_users(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    current_user: AuthUser = Depends(require_admin)
):
    """List known users extracted from active configurations and case records.

    ADMIN-only (P1-4): the user roster is admin-only data. Role comes from the
    verified token via require_admin; no client-supplied field can grant access.
    """
    db = get_db()
    if db is None:
        return {"users": [], "total": 0}

    user_map = {}
    # Fetch from voice_sos_config
    configs = voice_sos_config()
    if configs is not None:
        for c in configs.find({}, {"_id": 0}).limit(100):
            uid = c.get("user_id")
            if uid:
                user_map[uid] = {
                    "user_id": uid,
                    "role": "user",
                    "configured_safe_word": bool(c.get("safe_word_hash")),
                    "created_at": c.get("created_at", datetime.utcnow().isoformat()),
                    "last_active": c.get("updated_at", c.get("created_at"))
                }

    # Fetch distinct users from SOS cases
    cases_coll = sos_cases()
    if cases_coll is not None:
        for case in cases_coll.find({}, {"_id": 0, "user_id": 1, "created_at": 1, "severity": 1}).limit(200):
            uid = case.get("user_id")
            if uid:
                if uid not in user_map:
                    user_map[uid] = {
                        "user_id": uid,
                        "role": "user",
                        "configured_safe_word": False,
                        "created_at": case.get("created_at"),
                        "last_active": case.get("created_at")
                    }
                else:
                    user_map[uid]["last_active"] = max(
                        str(user_map[uid].get("last_active", "")),
                        str(case.get("created_at", ""))
                    )

    users_list = list(user_map.values())
    total = len(users_list)
    paginated = users_list[(page - 1) * limit : page * limit]

    return {
        "users": [serialize_doc(u) for u in paginated],
        "total": total,
        "page": page,
        "limit": limit
    }


@router.patch("/admin/users/{user_id}/role")
def update_user_role(
    user_id: str = Path(...),
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_admin)
):
    """Durably update an authority identity's authorization role (Admin only). P1-8.

    Previously this endpoint validated + audited + returned success but did NOT
    persist the change, so RBAC silently stayed on the old role. It now writes the
    new role to the authoritative `authority_accounts` store (the only durable,
    login-consulted role field in HAVEN) via an atomic single-identity update.

    Authorization and the acting-admin identity come ONLY from the verified token
    (require_admin); no request-body field can grant access or spoof the actor.
    """
    new_role = body.get("role")
    # STEP 3 — validate against the project's canonical roles; reject null/empty/arbitrary.
    if not isinstance(new_role, str) or new_role not in CANONICAL_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{new_role}'. Must be one of: {', '.join(CANONICAL_ROLES)}"
        )

    # 404 if there is no manageable identity for this id (never auto-create one).
    target = get_authority_by_id(user_id)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=(f"No manageable identity found for '{user_id}'. Only provisioned "
                    f"authority accounts have a durable role; normal users are not role-managed here."),
        )
    previous_role = target.get("role", "authority")

    # STEP 4 — lockout safety: an admin may not demote their OWN account out of admin.
    if user_id in (current_user.user_id, target.get("authority_id"), target.get("badge_number")) \
            and previous_role == "admin" and new_role != "admin":
        raise HTTPException(
            status_code=400,
            detail="An admin cannot demote their own account; ask another admin to change your role.",
        )

    # STEP 2 — persist the change atomically.
    updated, error = set_role(user_id, new_role)
    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"No manageable identity found for '{user_id}'.")

    # STEP 6 — audit with verified actor + previous and new role (never body actor).
    log_audit(
        actor_id=current_user.user_id,
        role=current_user.role,
        action="ROLE_CHANGED",
        metadata={
            "target_user_id": user_id,
            "previous_role": previous_role,
            "new_role": new_role,
        },
    )

    # STEP 5 — role is a JWT claim baked at login; existing tokens keep their old role
    # until re-authentication. Be honest about this instead of implying immediacy.
    return {
        "success": True,
        "user_id": user_id,
        "role": (updated or {}).get("role", new_role),
        "previous_role": previous_role,
        "effective_immediately": False,
        "message": (
            f"Role persisted as '{new_role}'. It applies on the user's next login; "
            f"existing sessions retain their current role until they re-authenticate."
        ),
    }


@router.get("/admin/system-config")
def get_system_config(current_user: AuthUser = Depends(require_admin)):
    """System health, environment flag status, and model configuration.

    ADMIN-only (P1-4): environment/config detail is admin-only. Role comes from
    the verified token via require_admin; no client-supplied field grants access.
    """
    db = get_db()
    return {
        "status": "operational",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "features": {
            "steganography": True,
            "voice_sos": True,
            "offline_queue": True,
            "realtime_notifications": True,
            "ai_risk_classifier": "demo_llm_mode",
            "semantic_vector_search": True,
            "legal_rag": True,
            "audit_trail": True,
            "privacy_compliance": True
        },
        "database": {
            "connected": db is not None,
            "name": "Haven"
        },
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/admin/system-stats")
def get_system_stats(current_user: AuthUser = Depends(require_admin)):
    """Return aggregated counts for dashboard overview.

    ADMIN-only (P1-4): platform-wide statistics are admin-only. Role comes from
    the verified token via require_admin; no client-supplied field grants access.
    """
    db = get_db()
    if db is None:
        return {"status": "error", "message": "Database not connected"}

    cases_coll = sos_cases()
    events_coll = sos_events()
    audits_coll = audit_logs()

    total_cases = cases_coll.count_documents({}) if cases_coll is not None else 0
    total_events = events_coll.count_documents({}) if events_coll is not None else 0
    total_audits = audits_coll.count_documents({}) if audits_coll is not None else 0

    total_users = 0
    if cases_coll is not None:
        users = cases_coll.distinct("user_id")
        total_users = len(users)

    return {
        "status": "healthy",
        "db_connected": True,
        "metrics": {
            "total_cases": total_cases,
            "total_users": total_users,
            "total_events": total_events,
            "total_audit_records": total_audits
        }
    }


# ─── Rapid Response Network: responder approval (admin-only) ────────────────────
def _admin_responder_view(rec: dict) -> dict:
    """Admin management view of a responder — NEVER the password hash/salt."""
    if not rec:
        return {}
    lu = rec.get("location_updated_at")
    return {
        "responder_id": rec.get("responder_id"),
        "badge_number": rec.get("badge_number"),
        "officer_name": rec.get("officer_name"),
        "display_label": rec.get("display_label"),
        "role": rec.get("role", "responder"),
        "active": bool(rec.get("active", False)),
        "verified": bool(rec.get("verified", False)),
        "status": rec.get("status"),
        "capabilities": rec.get("capabilities", []),
        "jurisdiction": rec.get("jurisdiction", ""),
        "has_location": bool(rec.get("current_location")),
        "location_updated_at": lu.isoformat() if hasattr(lu, "isoformat") else lu,
        "assigned_dispatch_id": rec.get("assigned_dispatch_id"),
    }


@router.get("/admin/responders")
def list_responders_endpoint(current_user: AuthUser = Depends(require_admin)):
    """List all field-responder accounts for admin approval/management (Admin only).

    ADMIN-only, matching the existing trusted admin workflow. Password material is
    never returned. Responders are provisioned on the server (provision_responder.py);
    this endpoint approves/verifies/activates them — it does not create them.
    """
    rows = responder_service.list_responders()
    return {"responders": [_admin_responder_view(r) for r in rows], "total": len(rows)}


@router.patch("/admin/responders/{responder_id}")
def update_responder_endpoint(
    responder_id: str = Path(...),
    body: ResponderAdminUpdateModel = Body(...),
    current_user: AuthUser = Depends(require_admin),
):
    """Approve (verify) and/or (de)activate a responder (Admin only).

    This is the human approval gate: a provisioned responder is INERT (verified=
    False) until an admin flips verified=True here. Authorization and the acting
    admin identity come ONLY from the verified token (require_admin); no body field
    can grant access or spoof the actor. verified/active are the ONLY mutable
    fields — role is fixed server-side and cannot be elevated through this endpoint.
    """
    if body.verified is None and body.active is None:
        raise HTTPException(status_code=400, detail="Provide 'verified' and/or 'active' to update.")

    existing = responder_service.get_responder_by_id(responder_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No responder account found for '{responder_id}'.")

    updated = existing
    if body.active is not None:
        ok = responder_service.set_active(responder_id, bool(body.active))
        if not ok:
            raise HTTPException(status_code=404, detail=f"No responder account found for '{responder_id}'.")
    if body.verified is not None:
        rec = responder_service.set_verified(responder_id, bool(body.verified))
        if rec is None:
            raise HTTPException(status_code=404, detail=f"No responder account found for '{responder_id}'.")

    updated = responder_service.get_responder_by_id(responder_id) or existing
    # Named audit events per the provider-management spec; one per changed flag.
    if body.verified is not None:
        log_audit(actor_id=current_user.user_id, role=current_user.role,
                  action="PROVIDER_VERIFICATION_APPROVED" if body.verified else "PROVIDER_VERIFICATION_REVOKED",
                  metadata={"responder_id": responder_id, "verified": bool(body.verified)})
    if body.active is not None:
        log_audit(actor_id=current_user.user_id, role=current_user.role,
                  action="PROVIDER_ACTIVATED" if body.active else "PROVIDER_DEACTIVATED",
                  metadata={"responder_id": responder_id, "active": bool(body.active)})
    log_audit(
        actor_id=current_user.user_id,
        role=current_user.role,
        action="RESPONDER_ADMIN_UPDATE",
        metadata={
            "responder_id": responder_id,
            "verified": body.verified,
            "active": body.active,
            "resulting_status": updated.get("status"),
        },
    )
    return {"success": True, "responder": _admin_responder_view(updated)}


# ─── Provider provisioning (ADMIN ONLY, per the Q1 decision) ─────────────────────
# AUTHORITY can never reach these. Creating a provider does NOT make it trusted: the
# record is created INERT (verified=False, OFFLINE, no usable password) and only an
# admin verification flips it, after the provider completes their own password setup
# with a single-use token. The role is fixed to "responder" server-side and is never
# read from the request body.
_PROVIDER_CATEGORY_CHOICES = tuple(responder_service.PROVIDER_CATEGORIES)


@router.post("/admin/providers", status_code=201)
def create_provider_endpoint(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_admin),
):
    """Provision a provider record and issue a single-use setup token (ADMIN only).

    Required: badge_number, display_name. Optional: provider_category, organization,
    station_unit, jurisdiction, capabilities (list), contact. Any `role`, `verified`,
    `active`, `status`, or `password` field in the body is IGNORED — those are
    trusted-backend-only. The setup token is returned exactly once for out-of-band
    hand-off to the provider; it is never stored in plaintext or logged.
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid request body.")
    badge = str(body.get("badge_number") or "").strip()
    display = str(body.get("display_name") or "").strip()
    if not badge or len(badge) > 40 or not display or len(display) > 120:
        raise HTTPException(status_code=422, detail="badge_number and display_name are required (bounded length).")
    category = responder_service._normalize_category(body.get("provider_category")) or "police"
    if category not in _PROVIDER_CATEGORY_CHOICES:
        raise HTTPException(status_code=422, detail="Unsupported provider category.")
    caps = body.get("capabilities") or []
    if not isinstance(caps, list) or len(caps) > 20:
        raise HTTPException(status_code=422, detail="capabilities must be a list of at most 20 tags.")
    caps = [str(c).strip().lower()[:40] for c in caps if str(c).strip()]
    if responder_service.get_responder(badge) is not None:
        raise HTTPException(status_code=409, detail="A provider with this badge number already exists.")

    rec = responder_service.create_responder_inert(
        badge_number=badge,
        officer_name=display,
        display_label=display,
        capabilities=caps,
        jurisdiction=str(body.get("jurisdiction") or "")[:120],
        provider_category=category,
        organization=str(body.get("organization") or "")[:120],
        station_unit=str(body.get("station_unit") or "")[:120],
        contact=str(body.get("contact") or "")[:120],
        active=True,
    )
    # Created with a random unusable password; the provider must set their own.
    responder_service.mark_password_unset(rec.get("responder_id"))
    try:
        token = responder_service.issue_setup_token(rec.get("responder_id"))
    except responder_service.SetupStoreUnavailable:
        raise HTTPException(status_code=503, detail="Provider setup store is unavailable. Try again later.")
    log_audit(actor_id=current_user.user_id, role=current_user.role, action="PROVIDER_CREATED",
              metadata={"responder_id": rec.get("responder_id"), "provider_category": category})
    return {
        "success": True,
        "provider": _admin_responder_view(rec),
        "provisioning_state": responder_service.provisioning_state(
            responder_service.get_responder_by_id(rec.get("responder_id")) or rec),
        # Shown ONCE. Hand off out-of-band; it expires and is single-use.
        "setup_token": token,
        "setup_token_expires_in_seconds": responder_service.SETUP_TOKEN_TTL_SECONDS,
    }


# ─── Admin Review of Authority Provider Registrations & Requests ────────────────
from services import provider_registration_service as prs  # noqa: E402


@router.get("/admin/provider-registrations")
def admin_list_provider_registrations_endpoint(
    status: str = None,
    current_user: AuthUser = Depends(require_admin),
):
    """List all provider registrations across jurisdictions (Admin only)."""
    rows = prs.list_registrations(status=status)
    return {"registrations": rows, "total": len(rows)}


@router.post("/admin/provider-registrations/{registration_id}/approve")
def admin_approve_provider_registration_endpoint(
    registration_id: str,
    current_user: AuthUser = Depends(require_admin),
):
    """Approve a pending provider registration (Admin only).

    Creates an INERT responder record and issues a single-use setup token.
    """
    try:
        doc = prs.approve_registration(
            registration_id=registration_id,
            reviewed_by=current_user.user_id,
            reviewed_by_role=current_user.role,
        )
        return {
            "success": True,
            "registration": doc,
            "setup_token": doc.get("setup_token"),
            "setup_token_expires_in_seconds": responder_service.SETUP_TOKEN_TTL_SECONDS,
            "responder": doc.get("responder"),
            "provisioning_state": doc.get("provisioning_state"),
        }
    except prs.RegistrationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (prs.RegistrationStateError, prs.RegistrationConflictError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/admin/provider-registrations/{registration_id}/reject")
def admin_reject_provider_registration_endpoint(
    registration_id: str,
    body: dict,
    current_user: AuthUser = Depends(require_admin),
):
    """Reject a pending provider registration with reason (Admin only)."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid request body.")
    reason = str(body.get("reason") or "").strip()
    try:
        doc = prs.reject_registration(
            registration_id=registration_id,
            reason=reason,
            reviewed_by=current_user.user_id,
            reviewed_by_role=current_user.role,
        )
        return {"success": True, "registration": doc}
    except prs.RegistrationValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except prs.RegistrationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except prs.RegistrationStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/admin/provider-requests")
def admin_list_provider_requests_endpoint(
    status: str = None,
    current_user: AuthUser = Depends(require_admin),
):
    """List provider suspension / revocation requests (Admin only)."""
    rows = prs.list_provider_requests(status=status)
    return {"requests": rows, "total": len(rows)}


@router.post("/admin/provider-requests/{request_id}/review")
def admin_review_provider_request_endpoint(
    request_id: str,
    body: dict,
    current_user: AuthUser = Depends(require_admin),
):
    """Review (approve or reject) a suspension or revocation request (Admin only)."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid request body.")
    action = str(body.get("action") or "").strip()
    notes = str(body.get("notes") or "").strip()
    try:
        doc = prs.review_provider_request(
            request_id=request_id,
            action=action,
            review_notes=notes,
            reviewed_by=current_user.user_id,
            reviewed_by_role=current_user.role,
        )
        return {"success": True, "request": doc}
    except prs.RegistrationValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except prs.RegistrationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except prs.RegistrationStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

