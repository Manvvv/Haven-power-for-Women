"""
therapy_routes.py — HAVEN mental-health / emotional-support endpoints.

Safety-first design (spec §2-§4, §16, §27-§29, §34):
  * A DETERMINISTIC triage (mental_health_triage) runs BEFORE any LLM call.
  * HIGH_RISK / IMMINENT_DANGER and medication-dosing turns are answered from
    fixed, reviewed text — they NEVER depend on the model being up or honest.
  * Non-crisis support turns use the LLM with a safety-hardened system prompt and
    fall back to deterministic grounding + resources if the provider is down.
  * Verified resources come only from mental_health_resources (no fabrication).
  * Privacy: raw sensitive text is never logged; sensitive turns are redacted
    before storage; a per-turn "save=false" disables persistence entirely; the
    safety plan and journal are AES-GCM encrypted at rest and user-controlled.
"""
import time
import json
import uuid
import hashlib
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from auth import (AuthUser, get_optional_user, get_current_user,
                  encrypt_evidence_payload, decrypt_evidence_payload)
from rate_limiter import rate_limit_dependency
from services.db import (therapy_sessions, safety_plans, mood_journal,
                         mood_checkins, serialize_doc)
from services.ai_service import call_groq
from services import mental_health_triage as TR
from services import mental_health_support as SUP
from services import mental_health_resources as R
from models.schemas import (MentalHealthChatModel, SafetyPlanModel,
                            MoodCheckinModel, MoodJournalEntryModel)

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Therapy"])

# Legacy single-language codes the old client sent → our 3 supported safety hints.
_LEGACY_LANG = {"en": "en", "en-in": "en", "hi": "hi", "hinglish": "hinglish"}
# Languages the backend can produce REVIEWED deterministic safety text in. Anything
# else falls back to English rather than machine-translating crisis wording (§10).
_SUPPORTED_RESPONSE_LANGS = ["en", "hi", "hinglish"]
# Signals whose raw text must be redacted before any storage (spec §14, §27).
_SENSITIVE_SIGNALS = ("self_harm", "suicide", "abuse", "violence",
                      "psychosis", "medical_emergency")
_REDACTED = "[sensitive message not stored for your privacy]"


def _uid_hash(user_id: Optional[str]) -> str:
    """Stable, non-reversible id for safe logging (spec §27: hash identifiers)."""
    return hashlib.sha256((user_id or "anon").encode("utf-8")).hexdigest()[:12]


def _resolve_lang_hint(model: MentalHealthChatModel) -> Optional[str]:
    raw = (model.language or model.lang or "").strip().lower()
    return _LEGACY_LANG.get(raw)  # None → let the detector decide


def _is_sensitive(triage: "TR.MHTriage") -> bool:
    if triage.crisis or triage.dosing_request:
        return True
    return any(triage.signals.get(s) for s in _SENSITIVE_SIGNALS)


def _resource_category(triage: "TR.MHTriage") -> str:
    if triage.risk_level == TR.IMMINENT:
        return "emergency"
    if triage.risk_level == TR.HIGH:
        return "crisis"
    if triage.dosing_request:
        return "medication"
    if triage.risk_level == TR.MODERATE:
        return "support"
    return "normal"


def _build_sources(*resource_lists) -> list:
    """De-duplicated provenance (name/source_url/verified_at) for shown resources."""
    out, seen = [], set()
    for lst in resource_lists:
        for r in lst or []:
            url = r.get("source_url") or r.get("official_url")
            if url and url not in seen:
                seen.add(url)
                out.append({"name": r.get("name") or r.get("provider_name", ""),
                            "source_url": url, "verified_at": r.get("verified_at", "")})
    return out


def _load_safety_plan(user_id: Optional[str]) -> Optional[dict]:
    """Decrypt and return the user's safety plan, or None. Never raises."""
    if not user_id:
        return None
    coll = safety_plans()
    if coll is None:
        return None
    doc = coll.find_one({"user_id": user_id})
    if not doc or not doc.get("ciphertext"):
        return None
    try:
        plain = decrypt_evidence_payload(doc["ciphertext"], doc.get("nonce", ""))
        data = json.loads(plain)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ────────────────────────────── Main chat turn ──────────────────────────────
