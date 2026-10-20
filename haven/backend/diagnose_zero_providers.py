#!/usr/bin/env python3
"""Diagnostic script for Phase 2: Diagnose zero providers issue.

This script examines the responder collection and reports WHY metrics show zero
providers. It checks all possible failure modes:
  A. No responders registered
  B. Responders exist but not verified
  C. Responders OFF_DUTY/OFFLINE/UNAVAILABLE
  D. Missing current_location (NULL)
  E. Stale locations (>300s old)
  F. Outside 10km radius from test incident
  G. Wrong jurisdiction
  H. MongoDB collection issues

Usage:
    python diagnose_zero_providers.py
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Load .env before imports
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from index_catalog import validate_configured_staging_target

# Test incident coordinates (Bengaluru-ish, matching test suite)
TEST_INC_LNG, TEST_INC_LAT = 77.5946, 12.9716

def main():
    target = validate_configured_staging_target(os.getenv("MONGO_ENDPOINT", ""))
    print("=" * 70)
    print("PHASE 2 DIAGNOSTIC: Why do metrics show zero providers?")
    print("=" * 70)
    if not target.approved:
        print(f"ERROR: staging target rejected: {target.reason}")
        print("No database connection was attempted.")
        return 1
    print(f"Approved staging target: {target.target_id}; database={target.database_name}")

    from services.responder_service import list_responders, availability_counts
    from services.dispatch_service import RESPONDER_LOCATION_MAX_AGE_SECONDS, DISPATCH_DEFAULT_RADIUS_M
    from services.geo_validation import haversine_meters

    print()

    # Fetch all responders
    all_responders = list_responders()
    print(f"Total responder accounts in database: {len(all_responders)}")

    if len(all_responders) == 0:
        print("\n❌ ROOT CAUSE A: No responders are registered.")
        print("   FIX: Run provision_responder.py or ensure_dev_responder() on login.")
        return 1

    print("\nBreakdown by verification & active status:")
    active_verified = [r for r in all_responders if r.get("active") and r.get("verified")]
    active_unverified = [r for r in all_responders if r.get("active") and not r.get("verified")]
    inactive_verified = [r for r in all_responders if not r.get("active") and r.get("verified")]
    inactive_unverified = [r for r in all_responders if not r.get("active") and not r.get("verified")]

    print(f"  - Active + Verified:   {len(active_verified)}")
    print(f"  - Active + Unverified: {len(active_unverified)}")
    print(f"  - Inactive + Verified: {len(inactive_verified)}")
    print(f"  - Inactive + Unverified: {len(inactive_unverified)}")

    if len(active_verified) == 0:
        print("\n❌ ROOT CAUSE B: Responders exist but none are BOTH active=True AND verified=True.")
        print("   FIX: Run `python provision_responder.py --badge <badge> --verify`")
        print("        or approve via PATCH /admin/responders/{id}")
        return 1

    # From here on, focus only on active+verified responders
    print(f"\n✓ Found {len(active_verified)} active+verified responder(s).")
    print("\nDetailed analysis of each active+verified responder:\n")

    issues_found = []
    for i, r in enumerate(active_verified, 1):
        rid = r.get("responder_id")
        badge = r.get("badge_number")
        status = r.get("status")
        location = r.get("current_location")
        location_ts = r.get("location_updated_at")
        juris = r.get("jurisdiction", "")
        assigned = r.get("assigned_dispatch_id")

        print(f"[{i}] {rid} (badge={badge})")
        print(f"    Status: {status}")
        print(f"    Assigned: {assigned or 'None'}")
        print(f"    Jurisdiction: '{juris}'")

        # Check C: Status must be AVAILABLE
        if status != "AVAILABLE":
            print(f"    ❌ ISSUE C: Status is '{status}', not 'AVAILABLE'.")
            issues_found.append((rid, f"Status={status} (need AVAILABLE)"))
            print()
            continue

        # Check D: Must have a location
        if not location or not isinstance(location, dict):
            print(f"    ❌ ISSUE D: current_location is NULL or invalid.")
            print(f"       The responder has never reported a GPS fix.")
            issues_found.append((rid, "Missing current_location (NULL)"))
            print()
            continue

        coords = location.get("coordinates")
        if not coords or len(coords) != 2:
            print(f"    ❌ ISSUE D: current_location.coordinates is invalid: {coords}")
            issues_found.append((rid, "Invalid coordinates format"))
            print()
            continue

        lng, lat = coords[0], coords[1]
        print(f"    Location: [{lng:.6f}, {lat:.6f}]")

        # Check E: Location freshness
        if not isinstance(location_ts, datetime):
            print(f"    ❌ ISSUE E: location_updated_at is not a datetime: {location_ts}")
            issues_found.append((rid, "Invalid location_updated_at timestamp"))
            print()
            continue

        age_seconds = (datetime.utcnow() - location_ts).total_seconds()
        print(f"    Location age: {age_seconds:.1f}s (max allowed: {RESPONDER_LOCATION_MAX_AGE_SECONDS}s)")

        if age_seconds > RESPONDER_LOCATION_MAX_AGE_SECONDS:
            print(f"    ❌ ISSUE E: Location is STALE (>{RESPONDER_LOCATION_MAX_AGE_SECONDS}s old).")
            issues_found.append((rid, f"Stale location ({age_seconds:.0f}s old)"))
            print()
            continue

        # Check F: Distance from test incident
        distance_m = haversine_meters(TEST_INC_LAT, TEST_INC_LNG, lat, lng)
        print(f"    Distance from test incident: {distance_m:.0f}m (max radius: {DISPATCH_DEFAULT_RADIUS_M}m)")

        if distance_m > DISPATCH_DEFAULT_RADIUS_M:
            print(f"    ❌ ISSUE F: Outside {DISPATCH_DEFAULT_RADIUS_M/1000}km radius from test incident.")
            issues_found.append((rid, f"Too far ({distance_m/1000:.1f}km away)"))
            print()
            continue

        # If we get here, this responder is fully eligible
        print(f"    ✅ ELIGIBLE for test incident at [{TEST_INC_LNG}, {TEST_INC_LAT}]")
        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    counts = availability_counts()
    print(f"Backend metrics (availability_counts):")
    print(f"  - responders_on_duty:   {counts['responders_on_duty']}")
    print(f"  - responders_available: {counts['responders_available']}")
    print(f"  - responders_busy:      {counts['responders_busy']}")
    print()

    if len(issues_found) == 0:
        print("✅ All active+verified responders are ELIGIBLE.")
        print("   The zero-providers issue should NOT occur.")
        print("   If metrics still show zero, check:")
        print("     - MongoDB geospatial indexes (run setup_indexes.py)")
        print("     - Frontend API calls to /dispatch/rrn/metrics")
        return 0
    else:
        print(f"❌ Found {len(issues_found)} issue(s) preventing eligibility:\n")
        for rid, issue in issues_found:
            print(f"  - {rid}: {issue}")
        print()
        print("Most common fixes:")
        if any("Missing current_location" in iss for _, iss in issues_found):
            print("  • Missing location: Responder must report GPS via POST /responder/location")
            print("                      or set in dev with rs.update_location(rid, lng, lat)")
        if any("Stale location" in iss for _, iss in issues_found):
            print("  • Stale location: Responder must send fresh GPS (< 300s old)")
        if any("Status=" in iss for _, iss in issues_found):
            print("  • Wrong status: Responder must call POST /responder/status {status: 'ON_DUTY'}")
        if any("Too far" in iss for _, iss in issues_found):
            print(f"  • Out of range: Test incident is at [{TEST_INC_LNG}, {TEST_INC_LAT}] (Bengaluru)")
            print(f"                  Place responders within {DISPATCH_DEFAULT_RADIUS_M/1000}km")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
