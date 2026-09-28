"""
test_legal_rag.py — Automated spec suite for HAVEN's grounded Legal RAG.

Covers the acceptance criteria for the "Next-Level Indian Legal Assistant" upgrade:
  * verified-corpus integrity + current-law (BNS/BNSS 2023) usage,
  * deterministic triage (category / language / state / urgency / emergency),
  * hybrid retrieval returns grounded, CITED sources for high-frequency queries,
  * NO-HALLUCINATION guard: with no verified match the LLM is never called and
    no legal content is invented,
  * evidence-level confidence (HIGH / MEDIUM / INSUFFICIENT_EVIDENCE),
  * legal-aid / eCourts escalation and emergency routing.

The suite is HERMETIC: it stubs the LLM (services.ai_service), the embedding
backend, and MongoDB with an in-memory fake, so it needs no network, no API key
and no live database. Run from haven/backend:

    pytest test_legal_rag.py -v
"""
import re
import sys
import types

import pytest

# ── Stub the LLM + embedding backend BEFORE importing the RAG service, so no
#    real Groq/Gemini client or API key is ever required. answer() does a lazy
#    `from services.ai_service import call_groq`, and embeddings import
#    `from services.ai_service import get_embedding`; both resolve to this fake.
_STUB_ANSWER = "GROUNDED_STUB_ANSWER: based only on the verified context above. [1]"
_fake_ai = types.ModuleType("services.ai_service")
_fake_ai.CALLS = []          # every call_groq invocation is recorded here


def _fake_get_embedding(text, *a, **k):
    return [0.0] * 768        # DEMO zero-vector; never used (semantic forced off)


def _fake_call_groq(messages, *a, **k):
    _fake_ai.CALLS.append(messages)
    return _STUB_ANSWER


_fake_ai.get_embedding = _fake_get_embedding
_fake_ai.call_groq = _fake_call_groq
sys.modules["services.ai_service"] = _fake_ai

from services import legal_corpus, legal_triage, legal_rag  # noqa: E402


# ─────────────────────────── in-memory Mongo fake ───────────────────────────
class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def limit(self, n):
        return _Cursor(self._docs[: int(n)])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    """Minimal MongoDB stand-in supporting the operators legal_rag actually uses:
    scalar equality, $and, $or and {$regex,$options} (incl. array fields)."""

    def __init__(self):
        self.docs = []

    def _match_field(self, value, cond):
        if isinstance(cond, dict) and "$regex" in cond:
            flags = re.I if "i" in cond.get("$options", "") else 0
            rx = re.compile(cond["$regex"], flags)
            if isinstance(value, (list, tuple)):
                return any(rx.search(str(v)) for v in value)
            return value is not None and bool(rx.search(str(value)))
        if isinstance(value, (list, tuple)):      # Mongo: match if any element equals
            return cond in value
        return value == cond

    def _match(self, doc, query):
        for key, cond in query.items():
            if key == "$and":
                if not all(self._match(doc, sub) for sub in cond):
                    return False
            elif key == "$or":
                if not any(self._match(doc, sub) for sub in cond):
                    return False
            elif not self._match_field(doc.get(key), cond):
                return False
        return True

    def _project(self, doc, projection):
        if not projection:
            return dict(doc)
        exclude = {k for k, v in projection.items() if v == 0}
        return {k: v for k, v in doc.items() if k not in exclude}

    def count_documents(self, query, limit=None):
        c = 0
        for d in self.docs:
            if self._match(d, query):
                c += 1
                if limit and c >= limit:
                    return c
        return c

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def find(self, query, projection=None):
        return _Cursor(self._project(d, projection) for d in self.docs if self._match(d, query))

    def distinct(self, field):
        return list({d.get(field) for d in self.docs if d.get(field) is not None})

    def aggregate(self, pipeline):
        return iter([])           # $vectorSearch path is disabled in these tests


_DEMO_EMBEDDING_INFO = {
    "backend": "stub", "model_name": "stub-model", "status": "DEMO",
    "semantic_search_available": False,
}

