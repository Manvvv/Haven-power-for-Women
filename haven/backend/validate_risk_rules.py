"""
validate_risk_rules.py — dependency-free regression lock for HAVEN's SOS
free-text risk engine on its DETERMINISTIC 'rules' backend.

Runs with the standard library only (no torch / sklearn / fastapi / network), so
it works in constrained environments and CI. It pins the *safety-critical*
severity invariants that the eval harness measured and that the rule classifier
(`services.ml.rule_classifier`, exposed via `services.ml.risk_engine`) must never
silently lose:

  * a lethal / asphyxiation / "kill me" cue is CRITICAL on its own evidence
  * an abduction in progress is CRITICAL on its own evidence
  * an in-progress danger cue is never scored below HIGH
  * physical assault / confinement / threat / stalking / repeated abuse is >= HIGH
  * Hindi / Hinglish distress (incl. past-tense "beat") is not silently LOW
  * a contradictory "I'm safe" reassurance NEVER overrides an active danger signal
  * a genuine "I'm safe, no danger" de-escalation with NO danger signal is LOW
  * low-grade fear / harassment (no active violence) is floored at MODERATE
  * benign / admin / info-seeking text is LOW

These are UNDER-ESCALATION tripwires: for a women's-safety platform the dangerous
failure is a real emergency scored calm. Every check asserts a *floor*
(pred >= expected on SEVERITY_ORDER) or an exact band where the band is the point.
Output is decision support only — a human authority verifies before any action;
this file does not test auto-dispatch because there is none.

Exit code 0 = all pass. Run:  python3 validate_risk_rules.py   (cwd = backend)
"""
import sys

sys.path.insert(0, ".")
from services.ml import risk_engine as RE   # noqa: E402

ORDER = RE.SEVERITY_ORDER
_FAILS = []
_PASSES = 0


def _check(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
    else:
        _FAILS.append(label)


_ENG = RE.get_engine()


def _sev(text):
    return _ENG.predict(text).get("severity", "LOW")


def exact(text, expected):
    """Severity must equal `expected` exactly (used where the band is the point)."""
    got = _sev(text)
    _check(got == expected, f"{text!r} -> {got} (expected exactly {expected})")


def floor(text, minimum):
    """Severity must be AT LEAST `minimum` (under-escalation guard)."""
    got = _sev(text)
    _check(ORDER.get(got, 0) >= ORDER[minimum],
           f"{text!r} -> {got} (expected >= {minimum})")


# ── 1. Lethal / asphyxiation / "kill me" cues → CRITICAL on their own ──────────
for t in [
    "he has a knife",
    "he is pointing a gun at me",
    "he threatened to kill me tonight",
    "he strangled me i cant breathe",
    "he is choking me",
    "he threw acid at my sister",
    "usके पास चाकू है",              # devanagari: he has a knife
    "wo bandook lekar aaya hai",     # hinglish: he came with a gun
    "usne gala daba diya",           # hinglish: he strangled
    "jaan se maar dunga bola",       # hinglish: said he'll kill me
]:
    exact(t, "CRITICAL")

# ── 2. Abduction in progress → CRITICAL (English + Devanagari + Hinglish) ───────
for t in [
    "he kidnapped me and locked me in a van",
    "he is forcing me into his car",
    "they are dragging me into a vehicle",
    "usne mujhe utha liya",          # hinglish: he abducted/lifted me
    "utha kar le ja rahe hain",      # hinglish: they are taking me away
    "किडनैप कर लिया",                 # devanagari: kidnapped
]:
    exact(t, "CRITICAL")

# ── 3. in-progress danger + (help / assault / threat) → CRITICAL ───────────────
for t in [
    "he is breaking the door down please send police right now",
    "he is chasing me and hitting me right now",
]:
    exact(t, "CRITICAL")

# A contradictory "I'm safe" reassurance NEVER overrides an active danger signal.
exact("i am safe now but he has a knife", "CRITICAL")
floor("dont worry im fine, he is breaking down the door", "HIGH")

# ── 4. in-progress danger cue ALONE is never below HIGH ────────────────────────
for t in [
    "he is banging on the door right now",
    "im hiding in the bathroom he is pounding on it",
    "come quickly hurry",
]:
    floor(t, "HIGH")

# ── 5. assault / confinement / threat / stalking / repeated → at least HIGH ────
floor("he punched me and bruised my arm", "HIGH")            # physical_assault
floor("he beat me last night", "HIGH")                       # physical_assault (past)
floor("he locked me in the room and took the keys", "HIGH")  # confinement
floor("he said he will hurt me if i leave", "HIGH")          # threat
floor("a man keeps following me to work every day", "HIGH")  # stalking
floor("he hits me every night", "HIGH")                      # repeated_abuse

# ── 6. Hindi / Hinglish distress is not silently LOW ───────────────────────────
floor("wo mujhe maar raha hai", "HIGH")     # beating me (present)
floor("usne mujhe bahut maara", "HIGH")     # beat me a lot (past)
floor("मार रहा है मुझे", "HIGH")             # devanagari: beating me
floor("बचाओ जल्दी आओ", "HIGH")               # devanagari: save me come quick

# ── 7. genuine de-escalation with NO danger signal → LOW ───────────────────────
for t in [
    "i am safe now, there is no danger",
    "false alarm, not an emergency, i'm safe",
]:
    exact(t, "LOW")

# ── 8. low-grade fear / harassment (no active violence) → floored at MODERATE ──
for t in [
    "i feel unsafe, a creepy man is watching my building",
    "a suspicious man keeps loitering outside my apartment",
    "my coworker keeps texting me and won't leave me alone",
    "डर लग रहा है कोई घूर रहा है",   # devanagari: feeling scared, someone staring
]:
    floor(t, "MODERATE")

# A bare help plea with no concrete indicator → at least MODERATE (needs follow-up)
floor("please help me", "MODERATE")

# ── 9. benign / info-seeking → LOW ─────────────────────────────────────────────
# NOTE: phrases containing "emergency" / "sos" / "help" deliberately trip the
# emergency_assistance_request indicator and float up to a soft MODERATE follow-up
# (a SAFE over-escalation the eval harness records honestly as sos27/sos28). This
# validator locks the under-escalation floors, so it uses genuinely benign,
# keyword-free info-seeking text that must stay LOW.
for t in [
    "how do i use this app",
    "how do i change my profile picture",
    "what languages does this app support",
]:
    exact(t, "LOW")

# ── 10. contract invariants ────────────────────────────────────────────────────
_out = _ENG.predict("he has a knife")
_check(_out.get("backend") == "rules",
       f"default backend should be 'rules', got {_out.get('backend')!r}")
_check(_out.get("model_version") == "rule-lexicon-v2",
       f"model_version should be 'rule-lexicon-v2', got {_out.get('model_version')!r}")
_check(0 <= _out.get("risk_score", -1) <= 100,
       f"risk_score out of range: {_out.get('risk_score')}")
# empty input must be safe & explicit, never crash
_empty = _ENG.predict("")
_check(_empty.get("severity") == "LOW", "empty input should be LOW")


def main():
    print("Validating SOS risk RULE ENGINE (deterministic 'rules' backend)...\n")
    if _FAILS:
        print(f"{_PASSES} passed, {len(_FAILS)} FAILED\n")
        for f in _FAILS:
            print("  FAIL:", f)
        return 1
    print(f"PASSED {_PASSES} checks")
    print("ALL SOS RISK-RULE SAFETY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
