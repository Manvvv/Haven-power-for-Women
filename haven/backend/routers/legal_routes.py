"""Legal Assistant routes — RAG-grounded query + verified document management.

Query is retrieval-augmented (services.legal_rag): it retrieves verified legal
passages before generating, cites only what it used, and returns a safe
no-context message rather than hallucinating. Document management is admin-only.
"""
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Body, UploadFile, File, HTTPException

from auth import AuthUser, get_optional_user, require_admin
from rate_limiter import rate_limit_dependency
from services.db import legal_docs, serialize_doc
from services.audit_service import log_audit
from services import legal_rag

logger = logging.getLogger("haven_backend")
router = APIRouter(prefix="", tags=["Legal"])


@router.post("/legal/query")
def legal_query(
    body: dict = Body(...),
    current_user=Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Answer a legal question with grounded RAG over verified sources.

    Open to victims (auth optional). Never hallucinates: if no verified source is
    relevant, returns an explicit no-context message.
    """
    question = body.get("question", "")
    if not str(question).strip():
        raise HTTPException(status_code=400, detail="question required")

    user_id = (current_user.user_id if current_user else None) or body.get("user_id") or "anonymous"
    # Optional UX hints (do not affect grounding): preferred language + state jurisdiction.
    language_hint = body.get("language") or body.get("language_hint")
    state_hint = body.get("state") or body.get("state_hint")
    result = legal_rag.answer(
        question=str(question), user_id=user_id,
        language_hint=language_hint, state_hint=state_hint,
    )

    # Audit without storing the full sensitive question in plaintext (hash + metadata only).
    import hashlib
    q_hash = hashlib.sha256(str(question).encode("utf-8")).hexdigest()[:16]
    authority_levels = sorted({s.get("authority_level", "") for s in result.get("sources", []) if s.get("authority_level")})
    log_audit(
        actor_id=user_id,
        role=(current_user.role if current_user else "anonymous"),
        action="LEGAL_QUERY",
        metadata={
            "q_hash": q_hash,
            "topic": result.get("topic"),
            "jurisdiction": result.get("jurisdiction"),
            "urgency": result.get("urgency"),
            "evidence_level": result.get("evidence_level"),
            "num_sources": len(result.get("sources", [])),
            "authority_levels": authority_levels,
            "retrieved_document_ids": result.get("retrieved_document_ids", []),
            "retrieval_mode": result.get("retrieval_mode"),
            "status": result.get("status"),
            "llm_provider": result.get("model_info", {}).get("llm_provider"),
        },
    )
    return result


@router.post("/legal/ingest")
def ingest_legal_document(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_admin),
):
    """Ingest a VERIFIED legal document (admin only).

    Body: {title, text, source_name?, source_url?, jurisdiction?, section?,
           verification_status?, document_version?, document_id?}
    """
    title = body.get("title", "")
    text = body.get("text", "")
    if not str(title).strip() or not str(text).strip():
        raise HTTPException(status_code=400, detail="title and text are required")

    result = legal_rag.ingest_document(
        title=title,
        text=text,
        source_name=body.get("source_name", ""),
        source_url=body.get("source_url", ""),
        jurisdiction=body.get("jurisdiction", "India"),
        section=body.get("section", ""),
        verification_status=body.get("verification_status", "verified"),
        document_version=body.get("document_version", "1"),
        uploaded_by=current_user.user_id,
        document_id=body.get("document_id", ""),
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    log_audit(current_user.user_id, current_user.role, "LEGAL_DOC_INGESTED",
              metadata={"document_id": result["document_id"],
                        "chunks_ingested": result["chunks_ingested"],
                        "chunks_skipped": result["chunks_skipped"]})
    return {"success": True, **result}


@router.post("/legal/upload-doc")
async def upload_legal_doc(
    file: UploadFile = File(...),
    source_name: str = "Legal Document",
    current_user: AuthUser = Depends(require_admin),
):
    """Upload a verified legal PDF (admin only). Extracts text then RAG-ingests it."""
    MAX = 15_000_000
    if file.size and file.size > MAX:
        raise HTTPException(status_code=413, detail="File too large. Maximum size 15MB.")
    if file.content_type and file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported.")

    from pypdf import PdfReader
    content = await file.read()
    if len(content) > MAX:
        raise HTTPException(status_code=413, detail="File too large. Maximum size 15MB.")

    try:
        reader = PdfReader(io.BytesIO(content))
        full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        logger.warning("PDF parse error: %s", e)
        raise HTTPException(status_code=400, detail="Could not read the PDF. It may be malformed or scanned images only.")

    if not full_text.strip():
        raise HTTPException(status_code=422, detail="No extractable text found in the PDF (scanned image?).")

    result = legal_rag.ingest_document(
        title=source_name[:300],
        text=full_text,
        source_name=source_name,
        verification_status="verified",
        uploaded_by=current_user.user_id,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    log_audit(current_user.user_id, current_user.role, "LEGAL_DOC_INGESTED",
              metadata={"document_id": result["document_id"],
                        "chunks_ingested": result["chunks_ingested"]})
    return {"success": True, "chunks_embedded": result["chunks_ingested"],
            "chunks_skipped": result["chunks_skipped"], "source": source_name,
            "document_id": result["document_id"]}


@router.get("/legal/documents")
def list_legal_documents(current_user: AuthUser = Depends(require_admin)):
    """List ingested legal documents grouped by document_id (admin only)."""
    coll = legal_docs()
    if coll is None:
        return {"documents": [], "total": 0}
    pipeline = [
        {"$group": {
            "_id": "$document_id",
            "title": {"$first": "$title"},
            "source_name": {"$first": "$source_name"},
            "section": {"$first": "$section"},
            "verification_status": {"$first": "$verification_status"},
            "document_version": {"$first": "$document_version"},
            "chunks": {"$sum": 1},
            "created_at": {"$first": "$created_at"},
        }},
        {"$sort": {"created_at": -1}},
    ]
    docs = [serialize_doc({"document_id": d.pop("_id"), **d}) for d in coll.aggregate(pipeline)]
    return {"documents": docs, "total": len(docs)}


@router.get("/legal/corpus/health")
def legal_corpus_health(current_user: AuthUser = Depends(require_admin)):
    """Corpus health / coverage report (admin only).

    Confirms the corpus is seeded and shows coverage by category + authority level,
    so an empty-collection regression (the original 'no verified source' bug) is
    immediately visible.
    """
    from services.embeddings import embedding_info
    coll = legal_docs()
    if coll is None:
        return {"ok": False, "error": "Database unavailable", "total_chunks": 0}

    total = coll.count_documents({})
    verified = coll.count_documents({"verification_status": "verified"})
    distinct_docs = len(coll.distinct("document_id"))

    def _counts(field):
        out = {}
        for v in coll.distinct(field):
            if v:
                out[str(v)] = coll.count_documents({field: v})
        return out

    einfo = embedding_info()
    corpus_version = getattr(legal_rag, "CORPUS_VERSION", "")
    return {
        "ok": total > 0,
        "seeded": total > 0,
        "corpus_version": corpus_version,
        "total_chunks": total,
        "verified_chunks": verified,
        "distinct_documents": distinct_docs,
        "by_category": _counts("category"),
        "by_authority_level": _counts("authority_level"),
        "embedding_status": einfo["status"],
        "semantic_search_available": einfo.get("semantic_search_available"),
        "note": ("Corpus is empty — run `python seed_legal_corpus.py` from haven/backend."
                 if total == 0 else "Corpus is populated."),
    }
