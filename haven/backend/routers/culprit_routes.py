"""Case & Profile Intelligence routes (formerly Culprit DB) + semantic case search.

Search now goes through `services.profile_search`:
  * NAME queries → deterministic lexical search (no embeddings, no similarity
    floor). A plain name like "nirmal nehra" can no longer be filtered out by a
    vector threshold.
  * DESCRIPTION / MIXED queries → field-aware hybrid (keyword + optional
    semantic), with a transparent keyword fallback when the embedding backend is
    unavailable. Scores are real; nothing is fabricated.

SAFETY: every result is an INVESTIGATIVE LEAD for human verification — never a
confirmation of guilt or identity. Access is authority/admin only, all actions
are audited (without raw queries or full descriptions), and embedding vectors
are never returned.
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Body, Depends, HTTPException
from auth import AuthUser, get_current_user, require_authority
from rate_limiter import rate_limit_dependency
from services.db import culprits, sos_cases, serialize_doc
from services.audit_service import log_audit
from services.search_service import search_cases, SEARCH_MODES
from services.profile_search import (
    run_profile_search,
    validate_profile_input,
    find_duplicate_candidates,
    generate_profile_id,
    ProfileSearchError,
)

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Case & Profile Intelligence"])

# Neutral disclaimer returned alongside every match set. Profile matches are
# investigative leads for human verification — never automated accusations.
PROFILE_MATCH_DISCLAIMER = (
    "Records are investigative references, not confirmations of guilt or identity. "
    "Treat all matches as leads for human verification."
)

# Neutral, non-accusatory relationships for case association (requirement 15).
# "culprit" is NEVER an allowed relationship label.
CASE_RELATIONSHIPS = ("Potential subject", "Witness", "Unknown person", "Person of interest")

# Fields exposed by the profile detail view (requirement 16). Reporter identity
# and the embedding vector are deliberately withheld.
_DETAIL_FIELDS = (
    "culprit_id", "name", "physical_description", "behavioral_traits",
    "location", "created_at", "updated_at", "associated_cases",
)


def _service_unavailable(msg: str):
    """503 with a clear, non-misleading message (requirement 26)."""
    raise HTTPException(status_code=503, detail=msg)


@router.post("/culprit/report")
def report_culprit(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Register a profile (Authority/Admin only).

    Hardened per requirements 12-14: input is validated + cleaned (length,
    junk, HTML/script, Unicode), likely duplicates are surfaced before an
    insert, and the public id is cryptographically random (not a guessable
    timestamp). Requires an authority/admin token — profile management is not
    available to normal users (requirement 21).
    """
    cleaned, errors = validate_profile_input(
        body.get("name"), body.get("physical_description"),
        body.get("behavioral_traits"), body.get("location"))
    if errors:
        raise HTTPException(status_code=400,
                            detail={"message": "Invalid profile input", "errors": errors})

    collection = culprits()
    if collection is None:
        _service_unavailable("Profile service is temporarily unavailable.")

    force = bool(body.get("force"))
    justification = str(body.get("justification", "") or "").strip()[:500]

    # Duplicate detection (requirement 13). A DB failure here surfaces as 503.
    try:
        duplicates = find_duplicate_candidates(collection, cleaned)
    except ProfileSearchError:
        _service_unavailable("Profile service is temporarily unavailable.")

    if duplicates and not force:
        # Do not silently create a duplicate — let the UI offer
        # Use existing / Cancel / Register anyway with justification.
        return {
            "success": False,
            "duplicate_found": True,
            "candidates": duplicates,
            "message": "Possible existing record found.",
            "disclaimer": PROFILE_MATCH_DISCLAIMER,
        }
    if duplicates and force and not justification:
        raise HTTPException(status_code=400,
                            detail="justification required to register a possible duplicate")

    # Embed physical + behavioral text (name is intentionally NOT embedded, so
    # name lookups stay deterministic).
    from services.embeddings import embed
    embedding = embed(f"{cleaned['physical_description']}. {cleaned['behavioral_traits']}")
    now = datetime.utcnow()
    profile_id = generate_profile_id()
    doc = {
        "name": cleaned["name"],
        "physical_description": cleaned["physical_description"],
        "behavioral_traits": cleaned["behavioral_traits"],
        "location": cleaned["location"],
        "reporter_id": current_user.user_id,
        "reporter_role": current_user.role,
        "description_embedding": embedding,
        "created_at": now,
        "updated_at": now,
        "culprit_id": profile_id,
        "associated_cases": [],
    }
    if force and duplicates:
        doc["duplicate_override_justification"] = justification
    collection.insert_one(doc)
    # Audit: profile id + override flag only — NO full description text.
    log_audit(current_user.user_id, current_user.role, "PROFILE_CREATED",
              metadata={"profile_id": profile_id, "duplicate_override": bool(force and duplicates)})
    return {"success": True, "profile_id": profile_id, "culprit_id": profile_id}


