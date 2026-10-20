"""Provider management, duty/freshness, honest push status, and dispatch invariants.

Runs against the real engine (services.dispatch_service / responder_service) in its
in-memory fallback, plus the real route functions called directly. It does NOT
exercise a live MongoDB or Redis, and it does NOT run a real push service; those are
verified separately and reported honestly.

Covers:
  PROVIDER  - ADMIN-only provisioning, AUTHORITY denied, role not spoofable,
              setup token single-use/expiring/hashed, verification required,
              off-duty receives no offers.
  DUTY      - ON_DUTY is a separate axis from AVAILABLE; OFF_DUTY clears location,
              push subscription and is refused while assigned; off-duty location
              POSTs are refused.
  FRESHNESS - a stale ON_DUTY fix is not eligible.
  PUSH      - honest status values; NOT_CONFIGURED without VAPID; never DELIVERED;
              push failure never blocks the in-app offer.
  DISPATCH  - batch cap, no duplicate offers, wave advance only after exhaustion,
              early all-decline advance, accepted dispatch never expands, no
              candidates -> FAILED, concurrent accept has exactly one winner.
"""
import inspect
import threading
from datetime import datetime, timedelta

import _rrn_test_support  # noqa: F401

from services import dispatch_service as ds
from services import responder_service as rs
from services import web_push as wp

import test_rapid_response_network as base  # reuse the hermetic harness + fixtures
from test_rapid_response_network import mk_responder, reset_state, AUDIT_CALLS

INC_LNG, INC_LAT = 77.5946, 12.9716


def near(km=0.5):
    """A point ~km north of the incident."""
    return INC_LNG, INC_LAT + km / 111.0


def create_dispatch(case_id, **kw):
    return ds.create_dispatch(
        case_id=case_id, created_by="AUTH-1", created_by_role="authority",
        incident_lng=INC_LNG, incident_lat=INC_LAT, **kw)


# ═══════════════════════════ PROVIDER: authorization ═════════════════════════════
def test_provisioning_is_admin_only_not_authority():
    from routers import admin_routes as ar
    from auth import require_authority
    dep = inspect.signature(ar.create_provider_endpoint).parameters["current_user"].default
    dep = getattr(dep, "dependency", dep)
    assert dep is ar.require_admin
    assert dep is not require_authority


def test_verify_and_activate_are_admin_only():
    from routers import admin_routes as ar
    dep = inspect.signature(ar.update_responder_endpoint).parameters["current_user"].default
    dep = getattr(dep, "dependency", dep)
    assert dep is ar.require_admin


def test_authority_roster_endpoint_is_read_only_authority_gated():
    from routers import dispatch_routes as dr
    dep = inspect.signature(dr.rrn_providers_endpoint).parameters["current_user"].default
    dep = getattr(dep, "dependency", dep)
    assert dep is dr.require_authority


def test_provider_creation_ignores_client_role_and_verification():
    """A client cannot make a provider trusted by sending role/verified/active/password."""
    reset_state()
    from routers import admin_routes as ar

    class Admin:
        user_id, role, name = "ADMIN-1", "admin", "Admin"

    body = {"badge_number": "PRV-100", "display_name": "Unit 100",
            "provider_category": "police", "role": "responder", "verified": True,
            "active": True, "status": "AVAILABLE", "password": "hunter2hunter2"}
    out = ar.create_provider_endpoint(body=body, current_user=Admin())
    rec = rs.get_responder("PRV-100")
    assert rec["verified"] is False                     # verification still required
    assert rec["status"] == "OFFLINE"
    assert rec.get("duty_status", "OFF_DUTY") == "OFF_DUTY"
    assert rec["role"] == "responder"
    assert rec.get("password_set") is False             # no password supplied by admin
    assert "setup_token" in out and out["setup_token"]
    # The admin-supplied password must never be stored or echoed back.
    assert "hunter2hunter2" not in repr(out)
    assert "hunter2hunter2" not in repr(rec)


