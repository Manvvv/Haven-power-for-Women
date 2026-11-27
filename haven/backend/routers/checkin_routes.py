"""Emergency Safety Check-In Timer HTTP routes."""
from fastapi import APIRouter, Depends, HTTPException, Path

from auth import AuthUser, get_current_user
from models.schemas import SafetyCheckinCreateModel, SafetyCheckinExtendModel
from rate_limiter import rate_limit_dependency
from services import checkin_service

router = APIRouter(tags=["Emergency Check-In"])


@router.post("/check-in")
def start_checkin_endpoint(
    payload: SafetyCheckinCreateModel,
    current_user: AuthUser = Depends(get_current_user),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Start a persistent backend-scheduled safety check-in timer with explicit consent."""
    try:
        doc = checkin_service.create_checkin(
            current_user.user_id,
            duration_minutes=payload.duration_minutes,
            reminder_before_minutes=payload.reminder_before_minutes,
            activity_label=payload.activity_label or "",
            consent_acknowledged=payload.consent_acknowledged,
            allow_contact_escalation=payload.allow_contact_escalation,
            allow_authority_escalation=payload.allow_authority_escalation,
            manual_location=payload.manual_location or "",
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
        return {"success": True, "checkin": doc}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database unavailable")


@router.get("/check-in/active")
def get_active_checkin_endpoint(current_user: AuthUser = Depends(get_current_user)):
    """Fetch the authenticated user's currently active safety check-in, or null."""
    return {"checkin": checkin_service.get_active_checkin(current_user.user_id)}


@router.get("/check-in/history")
def get_checkin_history_endpoint(
    limit: int = 15,
    current_user: AuthUser = Depends(get_current_user),
):
    """Fetch recent check-in history for the authenticated user."""
    items = checkin_service.list_checkin_history(current_user.user_id, limit=limit)
    return {"checkins": items, "total": len(items)}


@router.post("/check-in/{checkin_id}/confirm-safe")
def confirm_safe_endpoint(
    checkin_id: str = Path(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Confirm user safety before/at expiry, stopping any pending escalation."""
    try:
        doc = checkin_service.confirm_safe(checkin_id, current_user.user_id)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not doc:
        raise HTTPException(status_code=404, detail="Active check-in timer not found.")
    return {"success": True, "checkin": doc}


@router.post("/check-in/{checkin_id}/extend")
def extend_checkin_endpoint(
    checkin_id: str = Path(...),
    payload: SafetyCheckinExtendModel = ...,
    current_user: AuthUser = Depends(get_current_user),
):
    """Extend an active check-in timer."""
    try:
        doc = checkin_service.extend_checkin(checkin_id, current_user.user_id, payload.extra_minutes)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not doc:
        raise HTTPException(status_code=404, detail="Active check-in timer not found.")
    return {"success": True, "checkin": doc}


@router.post("/check-in/{checkin_id}/cancel")
def cancel_checkin_endpoint(
    checkin_id: str = Path(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Cancel an active check-in timer cleanly."""
    try:
        doc = checkin_service.cancel_checkin(checkin_id, current_user.user_id)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not doc:
        raise HTTPException(status_code=404, detail="Active check-in timer not found.")
    return {"success": True, "checkin": doc}
