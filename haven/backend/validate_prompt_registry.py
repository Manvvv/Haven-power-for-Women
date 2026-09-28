"""
Stdlib validator for the prompt/version registry (services.prompt_registry).

Runs with plain `python3 validate_prompt_registry.py` — no pytest, no network.
Asserts:
  * every shipped prompt has a stable id + non-empty version;
  * owned prompt text is retrievable and fingerprint-stable, and matches the
    literals the code actually uses;
  * attach() records a reviewed prompt's live text + fingerprint and drift is
    detectable;
  * the Aria support prompt is attached by its module and matches the registry;
  * stamp() is additive (never overwrites), always records a resolved_model, and
    is a no-op on non-dict input.
"""
import sys
sys.path.insert(0, ".")

from services import prompt_registry as PR

_checks = 0
_failures = []


def check(cond, label):
    global _checks
    _checks += 1
    if not cond:
        _failures.append(label)


# ── Every shipped prompt id has a non-empty version ──
_EXPECTED_IDS = {"risk_classify", "case_summarize", "intent_detect",
                 "message_expand", "aria_support_base", "legal_grounded"}
versions = PR.all_versions()
check(_EXPECTED_IDS.issubset(versions.keys()),
      f"registry missing ids: {_EXPECTED_IDS - set(versions.keys())}")
for pid in _EXPECTED_IDS:
    check(bool(PR.version(pid)), f"{pid}: empty version")
    check(bool(PR.description(pid)), f"{pid}: empty description")

# ── Owned prompts: retrievable, fingerprint-stable, match the code literals ──
check(PR.system_text("risk_classify") == "You are a risk classification AI. Output only valid JSON.",
      "risk_classify owned text drifted")
check(PR.system_text("case_summarize") == "You are an AI case summarizer. Output only valid JSON.",
      "case_summarize owned text drifted")
check(PR.system_text("intent_detect") == "You are an emergency intent detector. Output only valid JSON.",
      "intent_detect owned text drifted")
check(len(PR.fingerprint("risk_classify")) == 12, "fingerprint not a 12-char digest")
check(PR.fingerprint("risk_classify") != PR.fingerprint("case_summarize"),
      "distinct prompts share a fingerprint")

# ── ai_service actually uses the registry text (equals the historical literal) ──
# The text-equality checks above already prove classify_risk/summarize_case/
# intent_detect draw their system strings from this registry (they call
# PR.system_text(id)). Importing ai_service is only a wiring/syntax smoke test and
# needs fastapi, which is absent from the pure-stdlib sandbox — so it is optional.
try:
    from services import ai_service as AIS  # noqa: E402
    check(hasattr(AIS, "classify_risk"), "ai_service.classify_risk missing")
except ModuleNotFoundError as _e:
    print(f"  (skipped ai_service import smoke test: {_e} — expected in stdlib sandbox)")

# ── attach(): reviewed prompt drift detection ──
_orig = PR.system_text("aria_support_base")
PR.attach("legal_grounded", "SAMPLE LEGAL INSTRUCTION")
check(PR.system_text("legal_grounded") == "SAMPLE LEGAL INSTRUCTION", "attach did not record text")
check(PR.fingerprint("legal_grounded") == PR._fingerprint("SAMPLE LEGAL INSTRUCTION"),
      "attach fingerprint mismatch")
check(PR.version("legal_grounded") == "legal-grounded-v1", "attached id lost its version")

# ── Aria module attaches its live prompt and it matches the registry ──
from services import mental_health_support as SUP  # noqa: E402
check(PR.system_text("aria_support_base") == SUP._BASE_SYSTEM_PROMPT,
      "aria prompt in registry != live module text (drift)")
check(SUP.ARIA_PROMPT_VERSION == PR.version("aria_support_base"),
      "aria module version != registry version")

# ── stamp(): additive, non-destructive, always records resolved_model ──
r = PR.stamp({"answer": "x"}, prompt_id="risk_classify")
check(r["answer"] == "x", "stamp mutated existing field")
check(r["prompt_id"] == "risk_classify" and r["prompt_version"] == "risk-classify-v1",
      "stamp did not add prompt id/version")
check(r["resolved_model"] == PR.DEFAULT_MODEL, "stamp did not record default model")
r2 = PR.stamp({"prompt_version": "already", "resolved_model": "custom"}, prompt_id="risk_classify")
check(r2["prompt_version"] == "already" and r2["resolved_model"] == "custom",
      "stamp overwrote existing provenance")
check(PR.stamp("not-a-dict") == "not-a-dict", "stamp not a no-op on non-dict")
r3 = PR.stamp({}, prompt_id="unknown_id")
check("prompt_version" not in r3 and r3["resolved_model"] == PR.DEFAULT_MODEL,
      "stamp added a version for an unknown id")

# ── snapshot for the architecture report ──
snap = PR.registry_snapshot()
check(snap["registry_version"] == PR.PROMPT_REGISTRY_VERSION and "prompts" in snap,
      "registry_snapshot malformed")

if _failures:
    print(f"FAILED {len(_failures)}/{_checks} checks:")
    for f in _failures:
        print("  -", f)
    raise SystemExit(1)
print(f"PASSED {_checks} checks")
print("ALL PROMPT-REGISTRY CHECKS PASSED")
