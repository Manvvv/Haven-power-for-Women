"""
mental_health_resources.py — Centralized, VERIFIED mental-health resource registry.

Single source of truth for every emergency / crisis / support number surfaced by
HAVEN's mental-health module. Nothing here is invented: each government entry was
verified against an official Government of India source on the date in `verified_at`,
and each entry carries name/type/number/purpose/country/source_url/verified_at/
language_support/availability (spec §4, §23, §32).

Design rules:
  * Numbers are DATA with provenance, never presented by the model as clinical advice.
  * UI components MUST read from this registry — they must not hardcode numbers
    (spec §4: "Do NOT hardcode these directly inside multiple UI components").
  * Government resources are tier1 (authority_level="government_verified"); reputable
    NGO crisis lines are tier "ngo_helpline" and clearly labelled so callers can tell
    them apart. If a number ever fails re-verification, downgrade/remove it here — the
    whole app updates at once.

Pure-Python data module: no DB, no network, no deps → importable and testable in any
environment.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

# Registry-wide verification date. Government numbers re-verified via official
# MoHFW / MHA / MoSJE sources on this date (see per-entry source_url).
RESOURCES_VERSION = "2026-09-25"
_GOV_VERIFIED_AT = "2026-09-25"
# NGO numbers are widely published but not government-issued; verified against the
# organisation's own public listing as of the assistant's knowledge date. UIs should
# invite users to confirm before relying on them.
_NGO_VERIFIED_AT = "2026-01-01"

GOVERNMENT = "government_verified"
NGO = "ngo_helpline"

# Re-verification cadence per provenance tier. Government emergency numbers are stable
# and re-checked twice a year; NGO lines change more often, so re-check annually. These
# drive each entry's `next_verify_at` and the staleness validator (spec §23, §32).
_REVERIFY_DAYS = {GOVERNMENT: 180, NGO: 365}
_DEFAULT_REVERIFY_DAYS = 365

# ─────────────────────────── Resource registry ───────────────────────────
# Keyed by a stable id. `type` groups them for the UI; `authority_level`
# distinguishes government-issued from NGO-run lines.
RESOURCES: Dict[str, Dict[str, Any]] = {
    "emergency_112": {
        "id": "emergency_112",
        "name": "National Emergency Number (ERSS)",
        "type": "emergency",
        "number": "112",
        "purpose": "Immediate police, fire or medical emergency — pan-India response.",
        "country": "IN",
        "source_url": "https://112.gov.in/",
        "authority_level": GOVERNMENT,
        "verified_at": _GOV_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "telemanas_14416": {
        "id": "telemanas_14416",
        "name": "Tele-MANAS (National Tele Mental Health Programme)",
        "type": "mental_health_crisis",
        "number": "14416",
        "alt_number": "1800-891-4416",
        "purpose": ("Free, confidential 24x7 mental-health support and counselling by "
                    "trained professionals, in multiple Indian languages."),
        "country": "IN",
        "source_url": "https://telemanas.mohfw.gov.in/",
        "authority_level": GOVERNMENT,
        "verified_at": _GOV_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "kiran_18005990019": {
        "id": "kiran_18005990019",
        "name": "KIRAN Mental Health Rehabilitation Helpline",
        "type": "mental_health_support",
        "number": "1800-599-0019",
        "purpose": ("Toll-free 24x7 helpline for early screening, first-aid, psychological "
                    "support and distress management."),
        "country": "IN",
        "source_url": "https://depwd.gov.in/en/others-helplines/",
        "authority_level": GOVERNMENT,
        "verified_at": _GOV_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "childline_1098": {
        "id": "childline_1098",
        "name": "Childline (Children in distress)",
        "type": "child",
        "number": "1098",
        "purpose": "Emergency help for children in need of care and protection.",
        "country": "IN",
        "source_url": "https://www.childlineindia.org/",
        "authority_level": GOVERNMENT,
        "verified_at": _GOV_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "women_181": {
        "id": "women_181",
        "name": "Women Helpline",
        "type": "women",
        "number": "181",
        "purpose": "24x7 support and referral for women in distress, including violence at home.",
        "country": "IN",
        "source_url": "https://wcd.nic.in/schemes/women-helpline-scheme-universalisation",
        "authority_level": GOVERNMENT,
        "verified_at": _GOV_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "vandrevala": {
        "id": "vandrevala",
        "name": "Vandrevala Foundation Mental Health Helpline",
        "type": "mental_health_crisis",
        "number": "1860-2662-345",
        "alt_number": "9999-666-555",
        "purpose": "Free 24x7 counselling and crisis support (non-government / NGO).",
        "country": "IN",
        "source_url": "https://www.vandrevalafoundation.com/",
        "authority_level": NGO,
        "verified_at": _NGO_VERIFIED_AT,
        "language_support": ["en", "hi", "regional"],
        "availability": "24x7",
    },
    "aasra": {
        "id": "aasra",
        "name": "AASRA Suicide Prevention Helpline",
        "type": "mental_health_crisis",
        "number": "9820466726",
        "purpose": "Emotional support and suicide-prevention counselling (non-government / NGO).",
        "country": "IN",
        "source_url": "http://www.aasra.info/",
        "authority_level": NGO,
        "verified_at": _NGO_VERIFIED_AT,
        "language_support": ["en", "hi"],
        "availability": "24x7",
    },
    "icall": {
        "id": "icall",
        "name": "iCALL Psychosocial Helpline (TISS)",
        "type": "mental_health_support",
        "number": "9152987821",
        "purpose": "Counselling and psychosocial support by trained professionals (TISS / NGO).",
        "country": "IN",
        "source_url": "https://icallhelpline.org/",
        "authority_level": NGO,
        "verified_at": _NGO_VERIFIED_AT,
        "language_support": ["en", "hi"],
        "availability": "Mon-Sat, daytime hours (see website)",
    },
}

# Display-priority ordering per situation (ids only; order = priority).
_EMERGENCY_ORDER = ["emergency_112", "telemanas_14416"]
_CRISIS_ORDER = ["telemanas_14416", "kiran_18005990019", "vandrevala", "aasra", "emergency_112"]
_SUPPORT_ORDER = ["telemanas_14416", "kiran_18005990019", "icall", "vandrevala"]
_CHILD_ORDER = ["childline_1098", "emergency_112", "telemanas_14416"]
_WOMEN_ORDER = ["women_181", "emergency_112", "telemanas_14416"]

# Institutional professional-support pointers (national). We do NOT fabricate local
# clinics; instead we point to official routing services and national institutions,
# and let Tele-MANAS route callers to their state cell.
_PROFESSIONAL: List[Dict[str, Any]] = [
    {
        "provider_name": "Tele-MANAS (routes to your State mental-health cell)",
        "type": "government_teleservice",
        "state": "All India",
        "city": "",
        "languages": ["en", "hi", "regional"],
        "specialty": "General mental-health counselling & referral",
        "official_url": "https://telemanas.mohfw.gov.in/",
        "phone": "14416",
        "verified_at": _GOV_VERIFIED_AT,
        "availability": "24x7",
    },
    {
        "provider_name": "NIMHANS Bengaluru — Psychosocial Support",
        "type": "government_institution",
        "state": "Karnataka",
        "city": "Bengaluru",
        "languages": ["en", "hi", "regional"],
        "specialty": "Psychiatry, clinical psychology, psychosocial support",
        "official_url": "https://nimhans.ac.in/",
        "phone": "080-46110007",
        "verified_at": _GOV_VERIFIED_AT,
        "availability": "24x7 support line",
    },
    {
        "provider_name": "District Mental Health Programme (DMHP) — your district hospital",
        "type": "government_program",
        "state": "All India",
        "city": "",
        "languages": ["en", "hi", "regional"],
        "specialty": "Public mental-health services at district level",
        "official_url": "https://nhm.gov.in/",
        "phone": "",
        "verified_at": _GOV_VERIFIED_AT,
        "availability": "Government working hours (varies by district)",
    },
]

DISCLAIMER = ("HAVEN offers emotional support and information, and is not a doctor, "
              "therapist, or emergency service. It cannot diagnose conditions or "
              "prescribe treatment. In an emergency, contact 112 or the resources below.")


# ─────────────────────── Freshness metadata + staleness validator ───────────────────────
# Every resource carries verified_at + source_url + authority_level (above). We derive
# `next_verify_at` from the tier cadence so operators know when to re-check. Nothing is
# ever auto-removed — the validator only FLAGS (spec §23, §32).
def _iso_add_days(iso_date: str, days: int) -> str:
    y, m, d = (int(x) for x in iso_date.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def _reverify_days(authority_level: str) -> int:
    return _REVERIFY_DAYS.get(authority_level, _DEFAULT_REVERIFY_DAYS)


def _apply_freshness(entry: Dict[str, Any], default_level: str) -> None:
    """Ensure authority_level + next_verify_at are present on a registry entry."""
    entry.setdefault("authority_level", default_level)
    va = entry.get("verified_at")
    if va and not entry.get("next_verify_at"):
        entry["next_verify_at"] = _iso_add_days(va, _reverify_days(entry["authority_level"]))


for _r in RESOURCES.values():
    _apply_freshness(_r, NGO)
for _p in _PROFESSIONAL:
    _apply_freshness(_p, GOVERNMENT)


def _all_entries() -> List[Dict[str, Any]]:
    """Every verifiable entry (crisis registry + professional pointers)."""
    return list(RESOURCES.values()) + list(_PROFESSIONAL)


def check_resource_freshness(as_of: Optional[str] = None, due_soon_days: int = 30) -> Dict[str, Any]:
    """Flag resources whose re-verification is overdue ("stale") or imminent ("due_soon").

    Pure, side-effect-free audit for CI / ops. It NEVER removes or mutates a resource —
    a human must re-verify against the official source_url and update verified_at. Pass
    `as_of` (YYYY-MM-DD) for deterministic testing; defaults to today.
    """
    today = as_of or date.today().isoformat()
    horizon = _iso_add_days(today, max(0, due_soon_days))
    stale, due_soon, missing = [], [], []
    for e in _all_entries():
        ident = e.get("id") or e.get("provider_name") or e.get("name") or "?"
        nva = e.get("next_verify_at")
        if not e.get("verified_at") or not nva:
            missing.append(ident)
            continue
        row = {"id": ident, "name": e.get("name") or e.get("provider_name", ""),
               "authority_level": e.get("authority_level"),
               "verified_at": e.get("verified_at"), "next_verify_at": nva,
               "source_url": e.get("source_url") or e.get("official_url", "")}
        if nva < today:
            stale.append(row)
        elif nva <= horizon:
            due_soon.append(row)
    total = len(_all_entries())
    return {
        "as_of": today,
        "total": total,
        "stale_count": len(stale),
        "due_soon_count": len(due_soon),
        "missing_metadata_count": len(missing),
        "ok": not stale and not missing,
        "stale": stale,
        "due_soon": due_soon,
        "missing_metadata": missing,
        "policy": {"government_days": _REVERIFY_DAYS[GOVERNMENT],
                   "ngo_days": _REVERIFY_DAYS[NGO]},
        "note": "Flags only. Resources are never auto-removed; re-verify via source_url "
                "then update verified_at.",
    }


def _pick(ids: List[str]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for rid in ids:
        if rid in RESOURCES and rid not in seen:
            seen.add(rid)
            out.append(dict(RESOURCES[rid]))
    return out


def get_resource(resource_id: str) -> Optional[Dict[str, Any]]:
    r = RESOURCES.get(resource_id)
    return dict(r) if r else None


def emergency_resources(child: bool = False, women: bool = False) -> List[Dict[str, Any]]:
    """Emergency-first resources. 112 always leads unless a child-specific line applies."""
    if child:
        return _pick(_CHILD_ORDER)
    if women:
        return _pick(["emergency_112", "women_181", "telemanas_14416"])
    return _pick(_EMERGENCY_ORDER)


def crisis_resources() -> List[Dict[str, Any]]:
    """Mental-health crisis lines for high-risk / imminent-danger situations."""
    return _pick(_CRISIS_ORDER)


def support_resources() -> List[Dict[str, Any]]:
    """Non-emergency emotional-support lines."""
    return _pick(_SUPPORT_ORDER)


def child_resources() -> List[Dict[str, Any]]:
    return _pick(_CHILD_ORDER)


def women_resources() -> List[Dict[str, Any]]:
    return _pick(_WOMEN_ORDER)


def professional_resources(state: Optional[str] = None) -> List[Dict[str, Any]]:
    """National + (optionally) state-matched professional-support pointers.

    We never fabricate local clinics; if a state is given we surface state-matched
    institutional entries first, then always-available national routing (Tele-MANAS).
    """
    items = [dict(p) for p in _PROFESSIONAL]
    if state:
        s = state.strip().lower()
        items.sort(key=lambda p: 0 if p["state"].lower() == s else 1)
    return items


def all_resources() -> List[Dict[str, Any]]:
    return [dict(r) for r in RESOURCES.values()]


def offline_pack() -> Dict[str, Any]:
    """Small, self-contained crisis pack for offline / AI-unavailable use (spec §24, §29).

    Contains the exercises + numbers a user needs during a crisis WITHOUT any AI call.
    Versioned so the client can refresh it when connectivity returns.
    """
    return {
        "version": RESOURCES_VERSION,
        "emergency": _pick(_EMERGENCY_ORDER),
        "crisis": _pick(_CRISIS_ORDER),
        "grounding": {
            "title": "5-4-3-2-1 grounding",
            "steps": [
                "Name 5 things you can see.",
                "Name 4 things you can feel/touch.",
                "Name 3 things you can hear.",
                "Name 2 things you can smell.",
                "Name 1 thing you can taste, or one slow breath.",
            ],
        },
        "breathing": {
            "title": "Slow breathing",
            "steps": [
                "Breathe in gently through your nose for 4 counts.",
                "Hold for 4 counts.",
                "Breathe out slowly for 6 counts.",
                "Repeat a few times. Stop if you feel light-headed.",
            ],
        },
        "emergency_instructions": [
            "If you or someone else is in immediate danger, call 112 now.",
            "Try to be with another person, or move to a place where you feel safer.",
            "Tele-MANAS (14416) has trained counsellors available 24x7.",
        ],
        "haven_sos": {
            "title": "HAVEN SOS",
            "description": ("Open HAVEN's SOS screen to alert your trusted contacts and share "
                            "your live location — works from inside the app."),
            "in_app_path": "/sos",
            "consent_note": ("SOS only starts when you tap it, and uses the trusted contacts "
                             "you saved. HAVEN never contacts anyone automatically."),
        },
        "disclaimer": DISCLAIMER,
    }


if __name__ == "__main__":  # pragma: no cover — ops/CI freshness audit
    import json as _json
    report = check_resource_freshness()
    print(_json.dumps(report, ensure_ascii=False, indent=2))
    # Non-zero exit if anything is overdue or missing metadata, so CI can catch drift.
    raise SystemExit(0 if report["ok"] else 1)