@router.post("/therapy/chat")
def therapy_chat(
    body: MentalHealthChatModel = Body(...),
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60, scope="therapy_chat")),
):
    """Safety-first emotional-support turn: deterministic triage → structured reply."""
    t0 = time.time()
    message = (body.message or "")[:2000]
    user_id = current_user.user_id if current_user else (body.user_id or "anonymous")
    session_id = body.session_id

    # 1) DETERMINISTIC triage (no LLM). This is the safety layer.
    triage = TR.build_triage(message, _resolve_lang_hint(body))
    language = triage.language
    dosing = triage.dosing_request

    # 2) Verified resources (never fabricated). Emergency for crisis; escalation
    #    for medication-dosing; professional pointers once distress is real.
    emergency_res = SUP.emergency_resources_for(triage)
    if dosing and not emergency_res:
        emergency_res = R.crisis_resources()
    professional_res = []
    if triage.risk_level in (TR.MODERATE, TR.HIGH, TR.IMMINENT) or dosing \
            or triage.signals.get("abuse"):
        professional_res = R.professional_resources(body.state)
    coping = SUP.coping_tools_for(triage)

    # 3) Compose the reply text. Crisis + medication = DETERMINISTIC (spec §3,§18,§29).
    ai_available = True
    if triage.crisis:
        response_text = SUP.crisis_response_text(triage)          # HIGH / IMMINENT
    elif dosing:
        response_text = SUP.medication_safety_text(language)      # no doses, ever
    else:
        # Non-crisis: empathetic LLM support with a hard deterministic fallback.
        history = []
        coll = therapy_sessions()
        if session_id and coll is not None:
            past = coll.find_one({"session_id": session_id})
            if past:
                if current_user and past.get("user_id") not in (user_id, "anonymous", "anon"):
                    raise HTTPException(status_code=403, detail="Unauthorized access to therapy session")
                # Minimize what leaves the app: a short window of non-sensitive turns
                # only (crisis-tier + redacted messages are dropped). Single choke-point
                # so the /therapy/privacy dashboard can describe this truthfully.
                history = SUP.sanitize_history(past.get("messages", []), _REDACTED)
        try:
            messages = ([{"role": "system", "content": SUP.build_system_prompt(triage, language)}]
                        + history + [{"role": "user", "content": message}])
            response_text = call_groq(messages, max_tokens=220)
        except HTTPException:
            ai_available = False
            response_text = SUP.ai_unavailable_text(language)     # spec §29 failure mode

    # 4) Surface the user's own safety plan during a crisis (spec §9/§10), if any.
    safety_plan = _load_safety_plan(user_id) if (triage.crisis and current_user) else None

    # 5) Persist with privacy minimization (spec §14). save=false → store nothing.
    session_id = session_id or f"SESSION-{user_id}-{int(time.time())}"
    saved = False
    if body.save:
        coll = therapy_sessions()
        if coll is not None:
            if current_user:
                existing = coll.find_one({"session_id": session_id})
                if existing and existing.get("user_id") not in (user_id, "anonymous", "anon"):
                    raise HTTPException(status_code=403, detail="Unauthorized access to therapy session")
            sensitive = _is_sensitive(triage)
            stored_user = _REDACTED if sensitive else message
            coll.update_one(
                {"session_id": session_id},
                {"$set": {"user_id": user_id, "session_id": session_id,
                          "updated_at": datetime.utcnow()},
                 "$push": {"messages": {"$each": [
                     {"role": "user", "content": stored_user, "risk_level": triage.risk_level},
                     {"role": "assistant", "content": response_text},
                 ]}}},
                upsert=True,
            )
            saved = True

    # 6) Observability: SAFE metadata only — never raw text / contacts (spec §27).
    latency_ms = int((time.time() - t0) * 1000)
    provider_status = ("deterministic" if (triage.crisis or dosing)
                       else ("ok" if ai_available else "unavailable"))
    logger.info("mh_chat uid=%s risk=%s lang=%s mode=%s crisis=%s dosing=%s "
                "provider=%s category=%s latency_ms=%d",
                _uid_hash(user_id), triage.risk_level, language, triage.response_mode,
                triage.crisis, dosing, provider_status, _resource_category(triage), latency_ms)

    # Language contract (spec §31) — additive, no classifier reasoning exposed.
    requested_lang = (body.language or body.lang or "").strip().lower() or None
    fallback_used = bool(requested_lang and requested_lang not in _SUPPORTED_RESPONSE_LANGS
                         and requested_lang != language)

    return {
        "response": response_text,
        "risk_level": triage.risk_level,
        "crisis": triage.crisis,
        "needs_clarification": triage.needs_clarification,
        "clarifying_question": triage.clarifying_question,
        "coping_tools": coping,
        "emergency_resources": emergency_res,
        "professional_resources": professional_res,
        "safety_plan": safety_plan,
        "language": language,
        "detected_language": language,
        "response_language": language,
        "supported_languages": _SUPPORTED_RESPONSE_LANGS,
        "fallback_used": fallback_used,
        "sources": _build_sources(emergency_res, professional_res),
        "disclaimer": SUP.disclaimer(),
        "session_id": session_id,
        "mode": triage.response_mode,
        "ai_available": ai_available,
        "saved": saved,
    }


