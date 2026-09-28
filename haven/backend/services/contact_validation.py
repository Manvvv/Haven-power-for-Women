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
