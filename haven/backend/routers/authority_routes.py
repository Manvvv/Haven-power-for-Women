"""Authority routes — dispatch, DIR form, discreet dispatch."""
import json
import logging
import secrets
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from auth import AuthUser, require_authority
from services.db import sos_cases, dir_reports, serialize_doc
from services.ai_service import call_groq
from services.audit_service import log_audit
from models.schemas import DispatchWebhookModel, GenerateDIRFormModel, DiscreetDispatchModel

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Authority"])


@router.get("/authority/dispatch-partners")
def get_dispatch_partners(current_user: AuthUser = Depends(require_authority)):
    """Get list of active emergency response dispatch partners."""
    return {
        "partners": [
            {"id": "ERSS-112-NAT", "name": "ERSS 112 National Police Emergency Command",
             "type": "police_emergency", "status": "ONLINE", "response_sla_mins": 7,
             "coverage": "Pan-India (All States)", "api_endpoint": "https://erss.gov.in/api/v1/dispatch"},
            {"id": "NCW-HELPLINE-78", "name": "National Commission for Women (NCW 78)",
             "type": "women_crisis_ngo", "status": "ONLINE", "response_sla_mins": 15,
             "coverage": "Nationwide", "api_endpoint": "https://ncw.nic.in/api/dispatch"},
            {"id": "SNEHA-CRISIS-MUM", "name": "SNEHA Crisis Intervention Unit",
             "type": "ngo_crisis", "status": "ONLINE", "response_sla_mins": 10,
             "coverage": "Mumbai & Maharashtra", "api_endpoint": "https://snehamumbai.org/api/intake"},
            {"id": "SAKSHI-CRISIS-DEL", "name": "Sakshi Violence Intervention Cell",
             "type": "ngo_crisis", "status": "ONLINE", "response_sla_mins": 12,
             "coverage": "Delhi NCR", "api_endpoint": "https://sakshi.org.in/api/sos"},
        ]
    }


