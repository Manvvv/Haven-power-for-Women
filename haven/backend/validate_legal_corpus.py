"""
validate_legal_corpus.py — dependency-free integrity + behaviour validator.

Runs WITHOUT pytest, pymongo, or any API key: it stubs the database, embedding
and LLM backends in-memory, seeds the real verified corpus through the real
`legal_rag.ingest_document`, and asserts the grounded-RAG spec behaviours
(retrieval, citations, no-hallucination guard, evidence levels, triage).

Use it as a fast smoke test in constrained environments / CI:

    cd haven/backend && python validate_legal_corpus.py

Exit code 0 = all checks passed; 1 = one or more failures (details printed).
The full pytest suite (test_legal_rag.py) covers the same behaviour with more
granularity and should be run on the dev machine.
"""
import re
import sys
import types

# ── Stub heavy backends BEFORE importing services.legal_rag ──────────────────
_ai = types.ModuleType("services.ai_service")
_ai.CALLS = []
_ai.get_embedding = lambda text, *a, **k: [0.0] * 768
_ai.call_groq = lambda messages, *a, **k: (_ai.CALLS.append(messages) or "STUB_GROUNDED_ANSWER [1]")

_emb = types.ModuleType("services.embeddings")
_emb.EMBEDDING_DIM = 768
_emb.embed = lambda text: []
_emb.embedding_info = lambda: {"backend": "stub", "model_name": "stub", "status": "DEMO",
                               "semantic_search_available": False}

_db = types.ModuleType("services.db")


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def limit(self, n):
        return _Cursor(self._docs[: int(n)])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self):
        self.docs = []

    def _mf(self, value, cond):
        if isinstance(cond, dict) and "$regex" in cond:
            rx = re.compile(cond["$regex"], re.I if "i" in cond.get("$options", "") else 0)
            if isinstance(value, (list, tuple)):
                return any(rx.search(str(v)) for v in value)
            return value is not None and bool(rx.search(str(value)))
        if isinstance(value, (list, tuple)):
            return cond in value
        return value == cond

    def _match(self, doc, q):
        for key, cond in q.items():
            if key == "$and":
                if not all(self._match(doc, s) for s in cond):
                    return False
            elif key == "$or":
                if not any(self._match(doc, s) for s in cond):
                    return False
            elif not self._mf(doc.get(key), cond):
                return False
        return True

    def _project(self, doc, projection):
        if not projection:
            return dict(doc)
        exc = {k for k, v in projection.items() if v == 0}
        return {k: v for k, v in doc.items() if k not in exc}

    def count_documents(self, q, limit=None):
        c = 0
        for d in self.docs:
            if self._match(d, q):
                c += 1
                if limit and c >= limit:
                    return c
        return c

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def find(self, q, projection=None):
        return _Cursor(self._project(d, projection) for d in self.docs if self._match(d, q))

    def distinct(self, field):
        return list({d.get(field) for d in self.docs if d.get(field) is not None})

    def aggregate(self, pipeline):
        return iter([])


_FAKE_COLL = FakeCollection()
_db.legal_docs = lambda: _FAKE_COLL
_db.serialize_doc = lambda d: d

sys.modules["services.ai_service"] = _ai
sys.modules["services.embeddings"] = _emb
sys.modules["services.db"] = _db

from services import legal_corpus, legal_triage, legal_rag  # noqa: E402

_PASS = 0
_FAILS = []


