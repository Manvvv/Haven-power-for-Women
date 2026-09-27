"""
Case & Profile Intelligence — deterministic name search + field-aware hybrid
description search.

WHY THIS MODULE EXISTS
----------------------
The previous `/culprit/find-match` had two defects that made a plain name query
("nirmal nehra") return "No matches above threshold":

  1. In *description* mode it ran a VECTOR-ONLY search over
     `description_embedding` (built from physical + behavioral text, NOT the
     name) and then dropped everything below a hard 0.75 similarity floor. A
     name embedded against description vectors never clears that floor.
  2. In *name* mode it fell through to that SAME vector search whenever the
     exact/partial regex missed — so name search was not actually deterministic.
  3. On any vector error it fabricated a 0.5 "similarity" for arbitrary docs.

This module fixes all three:

  * NAME search is 100% deterministic and lexical — exact, all-terms, partial,
    and a conservative transliteration/spelling fold. It NEVER embeds the query
    and NEVER applies a similarity floor.
  * DESCRIPTION search is hybrid — field-aware keyword relevance blended with
    semantic similarity when a real embedding backend is available, and a
    transparent keyword fallback (degraded=True) when it is not. Scores are
    real; nothing is fabricated.
  * A weak semantic score can never outrank an exact name match.

SAFETY (non-negotiable)
-----------------------
Every result is an INVESTIGATIVE LEAD for human verification — never a
confirmation of guilt or identity. Similarity is surfaced as a retrieval level
(High / Moderate / Weak), not identity confidence. Raw embedding vectors are
NEVER returned. See the route layer for RBAC, audit hygiene and error codes.
"""
import re
import logging
import unicodedata

logger = logging.getLogger("haven_backend")

# ─── Query-type taxonomy (requirement 5) ─────────────────────────────────────
NAME_QUERY = "NAME_QUERY"
DESCRIPTION_QUERY = "DESCRIPTION_QUERY"
MIXED_QUERY = "MIXED_QUERY"

# Safe, user-facing factor labels (requirement 4). These are the ONLY match
# descriptors ever shown — never raw field weights, cosine values or vectors.
LABEL_NAME = "Name match"
LABEL_DESC = "Description similarity"
LABEL_BEHAVIOR = "Behavioral similarity"
LABEL_LOCATION = "Location match"

# Field-aware keyword weights for DESCRIPTION search. Physical description is the
# primary signal, behaviour next; name is a small contributor so that a name
# typed into the description box still surfaces, and location is a light hint.
# Sum == 1.0 so the blended keyword score stays in 0..1.
_FIELD_WEIGHTS = {
    "physical_description": 0.45,
    "behavioral_traits": 0.30,
    "name": 0.15,
    "location": 0.10,
}

# Deterministic hybrid blend (only used when semantic search is available).
_W_SEMANTIC = 0.55
_W_KEYWORD = 0.45

# Tokens that signal a physical/behavioral DESCRIPTION rather than a name. Used
# only by the "auto" classifier — the explicit name/description buttons win.
_DESCRIPTOR_HINTS = {
    "age", "aged", "tall", "short", "hair", "beard", "moustache", "clean",
    "cm", "kg", "ft", "feet", "year", "years", "old", "young", "build",
    "height", "weight", "complexion", "aggressive", "calm", "wearing", "wore",
    "male", "female", "man", "woman", "boy", "girl", "eyes", "eye", "scar",
    "tattoo", "fair", "dark", "medium", "slim", "heavy", "thin", "stocky",
    "bald", "spectacles", "glasses", "limp", "accent", "shirt", "jacket",
}

_TAG_RE = re.compile(r"<[^>]*>")


class ProfileSearchError(Exception):
    """Raised on a genuine backend failure (DB/index unavailable).

    The route layer maps this to HTTP 503 so the UI can say "search
    temporarily unavailable" instead of the misleading "no matches" (req. 26).
    """


