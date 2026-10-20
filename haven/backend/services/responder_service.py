"""Field-responder credential store & verification (Rapid Response Network).

Responders are the people/units that physically respond to a HAVEN incident after
an AUTHORITY has made a human-approved dispatch decision. They are a SEPARATE
identity population from authorities/admins and intentionally do NOT inherit any
authority/admin RBAC — a responder token can only reach the /responder/* surface.

This module mirrors services.authority_service exactly in security posture:
  * Passwords are hashed with the project PBKDF2 primitive (auth.hash_password)
    and additionally peppered with a server-side secret, so a database leak alone
    cannot be attacked offline.
  * The authenticated identity (responder_id / display_label / role) is read from
    the server-side record — NEVER from client-supplied request-body fields, so a
    client cannot spoof who they are or what role/label they hold.
  * Storage is MongoDB collection `responders` when a DB is available, with an
    in-process dict fallback for local dev / CI using the identical hashing path.

Pepper: RESPONDER_SECRET_KEY when configured, otherwise AUTHORITY_SECRET_KEY.
Falling back avoids introducing a NEW production-required secret (the production
config validator does not list RESPONDER_SECRET_KEY), while still binding every
responder password to a server-side secret.

Approval gate: responders are provisioned with verified=False and OFFLINE. An
admin must approve them (verified=True) through the trusted admin workflow before
they can ever be offered or claim a dispatch. Verification is enforced again in
the dispatch eligibility query and in the atomic accept claim, not just at login.
"""
import os
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

from auth import hash_password, verify_password, AUTHORITY_SECRET_KEY, IS_PRODUCTION
from services.db import responders

logger = logging.getLogger("haven_backend")

# Server-side pepper. Prefer a dedicated secret but fall back to the authority
# pepper so no new production-required secret is introduced.
RESPONDER_SECRET_KEY = os.getenv("RESPONDER_SECRET_KEY") or AUTHORITY_SECRET_KEY

# Operational availability states. BUSY is server-controlled: it is set ONLY by a
# successful atomic dispatch claim and cleared on release — a responder can never
# set BUSY on themselves (that would let a unit dodge offers while appearing on
# duty). The self-settable states are the SELF_SETTABLE_STATUSES subset below.
RESPONDER_STATUSES = ("OFFLINE", "AVAILABLE", "BUSY", "UNAVAILABLE")
SELF_SETTABLE_STATUSES = ("OFFLINE", "AVAILABLE", "UNAVAILABLE")

# Duty is a SEPARATE axis from operational status. ON_DUTY means the provider has
# declared operational availability and (once they opt in) shares location. It does
# NOT by itself make a unit dispatchable: eligibility additionally requires
# status == AVAILABLE, no live assignment, and a FRESH location fix.
DUTY_OFF, DUTY_ON = "OFF_DUTY", "ON_DUTY"
DUTY_STATUSES = (DUTY_OFF, DUTY_ON)

# Provider categories (§5 — only categories appropriate to the current application).
PROVIDER_CATEGORIES = (
    "police",
    "women_safety_unit",
    "ngo_response",
    "shelter_response",
    "medical_partner",
    "other_authorized",
)
# Human labels for the same categories (used in UI/API).
PROVIDER_CATEGORY_LABELS: dict = {
    "police": "Police",
    "women_safety_unit": "Women Safety Unit",
    "ngo_response": "NGO Response Team",
    "shelter_response": "Shelter Response Team",
    "medical_partner": "Medical Response Partner",
    "other_authorized": "Other Authorized Provider",
}

# In-memory fallback store used only when Mongo is unavailable. Keyed by badge_number.
_memory_store: Dict[str, Dict[str, Any]] = {}
_dev_seeded = False


def _peppered(password: str) -> str:
    """Bind the password to the server-side secret (pepper) before hashing."""
    return f"{RESPONDER_SECRET_KEY}\x1f{password}"


def _normalize_badge(badge: Optional[str]) -> str:
    return (badge or "").strip()


def _find(badge: str) -> Optional[Dict[str, Any]]:
    coll = responders()
    if coll is not None:
        return coll.find_one({"badge_number": badge})
    return _memory_store.get(badge)


