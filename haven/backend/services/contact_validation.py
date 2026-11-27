"""
Pure, dependency-free validation helpers for trusted emergency contacts.

Extracted from voice_routes so the rules can be unit-tested in a sandbox without
importing FastAPI / PyMongo (which pull in the whole app). These functions never
touch the database or the network — they only decide whether a submitted contact
field is acceptable and provide a normalized key for duplicate detection.
"""
import re

MAX_TRUSTED_CONTACTS = 5

# Deliberately conservative e-mail shape check (not RFC-complete): a single @,
# no whitespace, and a dotted domain. Enough to reject obvious garbage without
# rejecting valid addresses.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone(raw: str) -> str:
    """Digits-only key used for duplicate detection (drops spaces, +, dashes)."""
    return re.sub(r"\D", "", raw or "")


def valid_phone(raw: str) -> bool:
    """Server-side phone sanity check.

    Accepts a 10-digit Indian mobile (leading 6-9) or an 11-15 digit number
    carrying a country code. Rejects empty / too-short / letter-only input rather
    than trusting the client.
    """
    d = normalize_phone(raw)
    return (len(d) == 10 and d[0] in "6789") or (11 <= len(d) <= 15)


def valid_email(raw: str) -> bool:
    """True if `raw` is empty (email is optional) or a plausibly-valid address."""
    raw = (raw or "").strip()
    return raw == "" or bool(EMAIL_RE.match(raw))


ALLOWED_RELATIONSHIPS = (
    "family",
    "parent",
    "sibling",
    "spouse_partner",
    "friend",
    "colleague",
    "neighbor",
    "counselor",
    "other",
)


def normalize_relationship(raw: str) -> str:
    """Normalize a contact relationship string into a safe canonical label."""
    cleaned = re.sub(r"[^a-z0-9_\s/-]", "", (raw or "").strip().lower()).replace(" ", "_")
    if not cleaned:
        return "other"
    if cleaned in ALLOWED_RELATIONSHIPS:
        return cleaned
    return cleaned[:40]


def clamp_priority(raw, default: int = 1) -> int:
    """Clamp contact priority into [1, 5] safely."""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(5, val))
