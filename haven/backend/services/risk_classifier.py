"""
RiskClassifier — public facade over the swappable AI/ML risk engine.

Backwards compatible: the same `RiskClassifier().classify(text)` call used by
routers/ai_routes.py keeps working and still returns
severity / risk_score / indicators / confidence / explanation / model_version /
is_demo_mode. The heavy lifting now lives in services.ml.risk_engine, which
picks the best installed backend (DistilBERT -> sklearn -> rule lexicon) without
changing this contract.

Set HAVEN_RISK_LLM_ENRICH=1 to additionally ask the existing LLM to refine the
free-text `explanation` (never the severity/score — those stay model-driven).
The LLM is optional and its failure never breaks classification.
"""
import logging
import os

from services.ml.preprocessing import SEVERITY_LEVELS, INDICATORS
from services.ml.risk_engine import get_engine

logger = logging.getLogger("haven_backend")


class RiskClassifier:
    SEVERITY_LEVELS = SEVERITY_LEVELS
    INDICATORS = INDICATORS

    def __init__(self):
        # Constructing the engine here loads the best available backend once.
        self._engine = get_engine()

    def classify(self, text: str) -> dict:
        """Classify SOS text -> canonical risk result (see module docstring)."""
        result = self._engine.predict(text)

        if os.getenv("HAVEN_RISK_LLM_ENRICH", "").strip() == "1":
            result = self._maybe_enrich(text, result)

        # Defensive: guarantee the contract keys/types the API + tests expect.
        result.setdefault("severity", "LOW")
        result.setdefault("risk_score", 0)
        result.setdefault("indicators", [])
        result.setdefault("confidence", 0.0)
        result.setdefault("explanation", "")
        result.setdefault("model_version", "unknown")
        result.setdefault("is_demo_mode", True)
        return result

    def info(self) -> dict:
        """Expose active backend + demo status for /ai/model-info."""
        return self._engine.info()

    def _maybe_enrich(self, text: str, result: dict) -> dict:
        """Optionally let the LLM produce a richer explanation. Never changes
        the model's severity or score. Failures are swallowed."""
        try:
            from services.ai_service import call_groq
            prompt = (
                "A risk model classified a women's-safety SOS message as "
                f"severity={result['severity']} (indicators={result['indicators']}). "
                "Write ONE concise sentence explaining, for a human dispatcher, why this "
                "severity is plausible. Do not restate the severity label. Message:\n"
                f"{text[:800]}"
            )
            enriched = call_groq([{"role": "user", "content": prompt}]).strip()
            if enriched:
                result = dict(result)
                result["explanation"] = enriched + " (AI decision support only — verify before acting.)"
                result["model_version"] = result.get("model_version", "") + "+llm-explain"
        except Exception as e:
            logger.info("RiskClassifier LLM enrichment skipped: %s", e)
        return result
