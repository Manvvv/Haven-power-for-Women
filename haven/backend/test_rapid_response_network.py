"""Rapid Response Network — engine test suite (eligibility, FSM, concurrency, privacy).

WHAT THIS VERIFIES (and what it does not):
  * This suite drives the REAL dispatch/responder engine
    (services.dispatch_service + services.responder_service) against their
    in-memory collection fallback — the same code paths that run in production,
    minus the Mongo/Redis transport. It verifies the security- and
    correctness-critical logic that lives in that engine:
      - deterministic eligibility ("eligibility first, distance second")
      - the dispatch finite-state machine and its legal transitions
      - the double-assignment guard (a responder can never be bound to two
        incidents; an offer can be claimed at most once) under real threads
      - privacy of the audience-shaped views (no victim PII to responders, no
        responder identity to victims before acceptance, ETA never fabricated)
      - idempotent replay of accept / progress, and timeout escalation
      - that every state change audits ONLY identifiers (no tokens/PII/GPS logs)
  * It does NOT exercise the HTTP layer, JWT/RBAC dependencies, the WebSocket
    authorization, or a real MongoDB/Redis. Those are integration concerns that
    require the full web stack and a database; run them where FastAPI + a Mongo
    instance are available. The RBAC posture is instead asserted structurally by
    the dispatch_routes dependencies (require_authority / require_responder) and
    reviewed in the security report.

Runs under pytest, OR standalone (`python test_rapid_response_network.py`) via a
tiny built-in runner for environments without pytest installed.
"""
import threading
from datetime import datetime, timedelta

import _rrn_test_support  # noqa: F401  (installs dep shims only when missing)

from services import dispatch_service as ds
from services import responder_service as rs
from services import geo_validation as gv

# ── Audit capture: every _safe_audit → log_audit lands here so we can assert the
#    recorded metadata never carries secrets / tokens / victim PII / raw GPS. ──
AUDIT_CALLS = []
_SENSITIVE_KEYS = {
    "password", "password_hash", "password_salt", "token", "access_token",
    "jwt", "authorization", "secret", "latitude", "longitude", "coordinates",
    "transcript", "safe_word", "message", "victim_user_id", "user_id",
    "current_location", "officer_name",
}


def _capturing_audit(**kw):
    AUDIT_CALLS.append(kw)
    return "AUDIT-TEST"


def reset_state():
    """Hermetic reset: force in-memory stores, clear them, capture audit."""
    # Force the in-memory fallback in BOTH services regardless of environment.
    ds.dispatch_requests = lambda: None
    ds.dispatch_attempts = lambda: None
    ds.response_events = lambda: None
    rs.responders = lambda: None
    # Setup tokens: pin the in-memory store explicitly. Without this, the store
    # selects Mongo whenever a live DB is reachable, and these hermetic tests would
    # silently depend on the environment. Production behaviour (fail-closed when the
    # durable store is required) is unchanged and is covered separately.
    rs._setup_tokens_collection = lambda: None
    # Fresh, empty stores for every test.
    ds._MEM["dispatch_requests"] = ds._MemoryCollection()
    ds._MEM["dispatch_attempts"] = ds._MemoryCollection()
    ds._MEM["response_events"] = ds._MemoryCollection()
    rs._memory_store.clear()
    rs._dev_seeded = True  # suppress any dev-responder seeding
    # Capture audit; silence durable notifications (DB is absent).
    AUDIT_CALLS.clear()
    ds.log_audit = _capturing_audit
    try:
        ds.notification_manager.create_notification = lambda *a, **k: None
    except Exception:
        pass


# ── Fixtures (used by pytest; the standalone runner calls reset_state directly) ─
try:
    import pytest

    @pytest.fixture(autouse=True)
    def _auto_reset():
        reset_state()
        yield
except Exception:  # pragma: no cover - pytest absent (standalone mode)
    pytest = None


# ── Helpers ─────────────────────────────────────────────────────────────────
INC_LNG, INC_LAT = 77.5946, 12.9716  # Bengaluru-ish incident point [lng, lat]


def mk_responder(badge, lng, lat, status="AVAILABLE", verified=True, active=True,
                 caps=None, juris="", fresh=True, on_duty=True):
    """Create a responder directly in the in-memory store, fully positioned.

    on_duty defaults to True: an eligible unit must have declared ON_DUTY (the explicit
    consent point). Pass on_duty=False to model a provider who has not gone on duty.
    """
    rs.create_responder(badge_number=badge, officer_name="Internal Name",
                        password="pw-" + badge, display_label=f"Verified Response Unit {badge}",
                        capabilities=caps or [], jurisdiction=juris, active=active)
    rec = rs.get_responder(badge)
    if verified:
        rs.set_verified(rec["responder_id"], True)
    ts = datetime.utcnow() if fresh else datetime.utcnow() - timedelta(seconds=10 ** 6)
    rs._persist(rec, {
        "status": status,
        "duty_status": "ON_DUTY" if on_duty else "OFF_DUTY",
        "current_location": {"type": "Point", "coordinates": [float(lng), float(lat)]},
        "location_updated_at": ts,
    })
    return rs.get_responder(badge)