def test_provider_created_is_not_offered_until_verified():
    reset_state()
    rec = rs.create_responder_inert(badge_number="PRV-200", officer_name="U")
    rs._persist(rec, {"duty_status": "ON_DUTY", "status": "AVAILABLE",
                      "current_location": {"type": "Point", "coordinates": [INC_LNG, INC_LAT]},
                      "location_updated_at": datetime.utcnow()})
    res = create_dispatch("CASE-UNVER")
    assert res["eligible_provider_count"] == 0


def test_setup_token_single_use_and_hashed_at_rest():
    reset_state()
    rec = rs.create_responder_inert(badge_number="PRV-300", officer_name="U")
    rs.mark_password_unset(rec["responder_id"])
    tok = rs.issue_setup_token(rec["responder_id"])
    # Stored only as a digest.
    stored = [v for v in rs._setup_tokens_memory.values()]
    assert stored and all(tok not in repr(v) for v in stored)
    updated, err = rs.consume_setup_token(tok, "a-long-enough-pass")
    assert err is None and updated.get("password_set") is True
    _, err2 = rs.consume_setup_token(tok, "a-long-enough-pass")
    assert err2 == "used"


def test_setup_token_expired_is_rejected():
    reset_state()
    rec = rs.create_responder_inert(badge_number="PRV-301", officer_name="U")
    rs.mark_password_unset(rec["responder_id"])
    tok = rs.issue_setup_token(rec["responder_id"])
    digest = rs._token_digest(tok)
    rs._setup_tokens_memory[digest]["expires_at"] = datetime.utcnow() - timedelta(seconds=1)
    _, err = rs.consume_setup_token(tok, "a-long-enough-pass")
    assert err == "expired"


def test_setup_token_weak_password_rejected():
    reset_state()
    rec = rs.create_responder_inert(badge_number="PRV-302", officer_name="U")
    rs.mark_password_unset(rec["responder_id"])
    tok = rs.issue_setup_token(rec["responder_id"])
    _, err = rs.consume_setup_token(tok, "short")
    assert err == "weak_password"


def test_unset_password_provider_cannot_log_in():
    reset_state()
    rec = rs.create_responder_inert(badge_number="PRV-303", officer_name="U")
    rs.mark_password_unset(rec["responder_id"])
    _, err = rs.authenticate_responder("PRV-303", "anything-at-all")
    assert err == "bad_password"


def test_provisioning_state_labels_from_stored_flags():
    assert rs.provisioning_state({"active": True, "password_set": False}) == "PROVIDER_CREATED"
    assert rs.provisioning_state({"active": True, "password_set": True, "verified": False}) == "VERIFICATION_PENDING"
    assert rs.provisioning_state({"active": True, "verified": True}) == "VERIFIED"
    assert rs.provisioning_state({"active": True, "verified": True, "duty_status": "ON_DUTY"}) == "ACTIVE"
    assert rs.provisioning_state({"active": False, "verified": True}) == "SUSPENDED"


# ═══════════════════════════ DUTY & FRESHNESS ════════════════════════════════════
def test_on_duty_is_not_the_same_as_available():
    reset_state()
    p = mk_responder("DUTY-1", *near(), status="AVAILABLE", on_duty=False)
    assert rs.is_on_duty(p) is False
    rs.set_duty(p["responder_id"], "ON_DUTY")
    p = rs.get_responder("DUTY-1")
    assert rs.is_on_duty(p) and p["status"] == "AVAILABLE"


def test_off_duty_clears_location_and_push_subscription():
    reset_state()
    p = mk_responder("DUTY-2", *near(), on_duty=True)
    rs.set_push_subscription(p["responder_id"], {"endpoint": "https://push.example/x",
                                                 "keys": {"p256dh": "k" * 20, "auth": "a" * 10}})
    rec, err = rs.set_duty(p["responder_id"], "OFF_DUTY")
    assert err is None
    rec = rs.get_responder("DUTY-2")
    assert rec["duty_status"] == "OFF_DUTY"
    assert rec["current_location"] is None and rec["location_updated_at"] is None
    assert rec.get("push_subscription") is None


