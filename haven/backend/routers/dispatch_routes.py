"""Rapid Response Network HTTP API — human-approved dispatch + responder actions.

Endpoint groups and their trust boundary:

  AUTHORITY (require_authority) — the ONLY way a dispatch is ever created. HAVEN
  never auto-dispatches; a dispatch exists only because an authenticated authority
  pressed "Dispatch help". The incident location is resolved SERVER-SIDE from the
  case's own GPS fix (never taken from the request body), so a dispatcher cannot
  redirect a unit to an arbitrary point.

  RESPONDER (require_responder) — a responder manages ONLY their own availability,
  location, offers, and the dispatch they are assigned to. require_responder is
  strict (role=="responder" only), so an authority/admin token cannot act as a
  unit and a user token cannot reach these at all.

  VICTIM (get_current_user) — may read the minimal, truthful status of the dispatch
  for a case they own (safe unit label + help_on_the_way only). Never victim PII of
  anyone, never a responder's identity beyond the safe label.

All live WebSocket fan-out of state changes goes through dispatch_notify intents
returned by the engine; this router only transports them.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Body, status

from auth import AuthUser, require_authority, require_responder, get_current_user
from models.schemas import (
    ResponderDispatchCreateModel, ResponderStatusModel, ResponderLocationModel,
    ResponderDutyModel,
)
from services import dispatch_service, responder_service
from services.db import sos_events, sos_cases
from services.dispatch_notify import emit_intents
from services.geo_validation import (
    finite_or_none, finite_in_range, haversine_meters,
    LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX,
)
from services.incident_location import resolve_incident_point
from services.audit_service import log_audit
from rate_limiter import rate_limit_dependency

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Rapid Response Network"])

_OBSERVER_ROLES = ("authority", "admin", "police", "protection_officer")

# ─────────────────────────────── helpers ──────────────────────────────────────
def _responder_self_view(rec: Dict[str, Any]) -> Dict[str, Any]:
    """A responder's view of their OWN record — never the password hash/salt."""
    if not rec:
        return {}
    return {
        "responder_id": rec.get("responder_id"),
        "badge_number": rec.get("badge_number"),
        "display_label": rec.get("display_label"),
        "role": rec.get("role", "responder"),
        "active": bool(rec.get("active", False)),
        "verified": bool(rec.get("verified", False)),
        "status": rec.get("status"),
        "duty_status": rec.get("duty_status") or "OFF_DUTY",
        "capabilities": rec.get("capabilities", []),
        "jurisdiction": rec.get("jurisdiction", ""),
        "current_location": rec.get("current_location"),
        "location_updated_at": (
            rec.get("location_updated_at").isoformat()
            if hasattr(rec.get("location_updated_at"), "isoformat") else rec.get("location_updated_at")
        ),
        "assigned_dispatch_id": rec.get("assigned_dispatch_id"),
    }


def _resolve_incident_location(case_id: str):
    """Resolve the incident coordinates + case owner SERVER-SIDE (never from client).

    Pulls the live GPS fix, the sos_event row, and the sos_case row, then hands
    all three to the canonical resolver (services.incident_location), which
    understands every location shape HAVEN actually stores — numeric
    latitude/longitude, a GeoJSON Point, or the human-readable "lat, lng" string
    the authority case card renders — and returns one validated point. lng/lat
    are both None when NO source carries a valid fix, so the caller refuses to
    dispatch rather than fabricate a location.

    The dispatch REQUEST BODY is never consulted here: identity of the point
    comes only from stored case/event data and the authenticated live stream.
    """
    # Fields that may carry a location in any of the supported shapes.
    _LOC_PROJECTION = {
        "_id": 0, "user_id": 1, "jurisdiction": 1,
        "latitude": 1, "longitude": 1,
        "location": 1, "incident_location": 1,
        "current_location": 1, "last_location": 1,
    }

    # 1. Live in-memory fix (an event currently broadcasting over /ws/track).
    live_fix = None
    try:
        from main import tracking_manager
        cached = tracking_manager.latest_locations.get(case_id)
        if isinstance(cached, dict):
            live_fix = cached
    except Exception:
        live_fix = None

    # 2. Stored sos_event row (owner + any fix), matched by event_id == case_id.
    event_doc = None
    try:
        ev_coll = sos_events()
        if ev_coll is not None:
            event_doc = ev_coll.find_one({"event_id": case_id}, _LOC_PROJECTION)
    except Exception:
        event_doc = None

    # 3. The sos_case row (owner + any fix), matched by case_id.
    case_doc = None
    try:
        cs_coll = sos_cases()
        if cs_coll is not None:
            case_doc = cs_coll.find_one({"case_id": case_id}, _LOC_PROJECTION)
    except Exception:
        case_doc = None

    return resolve_incident_point(live_fix, event_doc, case_doc)


