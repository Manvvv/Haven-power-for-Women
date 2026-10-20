"""Rapid Response Network dispatch orchestration (deterministic, human-approved).

This is the engine behind the /dispatch/* and /responder/* endpoints. Its design
is governed by five hard rules:

  1. HUMAN-APPROVED ONLY. A dispatch is created exclusively by create_dispatch,
     which is reachable only from an authenticated AUTHORITY action. HAVEN never
     auto-dispatches. Nothing in here starts a dispatch on its own.
  2. DETERMINISTIC SELECTION. Which responder is eligible and which is offered is
     decided entirely by responder_service.find_eligible (hard predicates, then
     nearest-first). No AI and no client field participate in the decision.
  3. NEVER DOUBLE-ASSIGN. Acceptance is guarded by a Redis fast-lock PLUS an
     authoritative chain of single-document conditional updates (attempt →
     dispatch → responder). The Mongo conditional updates are the real guard, so
     correctness holds even if Redis is unavailable.
  4. TRUTHFUL, MINIMAL DISCLOSURE. Responders receive the incident location
     (operationally required) but no victim PII. Victims receive a safe unit
     label and a status that is only ever as advanced as reality (never "on the
     way" before an actual ACCEPT).
  5. BACKEND-OWNED TIMING. The accept window is DISPATCH_ACCEPT_TIMEOUT_SECONDS,
     snapshotted onto each dispatch; escalation is driven by process_expirations
     (pure + idempotent), never by a frontend timer.

Side-effect boundary: these functions are SYNC (pymongo is sync). They persist
state + audit + durable notifications themselves, and RETURN a list of live
"notification intents" for the async caller (router / background sweeper) to push
over WebSockets. This keeps the engine unit-testable without an event loop.
"""
import os
import copy
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from services.db import dispatch_requests, dispatch_attempts, response_events
from services import responder_service
from services.audit_service import log_audit
from services.notification_service import manager as notification_manager
from services.geo_validation import haversine_meters, finite_in_range, LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX
import rate_limiter

