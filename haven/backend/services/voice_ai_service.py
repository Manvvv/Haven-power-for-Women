"""
Voice AI Service — Whisper Speech Transcription & Emergency Information Extraction.

Strictly honors HAVEN V2 reliability & honesty principles:
  * Never fabricates a transcription when no Whisper provider API key is present;
    explicitly reports missing environment variables (GROQ_API_KEY or OPENAI_API_KEY).
  * Rejects invalid/oversized/unsupported audio payloads before outbound API calls.
  * Emergency information extraction reuses HAVEN's existing deterministic intent
    & risk engines first, enriched cleanly with LLM JSON extraction when available.
  * AI-extracted location is ALWAYS flagged `is_gps_confirmed=False`.
  * AI-suggested urgency is ALWAYS labelled a suggestion, never a verified assessment.
  * Never auto-dispatches emergency services (`auto_dispatched=False`).
"""
import base64
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from services.intent_service import detect_intent
from services.risk_classifier import RiskClassifier
from services.ai_contract import parse_llm_json

logger = logging.getLogger("haven_backend")

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB ceiling

_MIME_TO_EXT: Dict[str, str] = {
    "audio/webm": "webm",
    "audio/webm;codecs=opus": "webm",
    "audio/ogg": "ogg",
    "audio/ogg;codecs=opus": "ogg",
    "audio/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/aac": "aac",
}

_VALID_CATEGORIES = (
    "immediate_danger",
    "stalking",
    "domestic_violence",
    "harassment",
    "assault",
    "medical",
    "unsafe_transit",
    "other",
)

_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_OPENAI_WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

# Preposition + landmark pattern for deterministic mentioned-location extraction
# when LLM is offline/unavailable (e.g. "near the metro station", "at Connaught Place").
_LOC_PATTERN = re.compile(
    r"\b(?:near|at|outside|inside|behind|opposite|towards|by|pass|pas|ke paas)\s+"
    r"(?:the\s+)?([A-Za-z0-9\u0900-\u097F][A-Za-z0-9\u0900-\u097F\s,'-]{2,45}?)"
    r"(?=[.,;!?]|\s+(?:and|please|help|i|he|she|they|someone|urgent|now|jaldi)\b|$)",
    re.IGNORECASE,
)