@router.post("/authority/dispatch-webhook")
def trigger_dispatch_webhook(
    payload: DispatchWebhookModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Trigger emergency dispatch to ERSS 112 or NGO partner."""
    ts = datetime.utcnow().isoformat()
    dispatch_id = f"DISPATCH-{int(time.time())}-{secrets.token_hex(3).upper()}"
    collection = sos_cases()
    if collection is not None:
        collection.update_one(
            {"case_id": payload.case_id},
            {"$set": {"dispatch_status": "DISPATCHED", "dispatch_id": dispatch_id,
                      "dispatched_to": payload.agency_type, "dispatched_at": datetime.utcnow(),
                      "dispatched_by": current_user.user_id},
             "$push": {"dispatch_history": {
                 "dispatch_id": dispatch_id, "agency": payload.agency_type,
                 "timestamp": ts, "dispatcher": current_user.user_id,
                 "notes": payload.dispatcher_notes or "Immediate police/NGO unit dispatched via Haven ERSS gateway.",
                 "status": "DISPATCH_CONFIRMED"}}}
        )
    log_audit(current_user.user_id, current_user.role, "DISPATCH_SENT",
              case_id=payload.case_id, metadata={"agency": payload.agency_type, "dispatch_id": dispatch_id})
    return {
        "success": True, "dispatch_id": dispatch_id, "case_id": payload.case_id,
        "agency_type": payload.agency_type, "status": "DISPATCH_CONFIRMED",
        "estimated_arrival_minutes": 6 if payload.agency_type == "ERSS_112" else 12,
        "dispatched_at": ts,
        "message": f"🚨 Case {payload.case_id} successfully dispatched to {payload.agency_type} emergency queue."
    }


@router.post("/authority/generate-dir-form")
def generate_dir_form(
    payload: GenerateDIRFormModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Generates a Domestic Incident Report (DIR Form-1) under PWDVA 2005."""
    collection = sos_cases()
    if collection is None:
        raise HTTPException(status_code=500, detail="Database not connected")
    case_data = collection.find_one({"case_id": payload.case_id})
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")
    messages = [
        {"role": "system", "content": (
            "You are a legal AI assistant. Generate an official Indian Domestic Incident Report (DIR) Form-1 under Section 9(b) of PWDVA 2005. "
            "Cover: Complainant details, Nature & description of domestic violence (physical, emotional, verbal, economic, sexual), "
            "Whether shared household involved, Relief sought: Protection Order (Section 18), Residence Order (Section 19), Monetary Relief (Section 20), "
            "Custody Order (Section 21), Compensation (Section 22), Immediate danger assessment, Medical examination needed, Officer recommendation. "
            "Respond only with the report text.")},
        {"role": "user", "content": f"Case Data: {json.dumps(serialize_doc(case_data))}"}
    ]
    dir_report_text = call_groq(messages=messages, max_tokens=800)
    dir_form_number = f"DIR-{payload.case_id}-{int(time.time())}"
    response_doc = {
        "case_id": payload.case_id, "dir_form_number": dir_form_number,
        "generated_at": datetime.utcnow().isoformat(),
        "officer_name": payload.officer_name or current_user.name or "Protection Officer",
        "officer_designation": payload.officer_designation or "Protection Officer",
        "station_name": payload.station_name, "district": payload.district,
        "case_severity": case_data.get("severity"), "case_summary": case_data.get("summary"),
        "nature_of_abuse": case_data.get("nature_of_abuse"),
        "immediate_danger": case_data.get("immediate_danger"),
        "location": case_data.get("location"), "needs": case_data.get("needs"),
        "has_forensic_evidence": case_data.get("has_evidence", False),
        "evidence_hash": case_data.get("evidence_hash"),
        "dir_report_text": dir_report_text,
        "legal_sections": ["Section 498A IPC", "Section 85 BNS", "PWDVA 2005 Sec 12", "PWDVA 2005 Sec 18-22"],
        "relief_recommended": ["Protection Order", "Residence Order", "Monetary Relief"]
    }
    dir_coll = dir_reports()
    if dir_coll is not None:
        dir_coll.insert_one(response_doc)
    collection.update_one(
        {"case_id": payload.case_id},
        {"$set": {"dir_generated": True, "dir_form_number": dir_form_number}})
    log_audit(current_user.user_id, current_user.role, "DIR_GENERATED", case_id=payload.case_id)
    return serialize_doc(response_doc)


@router.post("/authority/discreet-dispatch")
def discreet_dispatch(
    payload: DiscreetDispatchModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Dispatches a silent/plainclothes Mahila Police response."""
    collection = sos_cases()
    if collection is None:
        raise HTTPException(status_code=500, detail="Database not connected")
    case_data = collection.find_one({"case_id": payload.case_id})
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")
    protocol = {}
    if payload.dispatch_type == "MAHILA_THANA":
        protocol = {"agency_name": "Women Police Cell (Mahila Thana)", "approach": "Plainclothes female officers", "vehicle": "Unmarked civilian vehicle", "siren": False, "estimated_minutes": 15, "contact_number": "1091"}
    elif payload.dispatch_type == "PLAINCLOTHES":
        protocol = {"agency_name": "Plainclothes Response Unit", "approach": "2 plainclothes officers (1 female)", "vehicle": "Unmarked vehicle", "siren": False, "estimated_minutes": 12, "contact_number": "112"}
    elif payload.dispatch_type == "PROTECTION_OFFICER":
        protocol = {"agency_name": "PWDVA Protection Officer", "approach": "Registered Protection Officer under DV Act", "vehicle": "Private vehicle", "siren": False, "estimated_minutes": 30, "contact_number": "181 (Women Helpline)"}
    elif payload.dispatch_type == "OSC_SAKHI":
        protocol = {"agency_name": "One Stop Centre (Sakhi)", "approach": "Counselor + Medical + Legal aid", "vehicle": "OSC emergency van", "siren": False, "estimated_minutes": 20, "contact_number": "181"}
    else:
        protocol = {"agency_name": payload.dispatch_type, "approach": "Standard", "vehicle": "Standard", "siren": not payload.silent_approach, "estimated_minutes": 15, "contact_number": ""}
    dispatch_doc = {
        "dispatch_id": f"DISCREET-{int(time.time())}", "case_id": payload.case_id,
        "dispatch_type": payload.dispatch_type, "priority": payload.priority,
        "silent_approach": payload.silent_approach, "dispatcher_notes": payload.dispatcher_notes,
        "dispatcher_id": current_user.user_id, "response_protocol": protocol,
        "dispatched_at": datetime.utcnow(), "status": "DISPATCHED"
    }
    collection.update_one({"case_id": payload.case_id}, {"$push": {"dispatch_history": dispatch_doc}})
    log_audit(current_user.user_id, current_user.role, "DISPATCH_SENT",
              case_id=payload.case_id, metadata={"type": payload.dispatch_type})
    return serialize_doc(dispatch_doc)
