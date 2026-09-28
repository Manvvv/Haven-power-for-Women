"""
validate_mental_health.py — dependency-free validation of HAVEN's mental-health
SAFETY layer (triage + verified resources + deterministic support text).

Runs with the standard library only (no fastapi / pytest / pymongo), so it works
in constrained environments and CI. It exercises the spec §30 test matrix across
English, Hindi and Hinglish and asserts the safety-critical invariants:
  * correct risk tier + response mode
  * emergency resources present exactly when required (never fabricated)
  * medication/dosing answers contain NO doses/numbers and escalate
  * crisis / AI-outage text carries the verified numbers (112, 14416) and NEVER
    diagnoses or promises false safety
  * reassurance and third-person grief correctly downgrade risk

Exit code 0 = all pass. Run:  python3 validate_mental_health.py   (cwd = backend)
"""
import sys
import re

sys.path.insert(0, ".")
from services import mental_health_triage as TR       # noqa: E402
from services import mental_health_support as SUP      # noqa: E402
from services import mental_health_resources as R      # noqa: E402

_FAILS = []
_PASSES = 0


def check(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
    else:
        _FAILS.append(label)


# Words that would indicate a diagnosis or false-safety promise (must NEVER appear
# in any deterministic, non-LLM safety text we ship).
_DIAGNOSIS_RE = re.compile(
    r"you have (depression|anxiety|ptsd|bipolar)|you are (depressed|bipolar)|"
    r"you'?re (depressed|bipolar)|diagnos", re.I)
_FALSE_SAFETY_RE = re.compile(r"you are (completely |totally )?safe|you'?re safe now", re.I)


def tier(msg, hint, expected_level, expected_mode, want_emergency):
    t = TR.build_triage(msg, hint)
    check(t.risk_level == expected_level,
          f"[{hint}] {msg!r} → {t.risk_level} (expected {expected_level})")
    check(t.response_mode == expected_mode,
          f"[{hint}] {msg!r} mode={t.response_mode} (expected {expected_mode})")
    er = SUP.emergency_resources_for(t)
    if want_emergency:
        check(len(er) > 0, f"[{hint}] {msg!r} expected emergency resources, got none")
        nums = [r["number"] for r in er]
        check("112" in nums or "14416" in nums,
              f"[{hint}] {msg!r} emergency set missing 112/14416: {nums}")
    else:
        check(len(er) == 0, f"[{hint}] {msg!r} expected NO emergency resources, got {len(er)}")
    return t


def _mk(lang, level):
    """Build a minimal triage with a fixed language + level for text-picker tests."""
    return TR.MHTriage(raw_message="test", risk_level=level, language=lang)


# ── §30 TEST MATRIX ─────────────────────────────────────────────────────────
# NORMAL (LOW_DISTRESS, normal mode, no emergency resources)
for m in ["I'm stressed about exams", "I'm lonely", "I can't sleep", "I feel overwhelmed"]:
    tier(m, "en", TR.LOW, TR.MODE_NORMAL, want_emergency=False)

# MODERATE
for m in ["I've been feeling really low", "I can't stop worrying", "I don't know how to cope"]:
    tier(m, "en", TR.MODERATE, TR.MODE_MODERATE, want_emergency=False)

# HIGH (explicit ideation, not in progress → crisis mode, emergency resources)
for m in ["I don't want to be here anymore", "I wish I wouldn't wake up", "I want to kill myself"]:
    tier(m, "en", TR.HIGH, TR.MODE_CRISIS, want_emergency=True)

# IMMINENT (act in progress / means+intent / active attack → emergency mode)
for m in ["I already took pills", "I am going to hurt myself right now",
          "I have a weapon and I'm thinking about using it", "someone is attacking me right now"]:
    tier(m, "en", TR.IMMINENT, TR.MODE_EMERGENCY, want_emergency=True)

# ABUSE (at least moderate, worth a check-in; abuse signal set)
for m in ["My partner is hitting me", "My husband threatens me", "I'm scared to go home"]:
    t = TR.build_triage(m, "en")
    check(t.signals.get("abuse"), f"abuse signal missing for {m!r}")
    check(TR._RANK[t.risk_level] >= TR._RANK[TR.MODERATE] or t.crisis,
          f"abuse {m!r} under-triaged: {t.risk_level}")

# CHILD (a child in severe distress → escalated to at least HIGH)
tchild = TR.build_triage("My child says they want to die", "en")
check(tchild.signals.get("child_safety"), "child_safety signal missing")
check(TR._RANK[tchild.risk_level] >= TR._RANK[TR.HIGH],
      f"child distress under-triaged: {tchild.risk_level}")

# HINDI
tier("मैं मरना चाहता हूँ", "hi", TR.HIGH, TR.MODE_CRISIS, want_emergency=True)
tier("मुझे बहुत डर लग रहा है", "hi", TR.MODERATE, TR.MODE_MODERATE, want_emergency=False)
tier("मैंने गोलियां खा ली हैं", "hi", TR.IMMINENT, TR.MODE_EMERGENCY, want_emergency=True)

# HINGLISH
tier("mujhe bahut stress hai", "hinglish", TR.LOW, TR.MODE_NORMAL, want_emergency=False)
tinten = TR.build_triage("mujhe lag raha hai main khud ko hurt kar lunga", "hinglish")
check(tinten.crisis, f"hinglish self-harm intent not flagged crisis: {tinten.risk_level}")
tier("maine pills le li hain", "hinglish", TR.IMMINENT, TR.MODE_EMERGENCY, want_emergency=True)

# ── Hinglish overdose code-switch (regression: English noun + Hindi verb) ──────
# These previously scored UNKNOWN/crisis=False — a code-switch a real user in
# crisis is very likely to type. Each must be an act-in-progress → IMMINENT with
# emergency resources. Guards the mental_health_triage lexicon fix permanently.
for m in ["kal raat maine bahut pills kha li", "pills kha li maine", "maine dawa kha li",
          "neend ki goliyan kha li", "sleeping pills kha li", "goli kha liya",
          "zeher pi liya", "poison kha li"]:
    tier(m, "hinglish", TR.IMMINENT, TR.MODE_EMERGENCY, want_emergency=True)

# "ending it all / ending my life" ideation must register as crisis (HIGH or above).
for m in ["ending it all tonight", "i am ending my life", "i want to end my life"]:
    check(TR.build_triage(m, "en").crisis, f"'ending' ideation not flagged crisis: {m!r}")

# ── Reassurance / grief downgrades ────────────────────────────────────────────
check(TR.build_triage("I used to want to die but I'm not suicidal now", "en").risk_level != TR.HIGH,
      "reassurance failed to downgrade")
check(not TR.build_triage("my brother died by suicide last year", "en").crisis,
      "third-person grief wrongly escalated to crisis")

# ── Medication / dosing safety (spec §18): NO doses/numbers, must escalate ─────
for m, hint in [("how much sleeping pills can I take", "en"),
                ("kitni goliyan leni chahiye", "hinglish")]:
    t = TR.build_triage(m, hint)
    check(t.dosing_request, f"dosing_request not set for {m!r}")
med_en = SUP.medication_safety_text("en")
check(not re.search(r"\d+\s*(mg|ml|tablet|pill|gram|g\b)", med_en, re.I),
      "medication text appears to contain a dose")
check("112" in med_en, "medication text missing emergency escalation (112)")
check(_DIAGNOSIS_RE.search(med_en) is None, "medication text contains a diagnosis")

# ── Deterministic crisis / AI-outage text: verified numbers, no diagnosis/false-safety
for lang in ("en", "hi", "hinglish"):
    high_t = _mk(lang, TR.HIGH)
    imm_t = _mk(lang, TR.IMMINENT)
    for txt in (SUP.crisis_response_text(high_t), SUP.crisis_response_text(imm_t),
                SUP.ai_unavailable_text(lang), SUP.medication_safety_text(lang)):
        check("14416" in txt, f"[{lang}] safety text missing Tele-MANAS 14416")
        check(not _DIAGNOSIS_RE.search(txt), f"[{lang}] safety text contains diagnosis")
        check(not _FALSE_SAFETY_RE.search(txt), f"[{lang}] safety text promises false safety")
    check("112" in SUP.crisis_response_text(imm_t), f"[{lang}] imminent text missing 112")

# ── System prompt (LLM path) must prohibit diagnosis & dependency ─────────────
sp = SUP.build_system_prompt(TR.build_triage("I feel low", "en"), "en")
for must in ["Diagnose", "medicine", "dependency", "professional"]:
    check(must.lower() in sp.lower(), f"system prompt missing guard: {must!r}")

# ── Verified resource registry: provenance present, numbers correct ───────────
for res in R.all_resources():
    check(bool(res.get("source_url")) and bool(res.get("verified_at")),
          f"resource {res.get('id')} missing provenance")
nums = {r["id"]: r["number"] for r in R.all_resources()}
check(nums.get("emergency_112") == "112", "112 number drifted")
check(nums.get("telemanas_14416") == "14416", "Tele-MANAS number drifted")
check(R.get_resource("telemanas_14416")["alt_number"] == "1800-891-4416",
      "Tele-MANAS alt number not the verified 1800-891-4416")

# ── Coping tools: crisis → grounding+breathing; every tool is a support_strategy
ct = SUP.coping_tools_for(TR.build_triage("I want to kill myself", "en"))
check([x["id"] for x in ct][:2] == ["grounding_54321", "breathing"],
      f"crisis coping tools wrong: {[x['id'] for x in ct]}")
check(all(x["type"] == "support_strategy" for x in SUP.all_tools()),
      "a coping tool is not labelled support_strategy")

# ── Offline pack self-contained (spec §24) ────────────────────────────────────
op = R.offline_pack()
check(all(k in op for k in ("emergency", "crisis", "grounding", "breathing",
                            "emergency_instructions", "disclaimer", "version")),
      "offline pack missing keys")

# ══ FINAL HARDENING checks (hybrid triage / freshness / privacy / offline SOS) ══

# 1) HYBRID SEMANTIC TRIAGE — novel phrasing escalates; layer can only RAISE risk;
#    deterministic floor still stands if the semantic layer fails.
for m, hint in [("honestly i dont wanna be alive anymore", "en"),
                ("i just hope i never wake up tomorrow", "en"),
                ("mujhe lagta hai main khud ko nuqsaan pahuncha dunga", "hinglish")]:
    check(TR.build_triage(m, hint).crisis, f"semantic recall miss (not crisis): {m!r}")
for m, hint in [("i just swallowed a bunch of tablets", "en"),
                ("maine abhi saari goliyan kha li", "hinglish"),
                ("mera dil karta hai ki i should just end it all tonight", "hinglish")]:
    check(TR.build_triage(m, hint).risk_level == TR.IMMINENT,
          f"acts-in-progress not IMMINENT: {m!r}")
# no false downgrade: explicit imminent survives reassurance/grief cues
check(TR.build_triage("i know i am safe with family but i already swallowed all the tablets",
                      "en").risk_level == TR.IMMINENT, "imminent wrongly downgraded")
# safe negatives must NOT over-escalate
for m in ["what time does the pharmacy open tomorrow?",
          "i did not take any pills, i just want to sleep",
          "i would never hurt myself, i promise"]:
    check(not TR.build_triage(m, "en").crisis, f"semantic over-escalated safe text: {m!r}")
# graceful degradation: force the semantic layer to raise → deterministic still classifies
_orig_sem = TR.semantic_escalation
try:
    TR.semantic_escalation = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    check(TR.build_triage("I want to kill myself", "en").risk_level == TR.HIGH,
          "deterministic HIGH lost when semantic layer down")
    check(TR.build_triage("I took a lot of pills just now", "en").risk_level == TR.IMMINENT,
          "deterministic IMMINENT lost when semantic layer down")
finally:
    TR.semantic_escalation = _orig_sem

# 2) RESOURCE FRESHNESS — every entry has next_verify_at; validator flags, never mutates.
for res in R.all_resources():
    check(bool(res.get("next_verify_at")), f"{res.get('id')} missing next_verify_at")
_fresh_today = R.check_resource_freshness(as_of="2026-09-25")
check(_fresh_today["ok"] and _fresh_today["missing_metadata_count"] == 0,
      f"freshness not ok today: {_fresh_today['missing_metadata']}")
_before = {r["id"]: r.get("next_verify_at") for r in R.all_resources()}
_fresh_future = R.check_resource_freshness(as_of="2035-01-01")
check(not _fresh_future["ok"] and _fresh_future["stale_count"] == _fresh_future["total"] > 0,
      "freshness validator failed to flag future staleness")
check(_before == {r["id"]: r.get("next_verify_at") for r in R.all_resources()},
      "freshness check mutated the registry")

# 3) AI-PROVIDER PRIVACY — sanitize_history drops sensitive/redacted/empty, clips, windows.
_RED = "[sensitive message not stored for your privacy]"
_msgs = [{"role": "user", "content": "hi", "risk_level": TR.LOW},
         {"role": "assistant", "content": "hello"},
         {"role": "user", "content": _RED, "risk_level": TR.HIGH},
         {"role": "user", "content": "I want to kill myself", "risk_level": TR.HIGH},
         {"role": "user", "content": "jumping now", "risk_level": TR.IMMINENT},
         {"role": "system", "content": "leak?"},
         {"role": "user", "content": "z" * 900, "risk_level": TR.LOW}]
_san = SUP.sanitize_history(_msgs, _RED)
check(all(o["role"] in ("user", "assistant") for o in _san), "sanitize let a non-chat role through")
check(_RED not in [o["content"] for o in _san], "sanitize leaked the redaction marker")
check("I want to kill myself" not in [o["content"] for o in _san], "sanitize leaked HIGH crisis text")
check(not any("jumping now" in o["content"] for o in _san), "sanitize leaked IMMINENT crisis text")
check(len(_san) <= 4 and all(len(o["content"]) <= 500 for o in _san),
      "sanitize window/clip not enforced")
check(SUP.sanitize_history(None, _RED) == [] and SUP.sanitize_history([{"x": 1}, 5], _RED) == [],
      "sanitize not defensive on junk input")

# 4) OFFLINE SAFETY PACK — HAVEN SOS path present; Tele-MANAS reachable offline (no AI).
check(op.get("haven_sos", {}).get("in_app_path") == "/sos", "offline pack missing HAVEN SOS /sos path")
check("14416" in {r["number"] for r in op["crisis"]}, "offline crisis pack missing Tele-MANAS 14416")

# 5) PRIVACY DASHBOARD accuracy — the Conversations text must reflect the real behaviour
#    (current message + short recent window) and must NOT keep the old misleading claim.
import os as _os  # noqa: E402
_routes = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "routers", "therapy_routes.py")
with open(_routes, encoding="utf-8") as _fh:
    _routes_src = _fh.read()
check("short window of your most recent non-sensitive chat turns" in _routes_src,
      "privacy dashboard text not updated to reflect recent-window behaviour")
check("Only the current non-crisis message is sent" not in _routes_src,
      "privacy dashboard still carries the old inaccurate 'only the current message' claim")

# ── Report ────────────────────────────────────────────────────────────────────
print(f"PASSED {_PASSES} checks")
if _FAILS:
    print(f"FAILED {len(_FAILS)}:")
    for f in _FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL MENTAL-HEALTH SAFETY CHECKS PASSED")
sys.exit(0)

