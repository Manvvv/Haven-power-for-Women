"""
Dependency-free validator for the Case & Profile Intelligence search engine
(services/profile_search.py).

Runs WITHOUT pytest / pymongo / fastapi so it can execute anywhere (the CI
sandbox has no PyPI access). It exercises the same behaviours as
test_profile_search.py using a tiny in-memory fake collection.

Usage:
    python backend/validate_profile_search.py
Exit code 0 == all checks passed, 1 == at least one failed.
"""
import os
import sys

# Make `services.*` importable regardless of the caller's CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from services import profile_search as ps  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


# ─── in-memory fake Mongo collection ─────────────────────────────────────────
class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, n):
        return FakeCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    """Minimal stand-in. `find` ignores the query filter and returns every doc
    (with projection applied); profile_search re-ranks/excludes deterministically
    afterwards, so this is faithful for scoring behaviour."""

    def __init__(self, docs):
        self.docs = docs

    def _project(self, d, projection):
        dd = dict(d)
        if projection:
            for k, v in projection.items():
                if v == 0:
                    dd.pop(k, None)
        return dd

    def find(self, filt=None, projection=None):
        return FakeCursor([self._project(d, projection) for d in self.docs])

    def find_one(self, filt, projection=None):
        for d in self.docs:
            if "culprit_id" in filt and d.get("culprit_id") == filt["culprit_id"]:
                return self._project(d, projection)
        return None

    def aggregate(self, pipeline):
        raise RuntimeError("vector search unavailable in validator")


class BrokenCollection:
    def find(self, *a, **k):
        raise RuntimeError("db down")

    def aggregate(self, *a, **k):
        raise RuntimeError("db down")


# ─── seed data (includes two similar names for false-positive checks) ─────────
DOCS = [
    {"culprit_id": "PROF-aaa", "name": "Nirmal Nehra",
     "physical_description": "tall male, black beard, around 35 years",
     "behavioral_traits": "aggressive, raised voice", "location": "Ghaziabad",
     "description_embedding": [0.1] * 768, "reporter_id": "auth-1"},
    {"culprit_id": "PROF-bbb", "name": "Nirmal Nehru",
     "physical_description": "short person, spectacles",
     "behavioral_traits": "calm, polite", "location": "Delhi",
     "description_embedding": [0.2] * 768, "reporter_id": "auth-2"},
    {"culprit_id": "PROF-ccc", "name": "Rakesh Sharma",
     "physical_description": "medium build, scar on left cheek, black jacket",
     "behavioral_traits": "followed the reporter", "location": "Noida",
     "description_embedding": [0.3] * 768, "reporter_id": "auth-3"},
]
COLL = FakeCollection(DOCS)


# ══════════════════════════════ PLACEHOLDER ══════════════════════════════════
def _ids(matches):
    return [m.get("profile_id") for m in matches]


print("Validating profile_search engine...\n")

# 1) Normalization / tokenization / fold
check(ps.normalize_text("  Nirmal   NEHRA!! ") == "nirmal nehra", "normalize collapses/strips")
check(ps.tokens("Nirmal, Nehra") == ["nirmal", "nehra"], "tokenizer splits on punctuation")
check(ps.normalize_text("<b>hi</b>") == "hi", "normalize strips HTML")
check(ps.fold_token("nehraa") == ps.fold_token("nehra"), "fold collapses doubled vowels")

# 2) Query classification (explicit buttons win; auto heuristic)
check(ps.classify_query("nirmal nehra", "name") == ps.NAME_QUERY, "explicit name button")
check(ps.classify_query("anything", "description") == ps.DESCRIPTION_QUERY, "explicit description button")
check(ps.classify_query("nirmal nehra") == ps.NAME_QUERY, "auto: plain name -> NAME")
check(ps.classify_query("tall male black jacket aggressive") == ps.DESCRIPTION_QUERY, "auto: descriptors -> DESCRIPTION")
check(ps.classify_query("nirmal nehra last seen near ghaziabad") == ps.MIXED_QUERY, "auto: several plain tokens -> MIXED")

# 3) Deterministic NAME search — the original bug: "nirmal nehra" must match
m = ps.deterministic_name_search(COLL, "nirmal nehra", 10)
check("PROF-aaa" in _ids(m), "exact full name 'nirmal nehra' found (root-cause fix)")
check(m[0]["profile_id"] == "PROF-aaa" and m[0]["match_score"] == 1.0, "exact match scores 1.0 and ranks first")
check(ps.deterministic_name_search(COLL, "NIRMAL NEHRA", 10)[0]["profile_id"] == "PROF-aaa", "case-insensitive name")
check("PROF-aaa" in _ids(ps.deterministic_name_search(COLL, "nirmal", 10)), "partial single-token name")
check("PROF-aaa" in _ids(ps.deterministic_name_search(COLL, "nehra", 10)), "partial by surname")
check("PROF-aaa" in _ids(ps.deterministic_name_search(COLL, "nehra nirmal", 10)), "reordered tokens")
check(ps.deterministic_name_search(COLL, "zzzznomatch", 10) == [], "no-match name returns empty (no invented profile)")

