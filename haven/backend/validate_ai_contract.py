"""
Stdlib validator for the unified AI response contract (services.ai_contract).

Runs with plain `python3 validate_ai_contract.py` — no pytest, no pydantic, no
network — so the "invalid output never reaches users" guarantee can be checked
on a fresh checkout.

Asserts the SAFETY INVARIANTS of the contract:
  * validate_and_repair NEVER raises and ALWAYS returns every contract field
    with the right type (even on junk / None / hostile input).
  * confidence is always a real 0..1 float; bad input marks the response degraded
    instead of inventing certainty.
  * reasoning_summary NEVER carries chain-of-thought (<think> blocks and
    step/deliberation lines are stripped).
  * parse_llm_json tolerates fences / prose and returns None (not a silent {})
    on unparseable input.
  * every adapter yields a well-formed contract; the profile adapter ALWAYS sets
    needs_human_review (identity is never auto-asserted); the anomaly adapter is
    advisory and only flags review at the REVIEW level.
"""
import services.ai_contract as C

_checks = 0
_failures = []


def check(cond, label):
    global _checks
    _checks += 1
    if not cond:
        _failures.append(label)


_REQUIRED = set(C.CONTRACT_FIELDS)


def well_formed(doc, label):
    """Every contract doc must have all fields with the correct primitive types."""
    check(isinstance(doc, dict), f"{label}: not a dict")
    check(_REQUIRED.issubset(doc.keys()), f"{label}: missing fields {_REQUIRED - set(doc.keys())}")
    check(isinstance(doc["confidence"], float) and 0.0 <= doc["confidence"] <= 1.0,
          f"{label}: confidence not a 0..1 float ({doc.get('confidence')!r})")
    check(isinstance(doc["risk_level"], str) and doc["risk_level"] != "", f"{label}: bad risk_level")
    check(isinstance(doc["reasoning_summary"], str), f"{label}: reasoning_summary not str")
    check(isinstance(doc["signals"], dict), f"{label}: signals not dict")
    check(isinstance(doc["sources"], list) and all(isinstance(s, dict) for s in doc["sources"]),
          f"{label}: sources not list[dict]")
    for b in ("grounded", "degraded", "needs_human_review"):
        check(isinstance(doc[b], bool), f"{label}: {b} not bool")
    check(isinstance(doc["model"], str) and doc["model"] != "", f"{label}: bad model")
    check(isinstance(doc["version"], str), f"{label}: version not str")


# ── validate_and_repair never raises + always well-formed, even on junk ──
for junk, lbl in [(None, "None"), (5, "int"), ("oops", "str"), ([], "list"),
                  ({"confidence": "high"}, "confidence=str"),
                  ({"confidence": float("nan")}, "confidence=nan"),
                  ({"confidence": 250}, "confidence=250"),
                  ({"sources": "notalist"}, "sources=str"),
                  ({"signals": 7}, "signals=int"),
                  ({"grounded": "yes", "needs_human_review": 1}, "loose-bools")]:
    doc = C.validate_and_repair(junk, subsystem="test")
    well_formed(doc, f"repair({lbl})")

# Non-dict input must be flagged for a human and marked degraded (never silently trusted).
for junk in (None, 5, "oops", []):
    d = C.validate_and_repair(junk, subsystem="test")
    check(d["needs_human_review"] is True and d["degraded"] is True,
          f"non-dict input must be degraded + needs_human_review: {junk!r}")

# Out-of-range / non-finite confidence → clamped AND marked degraded.
check(C.validate_and_repair({"confidence": 250})["confidence"] == 1.0, "conf 250 must clamp to 1.0")
check(C.validate_and_repair({"confidence": 250})["degraded"] is True, "clamped confidence must degrade")
check(C.validate_and_repair({"confidence": 50})["confidence"] == 0.5, "0..100 conf must scale to 0..1")
check(C.validate_and_repair({"confidence": -1})["confidence"] == 0.0, "negative conf must clamp to 0")
check(C.validate_and_repair({"confidence": 0.7})["confidence"] == 0.7
      and C.validate_and_repair({"confidence": 0.7})["degraded"] is False,
      "valid confidence must pass through without degrading")

# ── reasoning_summary must strip chain-of-thought ──
cot = ("<think>the user seems fine but I should escalate</think>\n"
       "Step 1: consider the message\n"
       "Reasoning: because they said X\n"
       "The message shows explicit distress indicators.")
