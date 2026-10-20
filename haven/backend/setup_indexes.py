"""
Haven — MongoDB Index Setup
============================
Creates all required indexes for the Haven database.

IDEMPOTENT: safe to run more than once. MongoDB will skip an index
that already exists with identical key-pattern and options, and will
raise a descriptive error if the same key-pattern is requested with
conflicting options. Re-running will not silently overwrite a
conflicting definition. This script NEVER drops indexes and NEVER
mutates collection documents.

OPERATOR WORKFLOW:
    1. Configure and verify the explicitly allowlisted staging target.
  2. Take a MongoDB snapshot/backup.
  3. Run backend/preflight_index_check.py (read-only) and confirm exit 0.
  4. Review blockers/conflicts.
    5. Set HAVEN_ALLOW_INDEX_SETUP=YES and run this only against approved staging:
       python setup_indexes.py
  6. Verify the printed OK/ERR lines.

ENVIRONMENT:
  Set MONGO_ENDPOINT in backend/.env before running.
  The script prints which database environment it targets but never
  prints the connection-string value itself.

This script rejects production mode and any target that is not explicitly
allowlisted as staging. It never drops indexes or modifies collection documents.

Importing this module does not connect to MongoDB or create indexes.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, GEOSPHERE, MongoClient
from pymongo.errors import OperationFailure

from index_catalog import (
    ATLAS_SEARCH_INDEX_PLANS,
    HAVEN_DATABASE_NAME,
    INDEX_SETUP_CONFIRM_VALUE,
    STANDARD_INDEX_OPS,
    confirm_index_setup_authorized,
    create_kwargs,
    format_preflight_report,
    run_preflight,
    sanitize_error,
    validate_configured_staging_target,
)

_DIR_MAP = {1: ASCENDING, -1: DESCENDING, "2dsphere": GEOSPHERE}


def main() -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    ep = os.getenv("MONGO_ENDPOINT", "")
    target = validate_configured_staging_target(ep)

    print("Haven MongoDB Index Setup")
    if not target.approved:
        print(f"ERROR: staging target rejected: {target.reason}")
        print("       Aborting before database connection or mutation.")
        return 1

    print("Target environment : staging (explicitly approved)")
    print(f"Approved target ID : {target.target_id}")
    print(f"Application mode   : {environment}")
    print(f"Database name      : {target.database_name}")
    print("MongoDB host        : approved allowlist match (not displayed)")
    print("=" * 60)

    if not ep:
        print("ERROR: MONGO_ENDPOINT is not set. Aborting.")
        return 1

    if not confirm_index_setup_authorized():
        print(
            "ERROR: staging index creation requires "
            f"HAVEN_ALLOW_INDEX_SETUP={INDEX_SETUP_CONFIRM_VALUE} in the process "
            "environment (not stored in git). Aborting without connecting."
        )
        return 1

    try:
        client = MongoClient(ep, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Cannot connect to MongoDB: {sanitize_error(e)}")
        return 1

    db = client[HAVEN_DATABASE_NAME]

    print("\n[Preflight] running read-only unique-index checks")
    result = run_preflight(
        db, environment_label=f"staging:{target.target_id} | mode={environment}"
    )
    print(format_preflight_report(result))
    if not result.ok:
        print("\nSETUP ABORTED — preflight blockers must be resolved first.")
        print("No indexes were created or dropped in this run after the failed preflight.")
        return 1

    errors = []
    warnings = []

    def _idx(collection_name, keys, **kwargs):
        """Create an index. Never drops an existing index."""
        coll = db[collection_name]
        key_str = ", ".join(
            f"{k} {'ASC' if d == ASCENDING else 'DESC' if d == DESCENDING else d}"
            for k, d in keys
        )
        opts_str = " ".join(f"{k}={v}" for k, v in kwargs.items() if k != "name")
        label = f"[{collection_name}] ({key_str}) {opts_str}".strip()
        print(f"  TRY {label}")
        try:
            idx_name = coll.create_index(keys, **kwargs)
            print(f"  OK  {label}  => {idx_name}")
        except OperationFailure as e:
            details = getattr(e, "details", None) or {}
            code = (
                details.get("codeName", "OperationFailure")
                if isinstance(details, dict)
                else "OperationFailure"
            )
            msg = f"CONFLICT {label}: {code} — {sanitize_error(e)}"
            print(f"  ERR {msg}")
            errors.append(msg)
        except Exception as e:
            msg = f"ERROR {label}: {sanitize_error(e)}"
            print(f"  ERR {msg}")
            errors.append(msg)

    def _search_idx(collection_name, index_name, field, dimensions, similarity="cosine"):
        """Atlas Vector Search index. Failure is informational, not a data mutation."""
        try:
            db.command({
                "createSearchIndexes": collection_name,
                "indexes": [{
                    "name": index_name,
                    "definition": {
                        "mappings": {
                            "dynamic": True,
                            "fields": {
                                field: {
                                    "type": "knnVector",
                                    "dimensions": dimensions,
                                    "similarity": similarity,
                                }
                            }
                        }
                    }
                }]
            })
            print(f"  OK  Atlas Search index '{index_name}' on [{collection_name}].{field}")
        except Exception as e:
            print(
                f"  --  Atlas Search index '{index_name}' skipped "
                f"(Atlas tier or already exists): {sanitize_error(e)}"
            )
            warnings.append(f"Atlas Search index '{index_name}' on [{collection_name}]")

    for collection, index_name, field, dimensions, similarity in ATLAS_SEARCH_INDEX_PLANS:
        print(f"\n[Atlas Search] {collection}.{field}")
        _search_idx(collection, index_name, field, dimensions, similarity)

    current_section = None
    for op in STANDARD_INDEX_OPS:
        if op.section != current_section:
            current_section = op.section
            print(f"\n[Section] {current_section}")
            if op.notes:
                print(f"  note: {op.notes}")
        pymongo_keys = [(k, _DIR_MAP.get(d, d)) for k, d in op.keys]
        _idx(op.collection, pymongo_keys, **create_kwargs(op))

    print("\n" + "=" * 60)
    if errors:
        print(f"SETUP FINISHED WITH {len(errors)} ERROR(S).")
        for e in errors:
            print(f"  ERROR: {e}")
        print("\nOperator action required for each ERROR above before indexes are complete.")
        print("No indexes were dropped.")
        return 1

    print("SETUP COMPLETE. All indexes created or already existed.")
    if warnings:
        print(f"  {len(warnings)} informational note(s) — Atlas Search may need Atlas tier M10+.")
    print("\nNext steps:")
    print("  1. Confirm 2dsphere on responders.current_location exists.")
    print("  2. Deploy/restart the backend through the operator-controlled process.")
    print("  3. Verify GET /health on the deployed API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
