"""Rapid Response Center — authority read-only view regression suite.

Covers the THREE read-only authority endpoints the Rapid Response Center page
depends on, plus the safe per-unit projection they share:

  * GET /dispatch/rrn/metrics      -> rrn_metrics_endpoint
  * GET /dispatch/rrn/nearby/{id}  -> rrn_nearby_endpoint
  * GET /dispatch/{id}/timeline    -> dispatch_timeline_endpoint
  * _nearby_responder_view(rec, inc_lng, inc_lat)  (the safe unit summary)

The security invariants under test (none of which the frontend can relax):
  - All three endpoints are gated by require_authority (NOT get_current_user /
    require_responder) — a victim or responder token can never read them.
  - "nearby" is VISIBILITY, not a force-assign surface: the incident point is
    resolved SERVER-SIDE from stored case GPS (never a request body), eligibility
    is delegated wholesale to responder_service.find_eligible with the engine's
    OWN constants, and the endpoint signature exposes NO knob a client could use
    to widen or re-rank the eligible set.
  - A unit summary never leaks officer identity, badge, phone, internal user id,
    or raw GPS — only a safe label, straight-line distance, and fix age. There is
    NO ETA anywhere (distance_type is always "straight_line").
  - metrics are merged from the REAL counting logic over stored rows; nothing is
    fabricated.
  - the timeline 404s on an unknown id (no id-probing) and surfaces only the
    safe detail keys (no raw GPS / victim PII), proven end to end.

Runs under pytest OR standalone (`python test_rrn_authority_views.py`), using the
same dependency shims as the engine suite so it works in an offline sandbox.
"""
import inspect
import sys
from datetime import datetime, timedelta

import _rrn_test_support  # noqa: F401  (installs dep shims only when missing)

import routers.dispatch_routes as dr
from services import dispatch_service, responder_service

MAX_AGE = dispatch_service.RESPONDER_LOCATION_MAX_AGE_SECONDS
RADIUS = dispatch_service.DISPATCH_DEFAULT_RADIUS_M


class _DummyAuthority:
    """Stand-in for the require_authority-verified user (body never reads PII)."""
    user_id = "AUTH-1"
    role = "authority"


# ── Fakes ──────────────────────────────────────────────────────────────────────
class _FakeColl:
    """Minimal find/find_one over a list of docs honouring an exact-match query."""

    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, query=None):
        q = query or {}
        return [dict(d) for d in self._docs if all(d.get(k) == v for k, v in q.items())]

    def find_one(self, query=None, projection=None):
        q = query or {}
        for d in self._docs:
            if all(d.get(k) == v for k, v in q.items()):
                out = dict(d)
                out.pop("_id", None)
                return out
        return None


class _FakeTracking:
    def __init__(self, latest=None):
        self.latest_locations = dict(latest or {})


def _patch_resolver_stores(events=None, cases=None, live=None):
    """Point the PRODUCTION resolver (dr._resolve_incident_location) at fake stores
    + the live cache. Returns a restore() callable. Never touches the request body."""
    saved_ev, saved_cs = dr.sos_events, dr.sos_cases
    dr.sos_events = lambda: _FakeColl(events or [])
    dr.sos_cases = lambda: _FakeColl(cases or [])
    fake_main = type(sys)("main")
    fake_main.tracking_manager = _FakeTracking(live or {})
    saved_main = sys.modules.get("main")
    sys.modules["main"] = fake_main

    def restore():
        dr.sos_events, dr.sos_cases = saved_ev, saved_cs
        if saved_main is not None:
            sys.modules["main"] = saved_main
        else:
            sys.modules.pop("main", None)

    return restore


class _patch:
    """Tiny save/restore for a single attribute on a module/object."""

    def __init__(self, obj, name, value):
        self._obj, self._name, self._value = obj, name, value

    def __enter__(self):
        self._saved = getattr(self._obj, self._name)
        setattr(self._obj, self._name, self._value)
        return self

    def __exit__(self, *exc):
        setattr(self._obj, self._name, self._saved)
        return False


