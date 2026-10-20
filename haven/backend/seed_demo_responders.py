#!/usr/bin/env python3
"""
HAVEN Demo Responder Seeding Script
====================================
Creates 3 HN-DEMO labelled responder accounts near the demo incident coordinates
so the full emergency-dispatch workflow can be demonstrated to hackathon judges.

SAFETY GUARDS (all enforced before any write):
  - Refuses to run when ENVIRONMENT=production (fail-closed).
  - Requires explicit --demo-mode flag.
  - Requires explicit --confirm-env <value> matching HAVEN_STAGING_TARGET_ID or
    the literal string "development".
  - Idempotent: already-existing HN-DEMO accounts are updated in-place; no duplicates.
  - Uses real PBKDF2 password hashing (same algorithm as production).
  - Never bypasses verified/duty_status/location gates — responders start
    verified=True so the demo is exercisable, but they still need to:
      (a) log in and post a fresh location, OR
      (b) use --seed-location to write a fresh location now (explicit flag required).
  - Demo accounts are labelled with "HN-DEMO" in the badge prefix.
  - Never touches non-HN-DEMO responder records.

USAGE:
    python seed_demo_responders.py --demo-mode --confirm-env development
    python seed_demo_responders.py --demo-mode --confirm-env development --seed-location
    python seed_demo_responders.py --demo-mode --confirm-env development --show-credentials
    python seed_demo_responders.py --demo-mode --confirm-env development --seed-location --show-credentials

WHAT IT CREATES:
    Badge        | Category | Capabilities   | Jurisdiction
    HN-DEMO-01   | police   | general        | Zone-Delhi
    HN-DEMO-02   | medical  | medical        | Zone-Delhi
    HN-DEMO-03   | ngo      | general        | Zone-Delhi

    All 3 are created: verified=True, active=True, duty_status=ON_DUTY, status=AVAILABLE.
    Location (when --seed-location): near Delhi (28.6°N, 77.2°E) within 2 km,
    matching the existing dev SOS cases.

CREDENTIALS: printed ONLY when --show-credentials is passed (never logged).
"""
import argparse
import os
import sys
import secrets
from datetime import datetime, timedelta

# ── Safety: must import BEFORE any service modules so the check fires first ──────

def _abort(msg: str) -> None:
    print(f"\nABORTED: {msg}", file=sys.stderr)
    sys.exit(1)


def _check_environment() -> None:
    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    if env == "production":
        _abort(
            "ENVIRONMENT=production detected. This script NEVER runs in production.\n"
            "It creates demo accounts that are not suitable for a live deployment."
        )


_check_environment()  # Runs immediately at import time.

# ── Argument parsing ──────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="HAVEN hackathon demo responder seeder (dev/staging only)."
    )
    parser.add_argument(
        "--demo-mode", action="store_true", required=True,
        help="Required flag. Confirms you intend to seed demo accounts.",
    )
    parser.add_argument(
        "--confirm-env", required=True, metavar="ENV_VALUE",
        help=(
            "Confirm the target environment. Must match HAVEN_STAGING_TARGET_ID "
            "or the literal 'development'."
        ),
    )
    parser.add_argument(
        "--seed-location", action="store_true", default=False,
        help=(
            "Also write a fresh GPS fix near Delhi so responders are immediately "
            "dispatch-eligible without needing to log in first. Requires explicit flag."
        ),
    )
    parser.add_argument(
        "--show-credentials", action="store_true", default=False,
        help="Print demo account credentials to stdout after seeding.",
    )
    return parser.parse_args()


def _validate_confirm_env(confirm_env: str) -> None:
    allowed = {"development"}
    target_id = os.getenv("HAVEN_STAGING_TARGET_ID", "").strip()
    if target_id:
        allowed.add(target_id)
    if confirm_env.strip() not in allowed:
        _abort(
            f"--confirm-env value '{confirm_env}' does not match any allowed "
            f"environment identity.\n"
            f"Allowed: {sorted(allowed)}\n"
            f"Set HAVEN_STAGING_TARGET_ID to use a staging identity."
        )


# ── Demo account definitions ──────────────────────────────────────────────────────

# Near Delhi — matching the existing SOS case coordinates (28.6°N, 77.2°E).
# Offsets keep units within 1-2 km of the incident (inside the 2 km inner wave).
_DEMO_ACCOUNTS = [
    {
        "badge_number": "HN-DEMO-01",
        "officer_name": "Demo Response Unit Alpha",
        "display_label": "Verified Response Unit HN-DEMO-01",
        "capabilities": ["general"],
        "jurisdiction": "Zone-Delhi",
        "provider_category": "police",
        "organization": "HAVEN Demo Network",
        "station_unit": "Alpha-Demo",
        # ~0.5 km north-east of the incident
        "demo_lat": 28.604,
        "demo_lng": 77.206,
    },
    {
        "badge_number": "HN-DEMO-02",
        "officer_name": "Demo Medical Unit Beta",
        "display_label": "Verified Response Unit HN-DEMO-02",
        "capabilities": ["medical"],
        "jurisdiction": "Zone-Delhi",
        "provider_category": "medical",
        "organization": "HAVEN Demo Network",
        "station_unit": "Beta-Demo",
        # ~0.8 km south-west of the incident
        "demo_lat": 28.592,
        "demo_lng": 77.192,
    },
    {
        "badge_number": "HN-DEMO-03",
        "officer_name": "Demo NGO Unit Gamma",
        "display_label": "Verified Response Unit HN-DEMO-03",
        "capabilities": ["general"],
        "jurisdiction": "Zone-Delhi",
        "provider_category": "ngo",
        "organization": "HAVEN Demo Network",
        "station_unit": "Gamma-Demo",
        # ~1.2 km north-west of the incident
        "demo_lat": 28.610,
        "demo_lng": 77.188,
    },
]