def _requester_owns_case(user_id: Optional[str], d: Dict[str, Any]) -> bool:
    """True when `user_id` is the victim/owner of the dispatch's case.

    Checks the dispatch's internal victim_user_id first, then falls back to the
    case/event owner so a victim can see their own dispatch even if victim_user_id
    was not captured at create time.
    """
    if not user_id:
        return False
    if d.get("victim_user_id") and str(d.get("victim_user_id")) == str(user_id):
        return True
    case_id = d.get("case_id")
    try:
        ev_coll = sos_events()
        if ev_coll is not None:
            ev = ev_coll.find_one({"event_id": case_id}, {"_id": 0, "user_id": 1})
            if ev and str(ev.get("user_id", "")) == str(user_id):
                return True
    except Exception:
        pass
    try:
        cs_coll = sos_cases()
        if cs_coll is not None:
            cs = cs_coll.find_one({"case_id": case_id}, {"_id": 0, "user_id": 1})
            if cs and str(cs.get("user_id", "")) == str(user_id):
                return True
    except Exception:
        pass
    return False


def _purge_dispatch_room(dispatch_id: str) -> None:
    """Drop the cached live responder location once a dispatch ends (no stale fix)."""
    try:
        from main import dispatch_manager
        dispatch_manager.purge_location(dispatch_id)
    except Exception:
        pass


def _clean_point(coords: Any) -> Optional[Dict[str, float]]:
    """A clean {lat,lng} from stored GeoJSON [lng, lat], or None.

    This is a DELIBERATE, authority-only projection of the unit's position so the
    Emergency Command map can plot eligible/offered/assigned units as real markers
    around the incident (an explicit product decision). It is minimal — just the
    coordinate pair, finiteness-checked — and NEVER the raw `current_location`
    GeoJSON blob or any accuracy/metadata. It is returned ONLY by authority-gated
    endpoints; the victim `public_view` path never calls this and carries no
    responder coordinates at all.
    """
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return None
    lng_val = finite_or_none(coords[0])
    lat_val = finite_or_none(coords[1])
    if lng_val is None or lat_val is None:
        return None
    if not (LAT_MIN <= lat_val <= LAT_MAX and LNG_MIN <= lng_val <= LNG_MAX):
        return None
    return {"lat": round(lat_val, 6), "lng": round(lng_val, 6)}


def _nearby_responder_view(rec: Dict[str, Any], inc_lng: float, inc_lat: float) -> Dict[str, Any]:
    """SAFE, authority-facing summary of ONE eligible responder near an incident.

    This is operational VISIBILITY only — it is deliberately NOT an assignment
    handle. The authority cannot force a unit onto a dispatch by picking from this
    list; the engine still auto-offers the nearest eligible unit on POST /dispatch
    and that unit must ACCEPT. So we expose only what an authority legitimately
    needs to understand coverage, and nothing that identifies the officer:
      - the SAFE display_label ("Verified Response Unit HR-204"), never officer_name
      - responder_id (the opaque "RESP-{badge}" handle, already in the authority
        dispatch view), never the raw badge_number/phone/user_id
      - straight-line distance to the incident (metres)
      - how stale their last fix is, so the authority can judge the distance
      - a clean {lat,lng} `location` for the authority Emergency Command map

    DELIBERATE EXPOSURE (authority-only): `location` is a minimal {lat,lng} pair so
    eligible/assigned units plot as real markers around the incident. This is an
    explicit product decision for the authority ops map ONLY — it is returned here
    behind require_authority and never on the victim `public_view` path. It is NOT
    the raw `current_location` GeoJSON blob and carries no accuracy/metadata. Still
    never exposed: officer_name, badge_number, phone, internal user_id, credentials.
    distance_m is computed server-side from the stored fix; distance_type is always
    "straight_line" and there is NO ETA (consistent with the rest of the RRN).
    """
    loc = rec.get("current_location") or {}
    coords = loc.get("coordinates") if isinstance(loc, dict) else None

    ts = rec.get("location_updated_at")
    age_seconds = None
    if isinstance(ts, datetime):
        age_seconds = max(0, int((datetime.utcnow() - ts).total_seconds()))
    location_fresh = (
        age_seconds is not None
        and age_seconds <= dispatch_service.RESPONDER_LOCATION_MAX_AGE_SECONDS
    )

    # A STALE or unknown fix is never presented as a current position: neither the
    # coordinate nor a distance computed from it is returned. The freshness flag and
    # age are kept so the authority can see that the unit exists and why it is withheld.
    distance_m = None
    location = None
    if location_fresh and isinstance(coords, (list, tuple)) and len(coords) == 2:
        # Stored GeoJSON is [lng, lat]; haversine_meters takes (lat, lng, lat, lng).
        distance_m = haversine_meters(inc_lat, inc_lng, coords[1], coords[0])
        if distance_m is not None:
            distance_m = round(distance_m)
        location = _clean_point(coords)

    return {
        "responder_id": rec.get("responder_id"),
        "display_label": rec.get("display_label"),
        "status": rec.get("status"),
        "capabilities": rec.get("capabilities", []),
        "jurisdiction": rec.get("jurisdiction", ""),
        "distance_m": distance_m,
        "distance_type": "straight_line",
        "location_age_seconds": age_seconds,
        "location_fresh": location_fresh,
        "location": location,
    }