def _dependency_of(fn, name="current_user"):
    """The dependency callable guarding a route param, across real-fastapi and the
    offline shim. Real fastapi: Depends(x).dependency == x. Shim: Depends(x) == x."""
    default = inspect.signature(fn).parameters[name].default
    return getattr(default, "dependency", default)


# Incident reference point used throughout (Delhi-ish); kept away from the equator
# so a lat/lng swap produces a GROSSLY different distance and can't pass by luck.
INC_LAT, INC_LNG = 28.6000, 77.2000


# ═══════════════════ AUTHZ — all three are authority-only ═════════════════════
def test_authz_metrics_requires_authority():
    assert _dependency_of(dr.rrn_metrics_endpoint) is dr.require_authority
    assert _dependency_of(dr.rrn_metrics_endpoint) is not dr.require_responder
    assert _dependency_of(dr.rrn_metrics_endpoint) is not dr.get_current_user


def test_authz_nearby_requires_authority():
    assert _dependency_of(dr.rrn_nearby_endpoint) is dr.require_authority
    assert _dependency_of(dr.rrn_nearby_endpoint) is not dr.get_current_user


def test_authz_timeline_requires_authority():
    assert _dependency_of(dr.dispatch_timeline_endpoint) is dr.require_authority
    assert _dependency_of(dr.dispatch_timeline_endpoint) is not dr.require_responder


# ═════════════ _nearby_responder_view — safe projection + geo math ════════════
def _unit(coords=None, updated_at=None, **extra):
    rec = {
        "responder_id": "RESP-HR204",
        "display_label": "Verified Response Unit HR-204",
        "status": "AVAILABLE",
        "capabilities": ["medical"],
        "jurisdiction": "DELHI",
    }
    if coords is not None:
        rec["current_location"] = {"type": "Point", "coordinates": list(coords)}
    if updated_at is not None:
        rec["location_updated_at"] = updated_at
    rec.update(extra)
    return rec


def test_view_distance_uses_geojson_lng_lat_ordering():
    """GeoJSON coordinates are [lng, lat]; the view must read index 0 as lng and
    index 1 as lat. A swap would place the unit near (lat=77) — thousands of km
    away — so matching the straight (near) distance proves the ordering."""
    r_lng, r_lat = 77.2500, 28.6500
    # A distance is only reported for a FRESH fix (a stale/untimed fix is withheld),
    # so the ordering check must supply a current timestamp.
    view = dr._nearby_responder_view(
        _unit([r_lng, r_lat], updated_at=datetime.utcnow()), INC_LNG, INC_LAT)
    expected = round(dr.haversine_meters(INC_LAT, INC_LNG, r_lat, r_lng))
    assert view["distance_m"] == expected
    assert view["distance_m"] < 50_000          # the near reading, never the swap
    assert view["distance_type"] == "straight_line"


def test_view_fresh_within_max_age():
    ts = datetime.utcnow() - timedelta(seconds=MAX_AGE - 60)
    view = dr._nearby_responder_view(_unit([INC_LNG, INC_LAT], ts), INC_LNG, INC_LAT)
    assert view["location_fresh"] is True
    assert view["location_age_seconds"] is not None
    assert view["location_age_seconds"] <= MAX_AGE


def test_view_stale_beyond_max_age():
    ts = datetime.utcnow() - timedelta(seconds=MAX_AGE + 60)
    view = dr._nearby_responder_view(_unit([INC_LNG, INC_LAT], ts), INC_LNG, INC_LAT)
    assert view["location_fresh"] is False
    assert view["location_age_seconds"] >= MAX_AGE


def test_view_no_location_is_unknown_not_fabricated():
    view = dr._nearby_responder_view(_unit(coords=None, updated_at=None), INC_LNG, INC_LAT)
    assert view["distance_m"] is None
    assert view["location_age_seconds"] is None
    assert view["location_fresh"] is False


