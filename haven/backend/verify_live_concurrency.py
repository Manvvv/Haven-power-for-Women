"""Live MongoDB concurrency check for the first-acceptance-wins barrier.

Writes ONLY to clearly-marked test documents (badge prefix LIVE-TEST-, dispatch
case prefix LIVE-TEST-CASE-) and removes them afterwards. Never run in production.

What it proves (against the configured MONGO_ENDPOINT):
  * N concurrent accepts for one dispatch -> exactly one winner.
  * The winner's responder record is BUSY and bound to that dispatch.
What it does NOT prove:
  * Cross-process Redis coordination. The Redis fast-lock is exercised only if the
    rate limiter resolves to the redis backend; this script reports which backend
    was actually used.

Usage (from backend/):  python verify_live_concurrency.py
"""
import os
import sys
import threading
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from index_catalog import validate_configured_staging_target

PREFIX = "LIVE-TEST-"
N = 5
INC_LNG, INC_LAT = 77.5946, 12.9716


def cleanup():
    target = validate_configured_staging_target(os.getenv("MONGO_ENDPOINT", ""))
    if not target.approved or os.getenv("HAVEN_ALLOW_LIVE_CONCURRENCY_TEST") != "YES":
        return False
    from services.db import responders, dispatch_requests, dispatch_attempts, response_events
    for coll, key in ((responders(), "badge_number"), (dispatch_requests(), "case_id"),
                      (dispatch_attempts(), None), (response_events(), None)):
        if coll is None:
            continue
        if key == "badge_number":
            coll.delete_many({"badge_number": {"$regex": f"^{PREFIX}"}})
        elif key == "case_id":
            coll.delete_many({"case_id": {"$regex": f"^{PREFIX}CASE"}})
        else:
            coll.delete_many({"dispatch_id": {"$exists": True}, "responder_id": {"$regex": "^RESP-LIVE-TEST-"}})
    return True


def main() -> int:
    target = validate_configured_staging_target(os.getenv("MONGO_ENDPOINT", ""))
    if not target.approved:
        print(f"ABORT: staging target rejected: {target.reason}")
        print("No database connection or write was attempted.")
        return 2
    if os.getenv("HAVEN_ALLOW_LIVE_CONCURRENCY_TEST") != "YES":
        print("ABORT: set HAVEN_ALLOW_LIVE_CONCURRENCY_TEST=YES after staging approval.")
        print("No database connection or write was attempted.")
        return 2

    print(f"Approved staging target: {target.target_id}; database={target.database_name}")
    from services import dispatch_service as ds
    from services import responder_service as rs
    import rate_limiter

    mode, _client = rate_limiter._resolve_backend()
    print(f"rate-limiter backend in use: {mode}")
    if rs.responders() is None:
        print("ABORT: responders collection not reachable on Mongo.")
        return 2

    cleanup()
    try:
        ids = []
        for i in range(N):
            badge = f"{PREFIX}{i:02d}"
            rs.create_responder(badge_number=badge, officer_name="Live Test",
                                password="live-test-" + badge, display_label=f"Test Unit {badge}",
                                capabilities=[], jurisdiction="", active=True)
            rec = rs.get_responder(badge)
            rs.set_verified(rec["responder_id"], True)
            rs._persist(rec, {
                "duty_status": "ON_DUTY", "status": "AVAILABLE",
                "current_location": {"type": "Point", "coordinates": [INC_LNG, INC_LAT + 0.001 * (i + 1)]},
                "location_updated_at": datetime.utcnow(),
            })
            ids.append(rs.get_responder(badge)["responder_id"])

        res = ds.create_dispatch(case_id=f"{PREFIX}CASE-1", created_by="LIVE-TEST",
                                 created_by_role="authority",
                                 incident_lng=INC_LNG, incident_lat=INC_LAT)
        did = (res.get("dispatch") or {}).get("dispatch_id")
        if not did:
            print("ABORT: dispatch was not created; inspect staging service logs privately.")
            return 3
        print(f"dispatch {did} offered to {res.get('eligible_provider_count')} providers")

        results = []
        barrier = threading.Barrier(len(ids))

        def go(rid):
            barrier.wait()
            _d, err, _n = ds.accept_offer(did, rid)
            results.append((rid, err))

        threads = [threading.Thread(target=go, args=(rid,)) for rid in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [rid for rid, err in results if err is None]
        print(f"concurrent accepts: {len(results)}, winners: {len(winners)}")
        d = ds.get_dispatch(did)
        bound = d.get("assigned_responder_id")
        ok = len(winners) == 1 and bound == winners[0]
        if ok:
            print("RESULT: PASS - exactly one winner, dispatch bound to winner")
        else:
            print("RESULT: FAIL - winners=%d bound=%s" % (len(winners), bound))
        return 0 if ok else 1
    finally:
        cleanup()
        print("cleanup: LIVE-TEST documents removed")


if __name__ == "__main__":
    sys.exit(main())
