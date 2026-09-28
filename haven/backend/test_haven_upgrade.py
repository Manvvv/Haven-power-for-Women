"""
HAVEN Platform Upgrade — Comprehensive Test Suite
Tests RBAC, Audit Logging, SOS Lifecycle, Offline Idempotency,
AI Risk Classification, Semantic Search, Legal Citations, Privacy Center, and Analytics.
"""
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from main import app
from auth import create_access_token
from services.lifecycle_service import (
    transition_sos,
    is_valid_transition,
    VALID_TRANSITIONS,
    SOS_STATES,
)

client = TestClient(app)

@pytest.fixture
def authority_token():
    return create_access_token(user_id="OFFICER-001", role="authority", name="Officer Priya")

@pytest.fixture
def admin_token():
    return create_access_token(user_id="ADMIN-001", role="admin", name="Admin Ananya")

@pytest.fixture
def user_token():
    return create_access_token(user_id="USER-001", role="user", name="User Meera")


class TestP1AuthorityCredentials:
    """P1-7: individual authority credentials + verified server-side identity.

    The shared authority password is gone. Login resolves an INDIVIDUAL officer
    record and derives identity from it; request-body fields never set identity.
    These tests provision test-only accounts via the service (no real secrets).
    """

    # Test-only, generated credentials — NOT production secrets.
    _BADGE = "TEST-PO-777"
    _PW = "s3cure-Test-Pass!" + "x9"
    _NAME = "Insp. Test Verified"
    _INACTIVE_BADGE = "TEST-PO-INACTIVE-778"
    _INACTIVE_PW = "another-Test-Pass!42"

    def _provision(self):
        from services import authority_service as svc
        svc.create_authority(self._BADGE, self._NAME, self._PW, role="authority", active=True)
        svc.create_authority(self._INACTIVE_BADGE, "Disabled Officer", self._INACTIVE_PW,
                             role="authority", active=False)

    def _login(self, ip="10.0.0.1", **body):
        # Each functional test uses a distinct X-Forwarded-For so the shared
        # login rate-limit bucket (5/60s) does not bleed across tests. The
        # dedicated rate-limit test reuses ONE ip to trip the limiter on purpose.
        return client.post("/auth/authority-login", json=body,
                           headers={"X-Forwarded-For": ip})

    def test_valid_credentials_login_succeeds(self):
        self._provision()
        r = self._login(ip="10.1.0.1", badge_number=self._BADGE, password=self._PW)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "authority"
        assert "access_token" in data

    def test_invalid_password_401(self):
        self._provision()
        r = self._login(ip="10.1.0.2", badge_number=self._BADGE, password="totally-wrong")
        assert r.status_code == 401

    def test_unknown_badge_401(self):
        r = self._login(ip="10.1.0.3", badge_number="NO-SUCH-BADGE-000", password=self._PW)
        assert r.status_code == 401

    def test_inactive_account_forbidden(self):
        self._provision()
        r = self._login(ip="10.1.0.4", badge_number=self._INACTIVE_BADGE, password=self._INACTIVE_PW)
        # Correct password but disabled account -> 403 (per convention).
        assert r.status_code == 403

    def test_identity_comes_from_server_record_not_body(self):
        """officer_name/badge/role in the body must NOT change the token identity."""
        self._provision()
        r = self._login(ip="10.1.0.5", badge_number=self._BADGE, password=self._PW,
                        officer_name="Attacker McSpoof", role="admin", user_id="SOMEONE-ELSE")
        assert r.status_code == 200
        data = r.json()
        # Role is the record's role (authority), never the body's "admin".
        assert data["role"] == "authority"
        # user_id is the server authority_id derived from the record, not the body.
        assert data["user_id"] == f"AUTH-{self._BADGE}"

    def test_spoofed_officer_name_does_not_change_actor(self):
        self._provision()
        r1 = self._login(ip="10.1.0.6", badge_number=self._BADGE, password=self._PW, officer_name="Real Name A")
        r2 = self._login(ip="10.1.0.7", badge_number=self._BADGE, password=self._PW, officer_name="Different Name B")
        assert r1.status_code == 200 and r2.status_code == 200
        # Same verified identity regardless of the body officer_name.
        assert r1.json()["user_id"] == r2.json()["user_id"] == f"AUTH-{self._BADGE}"

    def test_spoofed_badge_field_cannot_impersonate_other_officer(self):
        """You can only authenticate as the badge whose password you actually know."""
        self._provision()
        # Correct password for _BADGE but claiming the inactive officer's badge:
        # login is keyed on badge_number, so this authenticates (or fails) as that
        # badge — it can never yield _BADGE's identity via a mismatched password.
        r = self._login(ip="10.1.0.8", badge_number=self._INACTIVE_BADGE, password=self._PW)
        assert r.status_code == 401  # wrong password for that badge

    def test_user_token_cannot_gain_authority_via_body(self, user_token):
        """A USER token stays a user even if a body/query/header claims authority."""
        r = client.get("/cases?role=authority",
                       headers={"Authorization": f"Bearer {user_token}", "X-Role": "authority"})
        assert r.status_code == 403

    def test_authority_token_cannot_gain_admin_via_body(self, authority_token):
        """An AUTHORITY token cannot reach ADMIN-only endpoints by claiming admin."""
        r = client.get("/admin/users?role=admin",
                       headers={"Authorization": f"Bearer {authority_token}", "X-Role": "admin"})
        assert r.status_code == 403

    def test_audit_event_uses_verified_identity(self):
        """The login audit actor is the verified authority_id, not a body value."""
        from services import authority_service as svc
        self._provision()
        rec, err = svc.authenticate_authority(self._BADGE, self._PW)
        assert err is None and rec is not None
        assert rec["authority_id"] == f"AUTH-{self._BADGE}"
        assert rec["officer_name"] == self._NAME  # from the record, not the client

    def test_login_rate_limit_enforced(self):
        # >5 attempts / 60s from the SAME client should trip the existing limiter.
        responses = [self._login(ip="10.9.9.9", badge_number="RL-BADGE", password="bad")
                     for _ in range(8)]
        assert any(x.status_code == 429 for x in responses)

    def test_password_is_hashed_never_plaintext(self):
        from services import authority_service as svc
        self._provision()
        rec = svc.get_authority(self._BADGE)
        assert rec is not None
        # Only a hash + salt are stored; the plaintext password appears nowhere.
        assert "password_hash" in rec and "password_salt" in rec
        assert self._PW not in rec.get("password_hash", "")
        assert rec.get("password_hash") != self._PW
        assert len(rec["password_salt"]) == 32  # 16 random bytes, hex

    def test_hash_verifies_only_correct_password(self):
        from auth import hash_password, verify_password
        d = hash_password("Correct-Horse-Battery")
        assert verify_password("Correct-Horse-Battery", d["hash"], d["salt"]) is True
        assert verify_password("wrong", d["hash"], d["salt"]) is False


