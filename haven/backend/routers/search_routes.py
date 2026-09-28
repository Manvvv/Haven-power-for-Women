"""Search & Intelligence router — keyword / semantic / hybrid over Case & Profile Intelligence.

CASE search (`/search/semantic`) delegates to services.search_service over the
existing MongoDB Atlas $vectorSearch.

PROFILE search (`/search/profiles`, `/search/exact`) now delegates to the SINGLE
canonical, hardened matcher `services.profile_search.run_profile_search` — the
same implementation used by `/culprit/find-match`. There is no longer a second,
weaker profile matcher: every profile/culprit matching path converges here, so
each one gets query classification, deterministic name search, field-aware
hybrid description search, coarse retrieval levels (never identity confidence),
the SAFE_PUBLIC_MATCH_FIELDS output allowlist, mandatory human verification and
transparent degraded-mode handling. Raw record fields, raw scores and embedding
vectors are never returned.

Authorization is enforced server-side and is unchanged:
  * Case search is authority-only (cases are sensitive).
  * Profile search (semantic AND exact/keyword) is authority-only — profile
    intelligence is sensitive (P1-3).
Similarity is presented as a lead, never as proof of guilt or identity.
"""
import logging
from fastapi import APIRouter, Body, Query, Depends, HTTPException
from auth import AuthUser, require_authority
from rate_limiter import rate_limit_dependency
from services.db import culprits, serialize_doc
from services.audit_service import log_audit
from services.search_service import search_cases, SEARCH_MODES
from services.profile_search import (
    run_profile_search,
    ProfileSearchError,
    PROFILE_MATCH_DISCLAIMER,
)

logger = logging.getLogger("haven_backend")
router = APIRouter(prefix="/search", tags=["Search & Intelligence"])


def _norm_results(items):
    """serialize_doc each result (handles datetimes/ObjectIds safely)."""
    return [serialize_doc(r) for r in items]


def _profile_match_response(result: dict, query: str) -> dict:
    """Uniform, safe response for every profile-matching endpoint.

    `result` is the output of `profile_search.run_profile_search`; its `matches`
    have already passed through the SAFE_PUBLIC_MATCH_FIELDS allowlist, carry a
    coarse retrieval `match_level` (NOT identity confidence) and never include
    the embedding vector, reporter identity or Mongo `_id`. Legacy response keys
    (`matches` / `query` / `total` / `search_type` / `search_mode` / `degraded`)
    are preserved for existing callers; the canonical `results`, `query_type`,
    `human_verification_required` and `disclaimer` are added.
    """
    matches = result["matches"]
    return {
        "matches": matches,                    # back-compat key (existing frontend/tests)
        "results": matches,                    # canonical structured-contract key
        "query": query,
        "total": len(matches),
        "query_type": result["query_type"],
        "search_type": result["search_type"],
        "search_mode": result["search_type"],  # legacy alias preserved
        "degraded": result["degraded"],
        "human_verification_required": True,
        "disclaimer": PROFILE_MATCH_DISCLAIMER,
    }


@router.post("/semantic")
def search_semantic_cases(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60))
):
    """Search SOS cases. Body: {query, limit?, mode?=keyword|semantic|hybrid}.

    Authority-only. Preserves the previous default (semantic) when `mode` omitted.
    """
    query = body.get("query", "")
    limit = body.get("limit", 10)
    mode = str(body.get("mode", "semantic")).lower()
    if not str(query).strip():
        raise HTTPException(status_code=400, detail="query required")
    if mode not in SEARCH_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {list(SEARCH_MODES)}")

    result = search_cases(query=query, limit=limit, mode=mode)
    log_audit(actor_id=current_user.user_id, role=current_user.role, action="PROFILE_SEARCHED",
              metadata={"query": str(query)[:100], "type": "case_search",
                        "mode": result["search_mode"], "count": result["total"]})
    return {
        "results": _norm_results(result["results"]),
        "query": result["query"],
        "total": result["total"],
        "search_type": result["search_mode"],
        "search_mode": result["search_mode"],
        "degraded": result["degraded"],
    }


@router.post("/profiles")
def search_semantic_profiles(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60))
):
    """Search Case & Profile Intelligence records. Body: {description|query, limit?, mode?}.

    Authorization: authority/admin only (P1-3) — role comes from the verified
    token via require_authority; no body/query/header field can grant access.

    This endpoint now delegates to the SAME canonical hardened matcher as
    `/culprit/find-match` (`profile_search.run_profile_search`), instead of the
    old raw-field / raw-score `search_service.search_profiles`. The legacy `mode`
    (keyword|semantic|hybrid) is still validated for backward compatibility, but
    query routing is now handled canonically: the matcher classifies name vs
    description automatically and blends keyword + semantic with a transparent
    keyword fallback when the embedding backend is unavailable. Results are
    allowlisted (no raw internal fields), carry a coarse retrieval level and are
    flagged human_verification_required. A real backend failure returns 503 —
    never a misleading empty result. The rate limit (30/60s) is unchanged.
    """
    query = body.get("description") or body.get("query", "")
    limit = body.get("limit", 10)
    mode = str(body.get("mode", "semantic")).lower()
    if not str(query).strip():
        raise HTTPException(status_code=400, detail="description required")
    if mode not in SEARCH_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {list(SEARCH_MODES)}")

    collection = culprits()
    if collection is None:
        raise HTTPException(status_code=503, detail="Profile search is temporarily unavailable.")

    try:
        # "auto" lets the canonical classifier route name vs description; the
        # hybrid matcher already handles the keyword/semantic blend + fallback.
        result = run_profile_search(collection, str(query), "auto", limit)
    except ProfileSearchError:
        raise HTTPException(status_code=503, detail="Profile search is temporarily unavailable.")

    # Audit: query TYPE + count only — NEVER the raw query text (privacy).
    log_audit(actor_id=current_user.user_id, role=current_user.role, action="PROFILE_SEARCHED",
              metadata={"type": "profile_search", "query_type": result["query_type"],
                        "search_type": result["search_type"], "count": len(result["matches"]),
                        "degraded": result["degraded"]})
    return _profile_match_response(result, str(query))


@router.get("/exact")
def search_exact_profiles(
    name: str = Query(..., min_length=1, max_length=100),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Exact / partial name lookup for profile intelligence.

    Authority-only (P1-3): this reads the same sensitive culprit / profile
    intelligence records as /search/profiles. It now routes through the canonical
    hardened matcher in NAME mode (`run_profile_search(..., "name", ...)`) instead
    of a bespoke regex lookup that fabricated a flat 1.0/0.9 score and serialized
    raw documents (leaking reporter identity and other internal fields). NAME mode
    is fully deterministic — exact, reordered, all-terms, substring and a
    conservative transliteration fold — with real per-tier scores, the
    SAFE_PUBLIC_MATCH_FIELDS allowlist and mandatory human verification. A real
    backend failure returns 503 rather than a misleading empty result.
    """
    collection = culprits()
    if collection is None:
        raise HTTPException(status_code=503, detail="Profile search is temporarily unavailable.")

    try:
        result = run_profile_search(collection, name, "name", 10)
    except ProfileSearchError:
        raise HTTPException(status_code=503, detail="Profile search is temporarily unavailable.")

    # Audit: query TYPE + count only — NEVER the raw name text (privacy). This
    # closes a prior gap where exact name lookups were not audited at all.
    log_audit(actor_id=current_user.user_id, role=current_user.role, action="PROFILE_SEARCHED",
              metadata={"type": "profile_exact", "query_type": result["query_type"],
                        "search_type": result["search_type"], "count": len(result["matches"])})
    return _profile_match_response(result, name)
