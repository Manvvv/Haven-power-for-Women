"""
Isolated Demo Mode Service (Phase 8).

CRITICAL ISOLATION INVARIANT:
  * All persistence goes strictly to `demo_*` collections (`demo_cases`,
    `demo_dispatches`, `demo_responders`, `demo_contacts`, `demo_checkins`,
    `demo_provider_registrations`, `demo_safety_plans`, `demo_audit_logs`).
  * NEVER touches `sos_cases`, `sos_events`, `dispatch_requests`, `responders`,
    `trusted_contacts`, `authority_accounts`, or `sms_service`.
  * NEVER broadcasts on production WebSockets or contacts real responders/SMS/authorities.
  * Every document carries `"is_demo": True` and `"simulation": True`.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.db import demo_collection, serialize_doc
from services.voice_ai_service import extract_emergency_info

DEMO_LABEL = "SIMULATED_DEMO_ONLY"


def _dc(name: str):
    return demo_collection(name)


def seed_demo_workspace(force_reset: bool = False) -> Dict[str, Any]:
    """Ensure clean, realistic sample records exist in isolated demo_* collections."""
    cases = _dc("cases")
    dispatches = _dc("dispatches")
    responders = _dc("responders")
    contacts = _dc("contacts")
    checkins = _dc("checkins")
    regs = _dc("provider_registrations")
    plans = _dc("safety_plans")
    audits = _dc("audit_logs")

    if any(c is None for c in (cases, dispatches, responders, contacts, regs, plans, audits)):
        return {"connected": False}

    if force_reset:
        for c in (cases, dispatches, responders, contacts, checkins, regs, plans, audits):
            if c is not None:
                c.delete_many({})

    if responders.count_documents({}) > 0 and not force_reset:
        return get_demo_state()

    now = datetime.now(timezone.utc)

    # Sample Demo Personas (display metadata ONLY — zero real passwords/bypass tokens)
    responders.insert_many([
        {
            "responder_id": "DEMO-RESP-101",
            "badge_number": "DEMO-HN-101",
            "display_label": "Demo Unit Alpha (Mahila Patrol)",
            "provider_category": "police",
            "status": "AVAILABLE",
            "duty_status": "ON_DUTY",
            "verified": True,
            "active": True,
            "jurisdiction": "Central Delhi (Demo)",
            "capabilities": ["patrol", "women_cell"],
            "distance_m": 420,
            "is_demo": True,
            "simulation": True,
            "updated_at": now,
        },
        {
            "responder_id": "DEMO-RESP-102",
            "badge_number": "DEMO-HN-102",
            "display_label": "Demo Unit Sakhi-2 (Crisis NGO)",
            "provider_category": "ngo_crisis",
            "status": "OFFLINE",
            "duty_status": "OFF_DUTY",
            "verified": False,
            "active": True,
            "jurisdiction": "South Delhi (Demo)",
            "capabilities": ["counseling", "shelter"],
            "distance_m": 1150,
            "is_demo": True,
            "simulation": True,
            "updated_at": now,
        },
    ])

    contacts.insert_many([
        {
            "contact_id": "DEMO-CTC-1",
            "name": "Meera Sharma (Demo Sister)",
            "phone": "+91-98XXX-00101 (Demo)",
            "email": "meera.demo@example.invalid",
            "relationship": "sibling",
            "priority": 1,
            "verification_status": "VERIFIED",
            "is_demo": True,
            "created_at": now - timedelta(days=3),
        },
        {
            "contact_id": "DEMO-CTC-2",
            "name": "Aarti Verma (Demo Neighbor)",
            "phone": "+91-98XXX-00102 (Demo)",
            "email": "aarti.demo@example.invalid",
            "relationship": "neighbor",
            "priority": 2,
            "verification_status": "VERIFIED",
            "is_demo": True,
            "created_at": now - timedelta(days=2),
        },
    ])

    cases.insert_one({
        "case_id": "DEMO-CASE-SEED-001",
        "user_id": "DEMO-USER-ANANYA",
        "trigger_type": "demo_history_sample",
        "category": "unsafe_transit",
        "description": "Sample historical demo incident: Stranded late evening near metro exit, resolved smoothly.",
        "severity": "medium",
        "location": "28.6315, 77.2167 (Demo Metro Plaza)",
        "status": "RESOLVED",
        "timeline": [
            {"status": "CREATED", "actor": "DEMO-USER-ANANYA", "timestamp": (now - timedelta(hours=4)).isoformat()},
            {"status": "RECEIVED", "actor": "DEMO-SYSTEM", "timestamp": (now - timedelta(hours=4)).isoformat()},
            {"status": "ACKNOWLEDGED", "actor": "DEMO-AUTH-PRIYA", "timestamp": (now - timedelta(hours=3, minutes=57)).isoformat()},
            {"status": "RESOLVED", "actor": "DEMO-AUTH-PRIYA", "timestamp": (now - timedelta(hours=3, minutes=40)).isoformat()},
        ],
        "is_demo": True,
        "simulation": True,
        "created_at": now - timedelta(hours=4),
        "updated_at": now - timedelta(hours=3, minutes=40),
    })

    regs.insert_one({
        "registration_id": "DEMO-REG-001",
        "unit_name": "Sakhi Mobile Support Van (Demo)",
        "organization": "Delhi Women Safety NGO (Demo)",
        "provider_category": "ngo_crisis",
        "jurisdiction": "South Delhi (Demo)",
        "badge_number": "DEMO-NGO-305",
        "responder_id": "DEMO-RESP-102",
        "status": "PENDING_REVIEW",
        "submitted_by": "DEMO-AUTH-PRIYA",
        "submitted_at": (now - timedelta(minutes=25)).isoformat(),
        "is_demo": True,
        "simulation": True,
    })

    plans.insert_one({
        "plan_id": "DEMO-PLAN-001",
        "user_id": "DEMO-USER-ANANYA",
        "warning_signs": ["Feeling watched while commuting", "Phone battery below 15% after 9 PM"],
        "safe_places": ["Nearest Metro Police Booth", "24x7 Pharmacy on Main Road"],
        "things_that_help": ["Call sister Meera while walking", "Keep emergency contacts updated"],
        "emergency_numbers": ["112 (Emergency)", "181 (Women Helpline)", "1091 (Police Women Cell)"],
        "is_demo": True,
        "updated_at": now.isoformat(),
    })

    if checkins is not None:
        checkins.insert_one({
            "checkin_id": "DEMO-CHK-001",
            "activity_label": "Evening Cab Ride Home (Sample)",
            "duration_minutes": 30,
            "status": "CONFIRMED_SAFE",
            "escalation_summary": "Notify demo contacts when timer expires (simulated)",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "is_demo": True,
        })

    audits.insert_one({
        "audit_id": f"DEMO-AUD-{secrets.token_hex(3).upper()}",
        "actor": "DEMO-SYSTEM",
        "role": "system",
        "action": "DEMO_WORKSPACE_SEEDED",
        "details": "Isolated demo sandbox initialized cleanly (zero production writes).",
        "timestamp": now.isoformat(),
        "is_demo": True,
    })

    return get_demo_state()


def get_demo_state() -> Dict[str, Any]:
    cases_c = _dc("cases")
    if cases_c is None:
        return {"connected": False, "is_demo": True, "simulation": True}

    if _dc("responders").count_documents({}) == 0:
        seed_demo_workspace(force_reset=False)

    return {
        "connected": True,
        "is_demo": True,
        "simulation": True,
        "isolation_notice": "ISOLATED DEMO SANDBOX — reads/writes only demo_* collections; never triggers real SMS, WhatsApp, or emergency responders.",
        "accounts": {
            "user": {"id": "DEMO-USER-ANANYA", "name": "Ananya (Demo User)", "role": "user"},
            "authority": {"id": "DEMO-AUTH-PRIYA", "name": "Inspector Priya (Demo Dispatcher)", "role": "authority"},
            "responder": {"id": "DEMO-RESP-101", "name": "Demo Unit Alpha", "role": "responder"},
            "admin": {"id": "DEMO-ADMIN-KAVITA", "name": "Kavita (Demo Admin)", "role": "admin"},
        },
        "cases": [serialize_doc(x) for x in _dc("cases").find({}, {"_id": 0}).sort("created_at", -1).limit(15)],
        "dispatches": [serialize_doc(x) for x in _dc("dispatches").find({}, {"_id": 0}).sort("created_at", -1).limit(15)],
        "responders": [serialize_doc(x) for x in _dc("responders").find({}, {"_id": 0})],
        "contacts": [serialize_doc(x) for x in _dc("contacts").find({}, {"_id": 0})],
        "checkins": [serialize_doc(x) for x in _dc("checkins").find({}, {"_id": 0}).limit(10)],
        "provider_registrations": [serialize_doc(x) for x in _dc("provider_registrations").find({}, {"_id": 0})],
        "safety_plan": serialize_doc(_dc("safety_plans").find_one({}, {"_id": 0}) or {}),
        "audit_logs": [serialize_doc(x) for x in _dc("audit_logs").find({}, {"_id": 0}).sort("timestamp", -1).limit(20)],
    }


def _demo_audit(actor: str, role: str, action: str, details: str, case_id: Optional[str] = None) -> None:
    audits = _dc("audit_logs")
    if audits is not None:
        audits.insert_one({
            "audit_id": f"DEMO-AUD-{secrets.token_hex(3).upper()}",
            "actor": actor,
            "role": role,
            "action": action,
            "case_id": case_id,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_demo": True,
        })


def submit_demo_sos(category: str, description: str, location: str, trigger_type: str = "demo_website_sos",
                    voice_analysis: Optional[dict] = None) -> Dict[str, Any]:
    cases = _dc("cases")
    if cases is None:
        raise RuntimeError("Database unavailable")
    now = datetime.now(timezone.utc)
    cid = f"DEMO-CASE-{int(now.timestamp())}-{secrets.token_hex(2).upper()}"
    doc = {
        "case_id": cid,
        "user_id": "DEMO-USER-ANANYA",
        "trigger_type": trigger_type,
        "category": category or "immediate_danger",
        "description": description or "Simulated SOS distress report for demonstration.",
        "severity": "high" if category != "immediate_danger" else "critical",
        "location": location or "28.6328, 77.2197 (Simulated Connaught Place)",
        "status": "RECEIVED",
        "simulated_notifications": [
            {"contact": "Meera Sharma (Demo)", "status": "SIMULATED_ONLY_NOT_SENT"},
            {"contact": "Aarti Verma (Demo)", "status": "SIMULATED_ONLY_NOT_SENT"},
        ],
        "timeline": [
            {"status": "CREATED", "actor": "DEMO-USER-ANANYA", "timestamp": now.isoformat()},
            {"status": "RECEIVED", "actor": "DEMO-SYSTEM", "timestamp": now.isoformat()},
        ],
        "is_demo": True,
        "simulation": True,
        "created_at": now,
        "updated_at": now,
    }
    if voice_analysis:
        doc["voice_analysis"] = voice_analysis
    cases.insert_one(doc)
    _demo_audit("DEMO-USER-ANANYA", "user", "DEMO_SOS_SUBMITTED", f"Simulated SOS {cid} ({doc['category']})", cid)
    return serialize_doc(doc)


def analyze_demo_voice(transcript: str, language: str = "en") -> Dict[str, Any]:
    extraction = extract_emergency_info(transcript, language=language)
    extraction["is_demo"] = True
    extraction["simulation"] = True
    _demo_audit("DEMO-USER-ANANYA", "user", "DEMO_VOICE_ANALYZED", "Ran Voice AI extraction on sample transcript")
    return extraction


def create_demo_dispatch(case_id: str) -> Dict[str, Any]:
    cases = _dc("cases")
    dispatches = _dc("dispatches")
    if cases is None or dispatches is None:
        raise RuntimeError("Database unavailable")
    case = cases.find_one({"case_id": case_id})
    if not case:
        raise KeyError("Demo case not found")

    now = datetime.now(timezone.utc)
    did = f"DEMO-DISP-{int(now.timestamp())}-{secrets.token_hex(2).upper()}"
    doc = {
        "dispatch_id": did,
        "case_id": case_id,
        "status": "OFFERED",
        "offered_to": "DEMO-RESP-101",
        "assigned_responder_id": None,
        "responder_label": "Demo Unit Alpha (Mahila Patrol)",
        "distance_m": 420,
        "created_at": now,
        "updated_at": now,
        "assigned_at": None,
        "resolved_at": None,
        "response_time_seconds": None,
        "resolution_time_seconds": None,
        "events": [
            {"state": "OFFERED", "actor": "DEMO-AUTH-PRIYA", "note": "Offer broadcast to Demo Unit Alpha", "at": now.isoformat()},
        ],
        "is_demo": True,
        "simulation": True,
    }
    dispatches.insert_one(doc)
    cases.update_one(
        {"case_id": case_id},
        {
            "$set": {"status": "ACKNOWLEDGED", "updated_at": now},
            "$push": {"timeline": {"status": "ACKNOWLEDGED", "actor": "DEMO-AUTH-PRIYA", "timestamp": now.isoformat()}},
        },
    )
    _demo_audit("DEMO-AUTH-PRIYA", "authority", "DEMO_DISPATCH_CREATED", f"Created isolated demo dispatch {did}", case_id)
    return serialize_doc(doc)


def advance_demo_dispatch(dispatch_id: str, action: str) -> Dict[str, Any]:
    dispatches = _dc("dispatches")
    cases = _dc("cases")
    if dispatches is None or cases is None:
        raise RuntimeError("Database unavailable")
    d = dispatches.find_one({"dispatch_id": dispatch_id})
    if not d:
        raise KeyError("Demo dispatch not found")

    now = datetime.now(timezone.utc)
    mapping = {
        "accept": ("ACCEPTED", "IN_PROGRESS", "DEMO-RESP-101", "Responder accepted offer"),
        "enroute": ("EN_ROUTE", "IN_PROGRESS", "DEMO-RESP-101", "Responder en route to incident"),
        "arrived": ("ARRIVED", "IN_PROGRESS", "DEMO-RESP-101", "Responder arrived at scene"),
        "help_provided": ("HELP_PROVIDED", "IN_PROGRESS", "DEMO-RESP-101", "Assistance delivered"),
        "resolve": ("RESOLVED", "RESOLVED", "DEMO-AUTH-PRIYA", "Authority resolved case"),
    }
    if action not in mapping:
        raise ValueError(f"Unsupported demo dispatch action '{action}'")

    disp_status, case_status, actor, note = mapping[action]
    updates: Dict[str, Any] = {"status": disp_status, "updated_at": now}
    created = d.get("created_at")
    created_dt = created.replace(tzinfo=timezone.utc) if isinstance(created, datetime) and created.tzinfo is None else created

    if action == "accept":
        updates["assigned_responder_id"] = "DEMO-RESP-101"
        updates["assigned_at"] = now
        if isinstance(created_dt, datetime):
            updates["response_time_seconds"] = max(1, int((now - created_dt).total_seconds()))
    if action == "resolve":
        updates["resolved_at"] = now
        if isinstance(created_dt, datetime):
            updates["resolution_time_seconds"] = max(1, int((now - created_dt).total_seconds()))

    dispatches.update_one(
        {"dispatch_id": dispatch_id},
        {"$set": updates, "$push": {"events": {"state": disp_status, "actor": actor, "note": note, "at": now.isoformat()}}},
    )
    cases.update_one(
        {"case_id": d["case_id"]},
        {
            "$set": {"status": case_status, "updated_at": now},
            "$push": {"timeline": {"status": case_status, "actor": actor, "timestamp": now.isoformat()}},
        },
    )
    _demo_audit(actor, "responder" if "RESP" in actor else "authority", f"DEMO_DISPATCH_{disp_status}", note, d["case_id"])
    return serialize_doc(dispatches.find_one({"dispatch_id": dispatch_id}, {"_id": 0}))


def demo_admin_approve_provider(registration_id: str) -> Dict[str, Any]:
    regs = _dc("provider_registrations")
    responders = _dc("responders")
    if regs is None or responders is None:
        raise RuntimeError("Database unavailable")
    reg = regs.find_one({"registration_id": registration_id})
    if not reg:
        raise KeyError("Demo provider registration not found")
    now = datetime.now(timezone.utc)
    regs.update_one(
        {"registration_id": registration_id},
        {"$set": {"status": "APPROVED", "reviewed_by": "DEMO-ADMIN-KAVITA", "reviewed_at": now.isoformat()}},
    )
    rid = reg.get("responder_id")
    if rid:
        responders.update_one(
            {"responder_id": rid},
            {"$set": {"verified": True, "active": True, "duty_status": "ON_DUTY", "status": "AVAILABLE", "updated_at": now}},
        )
    _demo_audit("DEMO-ADMIN-KAVITA", "admin", "DEMO_PROVIDER_APPROVED",
                f"Approved {reg.get('unit_name')} & activated demo responder {rid}")
    return {
        "registration": serialize_doc(regs.find_one({"registration_id": registration_id}, {"_id": 0})),
        "responder": serialize_doc(responders.find_one({"responder_id": rid}, {"_id": 0})) if rid else None,
    }
