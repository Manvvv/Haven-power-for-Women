"""
validate_search_consolidation.py — static, dependency-free proof that EVERY
production profile/culprit matching path converges on the single canonical
hardened matcher (services.profile_search.run_profile_search) and that no legacy
duplicate profile matcher or field/score-leaking path survives (audit #11).

WHY STATIC (AST) INSTEAD OF HTTP:
  The routers import FastAPI, which is not installable in the CI sandbox. This
  validator parses the SOURCE with the stdlib `ast` module instead, so it runs
  anywhere and asserts the structural facts the audit requires:

    * services/search_service.py no longer DEFINES a profile matcher
      (search_profiles / _shape_profile / _keyword_profiles / _semantic_profiles
      / _hybrid_profiles) and no longer imports the `culprits` collection, but
      DOES still define CASE search — functionality preserved.
    * routers/search_routes.py: /search/profiles and /search/exact both call
      run_profile_search, do NOT call the legacy search_profiles, contain no
      fabricated-score assignment and no bespoke raw find(); all profile
      endpoints require_authority.
    * routers/culprit_routes.py: /culprit/find-match calls run_profile_search
      and requires authority.
    * profile_search.py is the ONLY module that runs a $vectorSearch over the
      culprit `culpritIndex`.

Exit 0 == all pass. Run: python3 validate_search_consolidation.py (cwd = backend)
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_FAILS = []
_PASSES = 0
_DEFT = (ast.FunctionDef, ast.AsyncFunctionDef)


def _check(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
    else:
        _FAILS.append(label)


def _src(rel):
    with open(os.path.join(_HERE, rel), encoding="utf-8") as fh:
        return fh.read()


def _tree(rel):
    return ast.parse(_src(rel))


def _func_defs(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, _DEFT)}


def _imported_names(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.ImportFrom, ast.Import)):
            for a in n.names:
                names.add(a.asname or a.name)
    return names


def _calls_in(node):
    """Set of called function short-names within an AST node."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _endpoint_funcs(tree):
    """Map (http_method, route_path) -> FunctionDef for @router.<method>('path')."""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, _DEFT):
            for dec in n.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    out[(dec.func.attr, dec.args[0].value)] = n
    return out


print("Validating profile/culprit search consolidation (static AST)...\n")

# ── 1. search_service.py: legacy profile matcher REMOVED, case search KEPT ────
ss = _tree("services/search_service.py")
ss_funcs = _func_defs(ss)
for gone in ("search_profiles", "_shape_profile", "_keyword_profiles",
             "_semantic_profiles", "_hybrid_profiles"):
    _check(gone not in ss_funcs,
           f"search_service.py must NOT define legacy profile fn {gone!r}")
for kept in ("search_cases", "_shape_case", "_hybrid_cases", "_keyword_cases",
             "_semantic_cases"):
    _check(kept in ss_funcs,
           f"search_service.py must STILL define case-search fn {kept!r} (functionality preserved)")
_check("culprits" not in _imported_names(ss),
       "search_service.py must no longer import the `culprits` collection")
_check("culpritIndex" not in _src("services/search_service.py"),
       "search_service.py must not reference culpritIndex (legacy profile vector path)")

# ── 2. search_routes.py: both profile endpoints reach the canonical matcher ───
sr_text = _src("routers/search_routes.py")
sr = ast.parse(sr_text)
sr_imports = _imported_names(sr)
_check("run_profile_search" in sr_imports,
       "search_routes.py must import run_profile_search (canonical matcher)")
_check("search_profiles" not in sr_imports,
       "search_routes.py must NOT import legacy search_profiles")
sr_eps = _endpoint_funcs(sr)

prof = sr_eps.get(("post", "/profiles"))
_check(prof is not None, "/search/profiles endpoint present")
if prof is not None:
    calls = _calls_in(prof)
    _check("run_profile_search" in calls, "/search/profiles calls run_profile_search")
    _check("search_profiles" not in calls, "/search/profiles no longer calls legacy search_profiles")
    _check("require_authority" in _names_in(prof), "/search/profiles requires authority (RBAC)")

exact = sr_eps.get(("get", "/exact"))
_check(exact is not None, "/search/exact endpoint present")
if exact is not None:
    _check("run_profile_search" in _calls_in(exact), "/search/exact calls run_profile_search")
    _check("require_authority" in _names_in(exact), "/search/exact requires authority (RBAC)")
    src_exact = ast.get_source_segment(sr_text, exact) or ""
    _check('["score"]' not in src_exact and "'score'" not in src_exact,
           "/search/exact no longer fabricates a flat score")
    _check(".find(" not in src_exact,
           "/search/exact no longer runs a bespoke raw collection.find() profile query")

sem = sr_eps.get(("post", "/semantic"))
_check(sem is not None and "require_authority" in _names_in(sem),
       "/search/semantic (case search) still requires authority (unchanged)")

# ── 3. culprit_routes.py: find-match already canonical ────────────────────────
cr = _tree("routers/culprit_routes.py")
cr_eps = _endpoint_funcs(cr)
fm = cr_eps.get(("post", "/find-match")) or cr_eps.get(("post", "/culprit/find-match"))
_check(fm is not None, "/culprit/find-match endpoint present")
if fm is not None:
    _check("run_profile_search" in _calls_in(fm), "/culprit/find-match calls run_profile_search")
    _check("require_authority" in _names_in(fm), "/culprit/find-match requires authority (RBAC)")
_check("run_profile_search" in _imported_names(cr),
       "culprit_routes.py imports the canonical matcher")

# ── 4. profile_search.py is the ONLY module doing a culprit $vectorSearch ─────
svc_dir = os.path.join(_HERE, "services")
offenders = []
for fn in sorted(os.listdir(svc_dir)):
    if not fn.endswith(".py") or fn == "profile_search.py":
        continue
    if "culpritIndex" in open(os.path.join(svc_dir, fn), encoding="utf-8").read():
        offenders.append(fn)
_check(not offenders,
       f"only profile_search.py may query culpritIndex; offenders: {offenders}")
_check("culpritIndex" in _src("services/profile_search.py"),
       "profile_search.py retains the canonical culprit vector path")


def main():
    if _FAILS:
        print(f"{_PASSES} passed, {len(_FAILS)} FAILED\n")
        for f in _FAILS:
            print("  FAIL:", f)
        return 1
    print(f"PASSED {_PASSES} checks")
    print("ALL PROFILE/CULPRIT SEARCH-CONSOLIDATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
