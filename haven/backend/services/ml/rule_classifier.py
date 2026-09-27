"""
Rule-based lexicon risk classifier — the always-available DEMO tier.

Pure standard library. Deterministic, fully explainable, and requires no model
download, so the /ai/classify-risk endpoint works on a fresh checkout with zero
ML dependencies. This is an honest heuristic baseline, NOT a trained model —
`is_demo_mode` is always True for this backend and the explanation says so.

The lexicon maps regex patterns to the platform's seven indicators. Severity is
derived from which indicators fire and how strong the danger signal is, then the
risk_score (0-100) is a monotonic function of that severity plus signal density.
"""
import re
from .preprocessing import clean_text, SEVERITY_LEVELS, SEVERITY_ORDER

MODEL_VERSION = "rule-lexicon-v1"

# ─── Indicator lexicon ────────────────────────────────────────────────────
# Each indicator maps to a list of compiled regex patterns. Word boundaries
# keep "hit" from matching "white". Patterns run against cleaned (lowercased,
# de-obfuscated) text.
def _compile(patterns):
    return [re.compile(p) for p in patterns]

_LEXICON = {
    "physical_assault": _compile([
        r"\bhit(s|ting)?\b", r"\bhitme\b", r"\bbeat(en|ing|s)?\b", r"\bpunch",
        r"\bslap", r"\bkick", r"\bchok(e|ing|ed)", r"\bstrangl", r"\bshov(e|ed|ing)",
        r"\bpush(ed|ing)?\b", r"\bgrab(bed|bing)?\b", r"\bdrag(ged|ging)?\b",
        r"\bpinn?ed\b", r"\bthrew me\b", r"\bthrow(n|ing)? me\b", r"\bburn(ed|t|ing)?\b",
        r"\battack(ed|ing|s)?\b", r"\bassault", r"\bbruis", r"\bbleeding\b",
        r"\bbroke(n)? (my )?(arm|nose|rib)", r"\bheld me down\b",
    ]),
    "threat": _compile([
        r"\bthreat", r"\bkill (me|us|you)\b", r"\bshoot\b", r"\bstab\b",
        r"\bhurt (me|us|you)\b", r"\bharm (me|us|you)\b", r"\bacid\b",
        r"\bwon'?t be so lucky\b", r"\bdo worse\b", r"\bmake a scene\b",
        r"\bif i (leave|tell|report|go|talk|call)", r"\bpost my (private )?photos\b",
        r"\btake the kids\b", r"\bknife\b", r"\bgun\b", r"\bweapon\b", r"\brod\b",
    ]),
    "confinement": _compile([
        r"\block(ed|s|ing)? (me|us)?\s*(in|inside|up)?\b", r"\block(ed)? the (door|gate)\b",
        r"\bwon'?t let me (leave|out|go)\b", r"\bwould'?nt let me\b", r"\bcan'?t (get|leave)",
        r"\bcannot leave\b", r"\btrapped\b", r"\bblock(ing|ed)? the (door|exit|only exit)\b",
        r"\btied (me )?up\b", r"\bcan'?t leave the (house|room|flat)\b", r"\btook (all )?(my|the) keys\b",
        r"\bnever leave the house\b", r"\bstore ?room\b",
    ]),
    "stalking": _compile([
        r"\bstalk", r"\bfollow(ed|ing|s)?\b", r"\bshow(ing|s|ed)? up (outside|at)\b",
        r"\bwaiting outside\b", r"\bwatching (my|the) (house|home)\b", r"\btracker\b",
        r"\bknows everywhere i go\b", r"\bwon'?t stop (texting|calling)\b",
        r"\boutside my (workplace|building|apartment|college|house)\b",
    ]),
    "immediate_danger": _compile([
        r"\bright now\b", r"\bcome quickly\b", r"\bcome fast\b", r"\bhurry\b",
        r"\bhiding\b", r"\bcan'?t breathe\b", r"\bchasing me\b", r"\bbreaking (the )?door\b",
        r"\bbreaking (it |the )?down\b", r"\bbanging on\b", r"\bpounding on\b",
        r"\bbroke in\b", r"\bforcing me into\b", r"\bforce (me|her) into\b",
        r"\bnearly passed out\b", r"\bset (fire|it on fire)\b", r"\bsmashing\b",
    ]),
    "repeated_abuse": _compile([
        r"\bevery (night|day|weekend|week)\b", r"\balways\b", r"\bagain (tonight|today)\b",
        r"\brepeat(ed|edly)?\b", r"\bfor (years|weeks|months)\b", r"\bfor the past\b",
        r"\bthis week\b", r"\bkeeps (hitting|threatening|calling|following|screaming)\b",
        r"\btwice this month\b", r"\bhas been abusive\b", r"\balmost every\b",
    ]),
    "emergency_assistance_request": _compile([
        r"\bhelp\b", r"\bsos\b", r"\bsend (help|police|someone|an ambulance)\b",
        r"\bcall (the )?police\b", r"\bplease help\b", r"\bneed (help|police|an ambulance)\b",
        r"\bemergency\b", r"\bcall 100\b", r"\bcall 911\b", r"\brescue\b",
    ]),
}

