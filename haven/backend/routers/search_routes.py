"""Search & Intelligence router — keyword / semantic / hybrid over Case & Profile Intelligence.

Modes (Phases 7-8) delegate to services.search_service, which uses the existing
MongoDB Atlas $vectorSearch. Authorization is enforced server-side:
  * Case search is authority-only (cases are sensitive).
  * Profile search (semantic AND exact/keyword) is authority-only — profile
    intelligence is sensitive (P1-3).
Similarity is presented as a lead ("Semantically similar …"), never as proof of
guilt or identity.
"""
import logging
from fastapi import APIRouter, Body, Query, Depends, HTTPException
from auth import AuthUser, require_authority
from rate_limiter import rate_limit_dependency
from services.db import culprits, serialize_doc
from services.audit_service import log_audit
from services.search_service import search_cases, search_profiles, SEARCH_MODES

logger = logging.getLogger("haven_backend")
router = APIRouter(prefix="/search", tags=["Search & Intelligence"])


def _norm_results(items):
    """serialize_doc each result (handles datetimes/ObjectIds safely)."""
    return [serialize_doc(r) for r in items]


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

    Authorization: authority/admin only (P1-3). Profile intelligence is sensitive,
    so this now mirrors the sibling case-search endpoint (/search/semantic) — it
    previously allowed any authenticated USER. Role comes from the verified token
    via require_authority; no body/query/header field can grant access. The search
    algorithm, ranking, limits, response schema, and rate limiting are unchanged.
    """
    query = body.get("description") or body.get("query", "")
    limit = body.get("limit", 10)
    mode = str(body.get("mode", "semantic")).lower()
    if not str(query).strip():
        raise HTTPException(status_code=400, detail="description required")
    if mode not in SEARCH_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {list(SEARCH_MODES)}")

    result = search_profiles(query=query, limit=limit, mode=mode)
    log_audit(actor_id=current_user.user_id, role=current_user.role, action="PROFILE_SEARCHED",
              metadata={"query": str(query)[:100], "type": "profile_search",
                        "mode": result["search_mode"], "count": result["total"]})
    return {
        "matches": _norm_results(result["matches"]),
        "query": result["query"],
        "total": result["total"],
        "search_type": result["search_mode"],
        "search_mode": result["search_mode"],
        "degraded": result["degraded"],
    }


@router.get("/exact")
def search_exact_profiles(
    name: str = Query(..., min_length=1, max_length=100),
    current_user: AuthUser = Depends(require_authority)
):
    """Exact + partial name lookup (keyword mode preserved for precise matching).

    Authority-only (P1-3): this reads the same sensitive culprit / profile
    intelligence records as /search/profiles, so it mirrors that endpoint's
    authorization instead of the previous plain get_current_user (which let any
    authenticated user enumerate the profile DB by name). Role comes from the
    verified token via require_authority; the search behaviour, projection,
    limits and response schema are unchanged.
    """
    import re
    collection = culprits()
    if collection is None:
        return {"matches": [], "query": name, "total": 0}

    escaped = re.escape(name.strip())
    exact = list(collection.find(
        {"name": {"$regex": f"^{escaped}$", "$options": "i"}},
        {"_id": 0, "description_embedding": 0}
    ).limit(10))
    if exact:
        for r in exact:
            r["score"] = 1.0
        return {"matches": [serialize_doc(r) for r in exact], "query": name,
                "total": len(exact), "match_type": "exact"}

    partial = list(collection.find(
        {"name": {"$regex": escaped, "$options": "i"}},
        {"_id": 0, "description_embedding": 0}
    ).limit(10))
    for r in partial:
        r["score"] = 0.9
    return {"matches": [serialize_doc(r) for r in partial], "query": name,
            "total": len(partial), "match_type": "partial"}
