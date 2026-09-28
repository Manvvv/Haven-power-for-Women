"""
Text preprocessing shared by every risk-classification backend.

Pure standard library — no third-party dependencies — so the rule-based tier
works out of the box. The sklearn and transformer backends reuse `clean_text`
so training and inference see identically normalised input.
"""
import re
import unicodedata

# Canonical severity vocabulary used across the whole platform.
SEVERITY_LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]

# Ordinal mapping — handy for numeric comparisons / escalation logic.
SEVERITY_ORDER = {level: i for i, level in enumerate(SEVERITY_LEVELS)}

# Indicator vocabulary (matches services.risk_classifier.RiskClassifier.INDICATORS).
INDICATORS = [
    "physical_assault",
    "threat",
    "confinement",
    "stalking",
    "immediate_danger",
    "repeated_abuse",
    "emergency_assistance_request",
]

# Very small, safe leet / obfuscation map. Covert SOS messages are sometimes
# typed under stress, so we normalise a few common substitutions.
#   * @ -> a and $ -> s are always safe (never part of a bare number).
#   * digit substitutions (0->o, 1->i, ...) are applied ONLY inside tokens that
#     also contain letters ("k1ll" -> "kill", "h3lp" -> "help"). Standalone
#     numbers are left intact so emergency numbers like "call 100" / "911" /
#     "112" survive and still match the emergency-plea patterns.
_LEET_SYMBOL = str.maketrans({"@": "a", "$": "s"})
_LEET_DIGIT = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
_ALNUM_TOKEN = re.compile(r"[0-9a-z]+")

_WHITESPACE = re.compile(r"\s+")
_REPEAT = re.compile(r"(.)\1{2,}")  # collapse "heeeelp" -> "heelp"


def _deleet(text: str) -> str:
    """De-obfuscate leetspeak without corrupting bare numbers."""
    text = text.translate(_LEET_SYMBOL)

    def _repl(m: "re.Match") -> str:
        tok = m.group(0)
        # Only substitute digits when the token also contains letters.
        if any(c.isalpha() for c in tok):
            return tok.translate(_LEET_DIGIT)
        return tok  # pure number (100, 911, 112, dates, room numbers) — keep as-is

    return _ALNUM_TOKEN.sub(_repl, text)


def clean_text(text: str) -> str:
    """
    Normalise a distress message for classification.

    - unicode NFKC normalisation
    - lowercase
    - light leet-speak de-obfuscation (letters only; bare numbers preserved)
    - collapse 3+ repeated chars and runs of whitespace

    Deliberately conservative: we do NOT strip punctuation or stopwords here,
    because negations ("not safe", "no danger") and punctuation ("help!!!")
    carry signal for this task.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.lower()
    text = _deleet(text)
    text = _REPEAT.sub(r"\1\1", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def tokenize(text: str) -> list:
    """Simple word tokenizer over cleaned text (used by the rule scorer)."""
    return re.findall(r"[a-z']+", clean_text(text))
