"""
Embedding backend wrapper — stable `embed(text) -> vector` contract.

Backend: Google Gemini `gemini-embedding-001` (768-dim), via the existing
services.ai_service.get_embedding(). This module adds status tracking so we can
honestly report whether real embeddings are active or we fell back.

Status semantics (exposed via embedding_info() and GET /ai/embedding-info):
    ACTIVE    — GEMINI_API_KEY present AND the most recent embedding call
                returned a real, non-zero vector.
    FALLBACK  — a call was attempted but returned the zero-vector fallback
                (upstream error / quota). Vector search will be degraded.
    DEMO      — no GEMINI_API_KEY configured; embeddings cannot run. Callers
                should treat semantic search as unavailable and say so.

We never fabricate an embedding: when the key is absent we return the documented
zero-vector so downstream $vectorSearch degrades to the keyword fallback rather
than silently returning meaningless "similarity".
"""
import os
import logging

from services.ai_service import get_embedding

logger = logging.getLogger("haven_backend")

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_VERSION = "v1-gemini-embedding-001"
EMBEDDING_DIM = 768

# Updated on every embed() call so /ai/embedding-info reflects reality.
_last_status = "UNKNOWN"
_last_error = None


def _has_key() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _is_zero_vector(vec) -> bool:
    return not vec or not any(abs(float(x)) > 1e-12 for x in vec)


def embed(text: str) -> list:
    """Return an embedding vector for `text` (stable public contract).

    Always returns a list of floats of length EMBEDDING_DIM. Updates the
    module status so embedding_info() reports the true backend state.
    """
    global _last_status, _last_error
    text = (text or "").strip()

    if not _has_key():
        _last_status = "DEMO"
        _last_error = "GEMINI_API_KEY not configured"
        return [0.0] * EMBEDDING_DIM

    if not text:
        # Empty input is not an error; just an empty (zero) vector.
        _last_status = "ACTIVE"
        _last_error = None
        return [0.0] * EMBEDDING_DIM

    try:
        vec = get_embedding(text)
    except Exception as e:  # get_embedding already guards, but be defensive
        logger.warning("embedding backend error: %s", e)
        _last_status = "FALLBACK"
        _last_error = str(e)
        return [0.0] * EMBEDDING_DIM

    # Normalise length so the vector index always gets the expected dimension.
    if len(vec) != EMBEDDING_DIM:
        if len(vec) > EMBEDDING_DIM:
            vec = vec[:EMBEDDING_DIM]
        else:
            vec = list(vec) + [0.0] * (EMBEDDING_DIM - len(vec))

    if _is_zero_vector(vec):
        _last_status = "FALLBACK"
        _last_error = "upstream returned empty/zero vector"
    else:
        _last_status = "ACTIVE"
        _last_error = None
    return vec


def embedding_info() -> dict:
    """Diagnostics for GET /ai/embedding-info (no secrets)."""
    if not _has_key():
        status = "DEMO"
    else:
        status = _last_status if _last_status != "UNKNOWN" else "READY"
    return {
        "model_name": EMBEDDING_MODEL,
        "model_version": EMBEDDING_VERSION,
        "dimension": EMBEDDING_DIM,
        "backend": "google-gemini",
        "status": status,
        "api_key_configured": _has_key(),
        "last_error": _last_error,
        "semantic_search_available": _has_key(),
        "note": (
            "Semantic search requires a configured embedding backend and a MongoDB "
            "Atlas $vectorSearch index. When status is DEMO/FALLBACK, search degrades "
            "to keyword matching and results are labelled accordingly."
        ),
    }
