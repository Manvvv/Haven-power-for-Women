"""
Haven MongoDB Pre-flight Index Check
======================================
Run this BEFORE setup_indexes.py to verify that all planned unique
indexes can be created safely.

READ-ONLY: performs no writes, creates no indexes, deletes nothing.
Connects only to an explicitly configured staging target whose MongoDB
hosts and database match exact allowlists. It refuses production mode.

Usage:
    python preflight_index_check.py          (from haven/backend)
    python backend/preflight_index_check.py  (from haven/)

MONGO_ENDPOINT and the staging allowlist must be configured in backend/.env
or the process environment. `--check-target` validates these settings
without connecting; `--show-index-plan` displays planned operations offline.
The script never prints connection strings, credentials, or hostnames.

Exit codes:
    0 — no blockers; unique-index creation is not known to be unsafe
    1 — one or more blockers found, or the database could not be reached

Importing this module does not connect to MongoDB.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from index_catalog import (
    HAVEN_DATABASE_NAME,
    format_index_plan,
    format_preflight_report,
    run_preflight,
    sanitize_error,
    validate_configured_staging_target,
)


def main() -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="Read-only HAVEN index preflight")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-target", action="store_true",
                       help="validate staging configuration without connecting")
    modes.add_argument("--show-index-plan", action="store_true",
                       help="display planned indexes without connecting")
    args = parser.parse_args()

    if args.show_index_plan:
        print(format_index_plan())
        return 0

    ep = os.getenv("MONGO_ENDPOINT", "")
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    target = validate_configured_staging_target(ep)

    print("Haven MongoDB Pre-flight Index Check")
    if not target.approved:
        print(f"ERROR: staging target rejected: {target.reason}")
        print("       No database connection was attempted.")
        return 1

    print("Target environment : staging (explicitly approved)")
    print(f"Approved target ID : {target.target_id}")
    print(f"Application mode   : {environment}")
    print(f"Database name      : {target.database_name}")
    print("MongoDB host        : approved allowlist match (not displayed)")
    print("=" * 60)

    if args.check_target:
        print("TARGET APPROVED — no database connection was attempted.")
        return 0

    if not ep:
        print("ERROR: MONGO_ENDPOINT is not set.")
        return 1

    client = None
    try:
        client = MongoClient(ep, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Cannot connect to MongoDB: {sanitize_error(e)}")
        print("       Verify staging service availability, network access, and credentials privately.")
        return 1
    try:
        db = client[HAVEN_DATABASE_NAME]
        label = f"staging:{target.target_id} | mode={environment}"
        result = run_preflight(db, environment_label=label)
        print(format_preflight_report(result))
        return 0 if result.ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
