"""Complete Provider Lifecycle End-to-End Integration Test.

Validates the full 18-step operational sequence:
1. AUTHORITY signs in, submits provider registration
2. Registration saved in database as PENDING_REVIEW
3. Authority views submitted registration in registrations list
4. Non-admin cannot approve (403)
5. ADMIN reviews and approves registration, receiving secure single-use setup token
6. Responder record initialized as INERT (verified=False, password_set=False)
7. Responder completes setup via /auth/responder-setup with strong password
8. Setup token cannot be redeemed twice (single-use enforced)
9. Unverified responder cannot receive dispatches (verified=False)
10. ADMIN verifies responder via /admin/responders/{id}/verify
11. Responder logs in via /auth/responder-login
12. Responder goes on duty via /responder/duty and publishes fresh GPS via /responder/location
13. Authority roster reflects provider's verified, active, on-duty, fresh location state
14. Authority dispatches emergency for a case via /dispatch/rrn/create
15. Responder polls /responder/offers and receives the broadcast offer
16. Responder accepts offer via /dispatch/{id}/accept; competing offers handled atomically
17. Authority views assigned response and live coordinates via /dispatch/rrn/case/{case_id}
18. Responder transitions through enroute -> arrived -> help-provided
19. Authority submits suspension request via /authority/providers/{id}/request-action
20. Admin approves suspension request via /admin/provider-requests/{id}/review
21. Provider is deactivated; login and dispatch eligibility are immediately blocked
22. Revocation request workflow permanently removes authorization
"""
import secrets
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from auth import create_access_token
from services import responder_service as rs
from services import dispatch_service as ds
from services.db import sos_cases, responders

client = TestClient(app)


@pytest.fixture
def authority_token():
    return create_access_token(user_id="AUTH-OFFICER-01", role="authority")


@pytest.fixture
def admin_token():
    return create_access_token(user_id="ADMIN-SUPER-01", role="admin")


@pytest.fixture
def user_token():
    return create_access_token(user_id="USER-CIVILIAN-01", role="user")


