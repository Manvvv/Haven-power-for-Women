#!/usr/bin/env python3
"""Seed test responders for development (Phase 3 documentation + Phase 4 testing).

This script provisions multiple test responders with proper locations so the
Rapid Response Network broadcast dispatch can be tested locally. Each responder
is created with:
  - verified=True (admin-approved)
  - active=True
  - status="AVAILABLE" (on duty)
  - current_location with fresh GPS fix near Bengaluru test incident
  - location_updated_at within the 300s freshness window

Usage:
    python seed_dev_responders.py

Environment:
    Set ENVIRONMENT=development (not production)
    MongoDB connection optional (uses in-memory fallback if unavailable)
"""
import sys
from pathlib import Path
from datetime import datetime

# Load .env before imports
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from services.responder_service import (
    create_responder, set_verified, update_location, get_responder, IS_PRODUCTION
)

# Test incident coordinates (Bengaluru-ish, matching test suite and diagnostic)
TEST_INC_LNG, TEST_INC_LAT = 77.5946, 12.9716

# Test responders to seed (each within ~1-5km of test incident)
TEST_RESPONDERS = [
    {
        "badge": "HN-204",
        "name": "Unit Rao",
        "label": "Verified Response Unit HN-204",
        "password": "haven2024",
        "capabilities": ["general", "patrol"],
        "jurisdiction": "Zone-5",
        "lng": 77.5946 + 0.001,  # ~111m east
        "lat": 12.9716 + 0.001,  # ~111m north
    },
    {
        "badge": "HN-205",
        "name": "Unit Sharma",
        "label": "Verified Response Unit HN-205",
        "password": "haven2024",
        "capabilities": ["general", "medical"],
        "jurisdiction": "Zone-5",
        "lng": 77.5946 - 0.002,  # ~222m west
        "lat": 12.9716 + 0.003,  # ~333m north
    },
    {
        "badge": "HN-206",
        "name": "Unit Kumar",
        "label": "Verified Response Unit HN-206",
        "password": "haven2024",
        "capabilities": ["general"],
        "jurisdiction": "Zone-5",
        "lng": 77.5946 + 0.004,  # ~444m east
        "lat": 12.9716 - 0.001,  # ~111m south
    },
]

def main():
    if IS_PRODUCTION:
        print("ERROR: This script is for development only. Do not run in production.")
        print("       Use provision_responder.py for production provisioning.")
        return 1

    print("=" * 70)
    print("SEEDING TEST RESPONDERS FOR DEVELOPMENT")
    print("=" * 70)
    print(f"Test incident location: [{TEST_INC_LNG}, {TEST_INC_LAT}] (Bengaluru)")
    print(f"Seeding {len(TEST_RESPONDERS)} responder(s) nearby...\n")

    seeded_count = 0
    for spec in TEST_RESPONDERS:
        badge = spec["badge"]
        existing = get_responder(badge)

        if existing:
            print(f"[{badge}] Already exists, updating location and status...")
            rid = existing["responder_id"]
        else:
            print(f"[{badge}] Creating new responder account...")
            rec = create_responder(
                badge_number=badge,
                officer_name=spec["name"],
                password=spec["password"],
                display_label=spec["label"],
                capabilities=spec["capabilities"],
                jurisdiction=spec["jurisdiction"],
                active=True,
            )
            rid = rec["responder_id"]
            # Admin-approve the responder
            set_verified(rid, True)
            print(f"    Created & verified: {rid}")

        # Set location (fresh GPS fix)
        update_location(rid, spec["lng"], spec["lat"])
        print(f"    Location set: [{spec['lng']:.6f}, {spec['lat']:.6f}]")

        # Ensure status is AVAILABLE (may already be set by ensure_dev_responder)
        rec = get_responder(badge)
        if rec and rec.get("status") != "AVAILABLE":
            from services.responder_service import _persist
            _persist(rec, {"status": "AVAILABLE"})
            print(f"    Status set: AVAILABLE")
        else:
            print(f"    Status: {rec.get('status') if rec else 'unknown'}")

        print(f"    [OK] {badge} is now eligible for dispatch.\n")
        seeded_count += 1

    print("=" * 70)
    print(f"SUCCESS: Seeded {seeded_count}/{len(TEST_RESPONDERS)} test responder(s).")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Run diagnose_zero_providers.py to verify all are eligible")
    print("  2. Start backend: python main.py")
    print("  3. Open Authority Rapid Response Center in browser")
    print("  4. Metrics should show 3 available providers")
    print("  5. Dispatch help for a test incident to trigger broadcast offers")
    print()
    print("To log in as a test responder:")
    for spec in TEST_RESPONDERS:
        print(f"  - Badge: {spec['badge']}, Password: {spec['password']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
