"""
validate_legal_normalization.py — dependency-free regression validator for the
Hindi / Hinglish legal-query normalization + expansion layer.

Reported issue: queries like "talaak", "talak", "talaaq", "तलाक़" (with a nukta)
and mixed-language phrasing returned NO verified source (no_context), while the
canonical "divorce"/"talaq"/"तलाक" worked. The fix is a deterministic
normalization + concept-expansion layer in services.legal_triage (nukta fold,
phonetic key, maintainable LEGAL_CONCEPTS map) wired into legal_rag retrieval —
NOT a lowered grounding threshold and NOT a giant keyword list.

This harness stubs the DB/embedding/LLM backends in-memory (exactly like
validate_legal_corpus.py), seeds the REAL verified corpus, and proves:
  A) unit behaviour of normalize_devanagari / phonetic_fold / match_concepts /
     expand_query / retrieval_tokens / classify_category, and
  B) end-to-end: every divorce surface-form + mixed-language query is grounded,
     cites the Hindu Marriage Act, and is NOT no_context — while an unrelated /
     nonsense query still returns no_context (no over-firing, no hallucination).

Run from haven/backend:  python validate_legal_normalization.py
Exit 0 = all passed; 1 = one or more failed.
"""
import re
import sys
import types

# ── Stub heavy backends BEFORE importing services.legal_rag (keyword-only mode) ─
_ai = types.ModuleType("services.ai_service")
_ai.CALLS = []
_ai.get_embedding = lambda text, *a, **k: [0.0] * 768
_ai.call_groq = lambda messages, *a, **k: (_ai.CALLS.append(messages) or "GROUNDED_STUB [1]")

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
    lt = legal_triage

    print("── Unicode / nukta normalization ──")
    check(lt._NUKTA == "़", "nukta constant is U+093C", repr(lt._NUKTA))
    # तलाक़ (with combining nukta) folds to तलाक (no nukta) used by the corpus.
    check(lt.normalize_devanagari("तलाक़") == "तलाक",
          "तलाक़ (nukta) -> तलाक", lt.normalize_devanagari("तलाक़"))
    # precomposed क़ (U+0958) also folds to base क.
    check(lt.normalize_devanagari("क़") == "क", "precomposed क़ (U+0958) -> क")
    check(lt.normalize_devanagari("divorce") == "divorce", "ASCII unchanged by normalization")
    check(lt.normalize_devanagari("") == "", "empty string safe")

    print("── Phonetic folding (romanised variants converge) ──")
    key = lt.phonetic_fold("talak")
    for v in ("talaq", "talaak", "talak", "talaaq"):
        check(lt.phonetic_fold(v) == key, f"phonetic_fold('{v}') == phonetic_fold('talak')",
              lt.phonetic_fold(v))
    check(lt.phonetic_fold("khulaa") == lt.phonetic_fold("khula"), "khulaa == khula")
    check(lt.phonetic_fold("तलाक") == "तलाक", "Devanagari token unchanged by fold")
    check(lt.phonetic_fold("Divorce") == lt.phonetic_fold("divorce"), "fold is case-insensitive")

    print("── Concept map structure (maintainable, not a bare keyword list) ──")
    ok_struct = all(
        c.get("id") and c.get("category") and c.get("aliases") and c.get("expansions")
        for c in lt.LEGAL_CONCEPTS)
    check(ok_struct, "every concept has id/category/aliases/expansions")
    check(any(c["id"] == "divorce" and c["category"] == "family" for c in lt.LEGAL_CONCEPTS),
          "divorce concept maps to family")
    cats = {c["category"] for c in lt.LEGAL_CONCEPTS}
    check({"family", "women_rights", "police", "cyber", "legal_aid"} <= cats,
          "concept map spans multiple legal domains", str(cats))

    print("── match_concepts routes variants -> divorce/family (deterministic) ──")
    divorce_variants = ["talaak", "talaq", "talak", "talaaq", "divorce",
                        "तलाक", "तलाक़", "khula",
                        "mujhe talaak chahiye", "meko talak lena hai",
                        "I want talaaq from my husband", "मुझे तलाक़ चाहिए"]
    for q in divorce_variants:
        cs = lt.match_concepts(q)
        check(bool(cs) and cs[0]["id"] == "divorce",
              f"match_concepts('{q}') -> divorce", str([c['id'] for c in cs]))
        check(lt.classify_category(q) == "family", f"classify_category('{q}') == family",
              lt.classify_category(q))

    print("── expand_query injects ONLY on-topic canonical corpus terms ──")
    exp = set(lt.expand_query("talaak"))
    check({"divorce", "talaq", "तलाक"} <= exp, "talaak expands to divorce/talaq/तलाक", str(exp))
    check("dowry" not in exp and "fir" not in exp and "cyber" not in exp,
          "talaak does NOT expand into unrelated topics", str(exp))
    rt = lt.retrieval_tokens("talaak")
    check("talaak" in rt and "divorce" in rt and "talaq" in rt,
          "retrieval_tokens keeps original token + adds expansions", str(rt))
    check(lt.query_tokens("talaak") == ["talaak"],
          "query_tokens() public contract unchanged (no expansion leakage)",
          str(lt.query_tokens("talaak")))

    print("── No over-firing: unrelated / nonsense queries are NOT expanded ──")
    for q in ("florblax quxzzy vrombat plonk", "what is the weather today",
              "यह काल्पनिक कानून 999999 क्या है"):
        check(lt.match_concepts(q) == [], f"no concept fires for '{q}'",
              str([c['id'] for c in lt.match_concepts(q)]))
        check(lt.expand_query(q) == [], f"no expansion for '{q}'")

    # ── Seed the REAL verified corpus through the real ingest path ──────────────
    print("── Seeding verified corpus ──")
    entries = legal_corpus.all_entries()
    ing = 0
    for e in entries:
        res = legal_rag.ingest_document(
            title=e["title"], text=e["text"], source_name=e.get("authority", ""),
            source_url=e.get("source_url", ""), jurisdiction=e.get("jurisdiction", "India"),
            section=e.get("section", ""), verification_status="verified",
            document_version=str(e.get("version", "1")), uploaded_by="validator",
            document_id=e["document_id"], metadata=e)
        ing += res.get("chunks_ingested", 0)
    check(ing >= 30, "seeded >=30 verified chunks", f"got {ing}")

    print("── End-to-end: every divorce variant is grounded + cites HMA (NOT no_context) ──")
    for q in ["talaak", "talaq", "talak", "talaaq", "divorce",
              "तलाक", "तलाक़", "मुझे तलाक़ चाहिए",
              "mujhe talaak chahiye", "meko talak chahiye",
              "i want talaaq", "how do I get talak from my husband"]:
        _ai.CALLS.clear()
        r = legal_rag.answer(q)
        check(not r["no_context"] and r["grounded"] and r["sources"],
              f"'{q}' -> grounded, NOT no_context", f"no_context={r['no_context']}")
        check(any(d.startswith("HMA-1955") for d in ids(r)),
              f"'{q}' cites Hindu Marriage Act", str(ids(r)))
        check(r["topic"] == "family", f"'{q}' topic == family", r.get("topic"))

    print("── Grounding floor NOT lowered: nonsense still returns no_context ──")
    _ai.CALLS.clear()
    r = legal_rag.answer("florblax quxzzy vrombat plonk")
    check(r["no_context"] and not r["grounded"] and r["sources"] == []
          and len(_ai.CALLS) == 0,
          "nonsense -> no_context, no LLM call, no invented sources")
    r = legal_rag.answer("यह काल्पनिक कानून 999999 क्या है")
    check(r["no_context"] and not r["grounded"] and r["sources"] == [],
          "unsupported Hindi -> no_context (no over-expansion)")

    print("── No topic leak: divorce expansion must not pull DV / eCourts sources ──")
    r = legal_rag.answer("मुझे तलाक़ चाहिए")
    check("PWDVA-2005-S3-S12" not in ids(r),
          "nukta divorce does NOT leak the domestic-violence source", str(ids(r)))
    r = legal_rag.answer("mujhe talaak chahiye")
    check("ECOURTS-EFILING" not in ids(r) and "ECOURTS-CASE-STATUS" not in ids(r),
          "transliterated divorce does NOT surface incidental eCourts navigation", str(ids(r)))

    print(f"\n==== {_PASS} passed, {len(_FAILS)} failed ====")
    if _FAILS:
        print("FAILURES:")
        for f in _FAILS:
            print("  - " + f)
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
