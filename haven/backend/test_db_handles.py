"""
Regression tests: collection handles must follow the CURRENT database connection.

Background: services/db.py used to expose module-level collection constants computed
once at import time. If the database was unavailable at import, those constants stayed
None for the life of the process, so every later request returned 503 even after the
database came back. The live accessors (get_collection / _live in voice_routes) must
re-resolve on every call.

These tests use the get_db() seam to simulate outage and recovery. They do not mock
any endpoint outcome.
"""
import pytest

import services.db as dbmod


class _FakeDB(dict):
    """Minimal stand-in for a pymongo Database: item access returns a named marker."""

    def __getitem__(self, name):
        return ("collection", name)


@pytest.fixture
def db_state(monkeypatch):
    """Let each test choose what get_db() returns, without touching real Mongo."""
    state = {"db": None}
    monkeypatch.setattr(dbmod, "get_db", lambda: state["db"])
    return state


def test_accessor_is_none_while_database_unavailable(db_state):
    db_state["db"] = None
    assert dbmod.get_collection("trusted_contacts") is None


def test_accessor_recovers_when_database_becomes_available(db_state):
    # Outage first, then recovery: the SAME accessor call must now resolve.
    db_state["db"] = None
    assert dbmod.get_collection("trusted_contacts") is None
    db_state["db"] = _FakeDB()
    assert dbmod.get_collection("trusted_contacts") == ("collection", "trusted_contacts")


def test_voice_routes_live_handle_recovers(db_state, monkeypatch):
    """voice_routes resolves collections per use via _live(); it must not freeze None."""
    pytest.importorskip("fastapi")
    from routers import voice_routes as vr

    monkeypatch.setattr(vr, "get_collection", dbmod.get_collection)
    db_state["db"] = None
    assert vr._live("sos_events") is None
    db_state["db"] = _FakeDB()
    assert vr._live("sos_events") == ("collection", "sos_events")


def test_no_import_time_collection_constants_remain_in_voice_routes():
    """Guard against reintroducing stale import-time handles in the voice router."""
    import pathlib
    src = (pathlib.Path(__file__).parent / "routers" / "voice_routes.py").read_text(encoding="utf-8")
    for stale in ("voice_sos_config_collection", "trusted_contacts_collection",
                  "sos_events_collection", "sos_collection"):
        assert stale not in src, f"stale import-time handle reintroduced: {stale}"