CORPUS_DOC_IDS = {e["document_id"] for e in legal_corpus.all_entries()}
CORPUS_TITLES = {e["title"] for e in legal_corpus.all_entries()}


@pytest.fixture
def rag(monkeypatch):
    """Seed the verified corpus into an in-memory collection, force keyword-only
    (DEMO) retrieval, and reset the recorded LLM calls. Yields the collection."""
    coll = FakeCollection()
    monkeypatch.setattr(legal_rag, "legal_docs", lambda: coll)
    monkeypatch.setattr(legal_rag, "embedding_info", lambda: dict(_DEMO_EMBEDDING_INFO))
    monkeypatch.setattr(legal_rag, "embed", lambda text: [])
    _fake_ai.CALLS.clear()
    for e in legal_corpus.all_entries():
        res = legal_rag.ingest_document(
            title=e["title"], text=e["text"], source_name=e.get("authority", ""),
            source_url=e.get("source_url", ""), jurisdiction=e.get("jurisdiction", "India"),
            section=e.get("section", ""), verification_status=e.get("verification_status", "verified"),
            document_version=str(e.get("version", "1")), uploaded_by="test",
            document_id=e["document_id"], metadata=e,
        )
        assert not res.get("error"), res
    return coll


def _doc_ids(resp):
    return {s.get("document_id") for s in resp.get("sources", [])}


# ═══════════════════════ 1. Verified corpus integrity ═══════════════════════
_VALID_AUTHORITY = {
    "tier1_primary_statute", "tier1_primary_authority",
    "tier2_official_explanatory", "tier3_secondary",
}


def test_corpus_nonempty_and_unique_ids():
    entries = legal_corpus.all_entries()
    assert len(entries) >= 30, "corpus must be substantial enough to ground common queries"
    ids = [e["document_id"] for e in entries]
    assert len(ids) == len(set(ids)), "document_id values must be unique"


def test_corpus_entries_are_well_formed_and_verified():
    for e in legal_corpus.all_entries():
        assert e["verification_status"] == "verified"
        assert e["title"] and e["text"].strip()
        assert e["act_name"] and e["section"], f"{e['document_id']} missing citation"
        assert e["authority_level"] in _VALID_AUTHORITY, e["document_id"]
        assert str(e.get("source_url", "")).startswith("http"), e["document_id"]
        assert isinstance(e["keywords"], list) and e["keywords"], e["document_id"]


def test_corpus_covers_all_required_domains():
    cats = {e["category"] for e in legal_corpus.all_entries()}
    for required in ("family", "women_rights", "child_safety", "police", "cyber",
                     "workplace", "legal_aid", "court_navigation"):
        assert required in cats, f"missing corpus coverage for {required}"


def test_corpus_uses_current_criminal_codes_not_stale_law():
    """IPC/CrPC/498A may only appear as explicitly-labelled historical references;
    the current codes (BNS/BNSS 2023) must be present as primary law."""
    joined = " ".join(e["text"] for e in legal_corpus.all_entries())
    assert "Bharatiya Nyaya Sanhita" in joined
    assert "Bharatiya Nagarik Suraksha Sanhita" in joined
    stale = ("Indian Penal Code", "Code of Criminal Procedure", "IPC", "498A", "CrPC")
    for e in legal_corpus.all_entries():
        low = e["text"].lower()
        if any(s.lower() in low for s in stale):
            assert ("historical" in low or "successor" in low or "former" in low), (
                f"{e['document_id']} references old code without a historical/successor label")


# ═══════════════════ 2. Deterministic triage (no LLM) ═══════════════════════
def test_triage_divorce_is_family_not_general():
    assert legal_triage.classify_category("i want divorce") == "family"


def test_triage_hinglish_divorce():
    q = legal_triage.build_query("mujhe apne pati se talaq chahiye")
    assert q.language == "hinglish"
    assert q.category == "family"