def _network_responder_view(rec: Dict[str, Any]) -> Dict[str, Any]:
    """SAFE, authority-facing roster summary of ONE verified responder (network-wide).

    Backs the authority-only Response Network view (counts + roster + optional
    network map). Like _nearby_responder_view this is VISIBILITY only — there is NO
    assignment handle here either; a roster row cannot be forced onto a dispatch.

    Exposes only what an ops centre needs to understand its own coverage: the safe
    label, duty/assignment booleans, status, capabilities, jurisdiction, and — for
    an on-duty unit with a FRESH fix — a clean {lat,lng} `location` (same deliberate,
    authority-only exposure as the nearby view; never on the victim path). A stale
    or missing fix yields location=None rather than a fabricated point. Never
    exposed: officer_name, badge_number, phone, internal user_id, credentials, the
    raw GeoJSON blob, or which specific dispatch a busy unit holds.
    """
    ts = rec.get("location_updated_at")
    age_seconds = None
    if isinstance(ts, datetime):
        age_seconds = max(0, int((datetime.utcnow() - ts).total_seconds()))
    location_fresh = (
        age_seconds is not None
        and age_seconds <= dispatch_service.RESPONDER_LOCATION_MAX_AGE_SECONDS
    )
    on_duty = (
        bool(rec.get("active", False))
        and bool(rec.get("verified", False))
        and responder_service.is_on_duty(rec)
    )
    assigned = bool(rec.get("assigned_dispatch_id")) or rec.get("status") == "BUSY"

    loc = rec.get("current_location") or {}
    coords = loc.get("coordinates") if isinstance(loc, dict) else None
    # Only plot a unit that is on duty AND has a fresh fix; otherwise withhold.
    location = _clean_point(coords) if (on_duty and location_fresh) else None

    return {
        "responder_id": rec.get("responder_id"),
        "display_label": rec.get("display_label"),
        "status": rec.get("status"),
        "capabilities": rec.get("capabilities", []),
        "jurisdiction": rec.get("jurisdiction", ""),
        "on_duty": on_duty,
        "assigned": assigned,
        "location": location,
        "location_fresh": location_fresh,
        "location_age_seconds": age_seconds,
    }


