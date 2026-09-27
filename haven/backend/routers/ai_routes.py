"""AI Engine routes — text gen, decomposition, image gen, poem, risk classifier, case summary."""
import base64
import io
import json
import logging
import re
import time
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from auth import AuthUser, get_optional_user, require_authority, require_self_or_authority
from rate_limiter import rate_limit_dependency
from services.db import sos_cases, ai_analyses, serialize_doc
from services.ai_service import call_groq, call_gemini, get_embedding, summarize_case
from services.media_service import generate_image_hf
from services.risk_classifier import RiskClassifier

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["AI Engine"])
risk_classifier = RiskClassifier()


@router.post("/text-generation")
def text_generation(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    """Expand brief distress keywords into a complete distress message."""
    keywords = body.get("keywords", "")[:500]
    context = body.get("context", "domestic abuse distress situation")[:500]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords required")
    system = (
        "You are an AI assistant for Haven, a women's safety platform. "
        "Expand brief keywords from a woman in distress into a clear, complete distress message. "
        "Output ONLY the expanded message, nothing else."
    )
    user_prompt = f"### USER KEYWORDS ###\n{keywords}\n### CONTEXT ###\n{context}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]
    result = call_groq(messages)
    # Some models wrap chain-of-thought in <think>…</think>; keep only the answer.
    expanded = re.sub(r'(?is)<think>.*?</think>', '', result).strip()
    if not expanded:
        # Never return HTTP 200 with an empty/malformed message. Surface a clean
        # error the frontend can classify instead of a valid-looking empty body.
        raise HTTPException(status_code=502, detail="Could not generate a message right now. Please try again.")
    return {"expanded_message": expanded}


@router.post("/img-generation")
def img_generation(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
):
    """Generate a benign cover image for steganography."""
    prompt = body.get("prompt", "peaceful garden")[:250]
    image_bytes = generate_image_hf(prompt)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        img.save(output, format="PNG")
        image_bytes = output.getvalue()
    except Exception as e:
        logger.warning(f"Image convert error: {e}")
    b64 = base64.b64encode(image_bytes).decode()
    return {"image_base64": b64, "format": "png"}


@router.post("/text-decomposition")
def text_decomposition(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    """Extract structured JSON from a distress message."""
    text = body.get("text", "")[:2000]
    messages = [
        {
            "role": "system",
            "content": (
                'Extract structured info from a distress message. '
                'Return ONLY valid JSON: '
                '{"severity":"low|medium|high|critical","location":"string or null",'
                '"nature_of_abuse":"string","immediate_danger":true,"needs":["list"],"summary":"string"}'
            )
        },
        {"role": "user", "content": f"Decompose this text: \n```\n{text}\n```"}
    ]
    result = call_groq(messages)
    try:
        parsed = json.loads(re.sub(r'```json|```', '', result).strip())
    except Exception:
        parsed = {"severity": "unknown", "summary": text[:200]}
    return parsed


@router.post("/generate-poem")
async def generate_poem(
    data: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=15, window_seconds=60))
):
    """Generate an empowering therapeutic poem."""
    import os
    from google import genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    try:
        emotional_state = data.get("emotional_state", "in need of hope and strength")[:100]
        prompt = f"""Write a short, beautiful, empowering poem (8-12 lines) for a woman who is feeling {emotional_state}.
The poem should be:
- Warm, gentle and hopeful
- About inner strength and resilience
- Not mention abuse or violence directly
- End with an uplifting message

Write ONLY the poem, no title, no explanation."""
        poem_text = ""
        if genai_client:
            response = genai_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            if response.text:
                poem_text = response.text.strip()
        if not poem_text:
            poem_text = "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."
        return {"poem": poem_text}
    except Exception as e:
        logger.warning(f"Poem error: {e}")
        return {"poem": "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."}


# ─── NEW AI Endpoints ─────────────────────────────────────

