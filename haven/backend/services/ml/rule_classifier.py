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

MODEL_VERSION = "rule-lexicon-v2"

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
        r"\bemergency\b", r"\bcall 100\b", r"\bcall 911\b", r"\bcall 112\b", r"\brescue\b",
    ]),
}

# ─── Multilingual extension (Hindi / Hinglish) ─────────────────────────────
# Additive ONLY: these patterns map non-English distress terms onto the SAME
# seven indicators. They can only ADD a fired indicator (raise severity), never
# remove one — so a Hindi/Hinglish SOS is no longer silently scored LOW. Text is
# NFKC-normalised + lowercased by clean_text (harmless for Devanagari, which has
# no case). Devanagari patterns use plain substring match (no ASCII \b);
# romanized patterns are \b-anchored. Deterministic and fully explainable.
_MULTILINGUAL = {
    "emergency_assistance_request": [
        # Devanagari: बचाओ (save me), मदद (help), पुलिस बुलाओ (call police)
        r"बचाओ", r"बचाव", r"मदद", r"पुलिस बुलाओ", r"पुलिस को बुलाओ", r"कोई मदद",
        # Hinglish
        r"\bbachao\b", r"\bbachaao\b", r"\bbacha?o\b", r"\bmadad\b", r"\bmadat\b",
        r"\bmujhe bacha", r"\bpolice bulao\b", r"\bpolice bulaao\b", r"\bhelp karo\b",
        r"\bkoi madad\b",
    ],
    "immediate_danger": [
        # Devanagari: जल्दी आओ (come quickly), अभी (right now), दरवाज़ा तोड़ (breaking door),
        # घुस आया (broke in), सांस नहीं (can't breathe), दम घुट (choking)
        r"जल्दी आओ", r"जल्दी भेजो", r"जल्दी करो", r"अभी आओ", r"दरवाज़ा तोड़", r"दरवाजा तोड़",
        r"घुस आया", r"अंदर घुस", r"सांस नहीं", r"साँस नहीं", r"दम घुट",
        # Hinglish
        r"\bjaldi aao\b", r"\bjaldi bhejo\b", r"\bjaldi karo\b", r"\babhi aao\b",
        r"\bdarwaza tod", r"\bghus aaya\b", r"\bandar ghus", r"\bsaans nahi\b",
        r"\bdam ghut", r"\bgala ghont",
    ],
    "physical_assault": [
        # Devanagari: मार रहा (beating), पीट रहा (beating), थप्पड़ (slap), गला दबा (strangle)
        r"मार रहा", r"मार रही", r"मारा", r"मारता", r"मारती", r"पीट रहा", r"पीट रही", r"पीटा",
        r"पीट रहे", r"पीटता", r"थप्पड़", r"लात मार", r"घूंसा", r"गला दबा", r"मारपीट", r"नोच",
        # Hinglish
        r"\bmaar raha\b", r"\bmaar rahi\b", r"\bmaar rahe\b", r"\bmaar diya\b",
        r"\bmarta hai\b", r"\bmaarta hai\b", r"\bmarta\b", r"\bmaarta\b",
        r"\bpeet raha\b", r"\bpeet rahi\b", r"\bpeeta\b", r"\bpeetta\b", r"\bpitai\b",
        r"\bmaarpeet\b", r"\bthappad\b", r"\blaat maar", r"\bghoonsa\b", r"\bgala daba",
        # Past-tense "beat" (he beat me) — a completed assault must not score LOW.
        r"\bmaara\b", r"\bmara\b", r"\bmujhe maara\b", r"\bbahut maara\b", r"\bmaar diya\b",
        r"\bpeeta hai\b", r"\bpeet diya\b",
    ],
    "threat": [
        # Devanagari: जान से मार (will kill), मार डालूंगा (I'll kill), चाकू (knife),
        # बंदूक (gun), तेज़ाब (acid), धमकी (threat)
        r"जान से मार", r"मार डालूंगा", r"मार दूंगा", r"मार डालेगा", r"मारेगा", r"मार दूँगा",
        r"चाकू", r"बंदूक", r"बन्दूक", r"तेज़ाब", r"तेजाब", r"छुरी", r"धमकी", r"खत्म कर दूंगा",
        r"गला काट",
        # Hinglish
        r"\bjaan se maar", r"\bmaar dunga\b", r"\bmaar doonga\b", r"\bmaar dalega\b",
        r"\bmaarega\b", r"\bmaar daloonga\b", r"\bchaku\b", r"\bchaakoo\b", r"\bchurri\b",
        r"\bchhuri\b", r"\bbandook\b", r"\bbanduk\b", r"\btezaab\b", r"\btejaab\b",
        r"\bacid daal", r"\bdhamki\b", r"\bkhatam kar", r"\bgala kaat",
    ],
    "confinement": [
        # Devanagari: बंद कर दिया (locked in), कमरे में बंद (locked in room), बंधक (hostage)
        r"बंद कर दिया", r"कमरे में बंद", r"घर में बंद", r"बाहर नहीं जाने", r"दरवाज़ा बंद कर",
        r"बंधक", r"निकलने नहीं",
        # Hinglish
        r"\bband kar diya\b", r"\bkamre me band\b", r"\bghar me band\b", r"\bbahar nahi jane\b",
        r"\bdarwaza band kar", r"\bbandhak\b", r"\bnikalne nahi\b",
    ],
    "stalking": [
        # Devanagari: पीछा कर (following), घर के बाहर (outside house), पीछे पड़ा (after me)
        r"पीछा कर", r"पीछा कर रहा", r"पीछा कर रही", r"घर के बाहर", r"पीछे पड़ा",
        # Hinglish
        r"\bpeecha kar", r"\bpicha kar", r"\bpeeche pad", r"\bghar ke bahar\b",
        r"\bfollow kar raha\b",
    ],
    "repeated_abuse": [
        # Devanagari: हर रोज़ (every day), रोज़ मारता (beats daily), हमेशा (always)
        r"हर रोज़", r"हर रोज", r"हर दिन", r"रोज़ मारता", r"रोज मारता", r"हमेशा", r"बार बार",
        # Hinglish
        r"\bhar roz\b", r"\bhar din\b", r"\broz marta\b", r"\bhamesha\b", r"\bbaar baar\b",
    ],
}
for _ind, _pats in _MULTILINGUAL.items():
    _LEXICON[_ind].extend(_compile(_pats))