def test_triage_fir_is_police_english_with_state():
    """Regression: 'police' must not be read as Hinglish, and FIR is a police matter."""
    q = legal_triage.build_query("police refused to file my FIR in Maharashtra")
    assert q.category == "police"
    assert q.state == "Maharashtra"
    assert q.language == "en"


def test_triage_cyber_leak_is_high_urgency():
    q = legal_triage.build_query("someone leaked my morphed photos online")
    assert q.category == "cyber"
    assert q.urgency in ("high", "emergency")


def test_triage_missing_child_override_to_child_safety():
    q = legal_triage.build_query("my child is missing")
    assert q.category == "child_safety"
    assert q.urgency in ("high", "emergency")
    assert q.children_involved is True


def test_triage_immediate_danger_is_emergency_with_112_first():
    tri = legal_triage.triage("he is hitting me right now")
    assert tri["urgency"] == "emergency" and tri["immediate_danger"] is True
    assert tri["emergency"] is True
    assert tri["helplines"][0]["number"] == "112"


def test_triage_state_extraction():
    assert legal_triage.build_query("domestic violence case in Karnataka").state == "Karnataka"


def test_legal_aid_block_lists_nalsa_and_telelaw():
    block = legal_triage.legal_aid_block()
    numbers = {h["number"] for h in block["helplines"]}
    assert "15100" in numbers and "14454" in numbers
    for h in block["helplines"]:            # helplines are data, carry provenance
        assert h.get("source") and h.get("verified_at")


# ═════════════════ 3. Evidence confidence + scoring helpers ═════════════════
def test_evidence_level_insufficient_when_empty():
    assert legal_triage.compute_evidence_level([]) == "INSUFFICIENT_EVIDENCE"


def test_evidence_level_high_with_two_primary_sources():
    passages = [{"authority_level": "tier1_primary_statute"},
                {"authority_level": "tier1_primary_statute"}]
    assert legal_triage.compute_evidence_level(passages) == "HIGH"


def test_evidence_level_high_with_one_strong_primary_source():
    assert legal_triage.compute_evidence_level(
        [{"authority_level": "tier1_primary_statute", "score": 0.72}]) == "HIGH"


def test_evidence_level_medium_for_weak_or_secondary():
    assert legal_triage.compute_evidence_level(
        [{"authority_level": "tier2_official_explanatory"}]) == "MEDIUM"
    assert legal_triage.compute_evidence_level(
        [{"authority_level": "tier1_primary_statute", "score": 0.60}]) == "MEDIUM"


def test_query_tokens_strips_stopwords():
    assert legal_triage.query_tokens("How do I get a divorce?") == ["divorce"]


def test_keyword_match_ratio():
    assert legal_triage.keyword_match_ratio(
        "divorce under the hindu marriage act", ["divorce", "custody"]) == 0.5


def test_authority_weight_ordering():
    aw = legal_triage.authority_weight
    assert aw("tier1_primary_statute") > aw("tier2_official_explanatory") > aw("tier3_secondary")
    assert aw("unknown-level") == 0.70


def test_blended_score_modes():
    # keyword-only mode: 0.75*kw + 0.25*auth
    assert legal_triage.blended_score(0.0, 1.0, 1.0, False) == pytest.approx(1.0)
    assert legal_triage.blended_score(0.0, 0.5, 0.6, False) == pytest.approx(0.525)
    # hybrid mode: 0.55*sem + 0.30*kw + 0.15*auth
    assert legal_triage.blended_score(1.0, 1.0, 1.0, True) == pytest.approx(1.0)


# ═══════════ 4. Grounded retrieval end-to-end (the original bug) ════════════
def test_seed_reports_ingested_chunks(rag):
    assert rag.count_documents({}) >= 30
    assert rag.count_documents({"verification_status": "verified"}) == rag.count_documents({})


def test_divorce_query_now_returns_grounded_cited_sources(rag):
    """The exact query that used to return 'no verified source'."""
    resp = legal_rag.answer("i want divorce")
    assert resp["grounded"] is True and resp["no_context"] is False
    assert resp["status"] == "grounded"
    assert resp["retrieval_mode"] == "keyword_fallback"
    assert len(resp["sources"]) >= 1
    assert any(did.startswith("HMA-1955") for did in _doc_ids(resp)), _doc_ids(resp)
    assert resp["topic"] == "family"
    assert resp["evidence_level"] in ("HIGH", "MEDIUM")