@router.post("/ai/classify-risk")
def classify_risk_endpoint(
    body: dict = Body(...),
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Classify SOS text for risk severity using AI (DEMO mode).

    Two paths, deliberately different in their trust requirements:

      * No ``case_id`` — ephemeral analysis, nothing is written. This preserves
        the anonymous SOS triage flow (a woman in distress may not be signed in),
        so it stays open but rate-limited.
      * With ``case_id`` — the AI verdict is PERSISTED against that case. This is
        an authenticated, authorized write: the caller must be signed in AND own
        the case (or be an authority/admin). A body-supplied ``user_id`` is never
        trusted — ownership is derived from the stored case document. This closes
        the IDOR where any caller could write an AI analysis onto an unrelated case.
    """
    text = body.get("text", "")[:2000]
    case_id = body.get("case_id")
    if not text:
        raise HTTPException(status_code=400, detail="text required")

    result = risk_classifier.classify(text)

    # Store analysis. The AI verdict is snapshotted into an IMMUTABLE `ai_prediction`
    # field on first classification and never overwritten by human review — the
    # override endpoint writes a separate `human_review` record. Top-level fields
    # mirror the latest AI result for backwards-compatible reads.
    if case_id:
        # Persisting requires authentication...
        if current_user is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required to persist risk analysis against a case.",
            )
        # ...and authorization for THIS case. Load the owner from the stored case
        # (never from the request body) and enforce self-or-authority access.
        cases_coll = sos_cases()
        if cases_coll is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        case = cases_coll.find_one({"case_id": case_id}, {"_id": 0, "user_id": 1})
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        require_self_or_authority(str(case.get("user_id", "")), current_user)

        coll = ai_analyses()
        if coll is not None:
            now = datetime.utcnow()
            ai_snapshot = {
                "severity": result.get("severity"),
                "risk_score": result.get("risk_score"),
                "indicators": result.get("indicators", []),
                "confidence": result.get("confidence"),
                "explanation": result.get("explanation", ""),
                "model_backend": result.get("backend"),
                "model_name": result.get("model_name"),
                "model_version": result.get("model_version"),
                "model_state": result.get("model_state"),
                "is_demo_mode": result.get("is_demo_mode", True),
                "predicted_at": now,
            }
            mirror = dict(result)
            mirror["case_id"] = case_id
            mirror["analyzed_at"] = now
            mirror["analyzed_by"] = "ai_engine"
            coll.update_one(
                {"case_id": case_id},
                {
                    "$set": mirror,
                    # Only set the immutable snapshot + null review the FIRST time.
                    "$setOnInsert": {"ai_prediction": ai_snapshot, "human_review": None},
                },
                upsert=True,
            )
    return result


@router.get("/ai/model-info")
def ai_model_info():
    """Report the active risk-classification backend and whether it is DEMO.

    Public + read-only so the frontend can honestly badge AI output. Never
    returns model paths or secrets.
    """
    return risk_classifier.info()


@router.get("/ai/embedding-info")
def ai_embedding_info():
    """Report the embedding backend used for semantic search (no secrets).

    Exposes model name/version/dimension and status (ACTIVE / FALLBACK / DEMO)
    so the UI can honestly show whether semantic search is really running.
    """
    from services.embeddings import embedding_info
    return embedding_info()


@router.post("/ai/summarize-case")
def summarize_case_endpoint(
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority)
):
    """Generate AI case summary for authorities."""
    case_id = body.get("case_id", "")
    if not case_id:
        raise HTTPException(status_code=400, detail="case_id required")

    collection = sos_cases()
    if collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    case_data = collection.find_one({"case_id": case_id}, {"_id": 0, "evidence": 0, "embedding": 0})
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")

    summary = summarize_case(serialize_doc(case_data))
    return summary


@router.get("/ai/analysis/{case_id}")
def get_ai_analysis(
    case_id: str,
    current_user: AuthUser = Depends(require_authority)
):
    """Get stored AI analysis for a case."""
    coll = ai_analyses()
    if coll is None:
        return {"analysis": None}
    doc = coll.find_one({"case_id": case_id}, {"_id": 0})
    return {"analysis": serialize_doc(doc) if doc else None}


@router.patch("/ai/analysis/{case_id}/override")
def override_ai_analysis(
    case_id: str,
    body: dict = Body(...),
    current_user: AuthUser = Depends(require_authority)
):
    """Human-in-the-loop review of an AI classification (Phase 1).

    Records a review WITHOUT overwriting the original AI prediction. The
    `action` field is "override" (default) or "accept". The immutable
    `ai_prediction` snapshot is preserved; the human decision is stored under
    `human_review`. Both remain readable via GET /ai/analysis/{case_id}.
    """
    from services.audit_service import log_audit
    coll = ai_analyses()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    doc = coll.find_one({"case_id": case_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No AI analysis found for this case")

    action = str(body.get("action", "override")).lower()
    if action not in ("accept", "override"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'override'")

    # Ensure the immutable AI snapshot exists even for analyses stored before this
    # field was introduced — backfill from the doc's top-level fields, once.
    set_fields = {}
    if not doc.get("ai_prediction"):
        set_fields["ai_prediction"] = {
            "severity": doc.get("severity"),
            "risk_score": doc.get("risk_score"),
            "indicators": doc.get("indicators", []),
            "confidence": doc.get("confidence"),
            "explanation": doc.get("explanation", ""),
            "model_backend": doc.get("backend"),
            "model_name": doc.get("model_name"),
            "model_version": doc.get("model_version"),
            "is_demo_mode": doc.get("is_demo_mode", True),
            "predicted_at": doc.get("analyzed_at"),
        }

    if action == "accept":
        human_review = {
            "action": "accept",
            "severity": doc.get("ai_prediction", {}).get("severity") or doc.get("severity"),
            "risk_score": doc.get("ai_prediction", {}).get("risk_score") or doc.get("risk_score"),
            "reason": body.get("reason", "AI classification accepted by reviewer"),
            "notes": body.get("notes", ""),
            "reviewer_id": current_user.user_id,
            "reviewed_at": datetime.utcnow(),
        }
        audit_action = "AI_RESULT_REVIEWED"
    else:
        if body.get("severity") is None:
            raise HTTPException(status_code=400, detail="override requires a 'severity'")
        human_review = {
            "action": "override",
            "severity": body.get("severity"),
            "risk_score": body.get("risk_score"),
            "reason": body.get("reason", ""),
            "notes": body.get("notes", ""),
            "reviewer_id": current_user.user_id,
            "reviewed_at": datetime.utcnow(),
        }
        audit_action = "SEVERITY_OVERRIDDEN"

    set_fields["human_review"] = human_review
    # Back-compat: keep the old field populated too, but never touch ai_prediction.
    set_fields["human_override"] = human_review if action == "override" else None

    coll.update_one({"case_id": case_id}, {"$set": set_fields})
    log_audit(current_user.user_id, current_user.role, audit_action,
              case_id=case_id, reason=body.get("reason", ""))
    return {
        "success": True,
        "case_id": case_id,
        "action": action,
        "human_review": serialize_doc(human_review),
        "message": f"AI classification {action}ed; original AI prediction preserved",
    }
