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
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

_WHITESPACE = re.compile(r"\s+")
_REPEAT = re.compile(r"(.)\1{2,}")  # collapse "heeeelp" -> "heelp"


def clean_text(text: str) -> str:
    """
    Normalise a distress message for classification.

    - unicode NFKC normalisation
    - lowercase
    - light leet-speak de-obfuscation
    - collapse 3+ repeated chars and runs of whitespace

    Deliberately conservative: we do NOT strip punctuation or stopwords here,
    because negations ("not safe", "no danger") and punctuation ("help!!!")
    carry signal for this task.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.lower()
    text = text.translate(_LEET)
    text = _REPEAT.sub(r"\1\1", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def tokenize(text: str) -> list:
    """Simple word tokenizer over cleaned text (used by the rule scorer)."""
    return re.findall(r"[a-z']+", clean_text(text))
