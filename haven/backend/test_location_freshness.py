"""
Responder location freshness — backend regression tests.

Covers fresh, stale, missing, future and OUT-OF-ORDER fix timestamps against the real
responder_service.update_location write path and the network view that gates what is
shown as a current position. Uses the hermetic in-memory store from
test_rapid_response_network (no Mongo/Redis required).
"""
import pathlib
import re
from datetime import datetime, timedelta

import pytest

import _rrn_test_support  # noqa: F401  (in-memory dependency shims when needed)
from test_rapid_response_network import reset_state, mk_responder
from services import responder_service as rs
from services import dispatch_service as ds
import routers.dispatch_routes as dr

INC_LNG, INC_LAT = 77.5946, 12.9716
MAX_AGE = ds.RESPONDER_LOCATION_MAX_AGE_SECONDS


def _unit(coords, updated_at):
    return {
        "responder_id": "R1", "display_label": "Unit", "status": "AVAILABLE",
        "active": True, "verified": True, "assigned_dispatch_id": None,
        "capabilities": [], "jurisdiction": "Z",
        "current_location": ({"type": "Point", "coordinates": coords} if coords else None),
        "location_updated_at": updated_at,
    }


@pytest.fixture
def on_duty_unit():
    reset_state()
    rec = rs.create_responder_inert(badge_number="LOC-1", officer_name="U")
    rs._persist(rec, {"duty_status": "ON_DUTY", "verified": True, "active": True,
                      "status": "AVAILABLE"})
    return rec["responder_id"]


def _stored(rid):
    return rs.get_responder_by_id(rid)


# ── policy constant ─────────────────────────────────────────────────────────────
def test_backend_policy_is_300s_and_matches_frontend_module():
    assert MAX_AGE == 300
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib"
           / "locationFreshness.ts").read_text(encoding="utf-8")
    m = re.search(r"LOCATION_MAX_AGE_SECONDS\s*=\s*(\d+)", src)
    assert m and int(m.group(1)) == MAX_AGE


# ── fresh / stale / missing via the write path + view ───────────────────────────
def test_fresh_fix_is_stored_and_shown_as_current(on_duty_unit):
    t = datetime.utcnow() - timedelta(seconds=10)
    rs.update_location(on_duty_unit, INC_LNG, INC_LAT, fix_time=t)
    rec = _stored(on_duty_unit)
    assert rec["current_location"]["coordinates"] == [INC_LNG, INC_LAT]
    view = dr._nearby_responder_view(_unit([INC_LNG, INC_LAT], rec["location_updated_at"]),
                                     INC_LNG, INC_LAT)
    assert view["location_fresh"] is True


def test_stale_stored_fix_is_never_shown_as_current():
    old = datetime.utcnow() - timedelta(seconds=MAX_AGE + 120)
    view = dr._nearby_responder_view(_unit([INC_LNG, INC_LAT], old), INC_LNG, INC_LAT)
    assert view["location_fresh"] is False
    assert view["location"] is None  # network view withholds the stale point


def test_missing_fix_is_unknown_and_not_fabricated():
    view = dr._nearby_responder_view(_unit(None, None), INC_LNG, INC_LAT)
    assert view["location_fresh"] is False
    assert view["location"] is None
    assert view["location_age_seconds"] is None


# ── future timestamps ───────────────────────────────────────────────────────────
def test_future_timestamp_beyond_skew_is_rejected_not_stored(on_duty_unit):
    before = _stored(on_duty_unit).get("current_location")
    future = datetime.utcnow() + timedelta(hours=1)
    out = rs.update_location(on_duty_unit, INC_LNG + 0.01, INC_LAT, fix_time=future)
    assert out.get("fix_rejected") == "future_timestamp"
    assert _stored(on_duty_unit).get("current_location") == before


def test_small_future_skew_is_tolerated(on_duty_unit):
    skewed = datetime.utcnow() + timedelta(seconds=5)
    out = rs.update_location(on_duty_unit, INC_LNG, INC_LAT, fix_time=skewed)
    assert out.get("fix_rejected") is None and out.get("fix_superseded") is None


# ── out-of-order delivery ───────────────────────────────────────────────────────
def test_delayed_older_fix_does_not_overwrite_newer(on_duty_unit):
    newer_t = datetime.utcnow() - timedelta(seconds=5)
    older_t = datetime.utcnow() - timedelta(seconds=120)
    rs.update_location(on_duty_unit, 77.6000, 12.9800, fix_time=newer_t)
    out = rs.update_location(on_duty_unit, 77.1000, 12.1000, fix_time=older_t)
    assert out.get("fix_superseded") is True
    stored = _stored(on_duty_unit)
    assert stored["current_location"]["coordinates"] == [77.6000, 12.9800]


def test_newer_fix_after_older_is_applied(on_duty_unit):
    older_t = datetime.utcnow() - timedelta(seconds=120)
    newer_t = datetime.utcnow() - timedelta(seconds=5)
    rs.update_location(on_duty_unit, 77.1000, 12.1000, fix_time=older_t)
    rs.update_location(on_duty_unit, 77.6000, 12.9800, fix_time=newer_t)
    assert _stored(on_duty_unit)["current_location"]["coordinates"] == [77.6000, 12.9800]


def test_timezone_aware_fix_time_is_normalised(on_duty_unit):
    from datetime import timezone
    aware = datetime.now(timezone.utc) - timedelta(seconds=10)
    out = rs.update_location(on_duty_unit, INC_LNG, INC_LAT, fix_time=aware)
    assert out.get("fix_rejected") is None
    assert out["location_updated_at"].tzinfo is None  # stored naive-UTC like the rest


# ── server-side integrity: off-duty clearing and consent still enforced ─────────
def test_off_duty_clears_fix_so_nothing_stale_lingers(on_duty_unit):
    rs.update_location(on_duty_unit, INC_LNG, INC_LAT,
                       fix_time=datetime.utcnow() - timedelta(seconds=10))
    rs.set_duty(on_duty_unit, "OFF_DUTY")
    rec = _stored(on_duty_unit)
    assert rec.get("current_location") is None
    assert rec.get("location_updated_at") is None