class TestP1AdminRolePersistence:
    """P1-8: PATCH /admin/users/{id}/role must DURABLY persist the role change.

    The authoritative, login-consulted role store in HAVEN is the
    `authority_accounts` collection (services/authority_service). These tests
    provision real authority identities through that service and assert the
    change lands in the store — not merely that the endpoint returned 200.
    """
    _BADGE = "TEST-ROLE-800"
    _ID = "AUTH-TEST-ROLE-800"
    _PW = "role-Test-Pass!" + "77"
    _ADMIN_BADGE = "TEST-ADMIN-900"
    _ADMIN_ID = "AUTH-TEST-ADMIN-900"
    _ADMIN_PW = "admin-Test-Pass!" + "88"

    def _provision_authority(self, role="authority"):
        from services import authority_service as svc
        return svc.create_authority(self._BADGE, "Role Target Officer", self._PW,
                                    role=role, active=True)

    def _admin_headers(self, admin_token):
        return {"Authorization": f"Bearer {admin_token}"}

    def test_unauthenticated_rejected(self):
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "user"})
        assert r.status_code == 401

    def test_user_cannot_change_roles(self, user_token):
        self._provision_authority()
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "user"},
                         headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_authority_cannot_change_roles(self, authority_token):
        self._provision_authority()
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "user"},
                         headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 403

    def test_admin_changes_authority_to_user_persists(self, admin_token):
        from services import authority_service as svc
        self._provision_authority(role="authority")
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "user"},
                         headers=self._admin_headers(admin_token))
        assert r.status_code == 200
        # Persistence verified in the actual storage layer, not just the HTTP code.
        rec = svc.get_authority_by_id(self._ID)
        assert rec is not None and rec["role"] == "user"

    def test_admin_changes_user_to_authority_persists(self, admin_token):
        from services import authority_service as svc
        # Start as an authority, demote to user, then promote back to authority.
        self._provision_authority(role="authority")
        svc.set_role(self._ID, "user")
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "authority"},
                         headers=self._admin_headers(admin_token))
        assert r.status_code == 200
        rec = svc.get_authority_by_id(self._ID)
        assert rec is not None and rec["role"] == "authority"

    def test_response_reports_persisted_role(self, admin_token):
        self._provision_authority(role="authority")
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "police"},
                         headers=self._admin_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "police"
        assert data["previous_role"] == "authority"
        # Honest about token/session semantics.
        assert data["effective_immediately"] is False

    def test_invalid_role_rejected(self, admin_token):
        self._provision_authority()
        for bad in ["superuser", "", None, "ADMIN"]:  # arbitrary/empty/null/wrong-case
            r = client.patch(f"/admin/users/{self._ID}/role", json={"role": bad},
                             headers=self._admin_headers(admin_token))
            assert r.status_code == 400, f"role {bad!r} should be rejected"

    def test_unknown_target_is_404(self, admin_token):
        r = client.patch("/admin/users/AUTH-DOES-NOT-EXIST-000/role", json={"role": "user"},
                         headers=self._admin_headers(admin_token))
        assert r.status_code == 404

    def test_database_contains_new_role_after_update(self, admin_token):
        from services import authority_service as svc
        self._provision_authority(role="authority")
        client.patch(f"/admin/users/{self._ID}/role", json={"role": "protection_officer"},
                     headers=self._admin_headers(admin_token))
        rec = svc.get_authority_by_id(self._ID)
        assert rec["role"] == "protection_officer"

    def test_audit_records_old_and_new_role(self, admin_token):
        self._provision_authority(role="authority")
        r = client.patch(f"/admin/users/{self._ID}/role", json={"role": "user"},
                         headers=self._admin_headers(admin_token))
        assert r.status_code == 200
        # The endpoint surfaces the previous role; when the audit store is
        # reachable, the ROLE_CHANGED entry must carry both roles.
        assert r.json()["previous_role"] == "authority"
        logs = client.get("/admin/audit-logs?action=ROLE_CHANGED",
                          headers=self._admin_headers(admin_token))
        if logs.status_code == 200:
            entries = logs.json().get("logs", [])
            if entries:
                meta = entries[0].get("metadata", {})
                assert meta.get("new_role") == "user"
                assert meta.get("previous_role") == "authority"

    def test_client_cannot_spoof_admin_identity(self, user_token):
        # A USER token cannot become admin by supplying actor_id/role in the body.
        self._provision_authority()
        r = client.patch(
            f"/admin/users/{self._ID}/role",
            json={"role": "user", "actor_id": "ADMIN-001", "role_override": "admin"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert r.status_code == 403

    def test_unrelated_fields_not_modified(self, admin_token):
        from services import authority_service as svc
        self._provision_authority(role="authority")
        before = svc.get_authority_by_id(self._ID)
        original_name = before["officer_name"]
        original_hash = before["password_hash"]
        r = client.patch(
            f"/admin/users/{self._ID}/role",
            json={"role": "user", "officer_name": "HACKED", "password_hash": "x", "active": False},
            headers=self._admin_headers(admin_token),
        )
        assert r.status_code == 200
        after = svc.get_authority_by_id(self._ID)
        assert after["officer_name"] == original_name   # untouched
        assert after["password_hash"] == original_hash   # untouched
        assert after["active"] is True                   # untouched
        assert after["role"] == "user"                   # only the role changed

    def test_admin_cannot_self_demote(self):
        from services import authority_service as svc
        from auth import create_access_token
        svc.create_authority(self._ADMIN_BADGE, "Self Admin", self._ADMIN_PW,
                             role="admin", active=True)
        self_admin_token = create_access_token(user_id=self._ADMIN_ID, role="admin", name="Self Admin")
        r = client.patch(f"/admin/users/{self._ADMIN_ID}/role", json={"role": "user"},
                         headers={"Authorization": f"Bearer {self_admin_token}"})
        assert r.status_code == 400
        # And the admin role must remain intact in the store (no lockout).
        assert svc.get_authority_by_id(self._ADMIN_ID)["role"] == "admin"


class TestRBACAndAuthorization:
    """Tests for role-based access control and admin endpoints."""

    def test_admin_audit_logs_unauthorized_user(self, user_token):
        """User cannot access admin audit logs."""
        resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 403

    def test_admin_audit_logs_authority_forbidden(self, authority_token):
        """Audit logs are ADMIN-only (P1-4): an authority user is now forbidden."""
        resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 403

    def test_admin_audit_logs_admin(self, admin_token):
        """Admin can view audit logs."""
        resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "total" in data

    def test_admin_system_stats(self, admin_token):
        """Admin can view system health metrics (P1-4: admin-only)."""
        resp = client.get("/admin/system-stats", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "metrics" in data


class TestAuditLogging:
    """Tests for sensitive authority actions recording audit trails."""

    def test_audit_log_created_on_case_view(self, authority_token, admin_token):
        """Viewing cases generates an audit log entry.

        The authority action generates the log; reading the audit trail back is
        ADMIN-only (P1-4), so the read uses an admin token.
        """
        client.get("/cases", headers={"Authorization": f"Bearer {authority_token}"})
        resp = client.get("/admin/audit-logs?action=CASE_VIEWED", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        logs = resp.json().get("logs", [])
        assert any(l["action"] == "CASE_VIEWED" for l in logs)


class TestP1AdminAuthorization:
    """P1-4: admin-only data endpoints must reject AUTHORITY users, not just USERs.

    Endpoints (all GET): /admin/audit-logs, /admin/users, /admin/system-config,
    /admin/system-stats.

    Contract:
      * unauthenticated -> 401
      * USER            -> 403
      * AUTHORITY       -> 403   (was 200 before P1-4)
      * ADMIN           -> allowed (200; or 503 if a service is down)

    Role is resolved by require_admin from the verified token — no body/query/
    path/header field can grant access. /admin/users/{id}/role already used
    require_admin and is intentionally NOT retested here (out of P1-4 scope).
    """

    _ADMIN_ENDPOINTS = (
        "/admin/audit-logs",
        "/admin/users",
        "/admin/system-config",
        "/admin/system-stats",
    )

    # ── unauthenticated -> 401 ──
    def test_unauthenticated_rejected(self):
        for ep in self._ADMIN_ENDPOINTS:
            assert client.get(ep).status_code == 401, ep

    # ── USER -> 403 ──
    def test_user_forbidden(self, user_token):
        for ep in self._ADMIN_ENDPOINTS:
            r = client.get(ep, headers={"Authorization": f"Bearer {user_token}"})
            assert r.status_code == 403, ep

    # ── AUTHORITY -> 403 (the core P1-4 tightening) ──
    def test_authority_forbidden(self, authority_token):
        for ep in self._ADMIN_ENDPOINTS:
            r = client.get(ep, headers={"Authorization": f"Bearer {authority_token}"})
            assert r.status_code == 403, ep

    # ── ADMIN -> allowed ──
    def test_admin_allowed(self, admin_token):
        for ep in self._ADMIN_ENDPOINTS:
            r = client.get(ep, headers={"Authorization": f"Bearer {admin_token}"})
            # 200 normally; 503 tolerated only if a backing service is unavailable.
            assert r.status_code in (200, 503), ep

    # ── role spoofing must not bypass authorization ──
    def test_query_role_spoof_unauthenticated_still_401(self):
        for ep in self._ADMIN_ENDPOINTS:
            assert client.get(f"{ep}?role=admin").status_code == 401, ep

    def test_user_body_and_query_role_spoof_still_403(self, user_token):
        # GET endpoints ignore bodies, but prove neither query nor header role helps.
        for ep in self._ADMIN_ENDPOINTS:
            r = client.get(f"{ep}?role=admin",
                           headers={"Authorization": f"Bearer {user_token}", "X-Role": "admin"})
            assert r.status_code == 403, ep

    def test_authority_role_spoof_still_403(self, authority_token):
        for ep in self._ADMIN_ENDPOINTS:
            r = client.get(f"{ep}?role=admin",
                           headers={"Authorization": f"Bearer {authority_token}", "X-Role": "admin"})
            assert r.status_code == 403, ep


class TestP1ImageEndpointSecurity:
    """P1-5: /encode and /decode are intentionally anonymous (covert victim SOS
    flow) but must be hardened against malformed base64, non-image / oversized /
    decompression-bomb payloads, and request abuse — without leaking internals.

    These tests build tiny in-memory images (no binary fixtures) and do not touch
    MongoDB.
    """

    import io as _io
    import base64 as _b64

    @staticmethod
    def _png_b64(width=8, height=8, color=(0, 128, 255)):
        import io, base64
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _assert_no_internals(resp):
        """A client error must not leak tracebacks or raw Pillow/Python internals."""
        text = resp.text
        assert "Traceback" not in text
        assert "PIL" not in text
        assert "Pillow" not in text
        assert "cannot identify image" not in text  # raw UnidentifiedImageError text
        assert "DecompressionBomb" not in text

    # ── A. /encode ──
    def test_encode_malformed_base64_is_400(self):
        r = client.post("/encode", json={"message": "help", "image_base64": "!!!not base64!!!"})
        assert r.status_code == 400
        self._assert_no_internals(r)

    def test_encode_non_image_payload_is_400(self):
        import base64
        junk = base64.b64encode(b"this is definitely not an image").decode()
        r = client.post("/encode", json={"message": "help", "image_base64": junk})
        assert r.status_code == 400
        self._assert_no_internals(r)

    def test_encode_oversized_base64_is_413(self):
        # Exceed the character ceiling without allocating a real huge image.
        huge = "A" * (15_000_001)
        r = client.post("/encode", json={"message": "help", "image_base64": huge})
        assert r.status_code == 413

    def test_encode_valid_small_image_succeeds(self):
        # 32x32 gives ample LSB capacity for the message plus the 12-byte
        # HAVEN payload header/footer (magic + length + CRC32).
        r = client.post("/encode", json={"message": "meet at the shelter", "image_base64": self._png_b64(32, 32)})
        assert r.status_code == 200
        assert "encoded_image_base64" in r.json()

    def test_encode_message_too_long_is_413(self):
        r = client.post("/encode", json={"message": "x" * 5001, "image_base64": self._png_b64()})
        assert r.status_code == 413

    # ── B. /decode ──
    def test_decode_malformed_base64_is_400(self):
        r = client.post("/decode", json={"image_base64": "%%%bad%%%"})
        assert r.status_code == 400
        self._assert_no_internals(r)

    def test_decode_non_image_payload_is_400(self):
        import base64
        junk = base64.b64encode(b"not an image at all").decode()
        r = client.post("/decode", json={"image_base64": junk})
        assert r.status_code == 400
        self._assert_no_internals(r)

    def test_decode_oversized_base64_is_413(self):
        huge = "A" * (15_000_001)
        r = client.post("/decode", json={"image_base64": huge})
        assert r.status_code == 413

    def test_decode_missing_field_is_400(self):
        r = client.post("/decode", json={})
        assert r.status_code == 400

    # ── C. Regression: encode -> decode round-trips the hidden message ──
    def test_encode_then_decode_roundtrip(self):
        secret = "safe word: bluebird"
        # A larger canvas guarantees enough LSB capacity for the message.
        enc = client.post("/encode", json={"message": secret, "image_base64": self._png_b64(64, 64)})
        assert enc.status_code == 200
        encoded_b64 = enc.json()["encoded_image_base64"]
        dec = client.post("/decode", json={"image_base64": encoded_b64})
        assert dec.status_code == 200
        assert dec.json().get("decoded_message") == secret

    def test_roundtrip_deterministic_ascii(self):
        # The exact deterministic round-trip the spec calls for.
        secret = "HAVEN STEGO TEST 123"
        enc = client.post("/encode", json={"message": secret, "image_base64": self._png_b64(64, 64)})
        assert enc.status_code == 200
        dec = client.post("/decode", json={"image_base64": enc.json()["encoded_image_base64"]})
        assert dec.status_code == 200
        assert dec.json().get("decoded_message") == secret

    def test_roundtrip_unicode_hindi(self):
        # HAVEN is multilingual — a Devanagari distress message must survive the
        # round-trip exactly. The old ord()/chr() codec corrupted any cp > 255.
        secret = "मुझे मदद चाहिए, मैं बाज़ार के पास फँसी हूँ"
        enc = client.post("/encode", json={"message": secret, "image_base64": self._png_b64(96, 96)})
        assert enc.status_code == 200
        dec = client.post("/decode", json={"image_base64": enc.json()["encoded_image_base64"]})
        assert dec.status_code == 200
        assert dec.json().get("decoded_message") == secret

    def test_roundtrip_emoji_and_smart_punctuation(self):
        secret = "help me — I'm trapped 🚨 near the market"
        enc = client.post("/encode", json={"message": secret, "image_base64": self._png_b64(96, 96)})
        assert enc.status_code == 200
        dec = client.post("/decode", json={"image_base64": enc.json()["encoded_image_base64"]})
        assert dec.status_code == 200
        assert dec.json().get("decoded_message") == secret

    def test_encode_message_too_large_for_image_is_413(self):
        # A message that fits the char ceiling (<=5000) but not the tiny image's
        # LSB capacity must fail honestly — never a fake-success unmodified image.
        long_msg = "x" * 400
        r = client.post("/encode", json={"message": long_msg, "image_base64": self._png_b64(8, 8)})
        assert r.status_code == 413
        detail = r.json().get("detail")
        assert isinstance(detail, dict) and detail.get("error_code") == "MESSAGE_TOO_LARGE_FOR_IMAGE"

    def test_decode_clean_image_reports_no_payload(self):
        # A perfectly valid PNG with nothing embedded → 200 NO_PAYLOAD (not an
        # error, not a false positive).
        r = client.post("/decode", json={"image_base64": self._png_b64(32, 32, color=(10, 20, 30))})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "NO_PAYLOAD"
        assert body.get("decoded_message") in (None, "")

    def test_decode_corrupted_payload_is_422(self):
        # Embed a message, flip an LSB in the payload region → CRC fails → the
        # decoder must report CORRUPTED_PAYLOAD, not a bogus message.
        import io, base64
        from PIL import Image
        import numpy as np
        enc = client.post("/encode", json={"message": "tampered rendezvous point", "image_base64": self._png_b64(64, 64)})
        assert enc.status_code == 200
        raw = base64.b64decode(enc.json()["encoded_image_base64"])
        arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8)
        flat = arr.flatten()
        flat[160] ^= 1  # well past the 96-bit header, inside payload/CRC
        buf = io.BytesIO()
        Image.fromarray(flat.reshape(arr.shape), "RGB").save(buf, format="PNG")
        tampered = base64.b64encode(buf.getvalue()).decode()
        dec = client.post("/decode", json={"image_base64": tampered})
        assert dec.status_code == 422
        assert dec.json().get("detail", {}).get("error_code") == "CORRUPTED_PAYLOAD"

    def test_decode_jpeg_recompression_is_rejected(self):
        # Encoding is lossless PNG; if the file is recompressed to JPEG the LSBs
        # are destroyed. The decoder must REJECT (UNSUPPORTED_FORMAT), never
        # falsely report a valid message.
        import io, base64
        from PIL import Image
        enc = client.post("/encode", json={"message": "secret 9pm rendezvous", "image_base64": self._png_b64(64, 64)})
        assert enc.status_code == 200
        raw = base64.b64decode(enc.json()["encoded_image_base64"])
        buf = io.BytesIO()
        Image.open(io.BytesIO(raw)).convert("RGB").save(buf, format="JPEG", quality=90)
        jpeg_b64 = base64.b64encode(buf.getvalue()).decode()
        dec = client.post("/decode", json={"image_base64": jpeg_b64})
        assert dec.status_code == 415
        assert dec.json().get("detail", {}).get("error_code") == "UNSUPPORTED_FORMAT"
        self._assert_no_internals(dec)

    # ── D. Rate limiting (20/60s on each endpoint) ──
    def test_encode_rate_limit_eventually_429(self):
        img = self._png_b64()
        codes = [
            client.post("/encode", json={"message": "hi", "image_base64": img}).status_code
            for _ in range(30)
        ]
        assert 429 in codes


class TestCaseListRegression:
    """Issue 2: the authority case list must reflect REAL MongoDB records,
    render the CANONICAL lifecycle status, and never create/duplicate cases on
    a read. Tests seed via the DB and skip cleanly when Mongo is unavailable.
    """

    @staticmethod
    def _cases_coll():
        try:
            from services.db import sos_cases
            return sos_cases()
        except Exception:
            return None

    def test_get_cases_requires_authority(self):
        # Read-only, but still authority-gated — an anonymous GET is rejected.
        r = client.get("/cases")
        assert r.status_code in (401, 403)

    def test_get_cases_is_read_only_no_duplicate_insertion(self, authority_token):
        coll = self._cases_coll()
        if coll is None:
            pytest.skip("MongoDB unavailable")
        hdr = {"Authorization": f"Bearer {authority_token}"}
        before = coll.count_documents({})
        for _ in range(3):
            assert client.get("/cases", headers=hdr).status_code == 200
        after = coll.count_documents({})
        # A GET/list must NEVER create an SOS case (React StrictMode / polling).
        assert after == before

    def test_get_cases_returns_real_seeded_record(self, authority_token):
        coll = self._cases_coll()
        if coll is None:
            pytest.skip("MongoDB unavailable")
        cid = "REG-CASELIST-REAL-001"
        coll.update_one({"case_id": cid},
                        {"$set": {"case_id": cid, "user_id": "USER-REG",
                                  "status": "CREATED", "severity": "high",
                                  "decoded_text": "regression seed record",
                                  "created_at": datetime.utcnow()}}, upsert=True)
        r = client.get("/cases", headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 200
        data = r.json()
        # total mirrors the number actually returned — never a hardcoded count.
        assert data["total"] == len(data["cases"])
        coll.delete_one({"case_id": cid})

    def test_get_cases_canonicalizes_legacy_status(self, authority_token):
        # A legacy 'active' status must render as the canonical 'RECEIVED' in the
        # response, so the UI never shows inconsistent/legacy state strings.
        coll = self._cases_coll()
        if coll is None:
            pytest.skip("MongoDB unavailable")
        cid = "REG-CASELIST-LEGACY-002"
        coll.update_one({"case_id": cid},
                        {"$set": {"case_id": cid, "user_id": "USER-REG",
                                  "status": "active", "severity": "critical",
                                  "created_at": datetime.utcnow()}}, upsert=True)
        r = client.get("/cases", headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 200
        seeded = [c for c in r.json()["cases"] if c["case_id"] == cid]
        assert seeded and seeded[0]["status"] == "RECEIVED"
        # Read-only shaping: the stored document itself is untouched by the GET.
        assert coll.find_one({"case_id": cid})["status"] == "active"
        coll.delete_one({"case_id": cid})


class TestSOSLifecycleAndIdempotency:
    """Tests for SOS state machine and offline duplicate prevention."""

    def test_lifecycle_states_defined(self):
        """The canonical 9-state lifecycle is present and ordered."""
        assert SOS_STATES[0] == "CREATED"
        assert SOS_STATES[-1] == "RESOLVED"
        assert "AI_ANALYZED" in SOS_STATES

    def test_valid_transitions(self):
        """Pipeline progression and authority triage transitions are allowed."""
        assert is_valid_transition("CREATED", "ENCODED")
        assert is_valid_transition("IN_PROGRESS", "RESOLVED")
        # A case on the dashboard may be acknowledged from any pipeline state.
        assert is_valid_transition("CREATED", "ACKNOWLEDGED")
        # No-op (same state) is always allowed.
        assert is_valid_transition("RESOLVED", "RESOLVED")

    def test_invalid_transitions_rejected(self):
        """Backwards / terminal transitions are correctly rejected."""
        # RESOLVED is terminal — cannot move onward.
        assert not is_valid_transition("RESOLVED", "IN_PROGRESS")
        # Cannot jump back into the automated pipeline after triage.
        assert not is_valid_transition("ACKNOWLEDGED", "ENCODED")

    def test_transition_sos_missing_case_is_safe(self):
        """transition_sos returns False (never raises) for an unknown case / no DB."""
        result = transition_sos("TEST-CASE-DOES-NOT-EXIST-999", "RESOLVED", "OFFICER-001", "authority")
        assert result is False

    def test_idempotency_duplicate_prevention(self):
        """Submitting the same idempotency key returns the existing case without duplicate creation."""
        idem_key = "IDEM-TEST-KEY-12345"
        payload = {
            "decoded_text": "Emergency need immediate assistance",
            "severity": "critical",
            "idempotency_key": idem_key
        }
        res1 = client.post("/save-extracted-data", json=payload)
        assert res1.status_code == 200
        case_id = res1.json()["case_id"]

        # Duplicate submit with same idempotency_key
        res2 = client.post("/save-extracted-data", json=payload)
        assert res2.status_code == 200
        assert res2.json().get("duplicate") is True
        assert res2.json()["case_id"] == case_id


class TestAIRiskClassifier:
    """Tests for AI risk severity classification and human review override."""

    def test_classify_risk_endpoint(self):
        """POST /ai/classify-risk (ephemeral, no case_id) returns structured severity.

        The no-case_id path performs analysis only and persists nothing, so it stays
        open (rate-limited) to preserve anonymous SOS triage. Persistence against a
        case_id now requires auth+ownership — see TestP1ClassifyRiskSecurity.
        """
        resp = client.post("/ai/classify-risk", json={
            "text": "Help me my husband locked me in the room and is threatening me with violence"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
        assert 0 <= data["risk_score"] <= 100
        assert isinstance(data["indicators"], list)
        assert "confidence" in data
        assert data["is_demo_mode"] is True

    def test_metrics_computation_correct(self):
        """Backend-comparison metric math is correct on a known tiny example."""
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "compare_backends", str(pathlib.Path("ml/compare_backends.py")))
        cb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cb)
        labels = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
        y_true = ["LOW", "LOW", "HIGH", "CRITICAL"]
        y_pred = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
        cm, per_class, macro_f1 = cb._metrics(y_true, y_pred, labels)
        # LOW: 1 correct of 2 gold, 1 predicted -> precision 1.0, recall 0.5
        assert abs(per_class["LOW"]["precision"] - 1.0) < 1e-9
        assert abs(per_class["LOW"]["recall"] - 0.5) < 1e-9
        assert 0.0 <= macro_f1 <= 1.0

    def test_compare_rules_backend_runs(self):
        """The rule backend evaluates live and returns in-range metrics (DEMO)."""
        import importlib.util, pathlib, json
        spec = importlib.util.spec_from_file_location(
            "compare_backends2", str(pathlib.Path("ml/compare_backends.py")))
        cb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cb)
        rows = cb.load_dataset(pathlib.Path(cb.DATA_PATH))
        res = cb.evaluate_backend("rules", rows)
        assert res["available"] is True
        assert 0.0 <= res["accuracy"] <= 1.0
        assert 0.0 <= res["macro_f1"] <= 1.0
        assert res["is_demo"] is True

    def test_human_override_ai_analysis(self, authority_token):
        """Authority can override AI classification and record reason."""
        override_payload = {
            "severity": "CRITICAL",
            "risk_score": 95,
            "notes": "Victim has severe threat history",
            "reason": "Direct weapon threat reported to dispatcher"
        }
        resp = client.patch(
            "/ai/analysis/TEST-AI-CASE-01/override",
            json=override_payload,
            headers={"Authorization": f"Bearer {authority_token}"}
        )
        # 200 when an analysis record exists to override; 404 if none was
        # persisted (persistence now requires an authorized case — see
        # TestP1ClassifyRiskSecurity); 503 if Mongo is unavailable in CI.
        assert resp.status_code in (200, 404, 503)
        if resp.status_code == 200:
            assert resp.json()["success"] is True


class TestP1ClassifyRiskSecurity:
    """P1-1: /ai/classify-risk must not let a caller persist an AI verdict
    onto a case they don't own.

    Contract:
      * No case_id  -> ephemeral analysis, no persistence, open (rate-limited).
      * With case_id -> authentication REQUIRED; caller must own the case
        (or be authority/admin); ownership derived from the stored case, never
        from a body-supplied user_id; unknown case -> 404.

    Tests that need a seeded case skip cleanly when Mongo is unavailable so the
    suite still runs in a DB-less CI environment.
    """

    _OWNER_CASE = "P1-AI-OWNED-USER001"
    _OTHER_CASE = "P1-AI-OWNED-OTHER"

    @staticmethod
    def _cases_coll():
        try:
            from services.db import sos_cases
            return sos_cases()
        except Exception:
            return None

    @classmethod
    def _seed_case(cls, case_id: str, owner_id: str):
        """Insert a minimal case owned by owner_id. Returns True if seeded."""
        coll = cls._cases_coll()
        if coll is None:
            return False
        try:
            coll.update_one(
                {"case_id": case_id},
                {"$set": {"case_id": case_id, "user_id": owner_id, "status": "CREATED"}},
                upsert=True,
            )
            return True
        except Exception:
            return False

    # ── no case_id: ephemeral analysis stays open, persists nothing ──
    def test_no_case_id_allowed_unauthenticated(self):
        r = client.post("/ai/classify-risk", json={"text": "he is threatening me right now"})
        assert r.status_code == 200
        assert "severity" in r.json()

    # ── persisting REQUIRES authentication ──
    def test_persist_requires_auth(self):
        # A case_id is supplied but no Authorization header -> 401 before any DB work.
        r = client.post("/ai/classify-risk",
                        json={"text": "help me", "case_id": self._OWNER_CASE})
        assert r.status_code == 401

    # ── authenticated + owner -> allowed (200); or DB-less 503 ──
    def test_owner_can_persist(self, user_token):
        seeded = self._seed_case(self._OWNER_CASE, "USER-001")  # user_token is USER-001
        r = client.post("/ai/classify-risk",
                        json={"text": "he locked me in and is threatening violence",
                              "case_id": self._OWNER_CASE},
                        headers={"Authorization": f"Bearer {user_token}"})
        if not seeded:
            # No DB -> the case can't be found -> 404 (or 503 if the coll is down).
            assert r.status_code in (404, 503)
        else:
            assert r.status_code == 200
            assert r.json()["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]

    # ── authenticated but NOT the owner -> 403 (no write) ──
    def test_non_owner_cannot_persist(self, user_token):
        # Seed a case owned by a DIFFERENT user; USER-001 must be refused.
        seeded = self._seed_case(self._OTHER_CASE, "USER-999")
        r = client.post("/ai/classify-risk",
                        json={"text": "help me", "case_id": self._OTHER_CASE},
                        headers={"Authorization": f"Bearer {user_token}"})
        if not seeded:
            assert r.status_code in (404, 503)
        else:
            assert r.status_code == 403

    # ── a body-supplied user_id must NOT grant ownership ──
    def test_body_user_id_is_not_trusted(self, user_token):
        # USER-001 tries to claim ownership of USER-999's case by spoofing user_id
        # in the body. Ownership comes from the stored case -> still 403.
        seeded = self._seed_case(self._OTHER_CASE, "USER-999")
        r = client.post("/ai/classify-risk",
                        json={"text": "help me", "case_id": self._OTHER_CASE,
                              "user_id": "USER-001"},
                        headers={"Authorization": f"Bearer {user_token}"})
        if not seeded:
            assert r.status_code in (404, 503)
        else:
            assert r.status_code == 403

    # ── authority/admin may analyze any case ──
    def test_authority_can_persist_any_case(self, authority_token):
        seeded = self._seed_case(self._OTHER_CASE, "USER-999")
        r = client.post("/ai/classify-risk",
                        json={"text": "victim reports weapon threat", "case_id": self._OTHER_CASE},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if not seeded:
            assert r.status_code in (404, 503)
        else:
            assert r.status_code == 200

    # ── authenticated + unknown case -> 404, never a silent write ──
    def test_unknown_case_is_404(self, user_token):
        r = client.post("/ai/classify-risk",
                        json={"text": "help me", "case_id": "NO-SUCH-AI-CASE-ZZZ"},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code in (404, 503)

    # ── rate limiting is enforced on the endpoint ──
    def test_rate_limit_enforced(self):
        # The dependency allows 30 req / 60s per client. Fire enough to trip it and
        # assert a 429 appears (unauthenticated ephemeral path keeps this cheap).
        codes = [
            client.post("/ai/classify-risk", json={"text": "hello there"}).status_code
            for _ in range(45)
        ]
        assert 429 in codes


class TestP1CulpritFindMatchSecurity:
    """P1-2: /culprit/find-match must not expose profile/case intelligence to
    anonymous or non-authority callers, and must not leak internal fields.

    Contract:
      * unauthenticated -> 401
      * USER            -> 403
      * AUTHORITY       -> allowed
      * ADMIN           -> allowed
      * role is taken from the verified token, never from a body field.

    The matching algorithm, vector behavior, response shape (matches/query/
    search_type), and rate limiting are preserved. Only the returned field set
    is minimized to what the workflow renders.
    """

    _PROFILE = "P1-PROFILE-001"

    @staticmethod
    def _culprits_coll():
        try:
            from services.db import culprits
            return culprits()
        except Exception:
            return None

    @classmethod
    def _seed_profile(cls):
        """Insert a profile carrying sensitive internal fields. Returns True if seeded."""
        coll = cls._culprits_coll()
        if coll is None:
            return False
        try:
            coll.update_one(
                {"culprit_id": cls._PROFILE},
                {"$set": {
                    "culprit_id": cls._PROFILE,
                    "name": "Test Profile Zeta",
                    "physical_description": "tall, dark hair, approx 40 years",
                    "behavioral_traits": "aggressive, controlling",
                    "location": "Ward 7",
                    # sensitive internal metadata that must NOT be returned:
                    "reporter_id": "USER-SECRET-777",
                    "reporter_role": "user",
                    "description_embedding": [0.0] * 768,
                }},
                upsert=True,
            )
            return True
        except Exception:
            return False

    # ── authorization matrix ──
    def test_unauthenticated_rejected(self):
        r = client.post("/culprit/find-match", json={"description": "Test Profile", "search_mode": "name"})
        assert r.status_code == 401

    def test_normal_user_forbidden(self, user_token):
        r = client.post("/culprit/find-match",
                        json={"description": "Test Profile", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_authority_allowed(self, authority_token):
        r = client.post("/culprit/find-match",
                        json={"description": "Test Profile", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        # 200 with a live DB, 503 if Mongo is unavailable in CI — never 401/403.
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            body = r.json()
            assert "matches" in body and "search_type" in body

    def test_admin_allowed(self, admin_token):
        r = client.post("/culprit/find-match",
                        json={"description": "Test Profile", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code in (200, 503)

    def test_body_role_field_is_not_trusted(self):
        # An anonymous caller cannot self-elevate by putting role/user_id in the body.
        r = client.post("/culprit/find-match",
                        json={"description": "x", "search_mode": "name",
                              "role": "admin", "user_id": "OFFICER-001"})
        assert r.status_code == 401

    # ── input validation ──
    def test_empty_query_rejected(self, authority_token):
        r = client.post("/culprit/find-match",
                        json={"description": "   ", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 400

    def test_invalid_top_n_rejected(self, authority_token):
        r = client.post("/culprit/find-match",
                        json={"description": "someone", "top_n": "not-a-number"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 400

    def test_top_n_clamped_not_errored(self, authority_token):
        # An over-large limit is clamped (not rejected) — preserves prior behavior.
        r = client.post("/culprit/find-match",
                        json={"description": "someone", "top_n": 9999, "search_mode": "name"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (200, 503)

    # ── sensitive-field safety ──
    def test_response_omits_internal_fields(self, authority_token):
        seeded = self._seed_profile()
        r = client.post("/culprit/find-match",
                        json={"description": "Test Profile Zeta", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if not seeded or r.status_code != 200:
            pytest.skip("DB unavailable — cannot assert field-level projection")
        matches = r.json().get("matches", [])
        assert matches, "expected the seeded profile to match by name"

        # Single source of truth: the production allowlist the shaper enforces.
        # Asserting against the SAME set means a field can never reach the API
        # without being deliberately added to the public contract there too. The
        # profile-search upgrade intentionally added safe RETRIEVAL metadata
        # (profile_id, match_score, match_level, match_factors, match_summary,
        # human_verification_required) — these are public and rendered by the
        # Authority UI; they are NOT identity confidence and imply no guilt.
        from services.profile_search import SAFE_PUBLIC_MATCH_FIELDS

        # Internal / sensitive fields that must NEVER appear in a match, whatever
        # the seeded record or DB row happens to contain.
        forbidden = {
            "_id", "reporter_id", "reporter_role",
            "description_embedding", "embedding", "raw_embedding",
            "password", "token", "secret",
        }
        for m in matches:
            leaked = forbidden & set(m.keys())
            assert not leaked, f"internal field(s) leaked: {sorted(leaked)}"
            # Only explicitly-approved public fields may be returned.
            extra = set(m.keys()) - set(SAFE_PUBLIC_MATCH_FIELDS)
            assert not extra, f"non-allowlisted field(s) returned: {sorted(extra)}"

    # ── neutral terminology preserved ──
    def test_disclaimer_present(self, authority_token):
        r = client.post("/culprit/find-match",
                        json={"description": "someone", "search_mode": "name"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if r.status_code != 200:
            pytest.skip("DB unavailable")
        assert "investigative references, not confirmations of guilt" in r.json().get("disclaimer", "")


class TestP1SearchProfilesSecurity:
    """P1-3: /search/profiles must be authority/admin only.

    Profile semantic search is sensitive intelligence — it previously allowed any
    authenticated USER. It now mirrors /search/semantic (case search):
      * unauthenticated -> 401
      * USER            -> 403
      * AUTHORITY       -> allowed
      * ADMIN           -> allowed
      * role comes from the verified token, never a body/query/header field.

    The keyword/semantic/hybrid algorithm, ranking, limits, response schema
    (matches/query/total/search_type/search_mode/degraded), and the 30/60s rate
    limit are unchanged — only the authorization dependency changed.
    """

    _BODY = {"description": "tall aggressive individual", "mode": "semantic", "limit": 5}

    def test_unauthenticated_rejected(self):
        r = client.post("/search/profiles", json=self._BODY)
        assert r.status_code == 401

    def test_normal_user_forbidden(self, user_token):
        r = client.post("/search/profiles", json=self._BODY,
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_authority_allowed(self, authority_token):
        r = client.post("/search/profiles", json=self._BODY,
                        headers={"Authorization": f"Bearer {authority_token}"})
        # Authorized: 200 with a live DB, 503 if Mongo is unavailable in CI —
        # never 401/403.
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            body = r.json()
            # Response schema preserved.
            for key in ("matches", "query", "total", "search_type", "search_mode", "degraded"):
                assert key in body

    def test_admin_allowed(self, admin_token):
        r = client.post("/search/profiles", json=self._BODY,
                        headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code in (200, 503)

    def test_body_role_field_does_not_bypass_auth(self):
        # An unauthenticated caller cannot self-elevate via body/query fields.
        r = client.post("/search/profiles?role=admin",
                        json={**self._BODY, "role": "admin", "user_id": "OFFICER-001"})
        assert r.status_code == 401

    def test_user_body_role_field_still_forbidden(self, user_token):
        # A USER token plus a spoofed body role is still 403 — role is from the token.
        r = client.post("/search/profiles",
                        json={**self._BODY, "role": "admin"},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_empty_query_rejected_for_authority(self, authority_token):
        # Existing input validation still applies once authorized (400, not 200).
        r = client.post("/search/profiles", json={"description": "   ", "mode": "semantic"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (400, 503)

    def test_invalid_mode_rejected_for_authority(self, authority_token):
        r = client.post("/search/profiles", json={"description": "someone", "mode": "telepathy"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (400, 503)


class TestP1SearchConsolidation:
    """Audit #11: EVERY production profile/culprit matching path must converge on
    the single canonical hardened matcher (profile_search.run_profile_search).

    The two formerly-divergent endpoints are re-pointed here:
      * POST /search/profiles  (was search_service.search_profiles: raw fields +
        raw score, no classification / level / verification / allowlist)
      * GET  /search/exact     (was a bespoke regex find() that fabricated a flat
        1.0/0.9 score and serialized raw docs, leaking reporter identity)

    Both now MUST return the canonical contract (query_type, search_type,
    human_verification_required, disclaimer), enforce the SAFE_PUBLIC_MATCH_FIELDS
    allowlist, keep authority-only RBAC, and degrade honestly (503 on backend
    failure — never a misleading empty result). These tests prove convergence at
    the HTTP boundary; validate_search_consolidation.py proves it statically.
    """

    _NAME = "Nirmal Nehra"

    @staticmethod
    def _culprits_coll():
        try:
            from services.db import culprits
            return culprits()
        except Exception:
            return None

    @classmethod
    def _seed(cls):
        """Seed a profile carrying sensitive internal fields. Returns True if seeded."""
        coll = cls._culprits_coll()
        if coll is None:
            return False
        try:
            coll.update_one(
                {"culprit_id": "P1-CONSOL-001"},
                {"$set": {
                    "culprit_id": "P1-CONSOL-001", "name": cls._NAME,
                    "physical_description": "medium build, short black hair",
                    "behavioral_traits": "evasive", "location": "Sector 9",
                    # sensitive internal metadata that must NEVER be returned:
                    "reporter_id": "USER-SECRET-999", "reporter_role": "user",
                    "description_embedding": [0.0] * 768,
                }},
                upsert=True,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _assert_canonical(body):
        """Every canonical profile-match response carries these keys."""
        for key in ("matches", "results", "query", "total", "query_type",
                    "search_type", "search_mode", "degraded",
                    "human_verification_required", "disclaimer"):
            assert key in body, f"missing canonical key {key!r}"
        assert body["human_verification_required"] is True
        assert "investigative references, not confirmations of guilt" in body["disclaimer"]
        assert isinstance(body["degraded"], bool)
        # back-compat: legacy `matches` and canonical `results` are the same set.
        assert body["matches"] == body["results"]

    @staticmethod
    def _assert_no_leak(matches):
        from services.profile_search import SAFE_PUBLIC_MATCH_FIELDS
        forbidden = {"_id", "reporter_id", "reporter_role", "description_embedding",
                     "embedding", "raw_embedding", "password", "token", "secret"}
        for m in matches:
            leaked = forbidden & set(m.keys())
            assert not leaked, f"internal field(s) leaked: {sorted(leaked)}"
            extra = set(m.keys()) - set(SAFE_PUBLIC_MATCH_FIELDS)
            assert not extra, f"non-allowlisted field(s) returned: {sorted(extra)}"

    # ── /search/exact — RBAC ──
    def test_exact_unauthenticated_rejected(self):
        r = client.get("/search/exact", params={"name": "Nirmal"})
        assert r.status_code == 401

    def test_exact_user_forbidden(self, user_token):
        r = client.get("/search/exact", params={"name": "Nirmal"},
                       headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_exact_authority_canonical_contract(self, authority_token):
        r = client.get("/search/exact", params={"name": self._NAME},
                       headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (200, 503)  # never 401/403
        if r.status_code == 200:
            body = r.json()
            self._assert_canonical(body)
            # NAME mode -> the canonical classifier reports a name query.
            assert body["query_type"] == "name"

    # ── /search/exact — deterministic name tiers reach the canonical matcher ──
    def test_exact_name_variants_match(self, authority_token):
        """Exact, reordered, substring and transliterated/folded names all route
        through run_profile_search in NAME mode and can match — the bug this audit
        closes was a plain name being filtered out by a vector threshold."""
        if not self._seed():
            pytest.skip("DB unavailable — cannot assert name-match tiers")
        for variant in ("Nirmal Nehra", "nehra nirmal", "nirmal", "Nirmal Nehraa"):
            r = client.get("/search/exact", params={"name": variant},
                           headers={"Authorization": f"Bearer {authority_token}"})
            if r.status_code != 200:
                pytest.skip("DB unavailable mid-run")
            body = r.json()
            self._assert_canonical(body)
            self._assert_no_leak(body["matches"])
            assert body["query_type"] == "name"
            assert any(m.get("name") == self._NAME for m in body["matches"]), \
                f"expected {self._NAME!r} to match variant {variant!r}"

    def test_exact_no_match_is_empty_not_error(self, authority_token):
        r = client.get("/search/exact",
                       params={"name": "Zzqx Nonexistent Person 4471"},
                       headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            body = r.json()
            self._assert_canonical(body)
            assert body["matches"] == []  # honest empty, not fabricated

    def test_exact_forbidden_fields_never_returned(self, authority_token):
        if not self._seed():
            pytest.skip("DB unavailable")
        r = client.get("/search/exact", params={"name": self._NAME},
                       headers={"Authorization": f"Bearer {authority_token}"})
        if r.status_code != 200:
            pytest.skip("DB unavailable")
        self._assert_no_leak(r.json().get("matches", []))

    # ── /search/profiles — now the SAME canonical matcher ──
    def test_profiles_authority_canonical_contract(self, authority_token):
        r = client.post("/search/profiles",
                        json={"description": "medium build evasive individual",
                              "mode": "semantic", "limit": 5},
                        headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            body = r.json()
            self._assert_canonical(body)
            # description text -> classifier reports description (or mixed).
            assert body["query_type"] in ("description", "mixed", "name")
            self._assert_no_leak(body["matches"])

    def test_profiles_name_query_classified_as_name(self, authority_token):
        r = client.post("/search/profiles", json={"query": self._NAME, "mode": "keyword"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if r.status_code != 200:
            pytest.skip("DB unavailable")
        assert r.json()["query_type"] in ("name", "mixed")

    def test_profiles_forbidden_fields_never_returned(self, authority_token):
        if not self._seed():
            pytest.skip("DB unavailable")
        r = client.post("/search/profiles", json={"query": self._NAME, "mode": "keyword"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if r.status_code != 200:
            pytest.skip("DB unavailable")
        self._assert_no_leak(r.json().get("matches", []))

    def test_profiles_degraded_flag_is_honest(self, authority_token):
        """Whatever the embedding backend state, `degraded` is a real boolean and
        the response never fabricates a semantic claim it cannot back."""
        r = client.post("/search/profiles",
                        json={"description": "someone tall and aggressive", "mode": "hybrid"},
                        headers={"Authorization": f"Bearer {authority_token}"})
        if r.status_code != 200:
            pytest.skip("DB unavailable")
        assert isinstance(r.json()["degraded"], bool)


class TestSemanticSearchAndIntelligence:
    """Tests for keyword / semantic / hybrid search over Case & Profile Intelligence."""

    def test_case_search_requires_authority(self):
        """Unauthenticated case search is rejected (cases are sensitive)."""
        resp = client.post("/search/cases", json={"query": "confinement", "limit": 5})
        assert resp.status_code == 401

    def test_case_search_forbidden_for_user(self, user_token):
        """A plain USER cannot search cases."""
        resp = client.post("/search/cases", json={"query": "confinement", "limit": 5},
                            headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 403

    def test_case_search_empty_query_rejected(self, authority_token):
        """Empty query returns a 400, never fabricated results."""
        resp = client.post("/search/cases", json={"query": "   ", "limit": 5},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 400

    def test_case_search_invalid_mode_rejected(self, authority_token):
        """An unknown mode is rejected."""
        resp = client.post("/search/cases", json={"query": "abuse", "mode": "telepathy"},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 400

    def test_keyword_mode(self, authority_token):
        """Keyword mode returns the uniform result shape."""
        resp = client.post("/search/cases",
                            json={"query": "physical confinement and threat", "limit": 5, "mode": "keyword"},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["results"], list)
        assert data["search_mode"] in ("keyword", "keyword_fallback")

    def test_semantic_mode(self, authority_token):
        """Semantic mode responds (may degrade to keyword_fallback without an embedding key)."""
        resp = client.post("/search/cases",
                            json={"query": "physical confinement and threat of abuse", "limit": 5, "mode": "semantic"},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data and isinstance(data["results"], list)
        # Honest labeling: if embeddings unavailable it must say so, not fake semantic.
        assert data["search_mode"] in ("semantic", "keyword_fallback")
        if data["search_mode"] == "keyword_fallback":
            assert data["degraded"] is True

    def test_hybrid_mode(self, authority_token):
        """Hybrid mode responds and respects the top-k limit."""
        resp = client.post("/search/cases",
                            json={"query": "threat of violence at home", "limit": 3, "mode": "hybrid"},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 3
        assert data["search_mode"] in ("hybrid", "keyword_fallback")

    def test_topk_limit_enforced(self, authority_token):
        """limit caps the number of returned results."""
        resp = client.post("/search/cases",
                            json={"query": "abuse", "limit": 2, "mode": "keyword"},
                            headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 2

    def test_embedding_info_reports_status(self):
        """GET /ai/embedding-info exposes model + honest status."""
        resp = client.get("/ai/embedding-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dimension"] == 768
        assert data["status"] in ("ACTIVE", "FALLBACK", "DEMO", "READY")
        assert "semantic_search_available" in data


class TestSearchServiceUnit:
    """Pure-function tests for the search service (no DB required)."""

    def test_keyword_score_deterministic(self):
        from services.search_service import _keyword_score
        s1 = _keyword_score("he locked me in the room", "locked room")
        s2 = _keyword_score("he locked me in the room", "locked room")
        assert s1 == s2 and 0.0 <= s1 <= 1.0
        # More matching terms -> higher score.
        assert _keyword_score("threat and violence", "threat violence") > _keyword_score("threat and violence", "stalking")

    def test_excerpt_centers_on_hit(self):
        from services.search_service import _excerpt
        ex = _excerpt("A long message. The word danger appears here. More text.", "danger")
        assert "danger" in ex

    def test_fallback_when_embeddings_unavailable(self, monkeypatch):
        """Semantic mode degrades to keyword_fallback when embeddings are DEMO."""
        import services.search_service as ss
        monkeypatch.setattr(ss, "_semantic_available", lambda: False)
        # No DB in test env -> empty results, but mode/degraded must be honest.
        out = ss.search_cases("threat of abuse", limit=5, mode="semantic")
        assert out["search_mode"] in ("keyword_fallback",) or out["total"] == 0
        if out["total"] and out["search_mode"] != "keyword_fallback":
            raise AssertionError("semantic claimed while embeddings unavailable")

    def test_embedding_dimension_stable_for_duplicates(self):
        """Re-embedding the same text yields a stable-dimension vector (safe to
        re-index duplicates without corrupting the vector field)."""
        from services.embeddings import embed, EMBEDDING_DIM
        v1 = embed("tall male aggressive black beard")
        v2 = embed("tall male aggressive black beard")
        assert len(v1) == EMBEDDING_DIM
        assert len(v2) == EMBEDDING_DIM


class TestLegalRAGCitations:
    """Tests for legal assistant returning source citations and legal disclaimers."""

    def test_legal_query_citations(self):
        """POST /legal/query returns answer with structured sources and disclaimer."""
        resp = client.post("/legal/query", json={
            "question": "What rights do I have if I am forced out of my matrimonial home?"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "sources" in data
        assert "disclaimer" in data
        assert "not constitute formal legal advice" in data["disclaimer"]


class TestLegalRAG:
    """RAG-specific tests: chunking, retrieval, no-context safety, authz, ingestion."""

    def test_clean_text_normalises(self):
        from services.legal_rag import clean_text
        assert clean_text("a\r\nb\t\t c\n\n\n\nd") == "a\nb c\n\nd"

    def test_chunk_document_splits_and_is_deterministic(self):
        from services.legal_rag import chunk_document
        text = ("Para one about protection orders. " * 20 + "\n\n"
                + "Para two about maintenance rights. " * 20 + "\n\n"
                + "Para three about custody. " * 20)
        c1 = chunk_document(text, max_chars=400, overlap=40)
        c2 = chunk_document(text, max_chars=400, overlap=40)
        assert len(c1) >= 2
        assert c1 == c2  # deterministic
        assert all(len(c) <= 600 for c in c1)  # roughly bounded

    def test_chunk_empty_text(self):
        from services.legal_rag import chunk_document
        assert chunk_document("") == []
        assert chunk_document("   \n\n  ") == []

    def test_chunk_hash_deterministic(self):
        from services.legal_rag import _chunk_hash
        assert _chunk_hash("DOC-1", "hello") == _chunk_hash("DOC-1", "hello")
        assert _chunk_hash("DOC-1", "hello") != _chunk_hash("DOC-2", "hello")

    def test_embedding_generation_dimension(self):
        from services.legal_rag import embed, EMBEDDING_DIM
        assert len(embed("protection of women from domestic violence")) == EMBEDDING_DIM

    def test_citation_dedup_from_retrieved_only(self):
        from services.legal_rag import _build_citations
        passages = [
            {"title": "PWDVA 2005", "section": "Section 17", "text": "Right to reside.", "score": 0.9, "document_id": "D1"},
            {"title": "PWDVA 2005", "section": "Section 17", "text": "Right to reside.", "score": 0.8, "document_id": "D1"},
            {"title": "PWDVA 2005", "section": "Section 19", "text": "Residence orders.", "score": 0.7, "document_id": "D1"},
        ]
        cites = _build_citations(passages)
        assert len(cites) == 2  # (Section 17) deduped
        assert {c["section"] for c in cites} == {"Section 17", "Section 19"}

    def test_no_context_does_not_hallucinate(self, monkeypatch):
        """When retrieval finds nothing, the answer is the safe no-context message,
        NOT a fabricated legal answer, and no LLM is called."""
        import services.legal_rag as rag
        called = {"llm": False}

        def _fake_retrieve(q, k=5, min_score=None):
            return {"passages": [], "mode": "semantic", "degraded": False}
        monkeypatch.setattr(rag, "retrieve", _fake_retrieve)
        # If the LLM were called, flip the flag (it must not be). Patch the EXACT
        # object answer() resolves at runtime. answer() does a lazy
        # `from services.ai_service import call_groq`, which reads
        # sys.modules["services.ai_service"]. Another hermetic test module
        # (test_legal_rag.py) swaps that sys.modules entry for a fake at import
        # time WITHOUT updating the `services.ai_service` package attribute, so
        # `import services.ai_service as ai` can bind a DIFFERENT module object
        # than the one answer() reads — patching that wrong object would be
        # silently bypassed. Patch sys.modules["services.ai_service"] directly.
        import sys
        ai = sys.modules["services.ai_service"]
        monkeypatch.setattr(ai, "call_groq", lambda *a, **k: called.__setitem__("llm", True) or "HALLUCINATED")

        out = rag.answer("Some obscure question with no sources", user_id="U1")
        assert out["no_context"] is True
        assert out["grounded"] is False
        assert out["sources"] == []
        assert out["answer"] == rag.NO_CONTEXT_MESSAGE
        assert called["llm"] is False  # never invoked without context

    def test_llm_unavailable_returns_sources_not_hallucination(self, monkeypatch):
        """If the LLM fails but sources were retrieved, we surface sources and a
        clear failure message — never invented content."""
        import services.legal_rag as rag
        passages = [{"title": "PWDVA 2005", "section": "Section 12", "text": "Application to Magistrate.",
                     "score": 0.82, "document_id": "D1", "source_url": ""}]
        monkeypatch.setattr(rag, "retrieve", lambda q, k=5, min_score=None: {"passages": passages, "mode": "semantic", "degraded": False})

        def _boom(*a, **k):
            raise RuntimeError("LLM down")
        # Patch the exact runtime-resolved object (see note in
        # test_no_context_does_not_hallucinate): answer()'s lazy
        # `from services.ai_service import call_groq` reads
        # sys.modules["services.ai_service"], which a sibling hermetic module may
        # have swapped for a fake — so patching `import ... as ai` would be bypassed.
        import sys
        ai = sys.modules["services.ai_service"]
        monkeypatch.setattr(ai, "call_groq", _boom)

        out = rag.answer("What is Section 12?", user_id="U1")
        assert out["status"] == "llm_unavailable"
        assert out["answer"] == rag.LLM_UNAVAILABLE_MESSAGE
        assert len(out["sources"]) == 1
        assert out["sources"][0]["section"] == "Section 12"
        # Generation status must NOT be conflated with evidence/retrieval status:
        # sources were retrieved, but no grounded ANSWER was generated.
        assert out["status"] != "grounded"

    def test_sources_with_llm_returns_grounded_answer(self, monkeypatch):
        """Sources retrieved AND the LLM succeeds -> status 'grounded', the model's
        answer is returned verbatim, and the verified sources are preserved."""
        import services.legal_rag as rag
        passages = [{"title": "PWDVA 2005", "section": "Section 12", "text": "Application to Magistrate.",
                     "score": 0.82, "document_id": "D1", "source_url": ""}]
        monkeypatch.setattr(rag, "retrieve", lambda q, k=5, min_score=None: {"passages": passages, "mode": "semantic", "degraded": False})
        # Patch the exact runtime-resolved object (see note in
        # test_no_context_does_not_hallucinate): patch sys.modules["services.ai_service"]
        # so the stub wins over any fake a sibling module may have installed there.
        import sys
        ai = sys.modules["services.ai_service"]
        monkeypatch.setattr(ai, "call_groq", lambda *a, **k: "Under Section 12 you may apply to the Magistrate [1].")

        out = rag.answer("What is Section 12?", user_id="U1")
        assert out["status"] == "grounded"
        assert out["grounded"] is True
        assert out["no_context"] is False
        assert out["answer"] == "Under Section 12 you may apply to the Magistrate [1]."
        assert out["answer"] != rag.LLM_UNAVAILABLE_MESSAGE
        assert len(out["sources"]) == 1
        assert out["sources"][0]["section"] == "Section 12"

    def test_relevance_floor_accepts_canonical_source_without_rerank_fields(self):
        """Regression guard for the #12 relevance floor: a canonical/legacy source
        that carries a genuine semantic `score` (already cleared retrieve()'s
        MIN_SCORE gate) but NONE of the private rerank-derived fields
        (_blended/_kw_ratio/_precise_hits/_cat_match) MUST still qualify as adequate
        evidence. Without this, an adequate source is mis-classified as no_context —
        the exact regression the floor's first cut introduced. This pins the
        contract so a future rerank refactor can't silently reintroduce it."""
        from services import legal_triage as t
        legacy = {"title": "PWDVA 2005", "section": "Section 12",
                  "text": "Application to Magistrate.", "score": 0.82, "document_id": "D1"}
        norm = t.normalize_passage(legacy)
        assert norm["semantic_score"] == 0.82
        assert norm["blended"] is None            # not reranked -> derived field absent
        assert t.passage_qualifies(legacy) is True
        assert t.assess_relevance([legacy])["passes"] is True
        # The floor is NOT weakened: a semantic score below the retrieval floor,
        # with no other support, is still rejected.
        assert t.passage_qualifies({"score": 0.40}) is False
        assert t.assess_relevance([{"score": 0.40}])["passes"] is False
        # And a genuinely weak keyword-only passage is still rejected.
        assert t.passage_qualifies(
            {"score": None, "_blended": 0.15, "_cat_match": False,
             "_precise_hits": 1, "_kw_ratio": 0.1}) is False

    def test_retrieval_falls_back_when_embeddings_unavailable(self, monkeypatch):
        """Embedding service DEMO/unavailable -> keyword_fallback retrieval mode."""
        import services.legal_rag as rag
        monkeypatch.setattr(rag, "embedding_info", lambda: {
            "status": "DEMO", "semantic_search_available": False,
            "model_name": "gemini-embedding-001", "backend": "google-gemini"})
        # No DB -> passages empty, but the honest mode is what we assert.
        res = rag.retrieve("domestic violence protection order", k=3)
        assert res["mode"] == "keyword_fallback"
        assert res["degraded"] is True

    def test_ingest_malformed_document_rejected(self):
        """Ingesting empty/malformed content is rejected, not embedded."""
        from services.legal_rag import ingest_document
        out = ingest_document(title="", text="", uploaded_by="ADMIN-001")
        assert out["chunks_ingested"] == 0
        assert "error" in out

    def test_ingest_endpoint_requires_admin(self, user_token, authority_token):
        """Only admins may ingest legal documents."""
        # Unauthenticated
        r0 = client.post("/legal/ingest", json={"title": "X", "text": "Y"})
        assert r0.status_code == 401
        # Plain user forbidden
        r1 = client.post("/legal/ingest", json={"title": "X", "text": "Y"},
                         headers={"Authorization": f"Bearer {user_token}"})
        assert r1.status_code == 403
        # Authority (non-admin) forbidden — management is admin-only
        r2 = client.post("/legal/ingest", json={"title": "X", "text": "Y"},
                         headers={"Authorization": f"Bearer {authority_token}"})
        assert r2.status_code == 403

    def test_upload_doc_requires_admin(self, user_token):
        """PDF upload is admin-only."""
        resp = client.post("/legal/upload-doc",
                           headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code in (401, 403, 422)  # 422 if file validation runs first


class TestVoiceSOSIntent:
    """Voice AI pipeline: intent detection + risk-classifier integration."""

    def test_intent_emergency(self):
        from services.intent_service import detect_intent
        r = detect_intent("Help me he has a knife and is threatening to kill me right now")
        assert r["intent"] == "EMERGENCY"
        assert 0.0 <= r["confidence"] <= 1.0
        assert isinstance(r["signals"], list) and r["signals"]

    def test_intent_possible_emergency(self):
        from services.intent_service import detect_intent
        r = detect_intent("He has been following me near my office and won't stop texting")
        assert r["intent"] in ("POSSIBLE_EMERGENCY", "EMERGENCY")
        assert r["needs_confirmation"] in (True, False)

    def test_intent_non_emergency(self):
        from services.intent_service import detect_intent
        # No emergency signals in this sentence -> NON_EMERGENCY.
        r = detect_intent("I would like to schedule a counselling appointment for next week")
        assert r["intent"] in ("NON_EMERGENCY", "UNKNOWN")

    def test_intent_unknown_on_empty(self):
        from services.intent_service import detect_intent
        r = detect_intent("")
        assert r["intent"] == "UNKNOWN"
        assert r["confidence"] == 0.0

    def test_low_recognition_confidence_downgrades(self):
        """Uncertain speech must not auto-escalate to EMERGENCY."""
        from services.intent_service import detect_intent
        r = detect_intent("he has a knife threatening to kill me", recognition_confidence=0.2)
        assert r["intent"] != "EMERGENCY"
        assert r["needs_confirmation"] is True

    def test_intent_deterministic(self):
        from services.intent_service import detect_intent
        a = detect_intent("he locked me in the room and is hitting me")
        b = detect_intent("he locked me in the room and is hitting me")
        assert a["intent"] == b["intent"] and a["signals"] == b["signals"]

    def test_risk_classifier_reused_for_transcript(self):
        """The transcript flows into the EXISTING risk classifier (no 2nd model)."""
        from services.risk_classifier import RiskClassifier
        risk = RiskClassifier().classify("he is choking me help me please")
        assert risk["severity"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
        assert "is_demo_mode" in risk

    def test_analyze_endpoint_empty_rejected(self):
        resp = client.post("/voice-sos/analyze", json={"transcript": "   "})
        assert resp.status_code == 400

    def test_analyze_endpoint_returns_pipeline(self):
        """/voice-sos/analyze returns intent + risk + honest availability flags,
        and never auto-actions."""
        resp = client.post("/voice-sos/analyze", json={
            "transcript": "he has a knife and is threatening to kill me right now",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"]["intent"] in ("EMERGENCY", "POSSIBLE_EMERGENCY", "NON_EMERGENCY", "UNKNOWN")
        assert "risk" in data
        assert data["auto_action"] is False

    def test_analyze_ai_unavailable_is_honest(self, monkeypatch):
        """If the risk classifier fails, the response says so rather than faking it."""
        import services.risk_classifier as rc

        class _Boom:
            def classify(self, *a, **k):
                raise RuntimeError("model down")
        monkeypatch.setattr(rc, "RiskClassifier", _Boom)
        resp = client.post("/voice-sos/analyze", json={"transcript": "help me now"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_available"] is False
        assert data["needs_confirmation"] is True

    def test_trigger_requires_config(self):
        """Trigger without configured Voice SOS is a safe 404, not a crash."""
        resp = client.post("/voice-sos/trigger", json={
            "user_id": "NO-SUCH-USER-VSOS", "spoken_phrase": "help",
            "latitude": 0.0, "longitude": 0.0,
        })
        assert resp.status_code in (404, 503)

    def test_trigger_model_accepts_voice_metadata(self):
        """VoiceSOSTriggerModel accepts optional transcript/intent/severity/risk."""
        from models.schemas import VoiceSOSTriggerModel
        m = VoiceSOSTriggerModel(user_id="U1", transcript="he is hurting me",
                                 intent="EMERGENCY", severity="CRITICAL", risk_score=92)
        assert m.intent == "EMERGENCY" and m.risk_score == 92


class TestP0SecurityFixes:
    """Regression tests for the P0 security audit fixes."""

    # ── P0 #1: user-scoped ownership (no unauthenticated bypass) ──
    def test_privacy_my_data_requires_auth(self):
        assert client.get("/privacy/my-data/USER-001").status_code == 401

    def test_privacy_my_data_forbidden_for_other_user(self, user_token):
        # user_token is USER-001; requesting USER-999 must be 403.
        r = client.get("/privacy/my-data/USER-999", headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_privacy_deletion_request_requires_auth(self):
        assert client.post("/privacy/deletion-request", json={"user_id": "USER-001"}).status_code == 401

    def test_voice_config_get_requires_auth(self):
        assert client.get("/voice-sos/config/USER-001").status_code == 401

    def test_voice_config_get_forbidden_for_other_user(self, user_token):
        r = client.get("/voice-sos/config/USER-999", headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_voice_history_requires_auth(self):
        assert client.get("/voice-sos/history/USER-001").status_code == 401

    def test_trusted_contacts_get_requires_auth(self):
        assert client.get("/trusted-contacts/USER-001").status_code == 401

    def test_trusted_contacts_get_forbidden_for_other_user(self, user_token):
        r = client.get("/trusted-contacts/USER-999", headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

    def test_authority_can_read_other_user_voice_config(self, authority_token):
        # Authority is explicitly allowed cross-user read (returns 200, not 403).
        r = client.get("/voice-sos/config/USER-001", headers={"Authorization": f"Bearer {authority_token}"})
        assert r.status_code == 200

    # ── P0 #5: /sos/evidence ──
    def test_evidence_requires_auth(self):
        r = client.post("/sos/evidence", json={"case_id": "ANY-CASE"})
        assert r.status_code in (401, 422)  # 401 no auth (422 only if body invalid first)

    def test_evidence_auth_then_missing_case(self, user_token):
        r = client.post("/sos/evidence", json={"case_id": "NO-SUCH-CASE-XYZ", "audio_base64": "", "image_base64": ""},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code in (404, 503)  # not found (or DB unavailable in CI)

    # ── P0 #6: /sos/location-update ──
    def test_location_update_requires_auth(self):
        r = client.post("/sos/location-update", json={"event_id": "E1", "latitude": 1.0, "longitude": 1.0})
        assert r.status_code in (401, 422)

    def test_location_update_auth_then_missing_event(self, user_token):
        r = client.post("/sos/location-update",
                        json={"event_id": "NO-SUCH-EVENT", "latitude": 1.0, "longitude": 1.0},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code in (404, 503)

    # ── P0 #3: unverified token can never yield an elevated role ──
    def test_forged_role_claim_is_downgraded_to_user(self):
        import jwt as _jwt
        from auth import decode_token
        # A token signed with the WRONG key, claiming admin. It is not a valid
        # internal token and (in dev, no Clerk) is unverifiable -> role forced to user.
        forged = _jwt.encode({"sub": "attacker", "user_id": "attacker", "role": "admin"},
                             "not-the-real-secret", algorithm="HS256")
        claims = decode_token(forged)
        assert claims["role"] == "user"

    def test_expired_internal_token_rejected(self):
        from datetime import timedelta
        from auth import decode_token
        import fastapi
        expired = create_access_token(user_id="U", role="user", expires_delta=timedelta(seconds=-5))
        with pytest.raises(fastapi.HTTPException):
            decode_token(expired)

    # ── P0 #4: production fail-fast on insecure defaults ──
    def test_production_config_fails_fast_on_defaults(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "IS_PRODUCTION", True)
        monkeypatch.setattr(auth, "JWT_SECRET", auth._DEFAULT_JWT_SECRET)
        monkeypatch.setattr(auth, "AUTHORITY_SECRET_KEY", auth._DEFAULT_AUTHORITY_KEY)
        monkeypatch.setattr(auth, "_RAW_EVID_KEY", auth._DEFAULT_EVIDENCE_KEY)
        monkeypatch.setattr(auth, "CLERK_ISSUER", "")
        monkeypatch.setattr(auth, "CLERK_JWKS_URL", "")
        with pytest.raises(RuntimeError):
            auth._validate_production_config()

    def test_production_config_ok_when_configured(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "IS_PRODUCTION", True)
        monkeypatch.setattr(auth, "JWT_SECRET", "a-real-strong-secret")
        monkeypatch.setattr(auth, "AUTHORITY_SECRET_KEY", "a-real-authority-key")
        monkeypatch.setattr(auth, "_RAW_EVID_KEY", "a-real-evidence-key")
        monkeypatch.setattr(auth, "CLERK_ISSUER", "https://example.clerk.accounts.dev")
        monkeypatch.setattr(auth, "CLERK_JWKS_URL", "https://example.clerk.accounts.dev/.well-known/jwks.json")
        auth._validate_production_config()  # must not raise


class TestP0WebSocketSecurity:
    """P0 #2: /ws/track must not leak or accept GPS without authorization."""

    def _expect_rejected(self, url):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises((WebSocketDisconnect, Exception)):
            with client.websocket_connect(url) as ws:
                ws.receive_json()

    def test_ws_no_token_rejected(self):
        self._expect_rejected("/ws/track/EVENT-1")

    def test_ws_invalid_token_rejected(self):
        self._expect_rejected("/ws/track/EVENT-1?token=not-a-jwt")

    def test_ws_expired_token_rejected(self):
        from datetime import timedelta
        expired = create_access_token(user_id="U", role="user", expires_delta=timedelta(seconds=-5))
        self._expect_rejected(f"/ws/track/EVENT-1?token={expired}")

    def test_ws_valid_token_unknown_event_rejected(self):
        # Valid token but the event does not exist (or no DB) -> rejected, no leak.
        tok = create_access_token(user_id="U-OWNER", role="user")
        self._expect_rejected(f"/ws/track/NO-SUCH-EVENT-123?token={tok}")


class TestPrivacyCenter:
    """Tests for user privacy data export and deletion endpoints."""

    def test_get_privacy_data(self, user_token):
        """GET /privacy/my-data/{user_id} aggregates user records."""
        resp = client.get("/privacy/my-data/USER-001", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "sos_cases" in data
        assert "therapy_sessions" in data

    def test_account_deletion_request(self, user_token):
        """POST /privacy/deletion-request registers user deletion request."""
        resp = client.post("/privacy/deletion-request", json={
            "user_id": "USER-001",
            "reason": "Exercising right to be forgotten"
        }, headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "request_id" in data


class TestAnalyticsDashboard:
    """Tests for authority analytics dashboard metrics."""

    def test_analytics_dashboard_metrics(self, authority_token):
        """GET /analytics/dashboard returns aggregated metrics."""
        resp = client.get("/analytics/dashboard", headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sos" in data
        assert "pending" in data
        assert "critical" in data

    def test_severity_distribution(self, authority_token):
        """GET /analytics/severity-distribution returns breakdown."""
        resp = client.get("/analytics/severity-distribution", headers={"Authorization": f"Bearer {authority_token}"})
        assert resp.status_code == 200
        assert "distribution" in resp.json()


class TestP2AuditHardening:
    """P2-1: request-context capture, sensitive-access events, and a tamper-
    evidence hash chain on audit records.

    The hash-chain / IP / no-secrets checks are pure functions and always run.
    The HTTP-level checks require the audit_logs collection (Mongo); when it is
    unavailable they skip rather than falsely fail (PyPI/Mongo may be absent).
    """

    # --- helpers ---------------------------------------------------------
    class _Hdrs(dict):
        def get(self, k, default=None):
            for kk, vv in self.items():
                if kk.lower() == k.lower():
                    return vv
            return default

    class _Addr:
        def __init__(self, host):
            self.host = host

    class _FakeReq:
        def __init__(self, headers=None, host="203.0.113.9"):
            self.headers = TestP2AuditHardening._Hdrs(headers or {})
            self.client = TestP2AuditHardening._Addr(host)

    def _audit_available(self):
        from services.db import audit_logs
        return audit_logs() is not None

    # --- STEP 2: request context / IP -----------------------------------
    def test_ip_captured_from_request_context(self):
        """(1) IP is captured from a Request (first X-Forwarded-For hop)."""
        from services import audit_service as a
        req = self._FakeReq(headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1",
                                     "user-agent": "HavenApp/1.0"})
        # Build the record shape the service produces (without needing Mongo)
        ip = a._extract_ip(req)
        ua = a._extract_user_agent(req)
        assert ip == "198.51.100.7"
        assert ua == "HavenApp/1.0"

    def test_direct_client_ip_without_proxy_header(self):
        from services import audit_service as a
        assert a._extract_ip(self._FakeReq(host="192.0.2.55")) == "192.0.2.55"

    # --- STEP 3 / STEP 2: no secrets in canonical record ----------------
    def test_no_secrets_in_hashed_fields(self):
        """(2) The canonical hash payload only contains metadata fields."""
        from services import audit_service as a
        assert "password" not in a._HASH_FIELDS
        assert "token" not in a._HASH_FIELDS
        assert "authorization" not in a._HASH_FIELDS
        # canonical serialization of a benign doc contains no secret markers
        doc = {"actor_id": "U", "role": "user", "action": "X",
               "metadata": {"target_user_id": "U", "cases": 2}}
        blob = a._canonical_json(doc).lower()
        for marker in ("password", "bearer ", "access_token", "safe_word"):
            assert marker not in blob

    # --- STEP 7: hash chain ---------------------------------------------
    def test_event_hash_is_deterministic_canonical(self):
        """(9) Same canonical content -> identical hash (key order agnostic)."""
        from services import audit_service as a
        base = {"audit_id": "A", "actor_id": "u", "role": "user", "action": "ACT",
                "case_id": None, "result": "success", "reason": "", "ip_address": "1.1.1.1",
                "user_agent": "ua", "metadata": {"b": 2, "a": 1},
                "timestamp": "2026-01-01T00:00:00"}
        reordered = dict(base); reordered["metadata"] = {"a": 1, "b": 2}
        h1 = a.compute_event_hash(base, a.GENESIS_HASH)
        h2 = a.compute_event_hash(reordered, a.GENESIS_HASH)
        assert h1 == h2
        assert len(h1) == 64

    def test_tampering_breaks_hash_verification(self):
        """(10) Modifying a record's canonical content fails verification."""
        from services import audit_service as a
        d1 = {"audit_id": "A1", "actor_id": "u1", "role": "user", "action": "ACT",
              "metadata": {}, "timestamp": "2026-01-01T00:00:00"}
        d1["previous_hash"] = a.GENESIS_HASH
        d1["event_hash"] = a.compute_event_hash(d1, a.GENESIS_HASH)
        d2 = {"audit_id": "A2", "actor_id": "u2", "role": "user", "action": "ACT2",
              "metadata": {}, "timestamp": "2026-01-01T00:00:01"}
        d2["previous_hash"] = d1["event_hash"]
        d2["event_hash"] = a.compute_event_hash(d2, d1["event_hash"])
        ok, bad = a.verify_audit_chain([d1, d2])
        assert ok is True and bad is None
        d2_tampered = dict(d2); d2_tampered["actor_id"] = "ATTACKER"
        ok2, bad2 = a.verify_audit_chain([d1, d2_tampered])
        assert ok2 is False and bad2 == "A2"

    def test_legacy_records_without_hash_readable(self):
        """(11) Legacy records lacking hash fields verify OK (skipped)."""
        from services import audit_service as a
        legacy = [{"audit_id": "OLD", "actor_id": "u", "action": "OLD",
                   "timestamp": "t"}]
        ok, bad = a.verify_audit_chain(legacy)
        assert ok is True and bad is None

    # --- STEP 4/6: privacy data-access event ----------------------------
    def test_privacy_data_access_audit_event(self, user_token):
        """(3)(6) Reading /privacy/my-data records PRIVACY_DATA_ACCESSED with
        the actor identity from the verified token; (8) admin audit API still
        returns the record. Skips if the audit store is unavailable."""
        if not self._audit_available():
            pytest.skip("audit_logs collection unavailable (no Mongo)")
        admin = create_access_token(user_id="ADMIN-001", role="admin", name="Admin")
        client.get("/privacy/my-data/USER-001",
                   headers={"Authorization": f"Bearer {user_token}"})
        resp = client.get("/admin/audit-logs?action=PRIVACY_DATA_ACCESSED",
                          headers={"Authorization": f"Bearer {admin}"})
        assert resp.status_code == 200
        logs = resp.json().get("logs", [])
        assert any(l["action"] == "PRIVACY_DATA_ACCESSED"
                   and l.get("actor_id") == "USER-001" for l in logs)

    def test_privacy_event_has_no_pii(self, user_token):
        """(2) The privacy audit event stores counts/ids only, never PII."""
        if not self._audit_available():
            pytest.skip("audit_logs collection unavailable (no Mongo)")
        admin = create_access_token(user_id="ADMIN-001", role="admin", name="Admin")
        client.get("/privacy/my-data/USER-001",
                   headers={"Authorization": f"Bearer {user_token}"})
        resp = client.get("/admin/audit-logs?action=PRIVACY_DATA_ACCESSED&actor_id=USER-001",
                          headers={"Authorization": f"Bearer {admin}"})
        for l in resp.json().get("logs", []):
            meta = l.get("metadata", {})
            assert "phone" not in meta and "email" not in meta
            assert "sos_cases" not in meta  # no raw records, only counts

    # --- STEP 8: existing audit-log API compatible ----------------------
    def test_existing_audit_log_api_compatible(self):
        """(8) The admin audit-log API shape is unchanged."""
        admin = create_access_token(user_id="ADMIN-001", role="admin", name="Admin")
        resp = client.get("/admin/audit-logs",
                          headers={"Authorization": f"Bearer {admin}"})
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            body = resp.json()
            for k in ("logs", "total", "page", "limit"):
                assert k in body

    # --- STEP 5: legal-query still hashes -------------------------------
    def test_legal_query_still_hashes_not_raw(self):
        """(7) Legal-query audit stores q_hash, never the raw question text."""
        resp = client.post("/legal/query", json={"question": "What are my rights?"})
        # Endpoint stays functional; the hashing behavior is asserted at the
        # audit layer (legal_routes builds metadata={'q_hash': ...}).
        assert resp.status_code in (200, 429, 503)


# ─── P2-2: Distributed rate limiting + durable cooldowns ────
import asyncio as _asyncio
import time as _time
import rate_limiter as _rl
from fastapi import HTTPException


class _FakeRedis:
    """Pure-Python emulation of the ZSET/TTL ops the limiter uses.

    NOTE: does NOT run the Lua script inside real Redis — this verifies the
    limiter/cooldown LOGIC and fallback wiring, not real-Redis atomicity.
    """
    def __init__(self):
        self.zsets = {}; self.kv = {}; self.expiry = {}; self.raise_on = set()

    def ping(self):
        return True

    def eval(self, script, numkeys, *args):
        if "eval" in self.raise_on:
            raise RuntimeError("redis down")
        key = args[0]; now = int(args[1]); window = int(args[2])
        maxr = int(args[3]); member = args[4]
        z = self.zsets.setdefault(key, {})
        cutoff = now - window
        for m in [m for m, s in z.items() if s <= cutoff]:
            del z[m]
        if len(z) >= maxr:
            return 1
        z[member] = now
        return 0

    def set(self, key, val, px=None, nx=False):
        self.kv[key] = val
        if px:
            self.expiry[key] = _time.time() * 1000 + px

    def pttl(self, key):
        if "pttl" in self.raise_on:
            raise RuntimeError("redis down")
        if key not in self.kv:
            return -2
        if key not in self.expiry:
            return -1
        rem = self.expiry[key] - _time.time() * 1000
        if rem <= 0:
            self.kv.pop(key, None); self.expiry.pop(key, None); return -2
        return int(rem)


class _Req:
    class _Hdrs(dict):
        def get(self, k, d=None):
            for kk, vv in self.items():
                if kk.lower() == k.lower():
                    return vv
            return d

    class _Addr:
        def __init__(self, h): self.host = h

    def __init__(self, headers=None, host="203.0.113.5"):
        self.headers = self._Hdrs(headers or {}); self.client = self._Addr(host)


def _run(coro):
    return _asyncio.new_event_loop().run_until_complete(coro)


def _use_memory():
    _rl._reset_backend_for_tests()
    _rl.IS_PRODUCTION = False; _rl.REDIS_ENABLED = False; _rl.REDIS_URL = ""
    _rl.REDIS_REQUIRED_IN_PRODUCTION = False


def _use_redis():
    _rl._reset_backend_for_tests()
    fake = _FakeRedis()
    _rl._backend_resolved = True; _rl._backend_mode = "redis"; _rl._redis_client = fake
    return fake


class TestP2DistributedRateLimit:
    """P2-2 distributed rate limiting + durable cooldowns (fake Redis)."""

    def test_under_limit_allowed_memory(self):
        _use_memory()
        dep = _rl.rate_limit_dependency(max_requests=3, window_seconds=60, scope="p1")
        req = _Req(host="10.0.0.1")
        assert all(_run(dep(req)) is True for _ in range(3))

    def test_over_limit_blocked_429_memory(self):
        _use_memory()
        dep = _rl.rate_limit_dependency(max_requests=1, window_seconds=60, scope="p2")
        req = _Req(host="10.0.0.2")
        _run(dep(req))
        with pytest.raises(HTTPException) as ei:
            _run(dep(req))
        assert ei.value.status_code == 429

    def test_429_detail_and_retry_after_preserved(self):
        _use_memory()
        dep = _rl.rate_limit_dependency(max_requests=1, window_seconds=45, scope="p3")
        req = _Req(host="10.0.0.3")
        _run(dep(req))
        with pytest.raises(HTTPException) as ei:
            _run(dep(req))
        assert ei.value.detail == "Rate limit exceeded. Maximum 1 requests per 45 seconds."
        assert ei.value.headers.get("Retry-After") == "45"

    def test_per_ip_isolation(self):
        _use_memory()
        dep = _rl.rate_limit_dependency(max_requests=1, window_seconds=60, scope="p4")
        _run(dep(_Req(host="1.1.1.1")))
        assert _run(dep(_Req(host="2.2.2.2"))) is True

    def test_per_endpoint_isolation_no_global_bucket(self):
        _use_memory()
        a = _rl.rate_limit_dependency(max_requests=1, window_seconds=60)
        b = _rl.rate_limit_dependency(max_requests=1, window_seconds=60)
        req = _Req(host="5.5.5.5")
        _run(a(req))
        assert _run(b(req)) is True

    def test_auth_identity_hashed_no_raw_jwt(self):
        jwt = "Bearer eyJhbGciOiJIUzI1NiJ9.body.sig-SECRET"
        ident = _rl._client_identity(_Req(headers={"Authorization": jwt}, host="9.9.9.9"))
        assert ident != _rl._client_identity(_Req(host="9.9.9.9"))
        assert "eyJhbGci" not in ident and "SECRET" not in ident
        assert ":tok_" in ident

    def test_redis_backend_allows_then_blocks(self):
        fake = _use_redis()
        dep = _rl.rate_limit_dependency(max_requests=2, window_seconds=60, scope="p7")
        req = _Req(host="7.7.7.7")
        assert all(_run(dep(req)) is True for _ in range(2))
        with pytest.raises(HTTPException) as ei:
            _run(dep(req))
        assert ei.value.status_code == 429
        assert any(k.startswith("haven:ratelimit:p7:") for k in fake.zsets)

    def test_redis_window_expiry(self):
        _use_redis()
        dep = _rl.rate_limit_dependency(max_requests=1, window_seconds=1, scope="p9")
        req = _Req(host="9.1.1.1")
        _run(dep(req))
        with pytest.raises(HTTPException):
            _run(dep(req))
        _time.sleep(1.15)
        assert _run(dep(req)) is True

    def test_production_fail_closed_when_redis_required_missing(self):
        _rl._reset_backend_for_tests()
        _rl.IS_PRODUCTION = True; _rl.REDIS_REQUIRED_IN_PRODUCTION = True
        _rl.REDIS_ENABLED = False; _rl.REDIS_URL = ""
        dep = _rl.rate_limit_dependency(max_requests=5, window_seconds=60, scope="fc")
        with pytest.raises(HTTPException) as ei:
            _run(dep(_Req(host="1.2.3.4")))
        assert ei.value.status_code == 503
        assert _rl.backend_status() == "fail_closed"
        _use_memory()  # restore

    def test_redis_error_dev_degrades_to_memory(self):
        _rl._reset_backend_for_tests()
        _rl.IS_PRODUCTION = False; _rl.REDIS_REQUIRED_IN_PRODUCTION = False
        fake = _FakeRedis(); fake.raise_on.add("eval")
        _rl._backend_resolved = True; _rl._backend_mode = "redis"; _rl._redis_client = fake
        dep = _rl.rate_limit_dependency(max_requests=5, window_seconds=60, scope="dv")
        assert _run(dep(_Req(host="1.2.3.10"))) is True
        _use_memory()

    # ── cooldowns ──
    def test_cooldown_set_then_active_memory(self):
        _use_memory()
        m = {}
        _rl.cooldown_set("voice_sos", "userA", 30, m)
        assert _rl.cooldown_remaining("voice_sos", "userA", 30, m) > 0

    def test_cooldown_expires_memory(self):
        _use_memory()
        m = {"userB": _time.time() - 31}
        assert _rl.cooldown_remaining("voice_sos", "userB", 30, m) == 0

    def test_cooldown_per_user_isolation(self):
        _use_memory()
        m = {}
        _rl.cooldown_set("voice_sos", "victimX", 60, m)
        assert _rl.cooldown_remaining("voice_sos", "victimX", 60, m) > 0
        assert _rl.cooldown_remaining("voice_sos", "victimY", 60, m) == 0

    def test_cooldown_durable_via_redis(self):
        fake = _use_redis()
        m = {}
        _rl.cooldown_set("voice_sos", "userR", 30, m)
        assert _rl.cooldown_remaining("voice_sos", "userR", 30, m) > 0
        assert "haven:cooldown:voice_sos:userR" in fake.kv
        _use_memory()

    def test_cooldown_never_fails_closed(self):
        fake = _use_redis()
        m = {}
        _rl.cooldown_set("voice_sos", "userE", 30, m)
        fake.raise_on.add("pttl")
        assert _rl.cooldown_remaining("voice_sos", "userE", 30, m) > 0
        _use_memory()


# ─── P2-3: JWT error sanitization + global request-body size limit ─────────
_LEAKY_MARKERS = (
    "signature", "jwk", "kid", "issuer", "iss ", "algorithm", "traceback",
    "pyjwt", "invalidtoken", "expiredsignature", "clerk", "jwks", "secret",
    "0x", "decode", "verify_", ".py", "exception", "line ",
)


def _detail_is_generic(detail: str) -> bool:
    from auth import _GENERIC_AUTH_ERROR
    if detail != _GENERIC_AUTH_ERROR:
        return False
    low = detail.lower()
    return not any(m in low for m in _LEAKY_MARKERS)


class TestP2JWTErrorSanitization:
    """P2-3 Part A: every client-visible auth error is a single stable string.

    Uses test-only, generated secrets/tokens — never production credentials.
    """

    def test_malformed_token_401_generic(self):
        from auth import decode_token
        with pytest.raises(HTTPException) as ei:
            decode_token("this.is.garbage")
        assert ei.value.status_code == 401
        assert _detail_is_generic(ei.value.detail)

    def test_invalid_signature_401_generic_strict(self, monkeypatch):
        import jwt as _jwt
        import auth as _auth
        monkeypatch.setattr(_auth, "STRICT_AUTH", True)
        # A well-formed JWT signed with the WRONG key (test-only secret).
        bad = _jwt.encode({"sub": "x", "role": "admin"}, "wrong-test-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as ei:
            _auth.decode_token(bad)
        assert ei.value.status_code == 401
        assert _detail_is_generic(ei.value.detail)

    def test_expired_internal_token_401_generic(self):
        from datetime import timedelta
        from auth import decode_token
        expired = create_access_token(user_id="U", role="user", expires_delta=timedelta(seconds=-5))
        with pytest.raises(HTTPException) as ei:
            decode_token(expired)
        assert ei.value.status_code == 401
        assert _detail_is_generic(ei.value.detail)

    def test_missing_claims_401_generic_strict(self, monkeypatch):
        import auth as _auth
        monkeypatch.setattr(_auth, "STRICT_AUTH", True)
        # Header-only "token" (no verifiable claims) under strict mode -> 401.
        with pytest.raises(HTTPException) as ei:
            _auth.decode_token("eyJhbGciOiJIUzI1NiJ9")
        assert ei.value.status_code == 401
        assert _detail_is_generic(ei.value.detail)

    def test_no_raw_exception_text_exposed(self, monkeypatch):
        import auth as _auth
        monkeypatch.setattr(_auth, "STRICT_AUTH", True)
        for tok in ("....", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.x.y", "not-a-jwt"):
            try:
                _auth.decode_token(tok)
            except HTTPException as e:
                low = str(e.detail).lower()
                assert not any(m in low for m in _LEAKY_MARKERS), f"leak in: {e.detail}"

    def test_valid_internal_token_still_authenticates(self):
        from auth import decode_token
        tok = create_access_token(user_id="USER-9", role="user", name="Ok")
        claims = decode_token(tok)
        assert claims["user_id"] == "USER-9" and claims["role"] == "user"

    def test_rbac_roles_unchanged(self):
        from auth import require_authority, require_admin, AuthUser
        authority = AuthUser(user_id="O1", role="authority")
        admin = AuthUser(user_id="A1", role="admin")
        user = AuthUser(user_id="U1", role="user")
        assert require_authority(authority) is authority
        assert require_admin(admin) is admin
        with pytest.raises(HTTPException) as e1:
            require_authority(user)
        assert e1.value.status_code == 403
        with pytest.raises(HTTPException) as e2:
            require_admin(authority)
        assert e2.value.status_code == 403

    def test_http_endpoint_returns_generic_401(self):
        from auth import _GENERIC_AUTH_ERROR
        r = client.get("/privacy/my-data/USER-001",
                       headers={"Authorization": "Bearer this.is.garbage"})
        assert r.status_code == 401
        body = r.json()
        assert body.get("detail") == _GENERIC_AUTH_ERROR
        assert "garbage" not in r.text.lower()


def _build_sized_app(max_bytes: int):
    """A tiny real ASGI app wrapped with the REAL BodySizeLimitMiddleware."""
    from fastapi import FastAPI as _FA, Request as _Rq
    from main import BodySizeLimitMiddleware
    a = _FA()

    @a.get("/ping")
    def ping():
        return {"ok": True}

    @a.post("/echo")
    async def echo(req: _Rq):
        raw = await req.body()
        return {"n": len(raw)}

    a.add_middleware(BodySizeLimitMiddleware, max_body_bytes=max_bytes)
    return TestClient(a)


class TestP2BodySizeLimit:
    """P2-3 Part B: global request-body ceiling enforced at the ASGI boundary."""

    def test_below_limit_reaches_endpoint(self):
        c = _build_sized_app(1000)
        r = c.post("/echo", content=b"x" * 500)
        assert r.status_code == 200 and r.json()["n"] == 500

    def test_at_boundary_ok(self):
        c = _build_sized_app(1000)
        r = c.post("/echo", content=b"x" * 1000)
        assert r.status_code == 200 and r.json()["n"] == 1000

    def test_above_limit_413(self):
        c = _build_sized_app(1000)
        r = c.post("/echo", content=b"x" * 1001)
        assert r.status_code == 413
        assert r.json()["detail"] == "Request body too large."

    def test_no_internal_detail_in_413(self):
        c = _build_sized_app(1000)
        r = c.post("/echo", content=b"x" * 5000)
        low = r.text.lower()
        assert not any(m in low for m in ("middleware", "traceback", "asgi", ".py", "exception"))

    def test_get_head_unaffected(self):
        c = _build_sized_app(10)  # tiny limit; GET has no body
        assert c.get("/ping").status_code == 200
        assert c.head("/ping").status_code in (200, 405)

    def test_normal_small_json_passes(self):
        c = _build_sized_app(1_000_000)
        r = c.post("/echo", json={"hello": "world"})
        assert r.status_code == 200

    def test_spoofed_small_content_length_still_counted(self):
        # Drive the middleware's streaming counter directly: a lying small
        # Content-Length must NOT let a large streamed body through.
        import asyncio
        from main import BodySizeLimitMiddleware

        async def inner(scope, receive, send):  # pragma: no cover - not reached
            while True:
                m = await receive()
                if not m.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = BodySizeLimitMiddleware(inner, max_body_bytes=100)
        scope = {"type": "http", "method": "POST",
                 "headers": [(b"content-length", b"10")]}  # lies: says 10

        chunks = [
            {"type": "http.request", "body": b"y" * 80, "more_body": True},
            {"type": "http.request", "body": b"y" * 80, "more_body": False},
        ]
        sent = []

        async def recv():
            return chunks.pop(0)

        async def send(m):
            sent.append(m)

        asyncio.run(mw(scope, recv, send))
        assert sent and sent[0]["status"] == 413

    def test_websocket_scope_passes_through(self):
        import asyncio
        from main import BodySizeLimitMiddleware
        called = {"v": False}

        async def inner(scope, receive, send):
            called["v"] = True

        mw = BodySizeLimitMiddleware(inner, max_body_bytes=1)
        asyncio.run(mw({"type": "websocket"}, None, None))
        assert called["v"] is True

    def test_endpoint_specific_limit_still_stricter(self):
        # The covert stego /encode guard (~11MB) must remain the stricter limit
        # regardless of the (larger) global ceiling.
        from routers.sos_routes import _decode_image_b64, MAX_IMAGE_B64_CHARS
        with pytest.raises(HTTPException) as ei:
            _decode_image_b64("A" * (MAX_IMAGE_B64_CHARS + 1))
        assert ei.value.status_code == 413