# 3b) False-positive safety: two similar names can both surface as leads
mm = ps.deterministic_name_search(COLL, "nirmal", 10)
check("PROF-aaa" in _ids(mm) and "PROF-bbb" in _ids(mm), "similar names both appear as separate leads")

# 4) Name typed into DESCRIPTION box must not be buried (name dominance)
hyb = ps.hybrid_description_search(COLL, "nirmal nehra", 10)
top = hyb["matches"][0]
check(top["profile_id"] == "PROF-aaa" and top["match_score"] >= 0.90, "full name in description box floored to >=0.90")
check(hyb["mode"] == "keyword_fallback", "semantic unavailable -> keyword_fallback mode")
check(hyb["degraded"] is False, "degraded False when semantic backend simply absent")

# 4b) Description keyword search finds the right record
d = ps.hybrid_description_search(COLL, "scar on left cheek black jacket", 10)
check("PROF-ccc" in _ids(d["matches"]), "description keyword search finds scar/jacket record")

# ══════════════════════════════ PLACEHOLDER2 ═════════════════════════════════
# 5) Retrieval levels (never identity confidence)
check(ps.match_level(0.9) == ps.LEVEL_HIGH, "0.9 -> High")
check(ps.match_level(0.5) == ps.LEVEL_MODERATE, "0.5 -> Moderate")
check(ps.match_level(0.2) == ps.LEVEL_WEAK, "0.2 -> Weak")

# 6) Result shape NEVER leaks embeddings / reporter / _id (requirement 25)
for res in ps.deterministic_name_search(COLL, "nirmal nehra", 10):
    leaked = [k for k in ("description_embedding", "reporter_id", "reporter_role", "_id") if k in res]
    check(not leaked, f"no sensitive field leaked ({leaked})")
    check(res.get("human_verification_required") is True, "human_verification_required flag present")
    check("profile_id" in res and "match_level" in res and "match_factors" in res, "structured contract fields present")

# 7) Structured orchestrator contract + public query_type values
r = ps.run_profile_search(COLL, "nirmal nehra", "name", 10)
check(r["query_type"] == "name", "public query_type is lowercase 'name'")
check(r["search_type"] == "deterministic_name", "name search_type label")
check(set(r.keys()) == {"query_type", "search_type", "matches", "degraded"}, "orchestrator returns exact contract keys")
r2 = ps.run_profile_search(COLL, "tall male black jacket aggressive", "description", 10)
check(r2["query_type"] == "description", "public query_type 'description'")
check(ps.run_profile_search(COLL, "", "name", 10)["search_type"] == "empty", "empty query -> search_type 'empty'")
check(ps.run_profile_search(COLL, "x", "name", 999)["matches"] == ps.run_profile_search(COLL, "x", "name", 50)["matches"], "top_n clamped to <=50")

# 8) Registration validation (requirement 12)
_, e_ok = ps.validate_profile_input("Nirmal Nehra", "tall male around 35 years", "raised voice", "Ghaziabad")
check(e_ok == {}, "valid input passes")
_, e_short = ps.validate_profile_input("", "short", "x", "")
check("physical_description" in e_short and "behavioral_traits" in e_short, "too-short required fields flagged")
_, e_junk = ps.validate_profile_input("", "aaaaaaaaaaaa", "valid behaviour text", "")
check("physical_description" in e_junk, "junk (single repeated char) rejected")
_, e_html = ps.validate_profile_input("<script>x</script>", "tall male around 35", "raised voice", "")
check("name" in e_html, "HTML/script content rejected")
_, e_big = ps.validate_profile_input("", "a tall male " * 400, "raised voice observed", "")
check("physical_description" in e_big, "oversized input rejected")
cleaned_u, e_u = ps.validate_profile_input("Ｎirmal", "tall male around 35 years", "raised voice", "")
check(e_u == {} and "Nirmal" in cleaned_u["name"], "Unicode NFKC-normalized fullwidth name accepted")

# 9) Duplicate detection (requirement 13)
dups = ps.find_duplicate_candidates(COLL, {"name": "Nirmal Nehra",
                                           "physical_description": "tall male, black beard, around 35 years"})
check(any(x["profile_id"] == "PROF-aaa" for x in dups), "duplicate: same name + similar description flagged")
none = ps.find_duplicate_candidates(COLL, {"name": "Totally Unique Person",
                                           "physical_description": "wearing a green hat only"})
check(none == [], "no duplicate for a genuinely new record")

# 10) Profile id: random, non-sequential, correct prefix, unique
i1, i2 = ps.generate_profile_id(), ps.generate_profile_id()
check(i1.startswith("PROF-") and len(i1) == 21, "profile id format PROF-<16 hex>")
check(i1 != i2, "profile ids are unique/random (not sequential)")

# 11) Hard DB failure surfaces as ProfileSearchError (route -> 503, never "no match")
try:
    ps.deterministic_name_search(BrokenCollection(), "nirmal", 10)
    check(False, "broken DB should raise ProfileSearchError")
except ps.ProfileSearchError:
    check(True, "broken DB raises ProfileSearchError (mapped to 503)")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)


