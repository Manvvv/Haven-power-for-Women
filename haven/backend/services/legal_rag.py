"""
Legal Assistant RAG service (Phase: RAG Legal Assistant).

Grounded retrieval-augmented generation over VERIFIED legal documents, using the
EXISTING infrastructure:
  * embeddings   -> services.embeddings.embed / embedding_info
  * vector store -> MongoDB Atlas $vectorSearch on legal_docs.embedding ("legalIndex")
  * LLM          -> services.ai_service.call_groq (Groq + Gemini fallback)

Pipeline:  question -> embed -> vector search -> filter weak matches
           -> constrained context -> LLM -> grounded answer + citations.

Safety guarantees:
  * If no sufficiently relevant verified passage is retrieved, we DO NOT call the
    LLM to invent an answer — we return an explicit no-context message.
  * The generation prompt constrains the model to the retrieved context and
    forbids inventing laws, sections, or citations.
  * Citations only ever contain passages that were actually retrieved & used.
  * When embeddings are unavailable (DEMO/FALLBACK) we transparently fall back to
    keyword retrieval and label it, rather than pretending semantic RAG ran.
"""
import hashlib
import logging
import os
import re
from datetime import datetime

from services.db import legal_docs, serialize_doc
from services.embeddings import embed, embedding_info, EMBEDDING_DIM
from services import legal_triage

logger = logging.getLogger("haven_backend")

# Corpus version surfaced in responses / health checks (kept in sync with legal_corpus).
CORPUS_VERSION = "2026-09-25"

# Minimum cosine similarity (Atlas vectorSearchScore) for a passage to count as
# relevant. Below this, we treat retrieval as "no sufficient evidence".
MIN_SCORE = float(os.getenv("HAVEN_LEGAL_MIN_SCORE", "0.55"))

DISCLAIMER = (
    "This assistant provides general legal information and does not constitute "
    "formal legal advice; it is not a substitute for consultation with a qualified "
    "legal professional."
)

NO_CONTEXT_MESSAGE = (
    "I couldn't find enough verified source material to answer this confidently. "
    "Please consult a qualified legal professional. For urgent help in India you can "
    "call NALSA (15100) or the NCW helpline (7827170170)."
)

LLM_UNAVAILABLE_MESSAGE = (
    "I retrieved relevant legal sources but the answer-generation service is "
    "temporarily unavailable. The source passages are listed below so you can "
    "review them directly, and please consult a qualified legal professional."
)

CITATION_UNVERIFIED_MESSAGE = (
    "I drafted an answer but could not verify all of its citations against the "
    "verified sources that were retrieved, so I am not showing that draft to avoid a "
    "misleading or fabricated reference. The verified source passages are listed below "
    "for you to review directly, and please consult a qualified legal professional."
)


# ─── text cleaning + chunking ────────────────────────────────────────────────
_WS = re.compile(r"[ \t]+")
_MULTINL = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalise extracted document text without destroying structure."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _MULTINL.sub("\n\n", text)
    return text.strip()