# ─── normalization & tokenization (requirement 12: Unicode-safe) ─────────────
def normalize_text(s) -> str:
    """NFKC-normalize, strip HTML tags, lowercase, fold punctuation to spaces."""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _TAG_RE.sub(" ", s)
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = s.replace("_", " ")
    return " ".join(s.split())


def tokens(s) -> list:
    """Unicode-aware word tokens (Latin, Devanagari and other scripts)."""
    return [t for t in normalize_text(s).split() if t]


def fold_token(t: str) -> str:
    """Conservative transliteration/spelling fold for name variants.

    Handles common Indian-name romanization drift (ph/f, doubled vowels,
    trailing silent h, etc.). Only ever used as the WEAKEST name-match tier and
    only when EVERY query token folds onto a name token, so false positives stay
    low and every such hit is still a human-verified lead.
    """
    t = t.lower()
    for a, b in (("ph", "f"), ("kh", "k"), ("gh", "g"), ("th", "t"),
                 ("dh", "d"), ("bh", "b"), ("ck", "k"), ("sh", "s")):
        t = t.replace(a, b)
    t = t.replace("w", "v").replace("y", "i")
    t = t.replace("ee", "i").replace("oo", "u").replace("aa", "a")
    t = re.sub(r"(.)\1+", r"\1", t)   # collapse remaining doubled letters
    t = re.sub(r"h$", "", t)          # trailing silent h
    return t


# ─── query classification (requirement 5) ────────────────────────────────────
def classify_query(query: str, search_mode: str = "auto") -> str:
    """Return NAME_QUERY / DESCRIPTION_QUERY / MIXED_QUERY.

    Explicit UI buttons ("name"/"description") are authoritative. "auto" uses a
    deterministic heuristic: descriptor words or digits + several tokens look
    like a description; a few plain tokens look like a name; otherwise mixed.
    """
    if search_mode == "name":
        return NAME_QUERY
    if search_mode == "description":
        return DESCRIPTION_QUERY
    toks = tokens(query)
    if not toks:
        return NAME_QUERY
    has_descriptor = any(t in _DESCRIPTOR_HINTS for t in toks) or any(c.isdigit() for c in query)
    if has_descriptor and len(toks) >= 3:
        return DESCRIPTION_QUERY
    if len(toks) <= 4 and not has_descriptor:
        return NAME_QUERY
    return MIXED_QUERY


# ─── retrieval levels & safe result shaping (requirements 8, 19, 24, 25) ─────
# Retrieval levels describe how strongly a record matched the QUERY. They are
# NOT identity confidence and NEVER imply guilt.
LEVEL_HIGH = "High"
LEVEL_MODERATE = "Moderate"
LEVEL_WEAK = "Weak"

# Only these fields are ever returned to the client. Everything else — the
# embedding vector, reporter identity, internal _id — is stripped here so it can
# never leak, independent of what the caller projects.
_PUBLIC_FIELDS = (
    "culprit_id", "name", "physical_description",
    "behavioral_traits", "location", "created_at",
)

# ── The ONE authoritative public-response contract for a search match ────────
# This is the single source of truth for every key a /culprit/find-match match
# object may contain. `_shape()` emits exactly these keys and NOTHING else, and
# the P1 security test asserts against this same set — so a field can never be
# added to the API without being consciously added to the public contract here.
# Every member is public-safe: the six record fields above (no reporter identity,
# no embedding vector, no Mongo _id) plus derived RETRIEVAL metadata. match_score
# / match_level / match_factors describe how strongly the record matched the
# QUERY — they are NOT identity confidence and never imply guilt. No raw field
# weight, cosine value or vector is ever exposed.
SAFE_PUBLIC_MATCH_FIELDS = frozenset(_PUBLIC_FIELDS) | {
    "profile_id",
    "match_score",
    "match_level",
    "match_factors",
    "match_summary",
    "human_verification_required",
}

_HUMAN_VERIFICATION_REQUIRED = True


