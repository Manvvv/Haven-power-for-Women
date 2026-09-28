"""
Unified AI response contract + validate/repair layer (audit gap #9).

WHY THIS EXISTS (spec: "unified schema-validated contract; invalid output never
reaches users; NO chain-of-thought exposure; reasoning_summary = observable
evidence only; raw LLM must NOT control role/authority/SOS lifecycle/dispatch/
DB-authz/suspension/legal-status/identity"):
    Every AI subsystem (SOS risk, Aria mental-health, legal RAG, profile match,
    anomaly signal) historically returned an ad-hoc dict, and LLM JSON was parsed
    with a bare `except: {}`. This module gives them ONE typed shape and ONE
    repair path so that:
      * a malformed / partial / hostile model output can never crash a caller and
        never reaches a user unvalidated (validate_and_repair NEVER raises — on
        junk it returns a safe, degraded, human-review response);
      * no hidden chain-of-thought leaks (reasoning_summary is sanitised of
        deliberation markers and <think> blocks — it carries observable evidence,
        never the model's internal reasoning);
      * confidence is always a real 0..1 number, sources/signals are always the
        right container type, and the booleans (grounded / degraded /
        needs_human_review) always exist.

DESIGN — this core is PURE STANDARD LIBRARY (no pydantic, no FastAPI) so the
safety guarantee can be unit-tested on a fresh checkout and does NOT couple the
"invalid output never reaches users" promise to any pydantic version. The typed
wire model `AIResponse` lives in models/schemas.py for optional FastAPI
`response_model` use; this module is the engine behind it.

HARD BOUNDARY: the contract is a PRESENTATION / VALIDATION shape. `result` is a
data payload only. Nothing here is authorised to set a user/authority role, move
an SOS through its lifecycle, trigger dispatch, grant DB access, suspend an
account, decide legal status, or assert an identity — those remain owned by the
deterministic backend, exactly as the spec requires.
"""
from __future__ import annotations

import json
import math
import re

CONTRACT_VERSION = "ai-contract-v1"

# The canonical field set (spec §: result, confidence, risk_level,
# reasoning_summary, signals, sources, grounded, model, version, degraded,
# needs_human_review). `subsystem` is additive observability metadata (which
# engine produced this) — it exposes no reasoning and breaks no client.
CONTRACT_FIELDS = (
    "result", "confidence", "risk_level", "reasoning_summary", "signals",
    "sources", "grounded", "model", "version", "degraded",
    "needs_human_review", "subsystem",
)

_MAX_REASONING_CHARS = 1500
_MAX_SOURCES = 25

# Chain-of-thought / deliberation markers that must NEVER surface to a user.
# We strip <think>…</think> style blocks and any line that reads like internal
# step-by-step reasoning, then fall back to a neutral note if nothing safe is left.
_THINK_BLOCK_RE = re.compile(
    r"<\s*(think|thinking|thought|scratchpad|reasoning|analysis)\s*>.*?"
    r"<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_COT_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:step\s*\d+\s*[:.\)]?)|"                 # "Step 1:", "step 2)"
    r"(?:\d+\s*[:.\)]\s*(?:first|then|next|so|because))|"
    r"(?:let'?s think|let me think|let me reason|let us reason)|"
    r"(?:chain[\s-]*of[\s-]*thought)|"
    r"(?:reasoning\s*[:\-])|(?:thought\s*[:\-])|(?:thinking\s*[:\-])|"
    r"(?:internal(?:\s+monologue)?\s*[:\-])|(?:scratchpad\s*[:\-])|"
    r"(?:my\s+(?:reasoning|thought\s+process|internal)\b)"
    r")",
    re.IGNORECASE,
)


def sanitize_reasoning_summary(text) -> str:
    """Return an observable-evidence summary with any chain-of-thought removed.

    Removes <think>-style blocks and deletes lines that read like step-by-step
    internal deliberation, collapses whitespace, and caps length. Non-string /
    empty input yields "" (the caller then supplies a neutral default). This is
    the guardrail behind "NO chain-of-thought exposure" — even if a model stuffs
    its reasoning into this field, it does not reach the user.
    """
    if not isinstance(text, str):
        return ""
    cleaned = _THINK_BLOCK_RE.sub(" ", text)
    kept = [ln for ln in cleaned.splitlines() if not _COT_LINE_RE.match(ln)]
    out = " ".join(" ".join(kept).split())
    if len(out) > _MAX_REASONING_CHARS:
        out = out[:_MAX_REASONING_CHARS].rstrip() + "…"
    return out