# ───────────────────────────── AUTHORITY endpoints ────────────────────────────
@router.post("/dispatch", status_code=status.HTTP_201_CREATED)
async def create_dispatch_endpoint(
    payload: ResponderDispatchCreateModel,
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Human-approved dispatch. Authority-only; HAVEN never auto-dispatches.

    The incident coordinates are resolved on the server from the case's own GPS
    fix — the request body cannot set them. If no numeric fix is known we refuse
    (409) rather than invent a location.
    """
    case_id = (payload.case_id or "").strip()
    if not case_id:
        raise HTTPException(status_code=422, detail="case_id is required.")

    lng, lat, victim_user_id, jurisdiction = _resolve_incident_location(case_id)
    if lng is None or lat is None:
        log_audit(actor_id=current_user.user_id, role=current_user.role,
                  action="DISPATCH_CREATE_BLOCKED", case_id=case_id, result="denied",
                  reason="no_incident_location", metadata={"case_id": case_id})
        raise HTTPException(
            status_code=409,
            detail="No known incident location for this case. A live GPS fix is required before dispatching help.",
        )

    result = dispatch_service.create_dispatch(
        case_id=case_id,
        created_by=current_user.user_id,
        created_by_role=current_user.role,
        incident_lng=lng, incident_lat=lat,
        required_capability=payload.required_capability,
        radius_m=payload.radius_m,
        notes=payload.notes or "",
        incident_jurisdiction=jurisdiction,
        victim_user_id=victim_user_id,
    )
    err = result.get("error")
    if err == "duplicate":
        existing = result.get("dispatch") or {}
        raise HTTPException(
            status_code=409,
            detail=f"An active dispatch already exists for this case (dispatch_id={existing.get('dispatch_id')}).",
        )
    if err == "bad_location":
        raise HTTPException(status_code=409, detail="Resolved incident location was invalid.")

    await emit_intents(result.get("notify"))
    return {
        "success": True,
        "offered": result.get("offered", False),
        "eligible_provider_count": result.get("eligible_provider_count", 0),
        "dispatch": dispatch_service.public_view(result.get("dispatch"), "authority"),
    }


@router.get("/dispatch")
def list_dispatches_endpoint(
    active_only: bool = False,
    current_user: AuthUser = Depends(require_authority),
):
    """Authority queue of dispatches (fullest operational view; no victim PII)."""
    rows = dispatch_service.list_dispatches(active_only=active_only)
    return {"dispatches": [dispatch_service.public_view(d, "authority") for d in rows]}


@router.get("/dispatch/by-case/{case_id}")
def dispatch_by_case_endpoint(
    case_id: str = Path(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Victim/observer read of the dispatch for a case.

    An authority/admin sees the operational view; the case owner sees the truthful
    minimal victim view (safe unit label + help_on_the_way). Anyone else is denied.
    Declared before /dispatch/{dispatch_id} so the literal path wins the route match.
    """
    d = dispatch_service.get_dispatch_by_case(case_id)
    if not d:
        return {"dispatch": None}
    role = (current_user.role or "").lower()
    if role in _OBSERVER_ROLES:
        return {"dispatch": dispatch_service.public_view(d, "authority")}
    if _requester_owns_case(current_user.user_id, d):
        return {"dispatch": dispatch_service.public_view(d, "victim")}
    raise HTTPException(status_code=403, detail="You are not authorized to view this dispatch.")


@router.get("/dispatch/rrn/metrics")
def rrn_metrics_endpoint(current_user: AuthUser = Depends(require_authority)):
    """Authority-only live counts for the Rapid Response Center summary cards.

    Every number is derived from real stored rows (dispatch_service.status_counts
    + responder_service.availability_counts) — nothing is fabricated or estimated.
    Counts only: no incident, responder identity, location, or victim PII crosses
    this boundary. Declared before /dispatch/{dispatch_id} so the literal 'rrn'
    segment is never swallowed by the id route.
    """
    metrics = {
        **dispatch_service.status_counts(),
        **responder_service.availability_counts(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    return {"metrics": metrics}


@router.get("/dispatch/rrn/nearby/{case_id}")
def rrn_nearby_endpoint(
    case_id: str = Path(...),
    current_user: AuthUser = Depends(require_authority),
):
    """Authority-only VISIBILITY of eligible responders near a case's incident.

    This is NOT a force-assign surface. The incident point is resolved SERVER-SIDE
    from the case's own stored GPS fix (never from the request); the responder set
    is produced by the SAME deterministic engine predicate used for real dispatch
    (responder_service.find_eligible — eligibility first, nearest-first), so the
    frontend can never widen or re-rank who is eligible. Each unit is returned via
    _nearby_responder_view (safe label + straight-line distance + fix age only; no
    raw GPS, officer identity, or victim PII). When no valid incident fix exists we
    say so and return an empty list rather than inventing a location.
    """
    lng, lat, _victim_user_id, jurisdiction = _resolve_incident_location(case_id)
    if lng is None or lat is None:
        return {"incident_resolved": False, "responders": []}

    eligible = responder_service.find_eligible(
        longitude=lng,
        latitude=lat,
        radius_m=dispatch_service.DISPATCH_DEFAULT_RADIUS_M,
        incident_jurisdiction=jurisdiction or None,
        max_age_seconds=dispatch_service.RESPONDER_LOCATION_MAX_AGE_SECONDS,
    )
    responders_view = [_nearby_responder_view(rec, lng, lat) for rec in eligible]
    return {
        "incident_resolved": True,
        "incident_jurisdiction": jurisdiction or "",
        "radius_m": dispatch_service.DISPATCH_DEFAULT_RADIUS_M,
        "responders": responders_view,
    }


@router.get("/dispatch/rrn/network")
def rrn_network_endpoint(current_user: AuthUser = Depends(require_authority)):
    """Authority-only overview of the whole verified-responder network.

    This is NOT incident-specific and NOT an assignment surface — it is the ops
    centre's roster: who is on duty, their status/capabilities/jurisdiction, and
    (for on-duty units with a fresh fix) a clean {lat,lng} for the network map.
    The SAME deterministic engine still decides eligibility and assignment on
    POST /dispatch; nothing here can pick, rank, or force a unit.

    Only VERIFIED + ACTIVE accounts are included (an unverified/inactive row is not
    a real unit). Every row is the safe _network_responder_view — no officer
    identity, phone, badge, internal id, credentials, raw GeoJSON, or victim PII.
    `summary` reuses responder_service.availability_counts() so the roster totals
    match the summary-card metrics exactly. Declared before /dispatch/{dispatch_id}
    so the literal 'rrn' segment is never swallowed by the id route.
    """
    roster = [
        _network_responder_view(rec)
        for rec in responder_service.list_responders()
        if rec.get("active", False) and rec.get("verified", False)
    ]
    # Presentation default: available units first, then busy, then the rest; the
    # frontend may re-sort, but this is a sensible server-side baseline. Ordering
    # is cosmetic only and does not affect eligibility or assignment.
    rank = {"AVAILABLE": 0, "BUSY": 1}
    roster.sort(key=lambda r: (rank.get(r.get("status") or "", 2),
                               str(r.get("display_label") or "")))
    return {
        "summary": responder_service.availability_counts(),
        "responders": roster,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/dispatch/rrn/providers")
def rrn_providers_endpoint(current_user: AuthUser = Depends(require_authority)):
    """Authority-only READ of the provider roster (no credentials, no history).

    AUTHORITY may view provider records and availability. Creation, verification,
    activation and role changes are ADMIN-only (see /admin/providers). Each row is
    the safe network projection plus provider metadata; no password material, no
    setup tokens, no contact details, no location history.
    """
    rows = []
    for rec in responder_service.list_responders():
        view = _network_responder_view(rec)
        view.update({
            "verified": bool(rec.get("verified", False)),
            "active": bool(rec.get("active", False)),
            "duty_status": rec.get("duty_status") or "OFF_DUTY",
            "provider_category": rec.get("provider_category") or "police",
            "organization": rec.get("organization") or "",
            "station_unit": rec.get("station_unit") or "",
            "active_dispatch_id_present": bool(rec.get("assigned_dispatch_id")),
            "provisioning_state": responder_service.provisioning_state(rec),
            "push_subscribed": bool(rec.get("push_subscription")),
        })
        rows.append(view)
    rows.sort(key=lambda r: (str(r.get("display_label") or "")))
    return {"providers": rows, "generated_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/dispatch/rrn/active-responders")
def rrn_active_responders_endpoint(current_user: AuthUser = Depends(require_authority)):
    """Authority-only roster of every responder currently holding an ACTIVE dispatch
    in the live-tracking window (ACCEPTED / EN_ROUTE / ARRIVED).

    READ-ONLY and authority-only. Returns the safe per-responder projection
    (_nearby_responder_view) joined to the live dispatch context needed for the
    Emergency Command Center: dispatch_id, case_id, dispatch_status (tracking-window
    statuses only), straight-line distance to the incident, and NO ETA. No officer
    identity, phone, badge, internal user_id, raw GeoJSON, or victim PII.

    This is VISIBILITY only — it never assigns or re-ranks anyone. The incident
    point is read from the stored dispatch record (server-side). Declared before
    /dispatch/{dispatch_id} so the literal 'rrn' segment is never swallowed by the
    id route.
    """
    rows = dispatch_service.active_assigned_responders()
    return {"active_responders": rows, "generated_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/dispatch/{dispatch_id}")
def get_dispatch_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_authority),
):
    d = dispatch_service.get_dispatch(dispatch_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    return {"dispatch": dispatch_service.public_view(d, "authority")}


@router.get("/dispatch/{dispatch_id}/timeline")
def dispatch_timeline_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_authority),
):
    """Authority-only chronological state-change log for one dispatch.

    Reads the append-only response_events log via dispatch_service.get_dispatch_timeline,
    which already restricts each entry's detail to safe identifiers/outcomes (no raw
    GPS, no victim PII). 404 if the dispatch does not exist so an authority cannot
    probe for ids by watching for empty-vs-missing timelines.
    """
    d = dispatch_service.get_dispatch(dispatch_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    return {"timeline": dispatch_service.get_dispatch_timeline(dispatch_id)}


@router.get("/dispatch/{dispatch_id}/offers")
def get_dispatch_offers_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_authority),
):
    """Authority-only visibility into all broadcast offers sent for this emergency.

    Returns the status of every provider attempt (PENDING, ACCEPTED, DECLINED,
    TIMEOUT, CANCELLED) along with safe display labels and straight-line distance.
    Never exposes officer identity, badge, phone, or internal IDs.
    """
    d = dispatch_service.get_dispatch(dispatch_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    return {"offers": dispatch_service.get_offers_for_dispatch(dispatch_id)}


@router.post("/dispatch/{dispatch_id}/cancel")
async def cancel_dispatch_endpoint(
    dispatch_id: str = Path(...),
    body: Optional[dict] = Body(None),
    current_user: AuthUser = Depends(require_authority),
):
    reason = ""
    if isinstance(body, dict):
        reason = str(body.get("reason") or "")[:500]
    d, err, notify = dispatch_service.cancel_dispatch(
        dispatch_id, current_user.user_id, current_user.role, reason=reason)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    if err == "already_terminal":
        raise HTTPException(status_code=409, detail="Dispatch is already in a terminal state.")
    await emit_intents(notify)
    _purge_dispatch_room(dispatch_id)
    return {"success": True, "dispatch": dispatch_service.public_view(d, "authority")}


# ───────────────────────────── RESPONDER endpoints ────────────────────────────
@router.get("/responder/me")
def responder_me_endpoint(current_user: AuthUser = Depends(require_responder)):
    """The responder's own account state (availability, verification, assignment)."""
    rec = responder_service.get_responder_by_id(current_user.user_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    return {"responder": _responder_self_view(rec)}


@router.get("/responder/active-dispatch")
def responder_active_dispatch_endpoint(current_user: AuthUser = Depends(require_responder)):
    """The responder's OWN currently-assigned dispatch (responder view), or null.

    Lets a responder re-hydrate an in-progress assignment after a reload. Identity
    comes ONLY from the verified token: the dispatch is resolved from the
    responder's own record and then re-checked to be assigned to THIS responder, so
    a responder can never read a dispatch that is not theirs by guessing an id.
    No victim PII is present on the responder view.
    """
    rec = responder_service.get_responder_by_id(current_user.user_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    did = rec.get("assigned_dispatch_id")
    if not did:
        return {"dispatch": None}
    d = dispatch_service.get_dispatch(did)
    if not d or str(d.get("assigned_responder_id") or "") != str(current_user.user_id):
        # Record points at a dispatch that is not (any longer) ours — report none.
        return {"dispatch": None}
    return {"dispatch": dispatch_service.public_view(d, "responder")}


@router.post("/responder/status")
def responder_status_endpoint(
    payload: ResponderStatusModel,
    current_user: AuthUser = Depends(require_responder),
):
    """Responder toggles their OWN availability (OFFLINE/AVAILABLE/UNAVAILABLE).

    BUSY is server-controlled and rejected here; a responder holding a live
    dispatch cannot flip availability (prevents silently abandoning an incident).
    """
    rec, err = responder_service.set_self_status(current_user.user_id, payload.status)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Responder account not found.")
    if err == "bad_status":
        raise HTTPException(
            status_code=422,
            detail="Status must be one of OFFLINE, AVAILABLE, UNAVAILABLE (BUSY is set by the system).",
        )
    if err == "inactive":
        raise HTTPException(status_code=403, detail="This provider account is inactive or suspended.")
    if err == "assigned":
        raise HTTPException(
            status_code=409,
            detail="You cannot change availability while assigned to a live dispatch.",
        )
    log_audit(actor_id=current_user.user_id, role="responder", action="RESPONDER_STATUS_SET",
              result="success", metadata={"status": (rec or {}).get("status")})
    return {"success": True, "responder": _responder_self_view(rec)}


@router.post("/responder/duty")
def responder_duty_endpoint(
    payload: ResponderDutyModel,
    current_user: AuthUser = Depends(require_responder),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Responder goes ON_DUTY or OFF_DUTY (their OWN record only).

    ON_DUTY requires explicit location-sharing consent in the request body; without
    it the unit is not put on duty (no operational GPS is collected without consent).
    OFF_DUTY stops new location collection, clears the stored fix, and is refused
    while the unit holds a live assignment.
    """
    want = (payload.duty or "").strip().upper()
    if want == "ON_DUTY" and payload.location_sharing_consent is not True:
        raise HTTPException(
            status_code=422,
            detail="Going on duty requires explicit consent to share your operational location.",
        )
    rec, err = responder_service.set_duty(current_user.user_id, want)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Responder account not found.")
    if err == "inactive":
        raise HTTPException(status_code=403, detail="This provider account is inactive or suspended.")
    if err == "bad_duty":
        raise HTTPException(status_code=422, detail="duty must be ON_DUTY or OFF_DUTY.")
    if err == "assigned":
        raise HTTPException(
            status_code=409,
            detail="You cannot go off duty while assigned to a live dispatch.",
        )
    log_audit(
        actor_id=current_user.user_id, role="responder",
        action="PROVIDER_WENT_ON_DUTY" if want == "ON_DUTY" else "PROVIDER_WENT_OFF_DUTY",
        result="success", metadata={"duty_status": want},
    )
    if want == "ON_DUTY":
        log_audit(actor_id=current_user.user_id, role="responder",
                  action="PROVIDER_LOCATION_SHARING_STARTED", result="success", metadata={})
    else:
        log_audit(actor_id=current_user.user_id, role="responder",
                  action="PROVIDER_LOCATION_SHARING_STOPPED", result="success", metadata={})
    return {"success": True, "responder": _responder_self_view(rec)}


def _parse_device_time(raw):
    """Parse the device's GPS timestamp (ISO-8601). None when absent or unparseable,
    in which case the server falls back to arrival time. Never trusts garbage."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 64:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/responder/location")
def responder_location_endpoint(
    payload: ResponderLocationModel,
    current_user: AuthUser = Depends(require_responder),
    _=Depends(rate_limit_dependency(max_requests=120, window_seconds=60)),
):
    """Responder reports their OWN live GPS fix (used for eligibility + the map).

    Coordinates are validated and stored as GeoJSON [lng, lat]; a client cannot
    report another unit's location (identity is the verified token's responder_id).
    Refused (409) while OFF_DUTY: no operational location is collected off duty.
    """
    if not (finite_in_range(payload.longitude, LNG_MIN, LNG_MAX)
            and finite_in_range(payload.latitude, LAT_MIN, LAT_MAX)):
        raise HTTPException(status_code=422, detail="Invalid coordinates.")
    current = responder_service.get_responder_by_id(current_user.user_id)
    if not current:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    if not responder_service.is_on_duty(current):
        raise HTTPException(
            status_code=409,
            detail="Location sharing is only accepted while you are on duty.",
        )
    acc = finite_or_none(getattr(payload, "accuracy", None))
    fix_time = _parse_device_time(getattr(payload, "timestamp", None))
    rec = responder_service.update_location(
        current_user.user_id, payload.longitude, payload.latitude, accuracy=acc,
        fix_time=fix_time)
    if not rec:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    if rec.get("fix_rejected"):
        raise HTTPException(status_code=422, detail="Location timestamp is in the future. Check the device clock.")
    lu = rec.get("location_updated_at")
    if rec.get("fix_superseded"):
        # A newer fix is already stored; this older one is not applied (not an error for the client).
        return {"success": True, "applied": False, "reason": "superseded_by_newer_fix",
                "location_updated_at": lu.isoformat() if hasattr(lu, "isoformat") else lu}
    return {
        "applied": True,
        "success": True,
        "location_updated_at": lu.isoformat() if hasattr(lu, "isoformat") else lu,
    }


@router.get("/responder/push/config")
def responder_push_config_endpoint(current_user: AuthUser = Depends(require_responder)):
    """Public VAPID key for PushManager.subscribe, or configured=false.

    Only the PUBLIC key is ever returned. VAPID_PRIVATE_KEY never leaves the server.
    """
    from services import web_push
    pub = web_push.public_key_for_client()
    return {"configured": pub is not None, "vapid_public_key": pub}


@router.post("/responder/push-subscription")
def responder_push_subscribe_endpoint(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_responder),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60)),
):
    """Register this responder's Web Push subscription (their OWN record only)."""
    from services import web_push
    clean = web_push.validate_subscription(body.get("subscription") if isinstance(body, dict) else None)
    if clean is None:
        raise HTTPException(status_code=422, detail="Invalid push subscription.")
    rec = responder_service.set_push_subscription(current_user.user_id, clean)
    if not rec:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    log_audit(actor_id=current_user.user_id, role="responder",
              action="PROVIDER_PUSH_SUBSCRIBED", result="success", metadata={})
    return {"success": True, "subscribed": True}