# Indicators that, on their own, imply an active in-progress emergency.
_CRITICAL_SIGNALS = {"immediate_danger"}
# Weapon / lethal cues push severity up hard even without other signals.
_LETHAL = re.compile(r"\b(knife|gun|shoot|stab|kill me|kill us|acid|strangl|chok(e|ing|ed)|can'?t breathe)\b")
# Explicit "I am safe / no danger" de-escalation cues.
_SAFE_CUES = re.compile(r"\b(i am safe|i'?m safe|no danger|not in (any )?danger|no violence|safe (right )?now|not an emergency)\b")


def _match_indicators(cleaned: str):
    """Return (set of indicator names that fired, dict of per-indicator hit counts)."""
    fired = {}
    for name, patterns in _LEXICON.items():
        hits = sum(1 for p in patterns if p.search(cleaned))
        if hits:
            fired[name] = hits
    return fired


def _derive_severity(fired: dict, cleaned: str) -> str:
    """
    Map fired indicators -> severity band.

    CRITICAL: active immediate danger, OR a lethal weapon/asphyxiation cue,
              OR physical assault happening together with an emergency plea.
    HIGH:     physical assault or confinement present (violence has occurred),
              or a direct threat combined with stalking.
    MODERATE: threats, stalking, confinement-lite, or repeated controlling abuse
              without a clear in-progress assault.
    LOW:      distress / information-seeking with no danger indicators, or an
              explicit "I'm safe" cue.
    """
    names = set(fired)
    lethal = bool(_LETHAL.search(cleaned))
    has_emergency = "emergency_assistance_request" in names

    if _CRITICAL_SIGNALS & names and (has_emergency or lethal or "physical_assault" in names or "threat" in names):
        return "CRITICAL"
    if lethal and has_emergency:
        return "CRITICAL"
    if "physical_assault" in names and has_emergency and _CRITICAL_SIGNALS & names:
        return "CRITICAL"

    if "physical_assault" in names or "confinement" in names:
        return "HIGH"
    if "threat" in names and "stalking" in names:
        return "HIGH"
    if lethal:
        return "HIGH"

    if names & {"threat", "stalking", "repeated_abuse"}:
        return "MODERATE"
    if has_emergency and names:
        return "MODERATE"

    # No danger indicators fired.
    return "LOW"


def _score_for(severity: str, fired: dict) -> int:
    """
    Risk score 0-100: severity sets the band floor, signal density nudges within.
    """
    band_floor = {"LOW": 5, "MODERATE": 40, "HIGH": 65, "CRITICAL": 88}[severity]
    band_span = {"LOW": 20, "MODERATE": 20, "HIGH": 20, "CRITICAL": 12}[severity]
    total_hits = sum(fired.values())
    # Saturating density factor (0..1) over the band's span.
    density = min(total_hits, 6) / 6.0
    return int(round(band_floor + density * band_span))


def _confidence(fired: dict, severity: str) -> float:
    """
    Heuristic confidence 0..1. More corroborating indicators -> higher
    confidence. LOW severity with zero indicators is a confident 'no signal'.
    This is a rule-of-thumb, not a calibrated probability, and is labelled DEMO.
    """
    n_indicators = len(fired)
    if severity == "LOW" and n_indicators == 0:
        return 0.6
    # 1 indicator ~0.55, saturates toward ~0.9 with 4+ indicators.
    return round(min(0.55 + 0.1 * n_indicators, 0.9), 2)


def classify(text: str) -> dict:
    """
    Classify a distress message with the rule-based lexicon.

    Returns the canonical result shape shared by every backend.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return {
            "severity": "LOW",
            "risk_score": 0,
            "indicators": [],
            "confidence": 0.5,
            "explanation": "No text supplied to classify.",
            "model_version": MODEL_VERSION,
            "backend": "rules",
            "is_demo_mode": True,
        }

    fired = _match_indicators(cleaned)

    # Explicit de-escalation: an unambiguous "I'm safe / no danger" statement
    # with no violence/confinement indicators caps severity at LOW.
    if _SAFE_CUES.search(cleaned) and not (fired.keys() & {"physical_assault", "confinement", "immediate_danger"}):
        severity = "LOW"
    else:
        severity = _derive_severity(fired, cleaned)

    indicators = sorted(fired.keys(), key=lambda k: SEVERITY_ORDER.get(severity, 0))
    risk_score = _score_for(severity, fired)
    confidence = _confidence(fired, severity)

    if indicators:
        explanation = (
            f"Rule-based DEMO classifier matched {len(indicators)} risk indicator(s): "
            f"{', '.join(indicators)}. Severity {severity} derived from these signals. "
            "This is a heuristic baseline for decision support only — a human authority "
            "must verify before any action."
        )
    else:
        explanation = (
            "Rule-based DEMO classifier found no explicit risk indicators; treated as "
            f"{severity} (distress / information-seeking). Human review still recommended."
        )

    return {
        "severity": severity,
        "risk_score": risk_score,
        "indicators": indicators,
        "confidence": confidence,
        "explanation": explanation,
        "model_version": MODEL_VERSION,
        "backend": "rules",
        "is_demo_mode": True,
    }
