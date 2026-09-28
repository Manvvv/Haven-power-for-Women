import os
import logging
import requests
from fastapi import HTTPException
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger("haven_backend")
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def call_gemini(prompt: str, system: str = "") -> str:
    """Call Gemini API with safe error handling without leaking upstream details."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": full_prompt}]}]},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Gemini upstream error code {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=502, detail="AI Service temporarily unavailable. Please try again later.")
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gemini connection error: {str(e)}")
        raise HTTPException(status_code=502, detail="AI Service connection timeout.")

def call_groq(messages: list, model: str = "openai/gpt-oss-120b", max_tokens: int = 1024) -> str:
    """Call Groq API with sanitized error handling and automatic model/Gemini fallback."""
    candidate_models = [model]
    for fallback in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_error = None
    if GROQ_API_KEY:
        for candidate in candidate_models:
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": candidate, "messages": messages, "max_tokens": max_tokens},
                    timeout=30,
                )
                if resp.status_code == 200:
                    # Extract content defensively. Reasoning models (e.g. gpt-oss)
                    # can return a 200 with an EMPTY `content` when the answer never
                    # reaches the final channel. Treat that as a soft failure and try
                    # the next candidate/provider rather than returning an empty body.
                    try:
                        content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
                    except (KeyError, IndexError, ValueError):
                        content = ""
                    if content:
                        return content
                    logger.warning(f"Groq model {candidate} returned 200 with empty content; trying next candidate")
                    last_error = f"empty content from {candidate}"
                    continue
                logger.warning(f"Groq upstream error code {resp.status_code} for model {candidate}: {resp.text}")
                last_error = f"Groq status {resp.status_code}"
            except Exception as e:
                logger.warning(f"Groq error with model {candidate}: {str(e)}")
                last_error = str(e)

    # Fallback to Gemini if Groq fails or key is missing
    if GEMINI_API_KEY:
        try:
            logger.info("Falling back to Gemini for language generation...")
            system_parts = [m["content"] for m in messages if m.get("role") == "system"]
            user_parts = [m["content"] for m in messages if m.get("role") in ["user", "assistant"]]
            system_str = "\n\n".join(system_parts)
            prompt_str = "\n\n".join(user_parts)
            return call_gemini(prompt=prompt_str, system=system_str)
        except Exception as e:
            logger.error(f"Gemini fallback failed: {str(e)}")

    logger.error(f"All LLM providers failed. Last error: {last_error}")
    raise HTTPException(status_code=502, detail="Language model service is currently unavailable.")


def get_embedding(text: str) -> list:
    """Get vector embedding from Gemini with sanitized errors."""
    try:
        resp = requests.post(
            f"{GEMINI_EMBED_URL}?key={GEMINI_API_KEY}",
            json={"model": "models/gemini-embedding-001", "content": {"parts": [{"text": text[:2000]}]}},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Embedding upstream error code {resp.status_code}")
            # Fallback zero-vector of length 768 to prevent complete endpoint crash
            return [0.0] * 768
        return resp.json()["embedding"]["values"]
    except Exception as e:
        logger.error(f"Embedding generation error: {str(e)}")
        return [0.0] * 768

def classify_risk(text: str) -> dict:
    """Classify risk using structured prompt."""
    from services.ai_contract import parse_llm_json
    from services import prompt_registry as PR
    prompt = f"Classify the following text for risk severity and indicators. Return only JSON with severity, risk_score, indicators, confidence, explanation.\n\nText: {text}"
    system = PR.system_text("risk_classify")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    result = call_groq(messages)
    parsed = parse_llm_json(result) or {}
    out = {
        "severity": parsed.get("severity", "UNKNOWN"),
        "risk_score": parsed.get("risk_score", 0),
        "indicators": parsed.get("indicators", []),
        "confidence": parsed.get("confidence", 0),
        "explanation": parsed.get("explanation", ""),
        "model_version": "groq-demo-v1",
        "is_demo_mode": True
    }
    return PR.stamp(out, prompt_id="risk_classify")

def summarize_case(case_data: dict) -> dict:
    """Summarize case."""
    from services.ai_contract import parse_llm_json
    from services import prompt_registry as PR
    prompt = f"Summarize the following case data. Return JSON with situation_summary, detected_concerns, risk_indicators, location_info, requested_assistance, review_priority, disclaimer.\n\nData: {case_data}"
    system = PR.system_text("case_summarize")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    result = call_groq(messages)
    return PR.stamp(parse_llm_json(result) or {}, prompt_id="case_summarize")

def detect_emergency_intent(transcript: str) -> dict:
    """Detect emergency intent."""
    from services.ai_contract import parse_llm_json
    from services import prompt_registry as PR
    prompt = f"Detect emergency intent from transcript. Return JSON with is_emergency, confidence, primary_intent.\n\nTranscript: {transcript}"
    system = PR.system_text("intent_detect")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    result = call_groq(messages)
    return PR.stamp(parse_llm_json(result) or {}, prompt_id="intent_detect")
