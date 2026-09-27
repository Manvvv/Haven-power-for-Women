"""
HAVEN embedding service (Phase 7).

A thin, stable wrapper around the vector-embedding backend so the rest of the
app depends on ONE interface:

    from services.embeddings import embed, embedding_info
    vector = embed("some text")      # -> list[float]

The wrapper preserves the existing Gemini embedding integration
(services.ai_service.get_embedding) but adds:
  * a stable `embed(text) -> vector` contract,
  * honest status reporting (ACTIVE / FALLBACK / DEMO) so we never pretend
    ML embeddings are running when the API key is missing or the call failed,
  * `embedding_info()` for GET /ai/embedding-info.
"""
from .embedding_service import embed, embedding_info, EMBEDDING_DIM  # noqa: F401