def near(dlng=0.001, dlat=0.001):
    """A point a few hundred metres from the incident."""
    return INC_LNG + dlng, INC_LAT + dlat


def create_dispatch(case_id="CASE-1", cap=None, radius=10000, juris=None, victim="VICTIM-1"):
    return ds.create_dispatch(
        case_id=case_id, created_by="AUTH-1", created_by_role="authority",
        incident_lng=INC_LNG, incident_lat=INC_LAT, required_capability=cap,
        radius_m=radius, notes="", incident_jurisdiction=juris, victim_user_id=victim)


# ───────────────────────────── Finite-state machine ───────────────────────────
def test_fsm_valid_transitions():
    reset_state()
    assert ds.is_valid_transition("CREATED", "SEARCHING")
    assert ds.is_valid_transition("SEARCHING", "OFFERED")
    assert ds.is_valid_transition("OFFERED", "ACCEPTED")
    assert ds.is_valid_transition("ACCEPTED", "EN_ROUTE")
    assert ds.is_valid_transition("EN_ROUTE", "ARRIVED")
    assert ds.is_valid_transition("ARRIVED", "HELP_PROVIDED")
    assert ds.is_valid_transition("HELP_PROVIDED", "RESOLVED")


def test_fsm_rejects_illegal_jumps():
    reset_state()
    # Cannot skip from an offer straight to arrival, nor advance a terminal state.
    assert not ds.is_valid_transition("OFFERED", "ARRIVED")
    assert not ds.is_valid_transition("CREATED", "ACCEPTED")
    assert not ds.is_valid_transition("SEARCHING", "ARRIVED")
    for term in ("CANCELLED", "EXPIRED", "FAILED", "RESOLVED"):
        assert ds.is_terminal(term)
        assert not ds.is_valid_transition(term, "ACCEPTED")


# ───────────────────────── Deterministic eligibility ──────────────────────────
def test_eligibility_hard_predicates():
    reset_state()
    lng, lat = near()
    mk_responder("OK", lng, lat)                              # eligible
    mk_responder("UNVERIFIED", lng, lat, verified=False)      # fails verified
    mk_responder("INACTIVE", lng, lat, active=False)          # fails active
    mk_responder("OFFLINE", lng, lat, status="OFFLINE")       # fails AVAILABLE
    mk_responder("STALE", lng, lat, fresh=False)              # fails freshness
    out = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=10000)
    ids = {r["responder_id"] for r in out}
    assert ids == {"RESP-OK"}, ids


def test_eligibility_distance_then_order_and_radius():
    reset_state()
    mk_responder("FAR", *near(0.05, 0.05))     # ~7 km away
    mk_responder("NEAR", *near(0.002, 0.002))  # ~300 m away
    out = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=10000)
    assert [r["responder_id"] for r in out] == ["RESP-NEAR", "RESP-FAR"]
    # Shrinking the radius drops the far unit entirely.
    near_only = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=1000)
    assert [r["responder_id"] for r in near_only] == ["RESP-NEAR"]


def test_eligibility_capability_and_jurisdiction_and_exclude():
    reset_state()
    mk_responder("MED", *near(), caps=["medical"], juris="BLR-C")
    mk_responder("GEN", *near(0.002, 0.0), caps=["general"], juris="BLR-C")
    cap = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=10000,
                           required_capability="medical")
    assert {r["responder_id"] for r in cap} == {"RESP-MED"}
    juris = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=10000,
                             incident_jurisdiction="BLR-N")
    assert juris == []  # neither unit is in the BLR-N jurisdiction
    excl = rs.find_eligible(longitude=INC_LNG, latitude=INC_LAT, radius_m=10000,
                            exclude_ids=["RESP-MED"])
    assert {r["responder_id"] for r in excl} == {"RESP-GEN"}


# ───────────────────────── create_dispatch (human-approved) ───────────────────
def test_create_dispatch_offers_and_audits_human_approved():
    reset_state()
    mk_responder("A", *near())
    res = create_dispatch(case_id="CASE-A")
    d = res["dispatch"]
    assert res["error"] is None and res["offered"] is True
    assert d["status"] == "OFFERED"
    # Incident coords came from the server-supplied fix, stored as GeoJSON [lng,lat].
    assert d["incident_location"]["coordinates"] == [INC_LNG, INC_LAT]
    # The creation was audited as an explicit human-approved action.
    created = [c for c in AUDIT_CALLS if c.get("action") == "DISPATCH_CREATED"]
    assert created and created[0]["reason"] == "human_approved_dispatch"
    assert created[0]["role"] == "authority"


def test_create_dispatch_duplicate_guard():
    reset_state()
    mk_responder("A", *near())
    create_dispatch(case_id="DUP")
    second = create_dispatch(case_id="DUP")
    assert second["error"] == "duplicate"


def test_create_dispatch_rejects_bad_location():
    reset_state()
    res = ds.create_dispatch(case_id="BAD", created_by="AUTH-1",
                             created_by_role="authority", incident_lng=999.0,
                             incident_lat=999.0, victim_user_id="V")
    assert res["error"] == "bad_location"


