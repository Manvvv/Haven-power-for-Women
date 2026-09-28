from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime

class CaseUpdateModel(BaseModel):
    status: Optional[str] = Field(None, max_length=50)
    dispatcher_notes: Optional[str] = Field(None, max_length=500)
    assigned_unit: Optional[str] = Field(None, max_length=100)
    priority: Optional[str] = Field(None, max_length=20)
    severity: Optional[str] = Field(None, max_length=20)

class TrustedContactModel(BaseModel):
    name: str = Field(..., max_length=100)
    phone: str = Field(..., max_length=30)
    email: Optional[str] = Field("", max_length=120)
    priority: int = Field(1, ge=1, le=10)

class VoiceSOSConfigModel(BaseModel):
    user_id: str
    enabled: bool = True
    # Optional so an EXISTING config can be updated (e.g. toggling `enabled`)
    # without resending the secret. The route requires a safe word when CREATING
    # a config and preserves the stored hash when it is omitted on update.
    safe_word: Optional[str] = Field(None, min_length=2, max_length=100)
    cooldown_seconds: int = Field(60, ge=10, le=600)
    contacts: List[TrustedContactModel] = []

class VoiceSOSTriggerModel(BaseModel):
    user_id: str
    spoken_phrase: Optional[str] = None
    hashed_safe_word: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    location_accuracy: float = 0.0
    timestamp: Optional[str] = ""
    # Optional voice-AI metadata (Voice AI pipeline). No raw audio is stored.
    transcript: Optional[str] = Field(None, max_length=2000)
    intent: Optional[str] = Field(None, max_length=30)
    severity: Optional[str] = Field(None, max_length=20)
    risk_score: Optional[int] = Field(None, ge=0, le=100)

class VoiceAnalyzeModel(BaseModel):
    """Analyze a speech transcript: intent + reuse the existing risk classifier."""
    transcript: str = Field(..., max_length=2000)
    recognition_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    case_id: Optional[str] = Field(None, max_length=100)

class EvidenceUploadModel(BaseModel):
    case_id: str = Field(..., max_length=100)
    audio_base64: str = Field("", max_length=20_000_000)
    image_base64: str = Field("", max_length=20_000_000)
    mime_type_audio: str = "audio/webm"
    mime_type_image: str = "image/jpeg"
    duration_seconds: float = 0.0
    device_info: str = ""
    timestamp: str = ""

class LocationUpdateModel(BaseModel):
    event_id: str = Field(..., max_length=100)
    latitude: float
    longitude: float
    # Optional device telemetry. Default None (NOT 5.0/0.0) so the backend never
    # fabricates precision the client did not actually report — only stored/echoed
    # when the device genuinely supplies them.
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    timestamp: str = ""

class DispatchWebhookModel(BaseModel):
    case_id: str
    agency_type: str = "ERSS_112"
    priority: str = "CRITICAL"
    dispatcher_notes: str = ""

class GenerateDIRFormModel(BaseModel):
    case_id: str
    officer_name: str = ""
    officer_designation: str = ""
    station_name: str = ""
    district: str = ""

class DiscreetDispatchModel(BaseModel):
    case_id: str
    dispatch_type: str
    priority: str = "HIGH"
    dispatcher_notes: str = ""
    silent_approach: bool = True

class RiskAssessmentModel(BaseModel):
    severity: str
    risk_score: int
    indicators: List[str]
    confidence: float
    explanation: str
    model_version: str
    is_demo_mode: bool
    # Phase 1 model metadata (optional for backwards compatibility).
    backend: Optional[str] = None
    model_name: Optional[str] = None
    model_state: Optional[str] = None
    classified_at: Optional[str] = None

class AIReviewModel(BaseModel):
    """Human-in-the-loop review of an AI risk classification (Phase 1)."""
    action: str = Field("override", pattern="^(accept|override)$")
    severity: Optional[str] = Field(None, max_length=20)
    risk_score: Optional[int] = Field(None, ge=0, le=100)
    reason: str = Field("", max_length=500)
    notes: str = Field("", max_length=1000)

class CaseSummaryModel(BaseModel):
    situation_summary: str
    detected_concerns: List[str]
    risk_indicators: List[str]
    location_info: dict
    requested_assistance: List[str]
    review_priority: str
    disclaimer: str

class AuditLogModel(BaseModel):
    audit_id: str
    actor_id: str
    role: str
    action: str
    case_id: Optional[str] = None
    result: str
    reason: str
    ip_address: str
    timestamp: datetime

class NotificationModel(BaseModel):
    notification_id: str
    recipient_id: str
    event_type: str
    title: str
    message: str
    case_id: str
    read: bool
    created_at: datetime

class PrivacyDataRequestModel(BaseModel):
    user_id: str
    request_type: str
    reason: str