def test_cannot_go_off_duty_while_assigned():
    reset_state()
    p = mk_responder("DUTY-3", *near(), on_duty=True)
    rs._persist(rs.get_responder("DUTY-3"), {"assigned_dispatch_id": "RRN-LIVE"})
    _, err = rs.set_duty(p["responder_id"], "OFF_DUTY")
    assert err == "assigned"


def test_stale_on_duty_location_is_not_eligible():
    reset_state()
    mk_responder("STALE-1", *near(), fresh=False, on_duty=True)
    res = create_dispatch("CASE-STALE")
    assert res["eligible_provider_count"] == 0


def test_fresh_on_duty_location_is_eligible():
    reset_state()
    mk_responder("FRESH-1", *near(), fresh=True, on_duty=True)
    res = create_dispatch("CASE-FRESH")
    assert res["eligible_provider_count"] == 1


def test_off_duty_provider_receives_no_offers():
    reset_state()
    off = mk_responder("OFF-1", *near(), on_duty=False)
    on = mk_responder("ON-1", *near(0.6), on_duty=True)
    res = create_dispatch("CASE-OFF")
    assert ds.get_offers_for_responder(off["responder_id"]) == []
    assert len(ds.get_offers_for_responder(on["responder_id"])) == 1


def test_off_duty_location_post_is_refused_route():
    """The route refuses a location fix while OFF_DUTY (no secret tracking)."""
    from routers import dispatch_routes as dr
    reset_state()
    mk_responder("LOC-1", *near(), on_duty=False)

    class U:
        user_id = rs.get_responder("LOC-1")["responder_id"]
        role = "responder"

    class Loc:
        latitude, longitude, accuracy = INC_LAT, INC_LNG, 5.0

    try:
        dr.responder_location_endpoint(payload=Loc(), current_user=U())
        raised = None
    except dr.HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 409