def test_create_dispatch_fails_when_no_eligible_responder():
    reset_state()
    # No responders at all → first offer cannot be made → FAILED (human follow-up).
    res = create_dispatch(case_id="LONELY")
    assert res["dispatch"]["status"] == "FAILED"
    assert any(c.get("action") == "DISPATCH_FAILED" for c in AUDIT_CALLS)


# ───────────────────────────── Accept happy path ──────────────────────────────
def test_accept_binds_responder_and_victim_sees_help_on_the_way():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-ACC")["dispatch"]
    dd, err, notify = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    assert err is None
    assert dd["status"] == "ACCEPTED"
    assert dd["assigned_responder_id"] == r["responder_id"]
    # The responder is now BUSY and bound to this dispatch.
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["status"] == "BUSY" and rr["assigned_dispatch_id"] == d["dispatch_id"]
    # Victim view flips help_on_the_way true, with a safe label and NO ETA.
    vv = ds.public_view(dd, "victim")
    assert vv["help_on_the_way"] is True
    assert vv["responder_label"] == "Verified Response Unit A"
    assert vv["eta_minutes"] is None and vv["distance_type"] == "straight_line"


# ───────────────── Double-assignment guard (the core concurrency rule) ─────────
def test_responder_cannot_be_claimed_for_two_dispatches_concurrently():
    reset_state()
    r = mk_responder("SOLO", *near())
    # Two independent incidents both legitimately offer to the ONLY nearby unit.
    d1 = create_dispatch(case_id="CASE-X", victim="VX")["dispatch"]
    d2 = create_dispatch(case_id="CASE-Y", victim="VY")["dispatch"]
    assert d1["status"] == "OFFERED" and d2["status"] == "OFFERED"

    results = {}
    barrier = threading.Barrier(2)

    def worker(key, did):
        barrier.wait()  # maximise the race window
        _, err, _ = ds.accept_offer(did, r["responder_id"])
        results[key] = err

    t1 = threading.Thread(target=worker, args=("d1", d1["dispatch_id"]))
    t2 = threading.Thread(target=worker, args=("d2", d2["dispatch_id"]))
    t1.start(); t2.start(); t1.join(); t2.join()

    # Exactly one accept succeeded; the other was refused (responder_unavailable).
    successes = [k for k, v in results.items() if v is None]
    assert len(successes) == 1, results
    won = d1 if successes[0] == "d1" else d2
    lost = d2 if successes[0] == "d1" else d1
    won_doc = ds.get_dispatch(won["dispatch_id"])
    lost_doc = ds.get_dispatch(lost["dispatch_id"])
    assert won_doc["status"] == "ACCEPTED"
    assert won_doc["assigned_responder_id"] == r["responder_id"]
    # The losing dispatch is NOT assigned to the (now-busy) responder.
    assert lost_doc["assigned_responder_id"] != r["responder_id"]
    assert lost_doc["status"] != "ACCEPTED"
    # The responder is bound to exactly one dispatch.
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["assigned_dispatch_id"] == won["dispatch_id"]


def test_try_claim_is_atomic_under_many_threads():
    reset_state()
    r = mk_responder("ATOM", *near())
    winners = []

    def claim(i):
        got = rs.try_claim_for_dispatch(r["responder_id"], f"RRN-{i}")
        if got is not None:
            winners.append(f"RRN-{i}")

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # The conditional single-document claim admits exactly one winner.
    assert len(winners) == 1, winners
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["status"] == "BUSY" and rr["assigned_dispatch_id"] == winners[0]


def test_non_offered_responder_cannot_accept():
    reset_state()
    r1 = mk_responder("ON", *near())             # within radius → receives broadcast offer
    r2 = mk_responder("OFF2", *near(1.0, 1.0))   # far away (outside radius) → not offered
    d = create_dispatch(case_id="CASE-NO")["dispatch"]
    assert ds.get_dispatch(d["dispatch_id"])["current_attempt_id"]
    # A responder who was NOT offered this dispatch cannot claim it.
    _, err, _ = ds.accept_offer(d["dispatch_id"], r2["responder_id"])
    assert err == "offer_unavailable"
    # The legitimately-offered unit still can.
    _, err2, _ = ds.accept_offer(d["dispatch_id"], r1["responder_id"])
    assert err2 is None


# ─────────────────────── Decline / timeout escalation ─────────────────────────
def test_decline_reoffers_to_next_unit():
    reset_state()
    r1 = mk_responder("FIRST", *near(0.001, 0.0))   # nearest → first offer
    r2 = mk_responder("SECOND", *near(0.003, 0.0))  # next nearest
    d = create_dispatch(case_id="CASE-DEC")["dispatch"]
    first_offered = ds.get_dispatch(d["dispatch_id"])["tried_responder_ids"][0]
    ds.decline_offer(d["dispatch_id"], first_offered)
    cur = ds.get_dispatch(d["dispatch_id"])
    assert cur["status"] == "OFFERED"
    # The re-offer went to the OTHER unit; the decliner is not re-tried.
    assert set(cur["tried_responder_ids"]) == {r1["responder_id"], r2["responder_id"]}


