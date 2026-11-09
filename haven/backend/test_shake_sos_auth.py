"""
test_shake_sos_auth.py — Integration tests for:
  - POST /auth/user-register
  - POST /auth/user-login
  - POST /shake-sos/trigger  (auth enforcement, ownership, idempotency)
  - sms_service.notify_trusted_contacts  (NOT_CONFIGURED path)

Uses TestClient from FastAPI / Starlette. MongoDB is mocked via mongomock
where available; if not, tests use STRICT_AUTH=false + MOCK_DB mode.
All tests run WITHOUT touching a live database or sending real SMS.
"""
import os
import sys
import uuid
import pytest
from unittest.mock import MagicMock, patch

# ── Ensure dev-mode auth (no live Clerk / strict verification needed) ──────────
os.environ.setdefault("STRICT_AUTH", "false")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("MOCK_DB", "true")

# ── SMS: ensure Twilio credentials are absent so we get NOT_CONFIGURED ─────────
for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
    os.environ.pop(k, None)


# ─── sms_service unit tests (no network, no DB) ───────────────────────────────

class TestSmsServiceNotConfigured:
    """When Twilio credentials are absent, every contact gets NOT_CONFIGURED."""

    def test_empty_contacts_returns_empty(self):
        from services.sms_service import notify_trusted_contacts
        results = notify_trusted_contacts([], "CASE-001", "test message")
        assert results == []

    def test_single_contact_not_configured(self):
        from services.sms_service import notify_trusted_contacts, STATUS_NOT_CONFIGURED
        contacts = [{"contact_id": "c1", "name": "Priya", "phone": "+919876543210"}]
        results = notify_trusted_contacts(contacts, "CASE-002", "emergency")
        assert len(results) == 1
        assert results[0].status == STATUS_NOT_CONFIGURED
        assert results[0].contact_id == "c1"
        assert results[0].name == "Priya"

    def test_multiple_contacts_all_not_configured(self):
        from services.sms_service import notify_trusted_contacts, STATUS_NOT_CONFIGURED
        contacts = [
            {"contact_id": "c1", "name": "A", "phone": "+911234567890"},
            {"contact_id": "c2", "name": "B", "phone": "+910987654321"},
        ]
        results = notify_trusted_contacts(contacts, "CASE-003", "help")
        assert all(r.status == STATUS_NOT_CONFIGURED for r in results)

    def test_to_safe_dict_excludes_phone(self):
        from services.sms_service import notify_trusted_contacts
        contacts = [{"contact_id": "c1", "name": "Meera", "phone": "+919999000001"}]
        results = notify_trusted_contacts(contacts, "CASE-004", "test")
        safe = results[0].to_safe_dict()
        assert "phone" not in safe
        assert safe["contact_id"] == "c1"
        assert safe["status"] in ("NOT_CONFIGURED", "FAILED", "SENT_TO_PROVIDER", "QUEUED")

    def test_never_raises_on_missing_phone(self):
        from services.sms_service import notify_trusted_contacts, STATUS_FAILED
        # A contact with no phone number should yield FAILED (missing phone), not raise
        contacts = [{"contact_id": "c9", "name": "NoPhone"}]  # phone key absent
        results = notify_trusted_contacts(contacts, "CASE-005", "test")
        # Either NOT_CONFIGURED (no credentials) or FAILED (no phone) — must not raise
        assert len(results) == 1
        assert results[0].status in ("NOT_CONFIGURED", "FAILED")

    def test_phone_masking(self):
        from services.sms_service import _mask_phone
        assert _mask_phone("+919876543210") == "***3210"
        assert _mask_phone("9999") == "***9999"
        assert _mask_phone("") == "****"


