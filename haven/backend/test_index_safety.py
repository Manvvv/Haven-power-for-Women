"""Read-only preflight and index-setup safety tests.

Uses in-memory fake collections. Does not connect to MongoDB Atlas or
mutate any real database.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from index_catalog import (
    HAVEN_DATABASE_NAME,
    INDEX_SETUP_CONFIRM_VALUE,
    UNIQUE_INDEX_PLANS,
    UniqueIndexPlan,
    catalog_consistency_errors,
    check_ttl_index,
    check_unique_field,
    classify_mongo_target,
    confirm_index_setup_authorized,
    format_index_plan,
    format_preflight_report,
    index_setup_requires_confirm,
    run_preflight,
    sanitize_error,
    unique_ops_as_tuples,
    validate_configured_redis_target,
    validate_configured_staging_target,
    validate_staging_target,
)


class FakeCollection:
    def __init__(self, docs=None, indexes=None, fail_aggregate=False,
                 fail_count=False, fail_indexes=False, fail_type_aggregate=False):
        self.docs = list(docs or [])
        self._indexes = dict(indexes) if indexes is not None else {
            "_id_": {"key": [("_id", 1)]}
        }
        self.fail_aggregate = fail_aggregate
        self.fail_count = fail_count
        self.fail_indexes = fail_indexes
        self.fail_type_aggregate = fail_type_aggregate
        self.create_calls = []

    def count_documents(self, query):
        if self.fail_count:
            raise RuntimeError("count unavailable")
        return sum(1 for d in self.docs if _match(d, query))

    def aggregate(self, pipeline):
        if self.fail_aggregate or (
            self.fail_type_aggregate and any("$project" in stage for stage in pipeline)
        ):
            raise RuntimeError("aggregate unavailable mongodb+srv://user:pass@cluster.mongodb.net/Haven")
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _match(d, stage["$match"])]
            elif "$group" in stage:
                spec = stage["$group"]
                id_expr = spec.get("_id")
                if id_expr == "$t":
                    buckets = {}
                    for d in docs:
                        buckets[d.get("t")] = buckets.get(d.get("t"), 0) + 1
                    docs = [{"_id": k, "n": n} for k, n in buckets.items()]
                else:
                    field = str(id_expr).lstrip("$")
                    buckets = {}
                    for d in docs:
                        key = d.get(field)
                        if isinstance(key, list):
                            key = tuple(key)
                        buckets[key] = buckets.get(key, 0) + 1
                    docs = [{"_id": k, "n": n} for k, n in buckets.items()]
            elif "$project" in stage:
                proj = stage["$project"]
                t_expr = (proj.get("t") or {}).get("$type")
                field = str(t_expr or "").lstrip("$")
                out = []
                for d in docs:
                    val = d.get(field)
                    out.append({"t": type(val).__name__})
                docs = out
            elif "$count" in stage:
                name = stage["$count"]
                docs = [{name: len(docs)}]
        return docs

    def index_information(self):
        if self.fail_indexes:
            raise RuntimeError("index listing unavailable")
        return dict(self._indexes)

    def create_index(self, keys, **kwargs):
        key_names = [k for k, _ in keys]
        name = kwargs.get("name") or "_".join(key_names) + "_1"
        for existing_name, meta in self._indexes.items():
            existing_keys = [k for k, _ in meta.get("key", [])]
            if existing_keys == key_names:
                same_unique = bool(meta.get("unique")) == bool(kwargs.get("unique"))
                same_sparse = bool(meta.get("sparse")) == bool(kwargs.get("sparse"))
                same_ttl = meta.get("expireAfterSeconds") == kwargs.get("expireAfterSeconds")
                if same_unique and same_sparse and same_ttl:
                    self.create_calls.append(name)
                    return existing_name
                raise RuntimeError("IndexOptionsConflict")
        self._indexes[name] = {
            "key": list(keys),
            "unique": bool(kwargs.get("unique")),
            "sparse": bool(kwargs.get("sparse")),
        }
        if "expireAfterSeconds" in kwargs:
            self._indexes[name]["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
        self.create_calls.append(name)
        return name


class FakeDB(dict):
    def __init__(self):
        super().__init__()
        self.command_calls = []

    def __getitem__(self, name):
        if name not in self:
            dict.__setitem__(self, name, FakeCollection([]))
        return dict.__getitem__(self, name)

    def command(self, command):
        self.command_calls.append(command)
        return {}


class FailingCollectionDB(FakeDB):
    def __getitem__(self, name):
        if name == "sos_cases":
            raise RuntimeError("collection access unavailable")
        return super().__getitem__(name)


class FakeMongoClient:
    def __init__(self, db):
        self.db = db
        self.admin = self

    def command(self, command):
        return {"ok": 1}

    def __getitem__(self, _name):
        return self.db


def _match(doc, query):
    if not query:
        return True
    for field, spec in query.items():
        if isinstance(spec, dict):
            if "$exists" in spec:
                exists = field in doc
                if bool(spec["$exists"]) != exists:
                    return False
            if "$ne" in spec:
                if field not in doc or doc[field] == spec["$ne"]:
                    return False
            if "$type" in spec and spec["$type"] in ("null", 10, "Null"):
                if field not in doc or doc[field] is not None:
                    return False
            if "$gt" in spec:
                if field not in doc or not (doc[field] > spec["$gt"]):
                    return False
        elif spec == "":
            if doc.get(field) != "":
                return False
        elif spec is None:
            if field in doc and doc[field] is not None:
                return False
        else:
            if doc.get(field) != spec:
                return False
    return True


def _plan(collection, field, unique=True, sparse=True):
    return UniqueIndexPlan(collection, field, unique=unique, sparse=sparse)


def test_catalog_covers_required_unique_fields():
    pairs = {(p.collection, p.field) for p in UNIQUE_INDEX_PLANS}
    expected = {
        ("sos_cases", "case_id"),
        ("culprits", "culprit_id"),
        ("voice_sos_config", "user_id"),
        ("sos_events", "event_id"),
        ("ai_analyses", "case_id"),
        ("responders", "responder_id"),
        ("responders", "badge_number"),
        ("dispatch_requests", "dispatch_id"),
        ("dispatch_attempts", "attempt_id"),
        ("provider_registrations", "registration_id"),
        ("provider_requests", "request_id"),
        ("responder_setup_tokens", "token_hash"),
    }
    assert expected <= pairs
    voice = next(p for p in UNIQUE_INDEX_PLANS if p.collection == "voice_sos_config")
    assert voice.sparse is False


def test_duplicate_values_are_blockers():
    coll = FakeCollection([{"case_id": "A"}, {"case_id": "A"}, {"case_id": "B"}])
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    assert chk.duplicate_groups == 1
    assert any(m.startswith("BLOCKER") for m in chk.messages)


def test_missing_field_blocks_non_sparse_unique():
    coll = FakeCollection([{"user_id": "u1"}, {}])
    chk = check_unique_field(coll, _plan("voice_sos_config", "user_id", sparse=False))
    assert chk.missing_field == 1
    assert chk.safe is False
    assert any("non-sparse" in m for m in chk.messages)


def test_explicit_null_blocks_non_sparse_unique():
    coll = FakeCollection([{"user_id": "u1"}, {"user_id": None}])
    chk = check_unique_field(coll, _plan("voice_sos_config", "user_id", sparse=False))
    assert chk.null_value == 1
    assert chk.missing_field == 0
    assert chk.safe is False


def test_missing_field_is_info_for_sparse_unique():
    coll = FakeCollection([{"responder_id": "r1"}, {}])
    chk = check_unique_field(coll, _plan("responders", "responder_id", sparse=True))
    assert chk.missing_field == 1
    assert chk.safe is True
    assert any(m.startswith("INFO") for m in chk.messages)


def test_duplicate_explicit_nulls_block_sparse_unique():
    coll = FakeCollection([{"case_id": None}, {"case_id": None}])
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", sparse=True))
    assert chk.null_value == 2
    assert chk.duplicate_groups == 1
    assert chk.safe is False
    assert any(m.startswith("BLOCKER") for m in chk.messages)


def test_empty_string_duplicates_block_sparse_unique():
    coll = FakeCollection([{"badge_number": ""}, {"badge_number": ""}, {"badge_number": "HN-1"}])
    chk = check_unique_field(coll, _plan("responders", "badge_number", sparse=True))
    assert chk.empty_string == 2
    assert chk.safe is False


def test_conflicting_existing_index_is_blocker():
    coll = FakeCollection(
        [{"case_id": "A"}],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "case_id_1": {"key": [("case_id", 1)], "unique": False, "sparse": False},
        },
    )
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", unique=True, sparse=True))
    assert chk.safe is False
    assert any(m.startswith("CONFLICT") for m in chk.messages)


def test_partial_unique_index_is_not_treated_as_matching():
    coll = FakeCollection(
        [{"case_id": "A"}],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "case_id_1": {
                "key": [("case_id", 1)], "unique": True, "sparse": True,
                "partialFilterExpression": {"active": True},
            },
        },
    )
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", unique=True, sparse=True))
    assert chk.safe is False
    assert any(m.startswith("CONFLICT") and "partial filter" in m for m in chk.messages)


def test_generated_index_name_collision_is_blocker():
    coll = FakeCollection(
        [{"case_id": "A"}],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "case_id_1": {"key": [("other", 1)]},
        },
    )
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", unique=True, sparse=True))
    assert chk.safe is False
    assert any(m.startswith("CONFLICT") and "different key pattern" in m for m in chk.messages)


def test_matching_existing_index_is_idempotent():
    coll = FakeCollection(
        [{"case_id": "A"}],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "case_id_1": {"key": [("case_id", 1)], "unique": True, "sparse": True},
        },
    )
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", unique=True, sparse=True))
    assert chk.safe is True
    assert any("idempotent" in m for m in chk.messages)


def test_failed_duplicate_aggregate_is_blocker():
    coll = FakeCollection([{"case_id": "A"}], fail_aggregate=True)
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    report = " ".join(chk.messages)
    assert "mongodb+srv://" not in report
    assert "[redacted]" in report or "aggregate failed" in report


def test_failed_document_read_is_blocker():
    coll = FakeCollection([{"case_id": "A"}], fail_count=True)
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    assert any(m.startswith("BLOCKER") and "could not read" in m for m in chk.messages)


def test_failed_index_inventory_is_blocker():
    coll = FakeCollection([{"case_id": "A"}], fail_indexes=True)
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    assert any(m.startswith("BLOCKER") and "could not read indexes" in m for m in chk.messages)


def test_failed_schema_type_inspection_is_blocker():
    coll = FakeCollection([{"case_id": "A"}], fail_type_aggregate=True)
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    assert any(m.startswith("BLOCKER") and "BSON types" in m for m in chk.messages)


def test_non_string_identifier_type_blocks_preflight():
    coll = FakeCollection([{"case_id": ["A", "B"]}])
    chk = check_unique_field(coll, _plan("sos_cases", "case_id"))
    assert chk.safe is False
    assert any(m.startswith("BLOCKER") and "scalar strings" in m for m in chk.messages)


def test_inaccessible_planned_collection_blocks_preflight():
    result = run_preflight(FailingCollectionDB(), environment_label="test")
    assert result.ok is False
    assert any("could not access collection [sos_cases]" in message for message in result.blockers)


def test_ttl_conflict_without_expire_option():
    db = FakeDB()
    db["responder_setup_tokens"] = FakeCollection(
        [],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "expires_at_1": {"key": [("expires_at", 1)]},
        },
    )
    blockers, _info = check_ttl_index(db)
    assert blockers
    assert "TTL" in blockers[0] or "expire" in blockers[0]


def test_nonunique_index_option_conflict_is_blocker():
    db = FakeDB()
    db["sos_cases"] = FakeCollection(
        [],
        indexes={
            "_id_": {"key": [("_id", 1)]},
            "created_at_-1": {"key": [("created_at", -1)], "unique": True},
        },
    )
    result = run_preflight(db, environment_label="test")
    assert result.ok is False
    assert any("planned keys" in msg and "uniqueness" in msg for msg in result.blockers)


def test_index_inventory_includes_nonunique_only_collections():
    result = run_preflight(FakeDB(), environment_label="test")
    assert "trusted_contacts" in result.index_inventory


def test_run_preflight_clean_database_passes():
    db = FakeDB()
    for plan in UNIQUE_INDEX_PLANS:
        db[plan.collection] = FakeCollection([{plan.field: f"id-{plan.collection}"}])
    result = run_preflight(db, environment_label="test")
    assert result.ok
    assert result.database_name == HAVEN_DATABASE_NAME


def test_run_preflight_nonzero_semantics_on_blockers():
    db = FakeDB()
    db["sos_cases"] = FakeCollection([{"case_id": "x"}, {"case_id": "x"}])
    result = run_preflight(db, environment_label="test")
    assert result.ok is False
    text = format_preflight_report(result)
    assert "PREFLIGHT FAILED" in text
    assert "duplicate value group" in text
    assert 'case_id=' not in text


def test_repeated_create_index_is_idempotent():
    coll = FakeCollection([{"case_id": "A"}])
    name1 = coll.create_index([("case_id", 1)], unique=True, sparse=True)
    name2 = coll.create_index([("case_id", 1)], unique=True, sparse=True)
    assert name1 == name2
    with pytest.raises(RuntimeError):
        coll.create_index([("case_id", 1)], unique=True, sparse=False)


def test_blocked_preconditions_prevent_index_creation_decision():
    db = FakeDB()
    db["voice_sos_config"] = FakeCollection([{}, {}])
    result = run_preflight(db, environment_label="test")
    assert not result.ok
    # setup_indexes.py exits before create_index when preflight fails.


def test_classify_endpoint_does_not_expose_secrets():
    uri = "mongodb+srv://user:super-secret-password@cluster.mongodb.net/Haven?retryWrites=true"
    info = classify_mongo_target(uri)
    blob = str(info)
    assert "super-secret-password" not in blob
    assert "user:" not in blob
    assert info["kind"] == "atlas"
    assert info["label"] == "MongoDB Atlas (cloud)"
    local = classify_mongo_target("mongodb://127.0.0.1:27017/Haven")
    assert local["kind"] == "local"
    assert "27017" not in local["label"]


def test_sanitize_error_strips_uris():
    err = RuntimeError(
        "auth failed mongodb+srv://alice:pw@cluster.mongodb.net/Haven "
        "password=example-secret token=example-token"
    )
    text = sanitize_error(err)
    assert "alice" not in text
    assert "example-secret" not in text
    assert "example-token" not in text
    assert "[redacted]" in text


def _staging_environment(**overrides):
    values = {
        "HAVEN_DATABASE_ENVIRONMENT": "staging",
        "HAVEN_STAGING_TARGET_ID": "haven-stage",
        "HAVEN_STAGING_MONGO_HOST_ALLOWLIST": "stage.example.net",
        "HAVEN_STAGING_DATABASE_ALLOWLIST": "Haven",
        "ENVIRONMENT": "development",
    }
    values.update(overrides)
    return values


def test_missing_staging_target_configuration_is_rejected():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    result = validate_configured_staging_target(uri, environment={})
    assert result.approved is False
    assert "staging" in result.reason


def test_unknown_host_is_rejected_by_staging_allowlist():
    uri = "mongodb://safe-test-user:safe-test-password@unknown.example.net:27017/Haven"
    result = validate_configured_staging_target(uri, environment=_staging_environment())
    assert result.approved is False
    assert "not allowlisted" in result.reason


def test_production_application_mode_is_rejected_for_staging():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    result = validate_configured_staging_target(
        uri,
        environment=_staging_environment(ENVIRONMENT="production"),
    )
    assert result.approved is False
    assert "production" in result.reason


def test_allowlisted_staging_target_is_approved_without_disclosing_host():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    result = validate_configured_staging_target(uri, environment=_staging_environment())
    assert result.approved is True
    assert result.target_id == "haven-stage"
    assert result.database_name == HAVEN_DATABASE_NAME


def _staging_redis_environment(**overrides):
    values = {
        "HAVEN_REDIS_TARGET_ENVIRONMENT": "staging",
        "HAVEN_STAGING_REDIS_TARGET_ID": "haven-redis-stage",
        "HAVEN_STAGING_REDIS_HOST_ALLOWLIST": "redis-stage.example.net",
        "HAVEN_STAGING_REDIS_DATABASE_ALLOWLIST": "2",
        "ENVIRONMENT": "development",
    }
    values.update(overrides)
    return values


def test_redis_target_requires_explicit_staging_configuration():
    uri = "rediss://safe-test-user:safe-test-password@redis-stage.example.net:6380/2"
    result = validate_configured_redis_target(uri, environment={})
    assert result.approved is False


def test_redis_target_rejects_non_allowlisted_host_and_production_mode():
    env = _staging_redis_environment()
    uri = "rediss://safe-test-user:safe-test-password@unknown.example.net:6380/2"
    assert not validate_configured_redis_target(uri, environment=env).approved
    assert not validate_configured_redis_target(
        uri,
        environment=_staging_redis_environment(ENVIRONMENT="production"),
    ).approved


def test_allowlisted_redis_staging_target_is_approved():
    uri = "rediss://safe-test-user:safe-test-password@redis-stage.example.net:6380/2"
    result = validate_configured_redis_target(
        uri, environment=_staging_redis_environment()
    )
    assert result.approved is True
    assert result.target_id == "haven-redis-stage"
    assert result.database_name == "2"


def test_database_mismatch_is_rejected():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Other"
    result = validate_configured_staging_target(uri, environment=_staging_environment())
    assert result.approved is False
    assert "identity is invalid" in result.reason


def test_preflight_target_check_never_constructs_mongo_client(monkeypatch, capsys):
    import preflight_index_check

    monkeypatch.setattr(preflight_index_check, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["preflight_index_check.py", "--check-target"])
    monkeypatch.setenv("MONGO_ENDPOINT", "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven")
    for key, value in _staging_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        preflight_index_check,
        "MongoClient",
        lambda *_args, **_kwargs: pytest.fail("target check must not connect"),
    )

    assert preflight_index_check.main() == 0
    output = capsys.readouterr().out
    assert "haven-stage" in output
    assert "safe-test-password" not in output
    assert "stage.example.net" not in output


def test_preflight_rejects_unknown_target_before_connecting(monkeypatch, capsys):
    import preflight_index_check

    monkeypatch.setattr(preflight_index_check, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["preflight_index_check.py"])
    monkeypatch.setenv(
        "MONGO_ENDPOINT",
        "mongodb://safe-test-user:safe-test-password@unknown.example.net:27017/Haven",
    )
    for key, value in _staging_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        preflight_index_check,
        "MongoClient",
        lambda *_args, **_kwargs: pytest.fail("unknown target must not connect"),
    )

    assert preflight_index_check.main() == 1
    output = capsys.readouterr().out
    assert "unknown.example.net" not in output
    assert "safe-test-password" not in output
    assert "No database connection was attempted" in output


def test_index_plan_is_printable_offline():
    plan = format_index_plan()
    assert "sos_cases" in plan
    assert "culpritIndex" in plan
    assert "responder_setup_tokens" in plan


def test_missing_staging_target_identifier_rejected():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    res1 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_TARGET_ID=""))
    assert res1.approved is False
    assert "valid staging target ID is required" in res1.reason
    res2 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_TARGET_ID="invalid target"))
    assert res2.approved is False
    assert "valid staging target ID is required" in res2.reason
    res3 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_TARGET_ID="-starts-with-dash"))
    assert res3.approved is False
    assert "valid staging target ID is required" in res3.reason


def test_missing_and_wildcard_host_allowlist_rejected():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    res1 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_MONGO_HOST_ALLOWLIST=""))
    assert res1.approved is False
    assert "host allowlist is required" in res1.reason
    res2 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_MONGO_HOST_ALLOWLIST="*"))
    assert res2.approved is False
    assert "host allowlist is required" in res2.reason


def test_missing_and_wildcard_database_allowlist_rejected():
    uri = "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven"
    res1 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_DATABASE_ALLOWLIST=""))
    assert res1.approved is False
    assert "database allowlist is required" in res1.reason
    res2 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_DATABASE_ALLOWLIST="*"))
    assert res2.approved is False
    assert "database allowlist is required" in res2.reason
    res3 = validate_configured_staging_target(uri, environment=_staging_environment(HAVEN_STAGING_DATABASE_ALLOWLIST="OtherDatabase"))
    assert res3.approved is False
    assert "application database is not allowlisted" in res3.reason


def test_missing_and_invalid_mongodb_endpoint_rejected():
    res1 = validate_configured_staging_target("", environment=_staging_environment())
    assert res1.approved is False
    assert "identity is invalid" in res1.reason
    res2 = validate_configured_staging_target(None, environment=_staging_environment())
    assert res2.approved is False
    assert "identity is invalid" in res2.reason
    res3 = validate_configured_staging_target("http://stage.example.net/Haven", environment=_staging_environment())
    assert res3.approved is False
    assert "identity is invalid" in res3.reason
    res4 = validate_configured_staging_target("mongodb://user:pass@stage.example.net/haven", environment=_staging_environment())
    assert res4.approved is False
    assert "identity is invalid" in res4.reason


def test_show_index_plan_cli_never_connects(monkeypatch, capsys):
    import preflight_index_check
    monkeypatch.setattr(preflight_index_check, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["preflight_index_check.py", "--show-index-plan"])
    monkeypatch.setattr(
        preflight_index_check,
        "MongoClient",
        lambda *_args, **_kwargs: pytest.fail("show-index-plan must never connect to MongoDB"),
    )
    monkeypatch.delenv("MONGO_ENDPOINT", raising=False)
    monkeypatch.delenv("HAVEN_DATABASE_ENVIRONMENT", raising=False)
    assert preflight_index_check.main() == 0
    output = capsys.readouterr().out
    assert "Planned standard MongoDB indexes:" in output
    assert "Planned Atlas Search indexes:" in output


def test_read_only_preflight_performs_zero_writes():
    class MutatingAttemptError(RuntimeError):
        pass

    class WriteGuardedCollection(FakeCollection):
        def insert_one(self, *a, **k):
            raise MutatingAttemptError("insert_one called")
        def insert_many(self, *a, **k):
            raise MutatingAttemptError("insert_many called")
        def update_one(self, *a, **k):
            raise MutatingAttemptError("update_one called")
        def update_many(self, *a, **k):
            raise MutatingAttemptError("update_many called")
        def delete_one(self, *a, **k):
            raise MutatingAttemptError("delete_one called")
        def delete_many(self, *a, **k):
            raise MutatingAttemptError("delete_many called")
        def drop(self, *a, **k):
            raise MutatingAttemptError("drop called")
        def drop_index(self, *a, **k):
            raise MutatingAttemptError("drop_index called")
        def drop_indexes(self, *a, **k):
            raise MutatingAttemptError("drop_indexes called")
        def create_index(self, *a, **k):
            raise MutatingAttemptError("create_index called during preflight")

    db = FakeDB()
    for plan in UNIQUE_INDEX_PLANS:
        db[plan.collection] = WriteGuardedCollection([{plan.field: f"sample-{plan.collection}"}])
    result = run_preflight(db, environment_label="strict-write-guard-test")
    assert result.ok is True


def test_target_check_rejects_missing_staging_environment_variable(monkeypatch, capsys):
    import preflight_index_check
    monkeypatch.setattr(preflight_index_check, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["preflight_index_check.py", "--check-target"])
    monkeypatch.delenv("HAVEN_DATABASE_ENVIRONMENT", raising=False)
    monkeypatch.setenv("MONGO_ENDPOINT", "mongodb://dummy-user:dummy-pass@stage.example.net/Haven")
    assert preflight_index_check.main() == 1
    output = capsys.readouterr().out
    assert "explicit staging target is required" in output
    assert "No database connection was attempted" in output


def test_production_and_atlas_require_explicit_confirm(monkeypatch):
    assert index_setup_requires_confirm("production", "mongodb://localhost:27017") is True
    assert index_setup_requires_confirm(
        "development", "mongodb+srv://u:p@cluster.mongodb.net/Haven"
    ) is True
    assert index_setup_requires_confirm("development", "mongodb://127.0.0.1:27017") is False
    monkeypatch.delenv("HAVEN_ALLOW_INDEX_SETUP", raising=False)
    assert confirm_index_setup_authorized() is False
    monkeypatch.setenv("HAVEN_ALLOW_INDEX_SETUP", INDEX_SETUP_CONFIRM_VALUE)
    assert confirm_index_setup_authorized() is True


def test_cors_production_requires_public_origin():
    from main import resolve_cors_origins

    dev = resolve_cors_origins(
        is_production=False, allowed_origins_raw=None, frontend_url=None
    )
    assert "http://localhost:3000" in dev

    prod = resolve_cors_origins(
        is_production=True,
        allowed_origins_raw="https://haven.example",
        frontend_url=None,
    )
    assert prod == ["https://haven.example"]

    with pytest.raises(RuntimeError):
        resolve_cors_origins(
            is_production=True, allowed_origins_raw=None, frontend_url=None
        )
    with pytest.raises(RuntimeError):
        resolve_cors_origins(
            is_production=True,
            allowed_origins_raw="http://localhost:3000",
            frontend_url=None,
        )
    with pytest.raises(RuntimeError):
        resolve_cors_origins(
            is_production=True,
            allowed_origins_raw="http://haven.example",
            frontend_url=None,
        )
    with pytest.raises(RuntimeError):
        resolve_cors_origins(
            is_production=True,
            allowed_origins_raw="https://haven.example/path",
            frontend_url=None,
        )
    with pytest.raises(RuntimeError):
        resolve_cors_origins(
            is_production=True, allowed_origins_raw="*", frontend_url=None
        )


def test_catalog_unique_plans_match_standard_ops():
    assert catalog_consistency_errors() == []
    plans = set((p.collection, p.field, p.unique, p.sparse) for p in UNIQUE_INDEX_PLANS)
    assert plans == set(unique_ops_as_tuples())


def test_badge_number_is_required_on_write():
    badge = next(p for p in UNIQUE_INDEX_PLANS if p.field == "badge_number")
    assert badge.required_on_write is True
    assert badge.sparse is True


def test_single_empty_string_is_info_not_blocker():
    coll = FakeCollection([{"case_id": ""}, {"case_id": "A"}])
    chk = check_unique_field(coll, _plan("sos_cases", "case_id", sparse=True))
    assert chk.empty_string == 1
    assert chk.safe is True
    assert any("empty-string" in m for m in chk.messages)


def test_custom_and_srv_endpoints_require_confirm():
    assert index_setup_requires_confirm(
        "development", "mongodb://10.0.0.8:27017/Haven"
    ) is True
    srv = classify_mongo_target("mongodb+srv://u:p@internal.example.com/Haven")
    assert srv["kind"] == "cloud_srv"
    assert "p@" not in str(srv)
    assert "internal.example.com" not in srv["label"]
    assert index_setup_requires_confirm(
        "development", "mongodb+srv://u:p@internal.example.com/Haven"
    ) is True


def test_advisory_duplicates_do_not_block_planned_indexes():
    db = FakeDB()
    for plan in UNIQUE_INDEX_PLANS:
        db[plan.collection] = FakeCollection([{plan.field: f"id-{plan.collection}"}])
    db["authority_accounts"] = FakeCollection(
        [{"badge_number": "DUP", "authority_id": "a1"},
         {"badge_number": "DUP", "authority_id": "a2"}]
    )
    result = run_preflight(db, environment_label="test")
    assert result.ok
    text = format_preflight_report(result)
    assert "advisory" in text.lower()
    assert "DUP" not in text


def test_setup_indexes_import_does_not_connect():
    import ast
    import pathlib
    src = (pathlib.Path(__file__).parent / "setup_indexes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_guard = False
    for node in tree.body:
        if isinstance(node, ast.If):
            if ast.unparse(node.test) in ("__name__ == '__main__'", '__name__ == "__main__"'):
                has_guard = True
    assert has_guard
    import setup_indexes as setup_mod
    assert callable(setup_mod.main)


def _patch_setup_indexes(monkeypatch, db):
    import setup_indexes

    monkeypatch.setattr(setup_indexes, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(
        setup_indexes, "MongoClient", lambda *_args, **_kwargs: FakeMongoClient(db)
    )
    monkeypatch.setenv("MONGO_ENDPOINT", "mongodb://safe-test-user:safe-test-password@stage.example.net:27017/Haven")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("HAVEN_DATABASE_ENVIRONMENT", "staging")
    monkeypatch.setenv("HAVEN_STAGING_TARGET_ID", "haven-stage")
    monkeypatch.setenv("HAVEN_STAGING_MONGO_HOST_ALLOWLIST", "stage.example.net")
    monkeypatch.setenv("HAVEN_STAGING_DATABASE_ALLOWLIST", "Haven")
    monkeypatch.setenv("HAVEN_ALLOW_INDEX_SETUP", INDEX_SETUP_CONFIRM_VALUE)
    monkeypatch.delenv("HAVEN_SKIP_INDEX_PREFLIGHT", raising=False)
    return setup_indexes


def test_setup_indexes_main_is_idempotent_with_fake_database(monkeypatch):
    db = FakeDB()
    setup_mod = _patch_setup_indexes(monkeypatch, db)

    assert setup_mod.main() == 0
    first_inventory = {
        name: collection.index_information()
        for name, collection in db.items()
    }

    assert setup_mod.main() == 0
    second_inventory = {
        name: collection.index_information()
        for name, collection in db.items()
    }
    assert second_inventory == first_inventory


def test_setup_indexes_main_stops_before_any_creation_on_blocker(monkeypatch):
    db = FakeDB()
    db["sos_cases"] = FakeCollection([{"case_id": "duplicate"}, {"case_id": "duplicate"}])
    setup_mod = _patch_setup_indexes(monkeypatch, db)

    assert setup_mod.main() == 1
    assert all(not collection.create_calls for collection in db.values())
    assert db.command_calls == []


def test_setup_indexes_rejects_unknown_target_before_connecting(monkeypatch, capsys):
    import setup_indexes

    monkeypatch.setattr(setup_indexes, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv(
        "MONGO_ENDPOINT",
        "mongodb://safe-test-user:safe-test-password@unknown.example.net:27017/Haven",
    )
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("HAVEN_DATABASE_ENVIRONMENT", "staging")
    monkeypatch.setenv("HAVEN_STAGING_TARGET_ID", "haven-stage")
    monkeypatch.setenv("HAVEN_STAGING_MONGO_HOST_ALLOWLIST", "stage.example.net")
    monkeypatch.setenv("HAVEN_STAGING_DATABASE_ALLOWLIST", "Haven")
    monkeypatch.setenv("HAVEN_ALLOW_INDEX_SETUP", INDEX_SETUP_CONFIRM_VALUE)
    monkeypatch.setattr(
        setup_indexes,
        "MongoClient",
        lambda *_args, **_kwargs: pytest.fail("unknown target must not connect"),
    )

    assert setup_indexes.main() == 1
    output = capsys.readouterr().out
    assert "unknown.example.net" not in output
    assert "safe-test-password" not in output