# ── Coercion helpers (all total — never raise) ───────────────────────────────
def _clamp_confidence(value) -> "tuple[float, bool]":
    """Coerce to a 0..1 float. Returns (confidence, repaired?) — repaired=True
    when the input was missing/invalid/out-of-range so the caller can mark the
    response degraded rather than silently inventing certainty."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0, True
    if not math.isfinite(f):
        return 0.0, True
    if f < 0.0:
        return 0.0, True
    if f > 1.0:
        # Accept a 0..100 style score defensively, else clamp.
        return (min(f / 100.0, 1.0), True) if f <= 100.0 else (1.0, True)
    return f, False


def _as_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "on")
    return default


def _as_str(value, default="") -> str:
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_sources(value) -> list:
    """Coerce to a list of dicts, capped, dropping non-dict entries."""
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str) and item.strip():
            out.append({"title": item})
        if len(out) >= _MAX_SOURCES:
            break
    return out


def parse_llm_json(text) -> "dict | None":
    """Safely extract a JSON object from raw LLM output.

    Strips ```json fences, tolerates leading/trailing prose by grabbing the
    outermost {...}, and returns a dict or None (never raises). Replaces the
    unsafe `try: json.loads(...) except: {}` sprinkled across ai_service — a
    None result lets the caller apply an explicit, honest fallback instead of a
    silent empty dict.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    stripped = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        val = json.loads(stripped)
        return val if isinstance(val, dict) else None
    except (ValueError, TypeError):
        pass
    # Fall back to the outermost brace-delimited object.
    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        try:
            val = json.loads(stripped[start:end + 1])
            return val if isinstance(val, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def build(result=None, *, confidence=0.0, risk_level="unknown",
          reasoning_summary="", signals=None, sources=None, grounded=False,
          model="deterministic", version="", degraded=False,
          needs_human_review=False, subsystem="unknown") -> dict:
    """Assemble a contract dict from already-trusted values, then validate/repair
    it so the output is guaranteed well-formed regardless of caller sloppiness."""
    conf, conf_repaired = _clamp_confidence(confidence)
    doc = {
        "result": result,
        "confidence": conf,
        "risk_level": _as_str(risk_level, "unknown") or "unknown",
        "reasoning_summary": sanitize_reasoning_summary(reasoning_summary),
        "signals": _as_dict(signals),
        "sources": _as_sources(sources),
        "grounded": _as_bool(grounded),
        "model": _as_str(model, "deterministic") or "deterministic",
        "version": _as_str(version),
        "degraded": _as_bool(degraded) or conf_repaired,
        "needs_human_review": _as_bool(needs_human_review),
        "subsystem": _as_str(subsystem, "unknown") or "unknown",
    }
    return doc


def validate_and_repair(raw, *, subsystem="unknown", model=None, version=None,
                        default_risk_level="unknown",
                        default_grounded=False) -> dict:
    """Coerce any object into a complete, typed contract dict. NEVER raises.

    * A non-dict / None input yields a safe, degraded response with
      needs_human_review=True (invalid output must never reach a user as-is).
    * Missing fields get honest defaults; confidence is clamped to 0..1;
      reasoning_summary is stripped of chain-of-thought; sources/signals are
      forced to the right container type.
    """
    if not isinstance(raw, dict):
        return build(
            result=None,
            confidence=0.0,
            risk_level=default_risk_level,
            reasoning_summary="",
            signals={},
            sources=[],
            grounded=default_grounded,
            model=model or "unknown",
            version=version or CONTRACT_VERSION,
            degraded=True,
            needs_human_review=True,
            subsystem=subsystem,
        )
    return build(
        result=raw.get("result"),
        confidence=raw.get("confidence", 0.0),
        risk_level=raw.get("risk_level", default_risk_level),
        reasoning_summary=raw.get("reasoning_summary", ""),
        signals=raw.get("signals"),
        sources=raw.get("sources"),
        grounded=raw.get("grounded", default_grounded),
        model=model if model is not None else raw.get("model", "deterministic"),
        version=version if version is not None else raw.get("version", ""),
        degraded=raw.get("degraded", False),
        needs_human_review=raw.get("needs_human_review", False),
        subsystem=subsystem if subsystem != "unknown" else raw.get("subsystem", "unknown"),
    )


# ── Adapters — map each subsystem's existing ad-hoc dict onto the contract ────
# These are ADDITIVE: they never mutate the source dict and never change an
# endpoint's current response shape. A route can return the contract in a NEW
# optional field (or via response_model) without breaking existing clients.

def from_risk_assessment(d) -> dict:
    """SOS risk (services.risk_classifier / ml.risk_engine) → contract.

    severity is the deterministic floor and stays the risk_level verbatim; the
    LLM (if any) only ever wrote the free-text explanation, never the label."""
    d = _as_dict(d)
    score = d.get("risk_score", 0)
    conf = d.get("confidence")
    if conf is None:  # derive a 0..1 confidence from the 0..100 score honestly
        try:
            conf = float(score) / 100.0
        except (TypeError, ValueError):
            conf = 0.0
    model = d.get("model_name") or d.get("backend") or "deterministic-rules"
    return build(
        result={"severity": d.get("severity", "UNKNOWN"), "risk_score": score},
        confidence=conf,
        risk_level=_as_str(d.get("severity", "UNKNOWN"), "UNKNOWN"),
        reasoning_summary=d.get("explanation", ""),
        signals={"indicators": d.get("indicators", []),
                 "is_demo_mode": d.get("is_demo_mode"),
                 "model_state": d.get("model_state")},
        grounded=False,
        model=model,
        version=_as_str(d.get("model_version")),
        degraded=_as_bool(d.get("is_demo_mode")),
        needs_human_review=_as_bool(d.get("needs_human_review")),
        subsystem="sos_risk",
    )


def from_mental_health(d) -> dict:
    """Aria mental-health response → contract. Exposes NO classifier reasoning:
    reasoning_summary is built from observable signals only; a human/emergency
    review is flagged whenever the deterministic triage says crisis."""
    d = _as_dict(d)
    crisis = _as_bool(d.get("crisis"))
    risk_level = _as_str(d.get("risk_level", "unknown"), "unknown")
    ai_available = d.get("ai_available", True)
    evidence = f"triage_risk={risk_level}; crisis={crisis}"
    if d.get("emergency_resources"):
        evidence += "; emergency_resources_attached"
    return build(
        result=d.get("response"),
        confidence=0.0,                       # triage is categorical, not probabilistic
        risk_level=risk_level,
        reasoning_summary=evidence,
        signals={"crisis": crisis, "mode": d.get("mode", "normal"),
                 "needs_clarification": _as_bool(d.get("needs_clarification"))},
        sources=d.get("sources"),
        grounded=bool(d.get("sources")),
        model="deterministic-triage" + ("" if ai_available else "+ai_unavailable"),
        version=_as_str(d.get("version")),
        degraded=not _as_bool(ai_available, True),
        needs_human_review=crisis,            # crisis always warrants human/emergency review
        subsystem="mental_health",
    )


def from_legal(d) -> dict:
    """Legal RAG answer → contract. grounded / sources are carried verbatim; an
    ungrounded or llm-unavailable answer is marked degraded, never fabricated."""
    d = _as_dict(d)
    status = _as_str(d.get("status"))
    grounded = _as_bool(d.get("grounded"))
    degraded = _as_bool(d.get("degraded")) or status in ("llm_unavailable", "no_context", "empty_query")
    minfo = _as_dict(d.get("model_info"))
    return build(
        result=d.get("answer"),
        confidence=0.0,
        risk_level="n/a",
        reasoning_summary="",                 # legal answer is the grounded prose itself
        signals={"status": status, "no_context": _as_bool(d.get("no_context")),
                 "retrieval_mode": d.get("retrieval_mode")},
        sources=d.get("sources"),
        grounded=grounded,
        model=_as_str(minfo.get("model_name") or minfo.get("embedding_model") or "legal-rag"),
        version=_as_str(minfo.get("corpus_version") or minfo.get("prompt_version")),
        degraded=degraded,
        needs_human_review=not grounded,      # ungrounded → don't rely on it; a human should
        subsystem="legal_rag",
    )


def from_profile_match(d) -> dict:
    """Culprit/profile match → contract. An embedding match is an investigative
    LEAD, never proof of identity: human_verification_required is preserved and
    needs_human_review is ALWAYS True."""
    d = _as_dict(d)
    score = d.get("match_score", 0.0)
    try:
        conf = float(score)
    except (TypeError, ValueError):
        conf = 0.0
    return build(
        result={k: v for k, v in d.items() if k != "match_score"},
        confidence=conf,
        risk_level=_as_str(d.get("match_level", "unknown"), "unknown"),
        reasoning_summary="",                 # match is a lead; no identity claim, no reasoning
        signals={"match_factors": d.get("match_factors", []),
                 "human_verification_required": d.get("human_verification_required", True)},
        grounded=False,
        model="profile-search",
        version=_as_str(d.get("module_version")),
        degraded=False,
        needs_human_review=True,              # identity is NEVER auto-asserted
        subsystem="profile_match",
    )


def from_anomaly_signal(d) -> dict:
    """Advisory abuse/anomaly signal (services.anomaly_signal) → contract. This
    is decoupled from emergency_risk and never auto-acts; the strongest thing it
    can say is needs_human_review."""
    d = _as_dict(d)
    try:
        conf = float(d.get("abuse_risk_score", 0)) / 100.0
    except (TypeError, ValueError):
        conf = 0.0
    return build(
        result=None,
        confidence=conf,
        risk_level=_as_str(d.get("level", "none"), "none"),
        reasoning_summary="",
        signals={"factors": d.get("factors", []),
                 "advisory_only": d.get("advisory_only", True),
                 "affects_emergency_response": d.get("affects_emergency_response", False)},
        grounded=False,
        model=_as_str(d.get("module_version", "anomaly-signal")),
        version=_as_str(d.get("module_version")),
        degraded=False,
        needs_human_review=_as_bool(d.get("flagged_for_review")),
        subsystem="anomaly_signal",
    )