def match_level(score: float) -> str:
    """Map a 0..1 retrieval score to a coarse, non-numeric level."""
    if score >= 0.75:
        return LEVEL_HIGH
    if score >= 0.45:
        return LEVEL_MODERATE
    return LEVEL_WEAK


def _factor_strength(v: float) -> str:
    """Coarse per-factor strength label (no raw weights/cosines exposed)."""
    if v >= 0.75:
        return "strong"
    if v >= 0.40:
        return "moderate"
    return "weak"


def _shape(doc: dict, score: float, factors: list, summary: str) -> dict:
    """Build the safe, whitelisted result object (requirement 25).

    Never includes embeddings/vectors, reporter metadata or Mongo _id. Always
    flags human_verification_required and labels the score as a RETRIEVAL level.
    """
    score = round(max(0.0, min(1.0, float(score))), 4)
    out = {k: doc.get(k) for k in _PUBLIC_FIELDS}
    # profile_id is the public identifier; keep culprit_id as a back-compat alias
    # (the collection name is preserved internally per requirement 15).
    out["profile_id"] = doc.get("culprit_id")
    out["match_score"] = score
    out["match_level"] = match_level(score)
    out["match_factors"] = [f for f in factors if f]
    out["match_summary"] = summary
    out["human_verification_required"] = _HUMAN_VERIFICATION_REQUIRED
    # Enforce the single authoritative allowlist: ONLY approved public fields ever
    # leave this function. This is a no-op on correct data (every key above is in
    # the set) but structurally guarantees that no reporter id, embedding vector,
    # Mongo _id or any future stray field can ever leak out via a match object.
    return {k: v for k, v in out.items() if k in SAFE_PUBLIC_MATCH_FIELDS}


# ─── candidate retrieval (requirement 24: token-based, not one big substring) ─
# The old keyword path escaped the WHOLE query as a single substring regex, so
# "nirmal nehra" only matched a field literally containing that exact substring.
# We instead OR the individual tokens across the searchable text fields.
_SEARCH_FIELDS = ("name", "physical_description", "behavioral_traits", "location")

# Never let a projected doc carry the embedding out of the DB layer.
_SAFE_PROJECTION = {"_id": 0, "description_embedding": 0}


def _token_or_filter(toks: list) -> dict:
    """Mongo filter: any token appears (case-insensitive) in any search field.

    Tokens are regex-escaped, so user input can never inject regex operators.
    """
    clauses = []
    for t in toks:
        if not t:
            continue
        rx = {"$regex": re.escape(t), "$options": "i"}
        for f in _SEARCH_FIELDS:
            clauses.append({f: rx})
    return {"$or": clauses} if clauses else {}


def _fetch_candidates(collection, toks: list, cap: int) -> list:
    """Fetch candidate docs matching any query token. Raises on DB failure.

    `cap` bounds the working set so a broad token never scans unboundedly; we
    still rank the full candidate set deterministically afterwards.
    """
    if collection is None:
        raise ProfileSearchError("profile collection unavailable")
    filt = _token_or_filter(toks)
    if not filt:
        return []
    try:
        cursor = collection.find(filt, _SAFE_PROJECTION).limit(cap)
        return list(cursor)
    except Exception as exc:  # DB/index failure — surface, never fabricate
        logger.warning("profile candidate fetch failed: %s", type(exc).__name__)
        raise ProfileSearchError("profile candidate fetch failed") from exc


def _all_docs(collection, cap: int) -> list:
    """Fetch up to `cap` docs (used by the name matcher). Raises on DB failure."""
    if collection is None:
        raise ProfileSearchError("profile collection unavailable")
    try:
        return list(collection.find({}, _SAFE_PROJECTION).limit(cap))
    except Exception as exc:
        logger.warning("profile scan failed: %s", type(exc).__name__)
        raise ProfileSearchError("profile scan failed") from exc


# ─── deterministic NAME search (requirements 2, 27) ──────────────────────────
# Tiers, strongest first. NO embeddings, NO similarity floor. A record is scored
# by the strongest tier it satisfies; anything unmatched is simply excluded.
NAME_SCAN_CAP = 2000