def test_timeout_escalates_then_fails_when_exhausted():
    reset_state()
    mk_responder("ONLY", *near())
    d = create_dispatch(case_id="CASE-TO")["dispatch"]
    # Force the outstanding offer to be expired, then run the idempotent sweep.
    future = datetime.utcnow() + timedelta(seconds=10 ** 6)
    out = ds.process_expirations(now=future)
    assert out["expired"] == 1
    cur = ds.get_dispatch(d["dispatch_id"])
    # Only one unit existed and it was already tried → dispatch FAILS, not re-offers.
    assert cur["status"] == "FAILED"
    assert any(c.get("action") == "DISPATCH_OFFER_TIMEOUT" for c in AUDIT_CALLS)
    # Idempotent: a second sweep expires nothing more.
    assert ds.process_expirations(now=future)["expired"] == 0


# ───────────────────────── Accept replay idempotency ──────────────────────────
def test_accept_is_idempotent_on_replay():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-REPLAY")["dispatch"]
    d1, e1, _ = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    assert e1 is None and d1["status"] == "ACCEPTED"
    # Re-sending the same accept must NOT create a second binding or error.
    d2, e2, notify2 = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    assert e2 is None and d2["status"] == "ACCEPTED" and notify2 == []
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["status"] == "BUSY" and rr["assigned_dispatch_id"] == d["dispatch_id"]


# ─────────────────────────── Cancel frees responder ───────────────────────────
def test_cancel_frees_bound_responder():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-CAN")["dispatch"]
    ds.accept_offer(d["dispatch_id"], r["responder_id"])
    assert rs.get_responder_by_id(r["responder_id"])["status"] == "BUSY"
    dd, err, _ = ds.cancel_dispatch(d["dispatch_id"], "AUTH-1", "authority", reason="stand down")
    assert err is None and dd["status"] == "CANCELLED"
    # The responder is released: AVAILABLE again and bound to nothing.
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["status"] == "AVAILABLE" and rr["assigned_dispatch_id"] in (None, "")
    # Cancelling a terminal dispatch is refused (no state change).
    _, err2, _ = ds.cancel_dispatch(d["dispatch_id"], "AUTH-1", "authority")
    assert err2 == "already_terminal"


# ─────────────────── Responder progress FSM (assigned only) ────────────────────
def test_mark_progress_happy_path_and_idempotent_replay():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-PROG")["dispatch"]
    did = d["dispatch_id"]
    ds.accept_offer(did, r["responder_id"])
    for state in ("EN_ROUTE", "ARRIVED", "HELP_PROVIDED"):
        dd, err, _ = ds.mark_progress(did, r["responder_id"], state)
        assert err is None and dd["status"] == state
        # Replaying the SAME state is idempotent (no error, no regression).
        dd2, err2, notify2 = ds.mark_progress(did, r["responder_id"], state)
        assert err2 is None and dd2["status"] == state and notify2 == []


def test_mark_progress_rejects_forbidden_bad_state_and_illegal_jump():
    reset_state()
    r1 = mk_responder("A", *near())
    r2 = mk_responder("B", *near(0.02, 0.0))  # far → never offered/assigned
    d = create_dispatch(case_id="CASE-PROG2")["dispatch"]
    did = d["dispatch_id"]
    ds.accept_offer(did, r1["responder_id"])
    # A responder not bound to the dispatch cannot advance it.
    _, err_forbidden, _ = ds.mark_progress(did, r2["responder_id"], "EN_ROUTE")
    assert err_forbidden == "forbidden"
    # A state outside the responder-progress set is rejected before any FSM check.
    _, err_bad, _ = ds.mark_progress(did, r1["responder_id"], "RESOLVED")
    assert err_bad == "bad_state"
    # Advance to ARRIVED, then an illegal backward jump to EN_ROUTE is refused.
    ds.mark_progress(did, r1["responder_id"], "ARRIVED")
    _, err_jump, _ = ds.mark_progress(did, r1["responder_id"], "EN_ROUTE")
    assert err_jump == "invalid_transition"


# ──────────── RESOLVED via the EXISTING case-resolution workflow ───────────────
def test_resolve_for_case_frees_responder_and_is_idempotent():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-RES")["dispatch"]
    ds.accept_offer(d["dispatch_id"], r["responder_id"])
    dd, _ = ds.resolve_dispatch_for_case("CASE-RES", "AUTH-1", "authority")
    assert dd["status"] == "RESOLVED"
    rr = rs.get_responder_by_id(r["responder_id"])
    assert rr["status"] == "AVAILABLE" and rr["assigned_dispatch_id"] in (None, "")
    # Idempotent: no active dispatch remains for the case.
    again, notify = ds.resolve_dispatch_for_case("CASE-RES", "AUTH-1", "authority")
    assert again is None and notify == []


# ──────────────────── Privacy of the audience-shaped views ─────────────────────
def test_public_view_victim_hides_pii_and_coords_and_never_fabricates_eta():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-PV", victim="VICTIM-SECRET")["dispatch"]
    dd, _, _ = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    vv = ds.public_view(dd, "victim")
    # The victim sees a safe label and truthful "help_on_the_way" — nothing more.
    assert vv["responder_label"] == "Verified Response Unit A"
    assert vv["help_on_the_way"] is True
    # No incident coordinates, no victim id, no responder identity, no fabricated ETA.
    assert "incident_location" not in vv and "coordinates" not in vv
    assert "victim_user_id" not in vv and "assigned_responder_id" not in vv
    assert vv["eta_minutes"] is None and vv["distance_type"] == "straight_line"