# Indicators that, on their own, imply an active in-progress emergency.
_CRITICAL_SIGNALS = {"immediate_danger"}
# Weapon / lethal cues push severity up hard even without other signals.
# English (\b-anchored) + Hindi (Devanagari, substring) + Hinglish (\b-anchored).
_LETHAL = re.compile(
    r"\b(knife|gun|shoot|stab|kill me|kill us|acid|strangl|chok(e|ing|ed)|can'?t breathe)\b"
    r"|चाकू|बंदूक|बन्दूक|तेज़ाब|तेजाब|छुरी|गला दबा|गला काट|दम घुट|सांस नहीं|साँस नहीं|जान से मार"
    r"|\b(chaku|chaakoo|churri|chhuri|bandook|banduk|tezaab|tejaab|gala daba|gala kaat|jaan se maar)\b"
)
# Explicit "I am safe / no danger" de-escalation cues.
_SAFE_CUES = re.compile(r"\b(i am safe|i'?m safe|no danger|not in (any )?danger|no violence|safe (right )?now|not an emergency)\b")

# Abduction / kidnapping in progress — a life-threatening emergency on its own.
# English + Devanagari (अगवा=abduct, किडनैप, उठा कर ले=lift-and-take) + Hinglish.
_ABDUCTION = re.compile(
    r"\b(kidnap(ped|ping)?|abduct(ed|ing|ion)?|"
    r"forc(e|ed|ing) (me|her) into (a |the |his )?(car|van|vehicle|auto|cab)|"
    r"drag(ged|ging)? (me|her) into|shov(e|ed|ing) (me|her) into|"
    r"pull(ed|ing)? (me|her) into (a |the |his )?(car|van|vehicle)|"
    r"taking (me|her) away|took (me|her) away against)\b"
    r"|अगवा|किडनैप|उठा कर ले|उठा कर ले जा|उठा ले ग|उठाकर ले"
    r"|\b(agva|agwa|kidnap kar|utha kar le ja|utha ke le ja|utha kar le gaya|"
    r"utha kar le|uthaya|utha liya|utha le gaya)\b"
)