logger = logging.getLogger("haven_backend")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    """Parse a positive-int env var within [lo, hi], falling back on bad input."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


# BACKEND-owned accept window (never frontend-hardcoded). Snapshotted per dispatch
# so changing the env var does not retro-expire offers already in flight.
DISPATCH_ACCEPT_TIMEOUT_SECONDS = _env_int("DISPATCH_ACCEPT_TIMEOUT_SECONDS", 45, 5, 3600)
DISPATCH_DEFAULT_RADIUS_M = _env_int("DISPATCH_DEFAULT_RADIUS_M", 10_000, 100, 100_000)
DISPATCH_MIN_RADIUS_M = 100
DISPATCH_MAX_RADIUS_M = 100_000
RESPONDER_LOCATION_MAX_AGE_SECONDS = _env_int("RESPONDER_LOCATION_MAX_AGE_SECONDS", 300, 10, 86_400)
# How many eligible candidates to retain per search (bounds the escalation chain).
_MAX_CANDIDATES = 25

# ── Broadcast wave configuration (deterministic, backend-owned) ───────────────
# Waves are ascending radii; the first wave offers the nearest ~5-6 providers
# simultaneously. If nobody accepts, the search expands to the next wave, never
# re-offering a provider already tried. Example: 2000,5000,10000.
def _parse_radius_waves() -> List[int]:
    raw = os.getenv("DISPATCH_RADIUS_WAVES")
    if raw is None or not str(raw).strip():
        # Default aligns with the spec example and preserves the existing 10km max.
        return [2000, 5000, 10000]
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    waves: List[int] = []
    for p in parts:
        try:
            v = int(p)
        except (TypeError, ValueError):
            continue
        v = max(DISPATCH_MIN_RADIUS_M, min(DISPATCH_MAX_RADIUS_M, v))
        if v not in waves:
            waves.append(v)
    waves.sort()
    return waves if waves else [2000, 5000, 10000]

DISPATCH_RADIUS_WAVES: List[int] = _parse_radius_waves()
DISPATCH_MAX_PROVIDERS_PER_WAVE = _env_int("DISPATCH_MAX_PROVIDERS_PER_WAVE", 6, 1, 25)
# Per-wave accept window. Falls back to the global DISPATCH_ACCEPT_TIMEOUT_SECONDS
# when the wave-specific var is not set, preserving existing behaviour.
DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS = _env_int(
    "DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS", DISPATCH_ACCEPT_TIMEOUT_SECONDS, 5, 3600
)

# ── Dispatch finite-state machine ──────────────────────────────────────────────
CREATED, SEARCHING, OFFERED, ACCEPTED = "CREATED", "SEARCHING", "OFFERED", "ACCEPTED"
EN_ROUTE, ARRIVED, HELP_PROVIDED = "EN_ROUTE", "ARRIVED", "HELP_PROVIDED"
CANCELLED, EXPIRED, FAILED, RESOLVED = "CANCELLED", "EXPIRED", "FAILED", "RESOLVED"

TERMINAL_STATES = frozenset({CANCELLED, EXPIRED, FAILED, RESOLVED})
VALID_TRANSITIONS: Dict[str, frozenset] = {
    CREATED: frozenset({SEARCHING, CANCELLED, FAILED}),
    SEARCHING: frozenset({OFFERED, FAILED, CANCELLED}),
    OFFERED: frozenset({ACCEPTED, SEARCHING, EXPIRED, FAILED, CANCELLED}),
    ACCEPTED: frozenset({EN_ROUTE, ARRIVED, HELP_PROVIDED, CANCELLED, RESOLVED}),
    EN_ROUTE: frozenset({ARRIVED, HELP_PROVIDED, CANCELLED, RESOLVED}),
    ARRIVED: frozenset({HELP_PROVIDED, CANCELLED, RESOLVED}),
    HELP_PROVIDED: frozenset({RESOLVED, CANCELLED}),
    CANCELLED: frozenset(), EXPIRED: frozenset(), FAILED: frozenset(), RESOLVED: frozenset(),
}
# Responder-settable progress transitions (EN_ROUTE/ARRIVED/HELP_PROVIDED only).
RESPONDER_PROGRESS_STATES = frozenset({EN_ROUTE, ARRIVED, HELP_PROVIDED})

# Attempt (offer) response states.
PENDING, A_ACCEPTED, A_DECLINED, A_TIMEOUT, A_CANCELLED = (
    "PENDING", "ACCEPTED", "DECLINED", "TIMEOUT", "CANCELLED")

_DISPATCH_LOCK_NS = "haven:dispatch:lock:"


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES


def is_valid_transition(from_status: str, to_status: str) -> bool:
    return to_status in VALID_TRANSITIONS.get(from_status, frozenset())


# ── Minimal in-memory collection (dev / CI / tests only) ───────────────────────
# Mirrors the subset of the pymongo API the engine uses, with the SAME atomicity
# contract for the conditional updates that guard double-assignment: find_one_and
# _update and update_one run under a per-collection lock, so a matched document is
# claimed by exactly one caller even under concurrent threads.
class _MemoryCollection:
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    @staticmethod
    def _match(doc: Dict[str, Any], flt: Dict[str, Any]) -> bool:
        for k, cond in flt.items():
            v = doc.get(k)
            if isinstance(cond, dict):
                for op, operand in cond.items():
                    if op == "$nin":
                        if v in operand:
                            return False
                    elif op == "$in":
                        if v not in operand:
                            return False
                    elif op == "$ne":
                        if v == operand:
                            return False
                    elif op == "$lt":
                        if v is None or not (v < operand):
                            return False
                    elif op == "$lte":
                        if v is None or not (v <= operand):
                            return False
                    elif op == "$gte":
                        if v is None or not (v >= operand):
                            return False
                    elif op == "$exists":
                        if bool(operand) != (k in doc):
                            return False
                    else:
                        return False
            elif v != cond:
                return False
        return True

    @staticmethod
    def _apply(doc: Dict[str, Any], update: Dict[str, Any]) -> None:
        for op, fields in update.items():
            if op == "$set":
                doc.update(fields)
            elif op == "$addToSet":
                for k, val in fields.items():
                    arr = doc.setdefault(k, [])
                    if val not in arr:
                        arr.append(val)
            elif op == "$push":
                for k, val in fields.items():
                    doc.setdefault(k, []).append(val)

    def insert_one(self, doc):
        with self._lock:
            self._docs.append(copy.deepcopy(doc))
        return type("R", (), {"inserted_id": doc.get("_id")})()

    def find_one(self, flt, projection=None):
        with self._lock:
            for d in self._docs:
                if self._match(d, flt):
                    return copy.deepcopy(d)
        return None

    def find(self, flt=None, projection=None):
        flt = flt or {}
        with self._lock:
            return [copy.deepcopy(d) for d in self._docs if self._match(d, flt)]

    def update_one(self, flt, update, upsert=False):
        with self._lock:
            for d in self._docs:
                if self._match(d, flt):
                    self._apply(d, update)
                    return type("R", (), {"modified_count": 1, "matched_count": 1})()
            return type("R", (), {"modified_count": 0, "matched_count": 0})()

    def update_many(self, flt, update):
        with self._lock:
            count = 0
            for d in self._docs:
                if self._match(d, flt):
                    self._apply(d, update)
                    count += 1
            return type("R", (), {"modified_count": count, "matched_count": count})()

    def find_one_and_update(self, flt, update, return_document=None):
        with self._lock:
            for d in self._docs:
                if self._match(d, flt):
                    self._apply(d, update)
                    return copy.deepcopy(d)
        return None


_MEM = {
    "dispatch_requests": _MemoryCollection(),
    "dispatch_attempts": _MemoryCollection(),
    "response_events": _MemoryCollection(),
}


def _dispatches():
    c = dispatch_requests()
    return c if c is not None else _MEM["dispatch_requests"]


def _attempts():
    c = dispatch_attempts()
    return c if c is not None else _MEM["dispatch_attempts"]


def _events():
    c = response_events()
    return c if c is not None else _MEM["response_events"]


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if isinstance(dt, datetime) else (dt or None)


def _new_dispatch_id() -> str:
    return f"RRN-{_now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _new_attempt_id() -> str:
    return f"ATT-{_now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


# find_one_and_update return-document sentinel: real pymongo value when available,
# else None (the in-memory collection returns the post-update doc regardless).
try:  # pragma: no cover - import shape varies by driver
    from pymongo import ReturnDocument as _ReturnDocument
    _RET_AFTER = _ReturnDocument.AFTER
except Exception:  # pragma: no cover
    _RET_AFTER = None


def _safe_audit(actor_id, role, action, case_id=None, result="success", reason="", metadata=None):
    """Audit a dispatch action, never raising and never logging sensitive payloads.

    Only identifiers/outcomes are recorded (dispatch_id, attempt_id, responder_id,
    reason). No tokens, no secrets, no raw GPS history, no victim PII.
    """
    try:
        log_audit(actor_id=actor_id or "unknown", role=role or "unknown", action=action,
                  case_id=case_id, result=result, reason=reason, metadata=metadata or {})
    except Exception:
        pass


# ── Redis fast-lock (optimization only; Mongo conditional updates are the guard) ──
def _redis_required() -> bool:
    """Fail-closed policy for coordination locks (matches rate_limiter's production rule)."""
    return bool(getattr(rate_limiter, "IS_PRODUCTION", False)
                and getattr(rate_limiter, "REDIS_REQUIRED_IN_PRODUCTION", False))


def _acquire_lock(dispatch_id: str, ttl_ms: int = 5000) -> Tuple[bool, Optional[str]]:
    """Cross-process accept lock. Returns (acquired, key).

    Policy:
      * Redis configured and reachable: SET NX PX. A loser is refused (not acquired).
      * Redis unreachable/unconfigured in PRODUCTION (REDIS_REQUIRED_IN_PRODUCTION):
        FAIL CLOSED -> (False, None). The accept is refused rather than proceeding
        without cross-process coordination.
      * Redis unavailable in development: (True, None). The authoritative Mongo
        conditional updates still guarantee exactly one winner; this is labelled as
        single-process fallback, not distributed coordination.
    """
    try:
        mode, client = rate_limiter._resolve_backend()
    except Exception:
        mode, client = "memory", None
    if mode == "redis" and client is not None:
        key = f"{_DISPATCH_LOCK_NS}{dispatch_id}"
        try:
            ok = client.set(key, "1", nx=True, px=ttl_ms)
            return bool(ok), (key if ok else None)
        except Exception:
            return (False, None) if _redis_required() else (True, None)
    if _redis_required():
        return False, None
    return True, None


def _release_lock(key: Optional[str]) -> None:
    if not key:
        return
    try:
        _mode, client = rate_limiter._resolve_backend()
        if client is not None:
            client.delete(key)
    except Exception:
        pass


def _record_event(dispatch_id: str, event: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """Append an append-only state-change marker. Minimal — never raw GPS history."""
    try:
        _events().insert_one({
            "dispatch_id": dispatch_id,
            "event": event,
            "detail": detail or {},
            "at": _now(),
        })
    except Exception:
        pass


# ─────────────────────────── Public (role-scoped) views ───────────────────────
# Field exposure is deliberately minimized per audience. victim_user_id is NEVER
# returned to anyone; it exists only to address notifications.
def _responder_label(responder_id: Optional[str]) -> Optional[str]:
    if not responder_id:
        return None
    rec = responder_service.get_responder_by_id(responder_id)
    return (rec or {}).get("display_label") if rec else None


def _wave_label(waves: List[int], idx: int) -> str:
    """Human-readable label for a wave, e.g. '0–2 km' for 2000 at index 0."""
    if not waves or idx < 0 or idx >= len(waves):
        return ""
    lo = 0 if idx == 0 else waves[idx - 1]
    hi = waves[idx]
    # Render in km when >=1000, else metres.
    def fmt(m: int) -> str:
        return f"{m/1000:.0f} km" if m >= 1000 else f"{m} m"
    return f"{fmt(lo)}–{fmt(hi)}"


def _current_wave_radius(d: Dict[str, Any]) -> int:
    waves = d.get("radius_waves") or DISPATCH_RADIUS_WAVES
    idx = int(d.get("current_wave_index", 0))
    if 0 <= idx < len(waves):
        return int(waves[idx])
    return int(d.get("radius_m") or waves[-1] if waves else DISPATCH_DEFAULT_RADIUS_M)


def public_view(d: Dict[str, Any], audience: str) -> Dict[str, Any]:
    """Shape a dispatch document for a given audience: victim | responder | authority.

    Common truthful facts are shared; identity and operational detail are added
    only where that audience legitimately needs them. Straight-line distance is
    labelled as such and ETA is always null (never fabricated).
    """
    if not d:
        return {}
    status = d.get("status")
    base = {
        "dispatch_id": d.get("dispatch_id"),
        "case_id": d.get("case_id"),
        "status": status,
        "created_at": _iso(d.get("created_at")),
        "updated_at": _iso(d.get("updated_at")),
        "assigned_at": _iso(d.get("assigned_at")),
        "distance_type": "straight_line",
        "eta_minutes": None,
    }
    assigned = d.get("assigned_responder_id")

    if audience == "victim":
        # Truthful, minimal: a safe unit label only once a responder has accepted.
        base["responder_label"] = _responder_label(assigned) if assigned else None
        base["help_on_the_way"] = status in (ACCEPTED, EN_ROUTE, ARRIVED)
        return base

    if audience == "responder":
        # The responder needs the incident location to actually respond, plus the
        # offer window. No victim PII is present on the dispatch to leak.
        base["incident_location"] = d.get("incident_location")
        base["required_capability"] = d.get("required_capability")
        base["radius_m"] = d.get("radius_m")
        base["notes"] = d.get("notes") or ""
        base["offer_expires_at"] = _iso(d.get("offer_expires_at"))
        base["accept_timeout_seconds"] = d.get("accept_timeout_seconds")
        # Wave context for responder (no PII, just operational radius).
        if d.get("radius_waves"):
            base["radius_waves"] = d.get("radius_waves")
            base["current_wave_index"] = d.get("current_wave_index", 0)
            base["current_wave_label"] = _wave_label(d.get("radius_waves"), int(d.get("current_wave_index", 0)))
        return base

    # authority / admin: fullest operational view (still no victim PII beyond the
    # case id the authority already handles).
    waves = d.get("radius_waves") or DISPATCH_RADIUS_WAVES
    wave_idx = int(d.get("current_wave_index", 0)) if d.get("radius_waves") is not None else 0
    # Per-wave attempt counts (honest).
    # Materialise once: pymongo returns a Cursor (no len(), single-pass iteration),
    # while the in-memory store returns a list. Both backends must behave the same.
    all_attempts = (list(_attempts().find({"dispatch_id": d.get("dispatch_id")}))
                    if d.get("dispatch_id") else [])
    pending = sum(1 for a in all_attempts if a.get("response") == PENDING)
    declined = sum(1 for a in all_attempts if a.get("response") == A_DECLINED)
    timed_out = sum(1 for a in all_attempts if a.get("response") == A_TIMEOUT)
    cancelled = sum(1 for a in all_attempts if a.get("response") == A_CANCELLED)
    # Re-read after counts if we used find above - need fresh for base
    base.update({
        "created_by": d.get("created_by"),
        "created_by_role": d.get("created_by_role"),
        "assigned_responder_id": assigned,
        "responder_label": _responder_label(assigned) if assigned else None,
        "incident_location": d.get("incident_location"),
        "incident_jurisdiction": d.get("incident_jurisdiction") or "",
        "required_capability": d.get("required_capability"),
        "radius_m": d.get("radius_m"),
        "notes": d.get("notes") or "",
        "offer_expires_at": _iso(d.get("offer_expires_at")),
        "accept_timeout_seconds": d.get("accept_timeout_seconds"),
        "attempts_made": len(d.get("tried_responder_ids", [])),
        "eligible_provider_count": d.get("eligible_provider_count", len(d.get("tried_responder_ids", []))),
        "broadcast_attempt_ids": d.get("broadcast_attempt_ids", []),
        "resolved_at": _iso(d.get("resolved_at")),
        "cancel_reason": d.get("cancel_reason") or "",
        # Wave-aware fields (authority only, backend-owned).
        "radius_waves": d.get("radius_waves") or waves,
        "current_wave_index": d.get("current_wave_index", 0) if d.get("radius_waves") is not None else 0,
        "current_wave_label": _wave_label(d.get("radius_waves") or waves, wave_idx),
        "current_wave_radius_m": _current_wave_radius(d),
        "max_providers_per_wave": d.get("max_providers_per_wave") or DISPATCH_MAX_PROVIDERS_PER_WAVE,
        "wave_accept_timeout_seconds": d.get("wave_accept_timeout_seconds") or d.get("accept_timeout_seconds") or DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS,
        "offers_pending": pending,
        "offers_declined": declined,
        "offers_timeout": timed_out,
        "offers_cancelled": cancelled,
        "offers_accepted": sum(1 for a in all_attempts if a.get("response") == A_ACCEPTED),
        "total_offers": len(all_attempts),
    })
    return base


# ─────────────────────────────────── Getters ──────────────────────────────────
def get_dispatch(dispatch_id: str) -> Optional[Dict[str, Any]]:
    return _dispatches().find_one({"dispatch_id": dispatch_id})


def get_active_dispatch_for_case(case_id: str) -> Optional[Dict[str, Any]]:
    """The one non-terminal dispatch for a case, if any (duplicate-dispatch guard)."""
    for d in _dispatches().find({"case_id": case_id}):
        if not is_terminal(d.get("status")):
            return d
    return None


def get_dispatch_by_case(case_id: str) -> Optional[Dict[str, Any]]:
    """Most relevant dispatch for a case: the active one, else the most recent."""
    active = get_active_dispatch_for_case(case_id)
    if active:
        return active
    rows = list(_dispatches().find({"case_id": case_id}))
    if not rows:
        return None
    return sorted(rows, key=lambda r: r.get("created_at") or _now(), reverse=True)[0]


def list_dispatches(active_only: bool = False) -> List[Dict[str, Any]]:
    rows = _dispatches().find({})
    if active_only:
        rows = [r for r in rows if not is_terminal(r.get("status"))]
    return sorted(rows, key=lambda r: r.get("created_at") or _now(), reverse=True)


# ─────────────────────── Authority read: operational metrics ──────────────────
def status_counts() -> Dict[str, int]:
    """Live dispatch counts grouped by lifecycle phase (authority metrics only).

    Derived entirely from real stored dispatch rows — nothing is fabricated.
      active_dispatches     : every non-terminal dispatch.
      waiting_for_responder : CREATED / SEARCHING / OFFERED (no unit accepted yet).
      incidents_in_response : ACCEPTED / EN_ROUTE / ARRIVED / HELP_PROVIDED.
    Terminal dispatches (CANCELLED/EXPIRED/FAILED/RESOLVED) are not counted active.
    """
    active = waiting = in_response = 0
    for r in _dispatches().find({}):
        s = r.get("status")
        if is_terminal(s):
            continue
        active += 1
        if s in (CREATED, SEARCHING, OFFERED):
            waiting += 1
        elif s in (ACCEPTED, EN_ROUTE, ARRIVED, HELP_PROVIDED):
            in_response += 1
    return {
        "active_dispatches": active,
        "waiting_for_responder": waiting,
        "incidents_in_response": in_response,
    }


# ─────────────────────── Authority read: event timeline ───────────────────────
# Detail keys safe to surface to an authority (identifiers/outcomes it already
# sees via public_view). Explicitly NO raw GPS, NO victim PII, NO internal
# attempt bookkeeping beyond these.
_TIMELINE_SAFE_DETAIL = ("responder_id", "reason", "via")


def get_dispatch_timeline(dispatch_id: str) -> List[Dict[str, Any]]:
    """Chronological state-change markers for one dispatch (authority read).

    Reads the append-only response_events log (previously write-only) and returns
    a minimal, truthful timeline: each entry is {event, at, detail} where detail
    is restricted to _TIMELINE_SAFE_DETAIL. Returns [] for an unknown dispatch.
    """
    rows = _events().find({"dispatch_id": dispatch_id})
    out: List[Dict[str, Any]] = []
    for ev in sorted(rows, key=lambda r: r.get("at") or _now()):
        detail = ev.get("detail") or {}
        safe = {k: detail.get(k) for k in _TIMELINE_SAFE_DETAIL if detail.get(k) is not None}
        out.append({"event": ev.get("event"), "at": _iso(ev.get("at")), "detail": safe})
    return out


# ─────────── Authority read: active assigned responders (live tracking) ─────────
# Reused by the Emergency Command Center "Active Assigned Responders" roster and the
# assigned-responder live-marker state. VISIBILITY ONLY: reads the SAME stored
# dispatch + responder rows the WS fans out to, derives the live-tracking window
# (ACCEPTED / EN_ROUTE / ARRIVED — the states the dispatch WebSocket actually
# broadcasts to), and joins each to the safe _nearby_responder_view projection.
# NEVER assigns/re-ranks anyone, NEVER exposes anything a victim could reach
# (all behind require_authority on the router). Incident point is taken from the
# stored dispatch record (server-side), never from any client payload.
_WS_TRACKING_STATES = frozenset({ACCEPTED, EN_ROUTE, ARRIVED})


def active_assigned_responders() -> List[Dict[str, Any]]:
    """Authority-only projection of every responder currently holding an ACTIVE
    dispatch in the live-tracking window (ACCEPTED / EN_ROUTE / ARRIVED).

    For each such dispatch the row is the safe _nearby_responder_view shape plus the
    dispatch context the ops map needs: dispatch_id, case_id, dispatch_status
    (tracking-window statuses only), and straight-line distance_m. Terminal or
    accepted-but-not-yet-live dispatches are excluded. No responder PII beyond the
    safe label, and no victim identity/dispatch data.
    """
    from routers.dispatch_routes import _nearby_responder_view  # local: avoids import cycle
    out: List[Dict[str, Any]] = []
    for d in list_dispatches(active_only=True):
        status = d.get("status")
        if status not in _WS_TRACKING_STATES:
            continue
        rid = d.get("assigned_responder_id")
        if not rid:
            continue  # defensive: accepted but no responder set
        rec = responder_service.get_responder_by_id(rid)
        if not rec:
            continue
        inc = (d.get("incident_location") or {}).get("coordinates")
        inc_lng, inc_lat = (None, None)
        if isinstance(inc, (list, tuple)) and len(inc) == 2:
            inc_lng, inc_lat = float(inc[0]), float(inc[1])
        base = _nearby_responder_view(rec, inc_lng, inc_lat)
        # Safe fields (label/id/status/cap/jurisdiction/distance/location/freshness)
        # + dispatch context only. responder_id is the same opaque handle already
        # present in the authority dispatch view.
        base.update({
            "dispatch_id": d.get("dispatch_id"),
            "case_id": d.get("case_id"),
            "dispatch_status": status,
            "distance_type": "straight_line",
            "eta_minutes": None,
        })
        out.append(base)
    out.sort(key=lambda r: (str(r.get("case_id") or ""), str(r.get("display_label") or "")))
    return out


def get_offers_for_responder(responder_id: str) -> List[Dict[str, Any]]:
    """Pending, non-expired offers currently addressed to this responder."""
    now = _now()
    out = []
    for att in _attempts().find({"responder_id": responder_id, "response": PENDING}):
        exp = att.get("expires_at")
        if isinstance(exp, datetime) and exp < now:
            continue
        d = get_dispatch(att.get("dispatch_id"))
        if not d or d.get("status") != OFFERED:
            continue
        view = public_view(d, "responder")
        view["attempt_id"] = att.get("attempt_id")
        view["distance_m"] = att.get("distance_m")
        out.append(view)
    return out


# ─────────────────────────── Offer / escalation core ──────────────────────────
def _incident_coords(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    loc = d.get("incident_location") or {}
    coords = loc.get("coordinates") if isinstance(loc, dict) else None
    if coords and len(coords) == 2:
        return coords[0], coords[1]  # (lng, lat)
    return None, None


def _notify_authorities_intent(event_type: str, dispatch_id: str, case_id: str, title: str, message: str) -> Dict[str, Any]:
    return {
        "kind": "authorities",
        "event_type": event_type,
        "data": {"title": title, "message": message, "case_id": case_id, "dispatch_id": dispatch_id},
    }


def _notify_user_intent(user_id: Optional[str], event_type: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    return {"kind": "user", "target": user_id, "event_type": event_type, "data": data}


def _send_offer_push(responder_id: str, dispatch_id: str, d: Dict[str, Any],
                     distance_m: Optional[float], expires_at: datetime) -> Dict[str, str]:
    """Best-effort Web Push for one offer. Returns {status, reason}; never raises.

    Order of checks is deliberate so the status is always the most specific truth:
      1. VAPID/library not configured   -> NOT_CONFIGURED (no send attempted)
      2. no stored subscription         -> SUBSCRIPTION_REQUIRED
      3. otherwise send -> SEND_ATTEMPTED or SEND_FAILED (never DELIVERED)
    """
    try:
        from services import web_push
        from services.web_push import (STATUS_NOT_CONFIGURED, STATUS_SUBSCRIPTION_REQUIRED)
        if not web_push.is_configured():
            return {"status": STATUS_NOT_CONFIGURED, "reason": "vapid_not_configured"}
        sub = responder_service.get_push_subscription(responder_id)
        if not sub:
            return {"status": STATUS_SUBSCRIPTION_REQUIRED, "reason": "no_subscription"}
        payload = web_push.build_payload(dispatch_id, "CRITICAL", distance_m, expires_at)
        result = web_push.send(sub, payload, ttl_seconds=DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS)
        reason = str(result.get("reason") or "")
        gone = result.get("status") == web_push.STATUS_SEND_FAILED and (
            reason.endswith("_404") or reason.endswith("_410"))
        if gone:
            # The browser subscription is gone: clear it so we stop retrying a dead endpoint.
            responder_service.set_push_subscription(responder_id, None)
            return {"status": web_push.STATUS_SUBSCRIPTION_REQUIRED, "reason": "subscription_expired"}
        return {"status": result.get("status", "SEND_FAILED"), "reason": result.get("reason", "unknown")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "SEND_FAILED", "reason": type(exc).__name__}


def _next_wave_candidates(d: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """Determine eligible candidates for the CURRENT wave, respecting per-wave cap.

    Returns (candidates, wave_radius_m). Waves are deterministic: the backend owns
    the radius list and the per-wave cap; the frontend cannot widen eligibility.
    Already-tried responders are excluded so a wave never re-offers a duplicate.
    """
    lng, lat = _incident_coords(d)
    if lng is None or lat is None:
        return [], 0
    waves = d.get("radius_waves") or DISPATCH_RADIUS_WAVES
    wave_idx = int(d.get("current_wave_index", 0))
    if wave_idx < 0:
        wave_idx = 0
    if wave_idx >= len(waves):
        return [], 0
    wave_radius = int(waves[wave_idx])
    max_per_wave = int(d.get("max_providers_per_wave") or DISPATCH_MAX_PROVIDERS_PER_WAVE)
    tried = list(d.get("tried_responder_ids", []))
    candidates = responder_service.find_eligible(
        longitude=lng, latitude=lat,
        required_capability=d.get("required_capability"),
        radius_m=wave_radius,
        exclude_ids=tried,
        incident_jurisdiction=d.get("incident_jurisdiction"),
        max_age_seconds=RESPONDER_LOCATION_MAX_AGE_SECONDS,
        limit=max_per_wave,
    )
    return candidates, wave_radius


_WAVE_LOCK_NS = "haven:dispatch:wave:"


def _acquire_wave_lock(dispatch_id: str, ttl_ms: int = 10000) -> Tuple[bool, Optional[str]]:
    """Cross-process guard so only one worker broadcasts a given wave.

    Same fail-closed policy as _acquire_lock: in production without Redis the wave is
    NOT broadcast by this worker (the sweeper retries on its next tick).
    """
    try:
        mode, client = rate_limiter._resolve_backend()
    except Exception:
        mode, client = "memory", None
    if mode == "redis" and client is not None:
        key = f"{_WAVE_LOCK_NS}{dispatch_id}"
        try:
            ok = client.set(key, "1", nx=True, px=ttl_ms)
            return bool(ok), (key if ok else None)
        except Exception:
            return (False, None) if _redis_required() else (True, None)
    if _redis_required():
        return False, None
    return True, None


def _broadcast_offers(d: Dict[str, Any]) -> Dict[str, Any]:
    """Broadcast the dispatch offer for the CURRENT wave, or advance/FAIL if none.

    Precondition: the dispatch is in SEARCHING. This is wave-aware: it offers at
    most DISPATCH_MAX_PROVIDERS_PER_WAVE nearest eligible providers within the
    current wave radius, never re-offering a provider already tried. If no
    candidates exist in this wave, it advances to the next wave (same call) until
    a wave has candidates or all waves are exhausted (FAILED). The backend selects
    radius and provider batch; the frontend cannot widen eligibility.
    """
    dispatch_id = d.get("dispatch_id")
    case_id = d.get("case_id")
    lng, lat = _incident_coords(d)
    notify: List[Dict[str, Any]] = []
    waves = d.get("radius_waves") or DISPATCH_RADIUS_WAVES

    # Try successive waves until one has candidates or we run out.
    while True:
        wave_idx = int((get_dispatch(dispatch_id) or d).get("current_wave_index", 0))
        # Re-read latest tried set each iteration.
        cur = get_dispatch(dispatch_id) or d
        # If the dispatch is no longer SEARCHING (assigned/cancelled), stop.
        if cur.get("status") != SEARCHING:
            return {"dispatch": cur, "notify": notify, "offered": False}
        if wave_idx >= len(waves):
            # All waves exhausted without candidates → FAILED.
            updated = _dispatches().find_one_and_update(
                {"dispatch_id": dispatch_id, "status": SEARCHING},
                {"$set": {"status": FAILED, "resolved_at": _now(), "updated_at": _now(),
                          "current_attempt_id": None, "offer_expires_at": None}},
                return_document=_RET_AFTER,
            ) or get_dispatch(dispatch_id)
            _record_event(dispatch_id, FAILED, {"reason": "no_eligible_responder_all_waves"})
            _safe_audit(cur.get("created_by") or "system", cur.get("created_by_role") or "system",
                        "DISPATCH_FAILED", case_id, "failure", "no_eligible_responder_all_waves",
                        {"dispatch_id": dispatch_id})
            notify.append(_notify_authorities_intent(
                "dispatch_failed", dispatch_id, case_id, "No responder available",
                "No verified responder was available after searching all radius waves. Human follow-up required."))
            return {"dispatch": updated, "notify": notify, "offered": False}

        # Ensure dispatch's wave index and radius match this wave.
        _dispatches().update_one(
            {"dispatch_id": dispatch_id},
            {"$set": {"current_wave_index": wave_idx, "radius_m": int(waves[wave_idx])}}
        )
        cur = get_dispatch(dispatch_id) or cur
        eligible, wave_radius = _next_wave_candidates(cur)

        if not eligible:
            # No candidates in this wave → advance to next wave.
            _record_event(dispatch_id, "DISPATCH_WAVE_EMPTY", {"wave_index": wave_idx, "wave_radius_m": wave_radius})
            # Atomically advance wave index so only one worker does it.
            advanced = _dispatches().find_one_and_update(
                {"dispatch_id": dispatch_id, "status": SEARCHING, "current_wave_index": wave_idx},
                {"$set": {"current_wave_index": wave_idx + 1, "radius_m": int(waves[wave_idx + 1]) if wave_idx + 1 < len(waves) else wave_radius,
                          "updated_at": _now()}},
                return_document=_RET_AFTER,
            )
            if not advanced:
                # Lost the wave-advance race; re-read and retry.
                continue
            _safe_audit(cur.get("created_by") or "system", cur.get("created_by_role") or "system",
                        "DISPATCH_RADIUS_EXPANDED", case_id, "success", "wave_empty_advance",
                        {"dispatch_id": dispatch_id, "from_wave": wave_idx, "to_wave": wave_idx + 1})
            # Loop to try next wave.
            continue

        # We have candidates for this wave → create PENDING attempts.
        timeout = int(cur.get("wave_accept_timeout_seconds") or cur.get("accept_timeout_seconds") or DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS)
        offered_at = _now()
        expires_at = offered_at + timedelta(seconds=timeout)
        attempt_ids: List[str] = []
        responder_ids: List[str] = []

        for chosen in eligible:
            responder_id = chosen.get("responder_id")
            c_lng, c_lat = None, None
            loc = chosen.get("current_location") or {}
            if isinstance(loc, dict) and loc.get("coordinates"):
                c_lng, c_lat = loc["coordinates"][0], loc["coordinates"][1]
            distance_m = haversine_meters(lat, lng, c_lat, c_lng) if c_lat is not None else None
            attempt_id = _new_attempt_id()
            _attempts().insert_one({
                "attempt_id": attempt_id,
                "dispatch_id": dispatch_id,
                "responder_id": responder_id,
                "responder_label": chosen.get("display_label"),
                "offered_at": offered_at,
                "expires_at": expires_at,
                "response": PENDING,
                "responded_at": None,
                "distance_m": round(distance_m, 1) if distance_m is not None else None,
                "wave_index": wave_idx,
                # Truthful push status, filled in after the send below. The in-app
                # offer is created regardless; push is never a precondition.
                "notification_status": "OFFER_CREATED",
                "push_status": None,
                "push_reason": None,
            })
            attempt_ids.append(attempt_id)
            responder_ids.append(responder_id)

        first_attempt = attempt_ids[0] if attempt_ids else None
        updated = _dispatches().find_one_and_update(
            {"dispatch_id": dispatch_id, "status": SEARCHING},
            {"$set": {"status": OFFERED, "current_attempt_id": first_attempt,
                      "broadcast_attempt_ids": list(set((cur.get("broadcast_attempt_ids") or []) + attempt_ids)),
                      "eligible_provider_count": len((cur.get("tried_responder_ids") or [])) + len(eligible),
                      "offer_expires_at": expires_at, "updated_at": _now(),
                      "current_wave_index": wave_idx, "radius_m": wave_radius}},
            return_document=_RET_AFTER,
        )
        if not updated:
            for aid in attempt_ids:
                _attempts().update_one({"attempt_id": aid}, {"$set": {"response": A_CANCELLED, "responded_at": _now()}})
            return {"dispatch": get_dispatch(dispatch_id), "notify": notify, "offered": False}

        for rid in responder_ids:
            _dispatches().update_one(
                {"dispatch_id": dispatch_id},
                {"$addToSet": {"tried_responder_ids": rid}},
            )

        for i, chosen in enumerate(eligible):
            responder_id = chosen.get("responder_id")
            attempt_id = attempt_ids[i]
            _record_event(dispatch_id, OFFERED, {"attempt_id": attempt_id, "responder_id": responder_id, "wave_index": wave_idx})
            _record_event(dispatch_id, "DISPATCH_WAVE_STARTED", {"wave_index": wave_idx, "wave_radius_m": wave_radius})
            _safe_audit(cur.get("created_by") or "system", cur.get("created_by_role") or "system",
                        "DISPATCH_OFFERED", case_id, "success", "broadcast_offer_sent",
                        {"dispatch_id": dispatch_id, "attempt_id": attempt_id, "responder_id": responder_id, "wave_index": wave_idx})
            try:
                notification_manager.create_notification(
                    responder_id, "dispatch_offer", "New response request",
                    "A verified authority has requested your response to a nearby incident.", case_id)
            except Exception:
                pass
            # Straight-line distance for the intent and the push payload.
            c_lng2, c_lat2 = None, None
            loc2 = chosen.get("current_location") or {}
            if isinstance(loc2, dict) and loc2.get("coordinates"):
                c_lng2, c_lat2 = loc2["coordinates"][0], loc2["coordinates"][1]
            dist2 = haversine_meters(lat, lng, c_lat2, c_lng2) if c_lat2 is not None else None
            # Web Push: honest, best-effort. Records the REAL status on the attempt.
            push = _send_offer_push(responder_id, dispatch_id, cur, dist2, expires_at)
            _attempts().update_one({"attempt_id": attempt_id}, {"$set": {
                "notification_status": push["status"], "push_status": push["status"],
                "push_reason": push["reason"]}})
            _safe_audit("system", "system", "PROVIDER_NOTIFICATION_ATTEMPTED", case_id,
                        "success" if push["status"] == "SEND_ATTEMPTED" else "failure",
                        push["status"].lower(),
                        {"dispatch_id": dispatch_id, "attempt_id": attempt_id,
                         "responder_id": responder_id, "push_status": push["status"],
                         "push_reason": push["reason"]})
            intent = _notify_user_intent(responder_id, "dispatch_offer", {
                "dispatch_id": dispatch_id, "case_id": case_id,
                "incident_location": cur.get("incident_location"),
                "required_capability": cur.get("required_capability"),
                "distance_m": round(dist2, 1) if dist2 is not None else None,
                "expires_at": _iso(expires_at), "accept_timeout_seconds": timeout,
                "wave_index": wave_idx, "wave_radius_m": wave_radius,
                "wave_label": _wave_label(waves, wave_idx),
            })
            if intent:
                notify.append(intent)

        return {"dispatch": updated, "notify": notify, "offered": True,
                "attempt_ids": attempt_ids, "responder_ids": responder_ids,
                "eligible_provider_count": len(eligible),
                "offers_sent": len(attempt_ids), "wave_index": wave_idx, "wave_radius_m": wave_radius}


# ───────────────────────────── Human-approved create ──────────────────────────
def create_dispatch(
    case_id: str,
    created_by: str,
    created_by_role: str,
    incident_lng: float,
    incident_lat: float,
    required_capability: Optional[str] = None,
    radius_m: Optional[int] = None,
    notes: str = "",
    incident_jurisdiction: Optional[str] = None,
    victim_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a human-approved dispatch and immediately make the first offer.

    Returns {"dispatch": view-doc, "notify": [...], "error": None|str}. error:
      'bad_location' -> incident coordinates invalid (caller already resolved them)
      'duplicate'    -> an active dispatch already exists for this case (the active
                        one is returned so the caller can 409 with its id)

    The incident coordinates are supplied by the caller after being read from the
    case's own live GPS fix — they are NOT taken from the client — so a dispatcher
    cannot redirect a unit to an arbitrary point.
    """
    if not (finite_in_range(incident_lng, LNG_MIN, LNG_MAX) and finite_in_range(incident_lat, LAT_MIN, LAT_MAX)):
        return {"dispatch": None, "notify": [], "error": "bad_location"}

    existing = get_active_dispatch_for_case(case_id)
    if existing:
        return {"dispatch": existing, "notify": [], "error": "duplicate"}

    # Wave-aware: when the authority does not pin a radius, use the first wave
    # as the initial radius; the dispatch carries the full wave set for expansion.
    waves = list(DISPATCH_RADIUS_WAVES)
    wave_timeout = DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS
    if isinstance(radius_m, int):
        # Authority pinned a custom radius — honor it as a single-wave dispatch.
        radius = max(DISPATCH_MIN_RADIUS_M, min(DISPATCH_MAX_RADIUS_M, radius_m))
        waves = [radius]
    else:
        radius = int(waves[0]) if waves else DISPATCH_DEFAULT_RADIUS_M
    cap = (required_capability or "").strip().lower() or None
    now = _now()
    dispatch_id = _new_dispatch_id()
    doc = {
        "dispatch_id": dispatch_id,
        "case_id": case_id,
        "created_by": created_by,
        "created_by_role": created_by_role,
        "status": SEARCHING,
        "incident_location": {"type": "Point", "coordinates": [float(incident_lng), float(incident_lat)]},
        "incident_jurisdiction": (incident_jurisdiction or "").strip(),
        "required_capability": cap,
        "radius_m": radius,
        "radius_waves": waves,
        "current_wave_index": 0,
        "max_providers_per_wave": DISPATCH_MAX_PROVIDERS_PER_WAVE,
        "wave_accept_timeout_seconds": wave_timeout,
        "notes": (notes or "")[:500],
        "victim_user_id": victim_user_id,   # internal only — never exposed in a view
        "accept_timeout_seconds": wave_timeout,
        "tried_responder_ids": [],
        "current_attempt_id": None,
        "assigned_responder_id": None,
        "assigned_at": None,
        "offer_expires_at": None,
        "resolved_at": None,
        "cancel_reason": "",
        "created_at": now,
        "updated_at": now,
    }
    _dispatches().insert_one(doc)
    _record_event(dispatch_id, CREATED, {"case_id": case_id})
    _safe_audit(created_by, created_by_role, "DISPATCH_CREATED", case_id, "success",
                "human_approved_dispatch",
                {"dispatch_id": dispatch_id, "radius_m": radius, "radius_waves": waves, "required_capability": cap})

    result = _broadcast_offers(doc)
    return {"dispatch": result.get("dispatch"), "notify": result.get("notify", []),
            "offered": result.get("offered", False), "error": None,
            "eligible_provider_count": result.get("eligible_provider_count", 0),
            "wave_index": result.get("wave_index", 0), "wave_radius_m": result.get("wave_radius_m", radius)}


# ─────────────── Broadcast helper: cancel all other pending offers ────────────
def _cancel_other_offers(dispatch_id: str, winning_attempt_id: str) -> int:
    """Cancel all PENDING offers for a dispatch except the winning one.

    Called after a provider wins the atomic accept. Each cancellation is a
    single-document conditional update so the sweep is idempotent.
    """
    cancelled = 0
    for att in _attempts().find({"dispatch_id": dispatch_id, "response": PENDING}):
        aid = att.get("attempt_id")
        if aid == winning_attempt_id:
            continue
        result = _attempts().find_one_and_update(
            {"attempt_id": aid, "response": PENDING},
            {"$set": {"response": A_CANCELLED, "responded_at": _now()}},
            return_document=_RET_AFTER,
        )
        if result:
            cancelled += 1
    return cancelled


# ──────────── Broadcast helper: check remaining pending offers ────────────────
def _has_pending_offers(dispatch_id: str) -> bool:
    """Return True if any PENDING offers remain for this dispatch."""
    for att in _attempts().find({"dispatch_id": dispatch_id, "response": PENDING}):
        return True
    return False


# ───────────── Authority read: offers for a dispatch (broadcast view) ─────────
def get_offers_for_dispatch(dispatch_id: str) -> List[Dict[str, Any]]:
    """All offer attempts for a dispatch, shaped for authority visibility.

    Returns each attempt's safe fields: attempt_id, responder_id, display_label,
    response status, timing, and distance. Never exposes officer identity/PII.
    """
    out: List[Dict[str, Any]] = []
    for att in _attempts().find({"dispatch_id": dispatch_id}):
        out.append({
            "attempt_id": att.get("attempt_id"),
            "responder_id": att.get("responder_id"),
            "display_label": att.get("responder_label") or _responder_label(att.get("responder_id")),
            "response": att.get("response"),
            "offered_at": _iso(att.get("offered_at")),
            "responded_at": _iso(att.get("responded_at")),
            "distance_m": att.get("distance_m"),
            # Honest push status: NOT_CONFIGURED / SUBSCRIPTION_REQUIRED / SEND_FAILED /
            # SEND_ATTEMPTED. Never DELIVERED (no receipt channel). In-app offer is valid
            # regardless.
            "push_status": att.get("push_status"),
            "push_reason": att.get("push_reason"),
        })
    out.sort(key=lambda a: a.get("offered_at") or "")
    return out


# ───────────────────────────── Accept (the guard) ─────────────────────────────
def accept_offer(dispatch_id: str, responder_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    """Responder accepts their current offer. Returns (dispatch, error, notify).

    Double-assignment is prevented by an authoritative chain of single-document
    conditional updates, each of which can succeed for AT MOST one caller:
       1. attempt:  PENDING                      -> ACCEPTED
       2. dispatch: OFFERED & unassigned & this  -> ACCEPTED & assigned
       3. responder: AVAILABLE & unassigned      -> BUSY & bound
    If step 3 loses (the unit became unavailable), steps 1-2 are rolled back and
    the dispatch is re-offered to the next eligible responder. A Redis fast-lock
    wraps the sequence as an optimization only.
    error ∈ {None, not_found, not_offered, offer_unavailable, responder_unavailable}.
    """
    d = get_dispatch(dispatch_id)
    if not d:
        return None, "not_found", []
    # Idempotent replay: this responder already holds the (non-terminal) dispatch.
    if d.get("assigned_responder_id") == responder_id and d.get("status") in (
            ACCEPTED, EN_ROUTE, ARRIVED, HELP_PROVIDED):
        return d, None, []
    if d.get("status") != OFFERED:
        return None, "offer_unavailable", []

    acquired, lock_key = _acquire_lock(dispatch_id)
    if not acquired:
        return None, "offer_unavailable", []
    try:
        # Step 1 — claim THIS responder's PENDING attempt (broadcast: match by
        # dispatch_id + responder_id, not by a single current_attempt_id).
        att = _attempts().find_one_and_update(
            {"dispatch_id": dispatch_id, "responder_id": responder_id, "response": PENDING},
            {"$set": {"response": A_ACCEPTED, "responded_at": _now()}},
            return_document=_RET_AFTER,
        )
        if not att:
            return None, "offer_unavailable", []
        attempt_id = att.get("attempt_id")

        # Step 2 — claim the dispatch (first and only accept wins).
        # In broadcast model, do NOT filter on current_attempt_id since there
        # are multiple concurrent attempts. The assigned_responder_id=None
        # guard is the authoritative first-writer-wins barrier.
        now = _now()
        dd = _dispatches().find_one_and_update(
            {"dispatch_id": dispatch_id, "status": OFFERED,
             "assigned_responder_id": None},
            {"$set": {"status": ACCEPTED, "assigned_responder_id": responder_id,
                      "assigned_at": now, "offer_expires_at": None, "updated_at": now}},
            return_document=_RET_AFTER,
        )
        if not dd:
            # Dispatch changed under us (cancelled/expired/already assigned): void attempt.
            _attempts().update_one({"attempt_id": attempt_id},
                                   {"$set": {"response": A_CANCELLED, "responded_at": _now()}})
            return None, "offer_unavailable", []

        # Step 3 — claim the responder (cannot be double-booked across dispatches).
        claimed = responder_service.try_claim_for_dispatch(responder_id, dispatch_id)
        if not claimed:
            # Roll back: free the dispatch. In broadcast model, revert to OFFERED
            # (other providers may still be pending) rather than re-broadcasting.
            _attempts().update_one({"attempt_id": attempt_id},
                                   {"$set": {"response": A_CANCELLED, "responded_at": _now()}})
            # Check if other PENDING attempts exist.
            remaining = list(_attempts().find({"dispatch_id": dispatch_id, "response": PENDING}))
            revert_status = OFFERED if remaining else FAILED
            _dispatches().find_one_and_update(
                {"dispatch_id": dispatch_id, "status": ACCEPTED, "assigned_responder_id": responder_id},
                {"$set": {"status": revert_status, "assigned_responder_id": None,
                          "assigned_at": None, "updated_at": _now()}},
                return_document=_RET_AFTER,
            )
            return None, "responder_unavailable", []

        # ── SUCCESS: provider won the assignment. Cancel all other pending offers. ──
        _cancel_other_offers(dispatch_id, attempt_id)

        label = claimed.get("display_label")
        _record_event(dispatch_id, ACCEPTED, {"responder_id": responder_id, "attempt_id": attempt_id})
        _record_event(dispatch_id, "PROVIDER_ASSIGNMENT_WON", {"responder_id": responder_id})
        _record_event(dispatch_id, "OTHER_OFFERS_CANCELLED", {"winning_attempt": attempt_id})
        _safe_audit(responder_id, "responder", "DISPATCH_ACCEPTED", d.get("case_id"), "success",
                    "offer_accepted", {"dispatch_id": dispatch_id, "attempt_id": attempt_id})
        notify = []
        vi = _notify_user_intent(d.get("victim_user_id"), "dispatch_accepted", {
            "dispatch_id": dispatch_id, "case_id": d.get("case_id"), "status": ACCEPTED,
            "responder_label": label, "message": "A verified responder is on the way."})
        if vi:
            notify.append(vi)
            try:
                notification_manager.create_notification(
                    d.get("victim_user_id"), "dispatch_accepted", "Help is on the way",
                    "A verified responder has accepted and is on the way.", d.get("case_id"))
            except Exception:
                pass
        # Notify all other providers that the request is no longer available.
        for cancelled_att in _attempts().find({"dispatch_id": dispatch_id, "response": A_CANCELLED}):
            cancelled_rid = cancelled_att.get("responder_id")
            if cancelled_rid and cancelled_rid != responder_id:
                ci = _notify_user_intent(cancelled_rid, "dispatch_offer_cancelled", {
                    "dispatch_id": dispatch_id, "case_id": d.get("case_id"),
                    "message": "This emergency has already been assigned."})
                if ci:
                    notify.append(ci)
        notify.append(_notify_authorities_intent(
            "dispatch_accepted", dispatch_id, d.get("case_id"), "Responder accepted",
            f"A responder accepted dispatch {dispatch_id}."))
        return dd, None, notify
    finally:
        _release_lock(lock_key)


# ───────────────────────────────── Decline ────────────────────────────────────
def decline_offer(dispatch_id: str, responder_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    """Responder declines their offer. In broadcast model, other offers remain.

    If other PENDING offers still exist, the dispatch stays OFFERED. If no offers
    remain (all declined/timed-out), the dispatch transitions to FAILED.
    """
    d = get_dispatch(dispatch_id)
    if not d:
        return None, "not_found", []
    if d.get("status") != OFFERED:
        return None, "not_offered", []

    # In broadcast model, find THIS responder's PENDING attempt by dispatch_id.
    att = _attempts().find_one_and_update(
        {"dispatch_id": dispatch_id, "responder_id": responder_id, "response": PENDING},
        {"$set": {"response": A_DECLINED, "responded_at": _now()}},
        return_document=_RET_AFTER,
    )
    if not att:
        return None, "offer_unavailable", []
    attempt_id = att.get("attempt_id")
    _record_event(dispatch_id, "PROVIDER_DECLINED", {"responder_id": responder_id, "attempt_id": attempt_id})
    _safe_audit(responder_id, "responder", "DISPATCH_DECLINED", d.get("case_id"), "success",
                "offer_declined", {"dispatch_id": dispatch_id, "attempt_id": attempt_id})

    notify: List[Dict[str, Any]] = []
    # In wave-aware model: if no PENDING remain in the *current* wave, try to
    # expand to the next wave instead of immediately failing. _try_expand_wave
    # is idempotent and handles the assigned check + wave lock.
    if not _has_pending_offers(dispatch_id):
        d_cur = get_dispatch(dispatch_id) or d
        # If the dispatch is still OFFERED and unassigned, try wave expansion.
        if d_cur.get("status") == OFFERED and not d_cur.get("assigned_responder_id"):
            expanded, wave_notify = _try_expand_wave(dispatch_id, _now())
            if wave_notify:
                notify.extend(wave_notify)
            if expanded:
                # Expanded to next wave — offers are now pending there.
                return get_dispatch(dispatch_id) or d_cur, None, notify
            # No wave to expand into (or lock race where another worker expanded
            # — re-check before failing). If still OFFERED with no pending, fail.
            d_after = get_dispatch(dispatch_id) or d_cur
            if d_after.get("status") == OFFERED and not _has_pending_offers(dispatch_id) and not d_after.get("assigned_responder_id"):
                waves = d_after.get("radius_waves") or DISPATCH_RADIUS_WAVES
                cur_idx = int(d_after.get("current_wave_index", 0))
                if cur_idx + 1 >= len(waves):
                    updated = _dispatches().find_one_and_update(
                        {"dispatch_id": dispatch_id, "status": OFFERED},
                        {"$set": {"status": FAILED, "resolved_at": _now(), "updated_at": _now(),
                                  "offer_expires_at": None}},
                        return_document=_RET_AFTER,
                    ) or get_dispatch(dispatch_id)
                    _record_event(dispatch_id, FAILED, {"reason": "all_offers_declined_all_waves"})
                    _safe_audit("system", "system", "DISPATCH_FAILED", d.get("case_id"), "failure",
                                "all_offers_exhausted_all_waves", {"dispatch_id": dispatch_id})
                    notify.append(_notify_authorities_intent(
                        "dispatch_failed", dispatch_id, d.get("case_id"), "No provider accepted",
                        "All eligible providers declined across all radius waves. Human follow-up required."))
                    return updated, None, notify
                # Another worker expanded — return current state without failing.
                return get_dispatch(dispatch_id) or d_after, None, notify
        # Fallback: if not in a wave expansion path, mark FAILED (legacy single-wave).
        updated = _dispatches().find_one_and_update(
            {"dispatch_id": dispatch_id, "status": OFFERED},
            {"$set": {"status": FAILED, "resolved_at": _now(), "updated_at": _now(),
                      "offer_expires_at": None}},
            return_document=_RET_AFTER,
        ) or get_dispatch(dispatch_id)
        _record_event(dispatch_id, FAILED, {"reason": "all_offers_declined_or_expired"})
        _safe_audit("system", "system", "DISPATCH_FAILED", d.get("case_id"), "failure",
                    "all_offers_exhausted", {"dispatch_id": dispatch_id})
        notify.append(_notify_authorities_intent(
            "dispatch_failed", dispatch_id, d.get("case_id"), "No provider accepted",
            "All eligible providers declined or timed out. Human follow-up required."))
        return updated, None, notify

    # Other offers still pending — dispatch stays OFFERED. Update timestamp.
    updated = _dispatches().find_one_and_update(
        {"dispatch_id": dispatch_id, "status": OFFERED},
        {"$set": {"updated_at": _now()}},
        return_document=_RET_AFTER,
    ) or get_dispatch(dispatch_id)
    return updated, None, notify


# ───────────────────── Escalation sweep (pure + idempotent) ───────────────────
def _try_expand_wave(dispatch_id: str, now: datetime) -> Tuple[bool, List[Dict[str, Any]]]:
    """Try to advance the dispatch to the next radius wave. Returns (expanded, notify).

    Only succeeds when: status==OFFERED, no PENDING remain in current wave, a next
    wave exists, and the dispatch is still unassigned. Uses a wave lock to prevent
    duplicate broadcasts across workers.
    """
    d = get_dispatch(dispatch_id)
    if not d or d.get("status") != OFFERED or d.get("assigned_responder_id"):
        return False, []
    if _has_pending_offers(dispatch_id):
        return False, []
    waves = d.get("radius_waves") or DISPATCH_RADIUS_WAVES
    cur_idx = int(d.get("current_wave_index", 0))
    if cur_idx + 1 >= len(waves):
        return False, []
    # Acquire wave lock so only one worker broadcasts the next wave.
    acquired, wkey = _acquire_wave_lock(dispatch_id)
    if not acquired:
        return False, []
    try:
        # Re-read under lock; another worker may have expanded already.
        d2 = get_dispatch(dispatch_id)
        if not d2 or d2.get("status") != OFFERED or d2.get("assigned_responder_id"):
            return False, []
        if _has_pending_offers(dispatch_id):
            return False, []
        cur_idx2 = int(d2.get("current_wave_index", 0))
        if cur_idx2 != cur_idx:
            return False, []
        next_idx = cur_idx + 1
        _dispatches().find_one_and_update(
            {"dispatch_id": dispatch_id, "status": OFFERED, "current_wave_index": cur_idx},
            {"$set": {"status": SEARCHING, "current_wave_index": next_idx,
                      "radius_m": int(waves[next_idx]), "updated_at": now}},
            return_document=_RET_AFTER,
        )
        _record_event(dispatch_id, "DISPATCH_RADIUS_EXPANDED",
                      {"from_wave": cur_idx, "to_wave": next_idx,
                       "from_radius_m": int(waves[cur_idx]), "to_radius_m": int(waves[next_idx])})
        _safe_audit("system", "system", "DISPATCH_RADIUS_EXPANDED", d2.get("case_id"), "success",
                    "wave_expanded", {"dispatch_id": dispatch_id, "from_wave": cur_idx, "to_wave": next_idx})
        cur_searching = get_dispatch(dispatch_id)
        if not cur_searching:
            return False, []
        result = _broadcast_offers(cur_searching)
        # _broadcast_offers may have already marked FAILED if no candidates in remaining waves.
        expanded = bool(result.get("offered"))
        # If _broadcast_offers advanced through empty waves and still found none, it
        # already transitioned to FAILED; count that as not expanded.
        if not expanded and (get_dispatch(dispatch_id) or {}).get("status") == FAILED:
            return False, result.get("notify", [])
        return expanded, result.get("notify", [])
    finally:
        _release_lock(wkey)


def process_expirations(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Time out stale offers and expand radius waves (or FAIL). Pure, idempotent, test-callable.

    Safe to call repeatedly and concurrently: the PENDING→TIMEOUT attempt update
    is a single-document conditional claim, so a given offer is expired by exactly
    one caller. After expiring, if no PENDING remain in the current wave, the
    dispatch advances to the next wave (up to DISPATCH_RADIUS_WAVES). An already
    assigned dispatch never expands.
    Returns counts + accumulated notification intents.
    """
    now = now or _now()
    expired = reoffered = failed = 0
    notify: List[Dict[str, Any]] = []
    expired_attempts = _attempts().find({"response": PENDING, "expires_at": {"$lt": now}})
    seen_dispatches: set = set()
    for att in expired_attempts:
        attempt_id = att.get("attempt_id")
        dispatch_id = att.get("dispatch_id")
        claimed = _attempts().find_one_and_update(
            {"attempt_id": attempt_id, "response": PENDING},
            {"$set": {"response": A_TIMEOUT, "responded_at": now}},
            return_document=_RET_AFTER,
        )
        if not claimed:
            continue
        expired += 1
        _record_event(dispatch_id, "PROVIDER_TIMEOUT", {"attempt_id": attempt_id,
                      "responder_id": att.get("responder_id"),
                      "wave_index": att.get("wave_index", 0)})
        _safe_audit("system", "system", "DISPATCH_OFFER_TIMEOUT", att.get("case_id") or "", "success",
                    "offer_timeout", {"dispatch_id": dispatch_id, "attempt_id": attempt_id})
        seen_dispatches.add(dispatch_id)

    for dispatch_id in seen_dispatches:
        d = get_dispatch(dispatch_id)
        if not d or d.get("status") != OFFERED or d.get("assigned_responder_id"):
            continue
        if _has_pending_offers(dispatch_id):
            continue
        # Try wave expansion first; if no next wave, mark FAILED.
        expanded, wave_notify = _try_expand_wave(dispatch_id, now)
        if wave_notify:
            notify.extend(wave_notify)
        if expanded:
            reoffered += 1
            continue
        # No wave to expand into → FAILED (only if still OFFERED and no pending).
        cur = get_dispatch(dispatch_id)
        if not cur or cur.get("status") != OFFERED or cur.get("assigned_responder_id"):
            continue
        if _has_pending_offers(dispatch_id):
            continue
        # Check if there was truly no next wave (not just a lock race).
        waves = cur.get("radius_waves") or DISPATCH_RADIUS_WAVES
        cur_idx = int(cur.get("current_wave_index", 0))
        if cur_idx + 1 < len(waves):
            continue  # lock race — another worker will expand; don't fail yet
        updated = _dispatches().find_one_and_update(
            {"dispatch_id": dispatch_id, "status": OFFERED},
            {"$set": {"status": FAILED, "resolved_at": now, "updated_at": now,
                      "offer_expires_at": None}},
            return_document=_RET_AFTER,
        )
        if updated:
            failed += 1
            _record_event(dispatch_id, FAILED, {"reason": "all_offers_expired_all_waves"})
            _safe_audit("system", "system", "DISPATCH_FAILED", cur.get("case_id"), "failure",
                        "all_offers_exhausted_all_waves", {"dispatch_id": dispatch_id})
            notify.append(_notify_authorities_intent(
                "dispatch_failed", dispatch_id, cur.get("case_id"), "No provider accepted",
                "All eligible providers timed out across all radius waves. Human follow-up required."))
    return {"expired": expired, "reoffered": reoffered, "failed": failed, "notify": notify}


# ───────────────────────────── Authority cancel ───────────────────────────────
def cancel_dispatch(dispatch_id: str, actor_id: str, role: str, reason: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    """Authority cancels a non-terminal dispatch. Frees any bound responder.

    error ∈ {None, not_found, already_terminal}. Idempotent on an already-terminal
    dispatch only insofar as it reports 'already_terminal' (no state change).
    """
    d = get_dispatch(dispatch_id)
    if not d:
        return None, "not_found", []
    if is_terminal(d.get("status")):
        return None, "already_terminal", []

    now = _now()
    prev_attempt = d.get("current_attempt_id")
    assigned = d.get("assigned_responder_id")
    updated = _dispatches().find_one_and_update(
        {"dispatch_id": dispatch_id, "status": d.get("status")},
        {"$set": {"status": CANCELLED, "resolved_at": now, "updated_at": now,
                  "current_attempt_id": None, "offer_expires_at": None,
                  "cancel_reason": (reason or "")[:500]}},
        return_document=_RET_AFTER,
    )
    if not updated:
        # Someone else moved it first — re-read and report whatever is now true.
        cur = get_dispatch(dispatch_id)
        if cur and is_terminal(cur.get("status")):
            return None, "already_terminal", []
        return cur, None, []

    # Void ALL outstanding PENDING offers and release a bound responder.
    _cancel_other_offers(dispatch_id, "")  # cancel ALL — no winner
    if assigned:
        try:
            responder_service.release_from_dispatch(assigned, dispatch_id)
        except Exception:
            pass

    _record_event(dispatch_id, CANCELLED, {"reason": (reason or "")[:120]})
    _safe_audit(actor_id, role, "DISPATCH_CANCELLED", d.get("case_id"), "success",
                "authority_cancel", {"dispatch_id": dispatch_id})
    notify: List[Dict[str, Any]] = []
    vi = _notify_user_intent(d.get("victim_user_id"), "dispatch_cancelled", {
        "dispatch_id": dispatch_id, "case_id": d.get("case_id"), "status": CANCELLED,
        "message": "The dispatch was cancelled."})
    if vi:
        notify.append(vi)
    if assigned:
        ri = _notify_user_intent(assigned, "dispatch_cancelled", {
            "dispatch_id": dispatch_id, "case_id": d.get("case_id"), "status": CANCELLED,
            "message": "This dispatch has been cancelled by the authority."})
        if ri:
            notify.append(ri)
    return updated, None, notify


# ─────────────────── Responder progress (assigned responder only) ─────────────
def mark_progress(dispatch_id: str, responder_id: str, new_state: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    """Assigned responder advances the dispatch: EN_ROUTE → ARRIVED → HELP_PROVIDED.

    Only the responder bound to the dispatch may call this, and only along a valid
    FSM transition. error ∈ {None, not_found, forbidden, bad_state, invalid_transition}.
    """
    if new_state not in RESPONDER_PROGRESS_STATES:
        return None, "bad_state", []
    d = get_dispatch(dispatch_id)
    if not d:
        return None, "not_found", []
    if d.get("assigned_responder_id") != responder_id:
        return None, "forbidden", []
    cur = d.get("status")
    # Idempotent replay: already in the requested state.
    if cur == new_state:
        return d, None, []
    if not is_valid_transition(cur, new_state):
        return None, "invalid_transition", []

    now = _now()
    updated = _dispatches().find_one_and_update(
        {"dispatch_id": dispatch_id, "status": cur, "assigned_responder_id": responder_id},
        {"$set": {"status": new_state, "updated_at": now}},
        return_document=_RET_AFTER,
    )
    if not updated:
        return None, "invalid_transition", []
    _record_event(dispatch_id, new_state, {"responder_id": responder_id})
    _safe_audit(responder_id, "responder", f"DISPATCH_{new_state}", d.get("case_id"), "success",
                "responder_progress", {"dispatch_id": dispatch_id})
    notify: List[Dict[str, Any]] = []
    msg = {
        EN_ROUTE: "Your responder is on the way.",
        ARRIVED: "Your responder has arrived.",
        HELP_PROVIDED: "Your responder has reported that help was provided.",
    }.get(new_state, "Dispatch updated.")
    vi = _notify_user_intent(d.get("victim_user_id"), "dispatch_progress", {
        "dispatch_id": dispatch_id, "case_id": d.get("case_id"), "status": new_state,
        "responder_label": updated.get("responder_label") or _responder_label(responder_id),
        "message": msg})
    if vi:
        notify.append(vi)
    notify.append(_notify_authorities_intent(
        "dispatch_progress", dispatch_id, d.get("case_id"), f"Dispatch {new_state}",
        f"Dispatch {dispatch_id} is now {new_state}."))
    return updated, None, notify


# ─────────── RESOLVED hook (driven by the EXISTING case-resolution flow) ───────
def resolve_dispatch_for_case(case_id: str, actor_id: str, role: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve the active dispatch (if any) when its case is resolved by an authority.

    This is a HOOK the existing authorized case-resolution workflow calls — HAVEN
    does not invent a parallel resolution path. Idempotent: returns (None, []) when
    there is no active dispatch. Releases any bound responder.
    """
    d = get_active_dispatch_for_case(case_id)
    if not d:
        return None, []
    now = _now()
    prev_attempt = d.get("current_attempt_id")
    assigned = d.get("assigned_responder_id")
    updated = _dispatches().find_one_and_update(
        {"dispatch_id": d.get("dispatch_id"), "status": d.get("status")},
        {"$set": {"status": RESOLVED, "resolved_at": now, "updated_at": now,
                  "current_attempt_id": None, "offer_expires_at": None}},
        return_document=_RET_AFTER,
    )
    # Void ALL outstanding PENDING offers and release a bound responder.
    _cancel_other_offers(d.get("dispatch_id"), "")
    if assigned:
        try:
            responder_service.release_from_dispatch(assigned, d.get("dispatch_id"))
        except Exception:
            pass
    _record_event(d.get("dispatch_id"), RESOLVED, {"via": "case_resolution"})
    _safe_audit(actor_id, role, "DISPATCH_RESOLVED", case_id, "success",
                "case_resolved", {"dispatch_id": d.get("dispatch_id")})
    notify: List[Dict[str, Any]] = []
    if assigned:
        ri = _notify_user_intent(assigned, "dispatch_resolved", {
            "dispatch_id": d.get("dispatch_id"), "case_id": case_id, "status": RESOLVED,
            "message": "This case has been resolved. Thank you."})
        if ri:
            notify.append(ri)
    return updated, notify


