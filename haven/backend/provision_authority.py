"""Provision an individual authority officer account (P1-7).

Minimal, operator-run CLI for creating/updating authority credentials. There is
intentionally NO public HTTP endpoint for this — accounts are provisioned by an
administrator on the server. Passwords are hashed (PBKDF2 + server pepper) and
never stored in plaintext.

Usage:
    python provision_authority.py --badge PO-1091 --name "Insp. Rao" [--role authority]
    # password read interactively (not echoed) unless --password is given.

    python provision_authority.py --badge PO-1091 --deactivate
    python provision_authority.py --badge PO-1091 --activate

In production, set ENVIRONMENT=production and a strong AUTHORITY_SECRET_KEY before
running so the pepper matches what the running server uses.
"""
import argparse
import getpass
import sys

# Load the SAME backend/.env the running server uses BEFORE importing anything
# that reads AUTHORITY_SECRET_KEY at import time (auth.py, imported transitively
# by authority_service). Without this, the CLI hashes passwords with the DEFAULT
# pepper ("haven2024") while the server — which loads .env via main.py — verifies
# with the real AUTHORITY_SECRET_KEY, so every login fails with
# "Invalid authority credentials" whenever .env sets a non-default key.
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from services.authority_service import create_authority, set_active, get_authority


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision a HAVEN authority officer account")
    ap.add_argument("--badge", required=True, help="Badge number (login username), e.g. PO-1091")
    ap.add_argument("--name", help="Officer name (identity shown in audit trail)")
    ap.add_argument("--role", default="authority",
                    choices=["authority", "police", "protection_officer", "admin"])
    ap.add_argument("--password", help="Password (omit to be prompted securely)")
    ap.add_argument("--deactivate", action="store_true", help="Disable an existing account")
    ap.add_argument("--activate", action="store_true", help="Re-enable an existing account")
    args = ap.parse_args()

    if args.deactivate or args.activate:
        ok = set_active(args.badge, active=bool(args.activate))
        if not ok:
            print(f"No authority account found for badge {args.badge}", file=sys.stderr)
            return 1
        print(f"Account {args.badge} {'activated' if args.activate else 'deactivated'}.")
        return 0

    if not args.name:
        print("--name is required when creating/updating an account", file=sys.stderr)
        return 2
    password = args.password or getpass.getpass("New authority password: ")
    if not password:
        print("Password must not be empty", file=sys.stderr)
        return 2
    rec = create_authority(args.badge, args.name, password, role=args.role, active=True)
    print(f"Provisioned authority '{rec['officer_name']}' "
          f"(authority_id={rec['authority_id']}, badge={rec['badge_number']}, role={rec['role']}).")
    print("Password stored as a PBKDF2 hash — plaintext is not persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
