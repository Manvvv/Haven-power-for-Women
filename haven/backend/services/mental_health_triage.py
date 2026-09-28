"""
mental_health_triage.py — Deterministic (NON-LLM) mental-health safety triage.

This is HAVEN's safety layer. It runs BEFORE any language model and never depends on
one, so crisis detection is reproducible, auditable, and still works when the AI
provider is down (spec §3, §28, §29). It is deliberately CONSERVATIVE around safety:
when a statement is ambiguous it escalates or asks a gentle safety question rather
than assuming the person is fine.

It classifies a message into one risk STATE:
    LOW_DISTRESS | MODERATE_DISTRESS | HIGH_RISK | IMMINENT_DANGER | UNKNOWN
and sets independent boolean SIGNALS:
    self_harm | suicide | abuse | violence | child_safety |
    medical_emergency | psychosis | substance

It works across English, Hindi (Devanagari) and Hinglish using Unicode-aware
tokenization plus substring phrase matching (spec §12). It performs NO diagnosis and
outputs no clinical labels — only risk level, signals, language, and whether a
clarifying safety question is needed.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TRIAGE_VERSION = "2026-09-25"
# Hybrid recall layer version (fuzzy/near-miss escalation on top of the lexicon).
SEMANTIC_VERSION = "2026-09-25"

# Risk states (ordered low → high for comparison).
LOW = "LOW_DISTRESS"
MODERATE = "MODERATE_DISTRESS"
HIGH = "HIGH_RISK"
IMMINENT = "IMMINENT_DANGER"
UNKNOWN = "UNKNOWN"
_RANK = {UNKNOWN: 0, LOW: 1, MODERATE: 2, HIGH: 3, IMMINENT: 4}

# Response modes drive length adaptation (spec §25).
MODE_NORMAL = "normal"
MODE_MODERATE = "moderate"
MODE_CRISIS = "crisis"
MODE_EMERGENCY = "emergency"

# Unicode-aware token pattern: ASCII alphanumerics OR a run of Devanagari letters/
# matras/digits (danda U+0964/U+0965 excluded). Mirrors the legal-triage tokenizer.
_WORD_RE = re.compile(r"[a-z0-9]+|[ऀ-ॣ०-ॿ]+")

# ─────────────────────── Lexicons (EN + Hindi + Hinglish) ───────────────────────
# All matching is substring-on-lowercased-text, which works across scripts. Phrases
# are chosen to be high-precision for the risk tier they sit in.

# IMMINENT: an act in progress / just taken, an active attack, or clear means+intent+now.
_IMMINENT_PHRASES = [
    # self-harm / overdose already done or in progress
    "took pills", "taken pills", "took the pills", "took a lot of pills", "took too many",
    "swallowed pills", "swallowed the", "overdosed", "over dosed", "od'd", "slit my", "slitting",
    "already cut", "cutting myself right now", "bleeding a lot", "won't stop bleeding",
    "took poison", "drank poison", "drank bleach", "took rat poison",
    # imminent suicide (plan/means/now)
    "going to kill myself", "about to kill myself", "kill myself tonight", "kill myself now",
    "end it tonight", "end it now", "end my life tonight", "ending it now", "about to jump",
    "going to jump", "on the ledge", "on the roof", "standing on the bridge", "tie the noose",
    "hang myself now", "shoot myself", "i have a plan to", "ready to die now",
    # means + intent
    "have a weapon and", "have a knife and", "have a gun and", "have pills and",
    "have a rope and", "thinking about using it", "going to use it on myself",
    # active external attack / immediate danger from another
    "attacking me right now", "being attacked", "he is attacking", "she is attacking",
    "attacking me", "hitting me right now", "he is hitting me", "beating me right now",
    "he is going to kill me", "going to kill me", "trying to kill me", "he has a knife",
    "he has a gun", "strangling me", "choking me", "kidnapped", "locked me in",
    # medical emergency
    "can't breathe", "cannot breathe", "not breathing", "chest pain", "unconscious",
    "collapsed", "passed out", "overdose",
    # Hindi (Devanagari)
    "गोलियां खा ली", "गोलियाँ खा ली", "गोली खा ली", "दवा खा ली", "ज़हर खा", "जहर खा",
    "अभी मार रहा", "मार रहा है", "मुझ पर हमला", "जान से मार", "मार डालेगा", "बचाओ",
    "अभी मरने", "अभी खत्म", "फांसी", "छत पर खड़", "साँस नहीं",
    # Hinglish
    "pills le li", "goliyan le li", "goliyaan le li", "zeher kha", "zaher kha", "poison pi",
    "abhi maar raha", "maar raha hai", "mujh par hamla", "jaan se maar", "bacha lo",
    "abhi marne", "abhi khatam kar", "phansi", "chhat par khada", "saans nahi",
    # Hinglish overdose already-taken — English noun ("pills") + Hindi verb ("kha li/liya"),
    # a very common code-switch that previously scored UNKNOWN (safety gap). Romanized
    # goli/dawa combos too (Devanagari forms already covered above).
    "pills kha li", "pills kha liya", "pills kha lee", "pills kha lie",
    "goli kha li", "goliyan kha li", "goliyaan kha li", "goli kha liya", "goliyan kha liya",
    "dawa kha li", "dawai kha li", "dawa kha liya", "neend ki goli", "neend ki goliyan",
    "sleeping pills kha", "bahut saari pills kha", "bahut saari goli kha", "zeher pi liya",
    "zeher kha liya", "poison kha li", "poison pi liya",
]

# IMMINENT self-harm INTENT ("going to / about to / right now"). These are negatable
# ("I'm NOT going to hurt myself"), so they only escalate when NOT reassured (below).
_IMMINENT_SELFHARM_INTENT = [
    "going to hurt myself", "gonna hurt myself", "about to hurt myself",
    "going to harm myself", "about to harm myself", "going to hurt myself now",
    "hurt myself right now", "harm myself right now", "going to cut myself",
    "about to cut myself", "khud ko hurt karne ja", "khud ko nuksan karne ja",
    "abhi khud ko hurt", "abhi khud ko nuksan",
]

# HIGH_RISK: explicit suicidal ideation / intent / self-harm desire (not in progress).
_SUICIDE_PHRASES = [
    "kill myself", "want to die", "wanna die", "i want to be dead", "wish i was dead",
    "wish i were dead", "wish i wouldn't wake up", "wish i would not wake up",
    "don't want to be here", "dont want to be here", "don't want to be here anymore",
    "don't want to live", "dont want to live", "no reason to live", "no point in living",
    "better off dead", "everyone better off without me", "end my life", "end it all",
    "ending it all", "ending my life", "ending it tonight", "want to end my life",
    "want to end it", "take my own life", "commit suicide", "suicidal", "suicide",
    "can't stay safe", "cannot stay safe", "can't keep myself safe", "don't feel safe from myself",
    # Eval-driven additive recall (seed set mh16/mh18/mh22): phrasing/method variants of
    # clearly suicidal ideation that the contiguous phrases above miss. Same HIGH-tier
    # scoping — still downgraded by _REASSURANCE / negation, never a new floor.
    "better off without me", "be better off without me", "world better off without me",
    "just ending it", "thinking about ending it", "thinking of ending it", "think about ending it",
    "all my pills at once", "all these pills at once", "take all my pills at once",
    "taking all my pills at once", "swallow all my pills", "swallow all these pills",
    "overdose on my pills", "take a whole bottle of pills", "whole bottle of pills",
    "मरना चाहता", "मरना चाहती", "मर जाना चाहता", "मर जाना चाहती", "आत्महत्या", "खुदकुशी",
    "जीना नहीं चाहता", "जीना नहीं चाहती", "जीने का मन नहीं", "मरना है", "खत्म कर दूं",
    "marna chahta", "marna chahti", "marna hai", "mar jana chahta", "mar jaana chahta",
    "atmahatya", "aatmahatya", "khudkushi", "jeena nahi chahta", "jeena nahi chahti",
    "jeene ka mann nahi", "khatam kar dun", "khatam kar dunga", "khatam kar dungi",
    "suicide karna", "suicide kar",
    # Eval-driven additive recall (seed set mh19): "dying is better" ideation phrasings.
    "marna behtar", "marna hi behtar", "mar jana behtar", "mar jaana behtar", "mar jana hi behtar",
    "मरना बेहतर", "मरना ही बेहतर", "मर जाना बेहतर",
]
_SELF_HARM_PHRASES = [
    "hurt myself", "harm myself", "self harm", "self-harm", "selfharm", "cut myself",
    "cutting myself", "cut my wrist", "burn myself", "injure myself", "want to bleed",
    # Eval-driven additive recall (seed set mh15): gerund / continuous phrasings that the
    # base ("hurt myself") misses. Same HIGH-tier scoping and _REASSURANCE downgrade.
    "hurting myself", "harming myself", "injuring myself", "cutting my wrist",
    "खुद को नुकसान", "खुद को चोट", "खुद को मारना", "खुद को नुक्सान",
    "khud ko hurt", "khud ko nuksan", "khud ko nuqsan", "khud ko chot", "khud ko marna",
]
# Reassurance / negation that DOWNGRADES a crisis phrase (kept minimal + explicit).
_REASSURANCE = [
    "don't want to die", "dont want to die", "not going to kill myself", "won't kill myself",
    "would never kill myself", "would never hurt myself", "i'm not suicidal", "im not suicidal",
    "not suicidal", "no longer want to die", "used to want to die", "don't want to hurt myself",
    "dont want to hurt myself", "not going to hurt myself", "not going to harm myself",
    "won't hurt myself", "won't harm myself", "wont hurt myself", "wont harm myself",
    "wont kill myself", "would never harm myself",
    "नहीं मरना चाहता", "मरना नहीं चाहता", "आत्महत्या नहीं",
    "marna nahi chahta", "nahi marna chahta", "suicide nahi",
]

# MODERATE_DISTRESS: significant distress, coping breakdown, panic — not (yet) crisis.
_MODERATE_PHRASES = [
    "hopeless", "no hope", "can't cope", "cannot cope", "can't take it", "cant take it",
    "can't take this anymore", "can't go on", "cant go on", "breaking down", "falling apart",
    "can't handle", "cannot handle", "can't do this anymore", "cant do this anymore",
    "panic attack", "panicking", "having a panic", "can't stop crying", "cant stop crying",
    "can't stop worrying", "cant stop worrying", "really low", "very low", "so depressed",
    "feeling worthless", "feel worthless", "empty inside", "feel numb", "feeling numb",
    "burnt out", "burned out", "can't get out of bed", "don't know how to cope",
    "dont know how to cope", "can't keep doing this", "cant keep doing this",
    "how long i can keep", "what's the point", "whats the point", "tired of everything",
    "so anxious", "so much anxiety", "severe anxiety",
    "उम्मीद नहीं", "बहुत डर", "बहुत घबरा", "घबराहट", "बहुत परेशान", "हिम्मत नहीं",
    "टूट गया", "टूट गई", "संभाल नहीं", "बहुत उदास",
    "bahut anxiety", "bahut pareshan", "bahut ghabra", "ghabrahat", "himmat nahi",
    "ummeed nahi", "tut gaya", "sambhal nahi", "bahut udaas", "cope nahi kar",
    "sab khatam ho gaya", "sab khatam", "kuch samajh nahi",
]

# LOW_DISTRESS: everyday stress, sadness, loneliness, tiredness, worry.
_LOW_PHRASES = [
    "stressed", "stress", "stressful", "lonely", "alone", "feeling alone", "sad", "unhappy",
    "feeling down", "feel down", "feeling low", "tired", "exhausted", "nervous", "worried",
    "anxious", "anxiety", "upset", "frustrated", "can't sleep", "cant sleep", "couldn't sleep",
    "not sleeping", "overwhelmed", "feel terrible", "bad day", "rough day", "feeling bad",
    "homesick", "heartbroken", "grief", "grieving", "miss them", "miss her", "miss him",
    "exam stress", "exams", "work stress", "study stress",
    "तनाव", "अकेला", "अकेली", "उदास", "परेशान", "थका", "थकी", "नींद नहीं", "डर लग",
    "tanav", "akela", "akeli", "udaas", "pareshan", "thaka", "thak gaya", "neend nahi",
    "stress hai", "dar lag", "akelapan", "dukhi",
]

# ─────────────────────── Signal lexicons (independent flags) ───────────────────────
_ABUSE_PHRASES = [
    "my partner", "my husband", "my boyfriend", "my in-laws", "my in laws", "sasural",
    "domestic violence", "beats me", "beat me", "hits me", "hitting me", "hit me",
    "abusing me", "abuses me", "abusive", "threatens me", "threatening me", "scared to go home",
    "afraid to go home", "won't let me leave", "controls me", "controlling", "coercive",
    "forced me", "forces me", "raped", "molested", "sexual", "stalking me", "following me home",
    "पति मारता", "पति पीटता", "पति धमकी", "घर जाने से डर", "मारता है", "पीटता है", "छेड़",
    "pati marta", "pati peetta", "pati dhamki", "ghar jaane se dar", "marta hai", "peetta hai",
]
_ACTIVE_VIOLENCE_PHRASES = [
    "hitting me", "beating me", "attacking me", "he is hitting", "he is beating",
    "attacking me right now", "being attacked", "strangling", "choking me",
    "मार रहा है", "मुझ पर हमला", "पीट रहा",
    "maar raha hai", "peet raha", "mujh par hamla",
]
_CHILD_OWN_PHRASES = [
    "my child", "my son", "my daughter", "my kid", "my baby", "my little", "my toddler",
    "my student", "मेरा बच्चा", "मेरी बेटी", "मेरा बेटा", "mera baccha", "meri beti", "mera beta",
]
_MEDICAL_PHRASES = [
    "took pills", "taken pills", "overdosed", "overdose", "swallowed", "poison", "bleeding",
    "can't breathe", "cannot breathe", "not breathing", "chest pain", "unconscious",
    "collapsed", "passed out", "seizure",
    "गोलियां खा", "गोली खा", "ज़हर", "जहर", "खून बह", "साँस नहीं",
    "pills le li", "goliyan le", "zeher", "zaher", "khoon beh", "saans nahi",
]
_PSYCHOSIS_PHRASES = [
    "hearing voices", "voices telling me", "voices in my head", "voices are telling",
    "seeing things", "seeing things that aren't", "hallucin", "losing my mind",
    "can't tell what's real", "cant tell whats real", "not real", "they are watching me",
    "आवाज़ें आ रही", "आवाजें सुनाई", "दिमाग खराब", "समझ नहीं आ रहा क्या असली",
    "aawaz aa rahi", "awaaz sunai", "dimaag kharab", "voices sunai",
]
_SUBSTANCE_PHRASES = [
    "sleeping pills", "how much medicine", "how many pills", "how many tablets",
    "extra pills", "extra dose", "double dose", "mix these medic", "mix my medic",
    "mix pills", "with alcohol", "lethal dose", "overdose on", "take more pills",
    "how much paracetamol", "how much of my", "kitni goliyan", "kitni dawa",
    "दवा कितनी", "कितनी गोलियां", "ज्यादा दवा",
]
# Dosing / lethal-quantity REQUESTS must never be answered with numbers (spec §18).
_DOSING_REQUEST = [
    "how much", "how many", "extra pills", "extra dose", "double dose", "take more",
    "mix these", "mix my", "lethal dose", "enough to", "kitni", "kitna", "ज्यादा", "कितनी",
]

# Minor self-identification (light heuristic → stricter safeguarding, spec §20).
_MINOR_RE = re.compile(
    r"\bi[' ]?a?m\s+(\d{1,2})\b|\b(\d{1,2})\s*(years?\s*old|yrs?\s*old|saal)\b"
    r"|\b(class|grade|std|standard)\s*(\d{1,2})\b|\b(\d{1,2})(st|nd|rd|th)\s+(class|grade|standard)\b"
)

# Hinglish signal tokens for language detection.
_HINGLISH_TOKENS = {
    "mujhe", "mera", "meri", "mere", "hai", "nahi", "nahin", "kya", "kaise", "raha", "rahi",
    "bahut", "ho", "rahi", "karna", "kar", "lag", "gaya", "gayi", "chahta", "chahti", "khud",
    "marna", "pati", "ghar", "dar", "pills", "goliyan", "sab", "khatam",
}

# ─────────────── Hybrid semantic/fuzzy recall anchors (spec §12, residual-risk) ───────────────
# The deterministic lexicon above is the SAFETY FLOOR. These short concept anchors feed a
# pure-stdlib fuzzy matcher (difflib) that catches novel phrasings, typos and romanization
# variants the exact lexicon misses. It can only RAISE the risk tier (never lower it), so a
# false-positive here is a safe over-escalation, and if it ever errors the deterministic
# result still stands. No ML deps → works offline / in CI.
_SEM_IMMINENT_ANCHORS = [
    "took pills", "taken pills", "swallowed pills", "swallowed tablets", "swallowed the tablets",
    "took overdose", "overdosed", "took poison", "drank poison", "drank bleach",
    "jump off", "jump from", "jumping off", "hang myself", "hanging myself",
    "end it tonight", "end it now", "kill myself now", "kill myself tonight",
    "slit my wrist", "cut my wrist now", "shoot myself",
    "goliyan kha li", "goliyan le li", "goliyaan le li", "zeher pi liya", "zeher kha liya",
    "chhat se kood", "phansi laga",
]
_SEM_HIGH_ANCHORS = [
    "want to die", "wanna die", "want to be dead", "kill myself", "end my life", "end it all",
    "no reason to live", "no point living", "dont want to live", "dont wanna live",
    "dont want to be alive", "dont wanna be alive", "dont want to be here", "never wake up",
    "better off dead", "take my own life", "want to disappear forever", "wanna disappear",
    "wanna vanish", "hurt myself", "harm myself", "cut myself",
    "marna chahta", "marna chahti", "jeena nahi chahta", "jeene ka mann nahi", "khatam kar dun",
    "khud ko nuksan", "khud ko nuqsaan", "khud ko marna", "khud ko hurt",
]
_SEM_MODERATE_ANCHORS = [
    "cant cope", "cannot cope", "hopeless", "cant take it anymore", "falling apart",
    "cant go on", "breaking down", "cant handle this", "cant keep going",
    "himmat nahi", "sambhal nahi", "tut gaya", "bahut pareshan",
]


# ─────────────────────────── Helpers ───────────────────────────
def _norm(text: str) -> str:
    """Lowercased text with apostrophe/whitespace normalized for substring matching."""
    t = (text or "").lower().replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(_norm(text))


def _any(text: str, phrases: List[str]) -> bool:
    return any(p in text for p in phrases)


def detect_language(text: str, hint: Optional[str] = None) -> str:
    if hint in ("en", "hi", "hinglish"):
        return hint
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi"
    if set(_tokens(text)) & _HINGLISH_TOKENS:
        return "hinglish"
    return "en"


def _fuzzy_phrase_span(msg_tokens: List[str], anchor: str,
                       thr: float = 0.82, min_frac: float = 0.85) -> int:
    """Return the start token index where `anchor` fuzzily matches, else -1.

    Every anchor token must find a near-match token (difflib ratio ≥ thr); at least
    min_frac of the anchor tokens must match (for the short anchors used here this means
    ALL of them, so the risk-bearing word — die/alive/pills — can't be dropped), and for
    multi-token anchors the matched positions must sit within a bounded window so
    scattered coincidental matches don't count. Pure stdlib — no external models.
    """
    a_tokens = anchor.split()
    if not a_tokens:
        return -1
    positions: List[int] = []
    for at in a_tokens:
        best, best_pos = 0.0, -1
        for i, mt in enumerate(msg_tokens):
            r = difflib.SequenceMatcher(None, at, mt).ratio()
            if r > best:
                best, best_pos = r, i
        if best >= thr:
            positions.append(best_pos)
    if len(positions) / len(a_tokens) < min_frac:
        return -1
    if len(a_tokens) > 1 and positions:
        if (max(positions) - min(positions)) > (2 * len(a_tokens) + 3):
            return -1
    return min(positions) if positions else -1


# Negations that FLIP the meaning of a self-harm/suicide phrase ("I do NOT want to
# die"). Deliberately excludes "can't" ("can't stay safe"/"can't go on" are real risk).
# NOTE: the word tokenizer splits apostrophe-contractions ("don't" -> "don","t"), so we
# include the leading contraction fragments (don/won/didn/doesn/...) as negation cues
# too — otherwise a windowed check would miss "I don't want to die".
_NEGATION_CUES = {
    "not", "dont", "didnt", "never", "wont", "no", "nahi", "nahin", "na", "nhi",
    "नहीं", "नही", "ना", "मत",
    # apostrophe-split contraction fragments (meaning-flipping; "can" excluded on purpose)
    "don", "won", "didn", "doesn", "isn", "wasn", "weren", "aren",
    "wouldn", "shouldn", "couldn", "hadn", "hasn", "haven", "ain",
}


def _negated_before(msg_tokens: List[str], start: int) -> bool:
    """True if a meaning-flipping negation sits in the 3 tokens before a match start.

    Only used to stop the UPGRADE-ONLY semantic layer from escalating clearly-negated
    statements. The deterministic lexicon is unaffected and remains the safety floor,
    so this can never lower a deterministic HIGH/IMMINENT result.
    """
    if start <= 0:
        return False
    return any(tok in _NEGATION_CUES for tok in msg_tokens[max(0, start - 3):start])


def _all_indices_of(msg_tokens: List[str], phrase_tokens: List[str]) -> List[int]:
    """Every start index where phrase_tokens occurs contiguously in msg_tokens."""
    n = len(phrase_tokens)
    if n == 0:
        return []
    return [i for i in range(len(msg_tokens) - n + 1)
            if msg_tokens[i:i + n] == phrase_tokens]


def _contains_unnegated(text: str, phrases: List[str]) -> bool:
    """True if ANY phrase appears in `text` in a position that is NOT immediately
    negated (windowed, 3 tokens before the match).

    This is what makes reassurance SCOPED instead of whole-message: a message like
    "I would never hurt myself, but now I'm about to hurt myself" still detects the
    unnegated "about to hurt myself" even though a reassurance phrase is present
    elsewhere. Conversely "I'm not going to hurt myself" is correctly treated as
    negated. Fail-safe: if a phrase is a substring but can't be token-aligned (odd
    punctuation), it is counted as present (over-detection is the safe direction).
    """
    toks = _tokens(text)
    for p in phrases:
        if p not in text:
            continue
        ptoks = _WORD_RE.findall(p.lower())
        if not ptoks:
            return True
        idxs = _all_indices_of(toks, ptoks)
        if not idxs:
            return True  # substring present but not token-aligned → fail safe
        if any(not _negated_before(toks, i) for i in idxs):
            return True
    return False


# Adversative / "turn" markers. Text after one of these can flip the meaning of an
# earlier clause: "I used to want to die BUT I'm fine now" (turn -> reassurance, safe)
# vs "I promise I'm fine BUT I want to die now" (turn -> danger, must NOT downgrade).
_ADVERSATIVE = {"but", "however", "though", "still", "yet",
                "lekin", "magar", "par", "phir", "fir", "pr",
                "लेकिन", "मगर", "पर", "फिर"}


def _danger_after_turn(text: str) -> bool:
    """True if an UNNEGATED present-danger phrase appears AFTER the last adversative
    marker. Used so a reassurance can only downgrade when it is the FINAL word on the
    matter — "…but I want to kill myself now" keeps its crisis tier despite an earlier
    reassurance."""
    toks = _tokens(text)
    turn_idx = -1
    for i, tk in enumerate(toks):
        if tk in _ADVERSATIVE:
            turn_idx = i
    if turn_idx < 0:
        return False
    tail = " ".join(toks[turn_idx + 1:])
    return (_contains_unnegated(tail, _SUICIDE_PHRASES)
            or _contains_unnegated(tail, _SELF_HARM_PHRASES)
            or _contains_unnegated(tail, _IMMINENT_SELFHARM_INTENT))


def _sem_hit(msg_tokens: List[str], anchor: str, thr: float, respect_negation: bool) -> bool:
    start = _fuzzy_phrase_span(msg_tokens, anchor, thr=thr)
    if start < 0:
        return False
    if respect_negation and _negated_before(msg_tokens, start):
        return False
    return True


def semantic_escalation(text: str, *, reassured: bool = False, grief: bool = False) -> str:
    """UPGRADE-ONLY fuzzy recall layer. Returns a proposed risk FLOOR to be combined
    with the deterministic result via max() — it can never downgrade.

    * IMMINENT act-in-progress anchors ignore reassurance (an overdose can't be
      "reassured away") but still respect an adjacent negation ("I did NOT take pills").
    * Suicidal/self-harm ideation anchors are capped at MODERATE when the message is
      explicitly reassured or is third-person grief, mirroring the deterministic guard.
    Safe by construction and dependency-free; callers wrap it so any failure is
    non-fatal and deterministic triage still runs.
    """
    toks = _tokens(text)[:120]  # bound work for long inputs
    if not toks:
        return UNKNOWN
    if any(_sem_hit(toks, a, 0.82, True) for a in _SEM_IMMINENT_ANCHORS):
        return IMMINENT
    level = UNKNOWN
    if any(_sem_hit(toks, a, 0.84, True) for a in _SEM_HIGH_ANCHORS):
        level = MODERATE if (reassured or grief) else HIGH
    if _RANK[level] < _RANK[MODERATE] and \
            any(_sem_hit(toks, a, 0.86, False) for a in _SEM_MODERATE_ANCHORS):
        level = MODERATE
    return level


def _is_first_person_grief(text: str) -> bool:
    """True when a suicide term appears only as third-person / past bereavement.

    e.g. 'my brother died by suicide' — grief, not the user's own current risk. We only
    treat it as grief when there is NO first-person self-referential ideation cue.
    """
    third = _any(text, ["my friend", "my brother", "my sister", "my father", "my mother",
                        "my mom", "my dad", "my uncle", "my cousin", "someone i", "my colleague",
                        "died by suicide", "passed away", "killed himself", "killed herself",
                        "took his own life", "took her own life", "lost him", "lost her"])
    first = _any(text, ["i want", "i wanna", "i wish i", "myself", "my life", "i don't want to be",
                        "i dont want to be", "i can't stay safe", "i feel like", "i am going to",
                        "i have a plan"])
    return third and not first


@dataclass
class MHTriage:
    """Deterministic understanding of a mental-health message (no diagnosis, no LLM)."""
    raw_message: str
    risk_level: str = UNKNOWN
    language: str = "en"
    signals: Dict[str, bool] = field(default_factory=dict)
    immediate_danger: bool = False
    needs_clarification: bool = False
    clarifying_question: Optional[str] = None
    minor_suspected: bool = False
    dosing_request: bool = False
    response_mode: str = MODE_NORMAL
    semantic_escalated: bool = False

    @property
    def crisis(self) -> bool:
        return self.risk_level in (HIGH, IMMINENT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "crisis": self.crisis,
            "language": self.language,
            "signals": dict(self.signals),
            "immediate_danger": self.immediate_danger,
            "needs_clarification": self.needs_clarification,
            "clarifying_question": self.clarifying_question,
            "minor_suspected": self.minor_suspected,
            "dosing_request": self.dosing_request,
            "response_mode": self.response_mode,
            "semantic_escalated": self.semantic_escalated,
            "triage_version": TRIAGE_VERSION,
        }


def _clarifying_question(language: str) -> str:
    if language == "hi":
        return ("मैं समझना चाहती हूँ ताकि सही मदद दे सकूँ — क्या आपके मन में खुद को "
                "नुकसान पहुँचाने के विचार आ रहे हैं?")
    if language == "hinglish":
        return ("Main samajhna chahti hoon taaki sahi madad de sakoon — kya aapke mann mein "
                "khud ko nuksan pahunchane ke vichaar aa rahe hain?")
    return ("I want to understand so I can help in the right way — are you having any "
            "thoughts of harming yourself or of not wanting to be here?")


def build_triage(message: str, language_hint: Optional[str] = None) -> MHTriage:
    """Classify a message into a conservative risk state + independent signals."""
    text = _norm(message)
    language = detect_language(message, language_hint)
    t = MHTriage(raw_message=(message or "").strip(), language=language)

    # ---- Signals (independent of the final state) ----
    sig = {
        "self_harm": _any(text, _SELF_HARM_PHRASES),
        "suicide": _any(text, _SUICIDE_PHRASES),
        "abuse": _any(text, _ABUSE_PHRASES),
        "violence": _any(text, _ACTIVE_VIOLENCE_PHRASES),
        "child_safety": _any(text, _CHILD_OWN_PHRASES),
        "medical_emergency": _any(text, _MEDICAL_PHRASES),
        "psychosis": _any(text, _PSYCHOSIS_PHRASES),
        "substance": _any(text, _SUBSTANCE_PHRASES),
    }
    t.minor_suspected = _detect_minor(text)
    t.dosing_request = _any(text, _SUBSTANCE_PHRASES) and _any(text, _DOSING_REQUEST)

    reassured = _any(text, _REASSURANCE)
    grief = _is_first_person_grief(text)
    # Reassurance is SCOPED: it only downgrades when it is the last word on the matter.
    # If a present-danger cue follows an adversative ("…but I want to die now"), the
    # reassurance no longer counts — a distant "I'm fine" can't mask a later disclosure.
    reassured_effective = reassured and not _danger_after_turn(text)

    # ---- State (conservative: highest applicable wins) ----
    level = UNKNOWN
    imminent_core = _any(text, _IMMINENT_PHRASES)
    # Self-harm INTENT is imminent when the intent phrase is present and NOT immediately
    # negated (windowed). A reassurance phrase elsewhere in the message can no longer
    # suppress a genuine, co-present intent — fixes
    # "I would never hurt myself, but now I'm about to hurt myself" (was capped MODERATE).
    imminent_intent = _contains_unnegated(text, _IMMINENT_SELFHARM_INTENT)
    imminent_hit = imminent_core or imminent_intent
    active_violence = sig["violence"] or _any(text, _ACTIVE_VIOLENCE_PHRASES)
    # Voices commanding harm → treat as imminent.
    command_harm = sig["psychosis"] and (sig["suicide"] or sig["self_harm"] or "hurt" in text)

    if imminent_hit or (sig["medical_emergency"] and (sig["suicide"] or sig["self_harm"] or "took" in text)) \
            or active_violence or command_harm:
        level = IMMINENT
        t.immediate_danger = True
    elif (sig["suicide"] or sig["self_harm"]) and not (reassured_effective or grief):
        level = HIGH
    elif _any(text, _MODERATE_PHRASES) or sig["psychosis"] or (sig["abuse"] and "threat" in text) \
            or ((sig["suicide"] or sig["self_harm"]) and (reassured_effective or grief)):
        level = MODERATE
    elif _any(text, _LOW_PHRASES) or sig["abuse"]:
        level = LOW
    else:
        level = UNKNOWN

    # Abuse with fear/threat but no active violence → at least MODERATE and worth a check-in.
    if sig["abuse"] and level in (UNKNOWN, LOW) and _any(text, ["threat", "scared", "afraid",
                                                                "डर", "dar", "धमकी", "dhamki"]):
        level = MODERATE

    # A child in severe distress is handled as a safety matter, not casual support.
    if sig["child_safety"] and (sig["suicide"] or sig["self_harm"] or "want to die" in text
                                or "hurt themsel" in text or "मरना" in text):
        level = max(level, HIGH, key=lambda s: _RANK[s])

    # ---- Hybrid semantic/fuzzy recall (UPGRADE-ONLY; never downgrades) ----
    # Runs AFTER the deterministic decision and can only raise the tier. Wrapped so a
    # failure here can never break the deterministic safety floor (spec: "if semantic
    # detection fails, deterministic triage must still work").
    try:
        sem = semantic_escalation(text, reassured=reassured_effective, grief=grief)
    except Exception:
        sem = UNKNOWN
    if _RANK[sem] > _RANK[level]:
        level = sem
        t.semantic_escalated = True
    if level == IMMINENT:
        t.immediate_danger = True

    t.risk_level = level
    t.signals = sig

    # ---- Clarification (spec §3: ambiguous → careful clarification) ----
    ambiguous = _any(text, ["can't keep doing this", "cant keep doing this", "how long i can keep",
                            "what's the point", "whats the point", "tired of everything",
                            "can't do this anymore", "cant do this anymore", "don't want to be here",
                            "sab khatam", "kuch samajh nahi"])
    if level == HIGH and reassured:
        # explicit reassurance already downgraded to MODERATE above
        pass
    if (level == MODERATE and (ambiguous or reassured)) or (level == HIGH and ambiguous
                                                            and not imminent_hit):
        t.needs_clarification = True
        t.clarifying_question = _clarifying_question(language)

    # ---- Response mode (length adaptation, spec §25) ----
    if level == IMMINENT:
        t.response_mode = MODE_EMERGENCY
    elif level == HIGH:
        t.response_mode = MODE_CRISIS
    elif level == MODERATE:
        t.response_mode = MODE_MODERATE
    else:
        t.response_mode = MODE_NORMAL
    return t


def _detect_minor(text: str) -> bool:
    for m in _MINOR_RE.finditer(text):
        for g in m.groups():
            if g and g.isdigit():
                n = int(g)
                if 4 <= n <= 17:
                    return True
    return False


def triage(message: str, language_hint: Optional[str] = None) -> Dict[str, Any]:
    """Public entrypoint: full deterministic triage as a plain dict."""
    return build_triage(message, language_hint).to_dict()