def get_stt_status() -> Dict[str, Any]:
    """Return honest Whisper STT configuration status without exposing any keys."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if groq_key:
        return {
            "available": True,
            "provider": "groq_whisper",
            "model": "whisper-large-v3-turbo",
            "supported_languages": ["auto", "en", "hi"],
            "missing_env": [],
            "setup_hint": None,
        }
    if openai_key:
        return {
            "available": True,
            "provider": "openai_whisper",
            "model": "whisper-1",
            "supported_languages": ["auto", "en", "hi"],
            "missing_env": [],
            "setup_hint": None,
        }
    return {
        "available": False,
        "provider": None,
        "model": None,
        "supported_languages": ["en", "hi"],
        "missing_env": ["GROQ_API_KEY", "OPENAI_API_KEY"],
        "setup_hint": "Set GROQ_API_KEY (recommended, Whisper large-v3-turbo) or OPENAI_API_KEY in backend/.env to enable audio transcription.",
    }


def _decode_audio(audio_b64: str, mime_type: str) -> Tuple[bytes, str, str]:
    """Validate mime type and decode base64/data-URI audio safely."""
    clean_mime = (mime_type or "audio/webm").strip().lower().split(";")[0].strip()
    full_mime = (mime_type or "audio/webm").strip().lower()
    ext = _MIME_TO_EXT.get(full_mime) or _MIME_TO_EXT.get(clean_mime)
    if not ext:
        raise ValueError(f"Unsupported audio format '{mime_type}'. Allowed: webm, ogg, mp4, m4a, mp3, wav, aac.")

    raw_b64 = (audio_b64 or "").strip()
    if "," in raw_b64 and raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1].strip()
    if not raw_b64:
        raise ValueError("Audio payload is empty.")

    try:
        audio_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 audio payload.") from exc

    if not audio_bytes:
        raise ValueError("Decoded audio is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError("Audio exceeds the 10 MB maximum upload limit.")
    return audio_bytes, clean_mime, ext


def transcribe_audio_whisper(audio_b64: str, mime_type: str, language: str = "auto") -> Dict[str, Any]:
    """Transcribe uploaded audio via configured Whisper provider (Groq or OpenAI).

    Never returns fake text if credentials are absent or the upstream call fails.
    """
    status = get_stt_status()
    if not status["available"]:
        return {
            "available": False,
            "error_code": "STT_NOT_CONFIGURED",
            "missing_env": status["missing_env"],
            "detail": status["setup_hint"],
        }

    audio_bytes, clean_mime, ext = _decode_audio(audio_b64, mime_type)

    lang_norm = (language or "auto").strip().lower()
    if lang_norm not in ("auto", "en", "hi"):
        lang_norm = "auto"

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    provider = "groq_whisper" if groq_key else "openai_whisper"
    url = _GROQ_WHISPER_URL if groq_key else _OPENAI_WHISPER_URL
    key = groq_key or openai_key
    model = "whisper-large-v3-turbo" if groq_key else "whisper-1"

    data: Dict[str, Any] = {"model": model, "response_format": "verbose_json"}
    if lang_norm in ("en", "hi"):
        data["language"] = lang_norm

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files={"file": (f"voice_sos.{ext}", audio_bytes, clean_mime)},
            timeout=45,
        )
    except requests.RequestException as exc:
        logger.warning("Whisper STT network error (%s): %s", provider, type(exc).__name__)
        return {
            "available": False,
            "error_code": "STT_UPSTREAM_TIMEOUT",
            "detail": "Speech transcription service could not be reached right now.",
        }

    if resp.status_code != 200:
        logger.warning("Whisper STT upstream status=%d provider=%s", resp.status_code, provider)
        return {
            "available": False,
            "error_code": "STT_UPSTREAM_ERROR",
            "detail": f"Speech transcription failed upstream (status {resp.status_code}). Check API key validity or type details manually.",
        }

    payload = resp.json() if resp.content else {}
    transcript = (payload.get("text") or "").strip()
    detected_lang = (payload.get("language") or lang_norm or "unknown").strip()
    return {
        "available": True,
        "transcript": transcript,
        "language_detected": detected_lang,
        "provider": provider,
        "model": model,
        "raw_audio_retained": False,
    }


def _infer_category(transcript: str, indicators: List[str]) -> str:
    """Deterministic mapping from transcript + indicators into HAVEN canonical SOS categories."""
    low = transcript.lower()
    ind_set = set(indicators)
    if "stalking" in ind_set or any(w in low for w in ("following me", "stalking", "follow me", "पीछा")):
        return "stalking"
    if "domestic" in low or "husband" in low or "home" in low or "confinement" in ind_set or "घरेलू" in transcript:
        return "domestic_violence"
    if "physical_assault" in ind_set or any(w in low for w in ("hit", "beat", "attack", "assault", "मार")):
        return "assault"
    if "harass" in low or "threat" in ind_set or "धमकी" in transcript or "परेशान" in transcript:
        return "harassment"
    if any(w in low for w in ("bus", "cab", "auto", "taxi", "metro", "train", "station", "stranded", "मेट्रो")):
        return "unsafe_transit"
    if any(w in low for w in ("bleed", "injured", "ambulance", "hospital", "medical", "unconscious", "दर्द")):
        return "medical"
    if "immediate_danger" in ind_set or "emergency_assistance_request" in ind_set:
        return "immediate_danger"
    return "other"


def _extract_location_rule(transcript: str) -> Optional[str]:
    m = _LOC_PATTERN.search(transcript or "")
    if not m:
        return None
    candidate = re.sub(r"\s+", " ", m.group(1)).strip(" ,.-")
    return candidate[:140] if len(candidate) >= 3 else None


def extract_emergency_info(transcript: str, language: str = "auto") -> Dict[str, Any]:
    """Extract structured emergency fields from user speech transcript for human review.

    Combines deterministic intent & RiskClassifier first, then optionally enhances
    situation summary & mentioned location via LLM without ever inventing PII or
    marking mentioned text as GPS-confirmed.
    """
    text = (transcript or "").strip()[:3000]
    intent = detect_intent(text)
    risk = RiskClassifier().classify(text)
    indicators = list(risk.get("indicators") or intent.get("signals") or [])

    suggested_category = _infer_category(text, indicators)
    suggested_urgency = str(risk.get("severity") or "medium").lower()
    if suggested_urgency not in ("low", "medium", "high", "critical"):
        suggested_urgency = "high" if intent.get("intent") == "EMERGENCY" else "medium"

    mentioned_location = _extract_location_rule(text)
    description = text
    contextual_info: List[str] = []
    ai_llm_used = False

    if os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip():
        try:
            from services.ai_service import call_groq
            prompt = (
                "Extract ONLY information explicitly present in this emergency transcript. "
                "Do NOT invent names, phone numbers, addresses, or GPS coordinates. "
                "Respond with JSON keys: category (one of immediate_danger, stalking, domestic_violence, "
                "harassment, assault, medical, unsafe_transit, other), description (short plain summary), "
                "mentioned_location (string or null), urgency (critical|high|medium|low), "
                "contextual_notes (list of brief factual clues from transcript).\n\n"
                f"Language hint: {language}\nTranscript:\n{text}"
            )
            raw = call_groq(
                [
                    {"role": "system", "content": "You are a safety triage extraction assistant. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
            )
            parsed = parse_llm_json(raw)
            if isinstance(parsed, dict):
                ai_llm_used = True
                cat = str(parsed.get("category") or "").strip().lower().replace(" ", "_")
                if cat in _VALID_CATEGORIES:
                    suggested_category = cat
                if isinstance(parsed.get("description"), str) and parsed["description"].strip():
                    description = parsed["description"].strip()[:500]
                if isinstance(parsed.get("mentioned_location"), str) and parsed["mentioned_location"].strip():
                    mentioned_location = parsed["mentioned_location"].strip()[:160]
                urg = str(parsed.get("urgency") or "").strip().lower()
                if urg in ("low", "medium", "high", "critical"):
                    suggested_urgency = urg
                notes = parsed.get("contextual_notes")
                if isinstance(notes, list):
                    contextual_info = [str(x).strip()[:160] for x in notes if str(x).strip()][:5]
        except Exception as exc:
            logger.info("Voice AI LLM extraction fallback to rules: %s", type(exc).__name__)

    return {
        "transcript": text,
        "suggested_category": suggested_category,
        "situation_description": description,
        "mentioned_location": mentioned_location,
        "is_gps_confirmed": False,
        "location_disclaimer": "AI-mentioned location from speech only — NOT a GPS-confirmed coordinate.",
        "suggested_urgency": suggested_urgency,
        "urgency_disclaimer": "AI suggestion only — not a verified emergency assessment.",
        "urgency_indicators": indicators,
        "contextual_info": contextual_info,
        "intent": intent,
        "risk": risk,
        "extraction_mode": "llm_plus_rules" if ai_llm_used else "deterministic_rules",
        "requires_human_confirmation": True,
        "auto_dispatched": False,
    }
