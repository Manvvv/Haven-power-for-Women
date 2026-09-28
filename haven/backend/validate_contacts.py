"""
validate_contacts.py — sandbox-runnable regression guard for the trusted-contacts
add/delete contract (issues #3/#4: "contacts cannot be added / deleted reliably").

Runs with the standard library only (no FastAPI / PyMongo needed), so it works in
CI where the app can't be imported. Two layers:

  A. UNIT — exercises the REAL pure validators in services/contact_validation.py
     (phone/email rules + duplicate-normalization key).
  B. STATIC (AST) — parses routers/voice_routes.py and proves the security-critical
     shape of the endpoints without executing them:
       * POST /trusted-contacts/add and DELETE /trusted-contacts/{contact_id} exist
       * both depend on get_current_user (authenticated)
       * identity comes from current_user.user_id (never a body user_id)
       * the DELETE filter is scoped to BOTH user_id AND contact_id (no cross-user
         delete, no unscoped wipe)
       * add validates name + phone + email and dedups by normalized phone

The full HTTP behaviour matrix (200/400/401/404/409 + persistence) is covered by
test_voice_sos.py::TestPerContactAddDelete, which needs a live app + Mongo.

Run:  python3 validate_contacts.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print("PASS " + name)
    else:
        failed += 1
        print("FAIL " + name)


# ── A) UNIT: the real pure validators ────────────────────────────────────────
from services.contact_validation import (
    MAX_TRUSTED_CONTACTS, normalize_phone, valid_phone, valid_email,
)

check("cap is a sane positive int", isinstance(MAX_TRUSTED_CONTACTS, int) and MAX_TRUSTED_CONTACTS >= 1)

# valid_phone: 10-digit Indian mobile (leading 6-9) OR 11-15 digit intl.
check("accepts 10-digit mobile (leading 9)", valid_phone("9876543210"))
check("accepts 10-digit mobile (leading 6)", valid_phone("6012345678"))
check("accepts spaced 10-digit mobile", valid_phone("98765 43210"))
check("accepts +country-code number", valid_phone("+91 98765 43210"))
check("rejects too-short number", not valid_phone("12345"))
check("rejects 10-digit starting 0-5", not valid_phone("5012345678"))
check("rejects empty phone", not valid_phone(""))
check("rejects letters-only phone", not valid_phone("call-me"))
check("rejects over-long (16 digit) number", not valid_phone("1234567890123456"))

# normalize_phone: duplicate-detection key ignores formatting.
check("normalize strips spaces/plus/dashes",
      normalize_phone("+91 98765-43210") == "919876543210")
check("normalize of two formats of same number matches",
      normalize_phone("98765 43210") == normalize_phone("9876543210"))
check("normalize handles None safely", normalize_phone(None) == "")

# valid_email: optional (empty OK), else must look like an address.
check("empty email is allowed (optional)", valid_email(""))
check("whitespace-only email is allowed (optional)", valid_email("   "))
check("accepts plausible email", valid_email("friend@test.com"))
check("rejects malformed email", not valid_email("not-an-email"))
check("rejects email missing domain dot", not valid_email("a@b"))


# ── B) STATIC (AST): endpoint shape + ownership guarantees ────────────────────
SRC = open(os.path.join(HERE, "routers", "voice_routes.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)


def _funcs(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]


def _route(fn):
    """Return (method, path) for the first @router.<method>('<path>') decorator."""
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"):
            method = d.func.attr
            path = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else None
            return method, path
    return None, None


FUNCS = _funcs(TREE)
ROUTES = {(_route(f)[0], _route(f)[1]): f for f in FUNCS if _route(f)[0]}

add_fn = ROUTES.get(("post", "/trusted-contacts/add"))
del_fn = ROUTES.get(("delete", "/trusted-contacts/{contact_id}"))

check("POST /trusted-contacts/add endpoint exists", add_fn is not None)
check("DELETE /trusted-contacts/{contact_id} endpoint exists", del_fn is not None)


def _depends_on_get_current_user(fn):
    """True if a param default is Depends(get_current_user)."""
    for d in (fn.args.defaults or []):
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends"
                and d.args and isinstance(d.args[0], ast.Name) and d.args[0].id == "get_current_user"):
            return True
    return False


def _src_of(fn):
    return ast.get_source_segment(SRC, fn) or ""


if add_fn:
    add_src = _src_of(add_fn)
    check("add is authenticated via get_current_user", _depends_on_get_current_user(add_fn))
    check("add derives identity from current_user.user_id", "current_user.user_id" in add_src)
    check("add does NOT trust a body user_id/owner_id",
          'body.get("user_id"' not in add_src and 'body.get("owner_id"' not in add_src)
    check("add validates name", "Contact name is required" in add_src)
    check("add validates phone via valid_phone", "valid_phone(" in add_src)
    check("add validates email via valid_email", "valid_email(" in add_src)
    check("add dedups by normalized phone (409)",
          "normalize_phone(" in add_src and "409" in add_src)
    check("add enforces the max-contacts cap", "MAX_TRUSTED_CONTACTS" in add_src)
    check("add returns the authoritative list", '"contacts"' in add_src)

if del_fn:
    del_src = _src_of(del_fn)
    check("delete is authenticated via get_current_user", _depends_on_get_current_user(del_fn))
    check("delete derives identity from current_user.user_id", "current_user.user_id" in del_src)
    # The delete filter MUST be scoped to BOTH the owner and the contact id.
    check("delete is scoped to user_id AND contact_id (no cross-user / unscoped delete)",
          '"user_id": user_id' in del_src and '"contact_id": contact_id' in del_src)
    check("delete uses delete_one (never delete_many)",
          "delete_one" in del_src and "delete_many" not in del_src)
    check("delete returns 404 when nothing was removed", "deleted_count == 0" in del_src and "404" in del_src)
    check("delete returns the authoritative remaining list", '"contacts"' in del_src)


print(f"\n==== {passed} passed, {failed} failed ====")
sys.exit(1 if failed else 0)