def get_responder(badge_number: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch a responder record by its badge number (the login username)."""
    badge = _normalize_badge(badge_number)
    if not badge:
        return None
    return _find(badge)


def _find_by_identity(identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve a responder record by responder_id (preferred) or badge_number.

    The token embeds responder_id (e.g. 'RESP-HN-204') as user_id, while records
    are keyed by badge_number, so callers may pass either form.
    """
    ident = (identity or "").strip()
    if not ident:
        return None
    coll = responders()
    if coll is not None:
        return coll.find_one({"responder_id": ident}) or coll.find_one({"badge_number": ident})
    for rec in _memory_store.values():
        if rec.get("responder_id") == ident or rec.get("badge_number") == ident:
            return rec
    return None


def get_responder_by_id(identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Public lookup by responder_id (preferred) or badge_number."""
    return _find_by_identity(identity)


def _normalize_category(cat: Optional[str]) -> Optional[str]:
    if not cat:
        return None
    c = str(cat).strip().lower()
    if c in PROVIDER_CATEGORIES:
        return c
    # Allow label form like "Police" -> "police"
    c2 = c.replace(" ", "_").replace("-", "_")
    if c2 in PROVIDER_CATEGORIES:
        return c2
    return None


def create_responder(
    badge_number: str,
    officer_name: str,
    password: str,
    display_label: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    jurisdiction: Optional[str] = None,
    active: bool = True,
    provider_category: Optional[str] = None,
    organization: Optional[str] = None,
    station_unit: Optional[str] = None,
    contact: Optional[str] = None,
) -> Dict[str, Any]:
    """Create (or overwrite) an individual responder account with a hashed password.

    Provisioned with verified=False and status=OFFLINE: a newly created responder
    is INERT until an admin verifies it.

    display_label is the ONLY identity string ever shown to a victim; it must be a
    safe, non-PII unit label (e.g. "Verified Response Unit HN-204"). officer_name
    is retained for internal/authority/admin audit use only.
    provider_category/organization/station_unit are operational metadata (authority
    view only, never victim PII). Contact is stored minimal and never exposed to
    victims.
    """
    badge = _normalize_badge(badge_number)
    if not badge:
        raise ValueError("badge_number required")
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    digest = hash_password(_peppered(password))
    now = datetime.utcnow()
    coll = responders()
    existing = _find(badge)
    caps = [str(c).strip().lower() for c in (capabilities or []) if str(c).strip()]
    cat = _normalize_category(provider_category) or (existing or {}).get("provider_category") or "police"
    if cat not in PROVIDER_CATEGORIES:
        cat = "police"
    record = {
        "responder_id": (existing or {}).get("responder_id") or f"RESP-{badge}",
        "badge_number": badge,
        "officer_name": officer_name or "Response Unit",
        "display_label": display_label or (existing or {}).get("display_label") or f"Verified Response Unit {badge}",
        "password_hash": digest["hash"],
        "password_salt": digest["salt"],
        "role": "responder",
        "active": bool(active),
        "verified": (existing or {}).get("verified", False),
        "status": (existing or {}).get("status") or "OFFLINE",
        "capabilities": caps or (existing or {}).get("capabilities") or [],
        "jurisdiction": (jurisdiction or (existing or {}).get("jurisdiction") or "").strip(),
        "provider_category": cat,
        "organization": (organization or (existing or {}).get("organization") or "").strip()[:120],
        "station_unit": (station_unit or (existing or {}).get("station_unit") or "").strip()[:120],
        "contact": (contact or (existing or {}).get("contact") or "").strip()[:120],
        "current_location": (existing or {}).get("current_location"),
        "location_updated_at": (existing or {}).get("location_updated_at"),
        "assigned_dispatch_id": (existing or {}).get("assigned_dispatch_id"),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    if coll is not None:
        coll.update_one({"badge_number": badge}, {"$set": record}, upsert=True)
    else:
        _memory_store[badge] = record
    return record


def create_responder_inert(
    badge_number: str,
    officer_name: str,
    display_label: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    jurisdiction: Optional[str] = None,
    provider_category: Optional[str] = None,
    organization: Optional[str] = None,
    station_unit: Optional[str] = None,
    contact: Optional[str] = None,
    active: bool = True,
) -> Dict[str, Any]:
    """Create an INERT responder record WITHOUT a password (setup token required).

    Used by the admin HTTP provisioning flow: the record is created with a random
    unusable password hash and verified=False/OFFLINE, and a single-use setup token
    is issued for the provider to set their real password. Direct login is impossible
    until the token is consumed.
    """
    import secrets as _secrets
    import hashlib as _hashlib
    # Random unusable password — login will always fail until setup completes.
    fake_pw = _secrets.token_urlsafe(32)
    return create_responder(
        badge_number=badge_number,
        officer_name=officer_name,
        password=fake_pw,
        display_label=display_label,
        capabilities=capabilities,
        jurisdiction=jurisdiction,
        active=active,
        provider_category=provider_category,
        organization=organization,
        station_unit=station_unit,
        contact=contact,
    )


def mark_password_unset(responder_id: Optional[str]) -> None:
    """Flag that the provider has NOT yet set their own password (PROVIDER_CREATED)."""
    rec = _find_by_identity(responder_id)
    if rec:
        _persist(rec, {"password_set": False})


def _persist(rec: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Atomic $set of `fields` on an EXISTING responder, keyed by responder_id.

    Never upserts, so an unknown identity cannot accidentally create an account,
    and only the named fields (plus updated_at) are touched. Returns the updated
    record (re-read from the DB when connected, else the mutated memory record).
    """
    rid = rec.get("responder_id")
    patch = dict(fields)
    patch["updated_at"] = datetime.utcnow()
    coll = responders()
    if coll is not None:
        coll.update_one({"responder_id": rid}, {"$set": patch})
        return coll.find_one({"responder_id": rid}) or rec
    rec.update(patch)
    return rec


def set_active(identity: str, active: bool) -> bool:
    """Activate/deactivate a responder account. Returns True if a record matched."""
    rec = _find_by_identity(identity)
    if not rec:
        return False
    _persist(rec, {"active": bool(active)})
    return True


def set_verified(identity: str, verified: bool) -> Optional[Dict[str, Any]]:
    """Admin approval gate: flip the verified flag. Returns the updated record or None.

    When un-verifying (verified=False) an on-duty unit, also force it OFFLINE so a
    revoked responder cannot linger as AVAILABLE in the eligibility query. An
    assigned unit is left untouched here; release happens through dispatch flow.
    """
    rec = _find_by_identity(identity)
    if not rec:
        return None
    fields: Dict[str, Any] = {"verified": bool(verified)}
    if not verified and not rec.get("assigned_dispatch_id") and rec.get("status") != "BUSY":
        fields["status"] = "OFFLINE"
    return _persist(rec, fields)


def set_self_status(responder_id: str, status: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Responder sets their OWN availability. Returns (record, error).

    error is one of:
      None            -> success
      'not_found'     -> no such responder
      'bad_status'    -> status not self-settable (BUSY/unknown are rejected here)
      'assigned'      -> cannot change availability while holding a live dispatch

    BUSY is intentionally NOT self-settable (server-controlled). A responder that
    is currently assigned must complete/leave the dispatch flow before toggling
    availability, so they cannot silently abandon an accepted incident.
    """
    rec = _find_by_identity(responder_id)
    if not rec:
        return None, "not_found"
    want = (status or "").strip().upper()
    if want not in ("OFFLINE", "AVAILABLE", "UNAVAILABLE"):
        return None, "bad_status"
    if not rec.get("active", True):
        return None, "inactive"
    if rec.get("assigned_dispatch_id"):
        return None, "assigned"
    updated = _persist(rec, {"status": want})
    return updated, None


def set_duty(responder_id: str, duty: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Responder goes ON_DUTY / OFF_DUTY. Returns (record, error).

    error: None | 'not_found' | 'bad_duty' | 'assigned' | 'inactive'.

    Going OFF_DUTY is always permitted EXCEPT while holding a live assignment (the
    unit must complete or be released from the dispatch first). OFF_DUTY also resets
    operational status to OFFLINE and clears the stored location, so no operational
    fix lingers after the unit stops sharing. Going ON_DUTY only sets the duty flag;
    the unit becomes dispatchable once it is also AVAILABLE with a fresh fix.
    """
    rec = _find_by_identity(responder_id)
    if not rec:
        return None, "not_found"
    want = (duty or "").strip().upper()
    if want not in DUTY_STATUSES:
        return None, "bad_duty"
    if want == DUTY_ON and not rec.get("active", True):
        return None, "inactive"
    if rec.get("assigned_dispatch_id") and want == DUTY_OFF:
        return None, "assigned"
    if want == DUTY_ON:
        fields: Dict[str, Any] = {"duty_status": DUTY_ON}
    else:
        # Off duty: stop operational tracking AND drop the push subscription so no
        # further offers are pushed to a unit that has stopped sharing.
        fields = {"duty_status": DUTY_OFF, "status": "OFFLINE",
                  "current_location": None, "location_updated_at": None,
                  "push_subscription": None, "push_subscribed_at": None}
    return _persist(rec, fields), None


# ── Single-use provider setup tokens ─────────────────────────────────────────────
# A newly provisioned provider receives a random, short-lived, single-use token that
# lets THEM set their own password. Only a SHA-256 digest is stored, the token is
# returned exactly once (to the admin, for out-of-band hand-off), and consuming it
# marks it used. No shared default password is ever created.
SETUP_TOKEN_TTL_SECONDS = 24 * 3600
_setup_tokens_memory: Dict[str, Dict[str, Any]] = {}


def _token_digest(token: str) -> str:
    import hashlib as _h
    return _h.sha256((token or "").encode("utf-8")).hexdigest()


class SetupStoreUnavailable(RuntimeError):
    """Raised in production when the durable token store is not reachable (fail closed)."""


def issue_setup_token(responder_id: str) -> str:
    """Create a fresh single-use setup token for a responder. Returns the plaintext
    token ONCE; only its digest is persisted. Replaces any earlier outstanding token.

    In production the durable Mongo store is REQUIRED; process memory is never used
    for trusted credential material there (fail closed)."""
    import secrets as _secrets
    from auth import IS_PRODUCTION as _PROD
    if _PROD and _setup_tokens_collection() is None:
        raise SetupStoreUnavailable("responder_setup_tokens store unavailable")
    token = _secrets.token_urlsafe(32)
    now = datetime.utcnow()
    doc = {
        "token_hash": _token_digest(token),
        "responder_id": responder_id,
        "issued_at": now,
        "expires_at": now + timedelta(seconds=SETUP_TOKEN_TTL_SECONDS),
        "used": False,
    }
    tokens_coll = _setup_tokens_collection()
    if tokens_coll is not None:
        # Supersede any earlier outstanding token for this responder.
        tokens_coll.update_many({"responder_id": responder_id, "used": False},
                                {"$set": {"used": True, "invalidated": True}})
        tokens_coll.insert_one(doc)
    else:
        for v in _setup_tokens_memory.values():
            if v.get("responder_id") == responder_id:
                v["used"] = True
        _setup_tokens_memory[doc["token_hash"]] = doc
    return token


def _setup_tokens_collection():
    try:
        from services.db import responder_setup_tokens
        return responder_setup_tokens()
    except Exception:
        return None


def consume_setup_token(token: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Atomically consume a setup token and set the provider's password.

    error: None | 'invalid' | 'expired' | 'used' | 'weak_password'. The single-use
    claim is a conditional update (used:False -> True), so a token can be redeemed
    by exactly one caller even under concurrency.
    """
    if not isinstance(password, str) or len(password) < 12:
        return None, "weak_password"
    digest = _token_digest(token)
    now = datetime.utcnow()
    tokens_coll = _setup_tokens_collection()

    # 1. Read the token state first so expiry/invalidation are reported honestly.
    if tokens_coll is not None:
        peek = tokens_coll.find_one({"token_hash": digest})
    else:
        peek = _setup_tokens_memory.get(digest)
        peek = dict(peek) if peek else None
    if not peek:
        return None, "invalid"
    if peek.get("used"):
        return None, "used"
    if peek.get("expires_at") and peek["expires_at"] < now:
        return None, "expired"

    # 2. Atomic single-use claim: exactly one caller can flip used False -> True.
    if tokens_coll is not None:
        claimed = tokens_coll.find_one_and_update(
            {"token_hash": digest, "used": False},
            {"$set": {"used": True, "used_at": now}})
        if not claimed:
            return None, "used"
    else:
        with _claim_lock:
            live = _setup_tokens_memory.get(digest)
            if not live or live.get("used"):
                return None, "used"
            live["used"] = True
            live["used_at"] = now

    # 3. Set the password on the bound responder record.
    rec = _find_by_identity(peek.get("responder_id"))
    if not rec:
        return None, "invalid"
    digest_pw = hash_password(_peppered(password))
    updated = _persist(rec, {"password_hash": digest_pw["hash"], "password_salt": digest_pw["salt"],
                             "password_set": True})
    return updated, None


def provisioning_state(rec: Dict[str, Any]) -> str:
    """Honest lifecycle label derived ONLY from stored flags (never trusted from clients).

    PROVIDER_CREATED       record exists, password/setup not yet completed
    VERIFICATION_PENDING   set-up complete but not admin-verified
    VERIFIED               admin-verified, account active, not yet on duty
    ACTIVE                 verified + active + on duty
    SUSPENDED              deactivated (active == False) after provisioning
    """
    if not rec:
        return "UNKNOWN"
    if not rec.get("active", False):
        return "SUSPENDED"
    if not rec.get("password_set", True):
        return "PROVIDER_CREATED"
    if not rec.get("verified", False):
        return "VERIFICATION_PENDING"
    if is_on_duty(rec):
        return "ACTIVE"
    return "VERIFIED"


def set_push_subscription(responder_id: str, subscription: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Store (or clear, when subscription is None) the responder's Web Push subscription.

    Stored on the responder's own record. The endpoint is kept (it is needed to send)
    and a sha256 digest is stored alongside for dedupe/audit. Never returned to any
    client. Cleared automatically on OFF_DUTY.
    """
    rec = _find_by_identity(responder_id)
    if not rec:
        return None
    if subscription is None:
        fields: Dict[str, Any] = {"push_subscription": None, "push_subscribed_at": None}
    else:
        import hashlib as _hashlib
        ep = subscription["endpoint"]
        fields = {
            "push_subscription": subscription,
            "push_endpoint_hash": _hashlib.sha256(ep.encode("utf-8")).hexdigest(),
            "push_subscribed_at": datetime.utcnow(),
        }
    return _persist(rec, fields)


def get_push_subscription(responder_id: str) -> Optional[Dict[str, Any]]:
    """Server-side read used ONLY by the notification sender (never sent to clients)."""
    rec = _find_by_identity(responder_id)
    return (rec or {}).get("push_subscription") or None


def is_on_duty(rec: Dict[str, Any]) -> bool:
    """True when a record has declared ON_DUTY. Missing field => OFF_DUTY (fail-closed)."""
    return (rec or {}).get("duty_status") == DUTY_ON


FIX_CLOCK_SKEW_SECONDS = 30  # tolerated device-ahead-of-server skew (matches frontend)


def update_location(
    responder_id: str, longitude: float, latitude: float, accuracy: Optional[float] = None,
    fix_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a responder's own live GPS fix as GeoJSON Point [lng, lat].

    Coordinates must already be validated/finite by the caller (geo_validation).
    Stored for 2dsphere eligibility and freshness; accuracy is echoed only when
    the device genuinely supplied it (never fabricated).

    Time semantics:
      * fix_time is the device's GPS time when supplied. It is used only if it is not
        in the future beyond FIX_CLOCK_SKEW_SECONDS; otherwise the write is refused
        (returns the unchanged record and sets 'fix_rejected' in the return dict).
      * Without fix_time the arrival time is used (legacy behaviour).
      * OUT-OF-ORDER GUARD: a fix older than the currently stored fix is SUPERSEDED.
        The stored position is not replaced, so a delayed packet cannot move a unit
        backwards or make an old position look current.
    """
    rec = _find_by_identity(responder_id)
    if not rec:
        return None
    now = datetime.utcnow()
    stamp = now
    if fix_time is not None:
        if fix_time.tzinfo is not None:
            fix_time = fix_time.astimezone(timezone.utc).replace(tzinfo=None)
        if (fix_time - now).total_seconds() > FIX_CLOCK_SKEW_SECONDS:
            out = dict(rec)
            out["fix_rejected"] = "future_timestamp"
            return out
        stamp = fix_time
    current_ts = rec.get("location_updated_at")
    if isinstance(current_ts, datetime) and stamp < current_ts:
        out = dict(rec)
        out["fix_superseded"] = True
        return out
    fields: Dict[str, Any] = {
        "current_location": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
        "location_updated_at": stamp,
    }
    if accuracy is not None:
        fields["location_accuracy"] = float(accuracy)
    return _persist(rec, fields)


def authenticate_responder(
    badge_number: Optional[str], password: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify responder credentials against the server-side record.

    Returns (record, error). error is one of:
      None           -> success (record is the verified responder account)
      'not_found'    -> no such badge (map to 401)
      'bad_password' -> password mismatch (map to 401 — same message as not_found)
      'inactive'     -> valid password but account disabled (map to 403)

    Password is checked BEFORE the active flag so account existence is not revealed
    to someone who does not already hold the correct password. Login succeeds for
    an unverified-but-active account (so the unit can see "pending approval"); the
    verified gate is enforced where it matters — eligibility and the accept claim —
    so an unverified unit can never actually be offered or claim an incident.
    """
    rec = get_responder(badge_number)
    if not rec:
        return None, "not_found"
    if rec.get("password_set") is False:
        # Provisioned but the provider has not redeemed their setup token yet. The
        # random placeholder hash is unusable, so report the same uniform 401.
        return None, "bad_password"
    if not verify_password(_peppered(password or ""),
                           rec.get("password_hash", ""), rec.get("password_salt", "")):
        return None, "bad_password"
    if not rec.get("active", True):
        return None, "inactive"
    return rec, None


def list_responders() -> List[Dict[str, Any]]:
    """Return all responder records (admin management view)."""
    coll = responders()
    if coll is not None:
        return list(coll.find({}))
    return list(_memory_store.values())


def availability_counts() -> Dict[str, int]:
    """Count VERIFIED + ACTIVE responders by duty state (authority metrics only).

    Only an approved, active account is a real "unit", so unverified/inactive
    accounts are excluded from every bucket. Nothing is fabricated — the counts
    reflect exactly what is stored. Freshness-aware:
      responders_available : AVAILABLE + fresh location + not assigned (dispatch eligible).
      responders_stale     : AVAILABLE but stale/missing location (on duty but not dispatchable).
      responders_busy      : BUSY or holding a live assignment.
      responders_on_duty   : all verified+active units (available+stale+busy).
      responders_offline   : verified+active but OFFLINE/UNAVAILABLE (on roster, not on duty).
    No identity, location, or PII is exposed — counts only.
    """
    from services.dispatch_service import RESPONDER_LOCATION_MAX_AGE_SECONDS as _MAX_AGE
    available = stale = busy = offline = on_duty = 0

    def _fresh(rec: Dict[str, Any]) -> bool:
        ts = rec.get("location_updated_at")
        if not isinstance(ts, datetime):
            return False
        return (datetime.utcnow() - ts).total_seconds() <= _MAX_AGE

    for rec in list_responders():
        if not rec.get("active", False) or not rec.get("verified", False):
            continue
        if not is_on_duty(rec):
            offline += 1  # verified roster unit currently OFF_DUTY
            continue
        on_duty += 1
        assigned = rec.get("assigned_dispatch_id")
        status = rec.get("status")
        if assigned or status == "BUSY":
            busy += 1
        elif status == "AVAILABLE":
            if _fresh(rec):
                available += 1
            else:
                stale += 1
        else:
            offline += 1
    total_registered = len([r for r in list_responders() if r.get("active", False)])
    verified_cnt = len([r for r in list_responders() if r.get("active", False) and r.get("verified", False)])
    return {
        "responders_available": available,
        "responders_stale": stale,
        "responders_busy": busy,
        "responders_offline": offline,
        "responders_on_duty": on_duty,
        "total_registered": total_registered,
        "verified": verified_cnt,
    }


# ─────────────────────── Eligibility & atomic assignment ───────────────────────
# Responder selection is DETERMINISTIC and server-side. No AI and no client field
# decides who is eligible or who gets assigned. "Eligibility first, distance
# second": every hard predicate below must hold, and only then are survivors
# ordered by straight-line proximity to the incident.

# Serializes the in-memory claim/release critical section so two concurrent
# accepts can never both mutate the same responder record. In Mongo mode the
# conditional find_one_and_update is itself atomic; this lock guards only the
# dict fallback used in dev/CI/tests.
_claim_lock = threading.RLock()


def _is_location_fresh(rec: Dict[str, Any], max_age_seconds: int) -> bool:
    if max_age_seconds is None or max_age_seconds <= 0:
        return True
    ts = rec.get("location_updated_at")
    if not isinstance(ts, datetime):
        return False
    return (datetime.utcnow() - ts).total_seconds() <= max_age_seconds


def is_location_fresh(rec: Dict[str, Any], max_age_seconds: int = 300) -> bool:
    return _is_location_fresh(rec, max_age_seconds)



def find_eligible(
    longitude: float,
    latitude: float,
    required_capability: Optional[str] = None,
    radius_m: int = 10_000,
    exclude_ids: Optional[List[str]] = None,
    incident_jurisdiction: Optional[str] = None,
    max_age_seconds: int = 300,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Deterministic eligibility query, nearest-first.

    HARD predicates (ALL must hold): active, verified, status==AVAILABLE, not
    already assigned, (capability contains required_capability if one was asked
    for), (jurisdiction matches if the incident specifies one), a location fix
    that is recent (<= max_age_seconds), and within radius_m of the incident.
    exclude_ids drops responders already tried on this dispatch so a re-offer
    never returns to a unit that declined/timed out.
    """
    from services.geo_validation import haversine_meters, finite_in_range, LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX
    exclude = set(exclude_ids or [])
    cap = (required_capability or "").strip().lower() or None
    juris = (incident_jurisdiction or "").strip() or None
    if not (finite_in_range(longitude, LNG_MIN, LNG_MAX) and finite_in_range(latitude, LAT_MIN, LAT_MAX)):
        return []

    coll = responders()
    if coll is not None:
        query: Dict[str, Any] = {
            "active": True,
            "verified": True,
            "duty_status": DUTY_ON,
            "status": "AVAILABLE",
            "assigned_dispatch_id": None,
            "current_location": {
                "$near": {
                    "$geometry": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
                    "$maxDistance": int(radius_m),
                }
            },
        }
        if cap:
            query["capabilities"] = cap
        if juris:
            query["jurisdiction"] = juris
        if exclude:
            query["responder_id"] = {"$nin": list(exclude)}
        if max_age_seconds and max_age_seconds > 0:
            query["location_updated_at"] = {"$gte": datetime.utcnow() - timedelta(seconds=max_age_seconds)}
        # $near already returns nearest-first; cap the scan with limit.
        return list(coll.find(query).limit(int(limit)))

    # ── In-memory fallback (dev/CI/tests): replicate the same predicates ──
    results: List[Tuple[float, Dict[str, Any]]] = []
    for rec in _memory_store.values():
        if not rec.get("active", False) or not rec.get("verified", False):
            continue
        if not is_on_duty(rec):
            continue
        if rec.get("status") != "AVAILABLE":
            continue
        if rec.get("assigned_dispatch_id"):
            continue
        if rec.get("responder_id") in exclude:
            continue
        if cap and cap not in [str(c).lower() for c in rec.get("capabilities", [])]:
            continue
        if juris and (rec.get("jurisdiction") or "") != juris:
            continue
        if not _is_location_fresh(rec, max_age_seconds):
            continue
        loc = rec.get("current_location") or {}
        coords = loc.get("coordinates") if isinstance(loc, dict) else None
        if not coords or len(coords) != 2:
            continue
        dist = haversine_meters(latitude, longitude, coords[1], coords[0])
        if dist is None or dist > radius_m:
            continue
        results.append((dist, rec))
    results.sort(key=lambda t: t[0])
    return [rec for _dist, rec in results[:limit]]


def try_claim_for_dispatch(responder_id: str, dispatch_id: str) -> Optional[Dict[str, Any]]:
    """Atomically mark a responder BUSY for a dispatch, or return None if unclaimable.

    The conditional guard — status==AVAILABLE AND assigned_dispatch_id is None AND
    verified AND active — guarantees that two concurrent accepts can never both
    succeed for the same responder (single-document atomic update in Mongo; mutex
    in the memory fallback). Returns the updated record on success, None otherwise.
    """
    match = {
        "responder_id": responder_id,
        "status": "AVAILABLE",
        "assigned_dispatch_id": None,
        "verified": True,
        "active": True,
        "duty_status": DUTY_ON,
    }
    patch = {"status": "BUSY", "assigned_dispatch_id": dispatch_id, "updated_at": datetime.utcnow()}
    coll = responders()
    if coll is not None:
        try:
            from pymongo import ReturnDocument
            return coll.find_one_and_update(match, {"$set": patch}, return_document=ReturnDocument.AFTER)
        except Exception:
            # Fallback for driver variants without ReturnDocument import path.
            updated = coll.update_one(match, {"$set": patch})
            if getattr(updated, "modified_count", 0) == 1:
                return coll.find_one({"responder_id": responder_id})
            return None
    with _claim_lock:
        for rec in _memory_store.values():
            if (rec.get("responder_id") == responder_id and rec.get("status") == "AVAILABLE"
                    and not rec.get("assigned_dispatch_id") and rec.get("verified") and rec.get("active")
                    and is_on_duty(rec)):
                rec.update(patch)
                return rec
        return None


def release_from_dispatch(responder_id: str, dispatch_id: Optional[str] = None) -> bool:
    """Release a responder back to AVAILABLE after a dispatch ends. Idempotent.

    When dispatch_id is given, only releases if the responder is still bound to
    THAT dispatch, so a stale release cannot free a unit that has since been
    assigned to a different incident. Returns True if a record was released.
    """
    match: Dict[str, Any] = {"responder_id": responder_id}
    if dispatch_id is not None:
        match["assigned_dispatch_id"] = dispatch_id
    patch = {"status": "AVAILABLE", "assigned_dispatch_id": None, "updated_at": datetime.utcnow()}
    coll = responders()
    if coll is not None:
        res = coll.update_one(match, {"$set": patch})
        return getattr(res, "modified_count", 0) >= 1
    with _claim_lock:
        for rec in _memory_store.values():
            if rec.get("responder_id") != responder_id:
                continue
            if dispatch_id is not None and rec.get("assigned_dispatch_id") != dispatch_id:
                continue
            rec.update(patch)
            return True
        return False


def ensure_dev_responder() -> None:
    """Non-production convenience: seed ONE local dev responder so dev/CI works.

    Never runs in production. The dev unit is seeded verified=True + AVAILABLE so a
    developer can exercise the full dispatch flow locally without an admin step.
    """
    global _dev_seeded
    if IS_PRODUCTION or _dev_seeded:
        return
    badge = os.getenv("DEV_RESPONDER_BADGE", "HN-204")
    if get_responder(badge) is None:
        create_responder(
            badge_number=badge,
            officer_name=os.getenv("DEV_RESPONDER_NAME", "Duty Response Unit"),
            password=os.getenv("DEV_RESPONDER_PASSWORD", "haven2024"),
            display_label=os.getenv("DEV_RESPONDER_LABEL", f"Verified Response Unit {badge}"),
            capabilities=["general"],
            jurisdiction=os.getenv("DEV_RESPONDER_JURISDICTION", ""),
            active=True,
        )
        # Dev unit is pre-approved and on duty so the local flow is exercisable.
        set_verified(f"RESP-{badge}", True)
        rec = get_responder(badge)
        if rec is not None:
            _persist(rec, {"status": "AVAILABLE"})
        logger.info("Seeded development responder account (non-production only).")
    _dev_seeded = True