@router.delete("/responder/push-subscription")
def responder_push_unsubscribe_endpoint(current_user: AuthUser = Depends(require_responder)):
    """Remove this responder's push subscription."""
    rec = responder_service.set_push_subscription(current_user.user_id, None)
    if not rec:
        raise HTTPException(status_code=404, detail="Responder account not found.")
    return {"success": True, "subscribed": False}


@router.get("/responder/offers")
def responder_offers_endpoint(current_user: AuthUser = Depends(require_responder)):
    """Pending, non-expired offers addressed to this responder (incident loc, no PII)."""
    return {"offers": dispatch_service.get_offers_for_responder(current_user.user_id)}


@router.post("/dispatch/{dispatch_id}/accept")
async def accept_offer_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_responder),
):
    """Accept the current offer — the single point where double-assignment is barred."""
    d, err, notify = dispatch_service.accept_offer(dispatch_id, current_user.user_id)
    # Emit first so a failed claim's re-offer intents still reach the next unit.
    await emit_intents(notify)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    if err == "not_offered":
        raise HTTPException(status_code=409, detail="This dispatch is not awaiting your acceptance.")
    if err == "offer_unavailable":
        raise HTTPException(status_code=409, detail="This offer was already taken or has expired.")
    if err == "responder_unavailable":
        raise HTTPException(status_code=409, detail="You are not currently available to accept this offer.")
    return {"success": True, "dispatch": dispatch_service.public_view(d, "responder")}


