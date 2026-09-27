"""
Emergency intent detection for Voice SOS (Voice AI pipeline).

Position in the pipeline:
    voice -> speech-to-text -> transcript -> [THIS: intent detection]
          -> existing risk classifier -> SOS workflow

Design:
  * Lightweight, explainable, rule-based classifier first — always available,
    no ML dependency, deterministic.
  * Swappable: set HAVEN_INTENT_LLM=1 to use the existing LLM intent detector
    (services.ai_service.detect_emergency_intent) instead; failures fall back to
    rules so the pipeline never hard-fails.
  * Reuses the shared risk lexicon (services.ml.rule_classifier) so intent
    "signals" line up with the risk classifier's indicators — no second model.

Classes: EMERGENCY | POSSIBLE_EMERGENCY | NON_EMERGENCY | UNKNOWN.

The output is decision-support only. Uncertain speech (low recognition
confidence) is intentionally down-graded so the UI asks a human to confirm
rather than auto-escalating.
"""
import logging
import os

from services.ml.preprocessing import clean_text
from services.ml import rule_classifier

logger = logging.getLogger("haven_backend")

INTENT_LEVELS = ["NON_EMERGENCY", "UNKNOWN", "POSSIBLE_EMERGENCY", "EMERGENCY"]
MODEL_VERSION = "intent-rules-v1"

# If browser speech recognition confidence is below this, we cap the intent at
# POSSIBLE_EMERGENCY and flag needs_confirmation — uncertain audio must not
# silently escalate.
LOW_RECOGNITION_CONFIDENCE = 0.5


def _rule_intent(transcript: str) -> dict:
    """Deterministic, explainable intent from the shared risk lexicon."""
    cleaned = clean_text(transcript)
    if not cleaned:
        return {"intent": "UNKNOWN", "confidence": 0.0, "signals": [],
                "explanation": "No transcript to analyse.",
                "method": "rules", "model_version": MODEL_VERSION, "is_demo_mode": True}

    fired = rule_classifier._match_indicators(cleaned)  # {indicator: hits}
    signals = sorted(fired.keys())
    names = set(fired)

    emergency_now = "immediate_danger" in names
    violence = bool(names & {"physical_assault", "confinement"})
    threat_like = bool(names & {"threat", "stalking"})
    asked_help = "emergency_assistance_request" in names

    if emergency_now and (asked_help or violence or threat_like):
        intent, conf = "EMERGENCY", 0.9
    elif violence or (asked_help and (violence or threat_like)):
        intent, conf = "EMERGENCY", 0.8
    elif threat_like or asked_help:
        intent, conf = "POSSIBLE_EMERGENCY", 0.65
    elif signals:
        intent, conf = "POSSIBLE_EMERGENCY", 0.55
    else:
        intent, conf = "NON_EMERGENCY", 0.6

    if signals:
        explanation = (f"Detected {len(signals)} risk signal(s): {', '.join(signals)}. "
                       "Rule-based intent — human confirmation recommended.")
    else:
        explanation = "No emergency signals detected in the transcript."

    return {"intent": intent, "confidence": round(conf, 2), "signals": signals,
            "explanation": explanation, "method": "rules",
            "model_version": MODEL_VERSION, "is_demo_mode": True}


def _llm_intent(transcript: str) -> dict:
    """Optional LLM-backed intent (opt-in). Falls back to rules on any error."""
    try:
        from services.ai_service import detect_emergency_intent
        parsed = detect_emergency_intent(transcript) or {}
        is_emergency = bool(parsed.get("is_emergency"))
        conf = float(parsed.get("confidence", 0.0) or 0.0)
        if conf > 1:  # some models return 0-100
            conf = conf / 100.0
        if is_emergency and conf >= 0.7:
            intent = "EMERGENCY"
        elif is_emergency:
            intent = "POSSIBLE_EMERGENCY"
        elif conf >= 0.5:
            intent = "NON_EMERGENCY"
        else:
            intent = "UNKNOWN"
        # Attach explainable signals from the rule lexicon regardless.
        rule = _rule_intent(transcript)
        return {"intent": intent, "confidence": round(conf, 2),
                "signals": rule["signals"],
                "explanation": parsed.get("primary_intent") or rule["explanation"],
                "method": "llm", "model_version": "intent-llm-v1", "is_demo_mode": True}
    except Exception as e:
        logger.info("intent LLM unavailable, using rules: %s", e)
        return _rule_intent(transcript)


def detect_intent(transcript: str, recognition_confidence: float = None) -> dict:
    """Classify emergency intent from a speech transcript.

    `recognition_confidence` (0..1, optional) is the speech-to-text engine's own
    confidence. Low values down-grade EMERGENCY to POSSIBLE_EMERGENCY and set
    needs_confirmation so uncertain audio triggers a human check, not auto-action.
    """
    transcript = (transcript or "")[:2000]
    use_llm = os.getenv("HAVEN_INTENT_LLM", "").strip() == "1"
    result = _llm_intent(transcript) if use_llm else _rule_intent(transcript)

    needs_confirmation = result["intent"] in ("POSSIBLE_EMERGENCY", "UNKNOWN")

    # Uncertain recognition: never let shaky audio auto-escalate to EMERGENCY.
    if recognition_confidence is not None and recognition_confidence < LOW_RECOGNITION_CONFIDENCE:
        if result["intent"] == "EMERGENCY":
            result["intent"] = "POSSIBLE_EMERGENCY"
            result["explanation"] += (
                f" (Down-graded: low speech-recognition confidence "
                f"{recognition_confidence:.2f} — please confirm.)")
        needs_confirmation = True

    result["recognition_confidence"] = recognition_confidence
    result["needs_confirmation"] = needs_confirmation
    return result