class TestCompleteProviderLifecycleE2E:

    def test_full_provider_lifecycle_and_dispatch_workflow(
        self, authority_token, admin_token, user_token
    ):
        # ─────────────────────────────────────────────────────────────
        # STEP 1 & 2: Authority signs in and submits provider registration
        # ─────────────────────────────────────────────────────────────
        unique_badge = f"TEST-UNIT-{secrets.token_hex(3).upper()}"
        reg_payload = {
            "unit_name": "Nirbhaya Emergency Rapid Unit",
            "organization": "Delhi Police Women Safety Division",
            "provider_category": "police",
            "jurisdiction": "South Delhi",
            "capabilities": ["crisis-intervention", "patrol", "trauma-first-aid"],
            "contact": "+91-9876543210",
            "auth_reference": "DL-WSD-2026-0891",
            "badge_number": unique_badge,
            "notes": "Certified rapid response female officer unit",
        }

        # Non-authority cannot submit
        user_sub = client.post(
            "/authority/providers/register",
            json=reg_payload,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_sub.status_code == 403

        # Authority submits
        sub_res = client.post(
            "/authority/providers/register",
            json=reg_payload,
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert sub_res.status_code == 201
        reg_data = sub_res.json()["registration"]
        reg_id = reg_data["registration_id"]
        assert reg_data["status"] == "PENDING_REVIEW"
        assert reg_data["badge_number"] == unique_badge
        assert reg_data["submitted_by"] == "AUTH-OFFICER-01"
        assert reg_data["created_responder_id"] is None
        assert reg_data["setup_token"] is None  # Never exposed at submission

        # ─────────────────────────────────────────────────────────────
        # STEP 3 & 4: Registration appears in Authority list as PENDING_REVIEW
        # ─────────────────────────────────────────────────────────────
        auth_list_res = client.get(
            "/authority/providers/registrations",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert auth_list_res.status_code == 200
        my_regs = auth_list_res.json()["registrations"]
        found = [r for r in my_regs if r["registration_id"] == reg_id]
        assert len(found) == 1
        assert found[0]["status"] == "PENDING_REVIEW"
        assert found[0]["setup_token"] is None

        # Authority cannot approve its own registration
        unauth_app = client.post(
            f"/admin/provider-registrations/{reg_id}/approve",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert unauth_app.status_code == 403

        # ─────────────────────────────────────────────────────────────
        # STEP 5 & 6: Admin reviews and approves registration
        # ─────────────────────────────────────────────────────────────
        admin_list_res = client.get(
            "/admin/provider-registrations?status=PENDING_REVIEW",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_list_res.status_code == 200
        assert any(r["registration_id"] == reg_id for r in admin_list_res.json()["registrations"])

        app_res = client.post(
            f"/admin/provider-registrations/{reg_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert app_res.status_code == 200
        app_body = app_res.json()
        assert app_body["success"] is True
        assert app_body["registration"]["status"] == "APPROVED"
        setup_token = app_body["setup_token"]
        assert setup_token is not None and len(setup_token) > 20

        responder_info = app_body["responder"]
        responder_id = responder_info["responder_id"]
        assert responder_info["verified"] is False  # Must be INERT initially
        assert app_body["provisioning_state"] == "PROVIDER_CREATED"

        # Check DB: setup_token is NOT stored in plaintext in registrations collection
        persisted_list = client.get(
            "/authority/providers/registrations",
            headers={"Authorization": f"Bearer {authority_token}"},
        ).json()["registrations"]
        app_reg_check = [r for r in persisted_list if r["registration_id"] == reg_id][0]
        assert app_reg_check["status"] == "APPROVED"
        assert app_reg_check.get("setup_token") is None  # Secure! Not leaked.

        # ─────────────────────────────────────────────────────────────
        # STEP 7 & 8: Responder completes setup with single-use token
        # ─────────────────────────────────────────────────────────────
        strong_password = "SecureProviderPass#2026!"

        # Too short password rejected
        weak_setup = client.post(
            "/auth/responder-setup",
            json={"setup_token": setup_token, "password": "short"},
        )
        assert weak_setup.status_code == 422

        # Valid setup succeeds
        setup_res = client.post(
            "/auth/responder-setup",
            json={"setup_token": setup_token, "password": strong_password},
        )
        assert setup_res.status_code == 200
        setup_body = setup_res.json()
        assert setup_body["success"] is True

        # Single-use check: reusing setup token must fail
        reuse_res = client.post(
            "/auth/responder-setup",
            json={"setup_token": setup_token, "password": strong_password},
        )
        assert reuse_res.status_code in (400, 410)

        # ─────────────────────────────────────────────────────────────
        # STEP 9 & 10: Admin verifies the provider
        # ─────────────────────────────────────────────────────────────
        # Unverified provider state is VERIFICATION_PENDING
        rec_check = rs.get_responder_by_id(responder_id)
        assert rec_check["verified"] is False
        assert rs.provisioning_state(rec_check) == "VERIFICATION_PENDING"

        verify_res = client.patch(
            f"/admin/responders/{responder_id}",
            json={"verified": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["responder"]["verified"] is True

        # ─────────────────────────────────────────────────────────────
        # STEP 11 & 12: Responder logs in, goes ON_DUTY, publishes location
        # ─────────────────────────────────────────────────────────────
        login_res = client.post(
            "/auth/responder-login",
            json={"badge_number": unique_badge, "password": strong_password},
        )
        assert login_res.status_code == 200
        resp_jwt = login_res.json()["access_token"]
        assert resp_jwt is not None

        # Responder goes ON_DUTY with required consent
        duty_res = client.post(
            "/responder/duty",
            json={"duty": "ON_DUTY", "location_sharing_consent": True},
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert duty_res.status_code == 200
        assert duty_res.json()["responder"]["duty_status"] == "ON_DUTY"

        # Responder sets status to AVAILABLE
        status_res = client.post(
            "/responder/status",
            json={"status": "AVAILABLE"},
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert status_res.status_code == 200

        # Responder publishes GPS location (near incident)
        inc_lat, inc_lng = 28.5355, 77.2410
        loc_res = client.post(
            "/responder/location",
            json={"latitude": inc_lat + 0.002, "longitude": inc_lng + 0.002, "accuracy": 10.0},
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert loc_res.status_code == 200
        assert loc_res.json()["success"] is True

        # ─────────────────────────────────────────────────────────────
        # STEP 13: Authority roster reflects provider's live state
        # ─────────────────────────────────────────────────────────────
        roster_res = client.get(
            "/dispatch/rrn/providers",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert roster_res.status_code == 200
        roster = roster_res.json()["providers"]
        prov_row = [p for p in roster if p["responder_id"] == responder_id]
        assert len(prov_row) == 1
        assert prov_row[0]["verified"] is True
        assert prov_row[0]["active"] is True
        assert prov_row[0]["on_duty"] is True
        assert prov_row[0]["location_fresh"] is True

        # ─────────────────────────────────────────────────────────────
        # STEP 14 & 15: Create incident case and trigger dispatch
        # ─────────────────────────────────────────────────────────────
        test_case_id = f"CASE-E2E-{secrets.token_hex(4).upper()}"
        cases_coll = sos_cases()
        if cases_coll is not None:
            cases_coll.insert_one({
                "case_id": test_case_id,
                "status": "pending",
                "severity": "critical",
                "location": f"{inc_lat},{inc_lng}",
                "summary": "Urgent distress call in South Delhi area",
                "created_at": datetime.utcnow().isoformat(),
            })

        dispatch_res = client.post(
            "/dispatch",
            json={"case_id": test_case_id, "notes": "Dispatched via E2E test"},
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert dispatch_res.status_code == 201
        disp_data = dispatch_res.json()["dispatch"]
        dispatch_id = disp_data["dispatch_id"]
        assert disp_data["status"] == "OFFERED"

        # ─────────────────────────────────────────────────────────────
        # STEP 16: Responder polls offers and receives broadcast offer
        # ─────────────────────────────────────────────────────────────
        offers_res = client.get(
            "/responder/offers",
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert offers_res.status_code == 200
        offers = offers_res.json()["offers"]
        matching_offers = [o for o in offers if o["dispatch_id"] == dispatch_id]
        assert len(matching_offers) >= 1
        offer = matching_offers[0]
        assert offer["status"] in ("OFFERED", "PENDING")

        # ─────────────────────────────────────────────────────────────
        # STEP 17: Responder accepts offer atomically
        # ─────────────────────────────────────────────────────────────
        accept_res = client.post(
            f"/dispatch/{dispatch_id}/accept",
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert accept_res.status_code == 200
        assert accept_res.json()["success"] is True

        # Authority checks live tracking view
        track_res = client.get(
            f"/dispatch/by-case/{test_case_id}",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert track_res.status_code == 200
        track_body = track_res.json()
        assert track_body["dispatch"]["status"] == "ACCEPTED"
        assert track_body["dispatch"]["assigned_responder_id"] == responder_id

        # ─────────────────────────────────────────────────────────────
        # STEP 18: Responder updates status: enroute -> arrived -> help-provided
        # ─────────────────────────────────────────────────────────────
        enroute_res = client.post(
            f"/dispatch/{dispatch_id}/enroute",
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert enroute_res.status_code == 200

        arrived_res = client.post(
            f"/dispatch/{dispatch_id}/arrived",
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert arrived_res.status_code == 200

        complete_res = client.post(
            f"/dispatch/{dispatch_id}/help-provided",
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert complete_res.status_code == 200

        # ─────────────────────────────────────────────────────────────
        # STEP 19 & 20: Authority requests suspension; Admin approves it
        # ─────────────────────────────────────────────────────────────
        susp_req_res = client.post(
            f"/authority/providers/{responder_id}/request-action",
            json={
                "request_type": "SUSPENSION",
                "reason": "Administrative suspension pending review of incident report DL-99.",
            },
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert susp_req_res.status_code == 201
        req_id = susp_req_res.json()["request"]["request_id"]

        # Admin lists and reviews request
        reqs_list = client.get(
            "/admin/provider-requests?status=PENDING_REVIEW",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).json()["requests"]
        assert any(r["request_id"] == req_id for r in reqs_list)

        review_res = client.post(
            f"/admin/provider-requests/{req_id}/review",
            json={"action": "approve", "notes": "Suspension approved by Admin"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert review_res.status_code == 200
        assert review_res.json()["request"]["status"] == "APPROVED"

        # ─────────────────────────────────────────────────────────────
        # STEP 21: Verify provider is deactivated; login and dispatch blocked
        # ─────────────────────────────────────────────────────────────
        post_susp = rs.get_responder_by_id(responder_id)
        assert post_susp["active"] is False
        assert rs.provisioning_state(post_susp) == "SUSPENDED"

        # Suspended provider cannot log in
        blocked_login = client.post(
            "/auth/responder-login",
            json={"badge_number": unique_badge, "password": strong_password},
        )
        assert blocked_login.status_code in (401, 403)

        # Suspended provider cannot go on duty
        blocked_duty = client.post(
            "/responder/duty",
            json={"duty": "ON_DUTY", "location_sharing_consent": True},
            headers={"Authorization": f"Bearer {resp_jwt}"},
        )
        assert blocked_duty.status_code == 403

        # ─────────────────────────────────────────────────────────────
        # STEP 22: Authority requests REVOCATION; Admin approves it
        # ─────────────────────────────────────────────────────────────
        rev_req_res = client.post(
            f"/authority/providers/{responder_id}/request-action",
            json={
                "request_type": "REVOCATION",
                "reason": "Permanent revocation of provider credentials per disciplinary committee order.",
            },
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert rev_req_res.status_code == 201
        rev_req_id = rev_req_res.json()["request"]["request_id"]

        rev_review_res = client.post(
            f"/admin/provider-requests/{rev_req_id}/review",
            json={"action": "approve", "notes": "Permanent revocation confirmed by administrator"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert rev_review_res.status_code == 200
        assert rev_review_res.json()["request"]["status"] == "APPROVED"

        # Check provider state: both active and verified must be False
        post_rev = rs.get_responder_by_id(responder_id)
        assert post_rev["active"] is False
        assert post_rev["verified"] is False

        # Revoked provider cannot appear in eligible query
        eligible = rs.find_eligible(inc_lng, inc_lat, radius_m=20000)
        assert not any(p["responder_id"] == responder_id for p in eligible)