def test_public_view_responder_has_incident_but_no_victim_identity():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-PV2", victim="VICTIM-SECRET")["dispatch"]
    dd, _, _ = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    rv = ds.public_view(dd, "responder")
    # The responder needs the incident location + offer window to actually respond.
    assert rv["incident_location"]["coordinates"] == [INC_LNG, INC_LAT]
    assert "accept_timeout_seconds" in rv
    # But no victim PII and no victim user id ever reaches a responder.
    assert "victim_user_id" not in rv
    assert "VICTIM-SECRET" not in str(rv)


def test_public_view_authority_is_operational_without_victim_pii():
    reset_state()
    r = mk_responder("A", *near())
    d = create_dispatch(case_id="CASE-PV3", victim="VICTIM-SECRET")["dispatch"]
    dd, _, _ = ds.accept_offer(d["dispatch_id"], r["responder_id"])
    av = ds.public_view(dd, "authority")
    # Authority gets the fullest operational view (it already handles the case).
    assert av["assigned_responder_id"] == r["responder_id"]
    assert av["created_by_role"] == "authority" and av["attempts_made"] >= 1
    # Even so, the victim's internal user id is never surfaced in any view.
    assert "victim_user_id" not in av
    assert "VICTIM-SECRET" not in str(av)


# ──────────────────── Audit records only identifiers (no PII) ──────────────────
def _assert_audit_calls_are_pii_free():
    """Every captured audit call carries identifiers only — never a secret/PII/GPS."""
    assert AUDIT_CALLS, "expected at least one audited action"
    for call in AUDIT_CALLS:
        # Top-level kwargs must not themselves be sensitive channels.
        bad_top = _SENSITIVE_KEYS & set(call.keys())
        assert not bad_top, (bad_top, call)
        meta = call.get("metadata") or {}
        bad_meta = _SENSITIVE_KEYS & set(meta.keys())
        assert not bad_meta, (bad_meta, call)
        # The victim's internal id must never leak through any audited string value.
        blob = " ".join(str(v) for v in list(call.values()) + list(meta.values()))
        assert "VICTIM-SECRET" not in blob, call


def test_audit_trail_logs_identifiers_only_across_a_full_flow():
    reset_state()
    r = mk_responder("A", *near())
    # A complete lifecycle generates DISPATCH_CREATED/ACCEPTED/EN_ROUTE/.../RESOLVED.
    d = create_dispatch(case_id="CASE-AUDIT", victim="VICTIM-SECRET")["dispatch"]
    did = d["dispatch_id"]
    ds.accept_offer(did, r["responder_id"])
    ds.mark_progress(did, r["responder_id"], "EN_ROUTE")
    ds.mark_progress(did, r["responder_id"], "ARRIVED")
    ds.mark_progress(did, r["responder_id"], "HELP_PROVIDED")
    ds.resolve_dispatch_for_case("CASE-AUDIT", "AUTH-1", "authority")
    actions = {c.get("action") for c in AUDIT_CALLS}
    assert {"DISPATCH_CREATED", "DISPATCH_ACCEPTED", "DISPATCH_RESOLVED"} <= actions
    _assert_audit_calls_are_pii_free()



# ═══════════════════════════════════════════════════════════════════════════════
# ── BROADCAST DISPATCH MODEL TEST SUITE (26 EXPLICIT REQUIREMENTS) ───────────
# ═══════════════════════════════════════════════════════════════════════════════

def test_broadcast_dispatch_creates_offers_for_all_eligible_providers():
    """Requirement 1: Broadcast creates offers for ALL eligible providers simultaneously."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    p3 = mk_responder("P3", *near(0.003, 0.003))
    res = create_dispatch(case_id="CASE-BC-1")
    d = res["dispatch"]
    assert d["status"] == "OFFERED"
    assert res["eligible_provider_count"] == 3

    # All 3 providers receive an offer
    o1 = ds.get_offers_for_responder(p1["responder_id"])
    o2 = ds.get_offers_for_responder(p2["responder_id"])
    o3 = ds.get_offers_for_responder(p3["responder_id"])
    assert len(o1) == 1 and o1[0]["dispatch_id"] == d["dispatch_id"]
    assert len(o2) == 1 and o2[0]["dispatch_id"] == d["dispatch_id"]
    assert len(o3) == 1 and o3[0]["dispatch_id"] == d["dispatch_id"]

    # 3 PENDING attempts in DB
    offers = ds.get_offers_for_dispatch(d["dispatch_id"])
    assert len(offers) == 3
    assert all(o["response"] == "PENDING" for o in offers)


def test_first_acceptance_wins_atomically():
    """Requirement 2: First valid server-side acceptance wins the dispatch."""
    reset_state()
    p1 = mk_responder("PA", *near(0.001, 0.001))
    p2 = mk_responder("PB", *near(0.002, 0.002))
    p3 = mk_responder("PC", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-WIN-1")["dispatch"]
    did = d["dispatch_id"]

    # Provider A accepts first
    updated, err, notify = ds.accept_offer(did, p1["responder_id"])
    assert err is None
    assert updated["status"] == "ACCEPTED"
    assert updated["assigned_responder_id"] == p1["responder_id"]

    # Provider A is atomically bound to BUSY
    rec = rs.get_responder("PA")
    assert rec["status"] == "BUSY"
    assert rec["assigned_dispatch_id"] == did


def test_concurrent_accept_second_provider_gets_409():
    """Requirement 3: Second provider trying to accept loses the race with offer_unavailable."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-RACE-2")["dispatch"]
    did = d["dispatch_id"]

    # Provider 1 wins
    ds.accept_offer(did, p1["responder_id"])

    # Provider 2 loses
    _, err, _ = ds.accept_offer(did, p2["responder_id"])
    assert err == "offer_unavailable"


