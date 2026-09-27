"""Individual authority credential store & verification (P1-7).

Replaces the previous SHARED authority password. Each authority officer now has
an individually identifiable server-side record; login verifies the submitted
password against that record's PBKDF2 hash and the authenticated identity
(authority_id / badge_number / officer_name / role) is read from the record — it
is NEVER taken from client-supplied request-body fields.

Storage: MongoDB collection `authority_accounts` when a database is available.
When Mongo is not connected (local dev / CI), an in-process dictionary is used so
login still works; the same secure hashing path is used in both cases.

Password hashing reuses the project's PBKDF2 primitive (auth.hash_password) and
additionally applies AUTHORITY_SECRET_KEY as a server-side PEPPER, so a database
leak alone is insufficient to mount an offline attack. This is the ongoing role
of AUTHORITY_SECRET_KEY after it is retired as a shared login credential.
"""
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from auth import hash_password, verify_password, AUTHORITY_SECRET_KEY, IS_PRODUCTION
from services.db import authority_accounts

logger = logging.getLogger("haven_backend")

# Canonical authorization roles recognised across HAVEN (matches the values used
# by require_authority/require_admin and create_access_token). "user" is the
# unprivileged default; the rest are elevated. Used for role-change validation.
CANONICAL_ROLES = ("user", "authority", "admin", "police", "protection_officer")

# In-memory fallback store used only when Mongo is unavailable. Keyed by badge_number.
_memory_store: Dict[str, Dict[str, Any]] = {}
_dev_seeded = False


def _peppered(password: str) -> str:
    """Bind the password to the server-side secret (pepper) before hashing.

    The pepper lives in configuration, not the database, so leaked hashes cannot
    be attacked offline without also compromising AUTHORITY_SECRET_KEY.
    """
    return f"{AUTHORITY_SECRET_KEY}\x1f{password}"


def _normalize_badge(badge: Optional[str]) -> str:
    return (badge or "").strip()


def _find(badge: str) -> Optional[Dict[str, Any]]:
    coll = authority_accounts()
    if coll is not None:
        return coll.find_one({"badge_number": badge})
    return _memory_store.get(badge)


def get_authority(badge_number: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch an authority record by its badge number (the login username)."""
    badge = _normalize_badge(badge_number)
    if not badge:
        return None
    return _find(badge)


def create_authority(
    badge_number: str,
    officer_name: str,
    password: str,
    role: str = "authority",
    active: bool = True,
) -> Dict[str, Any]:
    """Create (or overwrite) an individual authority account with a hashed password.

    This is the minimal secure provisioning path. It does NOT expose an HTTP
    endpoint — accounts are provisioned by an operator/admin via a script or a
    one-off call (see README). Passwords are never stored in plaintext.
    """
    badge = _normalize_badge(badge_number)
    if not badge:
        raise ValueError("badge_number required")
    # Reject empty passwords explicitly: peppering would otherwise produce a
    # non-empty string and slip past hash_password's own empty-string guard,
    # leaving an account that is loginnable with an empty password.
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    if role not in ("authority", "police", "protection_officer", "admin"):
        raise ValueError("invalid authority role")
    digest = hash_password(_peppered(password))
    now = datetime.utcnow()
    coll = authority_accounts()
    existing = _find(badge)
    record = {
        "authority_id": (existing or {}).get("authority_id") or f"AUTH-{badge}",
        "badge_number": badge,
        "officer_name": officer_name or "Protection Officer",
        "password_hash": digest["hash"],
        "password_salt": digest["salt"],
        "role": role,
        "active": bool(active),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    if coll is not None:
        coll.update_one({"badge_number": badge}, {"$set": record}, upsert=True)
    else:
        _memory_store[badge] = record
    return record


def set_active(badge_number: str, active: bool) -> bool:
    """Activate/deactivate an authority account. Returns True if a record changed."""
    badge = _normalize_badge(badge_number)
    rec = _find(badge)
    if not rec:
        return False
    coll = authority_accounts()
    if coll is not None:
        coll.update_one({"badge_number": badge},
                        {"$set": {"active": bool(active), "updated_at": datetime.utcnow()}})
    else:
        rec["active"] = bool(active)
        rec["updated_at"] = datetime.utcnow()
    return True


def authenticate_authority(
    badge_number: Optional[str], password: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify individual authority credentials against the server-side record.

    Returns (record, error). error is one of:
      None          -> success (record is the verified authority account)
      'not_found'    -> no such badge (map to 401)
      'bad_password' -> password mismatch (map to 401 — same message as not_found)
      'inactive'     -> valid password but account disabled (map to 403)

    Password is checked BEFORE the active flag so account existence is not
    revealed to someone who does not already hold the correct password.
    """
    rec = get_authority(badge_number)
    if not rec:
        return None, "not_found"
    if not verify_password(_peppered(password or ""),
                           rec.get("password_hash", ""), rec.get("password_salt", "")):
        return None, "bad_password"
    if not rec.get("active", True):
        return None, "inactive"
    return rec, None


def ensure_dev_authority() -> None:
    """Non-production convenience: seed ONE local dev authority so dev/CI works.

    Never runs in production (IS_PRODUCTION). In production, individual authority
    accounts MUST be provisioned explicitly (see README). This does NOT create a
    universal/shared production password.
    """
    global _dev_seeded
    if IS_PRODUCTION or _dev_seeded:
        return
    badge = os.getenv("DEV_AUTHORITY_BADGE", "PO-1091")
    if get_authority(badge) is None:
        create_authority(
            badge_number=badge,
            officer_name=os.getenv("DEV_AUTHORITY_NAME", "Duty Protection Officer"),
            password=os.getenv("DEV_AUTHORITY_PASSWORD", "haven2024"),
            role="authority",
            active=True,
        )
        logger.info("Seeded development authority account (non-production only).")
    _dev_seeded = True


def _find_by_identity(identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve an authority record by authority_id (preferred) or badge_number.

    The token embeds authority_id (e.g. 'AUTH-PO-1091') as user_id, while records
    are keyed by badge_number, so admin tooling may pass either form.
    """
    ident = (identity or "").strip()
    if not ident:
        return None
    coll = authority_accounts()
    if coll is not None:
        return coll.find_one({"authority_id": ident}) or coll.find_one({"badge_number": ident})
    for rec in _memory_store.values():
        if rec.get("authority_id") == ident or rec.get("badge_number") == ident:
            return rec
    return None


def get_authority_by_id(identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Public lookup used by admin role management (by authority_id or badge)."""
    return _find_by_identity(identity)


def set_role(identity: Optional[str], new_role: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Persist a role change on an EXISTING authority identity (P1-8).

    Returns (record, error). error is one of:
      None         -> success (record is the updated authority account)
      'bad_role'   -> role not in CANONICAL_ROLES (map to 400)
      'not_found'  -> no matching identity (map to 404)

    Updates ONLY the `role` (and `updated_at`) field via an atomic $set targeting
    exactly the resolved identity. It never upserts, so an unknown identity cannot
    accidentally create a new account, and no unrelated fields are touched.
    """
    if not isinstance(new_role, str) or new_role not in CANONICAL_ROLES:
        return None, "bad_role"
    rec = _find_by_identity(identity)
    if not rec:
        return None, "not_found"
    aid = rec.get("authority_id")
    now = datetime.utcnow()
    coll = authority_accounts()
    if coll is not None:
        coll.update_one({"authority_id": aid}, {"$set": {"role": new_role, "updated_at": now}})
        updated = coll.find_one({"authority_id": aid})
    else:
        rec["role"] = new_role
        rec["updated_at"] = now
        updated = rec
    return updated, None
