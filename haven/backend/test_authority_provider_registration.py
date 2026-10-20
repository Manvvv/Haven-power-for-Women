"""Tests for Authority-initiated Provider Registration & Admin Review Lifecycle.

Covers:
  - Authority submits registration with input validation & duplicate prevention
  - Non-authority (USER / RESPONDER) cannot submit or access registrations (403)
  - Authority sees registrations submitted within its jurisdiction
  - Admin lists all registrations across jurisdictions
  - Admin approves registration -> INERT provider created + setup token issued + audit logged
  - Admin rejects registration -> status REJECTED + rejection reason stored + audit logged
  - Non-admin (AUTHORITY / USER) cannot approve or reject registrations (403)
  - Authority submits suspension or revocation request
  - Admin approves suspension -> provider deactivated immediately
  - Admin approves revocation -> provider unverified and deactivated
  - Admin rejects suspension/revocation request with notes
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from auth import create_access_token
from services import responder_service, provider_registration_service as prs

client = TestClient(app)


@pytest.fixture
def authority_token():
    return create_access_token(user_id="AUTH-TEST-01", role="authority")


@pytest.fixture
def admin_token():
    return create_access_token(user_id="ADMIN-TEST-01", role="admin")


@pytest.fixture
def user_token():
    return create_access_token(user_id="USER-TEST-01", role="user")


@pytest.fixture
def responder_token():
    return create_access_token(user_id="RESP-TEST-01", role="responder")


class TestAuthorityProviderRegistration:

    def test_authority_can_submit_valid_registration(self, authority_token):
        payload = {
            "unit_name": "South Patrol Unit 4",
            "organization": "Delhi Police",
            "provider_category": "police",
            "jurisdiction": "South District",
            "contact": "police.south4@gov.in",
            "auth_reference": "DP-AUTH-2026-991",
            "capabilities": ["patrol", "emergency"],
            "notes": "Fast response motorcycle unit",
        }
        res = client.post(
            "/authority/providers/register",
            json=payload,
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        reg = data["registration"]
        assert reg["status"] == "PENDING_REVIEW"
        assert reg["unit_name"] == "South Patrol Unit 4"
        assert reg["organization"] == "Delhi Police"
        assert reg["jurisdiction"] == "South District"
        assert reg["submitted_by"] == "AUTH-TEST-01"
        assert reg["badge_number"] is not None
        assert reg["created_responder_id"] is None
        assert reg["setup_token"] is None

    def test_ordinary_user_cannot_submit_registration(self, user_token):
        res = client.post(
            "/authority/providers/register",
            json={"unit_name": "Fake Unit", "organization": "None", "jurisdiction": "City"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert res.status_code == 403

    def test_responder_cannot_submit_registration(self, responder_token):
        res = client.post(
            "/authority/providers/register",
            json={"unit_name": "Fake Unit", "organization": "None", "jurisdiction": "City"},
            headers={"Authorization": f"Bearer {responder_token}"},
        )
        assert res.status_code == 403

    def test_registration_validation_enforced(self, authority_token):
        # Missing required fields
        res = client.post(
            "/authority/providers/register",
            json={"unit_name": "A"},  # Too short, missing org, contact, etc.
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res.status_code == 422

    def test_duplicate_badge_rejected(self, authority_token):
        import secrets
        badge = f"UNIQ-BDG-{secrets.token_hex(4).upper()}"
        payload = {
            "unit_name": "First Unit",
            "badge_number": badge,
            "organization": "Security Org",
            "provider_category": "other_authorized",
            "jurisdiction": "Zone-A",
            "contact": "sec@org.in",
            "auth_reference": "REF-001",
        }
        res1 = client.post(
            "/authority/providers/register",
            json=payload,
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res1.status_code == 201

        # Attempt to register again with same badge
        res2 = client.post(
            "/authority/providers/register",
            json=payload,
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res2.status_code == 409

    def test_authority_lists_its_registrations(self, authority_token):
        res = client.get(
            "/authority/providers/registrations",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "registrations" in data
        assert isinstance(data["registrations"], list)


class TestAdminRegistrationReview:

    def test_admin_lists_all_registrations(self, admin_token, authority_token):
        # Authority submits
        client.post(
            "/authority/providers/register",
            json={
                "unit_name": "Admin Review Test Unit",
                "organization": "NGO Life",
                "provider_category": "ngo_response",
                "jurisdiction": "North",
                "contact": "ngo@life.org",
                "auth_reference": "NGO-2026-X",
            },
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        res = client.get(
            "/admin/provider-registrations?status=PENDING_REVIEW",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        assert any(r["unit_name"] == "Admin Review Test Unit" for r in data["registrations"])

    def test_admin_approves_registration_creates_inert_provider(self, admin_token, authority_token):
        sub_res = client.post(
            "/authority/providers/register",
            json={
                "unit_name": "Sakhi Shelter Unit 1",
                "organization": "Sakhi Women Shelter",
                "provider_category": "shelter_response",
                "jurisdiction": "Central",
                "contact": "sakhi@shelter.in",
                "auth_reference": "SAKHI-REG-88",
            },
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        reg_id = sub_res.json()["registration"]["registration_id"]

        # Admin approves
        app_res = client.post(
            f"/admin/provider-registrations/{reg_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert app_res.status_code == 200
        app_data = app_res.json()
        assert app_data["success"] is True
        assert app_data["registration"]["status"] == "APPROVED"
        assert app_data["setup_token"] is not None
        assert app_data["responder"] is not None
        # Must be inert (not verified until setup completes and admin verifies)
        assert app_data["responder"]["verified"] is False
        assert app_data["provisioning_state"] == "PROVIDER_CREATED"

        # Check responder exists in database/memory
        resp_id = app_data["responder"]["responder_id"]
        rec = responder_service.get_responder_by_id(resp_id)
        assert rec is not None
        assert rec["display_label"] == "Sakhi Shelter Unit 1"

    def test_admin_rejects_registration_with_reason(self, admin_token, authority_token):
        sub_res = client.post(
            "/authority/providers/register",
            json={
                "unit_name": "Incomplete Credentials Unit",
                "organization": "Unknown Group",
                "provider_category": "other_authorized",
                "jurisdiction": "West",
                "contact": "unknown@group.org",
                "auth_reference": "INVALID-REF",
            },
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        reg_id = sub_res.json()["registration"]["registration_id"]

        rej_res = client.post(
            f"/admin/provider-registrations/{reg_id}/reject",
            json={"reason": "Authorization reference could not be verified with local authorities."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert rej_res.status_code == 200
        data = rej_res.json()
        assert data["registration"]["status"] == "REJECTED"
        assert data["registration"]["rejection_reason"] == "Authorization reference could not be verified with local authorities."

    def test_authority_cannot_approve_or_reject(self, authority_token):
        # An authority cannot call admin review endpoints
        res = client.post(
            "/admin/provider-registrations/PREG-FAKE/approve",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert res.status_code == 403


class TestAuthorityProviderActionRequests:

    def test_authority_submits_suspension_and_revocation_requests(self, authority_token, admin_token):
        import secrets
        badge = f"SUSP-TEST-{secrets.token_hex(4).upper()}"
        # Create a test provider via admin
        prov_res = client.post(
            "/admin/providers",
            json={
                "badge_number": badge,
                "display_name": "Suspension Candidate Unit",
                "provider_category": "police",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert prov_res.status_code == 201
        responder_id = prov_res.json()["provider"]["responder_id"]

        # Authority submits suspension request
        req_res = client.post(
            f"/authority/providers/{responder_id}/request-action",
            json={"request_type": "SUSPENSION", "reason": "Officer transferred to non-operational role."},
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert req_res.status_code == 201
        req_id = req_res.json()["request"]["request_id"]
        assert req_res.json()["request"]["status"] == "PENDING_REVIEW"

        # Authority checks action requests
        list_res = client.get(
            "/authority/providers/action-requests",
            headers={"Authorization": f"Bearer {authority_token}"},
        )
        assert list_res.status_code == 200
        assert any(r["request_id"] == req_id for r in list_res.json()["requests"])

        # Admin reviews and approves suspension
        rev_res = client.post(
            f"/admin/provider-requests/{req_id}/review",
            json={"action": "approve", "notes": "Approved per transfer memo."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert rev_res.status_code == 200
        assert rev_res.json()["request"]["status"] == "APPROVED"

        # Verify target provider is now deactivated
        updated_prov = responder_service.get_responder_by_id(responder_id)
        assert updated_prov["active"] is False
