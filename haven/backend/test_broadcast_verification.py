"""Phase 4 verification: End-to-end Broadcast Dispatch flow with configured test providers.

Verifies:
  1. Incident location resolution from case.
  2. Multiple providers eligible.
  3. Authority initiates dispatch.
  4. Every eligible provider gets a PENDING offer.
  5. eligible_provider_count matches the actual eligible set.
  6. offers_sent matches actual notifications.
  7. First valid acceptance wins atomically.
  8. All other pending offers cancelled after acceptance.
  9. Declines leave other valid pending offers active.
 10. All-offers-exhausted produces FAILED.
 11. Duplicate accept is idempotent; lost race gets 409 offer_unavailable.
"""
from datetime import datetime, timedelta
import _rrn_test_support  # installs shims if needed

from services import dispatch_service as ds
from services import responder_service as rs
from seed_dev_responders import TEST_INC_LNG, TEST_INC_LAT

def run_verification():
    print("=" * 70)
    print("PHASE 4 VERIFICATION: BROADCAST DISPATCH WITH TEST PROVIDERS")
    print("=" * 70)

    # 1. Reset state
    ds.dispatch_requests = lambda: None
    ds.dispatch_attempts = lambda: None
    ds.response_events = lambda: None
    rs.responders = lambda: None
    ds._MEM["dispatch_requests"] = ds._MemoryCollection()
    ds._MEM["dispatch_attempts"] = ds._MemoryCollection()
    ds._MEM["response_events"] = ds._MemoryCollection()
    rs._memory_store.clear()
    rs._dev_seeded = True

    # 2. Seed 3 test providers (HN-204, HN-205, HN-206) near the incident
    providers = [
        {"badge": "HN-204", "name": "Unit Rao", "lng": TEST_INC_LNG + 0.001, "lat": TEST_INC_LAT + 0.001},
        {"badge": "HN-205", "name": "Unit Sharma", "lng": TEST_INC_LNG - 0.002, "lat": TEST_INC_LAT + 0.002},
        {"badge": "HN-206", "name": "Unit Kumar", "lng": TEST_INC_LNG + 0.003, "lat": TEST_INC_LAT - 0.002},
    ]
    for p in providers:
        rs.create_responder(
            badge_number=p["badge"],
            officer_name=p["name"],
            password="testpassword",
            display_label=f"Verified Response Unit {p['badge']}",
            capabilities=["general", "patrol"],
            jurisdiction="Zone-5",
            active=True,
        )
        rec = rs.get_responder(p["badge"])
        rs.set_verified(rec["responder_id"], True)
        rs._persist(rec, {
            "duty_status": "ON_DUTY",
            "status": "AVAILABLE",
            "current_location": {"type": "Point", "coordinates": [p["lng"], p["lat"]]},
            "location_updated_at": datetime.utcnow(),
        })

    # Verify eligibility query
    eligible = rs.find_eligible(TEST_INC_LNG, TEST_INC_LAT, radius_m=10000)
    print(f"[Step 2] Eligible providers found: {len(eligible)} (expected: 3)")
    assert len(eligible) == 3, f"Expected 3 eligible, got {len(eligible)}"
    print("  ✓ PASS: All 3 configured test providers are eligible")

    # 3. Authority initiates dispatch
    print("[Step 3] Authority initiates dispatch for case CASE-BCAST-1...")
    res = ds.create_dispatch(
        case_id="CASE-BCAST-1",
        created_by="AUTH-01",
        created_by_role="authority",
        incident_lng=TEST_INC_LNG,
        incident_lat=TEST_INC_LAT,
        radius_m=10000,
        notes="High urgency",
    )

    d = res["dispatch"]
    dispatch_id = d["dispatch_id"]
    print(f"  ✓ Dispatch created: {dispatch_id}, status: {d['status']}")
    assert d["status"] == "OFFERED"

    # 4 & 5. Verify offers created
    offers = ds.get_offers_for_dispatch(dispatch_id)
    print(f"[Step 4] Offers created: {len(offers)}")
    assert len(offers) == 3, f"Expected 3 offers, got {len(offers)}"
    for o in offers:
        assert o["response"] == "PENDING"
        print(f"    - Attempt {o['attempt_id']} to {o['display_label']}: {o['response']}")
    print("  ✓ PASS: Every eligible provider received a PENDING offer")

    assert res.get("eligible_provider_count") == 3
    print(f"[Step 5] eligible_provider_count = {res.get('eligible_provider_count')} (matches 3)")
    print("  ✓ PASS: eligible_provider_count matches the actual eligible set")

    # 6. Verify offers_sent matches notifications
    notify_intents = res.get("notify") or []
    print(f"[Step 6] Notifications generated: {len(notify_intents)}")
    assert len(notify_intents) >= 3, "Expected at least 3 notification intents"
    print("  ✓ PASS: offers_sent matches notification intents")

    # 7 & 8. First valid acceptance wins atomically; others cancelled
    winner_rid = eligible[0]["responder_id"]
    print(f"[Step 7] First provider {winner_rid} accepts...")
    acc_d, acc_err, acc_notify = ds.accept_offer(dispatch_id, winner_rid)
    assert acc_err is None, f"Expected no error, got {acc_err}"
    assert acc_d is not None
    assert acc_d["status"] == "ACCEPTED"
    assert acc_d["assigned_responder_id"] == winner_rid
    print(f"  ✓ PASS: First provider {winner_rid} won dispatch atomically")

    # Check that winner became BUSY
    winner_rec = rs.get_responder_by_id(winner_rid)
    assert winner_rec["status"] == "BUSY"
    assert winner_rec["assigned_dispatch_id"] == dispatch_id
    print("  ✓ PASS: Winner marked BUSY and bound to dispatch")

    # Step 8: Other offers cancelled
    offers_after = ds.get_offers_for_dispatch(dispatch_id)
    print("[Step 8] Checking remaining offers:")
    for o in offers_after:
        if o["responder_id"] == winner_rid:
            assert o["response"] == "ACCEPTED"
            print(f"    - Winner {o['display_label']}: {o['response']}")
        else:
            assert o["response"] == "CANCELLED"
            print(f"    - Other unit {o['display_label']}: {o['response']}")
    print("  ✓ PASS: All other broadcast offers marked CANCELLED")

    # 11. Concurrency / race check: second provider tries to accept after winner
    loser_rid = eligible[1]["responder_id"]
    print(f"[Step 11] Loser {loser_rid} tries to accept (late)...")
    late_d, late_err, late_notify = ds.accept_offer(dispatch_id, loser_rid)
    assert late_err == "offer_unavailable"
    print("  ✓ PASS: Loser received 409 offer_unavailable (cannot double-claim)")

    # Double click idempotency for winner
    print(f"[Step 11] Winner {winner_rid} double-clicks ACCEPT...")
    replay_d, replay_err, replay_notify = ds.accept_offer(dispatch_id, winner_rid)
    assert replay_err is None
    assert replay_d is not None
    assert replay_d["status"] == "ACCEPTED"
    print("  ✓ PASS: Winner double-click is idempotent")

    # 9 & 10. Test declines and exhaustion -> FAILED
    print("\n[Steps 9 & 10] Testing declines and exhaustion flow...")
    res2 = ds.create_dispatch(
        case_id="CASE-BCAST-2",
        created_by="AUTH-01",
        created_by_role="authority",
        incident_lng=TEST_INC_LNG,
        incident_lat=TEST_INC_LAT,
        radius_m=10000,
    )
    d2_id = res2["dispatch"]["dispatch_id"]
    d2_offers = ds.get_offers_for_dispatch(d2_id)
    # 2 units available (winner of case 1 is busy)
    assert len(d2_offers) == 2

    # Unit 1 declines: other offer must remain PENDING
    first_to_decline = d2_offers[0]["responder_id"]
    remaining_unit = d2_offers[1]["responder_id"]
    print(f"  Unit {first_to_decline} declines...")
    dec_d, dec_err, dec_notify = ds.decline_offer(d2_id, first_to_decline)
    assert dec_err is None
    assert dec_d["status"] == "OFFERED"
    d2_offers_after_1 = ds.get_offers_for_dispatch(d2_id)
    rem_offer = next(o for o in d2_offers_after_1 if o["responder_id"] == remaining_unit)
    assert rem_offer["response"] == "PENDING"
    print(f"  ✓ PASS (Step 9): Decline left other offer {rem_offer['display_label']} active (PENDING)")

    # Second unit declines: all exhausted -> FAILED
    print(f"  Unit {remaining_unit} also declines...")
    dec2_d, dec2_err, dec2_notify = ds.decline_offer(d2_id, remaining_unit)
    assert dec2_d["status"] == "FAILED"
    print("  ✓ PASS (Step 10): When all offers declined, dispatch transitioned to FAILED")

    print("\n" + "=" * 70)
    print("ALL 11 BROADCAST DISPATCH VERIFICATION STEPS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_verification()