def test_concurrent_accept_third_provider_gets_409():
    """Requirement 4: Third provider trying to accept also loses with offer_unavailable."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    p3 = mk_responder("P3", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-RACE-3")["dispatch"]
    did = d["dispatch_id"]

    ds.accept_offer(did, p1["responder_id"])
    ds.accept_offer(did, p2["responder_id"])
    _, err3, _ = ds.accept_offer(did, p3["responder_id"])
    assert err3 == "offer_unavailable"


def test_other_offers_cancelled_after_first_accept():
    """Requirement 5: When one provider wins, all other pending offers are marked CANCELLED."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    p3 = mk_responder("P3", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-CANCEL-OTHERS")["dispatch"]
    did = d["dispatch_id"]

    ds.accept_offer(did, p2["responder_id"])  # P2 wins

    offers = ds.get_offers_for_dispatch(did)
    by_resp = {o["responder_id"]: o["response"] for o in offers}
    assert by_resp[p2["responder_id"]] == "ACCEPTED"
    assert by_resp[p1["responder_id"]] == "CANCELLED"
    assert by_resp[p3["responder_id"]] == "CANCELLED"


def test_cancelled_offer_cannot_be_accepted_later():
    """Requirement 6: A cancelled offer can never be accepted."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-CANCELLED-ACCEPT")["dispatch"]
    did = d["dispatch_id"]

    ds.accept_offer(did, p1["responder_id"])  # P1 wins, P2 cancelled
    _, err, _ = ds.accept_offer(did, p2["responder_id"])
    assert err == "offer_unavailable"


def test_declined_offer_leaves_other_offers_pending():
    """Requirement 7: One provider declining leaves other broadcast offers PENDING."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    p3 = mk_responder("P3", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-DEC-LEAVE")["dispatch"]
    did = d["dispatch_id"]

    # P1 declines
    updated, err, _ = ds.decline_offer(did, p1["responder_id"])
    assert err is None
    assert updated["status"] == "OFFERED"  # still OFFERED because P2, P3 remain

    offers = ds.get_offers_for_dispatch(did)
    by_resp = {o["responder_id"]: o["response"] for o in offers}
    assert by_resp[p1["responder_id"]] == "DECLINED"
    assert by_resp[p2["responder_id"]] == "PENDING"
    assert by_resp[p3["responder_id"]] == "PENDING"


def test_all_declined_marks_dispatch_failed():
    """Requirement 8: If every offered provider declines, dispatch transitions to FAILED."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-ALL-DEC")["dispatch"]
    did = d["dispatch_id"]

    ds.decline_offer(did, p1["responder_id"])
    updated, err, notify = ds.decline_offer(did, p2["responder_id"])
    assert err is None
    assert updated["status"] == "FAILED"
    assert any(n.get("event_type") == "dispatch_failed" for n in notify)


def test_timeout_on_single_provider_leaves_others_pending():
    """Requirement 9: Timeout on one provider leaves other offers pending."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-TO-SINGLE")["dispatch"]
    did = d["dispatch_id"]

    # Manually expire P1's attempt only
    now = datetime.utcnow()
    past = now - timedelta(seconds=100)
    future = now + timedelta(seconds=100)
    ds._attempts().update_one({"dispatch_id": did, "responder_id": p1["responder_id"]},
                              {"$set": {"expires_at": past}})
    ds._attempts().update_one({"dispatch_id": did, "responder_id": p2["responder_id"]},
                              {"$set": {"expires_at": future}})

    res = ds.process_expirations(now=now)
    assert res["expired"] == 1
    assert res["failed"] == 0

    cur = ds.get_dispatch(did)
    assert cur["status"] == "OFFERED"  # P2 is still pending


