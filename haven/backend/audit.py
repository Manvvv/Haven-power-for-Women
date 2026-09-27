"""
HAVEN Audit Logging Module.
Records sensitive authority actions for compliance and accountability.
All audit records are immutable once written.
"""

import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

logger = logging.getLogger("haven_audit")


# ─── Valid SOS Lifecycle States ──────────────────────────

SOS_LIFECYCLE_STATES = [
    "CREATED",
    "ENCODED",
    "SHARED",
    "RECEIVED",
    "DECODED",
    "AI_ANALYZED",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "RESOLVED",
]

# Allowed transitions: state -> list of valid next states
SOS_TRANSITIONS: Dict[str, list] = {
    "CREATED": ["ENCODED", "SHARED", "RECEIVED", "DECODED"],
    "ENCODED": ["SHARED", "RECEIVED"],
    "SHARED": ["RECEIVED", "DECODED"],
    "RECEIVED": ["DECODED", "ACKNOWLEDGED"],
    "DECODED": ["AI_ANALYZED", "ACKNOWLEDGED"],
    "AI_ANALYZED": ["ACKNOWLEDGED", "IN_PROGRESS"],
    "ACKNOWLEDGED": ["IN_PROGRESS"],
    "IN_PROGRESS": ["RESOLVED"],
    "RESOLVED": [],
}


class AuditEntry(BaseModel):
    actor_id: str = "system"
    actor_role: str = "unknown"
    action: str
    case_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool = True
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def log_audit(
    collection,
    action: str,
    actor_id: str = "system",
    actor_role: str = "unknown",
    case_id: Optional[str] = None,
    success: bool = True,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Write an immutable audit log entry to MongoDB.
    Returns the audit_id or None if collection is unavailable.
    """
    if collection is None:
        logger.warning(f"Audit log skipped (no DB): action={action} case={case_id}")
        return None

    audit_id = f"AUD-{int(time.time() * 1000)}-{actor_id[:8]}"
    entry = {
        "audit_id": audit_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "case_id": case_id,
        "timestamp": datetime.utcnow(),
        "ip_address": ip_address or "",
        "user_agent": user_agent or "",
        "success": success,
        "reason": reason or "",
        "metadata": metadata or {},
    }
    try:
        collection.insert_one(entry)
        logger.info(f"AUDIT: {action} by {actor_id}({actor_role}) case={case_id} success={success}")
        return audit_id
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
        return None


def validate_sos_transition(current_status: str, new_status: str) -> tuple:
    """
    Validate that a SOS lifecycle state transition is allowed.
    Returns (is_valid: bool, error_message: str | None).
    Also supports legacy statuses for backward compatibility.
    """
    # Normalize legacy statuses to lifecycle states
    legacy_map = {
        "pending": "CREATED",
        "active": "ACKNOWLEDGED",
        "in_progress": "IN_PROGRESS",
        "resolved": "RESOLVED",
    }

    norm_current = legacy_map.get(current_status.lower(), current_status.upper()) if current_status else "CREATED"
    norm_new = legacy_map.get(new_status.lower(), new_status.upper()) if new_status else ""

    if not norm_new:
        return False, "Target status cannot be empty"

    # If current state isn't in our lifecycle map, allow any transition (legacy compat)
    if norm_current not in SOS_TRANSITIONS:
        return True, None

    allowed = SOS_TRANSITIONS.get(norm_current, [])
    if norm_new in allowed:
        return True, None

    # Allow staying in same state (idempotent)
    if norm_current == norm_new:
        return True, None

    return False, f"Invalid transition: {norm_current} → {norm_new}. Allowed: {allowed}"


def record_status_history(
    sos_collection,
    case_id: str,
    old_status: str,
    new_status: str,
    changed_by: str,
    reason: Optional[str] = None,
) -> None:
    """Append a status change to the SOS case's history array."""
    if sos_collection is None:
        return
    history_entry = {
        "from_status": old_status,
        "to_status": new_status,
        "changed_by": changed_by,
        "timestamp": datetime.utcnow(),
        "reason": reason or "",
    }
    try:
        sos_collection.update_one(
            {"case_id": case_id},
            {"$push": {"status_history": history_entry}, "$set": {"updated_at": datetime.utcnow()}}
        )
    except Exception as e:
        logger.error(f"Failed to record status history for {case_id}: {e}")