# Low-grade fear / harassment / unease — real distress, but no evidence of active
# violence. Floors these at MODERATE so a woman's "a suspicious man is watching my
# building" / "I feel unsafe" is never scored LOW ('no signal'). Never a danger floor.
_UNEASE = re.compile(
    r"feel(ing)?\b.{0,14}\b(unsafe|scared|threatened|afraid|uneasy|creeped out)"
    r"|\b(creepy|suspicious|inappropriate|uncomfortable|harass(ing|ed|ment)?)\b"
    r"|\bloiter(ing|s|ed)?\b|\bstaring at me\b|\bkeeps staring\b"
    r"|\bwatching (my|me|the house|the building)\b|\bbeing watched\b"
    r"|\bwon'?t leave me alone\b|\bkeeps (calling|texting|messaging|following)\b"
    r"|डर लग|घूर|असहज|संदिग्ध|परेशान कर"
    r"|\b(dar lag|darr lag|ghoor|asahaj|sandigdh|pareshan kar)\b"
)


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
    Map fired indicators -> severity band (deterministic safety floor).

    CRITICAL: a lethal weapon / asphyxiation / "kill me" cue, OR an abduction in
              progress, OR an active in-progress danger cue combined with any
              violence / threat / help-plea. A weapon or life-threat present is
              CRITICAL on its own evidence — it must NEVER be graded lower merely
              because the victim did not also type the word "help".
    HIGH:     physical assault, confinement, an in-progress danger cue on its own,
              a direct threat of harm, active stalking (a leading pre-assault risk
              factor), or a repeated / escalating abuse pattern.
    MODERATE: low-grade fear / harassment / unease, or a bare help-plea with no
              concrete danger indicator — needs follow-up, no evidence of violence.
    LOW:      distress / information-seeking with no danger indicators, or an
              explicit "I'm safe" cue.

    This can only raise severity on evidence; it never downgrades a concrete
    high-risk signal. Output is decision support — a human authority must verify
    before any action (no auto-dispatch).
    """
    names = set(fired)
    lethal = bool(_LETHAL.search(cleaned))
    abduction = bool(_ABDUCTION.search(cleaned))
    has_emergency = "emergency_assistance_request" in names
    imminent = "immediate_danger" in names

    # ── CRITICAL ──────────────────────────────────────────────────────────────
    if lethal or abduction:
        return "CRITICAL"
    if imminent and (has_emergency or "physical_assault" in names or "threat" in names):
        return "CRITICAL"

    # ── HIGH ──────────────────────────────────────────────────────────────────
    if names & {"physical_assault", "confinement", "immediate_danger",
                "threat", "stalking", "repeated_abuse"}:
        return "HIGH"

    # ── MODERATE ──────────────────────────────────────────────────────────────
    if _UNEASE.search(cleaned):
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
    # caps severity at LOW — but ONLY when no concrete danger signal is present.
    # A message like "I'm safe now, he has a knife" fires threat + a lethal cue,
    # so it must NOT be capped: a contradictory reassurance never overrides an
    # active weapon/violence/threat signal (deterministic safety floor).
    _danger_signals = fired.keys() & {
        "physical_assault", "confinement", "immediate_danger", "threat", "stalking",
    }
    if (
        _SAFE_CUES.search(cleaned)
        and not _danger_signals
        and not _LETHAL.search(cleaned)
    ):
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