# ── Seeding logic ─────────────────────────────────────────────────────────────────

def _generate_password() -> str:
    """Generate a random 16-char alphanumeric password (meets >=12 char minimum)."""
    return secrets.token_urlsafe(12)


def _seed_one(account: dict, password: str, seed_location: bool) -> str:
    """Create or update ONE demo responder. Returns the badge number."""
    from services import responder_service

    badge = account["badge_number"]

    # create_responder is idempotent: upserts on badge_number.
    responder_service.create_responder(
        badge_number=badge,
        officer_name=account["officer_name"],
        password=password,
        display_label=account["display_label"],
        capabilities=account["capabilities"],
        jurisdiction=account["jurisdiction"],
        provider_category=account["provider_category"],
        organization=account["organization"],
        station_unit=account["station_unit"],
        active=True,
    )

    # Admin-verify the demo account so it is eligible immediately.
    responder_service.set_verified(f"RESP-{badge}", True)

    # Bring on duty (sets duty_status=ON_DUTY).
    rec = responder_service.get_responder(badge)
    if rec is None:
        raise RuntimeError(f"Responder {badge} not found after create.")
    responder_service._persist(rec, {"duty_status": "ON_DUTY", "status": "AVAILABLE"})

    # Optionally write a fresh GPS fix.
    if seed_location:
        lat = account["demo_lat"]
        lng = account["demo_lng"]
        # Use server arrival time (no device clock skew issue).
        responder_service._persist(
            responder_service.get_responder(badge),
            {
                "current_location": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "location_updated_at": datetime.utcnow(),
            },
        )
        print(f"  [{badge}] Location seeded: {lat}N, {lng}E (fresh, within 2 km of case)")
    else:
        print(f"  [{badge}] Created/updated (no location seeded - log in and POST /responder/location)")

    return badge


def main() -> None:
    args = _parse_args()

    if not args.demo_mode:
        _abort("--demo-mode flag is required.")

    _validate_confirm_env(args.confirm_env)

    # Add backend directory to path so service imports work.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Import service modules AFTER environment check.
    from services import responder_service  # noqa: F401 (ensures module is loaded)

    print("\n=========================================================")
    print("  HAVEN Demo Responder Seeding -- Non-Production Only")
    print("=========================================================")
    print(f"  Target environment: {args.confirm_env}")
    print(f"  Seed location now:  {args.seed_location}")
    print(f"  Accounts to seed:   {len(_DEMO_ACCOUNTS)}")
    print()

    credentials: list[dict] = []
    for account in _DEMO_ACCOUNTS:
        pw = _generate_password()
        badge = _seed_one(account, pw, args.seed_location)
        credentials.append({"badge": badge, "password": pw})

    print()
    print("All demo accounts seeded successfully.")

    if args.show_credentials:
        print()
        print("-" * 60)
        print("  DEMO CREDENTIALS (shown once -- keep these secure)")
        print("-" * 60)
        for c in credentials:
            print(f"  Badge: {c['badge']:<18}  Password: {c['password']}")
        print("-" * 60)
        print()
        print("  Login URL (responder): /responder/login")
        print("  Badge format: e.g. HN-DEMO-01")
        print()
    else:
        print()
        print("  Run with --show-credentials to display passwords.")

    if not args.seed_location:
        print()
        print("  NOTE: Responders are ON_DUTY + AVAILABLE but have NO fresh location.")
        print("  To make them dispatch-eligible NOW, run with --seed-location, OR")
        print("  have each responder log in and POST to /responder/location.")
        print("  Location freshness window: 300 seconds (5 minutes).")

    print()
    print("  NEXT STEPS FOR THE DEMO:")
    print("  1. Open an SOS case (or use existing VSOS-* cases) in the authority dashboard.")
    print("  2. Authority: Rapid Response -> select case -> click 'Dispatch Help'.")
    print("  3. Responder logs in at /responder and sees the dispatch offer.")
    print("  4. Responder clicks Accept -> status changes EN_ROUTE / ARRIVED / HELP_PROVIDED.")
    print("  5. Authority sees live status in the Rapid Response Center.")
    print()


if __name__ == "__main__":
    main()