def test_view_omits_identity_and_raw_gps():
    """Even when the stored record carries identity + raw GPS, the view must expose
    ONLY the safe fields — no officer_name/badge/phone/user_id, and never the raw
    `current_location` GeoJSON blob. The authority map coordinate is a clean,
    deliberate {lat,lng} `location` pair (product decision), NOT the raw blob."""
    ts = datetime.utcnow()
    rec = _unit(
        [INC_LNG, INC_LAT], ts,
        officer_name="Insp. Real Name", badge_number="HR-204-9931",
        phone="+91-99999-00000", user_id="USER-INTERNAL-7",
        password_hash="x", salt="y",
    )
    view = dr._nearby_responder_view(rec, INC_LNG, INC_LAT)
    assert set(view.keys()) == {
        "responder_id", "display_label", "status", "capabilities",
        "jurisdiction", "distance_m", "distance_type",
        "location_age_seconds", "location_fresh", "location",
    }
    forbidden = {"officer_name", "badge_number", "phone", "user_id",
                 "current_location", "location_updated_at", "password_hash", "salt"}
    assert not (forbidden & set(view.keys()))
    # `location` is the clean pair, never the raw GeoJSON blob.
    assert view["location"] == {"lat": INC_LAT, "lng": INC_LNG}
    assert view["location"].get("type") is None and "coordinates" not in view["location"]
    blob = repr(view)
    for secret in ("Insp. Real Name", "HR-204-9931", "+91-99999-00000", "USER-INTERNAL-7"):
        assert secret not in blob


def test_view_location_present_when_coords_exist():
    """The authority-only `location` is a clean {lat,lng} derived from stored
    GeoJSON [lng, lat] — proving the ordering is not swapped into {lat=lng}."""
    r_lng, r_lat = 77.2500, 28.6500
    view = dr._nearby_responder_view(_unit([r_lng, r_lat], datetime.utcnow()),
                                     INC_LNG, INC_LAT)
    assert view["location"] == {"lat": r_lat, "lng": r_lng}


def test_view_location_none_when_no_fix():
    """No stored fix -> location is None (never a fabricated 0,0 point)."""
    view = dr._nearby_responder_view(_unit(coords=None, updated_at=None), INC_LNG, INC_LAT)
    assert view["location"] is None


def test_view_location_rejects_out_of_range_coords():
    """A corrupt/out-of-range stored coordinate yields location=None, not a bad pin."""
    view = dr._nearby_responder_view(_unit([999.0, 999.0], datetime.utcnow()),
                                     INC_LNG, INC_LAT)
    assert view["location"] is None


def test_view_has_no_eta():
    """The whole RRN never fabricates an ETA — the view must carry none."""
    view = dr._nearby_responder_view(_unit([INC_LNG, INC_LAT], datetime.utcnow()),
                                     INC_LNG, INC_LAT)
    assert "eta" not in view and "eta_minutes" not in view


# ═══════════════════════ rrn_nearby_endpoint behaviour ════════════════════════
def test_nearby_no_fix_returns_unresolved_without_querying_units():
    """No stored GPS -> {incident_resolved:False, responders:[]} and find_eligible
    is NEVER called (so no coverage query runs against a fabricated point)."""
    def _boom(*a, **k):
        raise AssertionError("find_eligible must not be called when no fix exists")

    r = _patch_resolver_stores(cases=[{"case_id": "C-NO", "user_id": "U-1",
                                       "location": "Unknown"}])
    try:
        with _patch(dr.responder_service, "find_eligible", _boom):
            out = dr.rrn_nearby_endpoint(case_id="C-NO", current_user=_DummyAuthority())
    finally:
        r()
    assert out == {"incident_resolved": False, "responders": []}


