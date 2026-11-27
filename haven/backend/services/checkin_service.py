"""
Emergency Safety Check-In Timer Service (Phase 4B).

Persistent MongoDB-backed safety timers so check-ins survive logout, browser
closure, and device restart. Escalation and reminders run in the backend
background sweeper (and deterministically via `process_due_checkins()` in tests).

Privacy & consent rules:
  * Explicit `consent_acknowledged=True` is mandatory to start a timer.
  * Trusted contacts are NEVER contacted automatically unless the user
    explicitly enabled `allow_contact_escalation=True`.
  * Escalation SMS delivery status is tracked honestly via sms_service.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from services.audit_service import log_audit
from services.db import safety_checkins, trusted_contacts, sos_cases, sos_events, serialize_doc
from services.geo_validation import finite_in_range
from services.lifecycle_service import transition_sos
from services.notification_service import notification_manager
from services.sms_service import notify_trusted_contacts

logger = logging.getLogger("haven_backend")

STATUS_ACTIVE = "ACTIVE"
STATUS_CONFIRMED_SAFE = "CONFIRMED_SAFE"
STATUS_CANCELLED = "CANCELLED"
STATUS_ESCALATED = "ESCALATED"


def _remaining_seconds(doc: dict, now: Optional[datetime] = None) -> int:
    if not doc or doc.get("status") != STATUS_ACTIVE:
        return 0
    now = now or datetime.now(timezone.utc)
    exp = doc.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except ValueError:
            return 0
    if not isinstance(exp, datetime):
        return 0
    exp_aware = exp.replace(tzinfo=timezone.utc) if exp.tzinfo is None else exp
    return max(0, int((exp_aware - now).total_seconds()))


def public_checkin_view(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    out = serialize_doc(doc)
    out["remaining_seconds"] = _remaining_seconds(doc)
    return out


def _describe_escalation(allow_contacts: bool, allow_authority: bool) -> str:
    parts = ["Send you an urgent expiry notification inside HAVEN"]
    if allow_contacts:
        parts.append("attempt SMS alerts to your trusted contacts (when Twilio SMS is configured)")
    if allow_authority:
        parts.append("create a missed check-in escalation alert for HAVEN authorities")
    return "; ".join(parts) + "."


def create_checkin(
    user_id: str,
    *,
    duration_minutes: int,
    reminder_before_minutes: int = 5,
    activity_label: str = "",
    consent_acknowledged: bool = False,
    allow_contact_escalation: bool = False,
    allow_authority_escalation: bool = False,
    manual_location: str = "",
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """Create and persist a backend-scheduled emergency check-in timer."""
    if not consent_acknowledged:
        raise ValueError("Explicit consent acknowledging check-in timer expiry behavior is required.")

    coll = safety_checkins()
    if coll is None:
        raise RuntimeError("Database unavailable")

    if latitude is not None or longitude is not None:
        if latitude is None or longitude is None or not finite_in_range(latitude, -90.0, 90.0) or not finite_in_range(longitude, -180.0, 180.0):
            raise ValueError("Invalid coordinates for check-in location.")

    # Auto-close any expired/stale or prior active check-in? Refuse active conflict
    # clearly so the user explicitly cancels or confirms the existing timer first.
    existing = coll.find_one({"user_id": user_id, "status": STATUS_ACTIVE})
    if existing:
        raise FileExistsError("An active check-in timer is already running. Confirm safe, extend, or cancel it first.")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=int(duration_minutes))
    lead = min(int(reminder_before_minutes), max(1, int(duration_minutes) - 1))
    reminder_at = expires_at - timedelta(minutes=lead) if int(duration_minutes) >= 3 else now

    checkin_id = f"CHK-{int(now.timestamp())}-{secrets.token_hex(3).upper()}"
    rule_summary = _describe_escalation(allow_contact_escalation, allow_authority_escalation)

    doc: Dict[str, Any] = {
        "checkin_id": checkin_id,
        "user_id": user_id,
        "status": STATUS_ACTIVE,
        "duration_minutes": int(duration_minutes),
        "reminder_before_minutes": lead,
        "activity_label": (activity_label or "").strip()[:200],
        "consent_acknowledged": True,
        "allow_contact_escalation": bool(allow_contact_escalation),
        "allow_authority_escalation": bool(allow_authority_escalation),
        "escalation_summary": rule_summary,
        "manual_location": (manual_location or "").strip()[:300],
        "created_at": now,
        "updated_at": now,
        "reminder_at": reminder_at,
        "expires_at": expires_at,
        "reminder_sent": False,
        "reminder_sent_at": None,
        "confirmed_safe_at": None,
        "cancelled_at": None,
        "escalated_at": None,
        "escalation_outcome": None,
    }
    if latitude is not None and longitude is not None:
        doc["latitude"] = float(latitude)
        doc["longitude"] = float(longitude)

    coll.insert_one(doc)
    log_audit(
        actor_id=user_id, role="user", action="CHECKIN_STARTED",
        result="success",
        metadata={
            "checkin_id": checkin_id,
            "duration_minutes": int(duration_minutes),
            "allow_contact_escalation": bool(allow_contact_escalation),
            "allow_authority_escalation": bool(allow_authority_escalation),
        },
    )
    return public_checkin_view(doc) or {}


def get_active_checkin(user_id: str) -> Optional[dict]:
    coll = safety_checkins()
    if coll is None:
        return None
    doc = coll.find_one({"user_id": user_id, "status": STATUS_ACTIVE}, {"_id": 0})
    return public_checkin_view(doc)


def list_checkin_history(user_id: str, limit: int = 15) -> List[dict]:
    coll = safety_checkins()
    if coll is None:
        return []
    bounded = max(1, min(int(limit or 15), 50))
    rows = list(coll.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(bounded))
    return [public_checkin_view(r) for r in rows]


def confirm_safe(checkin_id: str, user_id: str) -> Optional[dict]:
    coll = safety_checkins()
    if coll is None:
        raise RuntimeError("Database unavailable")
    now = datetime.now(timezone.utc)
    updated = coll.find_one_and_update(
        {"checkin_id": checkin_id, "user_id": user_id, "status": STATUS_ACTIVE},
        {"$set": {"status": STATUS_CONFIRMED_SAFE, "confirmed_safe_at": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if updated:
        log_audit(actor_id=user_id, role="user", action="CHECKIN_CONFIRMED_SAFE",
                  result="success", metadata={"checkin_id": checkin_id})
        return public_checkin_view(updated)
    return None


def cancel_checkin(checkin_id: str, user_id: str) -> Optional[dict]:
    coll = safety_checkins()
    if coll is None:
        raise RuntimeError("Database unavailable")
    now = datetime.now(timezone.utc)
    updated = coll.find_one_and_update(
        {"checkin_id": checkin_id, "user_id": user_id, "status": STATUS_ACTIVE},
        {"$set": {"status": STATUS_CANCELLED, "cancelled_at": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if updated:
        log_audit(actor_id=user_id, role="user", action="CHECKIN_CANCELLED",
                  result="success", metadata={"checkin_id": checkin_id})
        return public_checkin_view(updated)
    return None


def extend_checkin(checkin_id: str, user_id: str, extra_minutes: int) -> Optional[dict]:
    coll = safety_checkins()
    if coll is None:
        raise RuntimeError("Database unavailable")
    existing = coll.find_one({"checkin_id": checkin_id, "user_id": user_id, "status": STATUS_ACTIVE})
    if not existing:
        return None
    now = datetime.now(timezone.utc)
    old_exp = existing.get("expires_at")
    if isinstance(old_exp, str):
        old_exp = datetime.fromisoformat(old_exp.replace("Z", "+00:00"))
    base = old_exp.replace(tzinfo=timezone.utc) if isinstance(old_exp, datetime) and old_exp.tzinfo is None else (old_exp or now)
    new_exp = max(base, now) + timedelta(minutes=int(extra_minutes))
    lead = int(existing.get("reminder_before_minutes") or 5)
    new_rem = new_exp - timedelta(minutes=lead)
    updated = coll.find_one_and_update(
        {"checkin_id": checkin_id, "user_id": user_id, "status": STATUS_ACTIVE},
        {"$set": {
            "expires_at": new_exp,
            "reminder_at": new_rem,
            "reminder_sent": False,
            "duration_minutes": int(existing.get("duration_minutes", 0)) + int(extra_minutes),
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if updated:
        log_audit(actor_id=user_id, role="user", action="CHECKIN_EXTENDED",
                  result="success", metadata={"checkin_id": checkin_id, "extra_minutes": int(extra_minutes)})
        return public_checkin_view(updated)
    return None


def process_due_checkins(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Evaluate all due check-in reminders and expired timers deterministically.

    Safe to call from background sweeper loop AND directly from unit tests.
    Uses atomic `find_one_and_update` claims so concurrent workers never double-fire.
    Returns notification intents for async WebSocket fan-out + counters.
    """
    coll = safety_checkins()
    if coll is None:
        return {"reminders": 0, "escalations": 0, "notify": []}

    now = now or datetime.now(timezone.utc)
    reminders_sent = 0
    escalations_run = 0
    intents: List[Dict[str, Any]] = []

    # 1) Send due pre-deadline reminders
    due_reminders = list(coll.find(
        {"status": STATUS_ACTIVE, "reminder_sent": False, "reminder_at": {"$lte": now}, "expires_at": {"$gt": now}},
        {"_id": 0, "checkin_id": 1},
    ).limit(50))

    for row in due_reminders:
        cid = row.get("checkin_id")
        claimed = coll.find_one_and_update(
            {"checkin_id": cid, "status": STATUS_ACTIVE, "reminder_sent": False},
            {"$set": {"reminder_sent": True, "reminder_sent_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if not claimed:
            continue
        reminders_sent += 1
        uid = claimed["user_id"]
        label = claimed.get("activity_label") or "Safety Check-In"
        title = "Safety Check-In Reminder"
        msg = f"Your safety check-in '{label}' is due soon. Confirm safe or extend timer."
        try:
            nid = notification_manager.create_notification(
                recipient_id=uid, event_type="CHECKIN_REMINDER", title=title, message=msg, case_id=cid,
            )
            intents.append({
                "kind": "user", "target": uid, "event_type": "CHECKIN_REMINDER",
                "data": {"notification_id": nid, "checkin_id": cid, "title": title, "message": msg},
            })
        except Exception:
            pass

    # 2) Escalate expired active timers atomically
    due_expired = list(coll.find(
        {"status": STATUS_ACTIVE, "expires_at": {"$lte": now}},
        {"_id": 0, "checkin_id": 1},
    ).limit(50))

    for row in due_expired:
        cid = row.get("checkin_id")
        claimed = coll.find_one_and_update(
            {"checkin_id": cid, "status": STATUS_ACTIVE},
            {"$set": {"status": STATUS_ESCALATED, "escalated_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if not claimed:
            continue
        escalations_run += 1
        uid = claimed["user_id"]
        label = claimed.get("activity_label") or "Safety Check-In"
        loc_desc = claimed.get("manual_location") or (
            f"{claimed.get('latitude')}, {claimed.get('longitude')}"
            if claimed.get("latitude") is not None and claimed.get("longitude") is not None
            else "No location provided"
        )
        outcome: Dict[str, Any] = {
            "user_notified": False,
            "contacts_attempted": False,
            "contact_results": [],
            "authority_case_created": None,
        }

        # Always notify owner
        try:
            nid = notification_manager.create_notification(
                recipient_id=uid,
                event_type="CHECKIN_ESCALATED",
                title="Safety Check-In Deadline Passed",
                message=f"Check-in '{label}' expired without confirmation. Configured escalation triggered.",
                case_id=cid,
            )
            intents.append({
                "kind": "user", "target": uid, "event_type": "CHECKIN_ESCALATED",
                "data": {"notification_id": nid, "checkin_id": cid, "title": "Safety Check-In Deadline Passed"},
            })
            outcome["user_notified"] = True
        except Exception:
            pass

        # Contact SMS escalation ONLY when user explicitly opted in
        if claimed.get("allow_contact_escalation"):
            tc_coll = trusted_contacts()
            contacts = list(tc_coll.find({"user_id": uid}, {"_id": 0})) if tc_coll is not None else []
            if contacts:
                outcome["contacts_attempted"] = True
                sms_text = (
                    f"HAVEN Safety Check-In Missed ({cid})\n"
                    f"Activity: {label}\nLocation: {loc_desc}\nDeadline passed: {now.isoformat()}"
                )
                results = notify_trusted_contacts(contacts, cid, sms_text)
                outcome["contact_results"] = [r.to_safe_dict() for r in results]

        # Authority escalation alert ONLY when user explicitly opted in
        if claimed.get("allow_authority_escalation"):
            cases_coll = sos_cases()
            if cases_coll is not None:
                esc_case_id = f"CHK-ESC-{int(now.timestamp())}-{secrets.token_hex(2).upper()}"
                case_doc = {
                    "case_id": esc_case_id,
                    "user_id": uid,
                    "trigger_type": "checkin_escalation",
                    "category": "other",
                    "description": f"Missed consented safety check-in ({cid}): {label}",
                    "decoded_text": f"Missed consented safety check-in ({cid}): {label}. Location: {loc_desc}",
                    "summary": f"Missed safety check-in ({label})",
                    "severity": "high",
                    "immediate_danger": False,
                    "location": loc_desc,
                    "location_source": "gps" if claimed.get("latitude") is not None else ("manual" if claimed.get("manual_location") else "unavailable"),
                    "status": "CREATED",
                    "is_demo": False,
                    "created_at": now,
                    "updated_at": now,
                    "checkin_id": cid,
                }
                if claimed.get("latitude") is not None and claimed.get("longitude") is not None:
                    case_doc["latitude"] = claimed["latitude"]
                    case_doc["longitude"] = claimed["longitude"]
                    case_doc["location_freshness"] = "CHECKIN_SNAPSHOT"
                try:
                    cases_coll.insert_one(case_doc)
                    ev_coll = sos_events()
                    if ev_coll is not None:
                        ev_coll.insert_one({
                            "event_id": esc_case_id, "user_id": uid, "trigger_type": "checkin_escalation",
                            "timestamp": now.isoformat(), "latitude": claimed.get("latitude"),
                            "longitude": claimed.get("longitude"), "status": "RECEIVED",
                            "is_test": False, "is_demo": False, "created_at": now,
                        })
                    transition_sos(esc_case_id, "RECEIVED", uid, "user", notes="Consented check-in timer expired")
                    outcome["authority_case_created"] = esc_case_id
                    aid = notification_manager.create_notification(
                        recipient_id="all_authorities",
                        event_type="CHECKIN_ESCALATED",
                        title="Missed Safety Check-In Alert",
                        message=f"Consented check-in {cid} missed deadline -> Case {esc_case_id}",
                        case_id=esc_case_id,
                    )
                    intents.append({
                        "kind": "authorities", "event_type": "CHECKIN_ESCALATED",
                        "data": {"notification_id": aid, "case_id": esc_case_id, "title": "Missed Safety Check-In Alert"},
                    })
                except Exception as exc:
                    logger.warning("checkin_service: authority case creation failed: %s", exc)

        coll.update_one({"checkin_id": cid}, {"$set": {"escalation_outcome": outcome, "updated_at": now}})
        log_audit(
            actor_id="system_checkin_scheduler",
            role="system",
            action="CHECKIN_ESCALATED",
            case_id=outcome.get("authority_case_created"),
            result="success",
            metadata={"checkin_id": cid, "allow_contact": bool(claimed.get("allow_contact_escalation")),
                      "allow_authority": bool(claimed.get("allow_authority_escalation"))},
        )

    return {"reminders": reminders_sent, "escalations": escalations_run, "notify": intents}
