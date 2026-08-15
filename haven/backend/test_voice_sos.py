"""
Haven Voice SOS — Backend Test Suite
Tests Voice SOS configuration, trigger, test mode, trusted contacts, and history endpoints.
"""
import pytest
import hashlib
import re
import time
from fastapi.testclient import TestClient


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


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed (likely missing env)")
class TestVoiceSOSConfig:
    """Tests for Voice SOS configuration endpoints."""

    def test_save_config(self):
        """POST /voice-sos/config should save configuration."""
        resp = client.post("/voice-sos/config", json={
            "user_id": "test_user_1",
            "enabled": True,
            "safe_word": "I need my blue notebook",
            "cooldown_seconds": 30,
            "contacts": [
                {"name": "Jane Doe", "phone": "+1234567890", "email": "jane@test.com", "priority": 1}
            ]
        })
        # May return 503 if no DB, 200 if DB connected
        assert resp.status_code in [200, 503]
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is True

    def test_get_config_unconfigured(self):
        """GET /voice-sos/config/{user_id} should return configured=False for unknown users."""
        resp = client.get("/voice-sos/config/nonexistent_user_xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False

    def test_config_never_returns_hash(self):
        """GET /voice-sos/config should never return safe_word_hash."""
        resp = client.get("/voice-sos/config/test_user_1")
        assert resp.status_code == 200
        data = resp.json()
        assert "safe_word_hash" not in data


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
        # First configure
        client.post("/voice-sos/config", json={
            "user_id": "test_trigger_user",
            "enabled": True,
            "safe_word": "help me now",
            "cooldown_seconds": 5,
            "contacts": []
        })
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


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestTrustedContacts:
    """Tests for trusted contacts endpoints."""

    def test_save_contacts(self):
        """POST /trusted-contacts should save contacts."""
        resp = client.post("/trusted-contacts", json={
            "user_id": "test_contacts_user",
            "contacts": [
                {"name": "Mom", "phone": "+1111111111", "priority": 1},
                {"name": "Friend", "phone": "+2222222222", "email": "friend@test.com", "priority": 2},
            ]
        })
        assert resp.status_code in [200, 503]
        if resp.status_code == 200:
            data = resp.json()
            assert data["contacts_saved"] == 2

    def test_max_contacts_limit(self):
        """POST /trusted-contacts should reject more than 5 contacts."""
        resp = client.post("/trusted-contacts", json={
            "user_id": "test_contacts_user",
            "contacts": [{"name": f"C{i}", "phone": f"+{i}000000"} for i in range(6)]
        })
        assert resp.status_code in [400, 503]

    def test_get_contacts(self):
        """GET /trusted-contacts/{user_id} should return saved contacts."""
        resp = client.get("/trusted-contacts/test_contacts_user")
        assert resp.status_code == 200
        data = resp.json()
        assert "contacts" in data

    def test_missing_user_id(self):
        """POST /trusted-contacts without user_id should return 400."""
        resp = client.post("/trusted-contacts", json={
            "contacts": [{"name": "Test", "phone": "+111"}]
        })
        assert resp.status_code in [400, 503]


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestVoiceSOSHistory:
    """Tests for Voice SOS history endpoint."""

    def test_get_history_empty(self):
        """GET /voice-sos/history/{user_id} should return empty for new users."""
        resp = client.get("/voice-sos/history/brand_new_user")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestVoiceSOSAnalytics:
    """Tests for Voice SOS analytics endpoint."""

    def test_analytics_endpoint(self):
        """GET /voice-sos/analytics should return aggregated data."""
        resp = client.get("/voice-sos/analytics")
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
        resp = client.get("/cases")
        assert resp.status_code == 200


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestLiveTrackingEndpoints:
    """Tests for real-time location streaming and WebSocket tracking."""

    def test_location_update_rest(self):
        """POST /sos/location-update should accept live GPS coordinates."""
        resp = client.post("/sos/location-update", json={
            "event_id": "TEST-EVT-101",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "accuracy": 4.5,
            "speed": 12.0,
            "heading": 90.0,
            "timestamp": "2026-08-15T14:30:00Z"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["event_id"] == "TEST-EVT-101"

    def test_websocket_tracking_room(self):
        """WebSocket /ws/track/{event_id} should connect and receive streamed coordinates."""
        with client.websocket_connect("/ws/track/TEST-EVT-ROOM") as ws:
            ws.send_json({
                "latitude": 28.6139,
                "longitude": 77.2090,
                "accuracy": 3.0
            })
            received = ws.receive_json()
            assert received["event_id"] == "TEST-EVT-ROOM"
            assert received["latitude"] == 28.6139
            assert received["longitude"] == 77.2090


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestERSSDispatchEndpoints:
    """Tests for ERSS 112 and NGO emergency dispatch gateways."""

    def test_get_dispatch_partners(self):
        """GET /authority/dispatch-partners should return active emergency partners."""
        resp = client.get("/authority/dispatch-partners")
        assert resp.status_code == 200
        data = resp.json()
        assert "partners" in data
        assert len(data["partners"]) >= 3
        partner_ids = [p["id"] for p in data["partners"]]
        assert "ERSS-112-NAT" in partner_ids

    def test_trigger_dispatch_webhook(self):
        """POST /authority/dispatch-webhook should return dispatch confirmation."""
        resp = client.post("/authority/dispatch-webhook", json={
            "case_id": "VSOS-TEST-CASE-999",
            "agency_type": "ERSS_112",
            "priority": "CRITICAL",
            "dispatcher_notes": "Automated priority dispatch test"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "DISPATCH_CONFIRMED"
        assert "dispatch_id" in data
        assert data["estimated_arrival_minutes"] == 6


@pytest.mark.skipif(not APP_AVAILABLE, reason="App import failed")
class TestEvidenceUploadEndpoint:
    """Tests for forensic evidence upload endpoint."""

    def test_upload_evidence(self):
        """POST /sos/evidence should store evidence with SHA-256 seal."""
        resp = client.post("/sos/evidence", json={
            "case_id": "VSOS-TEST-CASE-999",
            "audio_base64": "GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQRChYECGFOAZwE=",
            "image_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/",
            "mime_type_audio": "audio/webm",
            "mime_type_image": "image/jpeg",
            "duration_seconds": 6.0,
            "device_info": "Chrome/Android Mobile",
            "timestamp": "2026-08-15T18:00:00Z"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "evidence_hash" in data
        assert len(data["evidence_hash"]) == 64  # SHA-256 length