def _name_tier_score(query: str, name: str):
    """Return (score, summary) for the strongest name tier, or (0.0, '')."""
    q_toks = tokens(query)
    n_toks = tokens(name)
    if not q_toks or not n_toks:
        return 0.0, ""
    q_str = normalize_text(query)
    n_str = normalize_text(name)
    q_set, n_set = set(q_toks), set(n_toks)

    # 1) exact (normalized) equality
    if q_str == n_str:
        return 1.0, "Exact name match"
    # 2) all query terms present as whole name tokens
    if q_set <= n_set:
        if len(q_set) == len(n_set):
            return 0.97, "Exact name match (terms reordered)"
        return 0.90, "All name terms match"
    # 3) partial — full query is a substring, or every term is a token substring
    if q_str and q_str in n_str:
        return 0.80, "Partial name match"
    if all(any(qt in nt for nt in n_toks) for qt in q_toks):
        return 0.70, "Partial name match"
    # 4) conservative transliteration/spelling fold (weakest; all-or-nothing)
    n_folded = {fold_token(t) for t in n_toks}
    if all(fold_token(qt) in n_folded for qt in q_toks):
        return 0.55, "Name spelling/transliteration match"
    return 0.0, ""


def deterministic_name_search(collection, query: str, top_n: int) -> list:
    """Lexical, fully deterministic name search. Raises ProfileSearchError on
    DB failure (never returns a fabricated or partial-on-error result)."""
    docs = _all_docs(collection, NAME_SCAN_CAP)
    scored = []
    for doc in docs:
        score, summary = _name_tier_score(query, doc.get("name") or "")
        if score <= 0:
            continue
        factors = [{"label": LABEL_NAME, "strength": _factor_strength(score)}]
        scored.append((score, str(doc.get("culprit_id") or ""),
                       _shape(doc, score, factors, summary)))
    # deterministic: highest score first, then stable by profile id
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s[2] for s in scored[:top_n]]


# ─── field-aware keyword relevance (requirement 4) ───────────────────────────
def _field_keyword_ratio(q_set: set, field_text: str) -> float:
    """Fraction of unique query tokens found (whole-token or substring) in a
    single field. 0..1. Whole-token hits and substring hits both count."""
    if not q_set or not field_text:
        return 0.0
    f_toks = set(tokens(field_text))
    if not f_toks:
        return 0.0
    hits = 0
    for qt in q_set:
        if qt in f_toks or any(qt in ft for ft in f_toks):
            hits += 1
    return hits / len(q_set)


def _keyword_profile_score(query: str, doc: dict):
    """Return (blended_keyword_score, per_field_ratios) for a doc. 0..1."""
    q_set = set(tokens(query))
    ratios = {
        "name": _field_keyword_ratio(q_set, doc.get("name") or ""),
        "physical_description": _field_keyword_ratio(q_set, doc.get("physical_description") or ""),
        "behavioral_traits": _field_keyword_ratio(q_set, doc.get("behavioral_traits") or ""),
        "location": _field_keyword_ratio(q_set, doc.get("location") or ""),
    }
    blended = sum(_FIELD_WEIGHTS[f] * r for f, r in ratios.items())
    return blended, ratios


def _desc_factors(ratios: dict, sem_norm: float) -> list:
    """Map per-field keyword ratios (+ semantic) to the four safe factor labels.

    The physical-description factor absorbs the semantic signal so a purely
    semantic hit still surfaces a "Description similarity" reason without ever
    exposing a cosine value or vector.
    """
    desc_strength = max(ratios.get("physical_description", 0.0), sem_norm)
    pairs = [
        (LABEL_NAME, ratios.get("name", 0.0)),
        (LABEL_DESC, desc_strength),
        (LABEL_BEHAVIOR, ratios.get("behavioral_traits", 0.0)),
        (LABEL_LOCATION, ratios.get("location", 0.0)),
    ]
    return [{"label": lbl, "strength": _factor_strength(v)} for lbl, v in pairs if v > 0]


