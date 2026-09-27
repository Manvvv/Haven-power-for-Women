"""Analytics routes — dashboard metrics for authorities.

All metrics are computed live from stored documents (Phase 16). Acknowledgement
and resolution times are derived from the real sos_status_history transition
timestamps — nothing is hardcoded. When there is not yet enough data to compute
a duration, the field is returned as null (not a fabricated number).
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from auth import AuthUser, require_authority
from services.db import sos_cases, sos_events, sos_status_history, serialize_doc

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Analytics"])

# Case-insensitive status buckets (data mixes legacy lowercase + canonical upper).
_PENDING = ["pending", "CREATED", "ENCODED", "SHARED", "RECEIVED", "DECODED", "AI_ANALYZED"]
_IN_PROGRESS = ["active", "IN_PROGRESS", "ACKNOWLEDGED"]
_RESOLVED = ["resolved", "RESOLVED"]


def _avg_minutes_to(target_states: list) -> dict:
    """Average minutes from case creation to the FIRST transition into any of
    `target_states`, computed from real status-history timestamps.

    Returns {"avg_minutes": float|None, "median_minutes": float|None, "n": int}.
    None (never a fake number) when no completed transitions exist yet.
    """
    history = sos_status_history()
    if history is None:
        return {"avg_minutes": None, "median_minutes": None, "n": 0}

    # Earliest transition into a target state per case.
    pipeline = [
        {"$match": {"to_status": {"$in": [s.upper() for s in target_states]}}},
        {"$group": {"_id": "$case_id", "reached_at": {"$min": "$timestamp"}}},
    ]
    reached = {r["_id"]: r["reached_at"] for r in history.aggregate(pipeline)}
    if not reached:
        return {"avg_minutes": None, "median_minutes": None, "n": 0}

    cases = sos_cases()
    durations = []
    for case_id, reached_at in reached.items():
        case = cases.find_one({"case_id": case_id}, {"created_at": 1}) if cases is not None else None
        created = case.get("created_at") if case else None
        if not created or not hasattr(reached_at, "timestamp") or not hasattr(created, "timestamp"):
            continue
        delta_min = (reached_at - created).total_seconds() / 60.0
        if delta_min >= 0:  # guard against clock skew / bad data
            durations.append(delta_min)

    if not durations:
        return {"avg_minutes": None, "median_minutes": None, "n": 0}
    durations.sort()
    n = len(durations)
    median = durations[n // 2] if n % 2 else (durations[n // 2 - 1] + durations[n // 2]) / 2
    return {"avg_minutes": round(sum(durations) / n, 1), "median_minutes": round(median, 1), "n": n}


@router.get("/analytics/dashboard")
def analytics_dashboard(current_user: AuthUser = Depends(require_authority)):
    """Get aggregated SOS metrics for authority dashboard (all computed live)."""
    collection = sos_cases()
    if collection is None:
        return {"total_sos": 0, "pending": 0, "in_progress": 0, "resolved": 0,
                "critical": 0, "high": 0, "avg_ack_time_mins": None,
                "avg_resolution_time_mins": None}

    def ci(states):
        return {"$in": [s for st in states for s in (st, st.upper(), st.lower())]}

    total = collection.count_documents({})
    pending = collection.count_documents({"status": ci(_PENDING)})
    in_progress = collection.count_documents({"status": ci(_IN_PROGRESS)})
    resolved = collection.count_documents({"status": ci(_RESOLVED)})
    critical = collection.count_documents({"severity": {"$regex": "^critical$", "$options": "i"}})
    high = collection.count_documents({"severity": {"$regex": "^high$", "$options": "i"}})

    ack = _avg_minutes_to(["ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED"])
    res = _avg_minutes_to(["RESOLVED"])

    events_coll = sos_events()
    voice_total = events_coll.count_documents({"trigger_type": "voice_code"}) if events_coll is not None else 0
    voice_tests = events_coll.count_documents({"trigger_type": "test"}) if events_coll is not None else 0

    return {
        "total_sos": total, "pending": pending, "in_progress": in_progress,
        "resolved": resolved, "critical": critical, "high": high,
        "voice_activations": voice_total, "voice_tests": voice_tests,
        # Real, computed metrics. null (not "N/A"/0) when insufficient data.
        "avg_ack_time_mins": ack["avg_minutes"],
        "median_ack_time_mins": ack["median_minutes"],
        "ack_sample_size": ack["n"],
        "avg_resolution_time_mins": res["avg_minutes"],
        "median_resolution_time_mins": res["median_minutes"],
        "resolution_sample_size": res["n"],
    }


@router.get("/analytics/severity-distribution")
def severity_distribution(current_user: AuthUser = Depends(require_authority)):
    """Group cases by severity."""
    collection = sos_cases()
    if collection is None:
        return {"distribution": []}
    pipeline = [
        {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    results = list(collection.aggregate(pipeline))
    return {"distribution": [{"severity": r["_id"] or "unknown", "count": r["count"]} for r in results]}


@router.get("/analytics/type-distribution")
def type_distribution(current_user: AuthUser = Depends(require_authority)):
    """Group cases by trigger type."""
    collection = sos_cases()
    if collection is None:
        return {"distribution": []}
    pipeline = [
        {"$group": {"_id": "$trigger_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    results = list(collection.aggregate(pipeline))
    return {"distribution": [{"type": r["_id"] or "unknown", "count": r["count"]} for r in results]}


@router.get("/analytics/timeline")
def cases_timeline(current_user: AuthUser = Depends(require_authority)):
    """Cases grouped by date (last 30 days)."""
    collection = sos_cases()
    if collection is None:
        return {"timeline": []}
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    pipeline = [
        {"$match": {"created_at": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    results = list(collection.aggregate(pipeline))
    return {"timeline": [{"date": r["_id"], "count": r["count"]} for r in results]}


@router.get("/voice-sos/analytics")
def voice_sos_analytics(current_user: AuthUser = Depends(require_authority)):
    """Get aggregated Voice SOS analytics (Authority Only)."""
    events_coll = sos_events()
    if events_coll is None:
        return {"total_activations": 0, "test_activations": 0}
    total = events_coll.count_documents({"trigger_type": "voice_code"})
    tests = events_coll.count_documents({"trigger_type": "test"})
    failed = events_coll.count_documents({"status": "failed"})
    return {
        "total_activations": total, "test_activations": tests,
        "successful_alerts": total - failed, "failed_alerts": failed,
    }