def test_emergency_custody_query_returns_custody_sources(rag):
    """The second originally-failing query."""
    resp = legal_rag.answer("How do I get emergency custody of my children?")
    assert resp["grounded"] is True
    ids = _doc_ids(resp)
    assert ids & {"EMERGENCY-INTERIM-CUSTODY", "GWA-1890-CUSTODY", "HMGA-1956-S6",
                  "FAMILY-COURTS-ACT-1984", "VISITATION"}, ids


def test_cruelty_query_cites_current_bns_not_ipc(rag):
    resp = legal_rag.answer("my husband and in-laws beat me and demand dowry")
    assert resp["grounded"] is True
    assert "BNS-2023-S85-S86" in _doc_ids(resp), _doc_ids(resp)
    # Every cited passage carries a current-law act_name where applicable.
    bns = [s for s in resp["sources"] if s["document_id"] == "BNS-2023-S85-S86"][0]
    assert "Bharatiya Nyaya Sanhita" in bns["act_name"]


def test_citations_only_reference_real_retrieved_corpus(rag):
    """No-fabrication: every citation maps to a real corpus document actually used."""
    resp = legal_rag.answer("how do I report cyber blackmail and leaked photos")
    assert resp["grounded"] is True
    for s in resp["sources"]:
        assert s["document_id"] in CORPUS_DOC_IDS
        assert s["title"] in CORPUS_TITLES
        assert s["document_id"] in resp["retrieved_document_ids"]


def test_llm_receives_only_retrieved_context(rag):
    """The generation call is grounded: system prompt carries the verified context
    and forbids fabrication; user turn carries the question."""
    legal_rag.answer("what are the grounds for divorce")
    assert len(_fake_ai.CALLS) == 1
    system = _fake_ai.CALLS[0][0]["content"]
    user = _fake_ai.CALLS[0][1]["content"]
    assert "VERIFIED LEGAL CONTEXT" in system
    assert "Do NOT invent laws" in system
    assert "divorce" in user.lower()


# ═════════════ 5. No-hallucination guard + escalation + UX fields ═══════════
def test_no_match_never_calls_llm_and_invents_nothing(rag):
    """Unsupported query -> explicit no-context, LLM NOT invoked, no sources."""
    resp = legal_rag.answer("florblax quxzzy vrombat plonk")
    assert resp["no_context"] is True and resp["grounded"] is False
    assert resp["sources"] == []
    assert resp["answer"] == legal_rag.NO_CONTEXT_MESSAGE
    assert resp["evidence_level"] == "INSUFFICIENT_EVIDENCE"
    assert len(_fake_ai.CALLS) == 0, "LLM must not be called without verified sources"


def test_no_context_still_offers_safe_triage_help(rag):
    """Even with no legal source, deterministic safety help is still returned."""
    resp = legal_rag.answer("florblax quxzzy vrombat plonk")
    assert resp["legal_aid"] and resp["legal_aid"]["helplines"]
    assert resp["emergency_resources"], "helplines should still be offered"
    assert resp["disclaimer"] == legal_rag.DISCLAIMER


def test_legal_aid_query_routes_to_free_help(rag):
    resp = legal_rag.answer("I cannot afford a lawyer, is there free legal help?")
    assert resp["grounded"] is True
    assert _doc_ids(resp) & {"LSA-1987-S12", "NALSA-HOW-TO-APPLY", "TELE-LAW-14454"}, _doc_ids(resp)
    numbers = {h["number"] for h in resp["legal_aid"]["helplines"]}
    assert "15100" in numbers


def test_case_status_is_navigation_only_no_live_claim(rag):
    resp = legal_rag.answer("how do I check my case status online")
    assert "ECOURTS-CASE-STATUS" in _doc_ids(resp), _doc_ids(resp)
    steps = " ".join(resp["next_steps"]).lower()
    assert "ecourts" in steps
    assert "does not fetch live case status" in steps