def test_nearby_delegates_eligibility_to_engine_with_server_values():
    """With a stored fix the endpoint resolves the point SERVER-SIDE and hands the
    engine's OWN constants to find_eligible — never a client-supplied radius/filter.
    It returns the engine's units mapped through the safe view, in the SAME order."""
    captured = {}

    def _fake_find_eligible(**kwargs):
        captured.update(kwargs)
        # Two units, deliberately NOT in the order the UI might prefer, to prove the
        # endpoint does not re-rank — it echoes the engine's nearest-first order.
        return [
            _unit([77.2100, 28.6100], datetime.utcnow(),
                  responder_id="RESP-A", display_label="Unit A"),
            _unit([77.2500, 28.6500], datetime.utcnow(),
                  responder_id="RESP-B", display_label="Unit B"),
        ]

    case = {"case_id": "C-1", "user_id": "U-9", "jurisdiction": "DELHI",
            "latitude": INC_LAT, "longitude": INC_LNG}
    r = _patch_resolver_stores(cases=[case])
    try:
        with _patch(dr.responder_service, "find_eligible", _fake_find_eligible):
            out = dr.rrn_nearby_endpoint(case_id="C-1", current_user=_DummyAuthority())
    finally:
        r()

    # Server-resolved inputs + engine constants (no client knob widened anything).
    assert captured["longitude"] == INC_LNG
    assert captured["latitude"] == INC_LAT
    assert captured["radius_m"] == RADIUS
    assert captured["incident_jurisdiction"] == "DELHI"
    assert captured["max_age_seconds"] == MAX_AGE

    assert out["incident_resolved"] is True
    assert out["incident_jurisdiction"] == "DELHI"
    assert out["radius_m"] == RADIUS
    # Order preserved (no re-ranking), mapped through the safe view.
    assert [u["responder_id"] for u in out["responders"]] == ["RESP-A", "RESP-B"]
    for u in out["responders"]:
        assert set(u.keys()) == {
            "responder_id", "display_label", "status", "capabilities",
            "jurisdiction", "distance_m", "distance_type",
            "location_age_seconds", "location_fresh", "location",
        }
        assert "current_location" not in u  # raw GeoJSON blob never crosses the boundary
        # The authority-only map pin is a clean {lat,lng} pair, not the raw blob.
        assert set(u["location"].keys()) == {"lat", "lng"}


def test_nearby_endpoint_exposes_no_eligibility_knob():
    """Structural guarantee: the only inputs are the case id + the auth dependency.
    There is NO radius/capability/limit parameter a client could pass to widen or
    re-rank the eligible set — eligibility lives entirely in the backend engine."""
    params = list(inspect.signature(dr.rrn_nearby_endpoint).parameters)
    assert params == ["case_id", "current_user"]


# ═══════════════════════ rrn_metrics_endpoint behaviour ═══════════════════════
def test_metrics_merges_real_counts_over_stored_rows():
    """Every number is derived by the REAL counting logic from stored rows — the
    endpoint only merges status_counts() + availability_counts() + a timestamp."""
    dispatches = [
        {"status": "CREATED"}, {"status": "SEARCHING"}, {"status": "OFFERED"},
        {"status": "ACCEPTED"}, {"status": "EN_ROUTE"}, {"status": "HELP_PROVIDED"},
        {"status": "RESOLVED"}, {"status": "CANCELLED"},   # terminal -> not active
    ]
    fresh_ts = datetime.utcnow()
    responders = [
        {"active": True, "verified": True, "duty_status": "ON_DUTY", "status": "AVAILABLE",
         "assigned_dispatch_id": None, "location_updated_at": fresh_ts},
        {"active": True, "verified": True, "duty_status": "ON_DUTY", "status": "AVAILABLE",
         "assigned_dispatch_id": "RRN-x"},
        {"active": True, "verified": True, "duty_status": "ON_DUTY", "status": "BUSY"},
        {"active": True, "verified": True, "duty_status": "ON_DUTY", "status": "OFFLINE"},
        {"active": True, "verified": False, "status": "AVAILABLE"},   # unverified -> excluded
        {"active": False, "verified": True, "status": "AVAILABLE"},   # inactive  -> excluded
    ]
    with _patch(dr.dispatch_service, "_dispatches", lambda: _FakeColl(dispatches)), \
         _patch(dr.responder_service, "list_responders", lambda: list(responders)):
        out = dr.rrn_metrics_endpoint(current_user=_DummyAuthority())

    m = out["metrics"]
    assert m["active_dispatches"] == 6
    assert m["waiting_for_responder"] == 3
    assert m["incidents_in_response"] == 3
    assert m["responders_on_duty"] == 4
    assert m["responders_available"] == 1
    assert m["responders_busy"] == 2
    assert m["generated_at"].endswith("Z")
    # No fabricated extras: the documented counts + the timestamp. availability_counts
    # also reports freshness/roster buckets (stale, offline, total_registered, verified).
    assert set(m.keys()) == {
        "active_dispatches", "waiting_for_responder", "incidents_in_response",
        "responders_available", "responders_stale", "responders_busy",
        "responders_offline", "responders_on_duty", "total_registered", "verified",
        "generated_at",
    }