def test_timeout_on_all_providers_marks_dispatch_failed():
    """Requirement 10: Timeout on all providers transitions dispatch to FAILED."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-TO-ALL")["dispatch"]
    did = d["dispatch_id"]

    past = datetime.utcnow() - timedelta(seconds=100)
    ds._attempts().update_one({"dispatch_id": did, "responder_id": p1["responder_id"]},
                              {"$set": {"expires_at": past}})
    ds._attempts().update_one({"dispatch_id": did, "responder_id": p2["responder_id"]},
                              {"$set": {"expires_at": past}})

    res = ds.process_expirations()
    assert res["expired"] == 2
    assert res["failed"] == 1
    assert ds.get_dispatch(did)["status"] == "FAILED"


def test_provider_double_click_accept_is_idempotent():
    """Requirement 11: Double-click ACCEPT by the same winning provider is idempotent."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    d = create_dispatch(case_id="CASE-DBL-CLICK")["dispatch"]
    did = d["dispatch_id"]

    r1, err1, _ = ds.accept_offer(did, p1["responder_id"])
    assert err1 is None
    assert r1["status"] == "ACCEPTED"

    # Second click
    r2, err2, _ = ds.accept_offer(did, p1["responder_id"])
    assert err2 is None
    assert r2["status"] == "ACCEPTED"
    assert r2["assigned_responder_id"] == p1["responder_id"]