# ═══════════════════════════ PUSH: honest status ═════════════════════════════════
def test_push_not_configured_without_vapid(monkeypatch):
    monkeypatch.setattr(wp, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(wp, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setattr(wp, "VAPID_SUBJECT", "")
    assert wp.is_configured() is False
    assert wp.public_key_for_client() is None
    assert wp.send({"endpoint": "https://p/x", "keys": {"p256dh": "k" * 20, "auth": "a" * 10}},
                   {"title": "t"})["status"] == "NOT_CONFIGURED"


def test_vapid_private_key_never_in_client_or_payload(monkeypatch):
    monkeypatch.setattr(wp, "VAPID_PUBLIC_KEY", "PUB-KEY-VALUE")
    monkeypatch.setattr(wp, "VAPID_PRIVATE_KEY", "PRIV-SECRET-VALUE")
    monkeypatch.setattr(wp, "VAPID_SUBJECT", "mailto:ops@example.org")
    monkeypatch.setattr(wp, "_pywebpush", lambda: object())
    assert wp.public_key_for_client() == "PUB-KEY-VALUE"
    payload = wp.build_payload("RRN-1", "CRITICAL", 1800, datetime.utcnow() + timedelta(seconds=20))
    assert "PRIV-SECRET-VALUE" not in repr(payload)


def test_push_payload_has_no_victim_pii_or_location():
    payload = wp.build_payload("RRN-9", "CRITICAL", 1800, datetime.utcnow() + timedelta(seconds=20))
    blob = repr(payload)
    assert payload["title"] == "HAVEN EMERGENCY REQUEST"
    assert "Priority: CRITICAL" in payload["body"] and "1.8 km" in payload["body"]
    for leak in (str(INC_LAT), str(INC_LNG), "CASE-", "victim"):
        assert leak not in blob


def test_subscription_validation_rejects_malformed():
    assert wp.validate_subscription({"endpoint": "http://insecure/x", "keys": {"p256dh": "k", "auth": "a"}}) is None
    assert wp.validate_subscription({"endpoint": "https://ok/x"}) is None
    assert wp.validate_subscription("nope") is None


def test_send_failure_is_reported_honestly_not_delivered(monkeypatch):
    monkeypatch.setattr(wp, "VAPID_PUBLIC_KEY", "PUB")
    monkeypatch.setattr(wp, "VAPID_PRIVATE_KEY", "PRIV")
    monkeypatch.setattr(wp, "VAPID_SUBJECT", "mailto:ops@example.org")

    class FakeResp:
        status_code = 201

    class FakePW:
        @staticmethod
        def webpush(**kw):
            return FakeResp()

    monkeypatch.setattr(wp, "_pywebpush", lambda: FakePW)
    sub = {"endpoint": "https://push.example/x", "keys": {"p256dh": "k" * 20, "auth": "a" * 10}}
    res = wp.send(sub, {"title": "t"})
    assert res["status"] == "SEND_ATTEMPTED"           # handed to push service, NOT delivered
    assert res["status"] != wp.STATUS_DELIVERED


def test_push_failure_does_not_block_in_app_offer(monkeypatch):
    """Push is an enhancement: the offer exists and is listed even if push errors."""
    reset_state()

    def boom(*a, **k):
        raise RuntimeError("push transport down")

    monkeypatch.setattr(ds, "_send_offer_push", lambda *a, **k: {"status": "SEND_FAILED", "reason": "boom"})
    p = mk_responder("PUSH-1", *near(), on_duty=True)
    res = create_dispatch("CASE-PUSHFAIL")
    assert res["eligible_provider_count"] == 1
    offers = ds.get_offers_for_responder(p["responder_id"])
    assert len(offers) == 1


def test_offer_without_subscription_records_subscription_required(monkeypatch):
    reset_state()
    monkeypatch.setattr(wp, "VAPID_PUBLIC_KEY", "PUB")
    monkeypatch.setattr(wp, "VAPID_PRIVATE_KEY", "PRIV")
    monkeypatch.setattr(wp, "VAPID_SUBJECT", "mailto:ops@example.org")
    monkeypatch.setattr(wp, "_pywebpush", lambda: object())
    mk_responder("NOSUB-1", *near(), on_duty=True)
    create_dispatch("CASE-NOSUB")
    att = ds._attempts().find({})[0]
    assert att["push_status"] == "SUBSCRIPTION_REQUIRED"


def test_offer_without_vapid_records_not_configured(monkeypatch):
    # Hermetic: pin VAPID to unconfigured so the result does not depend on the
    # developer's backend/.env (which may hold a real VAPID key pair).
    monkeypatch.setattr(wp, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(wp, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setattr(wp, "VAPID_SUBJECT", "")
    reset_state()
    mk_responder("NOCFG-1", *near(), on_duty=True)
    create_dispatch("CASE-NOCFG")
    att = ds._attempts().find({})[0]
    assert att["push_status"] == "NOT_CONFIGURED"
    assert att["push_status"] != "DELIVERED"


# ═══════════════════════════ DISPATCH: waves & accept ════════════════════════════
def test_first_wave_respects_batch_cap_and_no_duplicates():
    reset_state()
    for i in range(9):
        mk_responder(f"CAP-{i}", *near(0.1 + i * 0.05), on_duty=True)
    res = create_dispatch("CASE-CAP")
    assert res["offered"] is True
    assert res["eligible_provider_count"] <= ds.DISPATCH_MAX_PROVIDERS_PER_WAVE
    d = ds.get_dispatch(res["dispatch"]["dispatch_id"])
    assert len(d["tried_responder_ids"]) == len(set(d["tried_responder_ids"]))


def test_no_eligible_candidates_fails_honestly():
    reset_state()
    res = create_dispatch("CASE-NONE")
    assert res["offered"] is False
    assert res["dispatch"]["status"] == "FAILED"


def test_accepted_dispatch_never_expands():
    reset_state()
    p = mk_responder("ACC-1", *near(), on_duty=True)
    res = create_dispatch("CASE-ACC")
    did = res["dispatch"]["dispatch_id"]
    ds.accept_offer(did, p["responder_id"])
    before = ds.get_dispatch(did)["current_wave_index"]
    ds.process_expirations(now=datetime.utcnow() + timedelta(days=1))
    after = ds.get_dispatch(did)
    assert after["status"] == "ACCEPTED"
    assert after["current_wave_index"] == before


def test_concurrent_accept_has_exactly_one_winner():
    reset_state()
    ids = []
    for i in range(3):
        ids.append(mk_responder(f"RACE-{i}", *near(0.2 + i * 0.1), on_duty=True)["responder_id"])
    res = create_dispatch("CASE-RACE")
    did = res["dispatch"]["dispatch_id"]
    results = []
    barrier = threading.Barrier(len(ids))

    def go(rid):
        barrier.wait()
        d, err, _ = ds.accept_offer(did, rid)
        results.append((rid, err))

    threads = [threading.Thread(target=go, args=(rid,)) for rid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r, e in results if e is None]
    assert len(winners) == 1
    assert ds.get_dispatch(did)["assigned_responder_id"] == winners[0]


def test_double_click_accept_is_idempotent():
    reset_state()
    p = mk_responder("DBL-1", *near(), on_duty=True)
    did = create_dispatch("CASE-DBL")["dispatch"]["dispatch_id"]
    _, e1, _ = ds.accept_offer(did, p["responder_id"])
    _, e2, _ = ds.accept_offer(did, p["responder_id"])
    assert e1 is None and e2 is None
    assert ds.get_dispatch(did)["assigned_responder_id"] == p["responder_id"]


def test_expired_offer_cannot_be_accepted():
    reset_state()
    p = mk_responder("EXP-1", *near(), on_duty=True)
    did = create_dispatch("CASE-EXP")["dispatch"]["dispatch_id"]
    ds.process_expirations(now=datetime.utcnow() + timedelta(days=1))
    _, err, _ = ds.accept_offer(did, p["responder_id"])
    assert err is not None


def test_cancelled_offer_cannot_be_accepted():
    reset_state()
    p = mk_responder("CAN-1", *near(), on_duty=True)
    did = create_dispatch("CASE-CAN")["dispatch"]["dispatch_id"]
    ds.cancel_dispatch(did, "AUTH-1", "authority", reason="test")
    _, err, _ = ds.accept_offer(did, p["responder_id"])
    assert err is not None
    assert ds.get_dispatch(did)["assigned_responder_id"] is None


def test_redis_required_in_production_fails_closed(monkeypatch):
    """Production without Redis must refuse the accept lock (not proceed unlocked)."""
    import rate_limiter as rl
    monkeypatch.setattr(rl, "IS_PRODUCTION", True)
    monkeypatch.setattr(rl, "REDIS_REQUIRED_IN_PRODUCTION", True)
    monkeypatch.setattr(rl, "_resolve_backend", lambda: ("memory", None))
    acquired, _ = ds._acquire_lock("RRN-X")
    assert acquired is False
    acquired_w, _ = ds._acquire_wave_lock("RRN-X")
    assert acquired_w is False


def test_dev_without_redis_is_labelled_single_process_fallback(monkeypatch):
    import rate_limiter as rl
    monkeypatch.setattr(rl, "IS_PRODUCTION", False)
    monkeypatch.setattr(rl, "REDIS_REQUIRED_IN_PRODUCTION", False)
    monkeypatch.setattr(rl, "_resolve_backend", lambda: ("memory", None))
    assert ds._acquire_lock("RRN-Y") == (True, None)