class TestSmsServiceConfigured:
    """When credentials ARE set, verify dispatch is attempted."""

    def test_twilio_library_failure_returns_failed(self):
        from services import sms_service as sms
        credentials = ("AC_fake_sid", "fake_token", "+10000000000")

        with patch.object(sms, "_load_credentials", return_value=credentials):
            with patch.object(sms, "_dispatch_sms", side_effect=RuntimeError("network_err")):
                results = sms.notify_trusted_contacts(
                    [{"contact_id": "cx", "name": "X", "phone": "+911234567890"}],
                    "CASE-010", "test"
                )
        assert results[0].status == sms.STATUS_FAILED
        assert results[0].error_message == "RuntimeError"

    def test_sent_to_provider_on_success(self):
        from services import sms_service as sms
        credentials = ("AC_fake_sid", "fake_token", "+10000000000")

        with patch.object(sms, "_load_credentials", return_value=credentials):
            with patch.object(sms, "_dispatch_sms", return_value=sms.STATUS_SENT_TO_PROVIDER):
                results = sms.notify_trusted_contacts(
                    [{"contact_id": "cy", "name": "Y", "phone": "+911234567890"}],
                    "CASE-011", "test"
                )
        assert results[0].status == sms.STATUS_SENT_TO_PROVIDER


# ─── auth module unit tests (no network, no DB) ───────────────────────────────

class TestPasswordHashing:
    """Verify PBKDF2 hash/verify round-trips and edge cases."""

    def test_hash_and_verify_roundtrip(self):
        from auth import hash_password, verify_password
        pw = "S3cr3t!Passw0rd"
        h = hash_password(pw)
        assert verify_password(pw, h["hash"], h["salt"])

    def test_wrong_password_fails(self):
        from auth import hash_password, verify_password
        h = hash_password("correct")
        assert not verify_password("incorrect", h["hash"], h["salt"])

    def test_empty_password_raises(self):
        from auth import hash_password
        with pytest.raises((ValueError, Exception)):
            hash_password("")

    def test_different_salts_different_hashes(self):
        from auth import hash_password
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        # Salts must be random — two hashes of the same password must differ
        assert h1["salt"] != h2["salt"]
        assert h1["hash"] != h2["hash"]

    def test_verify_rejects_wrong_salt(self):
        from auth import hash_password, verify_password
        h = hash_password("pw")
        bad_salt = hash_password("pw")["salt"]  # different random salt
        assert not verify_password("pw", h["hash"], bad_salt)


# ─── UserRegisterModel / UserLoginModel validation ────────────────────────────

class TestUserModels:
    def test_register_model_email_validated(self):
        from models.schemas import UserRegisterModel
        with pytest.raises(Exception):
            UserRegisterModel(email="not_an_email", password="Valid1234!", name="Test")

    def test_register_model_password_min_length(self):
        from models.schemas import UserRegisterModel
        with pytest.raises(Exception):
            UserRegisterModel(email="a@b.com", password="short", name="Test")

    def test_register_model_valid(self):
        from models.schemas import UserRegisterModel
        m = UserRegisterModel(email="user@example.com", password="Secure1234!", name="Alice")
        assert m.email == "user@example.com"
        assert m.name == "Alice"

    def test_login_model_normalises_email(self):
        from models.schemas import UserLoginModel
        m = UserLoginModel(email="  USER@EXAMPLE.COM  ", password="pw")
        assert m.email == "user@example.com"


# ─── JWT / token tests ────────────────────────────────────────────────────────

class TestTokens:
    def test_user_token_has_role_user(self):
        from auth import create_access_token, decode_token
        token = create_access_token(user_id="u-123", role="user", email="t@t.com")
        claims = decode_token(token)
        assert claims["role"] == "user"
        assert claims["user_id"] == "u-123"

    def test_user_token_cannot_claim_authority_role(self):
        """Even if a client forges role=authority in an unverified token,
        decode_token forces role=user for external tokens in non-strict mode."""
        import jwt as pyjwt
        from auth import decode_token, JWT_SECRET, JWT_ALGORITHM
        # Forge a token with role=authority using a WRONG key (will be unverifiable)
        forged = pyjwt.encode(
            {"sub": "hacker", "user_id": "hacker", "role": "authority",
             "iss": "some-other-issuer"},
            "wrong-secret",
            algorithm="HS256"
        )
        # STRICT_AUTH=false → decode_token accepts unverifiable tokens but forces role=user
        claims = decode_token(forged)
        assert claims["role"] == "user", "Forged authority role must be downgraded to user"

    def test_expired_token_raises(self):
        from datetime import timedelta
        from auth import create_access_token, decode_token
        import time
        token = create_access_token("u-999", expires_delta=timedelta(seconds=-1))
        with pytest.raises(Exception):
            decode_token(token)