# ═══════════════════════ dispatch_timeline_endpoint ═══════════════════════════
def test_timeline_404_on_unknown_dispatch():
    """Unknown id must 404 (not an empty list) so an authority can't probe for ids."""
    with _patch(dr.dispatch_service, "get_dispatch", lambda _id: None):
        try:
            dr.dispatch_timeline_endpoint(dispatch_id="NOPE", current_user=_DummyAuthority())
            raised = None
        except dr.HTTPException as e:  # noqa: PERF203
            raised = e
    assert raised is not None and raised.status_code == 404


def test_timeline_surfaces_only_safe_detail():
    """End to end through the endpoint: the timeline exposes only safe detail keys
    (responder_id/reason/via) and never raw GPS or victim PII, even when the stored
    event detail contains them — and entries come back in chronological order."""
    t0 = datetime(2026, 10, 1, 10, 0, 0)
    events = [
        {"dispatch_id": "D-1", "event": "ACCEPTED", "at": t0 + timedelta(minutes=2),
         "detail": {"responder_id": "RESP-A", "via": "accept",
                    "latitude": 28.6, "longitude": 77.2, "victim_user_id": "U-9",
                    "phone": "+91-99999-00000"}},
        {"dispatch_id": "D-1", "event": "CREATED", "at": t0,
         "detail": {"reason": "authority_dispatch"}},
    ]
    with _patch(dr.dispatch_service, "get_dispatch", lambda _id: {"dispatch_id": "D-1"}), \
         _patch(dr.dispatch_service, "_events", lambda: _FakeColl(events)):
        out = dr.dispatch_timeline_endpoint(dispatch_id="D-1", current_user=_DummyAuthority())

    tl = out["timeline"]
    assert [e["event"] for e in tl] == ["CREATED", "ACCEPTED"]   # sorted by `at`
    for entry in tl:
        assert set(entry["detail"].keys()) <= {"responder_id", "reason", "via"}
    blob = repr(tl)
    for leak in ("28.6", "77.2", "U-9", "+91-99999-00000", "latitude", "longitude", "victim"):
        assert leak not in blob


# ═══════════════════════ rrn_network_endpoint behaviour ═══════════════════════
def _net_unit(status="AVAILABLE", active=True, verified=True, fresh=True,
              coords=None, **extra):
    """A responder record for the network roster: duty flags + optional fix age.
    fresh=True -> fresh fix; fresh="stale" -> aged beyond MAX_AGE; fresh=False -> none."""
    ts = None
    if fresh is True:
        ts = datetime.utcnow()
    elif fresh == "stale":
        ts = datetime.utcnow() - timedelta(seconds=MAX_AGE + 60)
    extra.setdefault("duty_status", "ON_DUTY")
    return _unit(coords=coords, updated_at=ts, status=status,
                 active=active, verified=verified, **extra)


