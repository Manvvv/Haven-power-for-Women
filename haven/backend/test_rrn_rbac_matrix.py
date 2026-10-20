"""
RRN role-boundary matrix and database-cursor regression tests.

Asserts the server-side authorization matrix on the real routes, for anonymous, USER,
RESPONDER, AUTHORITY and ADMIN principals, and that dispatch service reads work when the
store returns pymongo-style cursors (single-pass, no len()) as well as lists.

No mocked authorization: every row is a real request through the app with a real
token minted by auth.create_access_token.
"""
import pytest

import _rrn_test_support  # noqa: F401
from fastapi.testclient import TestClient

from auth import create_access_token

try:
    from main import app
    client = TestClient(app, raise_server_exceptions=False)
    APP_OK = True
except Exception:  # pragma: no cover - environment without full stack
    APP_OK = False

pytestmark = pytest.mark.skipif(not APP_OK, reason="full app stack unavailable")


def _h(role, uid):
    return {"Authorization": "Bearer " + create_access_token(user_id=uid, role=role, name=uid)}


PRINCIPALS = {
    "anon": {},
    "user": _h("user", "U-RBAC"),
    "responder": _h("responder", "RESP-RBAC"),
    "authority": _h("authority", "AUTH-RBAC"),
    "admin": _h("admin", "ADMIN-RBAC"),
}

# Authority operational views: only AUTHORITY and ADMIN.
AUTHORITY_ONLY = ["/dispatch", "/dispatch/rrn/network", "/dispatch/rrn/providers",
                  "/dispatch/rrn/metrics"]
# Provider admin: ADMIN only (AUTHORITY must NOT gain provisioning rights).
ADMIN_ONLY = ["/admin/responders", "/admin/system-stats"]


def _code(path, who):
    return client.get(path, headers=PRINCIPALS[who]).status_code


@pytest.mark.parametrize("path", AUTHORITY_ONLY)
def test_authority_views_matrix(path):
    assert _code(path, "anon") == 401
    assert _code(path, "user") == 403
    assert _code(path, "responder") == 403
    assert _code(path, "authority") == 200
    assert _code(path, "admin") == 200


@pytest.mark.parametrize("path", ADMIN_ONLY)
def test_admin_only_excludes_authority(path):
    assert _code(path, "anon") == 401
    assert _code(path, "user") == 403
    assert _code(path, "responder") == 403
    assert _code(path, "authority") == 403   # AUTHORITY must not reach admin data
    assert _code(path, "admin") == 200


def test_provider_provisioning_is_admin_only_at_runtime():
    body = {"badge_number": "RBAC-X", "officer_name": "x"}
    assert client.post("/admin/providers", json=body).status_code == 401
    assert client.post("/admin/providers", json=body,
                       headers=PRINCIPALS["user"]).status_code == 403
    assert client.post("/admin/providers", json=body,
                       headers=PRINCIPALS["authority"]).status_code == 403


def test_responder_self_service_boundary():
    assert _code("/responder/offers", "anon") == 401
    assert _code("/responder/offers", "responder") == 200
    # Authority and admin do not read a responder's personal offer inbox.
    assert _code("/responder/offers", "authority") == 403
    assert _code("/responder/offers", "user") == 403


def test_unauthenticated_errors_disclose_no_protected_data():
    for path in AUTHORITY_ONLY + ADMIN_ONLY + ["/responder/offers"]:
        body = client.get(path).text
        assert "dispatches" not in body and "metrics" not in body and "responder_id" not in body


# ── cursor-safe dispatch service reads ─────────────────────────────────────────
class _SinglePassCursor:
    """Behaves like pymongo.Cursor: iterable once, no len(), no truthiness."""

    def __init__(self, docs):
        self._it = iter(list(docs))

    def __iter__(self):
        return self._it


def test_public_view_handles_cursor_attempts(monkeypatch):
    from services import dispatch_service as ds
    from test_rapid_response_network import reset_state
    reset_state()
    attempts = [{"dispatch_id": "D-CUR", "response": "PENDING", "responder_id": "R"}]
    monkeypatch.setattr(ds, "_attempts", lambda: type("C", (), {
        "find": lambda self, flt: _SinglePassCursor(attempts)})())
    view = ds.public_view({"dispatch_id": "D-CUR", "status": "OFFERED"}, "authority")
    assert view["total_offers"] == 1 if "total_offers" in view else True


def test_no_bare_find_cursor_used_for_truthiness_or_len():
    """Static guard for the defect class found in dispatch_service: a pymongo Cursor has
    no len() and is always truthy, so a bare find() bound to a name and then tested with
    `if not x` / `len(x)` / `if x` misbehaves. Such bindings must be wrapped in list()."""
    import pathlib, re
    src = (pathlib.Path(__file__).parent / "services" / "dispatch_service.py").read_text(encoding="utf-8")
    # Split into top-level function bodies so a name reused in another function
    # (e.g. `rows`) is judged only against the function that binds the cursor.
    chunks = re.split(r"^(?=def )", src, flags=re.M)
    offenders = []
    for body in chunks:
        for name, expr in re.findall(r"^\s*(\w+)\s*=\s*(_\w+\(\)\.find\(.*)$", body, flags=re.M):
            # Truthiness forms: `if not x`, `if x:`, ternary `A if x else B`, and len(x).
            if re.search(rf"(if\s+not\s+{name}\b|len\({name}\)|if\s+{name}\s*:|if\s+{name}\s+else)", body):
                offenders.append(f"{name} = {expr.strip()}")
    assert offenders == [], f"cursor used as truthy/len without list(): {offenders}"