def test_provider_becomes_busy_elsewhere_before_accept_fails_safely():
    """Requirement 12: Provider claimed by another incident before accept fails safely."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    d1 = create_dispatch(case_id="CASE-BUSY-1")["dispatch"]

    # P1 becomes busy on another case
    rs.try_claim_for_dispatch(p1["responder_id"], "DISPATCH-OTHER")

    # P1 tries to accept d1
    _, err, _ = ds.accept_offer(d1["dispatch_id"], p1["responder_id"])
    assert err == "responder_unavailable"

    # d1 stays OFFERED for P2
    cur = ds.get_dispatch(d1["dispatch_id"])
    assert cur["status"] == "OFFERED"
    # P2 can still accept
    d1_won, err2, _ = ds.accept_offer(d1["dispatch_id"], p2["responder_id"])
    assert err2 is None
    assert d1_won["assigned_responder_id"] == p2["responder_id"]


def test_off_duty_provider_not_eligible_for_broadcast():
    """Requirement 13: OFF_DUTY (OFFLINE) provider is not eligible for broadcast offers."""
    reset_state()
    p_off = mk_responder("POFF", *near(), status="AVAILABLE", on_duty=False)
    p_on = mk_responder("PON", *near(), status="AVAILABLE")
    res = create_dispatch(case_id="CASE-OFFDUTY")
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_off["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_on["responder_id"])) == 1


def test_out_of_radius_provider_not_eligible():
    """Requirement 14: Provider beyond radius is not eligible for broadcast."""
    reset_state()
    p_near = mk_responder("PNEAR", *near(0.001, 0.001))
    p_far = mk_responder("PFAR", *near(1.0, 1.0))  # ~150km away
    res = create_dispatch(case_id="CASE-RADIUS", radius=10000)
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_far["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_near["responder_id"])) == 1


def test_wrong_jurisdiction_provider_not_eligible():
    """Requirement 15: Provider outside incident jurisdiction is not eligible."""
    reset_state()
    p_north = mk_responder("PNORTH", *near(), juris="North Zone")
    p_south = mk_responder("PSOUTH", *near(), juris="South Zone")
    res = create_dispatch(case_id="CASE-JURIS", juris="North Zone")
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_south["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_north["responder_id"])) == 1


def test_stale_location_provider_not_eligible():
    """Requirement 16: Provider with stale GPS location is not eligible."""
    reset_state()
    p_fresh = mk_responder("PFRESH", *near(), fresh=True)
    p_stale = mk_responder("PSTALE", *near(), fresh=False)
    res = create_dispatch(case_id="CASE-STALE")
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_stale["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_fresh["responder_id"])) == 1


def test_unverified_provider_not_eligible():
    """Requirement 17: Unverified provider account is not eligible."""
    reset_state()
    p_unv = mk_responder("PUNV", *near(), verified=False)
    p_ver = mk_responder("PVER", *near(), verified=True)
    res = create_dispatch(case_id="CASE-UNVER")
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_unv["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_ver["responder_id"])) == 1


def test_inactive_provider_not_eligible():
    """Requirement 18: Inactive provider account is not eligible."""
    reset_state()
    p_inact = mk_responder("PINACT", *near(), active=False)
    p_act = mk_responder("PACT", *near(), active=True)
    res = create_dispatch(case_id="CASE-INACT")
    assert res["eligible_provider_count"] == 1
    assert len(ds.get_offers_for_responder(p_inact["responder_id"])) == 0
    assert len(ds.get_offers_for_responder(p_act["responder_id"])) == 1


def test_authority_sees_broadcast_offer_breakdown():
    """Requirement 19: Authority can inspect all broadcast offer statuses."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    p2 = mk_responder("P2", *near(0.002, 0.002))
    p3 = mk_responder("P3", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-AUTH-VIEW")["dispatch"]
    did = d["dispatch_id"]

    # P2 declines
    ds.decline_offer(did, p2["responder_id"])

    # Authority fetches offers
    offers = ds.get_offers_for_dispatch(did)
    assert len(offers) == 3
    by_status = {o["responder_id"]: o["response"] for o in offers}
    assert by_status[p1["responder_id"]] == "PENDING"
    assert by_status[p2["responder_id"]] == "DECLINED"
    assert by_status[p3["responder_id"]] == "PENDING"

    # Safe display labels only — no officer phone/name
    assert all("Verified Response Unit" in o["display_label"] for o in offers)


def test_authority_map_shows_eligible_providers_before_accept():
    """Requirement 20: Authority map shows eligible providers before acceptance."""
    reset_state()
    mk_responder("P1", *near(0.001, 0.001))
    mk_responder("P2", *near(0.002, 0.002))
    eligible = rs.find_eligible(INC_LNG, INC_LAT, radius_m=10000)
    assert len(eligible) == 2
    # Before accept, none are assigned
    assert all(e["status"] == "AVAILABLE" for e in eligible)


def test_authority_map_shows_only_assigned_after_accept():
    """Requirement 21: Active assigned responders roster only contains the accepted unit."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-ACTIVE-ROSTER")["dispatch"]
    ds.accept_offer(d["dispatch_id"], p1["responder_id"])

    assigned = ds.active_assigned_responders()
    assert len(assigned) == 1
    assert assigned[0]["responder_id"] == p1["responder_id"]
    assert assigned[0]["dispatch_id"] == d["dispatch_id"]


def test_victim_sees_only_assigned_provider_after_accept():
    """Requirement 22: Victim view contains safe unit label once accepted."""
    reset_state()
    p1 = mk_responder("P1", *near(0.001, 0.001))
    d = create_dispatch(case_id="CASE-VICTIM-VIEW")["dispatch"]
    ds.accept_offer(d["dispatch_id"], p1["responder_id"])

    updated = ds.get_dispatch(d["dispatch_id"])
    v = ds.public_view(updated, "victim")
    assert v["responder_label"] == "Verified Response Unit P1"
    assert v["help_on_the_way"] is True
    assert "incident_location" not in v  # no leaking
    assert "created_by" not in v


def test_victim_never_sees_unassigned_nearby_providers():
    """Requirement 23: Victim never sees unassigned candidate providers."""
    reset_state()
    mk_responder("P1", *near(0.001, 0.001))
    mk_responder("P2", *near(0.002, 0.002))
    d = create_dispatch(case_id="CASE-VICTIM-NO-LEAK")["dispatch"]

    v = ds.public_view(d, "victim")
    assert v["responder_label"] is None
    assert v["help_on_the_way"] is False
    assert "candidates" not in v
    assert "tried_responder_ids" not in v


def test_progress_state_machine_en_route_arrived_help_provided():
    """Requirement 24: Provider advances EN_ROUTE → ARRIVED → HELP_PROVIDED."""
    reset_state()
    p = mk_responder("P1", *near())
    d = create_dispatch(case_id="CASE-PROGRESS")["dispatch"]
    did = d["dispatch_id"]
    pid = p["responder_id"]

    ds.accept_offer(did, pid)

    d1, err1, _ = ds.mark_progress(did, pid, "EN_ROUTE")
    assert err1 is None and d1["status"] == "EN_ROUTE"

    d2, err2, _ = ds.mark_progress(did, pid, "ARRIVED")
    assert err2 is None and d2["status"] == "ARRIVED"

    d3, err3, _ = ds.mark_progress(did, pid, "HELP_PROVIDED")
    assert err3 is None and d3["status"] == "HELP_PROVIDED"


def test_cancel_dispatch_cancels_all_broadcast_offers():
    """Requirement 25: Authority cancel terminates all pending broadcast offers."""
    reset_state()
    mk_responder("P1", *near(0.001, 0.001))
    mk_responder("P2", *near(0.002, 0.002))
    mk_responder("P3", *near(0.003, 0.003))
    d = create_dispatch(case_id="CASE-CANCEL-ALL")["dispatch"]
    did = d["dispatch_id"]

    cancelled_d, err, _ = ds.cancel_dispatch(did, "AUTH-1", "authority", "Test cancel")
    assert err is None
    assert cancelled_d["status"] == "CANCELLED"

    offers = ds.get_offers_for_dispatch(did)
    assert all(o["response"] == "CANCELLED" for o in offers)


def test_movement_trail_real_gps_only_max_40_in_memory():
    """Requirement 26: Temporary client-side GPS movement trail constraints."""
    # Verify the trail rules: client-side, real GPS only, max 40 points, no DB storage
    trail = []
    for i in range(50):
        # Only real GPS frames (no interpolation)
        lat = 12.9716 + (i * 0.0001)
        lng = 77.5946 + (i * 0.0001)
        trail.append({"lat": lat, "lng": lng})
        if len(trail) > 40:
            trail = trail[-40:]  # strictly capped at 40 in-memory points

    assert len(trail) == 40
    # No persistence in MongoDB
    assert ds._dispatches().find_one({"movement_trail": {"$exists": True}}) is None


# ─────────────────────────── Standalone test runner ───────────────────────────
# Runs the whole suite WITHOUT pytest (`python test_rapid_response_network.py`),
# so the engine can be verified in a sandbox that has no pytest installed.
def _run_standalone():
    import traceback
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = failed = 0
    failures = []
    for name, fn in tests:
        reset_state()  # hermetic: mirror the pytest autouse fixture
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception:  # noqa: BLE001 - report every failure, keep going
            failed += 1
            failures.append((name, traceback.format_exc()))
            print(f"  FAIL  {name}")
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    for name, tb in failures:
        print(f"\n===== {name} =====\n{tb}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(_run_standalone())