def test_network_view_safe_projection_omits_identity_and_raw_gps():
    """An on-duty unit with a fresh fix exposes ONLY the safe roster fields — the
    clean {lat,lng} location (deliberate authority-only exposure) but never officer
    identity, phone, badge, internal id, credentials, the raw GeoJSON blob, or WHICH
    dispatch a busy unit holds."""
    rec = _net_unit(
        coords=[INC_LNG, INC_LAT], status="AVAILABLE", assigned_dispatch_id=None,
        officer_name="Insp. Real Name", badge_number="HR-204-9931",
        phone="+91-99999-00000", user_id="USER-INTERNAL-7",
        password_hash="x", salt="y",
    )
    view = dr._network_responder_view(rec)
    assert set(view.keys()) == {
        "responder_id", "display_label", "status", "capabilities", "jurisdiction",
        "on_duty", "assigned", "location", "location_fresh", "location_age_seconds",
    }
    assert view["on_duty"] is True and view["assigned"] is False
    assert view["location"] == {"lat": INC_LAT, "lng": INC_LNG}
    forbidden = {"officer_name", "badge_number", "phone", "user_id",
                 "assigned_dispatch_id", "current_location", "location_updated_at",
                 "password_hash", "salt"}
    assert not (forbidden & set(view.keys()))
    blob = repr(view)
    for secret in ("Insp. Real Name", "HR-204-9931", "+91-99999-00000", "USER-INTERNAL-7"):
        assert secret not in blob


def test_network_view_location_gated_on_on_duty_and_fresh():
    """location is a map pin ONLY for a unit on duty (active AND verified) with a
    FRESH fix. Stale / unverified / inactive / no-fix -> None, never fabricated."""
    # Fresh fix but UNVERIFIED -> not on duty -> withheld.
    v = dr._network_responder_view(_net_unit(coords=[INC_LNG, INC_LAT], verified=False))
    assert v["on_duty"] is False and v["location"] is None
    # Fresh fix but INACTIVE -> not on duty -> withheld.
    v = dr._network_responder_view(_net_unit(coords=[INC_LNG, INC_LAT], active=False))
    assert v["on_duty"] is False and v["location"] is None
    # On duty but STALE fix -> withheld and flagged not fresh.
    v = dr._network_responder_view(_net_unit(coords=[INC_LNG, INC_LAT], fresh="stale"))
    assert v["on_duty"] is True and v["location"] is None
    assert v["location_fresh"] is False and v["location_age_seconds"] >= MAX_AGE
    # Fresh fix, active & verified, but OFF_DUTY -> not on duty -> withheld.
    v = dr._network_responder_view(_net_unit(coords=[INC_LNG, INC_LAT], duty_status="OFF_DUTY"))
    assert v["on_duty"] is False and v["location"] is None
    # On duty, NO fix at all -> withheld, age None.
    v = dr._network_responder_view(_net_unit(coords=None, fresh=False))
    assert v["location"] is None and v["location_age_seconds"] is None


def test_network_view_assigned_flag_without_leaking_dispatch():
    """`assigned` is a boolean duty flag (holds a live assignment OR status BUSY);
    it must never reveal WHICH dispatch the unit is on."""
    held = dr._network_responder_view(
        _net_unit(status="AVAILABLE", assigned_dispatch_id="RRN-SECRET-123"))
    assert held["assigned"] is True and "RRN-SECRET-123" not in repr(held)
    assert dr._network_responder_view(_net_unit(status="BUSY"))["assigned"] is True
    free = dr._network_responder_view(_net_unit(status="AVAILABLE", assigned_dispatch_id=None))
    assert free["assigned"] is False


def test_authz_network_requires_authority():
    assert _dependency_of(dr.rrn_network_endpoint) is dr.require_authority
    assert _dependency_of(dr.rrn_network_endpoint) is not dr.require_responder
    assert _dependency_of(dr.rrn_network_endpoint) is not dr.get_current_user


def test_network_endpoint_exposes_no_eligibility_knob():
    """The roster endpoint takes only the auth dependency — no client parameter can
    filter, widen, or re-rank the network server-side."""
    assert list(inspect.signature(dr.rrn_network_endpoint).parameters) == ["current_user"]