def test_emergency_query_surfaces_emergency_routing(rag):
    resp = legal_rag.answer("he is going to kill me tonight, save me")
    assert resp["emergency"] is True and resp["immediate_danger"] is True
    assert any(h["number"] == "112" for h in resp["emergency_resources"])


def test_multi_issue_query_retrieves_across_domains(rag):
    resp = legal_rag.answer("I want a divorce, custody of my child, and he beats me for dowry")
    assert resp["grounded"] is True
    assert len(_doc_ids(resp)) >= 2, "multi-issue query should surface multiple sources"


def test_every_grounded_answer_has_disclaimer_and_versions(rag):
    resp = legal_rag.answer("what are the grounds for divorce")
    assert resp["disclaimer"] == legal_rag.DISCLAIMER
    assert resp["corpus_version"] == legal_rag.CORPUS_VERSION
    assert resp["triage_version"] == legal_triage.TRIAGE_VERSION


# ═════════ 6. Unicode tokenization + Hindi / Hinglish grounded retrieval ═════
def test_query_tokens_is_unicode_aware_for_devanagari():
    """Root Hindi-failure regression: the tokenizer must keep Devanagari words
    (it used to be ASCII-only, so Hindi queries produced zero keyword hits)."""
    toks = set(legal_triage.query_tokens("मुझे तलाक चाहिए"))
    assert {"मुझे", "तलाक", "चाहिए"} <= toks, toks


def test_query_tokens_drops_generic_hindi_function_words():
    """Generic Hindi particles/verbs (नहीं, रही) carry no legal signal and must be
    stripped, while substantive terms and Latin acronyms survive."""
    toks = set(legal_triage.query_tokens("पुलिस FIR नहीं लिख रही"))
    assert "पुलिस" in toks and "fir" in toks
    assert "नहीं" not in toks and "रही" not in toks, toks


def test_query_tokens_preserve_alphanumeric_section_tokens():
    assert "498a" in legal_triage.query_tokens("is 498a still valid")


def test_hindi_divorce_is_grounded_family_without_dv_leak(rag):
    resp = legal_rag.answer("मुझे तलाक चाहिए")
    assert resp["grounded"] is True and resp["topic"] == "family"
    assert any(did.startswith("HMA-1955") for did in _doc_ids(resp)), _doc_ids(resp)
    # Must NOT pull the domestic-violence source in via the generic pronoun मुझे.
    assert "PWDVA-2005-S3-S12" not in _doc_ids(resp), _doc_ids(resp)


def test_hindi_domestic_violence_is_women_rights(rag):
    resp = legal_rag.answer("पति मुझे मारता है")
    assert resp["grounded"] is True and resp["topic"] == "women_rights"
    assert {"PWDVA-2005-S3-S12", "BNS-2023-S85-S86"} & _doc_ids(resp), _doc_ids(resp)


def test_hindi_custody_returns_custody_sources(rag):
    resp = legal_rag.answer("मेरे बच्चे की कस्टडी चाहिए")
    assert resp["grounded"] is True
    assert _doc_ids(resp) & {"GWA-1890-CUSTODY", "EMERGENCY-INTERIM-CUSTODY",
                             "HMGA-1956-S6"}, _doc_ids(resp)


def test_hindi_legal_aid_without_divorce_leak(rag):
    resp = legal_rag.answer("मुझे कानूनी सहायता चाहिए")
    assert resp["grounded"] is True
    assert _doc_ids(resp) & {"LSA-1987-S12", "NALSA-HOW-TO-APPLY", "TELE-LAW-14454"}, _doc_ids(resp)
    # चाहिए ("want") must not drag the divorce statute into a legal-aid query.
    assert "HMA-1955-S13" not in _doc_ids(resp), _doc_ids(resp)