# ─────────── Verified resources & offline pack (NO AI, always available) ───────────
# Higher rate limit than chat: the crisis panel must render even if the AI-backed
# chat endpoint is rate-limited or the provider is down (spec §28, §29).
@router.get("/therapy/resources")
def therapy_resources(
    category: str = "all",
    state: Optional[str] = None,
    _=Depends(rate_limit_dependency(max_requests=120, window_seconds=60, scope="therapy_res")),
):
    """Centralized VERIFIED resource registry (spec §4, §23, §32). Never fabricated."""
    cat = (category or "all").lower()
    if cat == "emergency":
        return {"category": cat, "resources": R.emergency_resources(), "disclaimer": R.DISCLAIMER}
    if cat == "crisis":
        return {"category": cat, "resources": R.crisis_resources(), "disclaimer": R.DISCLAIMER}
    if cat == "support":
        return {"category": cat, "resources": R.support_resources(), "disclaimer": R.DISCLAIMER}
    if cat == "child":
        return {"category": cat, "resources": R.child_resources(), "disclaimer": R.DISCLAIMER}
    if cat == "women":
        return {"category": cat, "resources": R.women_resources(), "disclaimer": R.DISCLAIMER}
    if cat == "professional":
        return {"category": cat, "resources": R.professional_resources(state), "disclaimer": R.DISCLAIMER}
    return {
        "category": "all",
        "emergency": R.emergency_resources(),
        "crisis": R.crisis_resources(),
        "support": R.support_resources(),
        "professional": R.professional_resources(state),
        "version": R.RESOURCES_VERSION,
        "disclaimer": R.DISCLAIMER,
    }


@router.get("/therapy/offline-pack")
def therapy_offline_pack(
    _=Depends(rate_limit_dependency(max_requests=120, window_seconds=60, scope="therapy_offline")),
):
    """Self-contained crisis pack for offline / AI-unavailable use (spec §24, §29)."""
    return R.offline_pack()


@router.get("/therapy/coping-tools")
def therapy_coping_tools(
    _=Depends(rate_limit_dependency(max_requests=120, window_seconds=60, scope="therapy_tools")),
):
    """All low-risk support strategies (spec §8). Explicitly not medical treatment."""
    return {"tools": SUP.all_tools()}


# ─────────── Safety plan — encrypted, user-controlled (spec §9, §35) ───────────
# REQUIRED auth: a safety plan is always tied to one authenticated user, so it can
# never be read or written across users.
@router.get("/therapy/safety-plan")
def get_safety_plan(current_user: AuthUser = Depends(get_current_user)):
    plan = _load_safety_plan(current_user.user_id)
    coll = safety_plans()
    updated_at = None
    if coll is not None:
        doc = coll.find_one({"user_id": current_user.user_id})
        if doc and doc.get("updated_at"):
            updated_at = doc["updated_at"].isoformat() if hasattr(doc["updated_at"], "isoformat") else doc["updated_at"]
    return {"safety_plan": plan, "exists": plan is not None, "updated_at": updated_at}


