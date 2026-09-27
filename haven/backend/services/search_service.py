"""
Case & Profile Intelligence search service (Phases 7-8).

Three explicit modes over the EXISTING MongoDB Atlas $vectorSearch setup — no
infrastructure migration:

    keyword   — deterministic text/regex matching (exact behaviour preserved).
    semantic  — embedding + Atlas $vectorSearch (unchanged index/path).
    hybrid    — deterministic blend of keyword relevance + semantic similarity.

Design notes:
  * Every result is normalised to ONE shape (see `_shape_case` / `_shape_profile`)
    with id, score, excerpt, severity, status, timestamp and search_mode.
  * Semantic matches are labelled "Semantically similar ..." — similarity is a
    lead, never a claim of guilt or identity (requirement 10).
  * If embeddings are unavailable (DEMO/FALLBACK), semantic & hybrid transparently
    fall back to keyword and set `degraded=True` + `search_mode="keyword_fallback"`.
  * Hybrid ranking is fully deterministic (fixed weights, stable tie-break on id).
"""
import re
import logging

from services.db import sos_cases, culprits, serialize_doc
from services.embeddings import embed, embedding_info

logger = logging.getLogger("haven_backend")

# Deterministic hybrid weights. Semantic is weighted a little higher than
# keyword because it captures paraphrase, but keyword keeps precise matches
# competitive. Fixed values -> reproducible ranking.
_W_SEMANTIC = 0.6
_W_KEYWORD = 0.4

SEARCH_MODES = ("keyword", "semantic", "hybrid")

_CASE_LABEL = "Semantically similar case"
_PROFILE_LABEL = "Semantically similar profile"


# ─── helpers ────────────────────────────────────────────────────────────────
def _excerpt(text: str, query: str, width: int = 160) -> str:
    """Return a short excerpt around the first query-term hit, else the head."""
    if not text:
        return ""
    text = str(text)
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    low = text.lower()
    pos = -1
    for t in terms:
        pos = low.find(t)
        if pos != -1:
            break
    if pos == -1:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def _semantic_available() -> bool:
    return bool(embedding_info().get("semantic_search_available"))