@router.post("/culprit/find-match")
def find_culprit_match(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    """Search profiles: deterministic NAME search or hybrid DESCRIPTION search.

    Authority/admin only. NAME queries never require semantic similarity;
    DESCRIPTION/MIXED queries blend keyword + semantic (with keyword fallback).
    A real backend failure returns 503 — never a misleading empty result
    (requirement 26). Embedding vectors are never returned (requirement 25).
    """
    query = str(body.get("description", ""))[:500]
    if not query.strip():
        raise HTTPException(status_code=400, detail="description required")

    try:
        top_n = int(body.get("top_n", 10))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="top_n must be an integer")
    top_n = max(1, min(top_n, 50))

    search_mode = str(body.get("search_mode", "auto"))

    collection = culprits()
    if collection is None:
        _service_unavailable("Profile service is temporarily unavailable.")

    try:
        result = run_profile_search(collection, query, search_mode, top_n)
    except ProfileSearchError:
        _service_unavailable("Profile search is temporarily unavailable.")

    matches = result["matches"]
    # Audit: query TYPE + result count only — NEVER the raw query text.
    log_audit(current_user.user_id, current_user.role, "PROFILE_SEARCHED",
              metadata={"query_type": result["query_type"], "search_type": result["search_type"],
                        "count": len(matches), "degraded": result["degraded"]})

    resp = {
        "query_type": result["query_type"],
        "query": query,
        "total": len(matches),
        "search_type": result["search_type"],
        "degraded": result["degraded"],
        "human_verification_required": True,
        "matches": matches,     # back-compat with existing frontend
        "results": matches,     # structured contract name (requirement 25)
        "disclaimer": PROFILE_MATCH_DISCLAIMER,
    }
    if result["degraded"]:
        resp["notice"] = "Semantic similarity unavailable; showing keyword matches."
    return resp


@router.get("/culprit/profile/{profile_id}")
def get_profile_detail(
    profile_id: str,
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=40, window_seconds=60)),
):
    """Profile detail view (Authority/Admin only, audited) — requirement 16.

    Returns only whitelisted fields; the embedding vector and reporter identity
    are never exposed. Framed as an investigative record, not a confirmation.
    """
    collection = culprits()
    if collection is None:
        _service_unavailable("Profile service is temporarily unavailable.")

    doc = collection.find_one({"culprit_id": profile_id},
                              {"_id": 0, "description_embedding": 0,
                               "reporter_id": 0, "reporter_role": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")

    doc = serialize_doc(doc)
    profile = {k: doc.get(k) for k in _DETAIL_FIELDS if k in doc}
    profile["profile_id"] = profile.get("culprit_id")
    profile["human_verification_required"] = True

    log_audit(current_user.user_id, current_user.role, "PROFILE_VIEWED",
              metadata={"profile_id": profile_id})
    return {"profile": profile, "disclaimer": PROFILE_MATCH_DISCLAIMER}


@router.post("/culprit/associate-case")
def associate_profile_case(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Associate a profile with an existing case using a NEUTRAL relationship
    (requirement 15). 'culprit' is never an accepted relationship."""
    profile_id = str(body.get("profile_id", "")).strip()
    case_id = str(body.get("case_id", "")).strip()
    relationship = str(body.get("relationship", "")).strip()
    if not profile_id or not case_id:
        raise HTTPException(status_code=400, detail="profile_id and case_id are required")
    if relationship not in CASE_RELATIONSHIPS:
        raise HTTPException(status_code=400,
                            detail=f"relationship must be one of {list(CASE_RELATIONSHIPS)}")

    collection = culprits()
    cases = sos_cases()
    if collection is None or cases is None:
        _service_unavailable("Profile service is temporarily unavailable.")

    if not collection.find_one({"culprit_id": profile_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Profile not found")
    if not cases.find_one({"case_id": case_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Case not found")

    association = {
        "case_id": case_id,
        "relationship": relationship,
        "associated_by": current_user.user_id,
        "associated_at": datetime.utcnow(),
    }
    collection.update_one(
        {"culprit_id": profile_id},
        {"$push": {"associated_cases": association}, "$set": {"updated_at": datetime.utcnow()}})
    log_audit(current_user.user_id, current_user.role, "PROFILE_CASE_ASSOCIATED",
              case_id=case_id, metadata={"profile_id": profile_id, "relationship": relationship})
    return {"success": True, "profile_id": profile_id, "case_id": case_id,
            "relationship": relationship}


@router.post("/search/cases")
def semantic_case_search(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    """Search across SOS cases (Authority only). Body: {query, limit?, mode?}.

    Delegates to the unified search service (keyword | semantic | hybrid over the
    existing Atlas $vectorSearch). Authorization is enforced because case content
    is sensitive.
    """
    query = body.get("query", "")
    limit = min(int(body.get("limit", 10) or 10), 20)
    mode = str(body.get("mode", "semantic")).lower()
    if not str(query).strip():
        raise HTTPException(status_code=400, detail="query required")
    if mode not in SEARCH_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {list(SEARCH_MODES)}")

    result = search_cases(query=query, limit=limit, mode=mode)
    # Audit: mode + count only — the raw query text is NOT stored (privacy).
    log_audit(current_user.user_id, current_user.role, "CASE_SEARCHED",
              metadata={"type": "case_search", "mode": result["search_mode"],
                        "count": result["total"]})
    return {
        "results": [serialize_doc(r) for r in result["results"]],
        "query": result["query"],
        "total": result["total"],
        "search_type": result["search_mode"],
        "search_mode": result["search_mode"],
        "degraded": result["degraded"],
    }
