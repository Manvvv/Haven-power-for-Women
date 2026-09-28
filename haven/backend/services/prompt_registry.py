"""
prompt_registry.py — one source of truth for LLM prompt IDs, versions and text.

WHY (audit gap #10): every subsystem's system prompt was an inline literal with
no version tracked or returned, so a change to a safety-relevant prompt left no
trace on the response and no way to detect drift. This registry gives each prompt
a stable id + version + content fingerprint and a `stamp()` helper that adds
`prompt_id` / `prompt_version` / `resolved_model` to any response dict — additive,
non-breaking.

DESIGN — pure standard library and it imports NOTHING from `services` (so there
is no import cycle). Small, safe prompts (the JSON-only instruction strings) are
OWNED here as canonical text. Larger safety-reviewed prompts (Aria support, legal
grounded) stay defined in their own reviewed module; that module calls
`attach(id, live_text)` at import so the registry records the live fingerprint
and can VERIFY it matches the shipped version (drift detection) without holding a
second, divergeable copy.

This registry never selects a model, never routes, and never gates anything — it
is metadata + text lookup only.
"""
from __future__ import annotations

import hashlib

PROMPT_REGISTRY_VERSION = "prompt-registry-v1"

# Default generation model (mirrors services.ai_service.call_groq's default). The
# ACTUAL model that answered can differ after fallback; `stamp` records the model
# it is given and never claims more than that.
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


# ── Central version list — the single source of truth for shipped prompts ──
# `owned_text` is the canonical text for prompts this registry owns outright.
# Reviewed prompts defined elsewhere carry owned_text=None and get their live
# text via attach().
_META = {
    "risk_classify": {
        "version": "risk-classify-v1",
        "description": "SOS free-text risk classification; JSON-only output.",
        "owned_text": "You are a risk classification AI. Output only valid JSON.",
    },
    "case_summarize": {
        "version": "case-summarize-v1",
        "description": "Authority case summariser; JSON-only output.",
        "owned_text": "You are an AI case summarizer. Output only valid JSON.",
    },
    "intent_detect": {
        "version": "intent-detect-v1",
        "description": "Voice-SOS emergency intent detection; JSON-only output.",
        "owned_text": "You are an emergency intent detector. Output only valid JSON.",
    },
    "message_expand": {
        "version": "message-expand-v1",
        "description": "Expand brief distress keywords into a complete message.",
        "owned_text": (
            "You are an AI assistant for Haven, a women's safety platform. "
            "Expand brief keywords from a woman in distress into a clear, complete "
            "distress message. Output ONLY the expanded message, nothing else."
        ),
    },
    # Reviewed prompts owned by their own module (attached at import):
    "aria_support_base": {
        "version": "aria-support-v1",
        "description": "Aria non-crisis emotional-support system prompt (safety-reviewed).",
        "owned_text": None,
    },
    "legal_grounded": {
        "version": "legal-grounded-v1",
        "description": "Legal RAG grounded-answer system prompt (context-constrained).",
        "owned_text": None,
    },
}

# Live text + fingerprint attached by owning modules at import time.
_LIVE: "dict[str, dict]" = {}
for _pid, _m in _META.items():
    if _m["owned_text"] is not None:
        _LIVE[_pid] = {"text": _m["owned_text"], "fingerprint": _fingerprint(_m["owned_text"])}


def attach(prompt_id: str, live_text: str) -> None:
    """Register the live text of a reviewed prompt defined in another module.

    Records the fingerprint so drift can be detected. Unknown ids are accepted
    defensively (recorded with no version) rather than raising at import time —
    a missing registration must never break a running endpoint.
    """
    _LIVE[prompt_id] = {"text": live_text or "", "fingerprint": _fingerprint(live_text or "")}


def known(prompt_id: str) -> bool:
    return prompt_id in _META


def version(prompt_id: str) -> str:
    meta = _META.get(prompt_id)
    return meta["version"] if meta else ""


def description(prompt_id: str) -> str:
    meta = _META.get(prompt_id)
    return meta["description"] if meta else ""


def system_text(prompt_id: str) -> str:
    """Return the live/owned prompt text, or '' if none is available."""
    live = _LIVE.get(prompt_id)
    return live["text"] if live else ""


def fingerprint(prompt_id: str) -> str:
    live = _LIVE.get(prompt_id)
    return live["fingerprint"] if live else ""


def all_versions() -> "dict[str, str]":
    return {pid: meta["version"] for pid, meta in _META.items()}


def registry_snapshot() -> dict:
    """Full metadata view for observability / the AI architecture report."""
    return {
        "registry_version": PROMPT_REGISTRY_VERSION,
        "default_model": DEFAULT_MODEL,
        "prompts": {
            pid: {"version": meta["version"], "description": meta["description"],
                  "fingerprint": fingerprint(pid), "attached": pid in _LIVE}
            for pid, meta in _META.items()
        },
    }


def stamp(resp: dict, prompt_id: str = None, model: str = None) -> dict:
    """Additively stamp prompt/version/model provenance onto a response dict.

    Never overwrites an existing value and never raises; a non-dict resp is
    returned untouched. `resolved_model` is exactly the model handed in (or the
    configured default) — it does not assert which provider actually answered.
    """
    if not isinstance(resp, dict):
        return resp
    if prompt_id and known(prompt_id):
        resp.setdefault("prompt_id", prompt_id)
        resp.setdefault("prompt_version", version(prompt_id))
    resp.setdefault("resolved_model", model or DEFAULT_MODEL)
    return resp