@router.put("/therapy/safety-plan")
def put_safety_plan(
    body: SafetyPlanModel = Body(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Create or replace the caller's safety plan. Stored AES-GCM encrypted."""
    coll = safety_plans()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    enc = encrypt_evidence_payload(json.dumps(body.model_dump()))
    coll.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"user_id": current_user.user_id, "ciphertext": enc["ciphertext"],
                  "nonce": enc["nonce"], "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    logger.info("mh_safety_plan_saved uid=%s", _uid_hash(current_user.user_id))
    return {"success": True, "message": "Safety plan saved securely."}


@router.delete("/therapy/safety-plan")
def delete_safety_plan(current_user: AuthUser = Depends(get_current_user)):
    coll = safety_plans()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    coll.delete_one({"user_id": current_user.user_id})
    logger.info("mh_safety_plan_deleted uid=%s", _uid_hash(current_user.user_id))
    return {"success": True, "message": "Safety plan deleted."}


# ─────────── Mood check-ins (spec §21) — trends shown to the user only ───────────
@router.post("/therapy/mood-checkin")
def post_mood_checkin(
    body: MoodCheckinModel = Body(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Store a lightweight check-in. NOT a clinical score; note is encrypted."""
    coll = mood_checkins()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    note_enc = encrypt_evidence_payload(body.note) if body.note else {"ciphertext": "", "nonce": ""}
    coll.insert_one({
        "user_id": current_user.user_id,
        "checkin_id": uuid.uuid4().hex,
        "mood": body.mood, "stress": body.stress, "sleep": body.sleep,
        "safety": body.safety, "support_connection": body.support_connection,
        "note_ciphertext": note_enc["ciphertext"], "note_nonce": note_enc["nonce"],
        "created_at": datetime.utcnow(),
    })
    return {"success": True, "message": "Check-in saved. This is for your own reflection."}


@router.get("/therapy/mood-checkins")
def list_mood_checkins(current_user: AuthUser = Depends(get_current_user), limit: int = 30):
    coll = mood_checkins()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    limit = max(1, min(limit, 90))
    docs = list(coll.find({"user_id": current_user.user_id}).sort("created_at", -1).limit(limit))
    out = []
    for d in docs:
        note = ""
        if d.get("note_ciphertext"):
            note = decrypt_evidence_payload(d["note_ciphertext"], d.get("note_nonce", ""))
        out.append({
            "checkin_id": d.get("checkin_id"),
            "mood": d.get("mood"), "stress": d.get("stress"), "sleep": d.get("sleep"),
            "safety": d.get("safety"), "support_connection": d.get("support_connection"),
            "note": note,
            "created_at": d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at"),
        })
    return {"checkins": out}


# ─────────── Mood journal (spec §22) — encrypted, private, deletable ───────────
@router.post("/therapy/journal")
def post_journal(
    body: MoodJournalEntryModel = Body(...),
    current_user: AuthUser = Depends(get_current_user),
):
    """Store a private, ENCRYPTED journal entry owned by the caller."""
    coll = mood_journal()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    enc = encrypt_evidence_payload(json.dumps(body.model_dump()))
    entry_id = uuid.uuid4().hex
    coll.insert_one({
        "user_id": current_user.user_id, "entry_id": entry_id,
        "ciphertext": enc["ciphertext"], "nonce": enc["nonce"],
        "created_at": datetime.utcnow(),
    })
    return {"success": True, "entry_id": entry_id}


@router.get("/therapy/journal")
def list_journal(current_user: AuthUser = Depends(get_current_user), limit: int = 50):
    coll = mood_journal()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    limit = max(1, min(limit, 200))
    docs = list(coll.find({"user_id": current_user.user_id}).sort("created_at", -1).limit(limit))
    out = []
    for d in docs:
        entry = {}
        try:
            entry = json.loads(decrypt_evidence_payload(d["ciphertext"], d.get("nonce", "")))
        except Exception:
            entry = {}
        out.append({
            "entry_id": d.get("entry_id"),
            "mood": entry.get("mood"), "tags": entry.get("tags", []), "notes": entry.get("notes", ""),
            "created_at": d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at"),
        })
    return {"entries": out}


@router.delete("/therapy/journal/{entry_id}")
def delete_journal(entry_id: str, current_user: AuthUser = Depends(get_current_user)):
    coll = mood_journal()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    res = coll.delete_one({"entry_id": entry_id, "user_id": current_user.user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True, "message": "Journal entry deleted."}


# ─────────── Privacy dashboard & deletion controls (spec §14, §15, §35) ───────────
@router.get("/therapy/privacy")
def mental_health_privacy(current_user: AuthUser = Depends(get_current_user)):
    """What is stored, why, retention, access, AI-provider exposure + controls."""
    uid = current_user.user_id
    s_coll, sp_coll, j_coll, c_coll = (therapy_sessions(), safety_plans(),
                                       mood_journal(), mood_checkins())
    counts = {
        "conversations": s_coll.count_documents({"user_id": uid}) if s_coll is not None else 0,
        "safety_plan": (1 if (sp_coll is not None and sp_coll.count_documents({"user_id": uid})) else 0),
        "journal_entries": j_coll.count_documents({"user_id": uid}) if j_coll is not None else 0,
        "mood_checkins": c_coll.count_documents({"user_id": uid}) if c_coll is not None else 0,
    }
    return {
        "stored": counts,
        "details": [
            {"item": "Conversations", "why": "So a chat can continue where you left off.",
             "retention": "Kept until you delete them. Sensitive/crisis messages are redacted before storage.",
             "access": "Only you.", "ai_provider_receives": "Your current message, plus a short window of your most recent non-sensitive chat turns, is sent to the AI provider to generate a reply. Crisis, medication and other sensitive messages are never sent — those replies are generated on-device from fixed text. Your safety plan, journal, mood check-ins and trusted contacts are never sent to the AI."},
            {"item": "Safety plan", "why": "To help you during a hard moment.",
             "retention": "Kept until you delete it.", "access": "Only you.",
             "ai_provider_receives": "Never. Stored encrypted; not sent to any AI provider."},
            {"item": "Journal", "why": "Private reflection you choose to write.",
             "retention": "Kept until you delete it.", "access": "Only you.",
             "ai_provider_receives": "Never. Stored encrypted."},
            {"item": "Mood check-ins", "why": "To show you your own trends over time.",
             "retention": "Kept until you delete all data.", "access": "Only you.",
             "ai_provider_receives": "Never."},
        ],
        "controls": {
            "delete_conversation": "DELETE /therapy/sessions/{session_id}",
            "delete_safety_plan": "DELETE /therapy/safety-plan",
            "delete_journal_entry": "DELETE /therapy/journal/{entry_id}",
            "delete_all_mental_health_data": "DELETE /therapy/mental-health-data",
            "do_not_save_a_chat": "Send \"save\": false with a chat message.",
        },
        "disclaimer": R.DISCLAIMER,
    }


@router.delete("/therapy/mental-health-data")
def delete_all_mh_data(current_user: AuthUser = Depends(get_current_user)):
    """Delete ALL of the caller's mental-health data (spec §15)."""
    uid = current_user.user_id
    removed = {}
    for label, coll in (("conversations", therapy_sessions()), ("safety_plan", safety_plans()),
                        ("journal_entries", mood_journal()), ("mood_checkins", mood_checkins())):
        removed[label] = coll.delete_many({"user_id": uid}).deleted_count if coll is not None else 0
    logger.info("mh_delete_all uid=%s removed=%s", _uid_hash(uid), removed)
    return {"success": True, "deleted": removed,
            "message": "All your mental-health data has been deleted."}


@router.delete("/therapy/sessions/{session_id}")
def delete_therapy_session(
    session_id: str,
    current_user: Optional[AuthUser] = Depends(get_optional_user),
):
    """Delete a single conversation (privacy center). Ownership enforced."""
    coll = therapy_sessions()
    if coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    session = coll.find_one({"session_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    user_id = current_user.user_id if current_user else None
    if user_id and session.get("user_id") not in (user_id, "anonymous"):
        raise HTTPException(status_code=403, detail="Cannot delete another user's session")
    coll.delete_one({"session_id": session_id})
    return {"success": True, "message": "Therapy session deleted"}





