"""
Haven Voice SOS — Backend Test Suite
Tests Voice SOS configuration, trigger, test mode, trusted contacts, and history endpoints.
"""
import pytest
import hashlib
import re
import time
import secrets
from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect


def normalize_and_hash(word: str) -> str:
    """Replicate the backend's hash_safe_word function for test comparisons."""
    normalized = re.sub(r'[^\w\s]', '', word.lower()).strip()
    normalized = ' '.join(normalized.split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


# ── Import the app ──
try:
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    from main import app, _voice_sos_cooldowns
    client = TestClient(app)
    APP_AVAILABLE = True
except Exception as e:
    print(f"App import failed: {e}")
    APP_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Authenticated-request helpers (P1 security-hardening test fixes)
#
# Voice SOS config, trusted contacts, history, live-location REST, evidence
# upload and the live-tracking WebSocket are ALL authenticated and
# ownership-enforced in production. These helpers mint a REAL Haven JWT via the
# application's own create_access_token (HS256, issuer "haven-backend") — exactly
# the trusted token path the server verifies in decode_token(). Nothing is
# hardcoded except the test's chosen user_id/role: no secret, password, or
# production credential appears here. This lets the tests exercise the true
# production contract (authorized success AND unauthorized rejection) without
# weakening any guard.
# ─────────────────────────────────────────────────────────────────────────────
def _auth_token(user_id: str, role: str = "user") -> str:
    """Mint a real internal Haven access token for a test principal."""
    from auth import create_access_token
    return create_access_token(user_id=user_id, role=role)


def _auth_headers(user_id: str, role: str = "user") -> dict:
    """Authorization header carrying a real internal token for `user_id`."""
    return {"Authorization": f"Bearer {_auth_token(user_id, role)}"}


@pytest.fixture
def auth_headers():
    """Reusable fixture: call auth_headers("alice") / auth_headers("off", "authority")."""
    return _auth_headers


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed (likely missing env)")
class TestVoiceSOSConfig:
    """Tests for Voice SOS configuration endpoints.

    These endpoints require authentication; identity is derived from the verified
    token and a body user_id is NEVER trusted for write targeting. Reads are
    owner-or-authority only. Each test authenticates with a real Haven token.
    """

    def test_save_config(self):
        """POST /voice-sos/config saves config for the AUTHENTICATED user (body user_id ignored)."""
        resp = client.post("/voice-sos/config", json={
            "user_id": "test_user_1",  # ignored by the server; identity is the token
            "enabled": True,
            "safe_word": "I need my blue notebook",
            "cooldown_seconds": 30,
            "contacts": [
                {"name": "Jane Doe", "phone": "+1234567890", "email": "jane@test.com", "priority": 1}
            ]
        }, headers=_auth_headers("test_user_1"))
        # May return 503 if no DB, 200 if DB connected
        assert resp.status_code in [200, 503]
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is True

    def test_save_config_requires_auth(self):
        """Anonymous POST /voice-sos/config must be rejected (no unauthenticated writes)."""
        resp = client.post("/voice-sos/config", json={
            "user_id": "test_user_1", "enabled": True,
            "safe_word": "I need my blue notebook", "cooldown_seconds": 30, "contacts": []
        })
        assert resp.status_code == 401

    def test_get_config_unconfigured(self):
        """GET /voice-sos/config/{user_id} returns configured=False for unknown (owner) users."""
        uid = "nonexistent_user_xyz"
        resp = client.get(f"/voice-sos/config/{uid}", headers=_auth_headers(uid))
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False

    def test_get_config_requires_auth(self):
        """Anonymous GET of a config is rejected."""
        resp = client.get("/voice-sos/config/test_user_1")
        assert resp.status_code == 401

    def test_get_config_other_user_forbidden(self):
        """A plain user cannot read another user's config (IDOR/ownership protection)."""
        resp = client.get("/voice-sos/config/victim_user", headers=_auth_headers("attacker_user"))
        assert resp.status_code == 403

    def test_config_never_returns_hash(self):
        """GET /voice-sos/config must never return safe_word_hash or salt."""
        uid = "test_user_1"
        resp = client.get(f"/voice-sos/config/{uid}", headers=_auth_headers(uid))
        assert resp.status_code == 200
        data = resp.json()
        assert "safe_word_hash" not in data
        assert "safe_word_salt" not in data


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestSafeWordHashing:
    """Tests for safe word normalization and hashing."""

    def test_hash_deterministic(self):
        """Same input should always produce the same hash."""
        h1 = normalize_and_hash("I need my blue notebook")
        h2 = normalize_and_hash("I need my blue notebook")
        assert h1 == h2

    def test_hash_case_insensitive(self):
        """Hashing should be case-insensitive."""
        h1 = normalize_and_hash("I Need My Blue Notebook")
        h2 = normalize_and_hash("i need my blue notebook")
        assert h1 == h2

    def test_hash_strips_punctuation(self):
        """Hashing should strip punctuation."""
        h1 = normalize_and_hash("I need my blue notebook.")
        h2 = normalize_and_hash("I need my blue notebook")
        assert h1 == h2

    def test_hash_collapses_whitespace(self):
        """Hashing should collapse multiple spaces."""
        h1 = normalize_and_hash("I  need   my    blue notebook")
        h2 = normalize_and_hash("I need my blue notebook")
        assert h1 == h2

    def test_different_words_different_hash(self):
        """Different safe words should produce different hashes."""
        h1 = normalize_and_hash("I need my blue notebook")
        h2 = normalize_and_hash("call the police now")
        assert h1 != h2


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestVoiceSOSTrigger:
    """Tests for Voice SOS trigger and test endpoints."""

    def test_trigger_unconfigured_user(self):
        """POST /voice-sos/trigger should return 404 for unconfigured users."""
        resp = client.post("/voice-sos/trigger", json={
            "user_id": "no_such_user",
            "hashed_safe_word": "fake_hash",
            "latitude": 0.0,
            "longitude": 0.0,
            "location_accuracy": 0.0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        assert resp.status_code in [404, 503]

    def test_trigger_wrong_hash(self):
        """POST /voice-sos/trigger should return 403 for wrong safe word."""
        # First configure. Config creation now requires auth (post-hardening),
        # and the stored identity is the TOKEN's user_id — so authenticate AS
        # "test_trigger_user" to create the row under that id. The trigger below
        # is intentionally anonymous (get_optional_user) and resolves the config
        # via the body user_id, so it still finds this config on a clean DB.
        client.post("/voice-sos/config", json={
            "user_id": "test_trigger_user",
            "enabled": True,
            "safe_word": "help me now",
            "cooldown_seconds": 5,
            "contacts": []
        }, headers=_auth_headers("test_trigger_user"))
        # Try wrong hash
        resp = client.post("/voice-sos/trigger", json={
            "user_id": "test_trigger_user",
            "hashed_safe_word": "wrong_hash_value",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "location_accuracy": 10.0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        assert resp.status_code in [403, 503]

    def test_test_mode_no_real_case(self):
        """POST /voice-sos/test should validate but not create a real case."""
        resp = client.post("/voice-sos/test", json={
            "user_id": "test_trigger_user",
            "hashed_safe_word": normalize_and_hash("help me now"),
            "latitude": 28.6139,
            "longitude": 77.2090,
            "location_accuracy": 10.0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        if resp.status_code == 200:
            data = resp.json()
            assert data["is_test"] is True
            assert "TEST" in data["event_id"]

    def test_cooldown_enforcement(self):
        """POST /voice-sos/trigger should enforce cooldown period."""
        # Clear cooldown
        _voice_sos_cooldowns.pop("test_trigger_user", None)

        correct_hash = normalize_and_hash("help me now")

        # First trigger
        resp1 = client.post("/voice-sos/trigger", json={
            "user_id": "test_trigger_user",
            "hashed_safe_word": correct_hash,
            "latitude": 28.6139,
            "longitude": 77.2090,
            "timestamp": "2024-01-01T00:00:00Z"
        })

        if resp1.status_code == 200:
            # Immediate second trigger should hit cooldown
            resp2 = client.post("/voice-sos/trigger", json={
                "user_id": "test_trigger_user",
                "hashed_safe_word": correct_hash,
                "latitude": 28.6139,
                "longitude": 77.2090,
                "timestamp": "2024-01-01T00:00:01Z"
            })
            assert resp2.status_code == 429

    def test_trigger_reports_honest_dispatch_flags(self):
        """A successful trigger must NOT fabricate emergency action.

        The server prepares WhatsApp deep links the user opens; it does not
        auto-notify contacts or auto-dispatch ERSS-112. So the response must
        report erss_auto_dispatched == False and contacts_notified == 0
        (with the real count surfaced as contacts_pending). Regression guard
        for the previous hardcoded `erss_auto_dispatched: True` / notified count.
        """
        _voice_sos_cooldowns.pop("honest_flags_user", None)
        client.post("/voice-sos/config", json={
            "user_id": "honest_flags_user", "enabled": True,
            "safe_word": "open the window", "cooldown_seconds": 5, "contacts": [],
        }, headers=_auth_headers("honest_flags_user"))
        resp = client.post("/voice-sos/trigger", json={
            "user_id": "honest_flags_user",
            "hashed_safe_word": normalize_and_hash("open the window"),
            "latitude": 28.6139, "longitude": 77.2090,
            "timestamp": "2026-01-01T00:00:00Z",
        })
        if resp.status_code != 200:
            return  # no DB / cooldown / config unavailable — nothing to assert
        data = resp.json()
        assert data["erss_auto_dispatched"] is False
        assert data["contacts_notified"] == 0
        assert "contacts_pending" in data


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestTrustedContacts:
    """Tests for trusted contacts endpoints.

    Writes derive the owner from the token (a body user_id is ignored). Reads are
    owner-or-authority only. Tests authenticate with a real Haven token.
    """

    def test_save_contacts(self):
        """POST /trusted-contacts saves contacts for the authenticated user."""
        resp = client.post("/trusted-contacts", json={
            "user_id": "test_contacts_user",  # ignored; identity is the token
            "contacts": [
                {"name": "Mom", "phone": "+1111111111", "priority": 1},
                {"name": "Friend", "phone": "+2222222222", "email": "friend@test.com", "priority": 2},
            ]
        }, headers=_auth_headers("test_contacts_user"))
        assert resp.status_code in [200, 503]
        if resp.status_code == 200:
            data = resp.json()
            assert data["contacts_saved"] == 2

    def test_save_contacts_requires_auth(self):
        """Anonymous POST /trusted-contacts must be rejected."""
        resp = client.post("/trusted-contacts", json={
            "contacts": [{"name": "Mom", "phone": "+1111111111", "priority": 1}]
        })
        assert resp.status_code == 401

    def test_max_contacts_limit(self):
        """POST /trusted-contacts rejects more than 5 contacts (400) once authenticated."""
        resp = client.post("/trusted-contacts", json={
            "contacts": [{"name": f"C{i}", "phone": f"+{i}000000"} for i in range(6)]
        }, headers=_auth_headers("test_contacts_user"))
        assert resp.status_code in [400, 503]

    def test_get_contacts(self):
        """GET /trusted-contacts/{user_id} returns the owner's saved contacts."""
        uid = "test_contacts_user"
        resp = client.get(f"/trusted-contacts/{uid}", headers=_auth_headers(uid))
        assert resp.status_code == 200
        data = resp.json()
        assert "contacts" in data

    def test_get_contacts_other_user_forbidden(self):
        """A plain user cannot read another user's contacts (IDOR/ownership protection)."""
        resp = client.get("/trusted-contacts/victim_user", headers=_auth_headers("attacker_user"))
        assert resp.status_code == 403

    def test_missing_user_id(self):
        """Identity comes from the token, not the body — the old 'missing user_id -> 400'
        contract no longer exists.

        After the security hardening the endpoint derives the owner from the
        verified token and ignores any body user_id. So an AUTHENTICATED request
        with no body user_id succeeds (200/503), while an ANONYMOUS request (the
        only case with no derivable identity) is rejected with 401.
        """
        # Authenticated, no body user_id -> accepted (identity from token).
        resp = client.post("/trusted-contacts", json={
            "contacts": [{"name": "Test", "phone": "+111"}]
        }, headers=_auth_headers("token_identity_user"))
        assert resp.status_code in [200, 503]
        # Anonymous, no identity anywhere -> rejected.
        anon = client.post("/trusted-contacts", json={
            "contacts": [{"name": "Test", "phone": "+111"}]
        })
        assert anon.status_code == 401


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestVoiceSOSHistory:
    """Tests for Voice SOS history endpoint (owner-or-authority only)."""

    def test_get_history_empty(self):
        """GET /voice-sos/history/{user_id} returns empty for a new (owner) user."""
        uid = "brand_new_user"
        resp = client.get(f"/voice-sos/history/{uid}", headers=_auth_headers(uid))
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data

    def test_get_history_requires_auth(self):
        """Anonymous history read is rejected."""
        resp = client.get("/voice-sos/history/brand_new_user")
        assert resp.status_code == 401

    def test_get_history_other_user_forbidden(self):
        """A plain user cannot read another user's history (IDOR/ownership protection)."""
        resp = client.get("/voice-sos/history/victim_user", headers=_auth_headers("attacker_user"))
        assert resp.status_code == 403


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestVoiceSOSAnalytics:
    """Tests for Voice SOS analytics endpoint."""

    def test_analytics_endpoint(self):
        """GET /voice-sos/analytics should return aggregated data."""
        from auth import create_access_token
        token = create_access_token(user_id="test_officer", role="authority")
        resp = client.get("/voice-sos/analytics", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_activations" in data
        assert "test_activations" in data


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestExistingEndpoints:
    """Verify existing endpoints still work after Voice SOS changes."""

    def test_root(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Haven" in resp.json().get("message", "")

    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_cases_endpoint(self):
        from auth import create_access_token
        token = create_access_token(user_id="test_officer", role="authority")
        resp = client.get("/cases", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestLiveTrackingEndpoints:
    """Tests for real-time location streaming and WebSocket tracking.

    Both the REST location update and the WebSocket room are authenticated and
    ownership-enforced: only the event's owner (or an authority/admin) may push
    or observe a victim's live GPS. Tests seed an owned event when a real DB is
    present, and otherwise assert the documented no-DB behavior.
    """

    def test_location_update_rest(self):
        """POST /sos/location-update accepts live GPS for the event OWNER."""
        from services.db import sos_events
        owner = "track_owner_1"
        event_id = "TEST-EVT-101"
        body = {
            "event_id": event_id, "latitude": 19.0760, "longitude": 72.8777,
            "accuracy": 4.5, "speed": 12.0, "heading": 90.0,
            "timestamp": "2026-08-15T14:30:00Z",
        }
        coll = sos_events()
        if coll is None:
            # No DB configured: the endpoint enforces auth first, then reports 503.
            resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
            assert resp.status_code == 503
            return
        # Seed an event owned by the authenticated user (idempotent upsert).
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["event_id"] == event_id

    def test_location_update_requires_auth(self):
        """Anonymous location update is rejected (401), never silently accepted."""
        resp = client.post("/sos/location-update", json={
            "event_id": "TEST-EVT-101", "latitude": 19.0760, "longitude": 72.8777,
        })
        assert resp.status_code == 401

    def test_location_update_wrong_user_forbidden(self):
        """A non-owner plain user cannot push location to another user's event (403)."""
        from services.db import sos_events
        coll = sos_events()
        if coll is None:
            return  # ownership branch unreachable without a DB (503 covered above)
        event_id = "TEST-EVT-102"
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": "real_owner"}}, upsert=True)
        resp = client.post("/sos/location-update", json={
            "event_id": event_id, "latitude": 1.0, "longitude": 2.0,
        }, headers=_auth_headers("attacker_user"))
        assert resp.status_code == 403

    def test_location_update_persists_and_echoes_supplied_fields(self):
        """Supplied accuracy/speed/heading are stored + echoed (honest precision)."""
        from services.db import sos_events
        coll = sos_events()
        owner = "track_owner_fields"
        event_id = "TEST-EVT-FIELDS"
        body = {"event_id": event_id, "latitude": 19.07, "longitude": 72.87,
                "accuracy": 4.5, "speed": 12.0, "heading": 90.0}
        if coll is None:
            assert client.post("/sos/location-update", json=body,
                               headers=_auth_headers(owner)).status_code == 503
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 200
        data = resp.json()
        assert data["accuracy"] == 4.5 and data["speed"] == 12.0 and data["heading"] == 90.0

    def test_location_update_omits_unsupplied_accuracy(self):
        """Missing accuracy is NEVER fabricated — response omits the field."""
        from services.db import sos_events
        coll = sos_events()
        owner = "track_owner_nofab"
        event_id = "TEST-EVT-NOFAB"
        body = {"event_id": event_id, "latitude": 19.07, "longitude": 72.87}  # no accuracy
        if coll is None:
            assert client.post("/sos/location-update", json=body,
                               headers=_auth_headers(owner)).status_code == 503
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 200
        assert "accuracy" not in resp.json()  # no fabricated 5.0 default

    def test_location_update_rejects_invalid_coordinates(self):
        """Out-of-range latitude is rejected with 422 (never stored/broadcast)."""
        from services.db import sos_events
        coll = sos_events()
        owner = "track_owner_bad"
        event_id = "TEST-EVT-BAD"
        body = {"event_id": event_id, "latitude": 999.0, "longitude": 72.87}
        if coll is None:
            assert client.post("/sos/location-update", json=body,
                               headers=_auth_headers(owner)).status_code == 503
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 422

    def test_location_update_rejected_when_resolved(self):
        """A RESOLVED case stops live tracking: the update is rejected with 409."""
        from services.db import sos_events, sos_cases
        events_coll = sos_events()
        cases_coll = sos_cases()
        owner = "track_owner_resolved"
        event_id = "TEST-EVT-RESOLVED"
        body = {"event_id": event_id, "latitude": 19.07, "longitude": 72.87}
        if events_coll is None or cases_coll is None:
            assert client.post("/sos/location-update", json=body,
                               headers=_auth_headers(owner)).status_code == 503
            return
        events_coll.update_one({"event_id": event_id},
                               {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        cases_coll.update_one({"case_id": event_id},
                              {"$set": {"case_id": event_id, "user_id": owner, "status": "RESOLVED"}}, upsert=True)
        resp = client.post("/sos/location-update", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 409

    def test_websocket_tracking_room(self):
        """WebSocket /ws/track/{event_id}: the event OWNER connects (with a token) and
        receives the coordinates they broadcast."""
        from services.db import sos_events
        from main import tracking_manager
        owner = "ws_owner_1"
        event_id = "TEST-EVT-ROOM"
        token = _auth_token(owner)
        coll = sos_events()
        if coll is None:
            # No DB: the room cannot authorize the event -> connection rejected.
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/ws/track/{event_id}?token={token}"):
                    pass
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        # Clear any stale in-memory location so we receive the coords we send.
        tracking_manager.latest_locations.pop(event_id, None)
        with client.websocket_connect(f"/ws/track/{event_id}?token={token}") as ws:
            ws.send_json({"latitude": 28.6139, "longitude": 77.2090, "accuracy": 3.0})
            received = ws.receive_json()
            assert received["event_id"] == event_id
            assert received["latitude"] == 28.6139
            assert received["longitude"] == 77.2090

    def test_websocket_omits_unsupplied_telemetry(self):
        """WS broadcast never fabricates telemetry: a fix without accuracy/speed/
        heading is relayed with those keys absent (no accuracy=5.0 default)."""
        from services.db import sos_events
        from main import tracking_manager
        owner = "ws_owner_nofab"
        event_id = "TEST-EVT-WS-NOFAB"
        token = _auth_token(owner)
        coll = sos_events()
        if coll is None:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/ws/track/{event_id}?token={token}"):
                    pass
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        tracking_manager.latest_locations.pop(event_id, None)
        with client.websocket_connect(f"/ws/track/{event_id}?token={token}") as ws:
            ws.send_json({"latitude": 28.6139, "longitude": 77.2090})  # no telemetry
            received = ws.receive_json()
            assert received["latitude"] == 28.6139
            assert "accuracy" not in received
            assert "speed" not in received and "heading" not in received

    def test_websocket_skips_invalid_coordinates(self):
        """An out-of-range/NaN fix is skipped: no fabricated 0,0 'null island' is
        broadcast. A subsequent VALID fix is what the subscriber receives."""
        from services.db import sos_events
        from main import tracking_manager
        owner = "ws_owner_badcoord"
        event_id = "TEST-EVT-WS-BAD"
        token = _auth_token(owner)
        coll = sos_events()
        if coll is None:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/ws/track/{event_id}?token={token}"):
                    pass
            return
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": owner}}, upsert=True)
        tracking_manager.latest_locations.pop(event_id, None)
        with client.websocket_connect(f"/ws/track/{event_id}?token={token}") as ws:
            ws.send_json({"latitude": 999.0, "longitude": 77.2090})  # invalid -> skipped
            ws.send_json({"latitude": 28.61, "longitude": 77.20})    # valid -> delivered
            received = ws.receive_json()
            assert received["latitude"] == 28.61  # first (bad) fix was never broadcast

    def test_websocket_requires_token(self):
        """WS without a token is rejected (closed before accept, never subscribed)."""
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/track/TEST-EVT-ROOM"):
                pass

    def test_websocket_wrong_user_rejected(self):
        """An authenticated NON-owner (plain user) is rejected from another user's room."""
        from services.db import sos_events
        coll = sos_events()
        if coll is None:
            return  # ownership branch unreachable without a DB
        event_id = "TEST-EVT-ROOM2"
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": "real_owner"}}, upsert=True)
        token = _auth_token("attacker_user")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/track/{event_id}?token={token}"):
                pass

    def test_websocket_authority_can_observe(self):
        """An authority/admin may SUBSCRIBE read-only (connection accepted, no error)."""
        from services.db import sos_events
        coll = sos_events()
        if coll is None:
            return  # authorization requires the event store
        event_id = "TEST-EVT-ROOM3"
        coll.update_one({"event_id": event_id},
                        {"$set": {"event_id": event_id, "user_id": "some_owner"}}, upsert=True)
        token = _auth_token("officer_1", role="authority")
        # Entering the context without WebSocketDisconnect proves the observer was
        # accepted. Observers are read-only; we do not broadcast here.
        with client.websocket_connect(f"/ws/track/{event_id}?token={token}"):
            pass


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestERSSDispatchEndpoints:
    """Tests for ERSS 112 and NGO emergency dispatch gateways."""

    def test_get_dispatch_partners(self):
        """GET /authority/dispatch-partners should return active emergency partners."""
        from auth import create_access_token
        token = create_access_token(user_id="test_officer", role="authority")
        resp = client.get("/authority/dispatch-partners", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "partners" in data
        assert len(data["partners"]) >= 3
        partner_ids = [p["id"] for p in data["partners"]]
        assert "ERSS-112-NAT" in partner_ids

    def test_trigger_dispatch_webhook(self):
        """POST /authority/dispatch-webhook should return dispatch confirmation."""
        from auth import create_access_token
        token = create_access_token(user_id="test_officer", role="authority")
        resp = client.post("/authority/dispatch-webhook", json={
            "case_id": "VSOS-TEST-CASE-999",
            "agency_type": "ERSS_112",
            "priority": "CRITICAL",
            "dispatcher_notes": "Automated priority dispatch test"
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "DISPATCH_CONFIRMED"
        assert "dispatch_id" in data
        assert data["estimated_arrival_minutes"] == 6


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestEvidenceUploadEndpoint:
    """Tests for forensic evidence upload endpoint.

    Authenticated + ownership-enforced: evidence can only be attached to a case
    the caller owns (or as an authority/admin). Tests seed an owned case when a
    real DB is present, and otherwise assert the documented no-DB behavior.
    """

    _EVIDENCE_BODY = {
        "audio_base64": "GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQRChYECGFOAZwE=",
        "image_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/",
        "mime_type_audio": "audio/webm", "mime_type_image": "image/jpeg",
        "duration_seconds": 6.0, "device_info": "Chrome/Android Mobile",
        "timestamp": "2026-08-15T18:00:00Z",
    }

    def test_upload_evidence(self):
        """POST /sos/evidence stores an AES-256-GCM-sealed record for the case OWNER."""
        from services.db import sos_cases
        owner = "evidence_owner_1"
        case_id = "VSOS-TEST-CASE-999"
        body = {"case_id": case_id, **self._EVIDENCE_BODY}
        coll = sos_cases()
        if coll is None:
            resp = client.post("/sos/evidence", json=body, headers=_auth_headers(owner))
            assert resp.status_code == 503
            return
        coll.update_one({"case_id": case_id},
                        {"$set": {"case_id": case_id, "user_id": owner}}, upsert=True)
        resp = client.post("/sos/evidence", json=body, headers=_auth_headers(owner))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "evidence_hash" in data
        assert len(data["evidence_hash"]) == 64  # SHA-256 length

    def test_upload_evidence_requires_auth(self):
        """Anonymous evidence upload is rejected (401)."""
        resp = client.post("/sos/evidence", json={
            "case_id": "VSOS-TEST-CASE-999", **self._EVIDENCE_BODY
        })
        assert resp.status_code == 401

    def test_upload_evidence_wrong_user_forbidden(self):
        """A non-owner cannot attach evidence to another user's case (403)."""
        from services.db import sos_cases
        coll = sos_cases()
        if coll is None:
            return
        case_id = "VSOS-TEST-CASE-998"
        coll.update_one({"case_id": case_id},
                        {"$set": {"case_id": case_id, "user_id": "real_owner"}}, upsert=True)
        resp = client.post("/sos/evidence", json={
            "case_id": case_id, **self._EVIDENCE_BODY
        }, headers=_auth_headers("attacker_user"))
        assert resp.status_code == 403


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestSaveExtractedData:
    """/save-extracted-data — the covert/anonymous stego + offline SOS ingest.

    Product contract (spec §2): this endpoint is INTENTIONALLY anonymous (a woman
    in distress is not signed in during the covert flow), so it stays open but is
    hardened — rate-limited, size-limited, idempotent — and, critically, it NEVER
    reports success unless the write actually happened (DB down -> 503 so the
    offline-first client keeps the alert queued and retries).
    """

    def test_save_is_anonymous_never_401(self):
        """The covert ingest must NOT require auth: no request is answered with 401."""
        resp = client.post("/save-extracted-data", json={
            "decoded_text": "help me", "severity": "high",
        })
        assert resp.status_code != 401

    def test_save_success_or_honest_503(self):
        """With a DB it returns success+case_id; with no DB it returns 503 (never a
        fabricated success)."""
        from services.db import sos_cases
        resp = client.post("/save-extracted-data", json={
            "decoded_text": "trapped near market", "severity": "high",
        })
        if sos_cases() is None:
            assert resp.status_code == 503
            # A 503 body must NOT claim the save succeeded.
            assert resp.json().get("success") is not True
        else:
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True and data["case_id"]

    def test_save_is_idempotent(self):
        """A retried submission with the same idempotency_key returns the ORIGINAL
        case (no duplicate row)."""
        from services.db import sos_cases
        key = f"idem-{secrets.token_hex(6)}"
        body = {"decoded_text": "same alert", "severity": "medium", "idempotency_key": key}
        first = client.post("/save-extracted-data", json=body)
        if sos_cases() is None:
            assert first.status_code == 503
            return
        second = client.post("/save-extracted-data", json=body)
        assert first.status_code == 200 and second.status_code == 200
        assert second.json()["case_id"] == first.json()["case_id"]
        assert second.json().get("duplicate") is True

    def test_save_rejects_oversized_text(self):
        """decoded_text beyond the ceiling is rejected (422) before any persistence."""
        from services.db import sos_cases
        resp = client.post("/save-extracted-data", json={
            "decoded_text": "x" * 10_001,  # > MAX_SAVE_TEXT_CHARS (10_000)
        })
        if sos_cases() is None:
            # DB-unavailable is checked first -> 503; the size guard is covered when a DB exists.
            assert resp.status_code in (422, 503)
        else:
            assert resp.status_code == 422

    def test_save_rejects_non_string_text(self):
        """A non-string decoded_text is a controlled 400 (no stack/DB leak)."""
        from services.db import sos_cases
        resp = client.post("/save-extracted-data", json={"decoded_text": 12345})
        if sos_cases() is None:
            assert resp.status_code in (400, 503)
        else:
            assert resp.status_code == 400
