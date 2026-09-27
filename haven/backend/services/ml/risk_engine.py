"""
Swappable risk-classification engine (Parts 6-8).

Selects the best available backend once, at first use, and exposes a single
`predict(text)` returning the canonical result shape. Swapping the model never
changes the API or frontend contract.

Backend priority (highest first):
    1. transformer  — a fine-tuned DistilBERT text-classifier on disk.
                      Requires torch + transformers AND a real model directory
                      (HAVEN_RISK_MODEL_DIR). Only this tier can set
                      is_demo_mode = False, and only when the operator opts in
                      via HAVEN_RISK_PRODUCTION=1 to affirm the model was trained
                      on representative, labelled production data.
    2. sklearn      — TF-IDF + LogisticRegression baseline loaded from a
                      .joblib artifact (HAVEN_RISK_SKLEARN_PATH). Trained on the
                      *synthetic demo dataset*, so it stays is_demo_mode = True.
    3. rules        — pure-stdlib lexicon scorer. Always available. DEMO.

Environment variables (all optional):
    HAVEN_RISK_BACKEND        force a backend: "transformer" | "sklearn" | "rules"
    HAVEN_RISK_MODEL_DIR      path to a fine-tuned DistilBERT dir (config.json + weights)
    HAVEN_RISK_SKLEARN_PATH   path to a trained sklearn .joblib (default ml/artifacts/sklearn_risk.joblib)
    HAVEN_RISK_PRODUCTION     "1" to allow the transformer tier to report is_demo_mode=False
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from . import rule_classifier
from .preprocessing import clean_text, SEVERITY_LEVELS

logger = logging.getLogger("haven_backend")

# Human-readable model names per backend (Phase 1: model metadata).
_MODEL_NAMES = {
    "rules": "HAVEN Rule Lexicon",
    "sklearn": "TF-IDF + LogisticRegression",
    "transformer": "DistilBERT (fine-tuned)",
}

_BACKEND_DIR = Path(__file__).resolve().parent
_DEFAULT_SKLEARN_PATH = _BACKEND_DIR / "artifacts" / "sklearn_risk.joblib"

# Indicators are always attached by the rule scorer (explainable, model-agnostic),
# even when a learned model decides severity — so authorities always see *why*.
_RESULT_KEYS = ("severity", "risk_score", "indicators", "confidence",
                "explanation", "model_version", "backend", "is_demo_mode")


class RiskEngine:
    """Singleton-style engine. Construct via get_engine()."""

    def __init__(self):
        self.backend = "rules"
        self._sklearn = None          # (vectorizer, model, label_list)
        self._transformer = None      # (pipeline, id2label)
        self._production = os.getenv("HAVEN_RISK_PRODUCTION", "").strip() == "1"
        self._select_backend()

    # ── backend selection ────────────────────────────────────────────────
    def _select_backend(self):
        forced = os.getenv("HAVEN_RISK_BACKEND", "").strip().lower()

        order = ["transformer", "sklearn", "rules"]
        if forced in order:
            order = [forced]

        for name in order:
            if name == "transformer" and self._try_load_transformer():
                self.backend = "transformer"
                logger.info("RiskEngine: using transformer backend (%s)",
                            os.getenv("HAVEN_RISK_MODEL_DIR"))
                return
            if name == "sklearn" and self._try_load_sklearn():
                self.backend = "sklearn"
                logger.info("RiskEngine: using sklearn baseline backend")
                return
            if name == "rules":
                self.backend = "rules"
                logger.info("RiskEngine: using rule-based DEMO backend")
                return
        self.backend = "rules"

    def _try_load_transformer(self) -> bool:
        model_dir = os.getenv("HAVEN_RISK_MODEL_DIR", "").strip()
        if not model_dir or not Path(model_dir).is_dir():
            return False
        try:
            from transformers import (  # noqa: F401  (import is the availability check)
                AutoTokenizer, AutoModelForSequenceClassification, TextClassificationPipeline,
            )
            import torch  # noqa: F401
            tok = AutoTokenizer.from_pretrained(model_dir)
            model = AutoModelForSequenceClassification.from_pretrained(model_dir)
            pipe = TextClassificationPipeline(
                model=model, tokenizer=tok, return_all_scores=True, truncation=True,
            )
            id2label = {int(k): v for k, v in model.config.id2label.items()}
            self._transformer = (pipe, id2label)
            return True
        except Exception as e:  # torch/transformers missing or corrupt model
            logger.warning("RiskEngine: transformer backend unavailable (%s)", e)
            return False

    def _try_load_sklearn(self) -> bool:
        path = os.getenv("HAVEN_RISK_SKLEARN_PATH", "").strip() or str(_DEFAULT_SKLEARN_PATH)
        if not Path(path).is_file():
            return False
        try:
            import joblib
            bundle = joblib.load(path)
            self._sklearn = (bundle["vectorizer"], bundle["model"], bundle["labels"])
            return True
        except Exception as e:
            logger.warning("RiskEngine: sklearn backend unavailable (%s)", e)
            return False

    # ── prediction ───────────────────────────────────────────────────────
    def predict(self, text: str) -> dict:
        """Classify `text`, returning the canonical result shape (+ model metadata)."""
        text = (text or "")[:4000]

        # The rule scorer always runs: it supplies explainable indicators and is
        # the fallback if a learned backend errors at inference time.
        rule_result = rule_classifier.classify(text)

        if self.backend == "transformer":
            try:
                result = self._predict_transformer(text, rule_result)
            except Exception as e:
                logger.warning("RiskEngine: transformer inference failed, falling back to rules (%s)", e)
                result = rule_result
        elif self.backend == "sklearn":
            try:
                result = self._predict_sklearn(text, rule_result)
            except Exception as e:
                logger.warning("RiskEngine: sklearn inference failed, falling back to rules (%s)", e)
                result = rule_result
        else:
            result = rule_result

        return self._stamp_metadata(result)

    def _stamp_metadata(self, result: dict) -> dict:
        """Attach uniform model metadata (Phase 1) to any backend result."""
        backend = result.get("backend", self.backend)
        result["model_name"] = _MODEL_NAMES.get(backend, backend)
        # DEMO unless a production-affirmed transformer produced this result.
        result["model_state"] = "PRODUCTION" if result.get("is_demo_mode") is False else "DEMO"
        result["classified_at"] = datetime.now(timezone.utc).isoformat()
        return result

    def _predict_sklearn(self, text: str, rule_result: dict) -> dict:
        vectorizer, model, labels = self._sklearn
        X = vectorizer.transform([clean_text(text)])
        proba = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)[0]
            idx = int(proba.argmax())
            severity = str(labels[idx]).upper()
            confidence = round(float(proba[idx]), 3)
        else:
            severity = str(model.predict(X)[0]).upper()
            confidence = 0.5
        if severity not in SEVERITY_LEVELS:
            severity = rule_result["severity"]
        return {
            "severity": severity,
            "risk_score": self._score_from_proba(severity, proba),
            # Keep the explainable indicators from the rule scorer.
            "indicators": rule_result["indicators"],
            "confidence": confidence,
            "explanation": (
                f"scikit-learn TF-IDF + LogisticRegression predicted severity {severity} "
                f"(confidence {confidence}). Indicators shown are from the rule lexicon for "
                "explainability. Trained on the synthetic demo dataset — decision support only, "
                "human authority must verify."
            ),
            "model_version": "sklearn-tfidf-logreg-v1",
            "backend": "sklearn",
            "is_demo_mode": True,  # trained on synthetic demo data
        }

    def _predict_transformer(self, text: str, rule_result: dict) -> dict:
        pipe, id2label = self._transformer
        scores = pipe(text)[0]  # list of {label, score}
        best = max(scores, key=lambda s: s["score"])
        severity = str(best["label"]).upper()
        # Handle models whose labels are LABEL_0..LABEL_3.
        if severity.startswith("LABEL_"):
            severity = str(id2label.get(int(severity.split("_")[1]), severity)).upper()
        if severity not in SEVERITY_LEVELS:
            severity = rule_result["severity"]
        confidence = round(float(best["score"]), 3)
        return {
            "severity": severity,
            "risk_score": self._score_from_confidence(severity, confidence),
            "indicators": rule_result["indicators"],
            "confidence": confidence,
            "explanation": (
                f"DistilBERT text-classifier predicted severity {severity} "
                f"(confidence {confidence}). Indicators shown are from the rule lexicon for "
                "explainability. AI output is decision support only — a human authority must "
                "verify before dispatch."
            ),
            "model_version": f"distilbert-{os.path.basename(os.getenv('HAVEN_RISK_MODEL_DIR', 'finetuned'))}",
            "backend": "transformer",
            # Only a production-affirmed model reports non-demo.
            "is_demo_mode": not self._production,
        }

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _score_from_confidence(severity: str, confidence: float) -> int:
        band_floor = {"LOW": 5, "MODERATE": 40, "HIGH": 65, "CRITICAL": 88}[severity]
        band_span = {"LOW": 20, "MODERATE": 20, "HIGH": 20, "CRITICAL": 12}[severity]
        return int(round(band_floor + confidence * band_span))

    def _score_from_proba(self, severity: str, proba) -> int:
        conf = float(max(proba)) if proba is not None else 0.5
        return self._score_from_confidence(severity, conf)

    def info(self) -> dict:
        """Diagnostics for /ai/model-info (no secrets)."""
        is_demo = self.backend != "transformer" or not self._production
        return {
            "active_backend": self.backend,
            "model_name": _MODEL_NAMES.get(self.backend, self.backend),
            "model_state": "DEMO" if is_demo else "PRODUCTION",
            "is_demo_mode": is_demo,
            "severity_levels": SEVERITY_LEVELS,
            "transformer_available": self._transformer is not None,
            "sklearn_available": self._sklearn is not None,
            "production_affirmed": self._production,
            "training_data": "synthetic demo dataset" if is_demo else "operator-affirmed production data",
        }


_ENGINE = None


def get_engine() -> RiskEngine:
    """Return the process-wide RiskEngine, constructing it on first use."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RiskEngine()
    return _ENGINE