class SOSStatusTransitionModel(BaseModel):
    case_id: str
    new_status: str
    notes: Optional[str] = ""


# ─────────── Mental Health / Therapy (safety-first emotional support) ───────────
# These power the upgraded /therapy/* endpoints. Deterministic safety triage runs
# BEFORE any LLM call; crisis/medication answers never depend on a model. Sensitive
# data (safety plan, journal) is stored ENCRYPTED at rest and is user-controlled.

class MentalHealthChatModel(BaseModel):
    """A single mental-health support turn. Triage runs first, then A→B routing."""
    message: str = Field("", max_length=2000)          # spec §28 max prompt size
    session_id: Optional[str] = Field(None, max_length=120)
    # Language hint: "en" | "hi" | "hinglish" (auto-detected when omitted, spec §12).
    language: Optional[str] = Field(None, max_length=12)
    # Privacy control (spec §14): when False this turn is NOT persisted anywhere.
    save: bool = True
    # Optional region hint used ONLY to order national professional pointers (§23).
    state: Optional[str] = Field(None, max_length=60)
    # Back-compat with the previous client which sent {"user_id","lang"}.
    user_id: Optional[str] = Field(None, max_length=120)
    lang: Optional[str] = Field(None, max_length=12)


class MentalHealthChatResponse(BaseModel):
    """Structured, safety-first response (spec §34). No classifier reasoning exposed."""
    response: str
    risk_level: str
    crisis: bool = False
    needs_clarification: bool = False
    clarifying_question: Optional[str] = None
    coping_tools: List[Dict[str, Any]] = []
    emergency_resources: List[Dict[str, Any]] = []
    professional_resources: List[Dict[str, Any]] = []
    safety_plan: Optional[Dict[str, Any]] = None
    language: str = "en"
    # Language contract (spec §12/§20) — additive, non-breaking. `language` is kept
    # for existing clients; these describe how language was resolved this turn.
    detected_language: str = "en"          # what triage detected from the message
    response_language: str = "en"          # language the reply is actually written in
    supported_languages: List[str] = []    # codes the backend can respond in
    fallback_used: bool = False            # True when reply fell back to English
    sources: List[Dict[str, Any]] = []
    disclaimer: Optional[str] = None
    # Operational (non-clinical) fields the UI uses to adapt the view.
    session_id: Optional[str] = None
    mode: str = "normal"
    ai_available: bool = True
    saved: bool = True


class SafetyPlanModel(BaseModel):
    """User-controlled personal safety plan (spec §9). Stored ENCRYPTED at rest."""
    warning_signs: List[str] = Field(default_factory=list)
    people_to_contact: List[str] = Field(default_factory=list)
    safe_places: List[str] = Field(default_factory=list)
    things_that_help: List[str] = Field(default_factory=list)
    things_to_remove_or_avoid: List[str] = Field(default_factory=list)
    professional_contacts: List[str] = Field(default_factory=list)
    emergency_contacts: List[str] = Field(default_factory=list)


class MoodCheckinModel(BaseModel):
    """Optional lightweight check-in (spec §21). NOT a clinical/diagnostic score."""
    mood: Optional[int] = Field(None, ge=1, le=5)
    stress: Optional[int] = Field(None, ge=1, le=5)
    sleep: Optional[int] = Field(None, ge=1, le=5)
    safety: Optional[int] = Field(None, ge=1, le=5)
    support_connection: Optional[int] = Field(None, ge=1, le=5)
    note: Optional[str] = Field(None, max_length=500)


class MoodJournalEntryModel(BaseModel):
    """Optional private journal entry (spec §22). Stored ENCRYPTED at rest."""
    mood: Optional[str] = Field(None, max_length=60)
    tags: List[str] = Field(default_factory=list)
    notes: str = Field("", max_length=5000)


# ─────────────────────── Unified AI response contract ───────────────────────
# Typed wire shape for the shared AI contract (audit gap #9). The validate/repair
# ENGINE lives in services/ai_contract.py (pure stdlib, unit-tested); this model
# is the optional FastAPI `response_model` view over that same shape. Field names
# and defaults are kept in lockstep with services.ai_contract.build().
#
# SAFETY: `reasoning_summary` carries OBSERVABLE EVIDENCE ONLY — never the model's
# hidden chain-of-thought (services.ai_contract.sanitize_reasoning_summary strips
# deliberation before it is ever set). This contract is a presentation shape; it
# never controls role, SOS lifecycle, dispatch, DB authorization, suspension,
# legal status, or identity.
class AIResponse(BaseModel):
    result: Any = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: str = "unknown"
    reasoning_summary: str = ""
    signals: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    grounded: bool = False
    model: str = "deterministic"
    version: str = ""
    degraded: bool = False
    needs_human_review: bool = False
    # Additive observability tag (which engine produced this). Not reasoning.
    subsystem: str = "unknown"