# ─── optional semantic layer (requirement 3, 27) ─────────────────────────────
def _semantic_available() -> bool:
    """True only when a real embedding backend is configured (never faked)."""
    try:
        from services.embeddings import embedding_info
        return bool(embedding_info().get("semantic_search_available"))
    except Exception:
        return False


def _semantic_candidates(collection, query: str, limit: int) -> dict:
    """Return {culprit_id: (doc, normalized_score)} from Atlas vector search.

    Returns {} (never raises) on any embedding/vector failure so the caller can
    transparently degrade to keyword-only. Scores are min-max normalized within
    the returned set; nothing is fabricated when the backend is unavailable.
    """
    try:
        from services.embeddings import embed
        qvec = embed(query)
        if not qvec or not any(qvec):   # zero-vector == no real embedding
            return {}
        pipeline = [
            {"$vectorSearch": {
                "index": "culpritIndex",
                "path": "description_embedding",
                "queryVector": qvec,
                "numCandidates": max(limit * 5, 50),
                "limit": limit,
            }},
            {"$project": {"_id": 0, "description_embedding": 0,
                          "score": {"$meta": "vectorSearchScore"}}},
        ]
        raw = list(collection.aggregate(pipeline))
    except Exception as exc:
        logger.info("semantic profile search unavailable, degrading: %s",
                    type(exc).__name__)
        return {}
    if not raw:
        return {}
    scores = [float(r.get("score", 0.0)) for r in raw]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    out = {}
    for r in raw:
        cid = r.get("culprit_id")
        if cid is None:
            continue
        norm = (float(r.get("score", 0.0)) - lo) / span
        r.pop("score", None)          # never expose the raw cosine
        out[cid] = (r, norm)
    return out


# ─── hybrid DESCRIPTION search (requirements 3, 4, 27) ───────────────────────
_KEYWORD_CANDIDATE_CAP = 200


def _full_name_match(query: str, doc: dict) -> bool:
    """True when every query token is a whole token of the record's name.

    Used only to guarantee an exact/complete name typed into the DESCRIPTION box
    can never be buried by a weak semantic score (requirement 4)."""
    q_set = set(tokens(query))
    n_set = set(tokens(doc.get("name") or ""))
    return bool(q_set) and q_set <= n_set


def hybrid_description_search(collection, query: str, top_n: int) -> dict:
    """Field-aware keyword relevance blended with semantic similarity when a
    real embedding backend is available; transparent keyword fallback otherwise.

    Returns {"matches": [...], "mode": "hybrid"|"keyword_fallback",
             "degraded": bool}. Raises ProfileSearchError only on a hard DB
    failure of the keyword layer (semantic failure just degrades)."""
    q_toks = tokens(query)
    if not q_toks:
        return {"matches": [], "mode": "keyword_fallback", "degraded": False}

    # candidate pool: keyword matches (always) ∪ semantic matches (if available)
    kw_docs = _fetch_candidates(collection, q_toks, _KEYWORD_CANDIDATE_CAP)
    pool = {}
    for d in kw_docs:
        cid = d.get("culprit_id")
        if cid is not None:
            pool[cid] = d

    semantic_on = _semantic_available()
    sem = _semantic_candidates(collection, query, top_n * 3) if semantic_on else {}
    for cid, (d, _norm) in sem.items():
        pool.setdefault(cid, d)
    # semantic was requested but produced nothing usable → transparent fallback
    degraded = semantic_on and not sem
    use_semantic = semantic_on and bool(sem)

    scored = []
    for cid, doc in pool.items():
        kw, ratios = _keyword_profile_score(query, doc)
        sem_norm = sem.get(cid, (None, 0.0))[1] if use_semantic else 0.0
        if use_semantic:
            final = _W_SEMANTIC * sem_norm + _W_KEYWORD * kw
        else:
            final = kw
        # name-dominance safety: an exact/complete name match can never be
        # outranked by a weak semantic score (requirement 4).
        if _full_name_match(query, doc):
            final = max(final, 0.90)
        if final <= 0:
            continue
        summary = ("Description & keyword similarity" if use_semantic
                   else "Keyword similarity (semantic search unavailable)")
        factors = _desc_factors(ratios, sem_norm)
        scored.append((final, str(cid or ""), _shape(doc, final, factors, summary)))

    scored.sort(key=lambda t: (-t[0], t[1]))
    mode = "hybrid" if use_semantic else "keyword_fallback"
    return {"matches": [s[2] for s in scored[:top_n]],
            "mode": mode, "degraded": degraded}