def test_hindi_fir_refusal_is_police_without_missing_child_leak(rag):
    resp = legal_rag.answer("पुलिस FIR नहीं लिख रही")
    assert resp["grounded"] is True and resp["topic"] == "police"
    assert _doc_ids(resp) & {"POLICE-REFUSAL-REMEDY", "BNSS-2023-S173-FIR", "ZERO-FIR"}, _doc_ids(resp)
    # The missing-child helpline mentions "FIR" incidentally; it is off-topic here.
    assert "MISSING-CHILD-1098" not in _doc_ids(resp), _doc_ids(resp)


def test_hindi_online_threat_is_cyber(rag):
    resp = legal_rag.answer("मुझे ऑनलाइन धमकी मिल रही है")
    assert resp["grounded"] is True and resp["topic"] == "cyber"
    assert "CYBER-REPORTING-PORTAL" in _doc_ids(resp), _doc_ids(resp)


def test_hinglish_talaq_is_family_without_ecourts_navigation_leak(rag):
    resp = legal_rag.answer("mujhe talaq chahiye")
    assert resp["grounded"] is True and resp["topic"] == "family"
    assert any(did.startswith("HMA-1955") for did in _doc_ids(resp)), _doc_ids(resp)
    assert not (_doc_ids(resp) & {"ECOURTS-EFILING", "ECOURTS-CASE-STATUS"}), _doc_ids(resp)


def test_husband_threatening_classifies_to_womens_domain():
    """Spec: explicit wording must route to women_rights/family, never 'general'."""
    cat = legal_triage.classify_category("My husband is threatening me")
    assert cat in ("women_rights", "family"), cat


def test_online_threat_classifies_to_cyber():
    assert legal_triage.classify_category("Someone is threatening me online") == "cyber"


def test_unsupported_hindi_never_calls_llm_and_invents_nothing(rag):
    """No-hallucination must hold for Devanagari too: a made-up Hindi 'law' returns
    no context, no sources and never reaches the LLM."""
    resp = legal_rag.answer("यह काल्पनिक कानून 999999 क्या है")
    assert resp["no_context"] is True and resp["grounded"] is False
    assert resp["sources"] == []
    assert resp["answer"] == legal_rag.NO_CONTEXT_MESSAGE
    assert resp["evidence_level"] == "INSUFFICIENT_EVIDENCE"
    assert len(_fake_ai.CALLS) == 0
    # Deterministic safety help is still surfaced.
    assert resp["legal_aid"]["helplines"] and resp["emergency_resources"]


# ═══ 7. Deterministic normalization + concept expansion (talaak / तलाक़ fix) ═══
# Reported bug: "talaak" / "talak" / "talaaq" / "तलाक़" (nukta) and mixed-language
# phrasing returned no_context while canonical "divorce"/"talaq"/"तलाक" worked.
# The fix is a deterministic normalization + concept-expansion layer — NOT a
# lowered grounding threshold and NOT a bare keyword list. These specs lock in
# that behaviour and prove there is no over-firing / topic leak / floor lowering.
_DIVORCE_SURFACE_FORMS = [
    "talaak", "talaq", "talak", "talaaq", "divorce", "khula",
    "तलाक", "तलाक़", "मुझे तलाक़ चाहिए",
    "mujhe talaak chahiye", "meko talak lena hai", "i want talaaq",
    "how do I get talak from my husband",
]


def test_normalize_devanagari_folds_the_nukta():
    """तलाक़ (…क + combining nukta U+093C) and precomposed क़ (U+0958) both fold to
    the nukta-less corpus form so a surface variant matches the literal keyword."""
    assert legal_triage._NUKTA == "़"
    assert legal_triage.normalize_devanagari("तलाक़") == "तलाक"
    assert legal_triage.normalize_devanagari("क़") == "क"
    assert legal_triage.normalize_devanagari("divorce") == "divorce"   # ASCII untouched
    assert legal_triage.normalize_devanagari("") == ""


