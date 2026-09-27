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