# ─── orchestrator (requirement 25: structured contract) ──────────────────────
# Public, contract-facing query-type values (requirement 25 says the API returns
# "name|description|mixed"). The uppercase *_QUERY constants stay internal.
_PUBLIC_QUERY_TYPE = {
    NAME_QUERY: "name",
    DESCRIPTION_QUERY: "description",
    MIXED_QUERY: "mixed",
}


def run_profile_search(collection, query, search_mode: str = "auto",
                       top_n: int = 10) -> dict:
    """Single entry point for `/culprit/find-match`.

    Returns {query_type, search_type, matches, degraded}. `query_type` is the
    public short form ("name"/"description"/"mixed"). NAME queries go through the
    deterministic matcher (no vectors, no floor); DESCRIPTION/MIXED queries go
    through the hybrid matcher. Raises ProfileSearchError on hard DB failure so
    the route can return 503 rather than a misleading empty result.
    """
    query = (str(query) if query is not None else "").strip()
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 10
    top_n = max(1, min(top_n, 50))
    q_type = classify_query(query, search_mode)
    public_type = _PUBLIC_QUERY_TYPE.get(q_type, "mixed")
    if not query:
        return {"query_type": public_type, "search_type": "empty",
                "matches": [], "degraded": False}
    if q_type == NAME_QUERY:
        matches = deterministic_name_search(collection, query, top_n)
        return {"query_type": public_type, "search_type": "deterministic_name",
                "matches": matches, "degraded": False}
    res = hybrid_description_search(collection, query, top_n)
    return {"query_type": public_type, "search_type": res["mode"],
            "matches": res["matches"], "degraded": res["degraded"]}


# ─── registration hardening (requirements 12, 13, 14) ────────────────────────
NAME_MAX = 120
PHYS_MIN, PHYS_MAX = 10, 2000
BEHAV_MIN, BEHAV_MAX = 5, 2000
LOCATION_MAX = 200

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_field(s) -> str:
    """NFKC-normalize, strip HTML tags, drop control chars, collapse whitespace.

    Preserves human-readable casing/punctuation; only removes markup, control
    characters and redundant whitespace so stored records stay clean and safe.
    """
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _TAG_RE.sub(" ", s)
    s = _CTRL_RE.sub(" ", s)
    return " ".join(s.split()).strip()


def _looks_like_junk(text: str) -> bool:
    """Reject obviously non-descriptive input (single repeated char, no letters)."""
    compact = text.replace(" ", "")
    if not compact:
        return True
    alpha = [c for c in compact if c.isalpha()]
    if len(alpha) < 3:
        return True
    if len(set(compact)) <= 1:
        return True
    return False


def _has_markup(raw) -> bool:
    """Detect HTML/script injection attempts in the RAW submitted value."""
    raw = str(raw or "")
    if _TAG_RE.search(raw):
        return True
    lowered = raw.lower()
    return any(tok in lowered for tok in ("<script", "javascript:", "onerror=", "onload="))


