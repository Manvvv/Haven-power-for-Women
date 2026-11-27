"""Isolated Demo Mode routes (Phase 8).

All endpoints read/write strictly inside `demo_*` collections and NEVER trigger
real SMS, WhatsApp, authority dispatches, or responder alerts.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Path

from rate_limiter import rate_limit_dependency
from services import demo_service

router = APIRouter(prefix="/demo", tags=["Demo Mode"])


@router.get("/state")
def demo_state_endpoint(_=Depends(rate_limit_dependency(max_requests=60, window_seconds=60))):
    """Return full isolated demo sandbox snapshot (auto-seeds on first visit)."""
    return demo_service.get_demo_state()


@router.post("/reset")
def demo_reset_endpoint(_=Depends(rate_limit_dependency(max_requests=15, window_seconds=60))):
    """Reset and re-seed isolated demo_* collections."""
    return {"success": True, "state": demo_service.seed_demo_workspace(force_reset=True)}


@router.post("/sos")
def demo_submit_sos_endpoint(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Submit a simulated demo SOS incident (isolated to demo_cases)."""
    try:
        case = demo_service.submit_demo_sos(
            category=str((body or {}).get("category") or "immediate_danger"),
            description=str((body or {}).get("description") or "")[:1000],
            location=str((body or {}).get("location") or "")[:300],
            trigger_type=str((body or {}).get("trigger_type") or "demo_website_sos")[:40],
            voice_analysis=(body or {}).get("voice_analysis"),
        )
        return {"success": True, "is_demo": True, "simulation": True, "case": case}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/voice-sos/analyze")
def demo_voice_analyze_endpoint(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Run Voice AI extraction over a demo sample or edited transcript (non-dispatching)."""
    transcript = str((body or {}).get("transcript") or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="transcript is required")
    language = str((body or {}).get("language") or "en")
    return demo_service.analyze_demo_voice(transcript, language=language)


@router.post("/dispatch/{case_id}")
def demo_create_dispatch_endpoint(
    case_id: str = Path(...),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Demo Authority creates a simulated dispatch in demo_dispatches."""
    try:
        dispatch = demo_service.create_demo_dispatch(case_id)
        return {"success": True, "is_demo": True, "simulation": True, "dispatch": dispatch}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/dispatch/{dispatch_id}/respond")
def demo_respond_dispatch_endpoint(
    dispatch_id: str = Path(...),
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=40, window_seconds=60)),
):
    """Advance simulated dispatch lifecycle (accept -> enroute -> arrived -> help_provided -> resolve)."""
    action = str((body or {}).get("action") or "").strip().lower()
    try:
        dispatch = demo_service.advance_demo_dispatch(dispatch_id, action)
        return {"success": True, "is_demo": True, "simulation": True, "dispatch": dispatch}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/admin/providers/{registration_id}/approve")
def demo_admin_approve_endpoint(
    registration_id: str = Path(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Demo Admin approves a sample provider registration & activates Demo Responder."""
    try:
        result = demo_service.demo_admin_approve_provider(registration_id)
        return {"success": True, "is_demo": True, "simulation": True, **result}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