def test_phonetic_fold_converges_romanised_divorce_variants():
    key = legal_triage.phonetic_fold("talak")
    for v in ("talaq", "talaak", "talak", "talaaq"):
        assert legal_triage.phonetic_fold(v) == key, v
    assert legal_triage.phonetic_fold("khulaa") == legal_triage.phonetic_fold("khula")
    assert legal_triage.phonetic_fold("Divorce") == legal_triage.phonetic_fold("divorce")
    assert legal_triage.phonetic_fold("तलाक") == "तलाक"   # non-Latin returned unchanged


def test_legal_concepts_are_structured_not_a_bare_keyword_list():
    for c in legal_triage.LEGAL_CONCEPTS:
        assert c.get("id") and c.get("category") and c.get("aliases") and c.get("expansions")
    cats = {c["category"] for c in legal_triage.LEGAL_CONCEPTS}
    assert {"family", "women_rights", "police", "cyber", "legal_aid"} <= cats
    assert any(c["id"] == "divorce" and c["category"] == "family"
               for c in legal_triage.LEGAL_CONCEPTS)


@pytest.mark.parametrize("q", _DIVORCE_SURFACE_FORMS)
def test_divorce_variants_classify_to_family(q):
    concepts = legal_triage.match_concepts(q)
    assert concepts and concepts[0]["id"] == "divorce", q
    assert legal_triage.classify_category(q) == "family", q


def test_expand_query_injects_only_on_topic_terms():
    exp = set(legal_triage.expand_query("talaak"))
    assert {"divorce", "talaq", "तलाक"} <= exp
    assert not ({"dowry", "fir", "cyber"} & exp)           # no unrelated topic bleed
    rt = legal_triage.retrieval_tokens("talaak")
    assert "talaak" in rt and "divorce" in rt and "talaq" in rt
    # The public query_tokens() contract is intentionally unchanged (no leakage).
    assert legal_triage.query_tokens("talaak") == ["talaak"]


@pytest.mark.parametrize("q", [
    "florblax quxzzy vrombat plonk",
    "what is the weather today",
    "यह काल्पनिक कानून 999999 क्या है",
])
def test_no_concept_over_fires_for_unrelated_queries(q):
    assert legal_triage.match_concepts(q) == []
    assert legal_triage.expand_query(q) == []


@pytest.mark.parametrize("q", _DIVORCE_SURFACE_FORMS)
def test_divorce_surface_forms_are_grounded_and_cite_hma(rag, q):
    """Every transliterated / nukta / mixed-language divorce query reaches the SAME
    verified Hindu Marriage Act source as the canonical term — never no_context."""
    resp = legal_rag.answer(q)
    assert resp["no_context"] is False and resp["grounded"] is True, q
    assert resp["sources"], q
    assert resp["topic"] == "family", (q, resp["topic"])
    assert any(did.startswith("HMA-1955") for did in _doc_ids(resp)), (q, _doc_ids(resp))


def test_normalization_does_not_lower_the_grounding_floor(rag):
    """Retrieval was improved, thresholds were NOT lowered: nonsense and an
    unsupported Devanagari 'law' still return no_context with no LLM call and no
    invented sources."""
    _fake_ai.CALLS.clear()
    r = legal_rag.answer("florblax quxzzy vrombat plonk")
    assert r["no_context"] is True and r["grounded"] is False and r["sources"] == []
    assert len(_fake_ai.CALLS) == 0
    r = legal_rag.answer("यह काल्पनिक कानून 999999 क्या है")
    assert r["no_context"] is True and r["sources"] == []


def test_nukta_divorce_does_not_leak_dv_or_ecourts_sources(rag):
    """Concept expansion adds only the divorce concept's own canonical terms, so a
    divorce query cannot pull the domestic-violence or eCourts-navigation docs."""
    r = legal_rag.answer("मुझे तलाक़ चाहिए")
    assert "PWDVA-2005-S3-S12" not in _doc_ids(r), _doc_ids(r)
    r = legal_rag.answer("mujhe talaak chahiye")
    assert not (_doc_ids(r) & {"ECOURTS-EFILING", "ECOURTS-CASE-STATUS"}), _doc_ids(r)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