def check(cond, name, detail=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAILS.append(name)
        print(f"  FAIL  {name}  {detail}")


def ids(resp):
    return {s.get("document_id") for s in resp.get("sources", [])}


def main():
    entries = legal_corpus.all_entries()
    doc_ids = {e["document_id"] for e in entries}
    valid_auth = {"tier1_primary_statute", "tier1_primary_authority",
                  "tier2_official_explanatory", "tier3_secondary"}

    print("── Corpus integrity ──")
    check(len(entries) >= 30, "corpus has >=30 entries", f"got {len(entries)}")
    check(len(doc_ids) == len(entries), "document_ids unique")
    check(all(e["verification_status"] == "verified" for e in entries), "all entries verified")
    check(all(e["act_name"] and e["section"] for e in entries), "all entries carry a citation")
    check(all(e["authority_level"] in valid_auth for e in entries), "authority_level valid")
    check(all(str(e["source_url"]).startswith("http") for e in entries), "source_urls are links")
    cats = {e["category"] for e in entries}
    check({"family", "women_rights", "child_safety", "police", "cyber", "workplace",
           "legal_aid", "court_navigation"} <= cats, "all required domains covered", str(cats))

    joined = " ".join(e["text"] for e in entries)
    check("Bharatiya Nyaya Sanhita" in joined and "Bharatiya Nagarik Suraksha Sanhita" in joined,
          "current BNS/BNSS codes present")
    stale_ok = True
    for e in entries:
        low = e["text"].lower()
        if any(s in low for s in ("indian penal code", "code of criminal procedure", "ipc", "498a", "crpc")):
            if not ("historical" in low or "successor" in low or "former" in low):
                stale_ok = False
    check(stale_ok, "old codes only appear as labelled historical references")

    print("── Deterministic triage ──")
    check(legal_triage.classify_category("i want divorce") == "family", "divorce -> family")
    q = legal_triage.build_query("mujhe apne pati se talaq chahiye")
    check(q.language == "hinglish" and q.category == "family", "hinglish talaq -> family/hinglish")
    q = legal_triage.build_query("police refused to file my FIR in Maharashtra")
    check(q.category == "police" and q.state == "Maharashtra" and q.language == "en",
          "FIR -> police/Maharashtra/en")
    q = legal_triage.build_query("my child is missing")
    check(q.category == "child_safety" and q.urgency in ("high", "emergency"),
          "missing child -> child_safety/high")
    tri = legal_triage.triage("he is hitting me right now")
    check(tri["emergency"] and tri["immediate_danger"] and tri["helplines"][0]["number"] == "112",
          "immediate danger -> emergency + 112 first")
    check(legal_triage.build_query("dowry case in Karnataka").state == "Karnataka", "state extraction")

    print("── Evidence confidence + scoring ──")
    check(legal_triage.compute_evidence_level([]) == "INSUFFICIENT_EVIDENCE", "no passages -> INSUFFICIENT")
    check(legal_triage.compute_evidence_level(
        [{"authority_level": "tier1_primary_statute"}] * 2) == "HIGH", "two tier1 -> HIGH")
    check(legal_triage.compute_evidence_level(
        [{"authority_level": "tier2_official_explanatory"}]) == "MEDIUM", "tier2 only -> MEDIUM")
    check(legal_triage.query_tokens("How do I get a divorce?") == ["divorce"], "query_tokens strips stopwords")
    check(abs(legal_triage.blended_score(0.0, 0.5, 0.6, False) - 0.525) < 1e-9, "blended keyword mode")

    print("── Grounded RAG (seeded corpus) ──")
    _ai.CALLS.clear()
    ing = 0
    for e in entries:
        res = legal_rag.ingest_document(
            title=e["title"], text=e["text"], source_name=e.get("authority", ""),
            source_url=e.get("source_url", ""), jurisdiction=e.get("jurisdiction", "India"),
            section=e.get("section", ""), verification_status="verified",
            document_version=str(e.get("version", "1")), uploaded_by="validator",
            document_id=e["document_id"], metadata=e)
        ing += res.get("chunks_ingested", 0)
    check(ing >= 30, "seeded >=30 chunks", f"got {ing}")
    check(_FAKE_COLL.count_documents({}) == ing, "collection holds all seeded chunks")

    r = legal_rag.answer("i want divorce")
    check(r["grounded"] and not r["no_context"] and r["sources"], "divorce query grounded+cited")
    check(any(d.startswith("HMA-1955") for d in ids(r)), "divorce cites Hindu Marriage Act", str(ids(r)))
    check(r["topic"] == "family", "divorce topic=family")

    r = legal_rag.answer("How do I get emergency custody of my children?")
    check(r["grounded"] and (ids(r) & {"EMERGENCY-INTERIM-CUSTODY", "GWA-1890-CUSTODY",
          "HMGA-1956-S6", "FAMILY-COURTS-ACT-1984", "VISITATION"}),
          "emergency custody grounded w/ custody sources", str(ids(r)))

    r = legal_rag.answer("my husband and in-laws beat me and demand dowry")
    check("BNS-2023-S85-S86" in ids(r), "cruelty cites current BNS 2023", str(ids(r)))

    r = legal_rag.answer("how do I report cyber blackmail and leaked photos")
    check(all(s["document_id"] in doc_ids and s["title"] for s in r["sources"]),
          "no fabricated citations (all map to real corpus)")
    check(all(s["document_id"] in r["retrieved_document_ids"] for s in r["sources"]),
          "citations subset of retrieved ids")

    _ai.CALLS.clear()
    legal_rag.answer("what are the grounds for divorce")
    check(len(_ai.CALLS) == 1 and "VERIFIED LEGAL CONTEXT" in _ai.CALLS[0][0]["content"]
          and "Do NOT invent laws" in _ai.CALLS[0][0]["content"],
          "LLM invoked once, grounded + anti-fabrication prompt")

    _ai.CALLS.clear()
    r = legal_rag.answer("florblax quxzzy vrombat plonk")
    check(r["no_context"] and not r["grounded"] and r["sources"] == []
          and r["answer"] == legal_rag.NO_CONTEXT_MESSAGE and len(_ai.CALLS) == 0,
          "NO-HALLUCINATION: no match -> no LLM call, no invented sources")
    check(r["evidence_level"] == "INSUFFICIENT_EVIDENCE", "no match -> INSUFFICIENT_EVIDENCE")
    check(bool(r["legal_aid"]["helplines"]) and bool(r["emergency_resources"]),
          "no-context still returns safe triage help")

    r = legal_rag.answer("I cannot afford a lawyer, is there free legal help?")
    check(bool(ids(r) & {"LSA-1987-S12", "NALSA-HOW-TO-APPLY", "TELE-LAW-14454"}),
          "legal-aid query routes to free help", str(ids(r)))

    r = legal_rag.answer("how do I check my case status online")
    steps = " ".join(r["next_steps"]).lower()
    check("ECOURTS-CASE-STATUS" in ids(r) and "does not fetch live case status" in steps,
          "case-status is navigation-only, no live-fetch claim")

    r = legal_rag.answer("he is going to kill me tonight, save me")
    check(r["emergency"] and any(h["number"] == "112" for h in r["emergency_resources"]),
          "emergency query surfaces 112 routing")

    r = legal_rag.answer("what are the grounds for divorce")
    check(r["disclaimer"] == legal_rag.DISCLAIMER
          and r["corpus_version"] == legal_rag.CORPUS_VERSION
          and r["triage_version"] == legal_triage.TRIAGE_VERSION,
          "grounded answer carries disclaimer + versions")

    print("── Unicode tokenization (English + Devanagari + Hinglish) ──")
    dv = legal_triage.query_tokens("मुझे तलाक चाहिए")
    check({"मुझे", "तलाक", "चाहिए"} <= set(dv), "Devanagari query tokenized (मुझे/तलाक/चाहिए kept)", str(dv))
    check(legal_triage.query_tokens("How do I get a divorce?") == ["divorce"],
          "English tokenization unchanged (stopwords stripped)")
    check("498a" in legal_triage.query_tokens("what about 498a"), "alphanumeric token 498a preserved")
    police_toks = set(legal_triage.query_tokens("पुलिस FIR नहीं लिख रही"))
    check("पुलिस" in police_toks and "fir" in police_toks
          and "नहीं" not in police_toks and "रही" not in police_toks,
          "Hindi function words (नहीं/रही) dropped, legal terms + Latin kept", str(police_toks))

    print("── Hindi (Devanagari) grounded retrieval, keyword-only ──")
    r = legal_rag.answer("मुझे तलाक चाहिए")
    check(r["grounded"] and r["topic"] == "family" and any(d.startswith("HMA-1955") for d in ids(r)),
          "Hindi divorce -> family + Hindu Marriage Act", str(ids(r)))
    check("PWDVA-2005-S3-S12" not in ids(r),
          "Hindi divorce does NOT leak DV source via generic token मुझे", str(ids(r)))

    r = legal_rag.answer("पति मुझे मारता है")
    check(r["grounded"] and r["topic"] == "women_rights"
          and {"PWDVA-2005-S3-S12", "BNS-2023-S85-S86"} & ids(r),
          "Hindi domestic-violence -> women_rights + PWDVA/BNS", str(ids(r)))

    r = legal_rag.answer("मेरे बच्चे की कस्टडी चाहिए")
    check(r["grounded"] and bool(ids(r) & {"GWA-1890-CUSTODY", "EMERGENCY-INTERIM-CUSTODY", "HMGA-1956-S6"}),
          "Hindi custody -> guardianship/custody sources", str(ids(r)))

    r = legal_rag.answer("मुझे कानूनी सहायता चाहिए")
    check(r["grounded"] and bool(ids(r) & {"LSA-1987-S12", "NALSA-HOW-TO-APPLY", "TELE-LAW-14454"}),
          "Hindi legal-aid -> free-help sources", str(ids(r)))
    check("HMA-1955-S13" not in ids(r),
          "Hindi legal-aid does NOT leak divorce source via generic token चाहिए", str(ids(r)))

    r = legal_rag.answer("पुलिस FIR नहीं लिख रही")
    check(r["grounded"] and r["topic"] == "police"
          and bool(ids(r) & {"POLICE-REFUSAL-REMEDY", "BNSS-2023-S173-FIR", "ZERO-FIR"}),
          "Hindi FIR-refusal -> police/FIR sources", str(ids(r)))
    check("MISSING-CHILD-1098" not in ids(r),
          "Hindi FIR query does NOT leak missing-child helpline (incidental 'FIR' mention)", str(ids(r)))

    r = legal_rag.answer("मुझे ऑनलाइन धमकी मिल रही है")
    check(r["grounded"] and r["topic"] == "cyber" and "CYBER-REPORTING-PORTAL" in ids(r),
          "Hindi online-threat -> cyber reporting", str(ids(r)))

    print("── Hinglish (transliterated) retrieval ──")
    r = legal_rag.answer("mujhe talaq chahiye")
    check(r["grounded"] and r["topic"] == "family" and any(d.startswith("HMA-1955") for d in ids(r)),
          "Hinglish talaq -> family + Hindu Marriage Act", str(ids(r)))
    check("ECOURTS-EFILING" not in ids(r) and "ECOURTS-CASE-STATUS" not in ids(r),
          "Hinglish divorce does NOT surface incidental eCourts navigation", str(ids(r)))

    print("── Triage classification from explicit wording ──")
    check(legal_triage.classify_category("My husband is threatening me") in ("women_rights", "family"),
          "husband threatening -> women_rights/family (not general)")
    check(legal_triage.classify_category("Someone is threatening me online") == "cyber",
          "online threat -> cyber (distinguished by wording)")

    print("── No-hallucination on unsupported Hindi ──")
    _ai.CALLS.clear()
    r = legal_rag.answer("यह काल्पनिक कानून 999999 क्या है")
    check(r["no_context"] and not r["grounded"] and r["sources"] == []
          and r["answer"] == legal_rag.NO_CONTEXT_MESSAGE and len(_ai.CALLS) == 0,
          "unsupported Hindi -> no LLM call, no invented sources")
    check(r["evidence_level"] == "INSUFFICIENT_EVIDENCE", "unsupported Hindi -> INSUFFICIENT_EVIDENCE")
    check(bool(r["legal_aid"]["helplines"]) and bool(r["emergency_resources"]),
          "unsupported Hindi still returns safe triage help")

    # ══════════════ AUDIT #12: relevance floor + citation validation ══════════════
    print("── #12 relevance floor (assess_relevance, unit) ──")
    _strong = {"score": 0.9, "_blended": 0.8, "_cat_match": True, "_precise_hits": 3, "_kw_ratio": 0.9}
    _semantic_only = {"score": 0.62, "_blended": 0.45, "_cat_match": False, "_precise_hits": 0, "_kw_ratio": 0.0}
    _cat_one_hit = {"score": None, "_blended": 0.30, "_cat_match": True, "_precise_hits": 1, "_kw_ratio": 0.2}
    _weak = {"score": None, "_blended": 0.18, "_cat_match": False, "_precise_hits": 1, "_kw_ratio": 0.2}
    _incidental_sem = {"score": 0.55, "_blended": 0.20, "_cat_match": False, "_precise_hits": 0, "_kw_ratio": 0.0}
    check(legal_triage.assess_relevance([_strong])["passes"], "strong passage clears floor")
    check(legal_triage.assess_relevance([_semantic_only])["passes"],
          "genuine semantic hit above blended floor clears")
    check(legal_triage.assess_relevance([_cat_one_hit])["passes"],
          "on-topic (category) + 1 precise hit clears floor")
    check(not legal_triage.assess_relevance([_weak])["passes"],
          "lone incidental keyword hit (off-topic) BELOW floor -> rejected")
    check(not legal_triage.assess_relevance([_incidental_sem])["passes"],
          "semantic hit whose blended is below floor -> rejected")
    check(not legal_triage.assess_relevance([])["passes"]
          and legal_triage.assess_relevance([])["reason"] == "no_passages",
          "empty passages -> reject (no_passages)")
    check(legal_triage.assess_relevance([_weak, _strong])["qualifying"] == 1,
          "mixed batch: only qualifying passages counted")

    # REGRESSION GUARD (#12 follow-up): a canonical/legacy source that carries a
    # genuine semantic score but NONE of the private rerank-derived fields
    # (_blended/_kw_ratio/_precise_hits/_cat_match) MUST still clear the floor. This
    # is exactly the fixture shape used by TestLegalRAG.test_sources_with_llm_* /
    # test_llm_unavailable_* — retrieve() already dropped anything below MIN_SCORE,
    # so a surviving semantic hit is adequate. Prevents a future rerank refactor
    # from silently turning an adequate source into no_context.
    _legacy_semantic = {"title": "PWDVA 2005", "section": "Section 12",
                        "text": "Application to Magistrate.", "score": 0.82, "document_id": "D1"}
    check(legal_triage.normalize_passage(_legacy_semantic)["semantic_score"] == 0.82
          and legal_triage.normalize_passage(_legacy_semantic)["blended"] is None,
          "normalize_passage: legacy source has semantic_score, no derived blended")
    check(legal_triage.passage_qualifies(_legacy_semantic),
          "legacy/normalized semantic source (no _blended) still passes the floor")
    check(legal_triage.assess_relevance([_legacy_semantic])["passes"],
          "assess_relevance accepts legacy semantic-only source")
    check(not legal_triage.passage_qualifies({"score": 0.40}),
          "semantic-only source BELOW MIN_SCORE floor still rejected (floor intact)")

    print("── #12 citation validation (validate_citations, unit) ──")
    check(legal_triage.validate_citations("As per the Act [1], you may file.", 3)["valid"],
          "in-range citation [1] with 3 sources -> valid")
    check(legal_triage.validate_citations("See [1] and [2].", 2)["valid"],
          "multiple in-range citations -> valid")
    _oob = legal_triage.validate_citations("See [5] for details.", 3)
    check(not _oob["valid"] and _oob["invalid"] == [5] and _oob["reason"] == "fabricated_citation_id",
          "out-of-range citation [5] with 3 sources -> fabricated")
    check(not legal_triage.validate_citations("Refer to [0].", 3)["valid"],
          "citation [0] is invalid (1-indexed)")
    check(legal_triage.validate_citations("No markers, just prose.", 3)["valid"],
          "absence of markers is allowed (not fabricated)")
    check(not legal_triage.validate_citations("Per [1].", 0)["valid"],
          "any marker when zero sources retrieved -> fabricated")
    _multi = legal_triage.validate_citations("[1] then [4] then [2].", 3)
    check(not _multi["valid"] and _multi["invalid"] == [4] and _multi["cited"] == [1, 2, 4],
          "batch: only the out-of-range id flagged, all cited reported")

    print("── #12 relevance floor end-to-end (answer gating) ──")
    _orig_retrieve = legal_rag.retrieve
    try:
        # Retrieval returns a passage, but it is BELOW the relevance floor: "some
        # source was retrieved" must NOT ground. Expect the safe no-context path
        # and ZERO LLM calls.
        legal_rag.retrieve = lambda q, k=5, min_score=None: {
            "passages": [{"document_id": "WEAK-DOC", "title": "Weak", "text": "x",
                          "_blended": 0.15, "score": None, "_cat_match": False,
                          "_precise_hits": 1, "_kw_ratio": 0.1}],
            "mode": "keyword_fallback", "degraded": True, "semantic_available": False}
        _ai.CALLS.clear()
        r = legal_rag.answer("i want divorce")
        check(r["no_context"] and not r["grounded"] and r["sources"] == []
              and r["answer"] == legal_rag.NO_CONTEXT_MESSAGE and len(_ai.CALLS) == 0,
              "weak-but-present source -> no_context, NO LLM call")
        check(r["evidence_level"] == "INSUFFICIENT_EVIDENCE"
              and r.get("relevance", {}).get("reason") == "below_relevance_floor",
              "below-floor retrieval reported as INSUFFICIENT_EVIDENCE + reason")
        check(bool(r["legal_aid"]["helplines"]) and bool(r["emergency_resources"]),
              "below-floor still returns safe deterministic triage help")

        # A strongly-relevant passage clears the floor -> LLM IS allowed.
        legal_rag.retrieve = lambda q, k=5, min_score=None: {
            "passages": [{"document_id": "HMA-1955-S13", "title": "Hindu Marriage Act 1955",
                          "text": "Grounds for divorce under section 13.", "section": "13",
                          "act_name": "Hindu Marriage Act, 1955", "authority_level": "tier1_primary_statute",
                          "_blended": 0.82, "score": 0.9, "_cat_match": True,
                          "_precise_hits": 3, "_kw_ratio": 0.8}],
            "mode": "keyword_fallback", "degraded": True, "semantic_available": False}
        _ai.CALLS.clear()
        r = legal_rag.answer("i want divorce")
        check(r["grounded"] and not r["no_context"] and len(_ai.CALLS) == 1
              and r.get("citation_check", {}).get("valid") is True,
              "strongly-relevant source clears floor -> grounded + LLM called once")
    finally:
        legal_rag.retrieve = _orig_retrieve

    print("── #12 citation validation end-to-end (fabricated id degrades) ──")
    _orig_groq = _ai.call_groq
    try:
        # LLM cites [9] but at most k sources were retrieved -> fabricated reference.
        # Must NOT silently mark grounded=true: degrade safely, preserve the real
        # verified sources, and never surface the hallucinated draft.
        _ai.call_groq = lambda messages, *a, **k: (_ai.CALLS.append(messages)
                                                   or "You can file for divorce [9].")
        _ai.CALLS.clear()
        r = legal_rag.answer("i want divorce")
        check(r["status"] == "citation_check_failed" and not r["grounded"] and r["degraded"] is True,
              "fabricated citation id -> status citation_check_failed, grounded=False")
        check(r["answer"] == legal_rag.CITATION_UNVERIFIED_MESSAGE
              and "[9]" not in r["answer"],
              "fabricated draft withheld -> unverified-citation message surfaced instead")
        check(bool(r["sources"]) and all(s["document_id"] in doc_ids for s in r["sources"]),
              "fabricated citation -> genuinely retrieved verified sources preserved")
        check(r.get("citation_check", {}).get("invalid_ids") == [9],
              "citation_check reports the fabricated id [9]")
        check(len(_ai.CALLS) == 1, "LLM was called once (floor passed), fabrication caught post-hoc")

        # Sanity: a valid in-range citation from the same query is accepted.
        _ai.call_groq = lambda messages, *a, **k: (_ai.CALLS.append(messages)
                                                   or "Grounds for divorce are set out in [1].")
        r = legal_rag.answer("i want divorce")
        check(r["grounded"] and r["status"] == "grounded"
              and r.get("citation_check", {}).get("valid") is True,
              "valid in-range citation [1] -> grounded accepted")
    finally:
        _ai.call_groq = _orig_groq

    print("\n" + "=" * 60)
    print(f"RESULT: {_PASS} passed, {len(_FAILS)} failed")
    if _FAILS:
        print("FAILED:", ", ".join(_FAILS))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