def test_network_endpoint_filters_orders_and_matches_summary():
    """Only VERIFIED+ACTIVE units appear; order is available-first, then busy, then
    the rest (tie-break by label); and `summary` equals the REAL availability_counts
    over the same rows — nothing fabricated, no identity/raw-GPS/dispatch-id leak."""
    roster = [
        _net_unit(status="AVAILABLE", coords=[INC_LNG, INC_LAT],
                  responder_id="R-ALPHA", display_label="Alpha",
                  officer_name="SECRET NAME", badge_number="BADGE-1",
                  phone="+91-00000-11111", user_id="UID-1"),
        _net_unit(status="AVAILABLE", responder_id="R-ZULU", display_label="Zulu"),
        _net_unit(status="BUSY", responder_id="R-BRAVO", display_label="Bravo",
                  assigned_dispatch_id="RRN-HIDDEN"),
        _net_unit(status="OFFLINE", fresh=False, responder_id="R-CHARLIE",
                  display_label="Charlie"),
        _net_unit(status="AVAILABLE", verified=False,
                  responder_id="R-UNVERIFIED", display_label="Unverified"),
        _net_unit(status="AVAILABLE", active=False,
                  responder_id="R-INACTIVE", display_label="Inactive"),
    ]
    with _patch(dr.responder_service, "list_responders", lambda: list(roster)):
        out = dr.rrn_network_endpoint(current_user=_DummyAuthority())

    # Unverified + inactive excluded; survivors ordered available→busy→other, A→Z.
    assert [r["responder_id"] for r in out["responders"]] == \
        ["R-ALPHA", "R-ZULU", "R-BRAVO", "R-CHARLIE"]
    # summary is the REAL availability_counts() over the same rows (full contract).
    assert out["summary"] == {
        "responders_available": 2, "responders_stale": 0, "responders_busy": 1,
        "responders_offline": 1, "responders_on_duty": 4,
        "total_registered": 5, "verified": 4,
    }
    assert out["generated_at"].endswith("Z")
    blob = repr(out)
    for leak in ("SECRET NAME", "BADGE-1", "+91-00000-11111", "UID-1",
                 "RRN-HIDDEN", "current_location", "assigned_dispatch_id"):
        assert leak not in blob


# ═══════════ victim path NEVER carries responder location (cross-check) ════════
def test_victim_public_view_carries_no_responder_location():
    """The authority-only coordinate exposure must NOT bleed onto the victim path.
    Even when the stored dispatch carries raw responder GPS, the victim view is a
    fixed allowlist with a safe label + help flag only — no location of any kind."""
    doc = {
        "dispatch_id": "D-1", "case_id": "C-1", "status": "EN_ROUTE",
        "assigned_responder_id": "RESP-HR204",
        "incident_location": {"type": "Point", "coordinates": [INC_LNG, INC_LAT]},
        "responder_location": {"type": "Point", "coordinates": [77.25, 28.65]},
        "current_location": {"type": "Point", "coordinates": [77.25, 28.65]},
        "latitude": 28.65, "longitude": 77.25,
    }
    with _patch(dispatch_service, "_responder_label",
                lambda _id: "Verified Response Unit HR-204"):
        view = dispatch_service.public_view(doc, "victim")
    assert set(view.keys()) == {
        "dispatch_id", "case_id", "status", "created_at", "updated_at",
        "assigned_at", "distance_type", "eta_minutes",
        "responder_label", "help_on_the_way",
    }
    assert view["help_on_the_way"] is True
    assert view["responder_label"] == "Verified Response Unit HR-204"
    blob = repr(view)
    for leak in ("coordinates", "current_location", "responder_location",
                 "latitude", "longitude", "77.25", "28.65"):
        assert leak not in blob


# ── standalone runner (mirrors the engine suite; works without pytest) ─────────
def _run_standalone():
    import traceback
    tests = sorted((n, o) for n, o in globals().items()
                   if n.startswith("test_") and callable(o))
    passed = failed = 0
    failures = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            failures.append((name, traceback.format_exc()))
            print(f"  FAIL  {name}")
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    for name, tb in failures:
        print(f"\n===== {name} =====\n{tb}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_standalone())
