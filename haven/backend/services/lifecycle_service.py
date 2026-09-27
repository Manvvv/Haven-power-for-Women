from datetime import datetime
from services.db import sos_cases, sos_status_history
from services.audit_service import log_audit

# Canonical SOS lifecycle. The first six states model the automated pipeline
# (create → encode → share → receive → decode → AI analysis). The final three
# (ACKNOWLEDGED → IN_PROGRESS → RESOLVED) are authority triage actions.
#
# Because a case only appears on the authority dashboard once it has effectively
# been "received", authorities may acknowledge / start / resolve it from ANY
# pipeline state (not just the strict next one). This keeps the triage workflow
# practical while still preventing nonsensical moves such as un-resolving a case
# or jumping backwards through the automated pipeline.
_TRIAGE_TARGETS = ["ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED"]

VALID_TRANSITIONS = {
    "CREATED": ["ENCODED", "SHARED", "RECEIVED", "DECODED", "AI_ANALYZED"] + _TRIAGE_TARGETS,
    "ENCODED": ["SHARED", "RECEIVED", "DECODED", "AI_ANALYZED"] + _TRIAGE_TARGETS,
    "SHARED": ["RECEIVED", "DECODED", "AI_ANALYZED"] + _TRIAGE_TARGETS,
    "RECEIVED": ["DECODED", "AI_ANALYZED"] + _TRIAGE_TARGETS,
    "DECODED": ["AI_ANALYZED"] + _TRIAGE_TARGETS,
    "AI_ANALYZED": _TRIAGE_TARGETS,
    "ACKNOWLEDGED": ["IN_PROGRESS", "RESOLVED"],
    "IN_PROGRESS": ["ACKNOWLEDGED", "RESOLVED"],
    "RESOLVED": [],
}

# Ordered list of all lifecycle states (used by UIs and tests).
SOS_STATES = [
    "CREATED", "ENCODED", "SHARED", "RECEIVED", "DECODED",
    "AI_ANALYZED", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED",
]

# ─── Legacy status compatibility (boundary normalization) ───────────────────
# Some producers historically wrote non-canonical status strings — notably the
# voice-SOS trigger, which stored the case as "active" and its event as
# "triggered". Those are NOT keys in VALID_TRANSITIONS, so any attempt to
# transition/resolve such a case failed and surfaced as a spurious 409.
#
# Rather than expand the state machine with parallel states (which would create
# two competing systems), we map these legacy values onto the SINGLE canonical
# state they semantically represent: a live case that the system has received
# and that authorities may now triage → RECEIVED. Normalization happens at the
# boundary (validation + transition), and transition_sos rewrites the stored
# status to canonical, so existing rows self-heal on their first transition.
_STATUS_ALIASES = {
    "ACTIVE": "RECEIVED",
    "TRIGGERED": "RECEIVED",
}


def canonical_status(status: str) -> str:
    """Normalize any status string to its canonical lifecycle state.

    Unknown/canonical values pass through unchanged (upper-cased); only the
    documented legacy aliases are remapped. This is the one place legacy
    statuses are translated — there is exactly one canonical state model.
    """
    s = (status or "CREATED").upper()
    return _STATUS_ALIASES.get(s, s)


def is_terminal_status(status: str) -> bool:
    """True if the (canonicalized) status is terminal — no further transitions.

    Used to stop live location tracking on a resolved case. Driven by
    VALID_TRANSITIONS so any future terminal state is covered automatically.
    """
    return VALID_TRANSITIONS.get(canonical_status(status), None) == []


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """
    Pure state-machine check (no DB) — is moving from `from_status` to
    `to_status` allowed? A no-op transition to the same state is allowed.
    Useful for validation and unit testing without a database.

    Both endpoints are canonicalized first so legacy statuses ("active",
    "triggered") validate against the canonical machine instead of failing.
    """
    f = canonical_status(from_status)
    t = canonical_status(to_status) if to_status else ""
    if t == f:
        return True
    return t in VALID_TRANSITIONS.get(f, [])


def transition_sos(case_id: str, new_status: str, actor_id: str, role: str, notes: str = '') -> bool:
    """Transition an SOS case to a new status."""
    cases_coll = sos_cases()
    history_coll = sos_status_history()

    if cases_coll is None or history_coll is None:
        return False

    case = cases_coll.find_one({"case_id": case_id})
    if not case:
        return False

    current_status = canonical_status(case.get("status", "CREATED"))
    new_status_upper = canonical_status(new_status)

    if not is_valid_transition(current_status, new_status_upper):
        return False

    now = datetime.utcnow()
    cases_coll.update_one(
        {"case_id": case_id},
        {"$set": {"status": new_status_upper, "updated_at": now}}
    )

    history_coll.insert_one({
        "case_id": case_id,
        "from_status": current_status,
        "to_status": new_status_upper,
        "actor_id": actor_id,
        "notes": notes,
        "timestamp": now
    })

    log_audit(
        actor_id=actor_id,
        role=role,
        action="CASE_STATUS_CHANGED",
        case_id=case_id,
        result="success",
        metadata={"from": current_status, "to": new_status_upper}
    )
    return True