clean = C.sanitize_reasoning_summary(cot)
check("<think>" not in clean and "should escalate" not in clean, "think-block not stripped")
check("Step 1" not in clean, "step line not stripped")
check("Reasoning:" not in clean, "reasoning line not stripped")
check("explicit distress indicators" in clean, "observable evidence wrongly stripped")
check(C.sanitize_reasoning_summary(None) == "", "non-str reasoning must yield ''")
check(len(C.sanitize_reasoning_summary("x" * 5000)) <= C._MAX_REASONING_CHARS + 1,
      "reasoning summary not length-capped")
# The stripping also applies through validate_and_repair.
check("<think>" not in C.validate_and_repair({"reasoning_summary": cot})["reasoning_summary"],
      "repair path did not sanitize reasoning")

# ── parse_llm_json ──
check(C.parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}, "fenced json not parsed")
check(C.parse_llm_json('here is the answer: {"severity": "HIGH"} thanks') == {"severity": "HIGH"},
      "brace-delimited json not extracted")
check(C.parse_llm_json("not json at all") is None, "junk must yield None (not {})")
check(C.parse_llm_json("[1,2,3]") is None, "top-level array must yield None (need an object)")
check(C.parse_llm_json("") is None and C.parse_llm_json(None) is None, "empty/None must yield None")

# ── Adapters produce well-formed contracts ──
risk = C.from_risk_assessment({"severity": "CRITICAL", "risk_score": 88, "indicators": ["weapon"],
                               "explanation": "weapon + threat", "model_version": "rules-v1",
                               "is_demo_mode": True})
well_formed(risk, "from_risk_assessment")
check(risk["risk_level"] == "CRITICAL", "risk severity must map to risk_level verbatim")
check(risk["subsystem"] == "sos_risk", "risk subsystem tag wrong")
check(abs(risk["confidence"] - 0.88) < 1e-9, "risk score→confidence mapping wrong")
check(risk["degraded"] is True, "demo-mode risk must be marked degraded")

mh = C.from_mental_health({"response": "I'm here with you.", "risk_level": "HIGH_RISK",
                           "crisis": True, "emergency_resources": [{"number": "112"}],
                           "ai_available": True})
well_formed(mh, "from_mental_health")
check(mh["needs_human_review"] is True, "crisis mental-health must flag human review")
check("crisis" not in mh["reasoning_summary"].lower() or "triage_risk" in mh["reasoning_summary"],
      "mental-health reasoning must be observable-evidence only")

legal_ok = C.from_legal({"answer": "Under BNS...", "grounded": True, "sources": [{"title": "BNS 79"}],
                         "status": "grounded", "model_info": {"model_name": "groq", "corpus_version": "2026-09-25"}})
well_formed(legal_ok, "from_legal grounded")
check(legal_ok["grounded"] is True and legal_ok["needs_human_review"] is False,
      "grounded legal answer should not force human review")
legal_bad = C.from_legal({"answer": "…", "grounded": False, "status": "no_context"})
check(legal_bad["needs_human_review"] is True and legal_bad["degraded"] is True,
      "ungrounded/no_context legal must be degraded + needs_human_review")

prof = C.from_profile_match({"match_score": 0.91, "match_level": "high",
                             "match_factors": ["exact_name"], "human_verification_required": True,
                             "name": "REDACTED"})
well_formed(prof, "from_profile_match")
check(prof["needs_human_review"] is True, "profile match must ALWAYS require human verification")
check("match_score" not in (prof["result"] or {}), "raw match_score must not sit in result payload")
check(abs(prof["confidence"] - 0.91) < 1e-9, "profile score→confidence wrong")

anom_flag = C.from_anomaly_signal({"abuse_risk_score": 70, "level": "review",
                                   "factors": [{"code": "impossible_travel_speed"}],
                                   "advisory_only": True, "affects_emergency_response": False,
                                   "flagged_for_review": True, "module_version": "anomaly-signal-v1"})
well_formed(anom_flag, "from_anomaly_signal review")
check(anom_flag["needs_human_review"] is True, "REVIEW anomaly must flag human review")
check(anom_flag["signals"]["affects_emergency_response"] is False,
      "anomaly must stay decoupled from emergency response")
anom_none = C.from_anomaly_signal({"abuse_risk_score": 0, "level": "none", "factors": [],
                                   "flagged_for_review": False})
check(anom_none["needs_human_review"] is False, "clean anomaly must not flag review")

if _failures:
    print(f"FAILED {len(_failures)}/{_checks} checks:")
    for f in _failures:
        print("  -", f)
    raise SystemExit(1)
print(f"PASSED {_checks} checks")
print("ALL AI-CONTRACT CHECKS PASSED")