def chunk_document(text: str, max_chars: int = 1200, overlap: int = 150) -> list:
    """Split cleaned text into meaningful, slightly-overlapping chunks.

    Paragraph-aware: packs whole paragraphs up to `max_chars`; a paragraph longer
    than the limit is split on sentence boundaries. Overlap preserves context
    across chunk edges. Deterministic (same input -> same chunks).
    """
    text = clean_text(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for para in paragraphs:
        if len(para) > max_chars:
            flush()
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sbuf = ""
            for s in sentences:
                if len(sbuf) + len(s) + 1 > max_chars:
                    if sbuf.strip():
                        chunks.append(sbuf.strip())
                    # start next with overlap tail
                    sbuf = (sbuf[-overlap:] + " " if overlap and sbuf else "") + s
                else:
                    sbuf = f"{sbuf} {s}".strip()
            if sbuf.strip():
                chunks.append(sbuf.strip())
        elif len(buf) + len(para) + 2 > max_chars:
            flush()
            buf = para
        else:
            buf = f"{buf}\n\n{para}".strip()
    flush()
    return chunks


def _chunk_hash(document_id: str, text: str) -> str:
    return hashlib.sha256(f"{document_id}::{text}".encode("utf-8")).hexdigest()


# ─── ingestion ───────────────────────────────────────────────────────────────
def ingest_document(
    *,
    title: str,
    text: str,
    source_name: str = "",
    source_url: str = "",
    jurisdiction: str = "India",
    section: str = "",
    verification_status: str = "verified",
    document_version: str = "1",
    uploaded_by: str = "system",
    document_id: str = "",
    metadata: dict = None,
) -> dict:
    """Chunk + embed + store a verified legal document.

    Returns {document_id, chunks_ingested, chunks_skipped, embedding_status, error?}.
    Deduplicates by chunk_hash so re-ingesting the same document does not create
    duplicate embeddings. `metadata` (e.g. authority_level, category, keywords,
    act_name, authority, source_type, effective_date, last_verified, language,
    state, court) is stored alongside each chunk to power hybrid retrieval.
    """
    coll = legal_docs()
    if coll is None:
        return {"document_id": document_id, "chunks_ingested": 0, "chunks_skipped": 0,
                "embedding_status": embedding_info()["status"], "error": "Database unavailable"}

    title = (title or "").strip()[:300]
    if not title or not (text or "").strip():
        return {"document_id": document_id, "chunks_ingested": 0, "chunks_skipped": 0,
                "embedding_status": embedding_info()["status"], "error": "title and text are required"}

    if not document_id:
        document_id = f"LEGAL-{int(datetime.utcnow().timestamp())}"

    chunks = chunk_document(text)
    if not chunks:
        return {"document_id": document_id, "chunks_ingested": 0, "chunks_skipped": 0,
                "embedding_status": embedding_info()["status"], "error": "no extractable text"}

    einfo = embedding_info()
    now = datetime.utcnow()
    ingested = skipped = 0

    for idx, chunk in enumerate(chunks):
        h = _chunk_hash(document_id, chunk)
        # Dedup: skip if this exact chunk already stored for this document.
        if coll.count_documents({"chunk_hash": h}, limit=1):
            skipped += 1
            continue
        embedding = embed(chunk)
        doc = {
            "document_id": document_id,
            "chunk_index": idx,
            "chunk_id": f"{document_id}-{idx}",
            "chunk_hash": h,
            "title": title,
            "text": chunk,
            "source": source_name[:200] or title,          # back-compat field
            "source_name": source_name[:200] or title,
            "source_url": source_url[:500],
            "jurisdiction": jurisdiction[:100],
            "section": section[:120],
            "verification_status": verification_status,
            "embedding": embedding,
            "embedding_model": einfo["model_name"],
            "document_version": str(document_version),
            "uploaded_by": uploaded_by,
            "created_at": now,
            "updated_at": now,
        }
        # Merge extra verified metadata (authority_level, category, keywords, …)
        # without letting it overwrite the core fields above.
        if metadata:
            for mk, mv in metadata.items():
                if mk not in doc and mk not in ("_id", "embedding", "chunk_hash"):
                    doc[mk] = mv
        coll.insert_one(doc)
        ingested += 1

    return {"document_id": document_id, "chunks_ingested": ingested,
            "chunks_skipped": skipped, "embedding_status": einfo["status"]}


# ─── retrieval ───────────────────────────────────────────────────────────────
def _searchable(doc: dict) -> str:
    """Concatenated searchable fields of a passage (for keyword-ratio scoring)."""
    parts = [str(doc.get("title", "")), str(doc.get("section", "")),
             str(doc.get("act_name", "")), str(doc.get("text", ""))]
    kws = doc.get("keywords")
    if isinstance(kws, (list, tuple)):
        parts.append(" ".join(str(x) for x in kws))
    return " ".join(parts)


def _keyword_retrieve(question: str, k: int) -> list:
    """Verified passages matching ANY meaningful query token.

    Tokenises the question (stopwords removed) into an OR-regex and searches
    title / section / act_name / keywords / text — fixing the previous bug where
    the whole question was escaped as one literal substring (matching nothing).
    """
    coll = legal_docs()
    if coll is None:
        return []
    tokens = legal_triage.retrieval_tokens(question)
    if not tokens:
        return []
    rx = {"$regex": "|".join(re.escape(t) for t in tokens), "$options": "i"}
    query = {"$and": [
        {"verification_status": "verified"},
        {"$or": [{"text": rx}, {"title": rx}, {"section": rx},
                 {"act_name": rx}, {"keywords": rx}]},
    ]}
    docs = list(coll.find(query, {"_id": 0, "embedding": 0}).limit(max(k * 4, 20)))
    for d in docs:
        d["score"] = None  # keyword mode has no similarity score
    return docs


def _merge_rerank(semantic: list, keyword: list, question: str, k: int,
                  semantic_available: bool) -> list:
    """Merge semantic + keyword passages, drop incidental (substring-only) matches,
    then rerank by a field-weighted precise-keyword score + source authority.

    Precise whole-word matching (legal_triage.match_profile) is what preserves the
    no-hallucination guarantee in keyword-only mode: the Mongo prefilter uses a coarse
    OR-regex that can substring-match (e.g. "pati" inside "participating", "कानून"
    inside "कानूनी"), so any passage with NO whole-word token overlap AND no genuine
    semantic-similarity hit is discarded here rather than surfaced as a weak citation.
    """
    tokens = legal_triage.retrieval_tokens(question)
    q_category = legal_triage.classify_category(question)

    def _key(d):
        return d.get("chunk_id") or f"{d.get('document_id')}::{d.get('chunk_index')}"

    def _structured(d):
        kws = d.get("keywords")
        kw_txt = " ".join(str(x) for x in kws) if isinstance(kws, (list, tuple)) else ""
        return " ".join([str(d.get("title", "")), str(d.get("section", "")),
                         str(d.get("act_name", "")), kw_txt])

    def _curated_keywords(d):
        """Just the human-curated keyword list — the highest-signal 'what is this doc
        actually about' field (excludes title/section/act, which can carry incidental
        tokens such as the acronym 'FIR' inside an otherwise unrelated explainer)."""
        kws = d.get("keywords")
        kw_txt = " ".join(str(x) for x in kws) if isinstance(kws, (list, tuple)) else ""
        return legal_triage.field_token_set(kw_txt)

    merged: dict = {}
    for d in list(semantic) + list(keyword):
        kk = _key(d)
        if kk not in merged:
            merged[kk] = dict(d)
        elif merged[kk].get("score") is None and d.get("score") is not None:
            merged[kk]["score"] = d.get("score")   # prefer a real similarity score

    ranked = []
    for d in merged.values():
        sem = float(d["score"]) if isinstance(d.get("score"), (int, float)) else 0.0
        semantic_hit = d.get("score") is not None   # came from $vectorSearch (>= min_score)
        s_hits, b_hits, cat_match = legal_triage.match_profile(
            tokens, _structured(d), str(d.get("text", "")),
            d.get("category"), q_category)
        kw_hits = sum(1 for t in tokens if t in _curated_keywords(d))  # curated-list hits
        # Keep-gate. On-topic passages (category match) are always kept. An off-topic
        # passage is retained only with real, non-incidental support:
        #   • a genuine semantic-similarity hit, OR
        #   • a hit in its CURATED keyword list (its declared subject), OR
        #   • two or more body whole-word hits.
        # This drops off-topic passages that matched only on an incidental token in the
        # title/section/act or a lone body word — e.g. the missing-child helpline (whose
        # keywords are all about missing children) surfacing for a "police won't file my
        # FIR" query solely because its text mentions filing an FIR. A primary on-topic
        # statute is never dropped; only clearly-irrelevant cross-topic noise is.
        strong_match = semantic_hit or cat_match or kw_hits > 0 or b_hits >= 2
        if not strong_match:
            continue
        kw = legal_triage.precise_relevance(tokens, s_hits, b_hits, cat_match)
        auth = legal_triage.authority_weight(d.get("authority_level"))
        d["_blended"] = round(legal_triage.blended_score(sem, kw, auth, semantic_available), 6)
        d["_kw_ratio"] = round(kw, 4)
        d["_precise_hits"] = s_hits + b_hits
        d["_cat_match"] = bool(cat_match)
        ranked.append(d)
    # Primary sort: blended score. Tie-breakers: on-topic category, precise-hit count,
    # then source authority — so a primary statute outranks incidental navigation hits.
    ranked.sort(key=lambda x: (x["_blended"], x.get("_cat_match", False),
                               x.get("_precise_hits", 0),
                               legal_triage.authority_weight(x.get("authority_level"))),
                reverse=True)
    return ranked[:k]


def retrieve(question: str, k: int = 5, min_score: float = None) -> dict:
    """Hybrid retrieval (semantic + keyword) over VERIFIED passages.

    Returns {passages, mode, degraded, semantic_available}.
    """
    min_score = MIN_SCORE if min_score is None else min_score
    coll = legal_docs()
    if coll is None:
        return {"passages": [], "mode": "none", "degraded": True, "semantic_available": False}

    einfo = embedding_info()
    semantic_available = bool(einfo.get("semantic_search_available"))
    semantic_passages = []

    if semantic_available:
        qvec = embed(question)
        try:
            raw = list(coll.aggregate([
                {"$vectorSearch": {"index": "legalIndex", "path": "embedding",
                                   "queryVector": qvec, "numCandidates": max(50, k * 10),
                                   "limit": k * 3}},
                {"$project": {"_id": 0, "embedding": 0,
                              "score": {"$meta": "vectorSearchScore"}}},
            ]))
            semantic_passages = [
                d for d in raw
                if float(d.get("score", 0.0)) >= min_score
                and d.get("verification_status", "verified") == "verified"
            ]
        except Exception as e:
            logger.warning("legal vector search failed, keyword only: %s", e)
            semantic_available = False

    keyword_passages = _keyword_retrieve(question, k)
    merged = _merge_rerank(semantic_passages, keyword_passages, question, k, semantic_available)

    if semantic_available:
        mode = "hybrid" if keyword_passages else "semantic"
        degraded = False
    else:
        mode = "keyword_fallback"
        degraded = True
    return {"passages": merged, "mode": mode, "degraded": degraded,
            "semantic_available": semantic_available}


# ─── citations ───────────────────────────────────────────────────────────────
def _build_citations(passages: list) -> list:
    """Distinct citations from the passages ACTUALLY retrieved (order preserved)."""
    seen, cites = set(), []
    for p in passages:
        title = p.get("title") or p.get("source_name") or p.get("source") or "Verified source"
        section = p.get("section") or ""
        key = (title, section)
        if key in seen:
            continue
        seen.add(key)
        cites.append({
            "document_id": p.get("document_id"),
            "title": title,
            "section": section,
            "act_name": p.get("act_name", ""),
            "authority": p.get("authority", ""),
            "authority_level": p.get("authority_level", ""),
            "source_type": p.get("source_type", ""),
            "source_url": p.get("source_url", ""),
            "last_verified": p.get("last_verified", ""),
            "effective_date": p.get("effective_date", ""),
            "relevance_score": (round(float(p["score"]), 4) if p.get("score") is not None else None),
            "match_strength": p.get("_kw_ratio"),
            "excerpt": (p.get("text", "")[:240] + ("…" if len(p.get("text", "")) > 240 else "")),
        })
    return cites


# ─── grounded answer ─────────────────────────────────────────────────────────
_LANG_INSTRUCTION = {
    "en": "Respond in clear, simple English.",
    "hi": "Respond in Hindi (Devanagari script), in clear, simple language.",
    "hinglish": "Respond in simple Hindi written in the Roman script (Hinglish), matching the user's style.",
}
# Languages the legal assistant can phrase grounded prose in (spec §12/§31). Other
# languages fall back to English — the LLM never fabricates a translated statute.
SUPPORTED_RESPONSE_LANGS = ["en", "hi", "hinglish"]

# Fixed, context-constrained grounded-answer instruction (audit gap #10). Kept as a
# module constant so its version + fingerprint can be tracked in prompt_registry;
# the per-request language line and retrieved context are appended at call time.
_LEGAL_SYSTEM_INSTRUCTION = (
    "You are Haven's legal information assistant for women in India. Answer ONLY "
    "using the numbered legal context provided. Rules:\n"
    "- Do NOT invent laws, sections, case names, citations, fees, deadlines or helpline numbers.\n"
    "- Use the law exactly as named in the context (e.g. current codes like BNS/BNSS 2023 "
    "if that is what the context says); do not substitute older codes.\n"
    "- If the context does not contain the answer, say you cannot confirm it from the "
    "available verified sources and recommend a qualified lawyer or legal aid.\n"
    "- Clearly separate what the LAW says from PRACTICAL next steps.\n"
    "- Do NOT claim a lawyer reviewed this or that any court/case database was queried.\n"
    "- Be compassionate and concise. Refer to sources by their [number] where relevant."
)
try:
    from services import prompt_registry as _PR
    _PR.attach("legal_grounded", _LEGAL_SYSTEM_INSTRUCTION)
    LEGAL_PROMPT_VERSION = _PR.version("legal_grounded")
except Exception:  # observability must never break retrieval/answering
    LEGAL_PROMPT_VERSION = "legal-grounded-v1"


def _first_sentences(text: str, n: int = 2, limit: int = 320) -> str:
    """A short, honest summary = the first N sentences of the grounded answer."""
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(parts[:n]).strip()
    return (summary[:limit] + "…") if len(summary) > limit else summary


def _scaffold(tri: dict, evidence_level: str, language_hint: str = None) -> dict:
    """Deterministic (non-LLM) structured fields shared by every response branch."""
    state = tri.get("state") or ""
    jurisdiction = f"India — {state}" if state else "India"
    lang = tri.get("language", "en")
    req = (language_hint or "").strip().lower() or None
    fallback_used = bool(req and req not in SUPPORTED_RESPONSE_LANGS and req != lang)
    return {
        "topic": tri.get("category", "general"),
        "jurisdiction": jurisdiction,
        "state": state,
        "language": lang,
        # Language contract (spec §31) — additive, no classifier reasoning exposed.
        "detected_language": lang,
        "response_language": lang,
        "supported_languages": SUPPORTED_RESPONSE_LANGS,
        "fallback_used": fallback_used,
        "urgency": tri.get("urgency", "normal"),
        "emergency": bool(tri.get("emergency")),
        "immediate_danger": bool(tri.get("immediate_danger")),
        "children_involved": bool(tri.get("children_involved")),
        "evidence_level": evidence_level,
        "clarifying_questions": tri.get("clarifying_questions", []),
        "next_steps": tri.get("next_steps", []),
        "evidence_checklist": tri.get("evidence_checklist", []),
        "legal_aid": tri.get("legal_aid", {}),
        "emergency_resources": tri.get("helplines", []),
        "triage_version": tri.get("triage_version", ""),
        "corpus_version": CORPUS_VERSION,
    }


def answer(question: str, user_id: str = "anonymous", k: int = 5,
           language_hint: str = None, state_hint: str = None) -> dict:
    """Full hybrid-RAG flow with deterministic triage scaffolding.

    Returns a dict safe to serialize as the API response. The LLM is ONLY used to
    phrase prose grounded in retrieved verified passages; all structured guidance
    (topic, urgency, helplines, next steps, checklist) is deterministic and never
    fabricates law. If no verified passage is found, the LLM is not called at all.
    """
    question = (question or "").strip()[:1000]
    einfo = embedding_info()
    base_meta = {
        "embedding_backend": einfo["backend"],
        "embedding_model": einfo["model_name"],
        "embedding_status": einfo["status"],
        "llm_provider": "groq+gemini-fallback",
        "is_demo_mode": einfo["status"] in ("DEMO", "FALLBACK"),
    }

    tri = legal_triage.triage(question, language_hint=language_hint, state_hint=state_hint)

    if not question:
        scaffold = _scaffold(tri, "INSUFFICIENT_EVIDENCE", language_hint)
        return {**scaffold,
                "answer": "Please enter a legal question.", "summary": "", "sources": [],
                "grounded": False, "no_context": False, "disclaimer": DISCLAIMER,
                "status": "empty_query", "retrieval_mode": "none", "model_info": base_meta,
                "retrieved_document_ids": []}

    result = retrieve(question, k=k)
    passages = result["passages"]
    retrieved_ids = [p.get("document_id") for p in passages if p.get("document_id")]

    # ── RELEVANCE FLOOR (audit #12): "some source was retrieved" is NOT enough to
    #    ground. A passage kept by the reranker only on a single incidental keyword
    #    hit is insufficient evidence. Require at least one passage that clears the
    #    deterministic relevance floor (reusing the reranker's own _blended /
    #    _kw_ratio / _precise_hits / _cat_match signals + the semantic score). If
    #    the floor is not met we take the SAME safe no-context path below and never
    #    call the LLM merely because weak sources exist. ──
    relevance = legal_triage.assess_relevance(passages)
    grounding_ok = bool(passages) and bool(relevance["passes"])
    # Evidence is only as strong as the floor allows: weak-but-present retrieval is
    # reported as INSUFFICIENT_EVIDENCE, never MEDIUM/HIGH.
    evidence_level = (legal_triage.compute_evidence_level(passages)
                      if grounding_ok else "INSUFFICIENT_EVIDENCE")
    scaffold = _scaffold(tri, evidence_level, language_hint)

    # ── No sufficiently relevant evidence -> never hallucinate law. Still return
    #    safe deterministic triage help (helplines, next steps, legal aid). This
    #    covers BOTH "nothing retrieved" and "retrieved but below the floor". ──
    if not grounding_ok:
        return {
            **scaffold,
            "answer": NO_CONTEXT_MESSAGE, "summary": "", "sources": [], "grounded": False,
            "no_context": True, "disclaimer": DISCLAIMER, "status": "no_context",
            "retrieval_mode": result["mode"], "degraded": result["degraded"],
            "model_info": base_meta, "retrieved_document_ids": [],
            "relevance": {"passes": False, "best_blended": relevance["best_blended"],
                          "reason": relevance["reason"]},
        }

    citations = _build_citations(passages)
    context_blocks = []
    for i, p in enumerate(passages, 1):
        label = p.get("title") or p.get("source_name") or "Source"
        sec = f" — {p.get('section')}" if p.get("section") else ""
        act = f" ({p.get('act_name')})" if p.get("act_name") else ""
        context_blocks.append(f"[{i}] {label}{sec}{act}\n{p.get('text','')}")
    context = "\n\n".join(context_blocks)

    lang_line = _LANG_INSTRUCTION.get(tri.get("language", "en"), _LANG_INSTRUCTION["en"])
    system = (
        f"{_LEGAL_SYSTEM_INSTRUCTION}\n"
        f"- {lang_line}\n\n"
        f"### VERIFIED LEGAL CONTEXT ###\n{context}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question: {question}"},
    ]

    try:
        from services.ai_service import call_groq
        generated = call_groq(messages).strip()
        status = "grounded"
    except Exception as e:
        logger.warning("legal RAG generation failed: %s", e)
        # Retrieval SUCCEEDED (verified sources exist) but GENERATION failed.
        # These two states must never be conflated: we surface the verified
        # sources + an explicit llm_unavailable status and never fabricate an
        # answer. `**scaffold` is spread first so it can never clobber the
        # authoritative status / sources / answer contract below.
        return {
            **scaffold,
            "answer": LLM_UNAVAILABLE_MESSAGE, "summary": "", "sources": citations,
            "grounded": True, "no_context": False, "disclaimer": DISCLAIMER,
            "status": "llm_unavailable", "retrieval_mode": result["mode"],
            "degraded": result["degraded"], "model_info": base_meta,
            "retrieved_document_ids": retrieved_ids,
        }

    # ── CITATION VALIDATION (audit #12): the LLM was instructed to cite sources as
    #    [n] markers referring to the numbered VERIFIED CONTEXT above. Before we
    #    surface the prose we deterministically confirm every [n] marker maps to a
    #    real retrieved source (1..len(citations)). A marker like [9] when only 3
    #    sources were retrieved is a fabricated reference — we DO NOT silently mark
    #    grounded=true. Instead we degrade safely: withhold the unverifiable draft,
    #    preserve the genuinely-retrieved verified sources for the user to read
    #    directly, and never expose an invented citation. ──
    cit_check = legal_triage.validate_citations(generated, len(citations))
    if not cit_check["valid"]:
        logger.warning("legal RAG citation validation failed: %s", cit_check["invalid"])
        return {
            **scaffold,
            "answer": CITATION_UNVERIFIED_MESSAGE, "summary": "", "sources": citations,
            "grounded": False, "no_context": False, "disclaimer": DISCLAIMER,
            "status": "citation_check_failed", "degraded": True,
            "retrieval_mode": result["mode"], "model_info": base_meta,
            "retrieved_document_ids": retrieved_ids,
            "citation_check": {"valid": False, "invalid_ids": cit_check["invalid"],
                               "cited_ids": cit_check["cited"], "reason": cit_check["reason"]},
        }

    return {
        **scaffold,
        "answer": generated,
        "summary": _first_sentences(generated),
        "sources": citations,
        "grounded": True,
        "no_context": False,
        "disclaimer": DISCLAIMER,
        "status": status,
        "retrieval_mode": result["mode"],
        "degraded": result["degraded"],
        "model_info": base_meta,
        "retrieved_document_ids": retrieved_ids,
        "citation_check": {"valid": True, "cited_ids": cit_check["cited"]},
    }