def _keyword_score(text: str, query: str) -> float:
    """Deterministic 0..1 keyword relevance: fraction of distinct query terms
    present, with a small bonus for an exact phrase hit."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return 0.0
    low = (text or "").lower()
    hits = sum(1 for t in set(terms) if t in low)
    base = hits / len(set(terms))
    phrase_bonus = 0.15 if query.strip().lower() in low else 0.0
    return round(min(base + phrase_bonus, 1.0), 4)


# ─── result shaping (uniform contract) ──────────────────────────────────────
def _shape_case(doc: dict, query: str, mode: str, score: float, semantic: bool) -> dict:
    text = doc.get("decoded_text") or doc.get("summary") or ""
    return {
        "id": doc.get("case_id"),
        "case_id": doc.get("case_id"),
        "score": round(float(score), 4),
        "excerpt": _excerpt(text, query),
        "severity": doc.get("severity", "unknown"),
        "status": doc.get("status", "unknown"),
        "timestamp": doc.get("created_at"),
        "search_mode": mode,
        "match_label": _CASE_LABEL if semantic else "Keyword match",
        "trigger_type": doc.get("trigger_type"),
    }


def _shape_profile(doc: dict, query: str, mode: str, score: float, semantic: bool) -> dict:
    text = f"{doc.get('physical_description','')} {doc.get('behavioral_traits','')}"
    return {
        "id": doc.get("culprit_id"),
        "culprit_id": doc.get("culprit_id"),
        "name": doc.get("name", "Unknown"),
        "score": round(float(score), 4),
        "excerpt": _excerpt(text, query),
        "physical_description": doc.get("physical_description", ""),
        "behavioral_traits": doc.get("behavioral_traits", ""),
        "location": doc.get("location", ""),
        "timestamp": doc.get("created_at"),
        "search_mode": mode,
        "match_label": _PROFILE_LABEL if semantic else "Keyword match",
    }


# ─── CASE search ─────────────────────────────────────────────────────────────
def _keyword_cases(query: str, limit: int) -> list:
    coll = sos_cases()
    if coll is None:
        return []
    esc = re.escape(query[:120])
    docs = list(coll.find(
        {"$or": [
            {"decoded_text": {"$regex": esc, "$options": "i"}},
            {"summary": {"$regex": esc, "$options": "i"}},
            {"nature_of_abuse": {"$regex": esc, "$options": "i"}},
        ]},
        {"_id": 0, "embedding": 0, "evidence": 0},
    ).limit(limit * 3))
    scored = [(_keyword_score(d.get("decoded_text", "") + " " + d.get("summary", ""), query), d) for d in docs]
    scored.sort(key=lambda x: (-x[0], str(x[1].get("case_id", ""))))
    return scored[:limit]


def _semantic_cases(query: str, limit: int) -> list:
    coll = sos_cases()
    if coll is None:
        return []
    qvec = embed(query)
    results = list(coll.aggregate([
        {"$vectorSearch": {"index": "casesIndex", "path": "embedding",
                           "queryVector": qvec, "numCandidates": max(50, limit * 5), "limit": limit}},
        {"$project": {"_id": 0, "embedding": 0, "evidence": 0,
                      "score": {"$meta": "vectorSearchScore"}}},
    ]))
    return [(float(d.get("score", 0.0)), d) for d in results]


def search_cases(query: str, limit: int = 10, mode: str = "semantic") -> dict:
    """Unified case search. Returns {results, query, total, search_mode, degraded}."""
    query = (query or "").strip()[:500]
    limit = max(1, min(int(limit or 10), 50))
    mode = mode if mode in SEARCH_MODES else "semantic"
    if not query:
        return {"results": [], "query": query, "total": 0, "search_mode": mode,
                "degraded": False, "error": "query required"}

    coll = sos_cases()
    if coll is None:
        return {"results": [], "query": query, "total": 0, "search_mode": mode, "degraded": False}

    degraded = False
    effective = mode
    if mode in ("semantic", "hybrid") and not _semantic_available():
        degraded = True
        effective = "keyword_fallback"

    try:
        if effective == "keyword" or effective == "keyword_fallback":
            scored = _keyword_cases(query, limit)
            out = [_shape_case(d, query, effective, s, semantic=False) for s, d in scored]
        elif effective == "semantic":
            scored = _semantic_cases(query, limit)
            out = [_shape_case(d, query, "semantic", s, semantic=True) for s, d in scored]
        else:  # hybrid
            out = _hybrid_cases(query, limit)
    except Exception as e:
        logger.warning("case search (%s) failed, keyword fallback: %s", effective, e)
        degraded = True
        scored = _keyword_cases(query, limit)
        out = [_shape_case(d, query, "keyword_fallback", s, semantic=False) for s, d in scored]

    return {"results": out, "query": query, "total": len(out),
            "search_mode": out[0]["search_mode"] if out else effective, "degraded": degraded}


def _hybrid_cases(query: str, limit: int) -> list:
    """Deterministic blend of keyword + semantic for cases, keyed by case_id."""
    kw = {d.get("case_id"): (s, d) for s, d in _keyword_cases(query, limit * 2)}
    sem = {d.get("case_id"): (s, d) for s, d in _semantic_cases(query, limit * 2)}
    # Normalise semantic scores to 0..1 within this result set.
    sem_scores = [s for s, _ in sem.values()]
    smax, smin = (max(sem_scores), min(sem_scores)) if sem_scores else (1.0, 0.0)
    span = (smax - smin) or 1.0

    combined = {}
    for cid in set(kw) | set(sem):
        k = kw.get(cid, (0.0, None))
        s = sem.get(cid, (0.0, None))
        doc = k[1] or s[1]
        kscore = k[0]
        sscore = (s[0] - smin) / span if cid in sem else 0.0
        final = _W_KEYWORD * kscore + _W_SEMANTIC * sscore
        combined[cid] = (final, doc, cid in sem)
    ranked = sorted(combined.items(), key=lambda kv: (-kv[1][0], str(kv[0])))[:limit]
    return [_shape_case(doc, query, "hybrid", final, semantic=is_sem)
            for _, (final, doc, is_sem) in ranked]


# ─── PROFILE search ──────────────────────────────────────────────────────────
def _keyword_profiles(query: str, limit: int) -> list:
    coll = culprits()
    if coll is None:
        return []
    esc = re.escape(query[:120])
    docs = list(coll.find(
        {"$or": [
            {"name": {"$regex": esc, "$options": "i"}},
            {"physical_description": {"$regex": esc, "$options": "i"}},
            {"behavioral_traits": {"$regex": esc, "$options": "i"}},
        ]},
        {"_id": 0, "description_embedding": 0},
    ).limit(limit * 3))
    scored = [(_keyword_score(f"{d.get('name','')} {d.get('physical_description','')} {d.get('behavioral_traits','')}", query), d) for d in docs]
    scored.sort(key=lambda x: (-x[0], str(x[1].get("culprit_id", ""))))
    return scored[:limit]


def _semantic_profiles(query: str, limit: int) -> list:
    coll = culprits()
    if coll is None:
        return []
    qvec = embed(query)
    results = list(coll.aggregate([
        {"$vectorSearch": {"index": "culpritIndex", "path": "description_embedding",
                           "queryVector": qvec, "numCandidates": max(30, limit * 5), "limit": limit}},
        {"$project": {"_id": 0, "description_embedding": 0,
                      "score": {"$meta": "vectorSearchScore"}}},
    ]))
    return [(float(d.get("score", 0.0)), d) for d in results]


def search_profiles(query: str, limit: int = 10, mode: str = "semantic") -> dict:
    """Unified profile search. Same contract as search_cases (matches key)."""
    query = (query or "").strip()[:500]
    limit = max(1, min(int(limit or 10), 30))
    mode = mode if mode in SEARCH_MODES else "semantic"
    if not query:
        return {"matches": [], "query": query, "total": 0, "search_mode": mode,
                "degraded": False, "error": "query required"}

    coll = culprits()
    if coll is None:
        return {"matches": [], "query": query, "total": 0, "search_mode": mode, "degraded": False}

    degraded = False
    effective = mode
    if mode in ("semantic", "hybrid") and not _semantic_available():
        degraded = True
        effective = "keyword_fallback"

    try:
        if effective in ("keyword", "keyword_fallback"):
            scored = _keyword_profiles(query, limit)
            out = [_shape_profile(d, query, effective, s, semantic=False) for s, d in scored]
        elif effective == "semantic":
            scored = _semantic_profiles(query, limit)
            out = [_shape_profile(d, query, "semantic", s, semantic=True) for s, d in scored]
        else:
            out = _hybrid_profiles(query, limit)
    except Exception as e:
        logger.warning("profile search (%s) failed, keyword fallback: %s", effective, e)
        degraded = True
        scored = _keyword_profiles(query, limit)
        out = [_shape_profile(d, query, "keyword_fallback", s, semantic=False) for s, d in scored]

    return {"matches": out, "query": query, "total": len(out),
            "search_mode": out[0]["search_mode"] if out else effective, "degraded": degraded}


def _hybrid_profiles(query: str, limit: int) -> list:
    kw = {d.get("culprit_id"): (s, d) for s, d in _keyword_profiles(query, limit * 2)}
    sem = {d.get("culprit_id"): (s, d) for s, d in _semantic_profiles(query, limit * 2)}
    sem_scores = [s for s, _ in sem.values()]
    smax, smin = (max(sem_scores), min(sem_scores)) if sem_scores else (1.0, 0.0)
    span = (smax - smin) or 1.0
    combined = {}
    for pid in set(kw) | set(sem):
        k = kw.get(pid, (0.0, None))
        s = sem.get(pid, (0.0, None))
        doc = k[1] or s[1]
        sscore = (s[0] - smin) / span if pid in sem else 0.0
        final = _W_KEYWORD * k[0] + _W_SEMANTIC * sscore
        combined[pid] = (final, doc, pid in sem)
    ranked = sorted(combined.items(), key=lambda kv: (-kv[1][0], str(kv[0])))[:limit]
    return [_shape_profile(doc, query, "hybrid", final, semantic=is_sem)
            for _, (final, doc, is_sem) in ranked]
