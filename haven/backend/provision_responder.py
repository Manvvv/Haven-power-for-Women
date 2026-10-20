"""Provision an individual field-responder account (Rapid Response Network).

Minimal, operator-run CLI for creating/updating responder credentials. There is
intentionally NO public HTTP endpoint for CREATING responders — accounts are
provisioned by an administrator on the server, mirroring provision_authority.py.
Passwords are hashed (PBKDF2 + server pepper) and never stored in plaintext.

A newly created responder is INERT (verified=False, status=OFFLINE): it cannot be
offered a dispatch until an admin approves it via the existing trusted admin
workflow (PATCH /admin/responders/{id}) or the --verify flag below. This keeps
responder approval human-controlled and prevents a freshly provisioned account
from silently entering the dispatch pool.

Usage:
    python provision_responder.py --badge HN-204 --name "Unit Rao" \
        --label "Verified Response Unit HN-204" \
        --capabilities medical,patrol --jurisdiction "Zone-5"
    # password read interactively (not echoed) unless --password is given.

    python provision_responder.py --badge HN-204 --verify      # admin approve
    python provision_responder.py --badge HN-204 --unverify     # revoke approval
    python provision_responder.py --badge HN-204 --deactivate
    python provision_responder.py --badge HN-204 --activate

In production, set ENVIRONMENT=production and a strong AUTHORITY_SECRET_KEY (or
RESPONDER_SECRET_KEY, if you set one) before running so the pepper matches what
the running server uses.
"""
import argparse
import getpass
import sys

# Load the SAME backend/.env the running server uses BEFORE importing anything
# that reads the pepper at import time (auth.py, imported transitively by
# responder_service). Without this, the CLI hashes with the DEFAULT pepper while
# the server verifies with the real key, so every responder login would fail.
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from services.responder_service import (
    create_responder, set_active, set_verified, get_responder,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision a HAVEN field-responder account")
    ap.add_argument("--badge", required=True, help="Badge number (login username), e.g. HN-204")
    ap.add_argument("--name", help="Internal officer/unit name (audit trail only; never shown to victims)")
    ap.add_argument("--role", default="responder", choices=["responder"],
                    help="Responder accounts always have role=responder (fixed).")
    ap.add_argument("--password", help="Password (omit to be prompted securely)")
    ap.add_argument("--label", help="Safe public unit label shown to victims (e.g. 'Verified Response Unit HN-204'). NO PII.")
    ap.add_argument("--capabilities", help="Comma-separated capability tags, e.g. medical,patrol")
    ap.add_argument("--jurisdiction", help="Jurisdiction / zone this unit serves")
    ap.add_argument("--verify", action="store_true", help="Approve (verify) an existing responder")
    ap.add_argument("--unverify", action="store_true", help="Revoke approval of an existing responder")
    ap.add_argument("--deactivate", action="store_true", help="Disable an existing account")
    ap.add_argument("--activate", action="store_true", help="Re-enable an existing account")
    args = ap.parse_args()

    # Admin lifecycle toggles operate on an EXISTING account only.
    if args.verify or args.unverify:
        rec = set_verified(args.badge, verified=bool(args.verify))
        if not rec:
            print(f"No responder account found for badge {args.badge}", file=sys.stderr)
            return 1
        print(f"Responder {args.badge} {'verified (approved)' if args.verify else 'unverified'}; "
              f"status={rec.get('status')}.")
        return 0

    if args.deactivate or args.activate:
        ok = set_active(args.badge, active=bool(args.activate))
        if not ok:
            print(f"No responder account found for badge {args.badge}", file=sys.stderr)
            return 1
        print(f"Account {args.badge} {'activated' if args.activate else 'deactivated'}.")
        return 0

    if not args.name:
        print("--name is required when creating/updating an account", file=sys.stderr)
        return 2
    password = args.password or getpass.getpass("New responder password: ")
    if not password:
        print("Password must not be empty", file=sys.stderr)
        return 2
    caps = [c.strip() for c in (args.capabilities or "").split(",") if c.strip()]
    rec = create_responder(
        args.badge, args.name, password,
        display_label=args.label, capabilities=caps,
        jurisdiction=args.jurisdiction, active=True,
    )
    print(f"Provisioned responder (responder_id={rec['responder_id']}, badge={rec['badge_number']}, "
          f"label='{rec['display_label']}', capabilities={rec['capabilities']}, "
          f"jurisdiction='{rec['jurisdiction']}').")
    print(f"verified={rec['verified']} status={rec['status']} — the unit is INERT until approved "
          f"(run with --verify, or approve via PATCH /admin/responders).")
    print("Password stored as a PBKDF2 hash — plaintext is not persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
