"""
test_profile_search.py — hermetic spec suite for Case & Profile Intelligence
search (services/profile_search.py).

Covers the "CASE & PROFILE INTELLIGENCE / CULPRIT SEARCH" upgrade acceptance
criteria:
  * NAME search is deterministic/lexical (exact, case-insensitive, partial,
    reordered tokens, no-match) and NEVER gated by a vector-similarity floor —
    this is the direct fix for the "nirmal nehra -> No matches above threshold"
    bug;
  * DESCRIPTION search is field-aware hybrid with a transparent keyword
    fallback (degraded) when no embedding backend is available;
  * a weak semantic score can never outrank an exact/complete name match;
  * results never leak embeddings / reporter identity / Mongo _id;
  * registration validation, duplicate detection, robust random profile ids;
  * hard DB failure raises ProfileSearchError (route -> 503, never "no match").

HERMETIC: an in-memory fake collection stands in for MongoDB and the semantic
layer is forced off (or monkeypatched) so no network / API key / DB is needed.

    cd haven/backend && pytest test_profile_search.py -v
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from services import profile_search as ps  # noqa: E402


# ─── in-memory fake collection ───────────────────────────────────────────────
class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, n):
        return FakeCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
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
            if filt.get("culprit_id") == d.get("culprit_id"):
                return self._project(d, projection)
        return None

    def aggregate(self, pipeline):
        raise RuntimeError("vector search unavailable")


class BrokenCollection:
    def find(self, *a, **k):
        raise RuntimeError("db down")

    def aggregate(self, *a, **k):
        raise RuntimeError("db down")


# ─── seed data (two similar names guard against false positives) ─────────────
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


@pytest.fixture()
def coll():
    return FakeCollection([dict(d) for d in DOCS])


@pytest.fixture()
def broken():
    return BrokenCollection()


@pytest.fixture(autouse=True)
def _force_semantic_off(monkeypatch):
    """Default: no embedding backend, so behaviour is deterministic. Individual
    tests that need semantic ON monkeypatch it back."""
    monkeypatch.setattr(ps, "_semantic_available", lambda: False)


def _ids(matches):
    return [m.get("profile_id") for m in matches]


# ─── 1) normalization / tokenization / folding ───────────────────────────────
def test_normalize_collapses_and_strips():
    assert ps.normalize_text("  Nirmal   NEHRA!! ") == "nirmal nehra"


def test_tokenizer_splits_on_punctuation():
    assert ps.tokens("Nirmal, Nehra") == ["nirmal", "nehra"]


def test_normalize_strips_html():
    assert ps.normalize_text("<b>hi</b>") == "hi"


def test_fold_collapses_doubled_vowels():
    assert ps.fold_token("nehraa") == ps.fold_token("nehra")


# ─── 2) query classification (explicit buttons win; auto heuristic) ───────────
def test_classify_explicit_name_button():
    assert ps.classify_query("nirmal nehra", "name") == ps.NAME_QUERY


def test_classify_explicit_description_button():
    assert ps.classify_query("anything", "description") == ps.DESCRIPTION_QUERY


def test_classify_auto_plain_name_is_name():
    assert ps.classify_query("nirmal nehra") == ps.NAME_QUERY


def test_classify_auto_descriptors_is_description():
    assert ps.classify_query(
        "tall male black jacket aggressive") == ps.DESCRIPTION_QUERY


def test_classify_auto_several_plain_tokens_is_mixed():
    assert ps.classify_query(
        "nirmal nehra last seen near ghaziabad") == ps.MIXED_QUERY


# ─── 3) deterministic NAME search — the original "nirmal nehra" bug ──────────
def test_exact_full_name_found_and_ranks_first(coll):
    m = ps.deterministic_name_search(coll, "nirmal nehra", 10)
    assert "PROF-aaa" in _ids(m)
    assert m[0]["profile_id"] == "PROF-aaa"
    assert m[0]["match_score"] == 1.0


def test_name_is_case_insensitive(coll):
    m = ps.deterministic_name_search(coll, "NIRMAL NEHRA", 10)
    assert m[0]["profile_id"] == "PROF-aaa"


def test_partial_single_token_name(coll):
    assert "PROF-aaa" in _ids(ps.deterministic_name_search(coll, "nirmal", 10))


def test_partial_by_surname(coll):
    assert "PROF-aaa" in _ids(ps.deterministic_name_search(coll, "nehra", 10))


def test_reordered_tokens(coll):
    assert "PROF-aaa" in _ids(
        ps.deterministic_name_search(coll, "nehra nirmal", 10))


def test_no_match_name_returns_empty(coll):
    # NEVER invents a profile; NAME search is not gated by a vector floor.
    assert ps.deterministic_name_search(coll, "zzzznomatch", 10) == []


def test_similar_names_both_surface_as_leads(coll):
    mm = ps.deterministic_name_search(coll, "nirmal", 10)
    assert "PROF-aaa" in _ids(mm) and "PROF-bbb" in _ids(mm)


# ─── 4) hybrid DESCRIPTION search + name dominance ───────────────────────────
def test_full_name_in_description_box_floored(coll):
    hyb = ps.hybrid_description_search(coll, "nirmal nehra", 10)
    top = hyb["matches"][0]
    assert top["profile_id"] == "PROF-aaa"
    assert top["match_score"] >= 0.90


def test_semantic_absent_is_keyword_fallback_not_degraded(coll):
    hyb = ps.hybrid_description_search(coll, "nirmal nehra", 10)
    assert hyb["mode"] == "keyword_fallback"
    assert hyb["degraded"] is False


def test_description_keyword_finds_scar_jacket(coll):
    d = ps.hybrid_description_search(coll, "scar on left cheek black jacket", 10)
    assert "PROF-ccc" in _ids(d["matches"])


def test_weak_semantic_cannot_outrank_exact_name(coll, monkeypatch):
    """Even with the semantic backend ON and handing a competing record a high
    vector score, an exact/complete name match still ranks first (req 4)."""
    monkeypatch.setattr(ps, "_semantic_available", lambda: True)
    doc_ccc = next(d for d in DOCS if d["culprit_id"] == "PROF-ccc")

    def fake_sem(collection, query, limit):
        return {"PROF-ccc": (dict(doc_ccc), 0.99)}  # (doc, normalized score)

    monkeypatch.setattr(ps, "_semantic_candidates", fake_sem)
    hyb = ps.hybrid_description_search(coll, "nirmal nehra", 10)
    assert hyb["mode"] == "hybrid"
    assert hyb["degraded"] is False
    assert hyb["matches"][0]["profile_id"] == "PROF-aaa"


def test_semantic_requested_but_empty_is_degraded(coll, monkeypatch):
    """Semantic backend claims availability but returns nothing usable →
    transparent 'keyword matches' fallback flagged degraded (req 27)."""
    monkeypatch.setattr(ps, "_semantic_available", lambda: True)
    monkeypatch.setattr(ps, "_semantic_candidates",
                        lambda collection, query, limit: {})
    hyb = ps.hybrid_description_search(coll, "scar black jacket", 10)
    assert hyb["degraded"] is True


# ─── 5) retrieval levels (never identity confidence) ─────────────────────────
def test_match_level_high():
    assert ps.match_level(0.9) == ps.LEVEL_HIGH


def test_match_level_moderate():
    assert ps.match_level(0.5) == ps.LEVEL_MODERATE


def test_match_level_weak():
    assert ps.match_level(0.2) == ps.LEVEL_WEAK


# ─── 6) result shape NEVER leaks embeddings / reporter / _id (req 25) ────────
def test_no_sensitive_field_leaks(coll):
    for res in ps.deterministic_name_search(coll, "nirmal nehra", 10):
        leaked = [k for k in ("description_embedding", "reporter_id",
                              "reporter_role", "_id") if k in res]
        assert not leaked, f"leaked {leaked}"
        assert res.get("human_verification_required") is True
        assert "profile_id" in res
        assert "match_level" in res
        assert "match_factors" in res


# ─── 7) orchestrator contract + public query_type values ─────────────────────
def test_orchestrator_name_contract(coll):
    r = ps.run_profile_search(coll, "nirmal nehra", "name", 10)
    assert r["query_type"] == "name"          # lowercase public value
    assert r["search_type"] == "deterministic_name"
    assert set(r.keys()) == {"query_type", "search_type", "matches", "degraded"}


def test_orchestrator_description_contract(coll):
    r = ps.run_profile_search(coll, "tall male black jacket aggressive",
                              "description", 10)
    assert r["query_type"] == "description"


def test_orchestrator_empty_query(coll):
    assert ps.run_profile_search(coll, "", "name", 10)["search_type"] == "empty"


def test_orchestrator_clamps_top_n(coll):
    a = ps.run_profile_search(coll, "x", "name", 999)["matches"]
    b = ps.run_profile_search(coll, "x", "name", 50)["matches"]
    assert a == b


# ─── 8) registration validation (req 12) ─────────────────────────────────────
def test_valid_input_passes():
    _, e = ps.validate_profile_input(
        "Nirmal Nehra", "tall male around 35 years", "raised voice", "Ghaziabad")
    assert e == {}


def test_too_short_required_fields_flagged():
    _, e = ps.validate_profile_input("", "short", "x", "")
    assert "physical_description" in e and "behavioral_traits" in e


def test_junk_repeated_char_rejected():
    _, e = ps.validate_profile_input("", "aaaaaaaaaaaa", "valid behaviour text", "")
    assert "physical_description" in e


def test_html_script_content_rejected():
    _, e = ps.validate_profile_input(
        "<script>x</script>", "tall male around 35", "raised voice", "")
    assert "name" in e


def test_oversized_input_rejected():
    _, e = ps.validate_profile_input(
        "", "a tall male " * 400, "raised voice observed", "")
    assert "physical_description" in e


def test_unicode_fullwidth_name_normalized():
    cleaned, e = ps.validate_profile_input(
        "Ｎirmal", "tall male around 35 years", "raised voice", "")
    assert e == {} and "Nirmal" in cleaned["name"]


# ─── 9) duplicate detection (req 13) ─────────────────────────────────────────
def test_duplicate_same_name_and_similar_desc_flagged(coll):
    dups = ps.find_duplicate_candidates(coll, {
        "name": "Nirmal Nehra",
        "physical_description": "tall male, black beard, around 35 years"})
    assert any(x["profile_id"] == "PROF-aaa" for x in dups)


def test_no_duplicate_for_new_record(coll):
    none = ps.find_duplicate_candidates(coll, {
        "name": "Totally Unique Person",
        "physical_description": "wearing a green hat only"})
    assert none == []


# ─── 10) profile id: random, non-sequential, correct prefix, unique ──────────
def test_profile_id_format_and_uniqueness():
    i1, i2 = ps.generate_profile_id(), ps.generate_profile_id()
    assert i1.startswith("PROF-") and len(i1) == 21
    assert i1 != i2


# ─── 11) hard DB failure surfaces as ProfileSearchError (route -> 503) ───────
def test_broken_db_raises_profilesearcherror(broken):
    with pytest.raises(ps.ProfileSearchError):
        ps.deterministic_name_search(broken, "nirmal", 10)


def test_broken_db_in_orchestrator_raises(broken):
    with pytest.raises(ps.ProfileSearchError):
        ps.run_profile_search(broken, "nirmal nehra", "name", 10)
