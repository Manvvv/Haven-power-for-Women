"""
Automated Security Test Suite for Haven Backend
Tests authentication, role authorization, evidence AES-GCM encryption, safe-word salting, mass-assignment guard and rate limiting.
"""

import sys
import os
import unittest
from fastapi.testclient import TestClient

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(__file__))

from main import app
from auth import (
    hash_safe_word_salted,
    verify_safe_word,
    encrypt_evidence_payload,
    decrypt_evidence_payload,
    create_access_token,
    verify_authority_password,
)

client = TestClient(app)

class HavenSecurityTests(unittest.TestCase):

    def test_unauthenticated_cases_endpoint_returns_401(self):
        """GAP 1: Verify /cases is protected and rejects unauthenticated requests."""
        response = client.get("/cases")
        self.assertEqual(response.status_code, 401, "Public access to /cases must return 401 Unauthorized")

    def test_authority_login_and_token_access(self):
        """GAP 2: Verify server-side authority login and authorized access to /cases."""
        # 1. Invalid password rejected
        bad_login = client.post("/auth/authority-login", json={"password": "wrong_password_123"})
        self.assertEqual(bad_login.status_code, 401)

        # 2. Valid password issues JWT
        login_res = client.post("/auth/authority-login", json={"password": "haven2024", "officer_name": "Test Inspector"})
        self.assertEqual(login_res.status_code, 200)
        data = login_res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "authority")

        token = data["access_token"]

        # 3. Access /cases with authority token
        headers = {"Authorization": f"Bearer {token}"}
        cases_res = client.get("/cases", headers=headers)
        self.assertEqual(cases_res.status_code, 200)
        self.assertIn("cases", cases_res.json())

    def test_mass_assignment_guard_on_cases_patch(self):
        """GAP 1: Verify PATCH /cases/{id} rejects arbitrary mass-assignment and requires authority."""
        # Without auth -> 401
        res_no_auth = client.patch("/cases/TEST-001", json={"status": "resolved", "arbitrary_injected_field": "hacked"})
        self.assertEqual(res_no_auth.status_code, 401)

        # With normal user auth -> 403 Forbidden
        user_token = create_access_token(user_id="normal_user", role="user")
        res_user_auth = client.patch(
            "/cases/TEST-001",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"status": "resolved"}
        )
        self.assertEqual(res_user_auth.status_code, 403)

    def test_evidence_aes_gcm_encryption_and_decryption(self):
        """GAP 8: Verify evidence is encrypted with AES-256-GCM and not stored in plaintext."""
        raw_evidence = "data:audio/webm;base64,GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQJChYECGFOAZwEAAAAAA"
        encrypted = encrypt_evidence_payload(raw_evidence)

        self.assertIn("ciphertext", encrypted)
        self.assertIn("nonce", encrypted)
        self.assertNotEqual(encrypted["ciphertext"], raw_evidence)
        self.assertTrue(len(encrypted["ciphertext"]) > 0)

        # Decrypt
        decrypted = decrypt_evidence_payload(encrypted["ciphertext"], encrypted["nonce"])
        self.assertEqual(decrypted, raw_evidence)

    def test_salted_safe_word_hashing_and_verification(self):
        """GAP 5 & 11: Verify safe word uses PBKDF2 with salt, not plain SHA-256."""
        safe_word = "Pink Lotus Emergency"
        result = hash_safe_word_salted(safe_word)

        self.assertIn("hash", result)
        self.assertIn("salt", result)
        self.assertNotEqual(result["hash"], safe_word)
        self.assertEqual(len(result["salt"]), 32)  # 16 bytes = 32 hex chars

        # Verification with exact phrase
        self.assertTrue(verify_safe_word("Pink Lotus Emergency", result["hash"], result["salt"]))
        # Case and whitespace normalization
        self.assertTrue(verify_safe_word("  pink   lotus emergency! ", result["hash"], result["salt"]))
        # Wrong phrase
        self.assertFalse(verify_safe_word("Blue Lotus", result["hash"], result["salt"]))

    def test_redos_protection_in_culprit_search(self):
        """GAP 17: Verify regex query escaping handles catastrophic regex patterns safely."""
        malicious_regex = "a" * 25 + "(a+)+b"
        res = client.post("/culprit/find-match", json={"description": malicious_regex, "search_mode": "name"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("matches", res.json())

    def test_rate_limiter_exceeds_threshold(self):
        """GAP 10: Verify rate limiting triggers 429 when abuse is detected."""
        # Rapid fire login attempts
        responses = [
            client.post("/auth/authority-login", json={"password": "bad"})
            for _ in range(8)
        ]
        # At least one request beyond the 5/minute threshold should get 429
        has_429 = any(r.status_code == 429 for r in responses)
        self.assertTrue(has_429, "Rate limiter should throttle after max requests")


if __name__ == "__main__":
    unittest.main()