def validate_profile_input(name, physical_description, behavioral_traits,
                           location) -> tuple:
    """Validate + clean a registration submission (requirement 12).

    Returns (cleaned_dict, errors_dict). `errors_dict` empty == valid. Physical
    description and behavioral traits are required; name and location optional.
    Behavioral-traits helper framing ("observed only") lives in the UI layer.
    """
    errors = {}
    for label, raw in (("name", name), ("physical_description", physical_description),
                       ("behavioral_traits", behavioral_traits), ("location", location)):
        if _has_markup(raw):
            errors[label] = "HTML or script content is not allowed."

    cname = clean_field(name)
    cphys = clean_field(physical_description)
    cbehav = clean_field(behavioral_traits)
    cloc = clean_field(location)

    if cname and len(cname) > NAME_MAX:
        errors.setdefault("name", f"Name must be at most {NAME_MAX} characters.")

    if len(cphys) < PHYS_MIN:
        errors.setdefault("physical_description",
                          f"Physical description must be at least {PHYS_MIN} characters.")
    elif len(cphys) > PHYS_MAX:
        errors.setdefault("physical_description",
                          f"Physical description must be at most {PHYS_MAX} characters.")
    elif _looks_like_junk(cphys):
        errors.setdefault("physical_description",
                          "Physical description does not look like a valid description.")

    if len(cbehav) < BEHAV_MIN:
        errors.setdefault("behavioral_traits",
                          f"Behavioral traits must be at least {BEHAV_MIN} characters.")
    elif len(cbehav) > BEHAV_MAX:
        errors.setdefault("behavioral_traits",
                          f"Behavioral traits must be at most {BEHAV_MAX} characters.")
    elif _looks_like_junk(cbehav):
        errors.setdefault("behavioral_traits",
                          "Behavioral traits do not look like a valid description.")

    if cloc and len(cloc) > LOCATION_MAX:
        errors.setdefault("location", f"Location must be at most {LOCATION_MAX} characters.")

    cleaned = {
        "name": cname or "Unknown",
        "physical_description": cphys,
        "behavioral_traits": cbehav,
        "location": cloc,
    }
    return cleaned, errors


def _jaccard(a: set, b: set) -> float:
    """Token-set Jaccard similarity (0..1)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# Duplicate thresholds: a duplicate is likely when the normalized name matches
# exactly, or the physical descriptions overlap heavily.
_DUP_NAME_LEVEL = "likely"
_DUP_DESC_JACCARD = 0.85


def find_duplicate_candidates(collection, cleaned: dict, limit: int = 5) -> list:
    """Return possible existing records for a submission (requirement 13).

    Flags an exact normalized-name match, or a strong physical-description token
    overlap. The route surfaces these so the user can Use existing / Cancel /
    Register anyway with justification. Raises ProfileSearchError on DB failure.
    """
    name_norm = normalize_text(cleaned.get("name") or "")
    phys_tokens = set(tokens(cleaned.get("physical_description") or ""))
    seed = list(phys_tokens) + tokens(cleaned.get("name") or "")
    if not seed:
        return []
    docs = _fetch_candidates(collection, seed, _KEYWORD_CANDIDATE_CAP)

    out = []
    for doc in docs:
        reasons = []
        level = None
        if name_norm and name_norm not in ("", "unknown") and \
                normalize_text(doc.get("name") or "") == name_norm:
            reasons.append("Same name already on record")
            level = _DUP_NAME_LEVEL
        jac = _jaccard(phys_tokens, set(tokens(doc.get("physical_description") or "")))
        if jac >= _DUP_DESC_JACCARD:
            reasons.append("Very similar physical description")
            level = _DUP_NAME_LEVEL
        if reasons:
            out.append({
                "profile_id": doc.get("culprit_id"),
                "name": doc.get("name"),
                "physical_description": doc.get("physical_description"),
                "location": doc.get("location"),
                "match_level": LEVEL_HIGH if level == _DUP_NAME_LEVEL else LEVEL_MODERATE,
                "reasons": reasons,
            })
    return out[:limit]


def generate_profile_id() -> str:
    """Cryptographically-random, non-sequential public profile id (req. 14).

    Never derived from timestamps or DB counters, so it does not leak record
    counts or ordering. Kept under the `culprit_id` field for storage back-compat.
    """
    import secrets
    return "PROF-" + secrets.token_hex(8)
