"""
Shared MongoDB index catalog and read-only preflight logic for HAVEN.

This module is importable without connecting to MongoDB. Scripts and tests
use it so planned unique-index definitions cannot drift between
setup_indexes.py and preflight_index_check.py.

Secrets: never log or return connection strings, credentials, or document
values from unique-key fields.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

# Database name used by services/db.py — keep in lockstep.
HAVEN_DATABASE_NAME = "Haven"

# Operator must set this exact value to allow index creation against Atlas
# or ENVIRONMENT=production. The setup script still does not drop indexes.
INDEX_SETUP_CONFIRM_VALUE = "YES"

STAGING_ENVIRONMENT_VARIABLE = "HAVEN_DATABASE_ENVIRONMENT"
STAGING_TARGET_ID_VARIABLE = "HAVEN_STAGING_TARGET_ID"
STAGING_HOST_ALLOWLIST_VARIABLE = "HAVEN_STAGING_MONGO_HOST_ALLOWLIST"
STAGING_DATABASE_ALLOWLIST_VARIABLE = "HAVEN_STAGING_DATABASE_ALLOWLIST"

@dataclass(frozen=True)
class UniqueIndexPlan:
    collection: str
    field: str
    unique: bool = True
    sparse: bool = True
    # Application always writes this field on create. Sparse is a migration
    # safety net for legacy/incomplete documents, not a statement that the
    # field is optional in the data model.
    required_on_write: bool = True
    notes: str = ""


@dataclass(frozen=True)
class IndexOp:
    collection: str
    keys: Tuple[Tuple[str, Any], ...]
    unique: bool = False
    sparse: bool = False
    expire_after_seconds: Optional[int] = None
    section: str = ""
    notes: str = ""


ATLAS_SEARCH_INDEX_PLANS: Tuple[Tuple[str, str, str, int, str], ...] = (
    ("culprits", "culpritIndex", "description_embedding", 768, "cosine"),
    ("legal_docs", "legalIndex", "embedding", 768, "cosine"),
    ("sos_cases", "casesIndex", "embedding", 768, "cosine"),
)


# ── Planned unique indexes (source of truth) ────────────────────────────────
# Sparse is used on identifier fields that every *new* write sets, so that
# legacy documents missing the field do not block index builds. Empty strings
# ARE indexed by sparse unique indexes and must be unique.
# voice_sos_config.user_id is NOT sparse: every config row is keyed by user.
UNIQUE_INDEX_PLANS: Tuple[UniqueIndexPlan, ...] = (
    UniqueIndexPlan("sos_cases", "case_id", sparse=True, required_on_write=True,
                    notes="Cases are created with case_id. Sparse excludes incomplete ingest docs."),
    UniqueIndexPlan("culprits", "culprit_id", sparse=True, required_on_write=True,
                    notes="Profiles are created with culprit_id."),
    UniqueIndexPlan("voice_sos_config", "user_id", sparse=False, required_on_write=True,
                    notes="One config per user. Missing/null user_id is a blocker."),
    UniqueIndexPlan("sos_events", "event_id", sparse=True, required_on_write=True,
                    notes="Events are created with event_id."),
    UniqueIndexPlan("ai_analyses", "case_id", sparse=True, required_on_write=True,
                    notes="Not every case has an analysis document."),
    UniqueIndexPlan("responders", "responder_id", sparse=True, required_on_write=True,
                    notes="Provisioned responders always receive responder_id."),
    UniqueIndexPlan("responders", "badge_number", sparse=True, required_on_write=True,
                    notes="create_responder requires a non-empty badge. Sparse excludes legacy docs missing the field; empty strings are still indexed."),
    UniqueIndexPlan("dispatch_requests", "dispatch_id", sparse=True, required_on_write=True,
                    notes="Dispatches are created with dispatch_id."),
    UniqueIndexPlan("dispatch_attempts", "attempt_id", sparse=True, required_on_write=True,
                    notes="Attempts are created with attempt_id."),
    UniqueIndexPlan("provider_registrations", "registration_id", sparse=True, required_on_write=True,
                    notes="Registrations are created with registration_id."),
    UniqueIndexPlan("provider_requests", "request_id", sparse=True, required_on_write=True,
                    notes="Requests are created with request_id."),
    UniqueIndexPlan("responder_setup_tokens", "token_hash", sparse=True, required_on_write=True,
                    notes="Tokens store SHA-256 digests only."),
)

# Non-unique / TTL / 2dsphere operations created by setup_indexes.py.
# Direction values: 1 ASC, -1 DESC, "2dsphere" GEOSPHERE.
STANDARD_INDEX_OPS: Tuple[IndexOp, ...] = (
    IndexOp("sos_cases", (("severity", 1), ("status", 1)), section="SOS Cases"),
    IndexOp("sos_cases", (("created_at", -1),), section="SOS Cases"),
    IndexOp("sos_cases", (("case_id", 1),), unique=True, sparse=True, section="SOS Cases"),
    IndexOp("sos_cases", (("trigger_type", 1),), section="SOS Cases"),
    IndexOp("therapy_sessions", (("session_id", 1),), section="SOS Cases"),
    IndexOp("therapy_sessions", (("user_id", 1),), section="SOS Cases"),
    IndexOp("culprits", (("culprit_id", 1),), unique=True, sparse=True, section="Culprit lookup"),
    IndexOp("culprits", (("name", 1),), section="Culprit lookup"),
    IndexOp("culprits", (("location", 1),), section="Culprit lookup"),
    IndexOp("culprits", (("created_at", -1),), section="Culprit lookup"),
    IndexOp("culprits", (("associated_cases.case_id", 1),), section="Culprit lookup"),
    IndexOp("voice_sos_config", (("user_id", 1),), unique=True, sparse=False, section="Voice SOS"),
    IndexOp("trusted_contacts", (("user_id", 1),), section="Voice SOS"),
    IndexOp("sos_events", (("user_id", 1),), section="Voice SOS"),
    IndexOp("sos_events", (("event_id", 1),), unique=True, sparse=True, section="Voice SOS"),
    IndexOp("sos_events", (("created_at", -1),), section="Voice SOS"),
    IndexOp("audit_logs", (("timestamp", -1),), section="Audit"),
    IndexOp("audit_logs", (("action", 1),), section="Audit"),
    IndexOp("audit_logs", (("actor_id", 1),), section="Audit"),
    IndexOp("audit_logs", (("case_id", 1),), section="Audit"),
    IndexOp("notifications", (("recipient_id", 1), ("read", 1)), section="Audit"),
    IndexOp("notifications", (("created_at", -1),), section="Audit"),
    IndexOp("sos_status_history", (("case_id", 1), ("timestamp", 1)), section="Audit"),
    IndexOp("privacy_records", (("user_id", 1),), section="Audit"),
    IndexOp("ai_analyses", (("case_id", 1),), unique=True, sparse=True, section="Audit"),
    IndexOp("responders", (("current_location", "2dsphere"),), section="Rapid Response",
            notes="Required for $near eligibility queries."),
    IndexOp("responders", (("responder_id", 1),), unique=True, sparse=True, section="Rapid Response"),
    IndexOp("responders", (("badge_number", 1),), unique=True, sparse=True, section="Rapid Response"),
    IndexOp("responders", (("status", 1), ("verified", 1), ("active", 1)), section="Rapid Response"),
    IndexOp("responders", (("assigned_dispatch_id", 1),), section="Rapid Response"),
    IndexOp("dispatch_requests", (("dispatch_id", 1),), unique=True, sparse=True, section="Rapid Response"),
    IndexOp("dispatch_requests", (("case_id", 1),), section="Rapid Response"),
    IndexOp("dispatch_requests", (("status", 1),), section="Rapid Response"),
    IndexOp("dispatch_requests", (("created_at", -1),), section="Rapid Response"),
    IndexOp("dispatch_attempts", (("attempt_id", 1),), unique=True, sparse=True, section="Rapid Response"),
    IndexOp("dispatch_attempts", (("dispatch_id", 1),), section="Rapid Response"),
    IndexOp("dispatch_attempts", (("responder_id", 1), ("response", 1)), section="Rapid Response"),
    IndexOp("dispatch_attempts", (("expires_at", 1),), section="Rapid Response"),
    IndexOp("response_events", (("dispatch_id", 1), ("at", 1)), section="Rapid Response"),
    IndexOp("provider_registrations", (("registration_id", 1),), unique=True, sparse=True,
            section="Provider Registration"),
    IndexOp("provider_registrations", (("submitted_by", 1),), section="Provider Registration"),
    IndexOp("provider_registrations", (("status", 1),), section="Provider Registration"),
    IndexOp("provider_registrations", (("badge_number", 1),), sparse=True, section="Provider Registration",
            notes="Non-unique; duplicate pending badges are rejected in application logic."),
    IndexOp("provider_registrations", (("submitted_at", -1),), section="Provider Registration"),
    IndexOp("provider_requests", (("request_id", 1),), unique=True, sparse=True,
            section="Provider Registration"),
    IndexOp("provider_requests", (("responder_id", 1),), section="Provider Registration"),
    IndexOp("provider_requests", (("submitted_by", 1),), section="Provider Registration"),
    IndexOp("provider_requests", (("status", 1),), section="Provider Registration"),
    IndexOp("provider_requests", (("submitted_at", -1),), section="Provider Registration"),
    IndexOp("responder_setup_tokens", (("token_hash", 1),), unique=True, sparse=True,
            section="Provider Registration"),
    IndexOp("responder_setup_tokens", (("responder_id", 1),), section="Provider Registration"),
    IndexOp("responder_setup_tokens", (("expires_at", 1),), expire_after_seconds=0,
            section="Provider Registration",
            notes="TTL: expire at the datetime stored in expires_at."),
)


def planned_as_tuples() -> List[Tuple[str, str, bool, bool]]:
    """(collection, field, unique, sparse) — used by older script loops."""
    return [(p.collection, p.field, p.unique, p.sparse) for p in UNIQUE_INDEX_PLANS]


def unique_ops_as_tuples() -> List[Tuple[str, str, bool, bool]]:
    """Unique single-field ops from STANDARD_INDEX_OPS (must match UNIQUE_INDEX_PLANS)."""
    out: List[Tuple[str, str, bool, bool]] = []
    for op in STANDARD_INDEX_OPS:
        if not op.unique:
            continue
        if len(op.keys) != 1:
            out.append((op.collection, ",".join(k for k, _ in op.keys), True, op.sparse))
            continue
        out.append((op.collection, op.keys[0][0], True, op.sparse))
    return out


def catalog_consistency_errors() -> List[str]:
    """Detect drift between UNIQUE_INDEX_PLANS and unique STANDARD_INDEX_OPS."""
    errors: List[str] = []
    plans = set(planned_as_tuples())
    ops = set(unique_ops_as_tuples())
    for item in sorted(plans - ops):
        errors.append(
            f"BLOCKER: unique plan {item} is missing from STANDARD_INDEX_OPS. "
            "setup_indexes.py would not create it."
        )
    for item in sorted(ops - plans):
        errors.append(
            f"BLOCKER: STANDARD_INDEX_OPS unique index {item} is missing from "
            "UNIQUE_INDEX_PLANS. Preflight would not check it."
        )
    return errors


# Application-enforced identifiers that are NOT created by setup_indexes.py.
# Reported by preflight as advisory only so a later unique index is not a surprise.
ADVISORY_UNIQUE_INDEX_PLANS: Tuple[UniqueIndexPlan, ...] = (
    UniqueIndexPlan(
        "authority_accounts", "badge_number", sparse=True, required_on_write=True,
        notes="Authority login key. Uniqueness is application-enforced today.",
    ),
    UniqueIndexPlan(
        "authority_accounts", "authority_id", sparse=True, required_on_write=True,
        notes="Stable authority identifier. Not yet in setup_indexes.py.",
    ),
    UniqueIndexPlan(
        "therapy_sessions", "session_id", sparse=False, required_on_write=True,
        notes="Looked up and upserted by session_id; current setup index is non-unique.",
    ),
)


def sanitize_error(exc: BaseException) -> str:
    """Return safe error context without echoing arbitrary driver messages."""
    return f"{type(exc).__name__}: [redacted]"


def classify_mongo_target(endpoint: str) -> Dict[str, Any]:
    """Identify the target class without exposing the URI or credentials."""
    ep = endpoint or ""
    lower = ep.lower()
    if not ep:
        kind = "unset"
        label = "MONGO_ENDPOINT not set"
    elif "localhost" in lower or "127.0.0.1" in ep or "[::1]" in lower:
        kind = "local"
        label = "Local MongoDB (development)"
    elif "mongodb.net" in ep or "atlas" in lower:
        kind = "atlas"
        label = "MongoDB Atlas (cloud)"
    elif lower.startswith("mongodb+srv://"):
        kind = "cloud_srv"
        label = "MongoDB SRV / cloud-style endpoint"
    else:
        kind = "custom"
        label = "Custom / unrecognised endpoint (treat as production-adjacent)"
    looks_cloud = kind in ("atlas", "cloud_srv")
    ambiguous = kind in ("custom", "cloud_srv")
    return {
        "kind": kind,
        "label": label,
        "looks_cloud": looks_cloud,
        "ambiguous": ambiguous,
        "requires_setup_confirm": looks_cloud or kind == "custom",
        "database_name": HAVEN_DATABASE_NAME,
        "endpoint_configured": bool(ep),
    }


def index_setup_requires_confirm(environment: str, endpoint: str) -> bool:
    env = (environment or "development").strip().lower()
    target = classify_mongo_target(endpoint)
    return env in ("production", "prod") or bool(target.get("requires_setup_confirm"))


def confirm_index_setup_authorized() -> bool:
    return os.getenv("HAVEN_ALLOW_INDEX_SETUP", "").strip() == INDEX_SETUP_CONFIRM_VALUE


@dataclass
class FieldCheck:
    collection: str
    field: str
    safe: bool
    total: int = 0
    with_value: int = 0
    null_value: int = 0
    missing_field: int = 0
    empty_string: int = 0
    duplicate_groups: int = 0
    type_variants: List[str] = field(default_factory=list)
    existing_indexes: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


@dataclass
class PreflightResult:
    blockers: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    checks: List[FieldCheck] = field(default_factory=list)
    advisory_checks: List[FieldCheck] = field(default_factory=list)
    index_inventory: Dict[str, List[str]] = field(default_factory=dict)
    environment_label: str = ""
    database_name: str = HAVEN_DATABASE_NAME

    @property
    def ok(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class TargetValidation:
    approved: bool
    target_id: str = ""
    database_name: str = HAVEN_DATABASE_NAME
    reason: str = ""


def _mongo_uri_identity(endpoint: str) -> Tuple[set[str], str]:
    """Parse host/database identity locally without resolving or connecting."""
    parsed = urlsplit((endpoint or "").strip())
    if parsed.scheme.lower() not in ("mongodb", "mongodb+srv") or not parsed.netloc:
        raise ValueError("invalid MongoDB endpoint")

    authority = parsed.netloc.rsplit("@", 1)[-1]
    hosts: set[str] = set()
    for entry in authority.split(","):
        entry = entry.strip()
        if entry.startswith("["):
            end = entry.find("]")
            host = entry[1:end] if end > 0 else ""
        else:
            host = entry.rsplit(":", 1)[0] if entry.count(":") == 1 else entry
        host = host.lower().rstrip(".")
        if not host:
            raise ValueError("invalid MongoDB endpoint")
        hosts.add(host)

    path = unquote(parsed.path.lstrip("/"))
    if "/" in path:
        raise ValueError("invalid MongoDB database path")
    if path and path != HAVEN_DATABASE_NAME:
        raise ValueError("MongoDB URI database does not match the application database")
    return hosts, HAVEN_DATABASE_NAME


def validate_staging_target(
    endpoint: str,
    *,
    target_environment: str,
    target_id: str,
    host_allowlist: str,
    database_allowlist: str,
    application_environment: str,
) -> TargetValidation:
    """Require explicit staging intent and exact host/database allowlists."""
    target_env = (target_environment or "").strip().lower()
    app_env = (application_environment or "").strip().lower()
    target_id = (target_id or "").strip()
    if app_env in ("production", "prod"):
        return TargetValidation(False, reason="production application mode is not permitted")
    if target_env != "staging":
        return TargetValidation(False, reason="explicit staging target is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", target_id):
        return TargetValidation(False, reason="a valid staging target ID is required")

    allowed_hosts = {
        value.strip().lower().rstrip(".")
        for value in (host_allowlist or "").split(",")
        if value.strip()
    }
    allowed_databases = {
        value.strip()
        for value in (database_allowlist or "").split(",")
        if value.strip()
    }
    if not allowed_hosts or "*" in allowed_hosts:
        return TargetValidation(False, reason="an exact staging MongoDB host allowlist is required")
    if not allowed_databases or "*" in allowed_databases:
        return TargetValidation(False, reason="an exact staging database allowlist is required")
    if HAVEN_DATABASE_NAME not in allowed_databases:
        return TargetValidation(False, reason="the application database is not allowlisted")

    try:
        target_hosts, database_name = _mongo_uri_identity(endpoint or "")
    except (TypeError, ValueError):
        return TargetValidation(False, reason="MongoDB endpoint identity is invalid or unavailable")
    if not target_hosts.issubset(allowed_hosts):
        return TargetValidation(False, reason="MongoDB endpoint host is not allowlisted")
    if database_name not in allowed_databases:
        return TargetValidation(False, reason="MongoDB database is not allowlisted")
    return TargetValidation(True, target_id=target_id, database_name=database_name)


def validate_configured_staging_target(
    endpoint: str,
    *,
    environment: Optional[Dict[str, str]] = None,
) -> TargetValidation:
    """Validate staging identity from environment variables without connecting."""
    settings = os.environ if environment is None else environment
    return validate_staging_target(
        endpoint,
        target_environment=settings.get(STAGING_ENVIRONMENT_VARIABLE, ""),
        target_id=settings.get(STAGING_TARGET_ID_VARIABLE, ""),
        host_allowlist=settings.get(STAGING_HOST_ALLOWLIST_VARIABLE, ""),
        database_allowlist=settings.get(STAGING_DATABASE_ALLOWLIST_VARIABLE, ""),
        application_environment=settings.get("ENVIRONMENT", "development"),
    )


def validate_configured_redis_target(
    endpoint: str,
    *,
    environment: Optional[Dict[str, str]] = None,
) -> TargetValidation:
    """Require an explicit Redis staging identity and exact host/database allowlists."""
    settings = os.environ if environment is None else environment
    app_env = settings.get("ENVIRONMENT", "development").strip().lower()
    if app_env in ("production", "prod"):
        return TargetValidation(False, reason="production application mode is not permitted")
    if settings.get("HAVEN_REDIS_TARGET_ENVIRONMENT", "").strip().lower() != "staging":
        return TargetValidation(False, reason="explicit staging Redis target is required")
    target_id = settings.get("HAVEN_STAGING_REDIS_TARGET_ID", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", target_id):
        return TargetValidation(False, reason="a valid staging Redis target ID is required")

    allowed_hosts = {
        value.strip().lower().rstrip(".")
        for value in settings.get("HAVEN_STAGING_REDIS_HOST_ALLOWLIST", "").split(",")
        if value.strip()
    }
    allowed_databases = {
        value.strip()
        for value in settings.get("HAVEN_STAGING_REDIS_DATABASE_ALLOWLIST", "").split(",")
        if value.strip()
    }
    if not allowed_hosts or "*" in allowed_hosts:
        return TargetValidation(False, reason="an exact staging Redis host allowlist is required")
    if not allowed_databases or "*" in allowed_databases:
        return TargetValidation(False, reason="an exact staging Redis database allowlist is required")

    try:
        parsed = urlsplit(endpoint or "")
        if parsed.scheme.lower() not in ("redis", "rediss") or not parsed.hostname:
            raise ValueError("invalid Redis endpoint")
        host = parsed.hostname.lower().rstrip(".")
        database_name = parsed.path.lstrip("/") or "0"
        if "/" in database_name or not database_name.isdigit():
            raise ValueError("invalid Redis database path")
    except (TypeError, ValueError):
        return TargetValidation(False, reason="Redis endpoint identity is invalid or unavailable")
    if host not in allowed_hosts:
        return TargetValidation(False, reason="Redis endpoint host is not allowlisted")
    if database_name not in allowed_databases:
        return TargetValidation(False, reason="Redis database is not allowlisted")
    return TargetValidation(True, target_id=target_id, database_name=database_name)


def _mongo_count(coll: Any, query: Dict[str, Any]) -> int:
    return int(coll.count_documents(query))


def _mongo_dup_groups(coll: Any, field: str) -> int:
    pipe = [
        # Sparse indexes include explicit nulls; only missing fields are omitted.
        {"$match": {field: {"$exists": True}}},
        {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$count": "dupe_groups"},
    ]
    res = list(coll.aggregate(pipe))
    if not res:
        return 0
    return int(res[0].get("dupe_groups") or res[0].get("n") or 0)


def _index_keys(meta: Dict[str, Any]) -> List[str]:
    return [key for key, _direction in _index_key_pattern(meta)]


def _index_key_pattern(meta: Dict[str, Any]) -> List[Tuple[str, Any]]:
    key = meta.get("key") or []
    if isinstance(key, dict):
        return [(str(name), direction) for name, direction in key.items()]
    return [
        (str(item[0]), item[1])
        for item in key
        if isinstance(item, (list, tuple)) and len(item) >= 2
    ]


def _index_name(keys: Tuple[Tuple[str, Any], ...] | List[Tuple[str, Any]]) -> str:
    return "_".join(f"{name}_{direction}" for name, direction in keys)


def _has_custom_collation(meta: Dict[str, Any]) -> bool:
    collation = meta.get("collation")
    return bool(collation and collation.get("locale") != "simple")


def check_unique_field(coll: Any, plan: UniqueIndexPlan) -> FieldCheck:
    """Read-only safety check for one planned unique index."""
    chk = FieldCheck(collection=plan.collection, field=plan.field, safe=True)
    try:
        chk.total = _mongo_count(coll, {})
        chk.with_value = _mongo_count(coll, {plan.field: {"$exists": True, "$ne": None}})
        chk.missing_field = _mongo_count(coll, {plan.field: {"$exists": False}})
        # BSON null only — not missing fields (Mongo `{field: null}` matches both).
        chk.null_value = _mongo_count(coll, {plan.field: {"$type": "null"}})
        chk.empty_string = _mongo_count(coll, {plan.field: ""})
    except Exception as e:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: could not read [{plan.collection}].{plan.field}: "
            f"{sanitize_error(e)}. Unique-index safety is not proven."
        )
        return chk

    try:
        chk.duplicate_groups = _mongo_dup_groups(coll, plan.field)
    except Exception as e:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: [{plan.collection}].{plan.field} — duplicate aggregate failed "
            f"({sanitize_error(e)}). Unique index creation is not proven safe."
        )
        return chk

    if chk.duplicate_groups > 0:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: [{plan.collection}].{plan.field} — {chk.duplicate_groups} duplicate "
            "value group(s) among indexed values, including explicit nulls. "
            "Unique index creation will fail. "
            "Remediation: inspect the collection in Atlas/local shell, keep one canonical "
            "document per value, and archive extras. Do not rewrite production records "
            "without an operator-approved backup. Duplicate values are not printed here."
        )

    if plan.unique and not plan.sparse:
        if chk.missing_field > 0:
            chk.safe = False
            chk.messages.append(
                f"BLOCKER: [{plan.collection}].{plan.field} — non-sparse unique index but "
                f"{chk.missing_field} document(s) omit the field. MongoDB indexes a single "
                "null key for missing fields. Remediation: backfill user_id (required) or "
                "remove incomplete documents after backup. Do not switch to sparse unless "
                "the data model makes the field optional."
            )
        if chk.null_value > 0:
            chk.safe = False
            chk.messages.append(
                f"BLOCKER: [{plan.collection}].{plan.field} — non-sparse unique index but "
                f"{chk.null_value} document(s) store explicit null. Remediation: set a real "
                "user_id or delete incomplete rows after backup."
            )
    elif plan.unique and plan.sparse:
        if chk.missing_field > 0:
            chk.messages.append(
                f"INFO: [{plan.collection}].{plan.field} — {chk.missing_field} doc(s) missing "
                "field; sparse index will exclude them."
            )
        if chk.null_value > 0:
            chk.messages.append(
                f"INFO: [{plan.collection}].{plan.field} — {chk.null_value} explicit null "
                "doc(s); sparse indexes include explicit nulls, and duplicate nulls are "
                "checked as duplicate keys."
            )

    if plan.unique and chk.empty_string > 1:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: [{plan.collection}].{plan.field} — {chk.empty_string} documents have "
            "empty-string values. Sparse unique indexes still include empty strings, so "
            "creation will fail. Remediation: replace empty strings with omitted fields "
            "(if optional) or distinct identifiers (if required)."
        )
    elif plan.unique and chk.empty_string == 1:
        chk.messages.append(
            f"INFO: [{plan.collection}].{plan.field} — 1 document has an empty-string "
            "value. Sparse unique indexes include empty strings. Remediation is optional "
            "until a second empty string appears; prefer a real identifier or omit the field."
        )

    if plan.unique and plan.sparse and plan.required_on_write and chk.missing_field > 0:
        chk.messages.append(
            f"INFO: [{plan.collection}].{plan.field} is required on new writes but "
            f"{chk.missing_field} existing document(s) omit it. Sparse unique is the "
            "migration safety net; backfill is operator-owned and not performed by this tool."
        )

    try:
        idx_info = coll.index_information()
    except Exception as e:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: could not read indexes for [{plan.collection}]: "
            f"{sanitize_error(e)}. Existing index conflicts cannot be ruled out."
        )
        idx_info = {}

    for name, meta in (idx_info or {}).items():
        if name == "_id_":
            continue
        key_pattern = _index_key_pattern(meta)
        keys_in_idx = [key for key, _direction in key_pattern]
        if name == f"{plan.field}_1" and key_pattern != [(plan.field, 1)]:
            chk.safe = False
            chk.messages.append(
                f"CONFLICT: [{plan.collection}].{plan.field} — existing index name "
                f"'{name}' is assigned to a different key pattern. MongoDB will reject "
                "the planned index until an operator reviews the conflict."
            )
        if keys_in_idx == [plan.field]:
            existing_unique = bool(meta.get("unique", False))
            existing_sparse = bool(meta.get("sparse", False))
            ttl = meta.get("expireAfterSeconds", None)
            chk.existing_indexes.append(
                f"{name} unique={existing_unique} sparse={existing_sparse} TTL={ttl}"
            )
            if key_pattern != [(plan.field, 1)]:
                chk.messages.append(
                    f"INFO: [{plan.collection}].{plan.field} has an index with a "
                    "different key direction; it does not match the planned ascending index."
                )
            elif (existing_unique != plan.unique or existing_sparse != plan.sparse
                  or ttl is not None or "partialFilterExpression" in meta
                or _has_custom_collation(meta) or bool(meta.get("hidden", False))):
                chk.safe = False
                chk.messages.append(
                    f"CONFLICT: [{plan.collection}].{plan.field} — existing index '{name}' "
                    "has options that differ from the planned index (including uniqueness, "
                    "sparsity, TTL, partial filter, or collation). MongoDB may reject the "
                    "planned create_index or the index may enforce different semantics. "
                    f"Operator review is required; this script never drops indexes."
                )
            else:
                chk.messages.append(
                    f"INFO: [{plan.collection}].{plan.field} — existing index '{name}' "
                    "matches the planned unique/sparse options (idempotent)."
                )
        elif plan.field in keys_in_idx:
            chk.messages.append(
                f"INFO: [{plan.collection}].{plan.field} appears in compound index '{name}' "
                "(not a unique-index conflict)."
            )

    try:
        # Best-effort type mix; skip if the server cannot $project $type.
        pipe = [
            {"$match": {plan.field: {"$exists": True, "$ne": None}}},
            {"$project": {"t": {"$type": f"${plan.field}"}}},
            {"$group": {"_id": "$t", "n": {"$sum": 1}}},
        ]
        variants = []
        for row in coll.aggregate(pipe):
            variants.append(str(row.get("_id")))
        chk.type_variants = sorted(set(variants))
        unexpected_types = [
            value_type for value_type in chk.type_variants
            if value_type not in ("string", "str")
        ]
        if unexpected_types:
            chk.safe = False
            chk.messages.append(
                f"BLOCKER: [{plan.collection}].{plan.field} contains unexpected BSON "
                f"type(s) {unexpected_types}; identifier fields must be scalar strings. "
                "Resolve schema drift and rerun preflight."
            )
        elif len(chk.type_variants) > 1:
            chk.messages.append(
                f"INFO: [{plan.collection}].{plan.field} has mixed BSON types "
                f"{chk.type_variants}. Uniqueness is per exact value; mixed types are "
                "unexpected schema variation."
            )
    except Exception as e:
        chk.safe = False
        chk.messages.append(
            f"BLOCKER: could not inspect BSON types for [{plan.collection}].{plan.field}: "
            f"{sanitize_error(e)}. Schema variation is not fully checked."
        )

    return chk


def check_ttl_index(db: Any) -> Tuple[List[str], List[str]]:
    blockers: List[str] = []
    info: List[str] = []
    coll_name = "responder_setup_tokens"
    field = "expires_at"
    try:
        idx_info = db[coll_name].index_information()
    except Exception as e:
        blockers.append(
            f"BLOCKER: could not inspect TTL index on [{coll_name}].{field}: "
            f"{sanitize_error(e)}. Existing index conflicts cannot be ruled out."
        )
        return blockers, info
    ttl_found = False
    for name, meta in (idx_info or {}).items():
        keys = _index_keys(meta)
        if keys == [field]:
            if "expireAfterSeconds" in meta:
                ttl_found = True
                if meta.get("expireAfterSeconds") != 0:
                    blockers.append(
                        f"CONFLICT: [{coll_name}].{field} — existing index '{name}' has "
                        f"expireAfterSeconds={meta.get('expireAfterSeconds')}, planned 0. "
                        "Drop is operator-only after backup."
                    )
            else:
                blockers.append(
                    f"CONFLICT: [{coll_name}].{field} — existing index '{name}' has no TTL "
                    "option; create_index with expireAfterSeconds=0 will be rejected. "
                    "Operator must drop '{name}' after backup. This tooling never drops indexes."
                )
    if ttl_found:
        info.append("TTL index on [responder_setup_tokens].expires_at already exists.")
    else:
        info.append("TTL index on [responder_setup_tokens].expires_at will be created by setup.")
    return blockers, info


def check_standard_index_conflicts(db: Any) -> Tuple[List[str], List[str]]:
    """Check non-unique planned index options and generated-name collisions."""
    blockers: List[str] = []
    info: List[str] = []
    for op in STANDARD_INDEX_OPS:
        if op.unique:
            continue
        try:
            indexes = db[op.collection].index_information()
        except Exception as e:
            blockers.append(
                f"BLOCKER: could not read indexes for [{op.collection}] while checking "
                f"planned {op.keys}: {sanitize_error(e)}. Index conflicts cannot be ruled out."
            )
            continue

        expected_name = _index_name(op.keys)
        for name, meta in (indexes or {}).items():
            if name == "_id_":
                continue
            pattern = _index_key_pattern(meta)
            if name == expected_name and pattern != list(op.keys):
                blockers.append(
                    f"CONFLICT: [{op.collection}] planned index {op.keys} uses generated "
                    f"name '{expected_name}', already assigned to a different key pattern."
                )
                continue
            if pattern != list(op.keys):
                continue
            ttl = meta.get("expireAfterSeconds")
            expected_ttl = op.expire_after_seconds
            if (bool(meta.get("unique", False)) or bool(meta.get("sparse", False)) != op.sparse
                    or ttl != expected_ttl or "partialFilterExpression" in meta
                    or _has_custom_collation(meta) or bool(meta.get("hidden", False))):
                blockers.append(
                    f"CONFLICT: [{op.collection}] existing index '{name}' matches planned "
                    f"keys {op.keys} but has incompatible uniqueness, sparsity, TTL, "
                    "partial-filter, collation, or hidden options. Operator review is required."
                )
            else:
                info.append(
                    f"INFO: [{op.collection}] existing index '{name}' matches planned "
                    f"keys {op.keys} and options."
                )
    return blockers, info


def _index_summary(name: str, meta: Dict[str, Any]) -> str:
    keys = _index_keys(meta)
    unique = bool(meta.get("unique", False))
    sparse = bool(meta.get("sparse", False))
    ttl = meta.get("expireAfterSeconds", None)
    partial = "partialFilterExpression" in meta
    collation = (meta.get("collation") or {}).get("locale", "default")
    hidden = bool(meta.get("hidden", False))
    return (
        f"{name} keys={keys} unique={unique} sparse={sparse} TTL={ttl} "
        f"partial={partial} collation={collation} hidden={hidden}"
    )


def _inventory_collection_indexes(db: Any, collection: str) -> Tuple[List[str], Optional[str]]:
    try:
        idx_info = db[collection].index_information()
    except Exception as e:
        return [], sanitize_error(e)
    rows = []
    for name, meta in (idx_info or {}).items():
        if name == "_id_":
            continue
        rows.append(_index_summary(name, meta if isinstance(meta, dict) else {}))
    return rows, None


def run_preflight(db: Any, *, environment_label: str = "") -> PreflightResult:
    """Read-only. Never writes, never drops, never prints document values."""
    result = PreflightResult(environment_label=environment_label)
    for drift in catalog_consistency_errors():
        result.blockers.append(drift)
        result.info.append(drift)
    for plan in UNIQUE_INDEX_PLANS:
        try:
            coll = db[plan.collection]
        except Exception as e:
            result.blockers.append(
                f"BLOCKER: could not access collection [{plan.collection}]: "
                f"{sanitize_error(e)}. Preflight is incomplete."
            )
            continue
        chk = check_unique_field(coll, plan)
        result.checks.append(chk)
        for msg in chk.messages:
            if msg.startswith("BLOCKER") or msg.startswith("CONFLICT"):
                result.blockers.append(msg)
            else:
                result.info.append(msg)
        if not chk.safe:
            # Ensure a blocker exists even if a check set safe=False without a prefix.
            if not any(m.startswith("BLOCKER") or m.startswith("CONFLICT") for m in chk.messages):
                result.blockers.append(
                    f"BLOCKER: [{plan.collection}].{plan.field} failed preflight."
                )
    ttl_blockers, ttl_info = check_ttl_index(db)
    result.blockers.extend(ttl_blockers)
    result.info.extend(ttl_info)
    index_blockers, index_info = check_standard_index_conflicts(db)
    result.blockers.extend(index_blockers)
    result.info.extend(index_info)

    inventory_names = sorted({
        p.collection for p in UNIQUE_INDEX_PLANS
    } | {p.collection for p in ADVISORY_UNIQUE_INDEX_PLANS} | {"responder_setup_tokens"})
    inventory_names = sorted(set(inventory_names) | {op.collection for op in STANDARD_INDEX_OPS})
    for coll_name in inventory_names:
        rows, err = _inventory_collection_indexes(db, coll_name)
        if err:
            result.blockers.append(
                f"BLOCKER: could not list indexes for [{coll_name}]: {err}. "
                "Existing index conflicts cannot be ruled out."
            )
            continue
        result.index_inventory[coll_name] = rows

    for plan in ADVISORY_UNIQUE_INDEX_PLANS:
        try:
            chk = check_unique_field(db[plan.collection], plan)
        except Exception as e:
            result.blockers.append(
                f"BLOCKER: advisory schema read [{plan.collection}].{plan.field} failed: "
                f"{sanitize_error(e)}. Preflight is incomplete."
            )
            continue
        result.advisory_checks.append(chk)
        result.blockers.extend(
            message for message in chk.messages
            if message.startswith("BLOCKER")
            and any(token in message for token in (
                "could not read", "duplicate aggregate failed", "could not inspect BSON types"
            ))
        )
        dup = "duplicates present" if chk.duplicate_groups else "no duplicate groups"
        result.info.append(
            f"INFO: advisory (NOT created by setup) [{plan.collection}].{plan.field} "
            f"— {dup}; missing={chk.missing_field}; null={chk.null_value}; "
            f"empty_string={chk.empty_string}. {plan.notes}"
        )
    return result


def format_preflight_report(result: PreflightResult) -> str:
    lines = [
        "Haven MongoDB Pre-flight Index Check",
        f"Target environment : {result.environment_label}",
        f"Database name      : {result.database_name}",
        "=" * 60,
        "",
        "--- Checking all planned unique index fields ---",
    ]
    for chk in result.checks:
        lines.append(
            f"\n  [{chk.collection}].{chk.field}"
        )
        lines.append(f"    total_docs    : {chk.total}")
        lines.append(f"    with_value    : {chk.with_value}")
        lines.append(f"    null_value    : {chk.null_value}")
        lines.append(f"    missing_field : {chk.missing_field}")
        lines.append(f"    empty_string  : {chk.empty_string}")
        lines.append(f"    duplicate_grps: {chk.duplicate_groups}")
        if chk.existing_indexes:
            for idx in chk.existing_indexes:
                lines.append(f"    existing_index: {idx}")
        if chk.type_variants:
            lines.append(f"    value_types   : {', '.join(chk.type_variants)}")
        for msg in chk.messages:
            prefix = "    *** " if msg.startswith("BLOCKER") or msg.startswith("CONFLICT") else "    --- "
            lines.append(prefix + msg)
        if chk.safe:
            lines.append(f"    [OK] no blockers for [{chk.collection}].{chk.field}")
    if result.index_inventory:
        lines.append("\n--- Existing indexes (names and options only; no document values) ---")
        for coll_name in sorted(result.index_inventory):
            rows = result.index_inventory[coll_name]
            if not rows:
                lines.append(f"  [{coll_name}] (no non-_id indexes yet)")
            else:
                for row in rows:
                    lines.append(f"  [{coll_name}] {row}")
    if result.advisory_checks:
        lines.append("\n--- Advisory unique fields (NOT created by setup_indexes.py) ---")
        for chk in result.advisory_checks:
            lines.append(
                f"  [{chk.collection}].{chk.field} total={chk.total} dups={chk.duplicate_groups} "
                f"missing={chk.missing_field} null={chk.null_value} empty={chk.empty_string}"
            )
    lines.append("\n--- TTL ---")
    for msg in result.info:
        if "TTL" in msg or "ttl" in msg:
            lines.append(f"  {msg}")
    lines.append("\n" + "=" * 60)
    lines.append(f"Target environment : {result.environment_label}")
    if result.blockers:
        lines.append(f"PREFLIGHT FAILED — {len(result.blockers)} blocker(s) found:")
        for i, b in enumerate(result.blockers, 1):
            lines.append(f"  [{i}] {b}")
        lines.append("\nDo NOT run setup_indexes.py until all blockers are resolved.")
    else:
        lines.append("PREFLIGHT PASSED — no blockers found.")
        lines.append(
            "No index operation was performed. Review the offline plan and obtain "
            "separate operator authorization before any staging migration."
        )
        extra = [m for m in result.info if m.startswith("INFO")]
        if extra:
            lines.append(f"\nInformational notes ({len(extra)}):")
            for note in extra:
                lines.append(f"  - {note}")
    return "\n".join(lines)


def create_kwargs(op: IndexOp) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if op.unique:
        kwargs["unique"] = True
    if op.sparse:
        kwargs["sparse"] = True
    if op.expire_after_seconds is not None:
        kwargs["expireAfterSeconds"] = op.expire_after_seconds
    return kwargs


def format_index_plan() -> str:
    """Render intended operations without accessing database state."""
    lines = ["Planned standard MongoDB indexes:"]
    for op in STANDARD_INDEX_OPS:
        options = [f"unique={op.unique}", f"sparse={op.sparse}"]
        if op.expire_after_seconds is not None:
            options.append(f"expireAfterSeconds={op.expire_after_seconds}")
        lines.append(f"  [{op.collection}] {list(op.keys)} {' '.join(options)}")
    lines.append("Planned Atlas Search indexes:")
    for collection, name, field_name, dimensions, similarity in ATLAS_SEARCH_INDEX_PLANS:
        lines.append(
            f"  [{collection}] {name}: {field_name} dimensions={dimensions} "
            f"similarity={similarity}"
        )
    return "\n".join(lines)