@router.post("/dispatch/{dispatch_id}/decline")
async def decline_offer_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_responder),
):
    """Decline the current offer; the dispatch re-offers to the next eligible unit."""
    d, err, notify = dispatch_service.decline_offer(dispatch_id, current_user.user_id)
    await emit_intents(notify)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    if err == "not_offered":
        raise HTTPException(status_code=409, detail="This dispatch is not awaiting your acceptance.")
    if err == "offer_unavailable":
        raise HTTPException(status_code=409, detail="This offer is no longer available to you.")
    return {"success": True}


async def _responder_progress(dispatch_id: str, responder_id: str, new_state: str):
    d, err, notify = dispatch_service.mark_progress(dispatch_id, responder_id, new_state)
    await emit_intents(notify)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Dispatch not found.")
    if err == "forbidden":
        raise HTTPException(status_code=403, detail="Only the assigned responder can update this dispatch.")
    if err == "bad_state":
        raise HTTPException(status_code=422, detail="Unknown progress state.")
    if err == "invalid_transition":
        raise HTTPException(status_code=409, detail="That status change is not allowed from the current state.")
    return {"success": True, "dispatch": dispatch_service.public_view(d, "responder")}


@router.post("/dispatch/{dispatch_id}/enroute")
async def responder_enroute_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_responder),
):
    return await _responder_progress(dispatch_id, current_user.user_id, dispatch_service.EN_ROUTE)


@router.post("/dispatch/{dispatch_id}/arrived")
async def responder_arrived_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_responder),
):
    return await _responder_progress(dispatch_id, current_user.user_id, dispatch_service.ARRIVED)


@router.post("/dispatch/{dispatch_id}/help-provided")
async def responder_help_provided_endpoint(
    dispatch_id: str = Path(...),
    current_user: AuthUser = Depends(require_responder),
):
    return await _responder_progress(dispatch_id, current_user.user_id, dispatch_service.HELP_PROVIDED)



