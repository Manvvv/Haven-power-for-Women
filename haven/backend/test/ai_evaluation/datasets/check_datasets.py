"""
check_datasets.py — quality checks for the HAVEN AI evaluation SEED datasets.

Pure standard library. Validates that every seed dataset conforms to its declared
schema BEFORE the eval harness trusts it, so a malformed row or a typo'd label
fails loudly here instead of silently skewing a metric.

It is a *data* linter, not a model test. It asserts, per dataset:
  * every line is valid JSON and carries all required fields (right types)
  * ids are unique and follow the file's prefix convention
  * the free-text field is non-empty
  * the label(s) are drawn from the allowed vocabulary
  * a human-readable `note` is present (every row must justify itself)
  * cross-field consistency (e.g. mental-health crisis flag matches risk level)
  * minimum class coverage for the safety-critical classes

Exit code 0 = all pass. Run:  python3 check_datasets.py   (cwd = this datasets/ dir
or backend/test/ai_evaluation).
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = _HERE if os.path.basename(_HERE) == "datasets" else os.path.join(_HERE, "datasets")

_FAILS = []
_PASSES = 0


def _ok(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
    else:
        _FAILS.append(label)


def _rows(name):
    out = []
    with open(os.path.join(_DATA, name), encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append((i, json.loads(line)))
            except json.JSONDecodeError as e:
                _FAILS.append(f"{name}:{i} invalid JSON ({e})")
    return out


# ── Dataset schema specifications ───────────────────────────────────────────────
# label_fields: {field: allowed set or type-check callable}
_SPECS = {
    "mental_health_crisis.jsonl": {
        "prefix": "mh", "text_field": "text",
        "fields": {
            "lang": {"en", "hi", "hinglish"},
            "crisis": bool,
            "risk_level": {"IMMINENT_DANGER", "HIGH_RISK", "MODERATE_DISTRESS",
                           "LOW_DISTRESS", "UNKNOWN"},
        },
        "min_coverage": {"risk_level": {"IMMINENT_DANGER", "HIGH_RISK",
                                        "MODERATE_DISTRESS", "LOW_DISTRESS"}},
    },
    "sos_risk.jsonl": {
        "prefix": "sos", "text_field": "text",
        "fields": {"severity": {"CRITICAL", "HIGH", "MODERATE", "LOW"}},
        "min_coverage": {"severity": {"CRITICAL", "HIGH", "MODERATE", "LOW"}},
    },
    "intent.jsonl": {
        "prefix": "in", "text_field": "transcript",
        "fields": {
            "recognition_confidence": float,
            "intent": {"EMERGENCY", "POSSIBLE_EMERGENCY", "UNKNOWN", "NON_EMERGENCY"},
        },
        "min_coverage": {"intent": {"EMERGENCY", "NON_EMERGENCY"}},
    },
    "legal_category.jsonl": {
        "prefix": "lg", "text_field": "question",
        "fields": {"category": {"child_safety", "women_rights", "cyber", "workplace",
                                "police", "family", "court_navigation", "legal_aid",
                                "general"}},
        "min_coverage": {"category": {"child_safety", "women_rights", "legal_aid"}},
    },
    "profile_query.jsonl": {
        "prefix": "pf", "text_field": "query",
        "fields": {"query_type": {"NAME_QUERY", "DESCRIPTION_QUERY", "MIXED_QUERY"}},
        "min_coverage": {"query_type": {"NAME_QUERY", "DESCRIPTION_QUERY", "MIXED_QUERY"}},
    },
}


def _check_field(name, ln, rid, field, spec, value):
    if isinstance(spec, set):
        _ok(value in spec, f"{name}:{ln} [{rid}] {field}={value!r} not in allowed vocab")
    elif spec is bool:
        _ok(isinstance(value, bool), f"{name}:{ln} [{rid}] {field} must be bool, got {type(value).__name__}")
    elif spec is float:
        _ok(isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0.0 <= float(value) <= 1.0,
            f"{name}:{ln} [{rid}] {field} must be a 0..1 number, got {value!r}")


def check_dataset(name, spec):
    rows = _rows(name)
    _ok(len(rows) > 0, f"{name}: dataset is empty")
    seen_ids = set()
    coverage = {f: set() for f in spec.get("min_coverage", {})}
    tf = spec["text_field"]
    for ln, r in rows:
        rid = r.get("id", "?")
        _ok("id" in r and isinstance(rid, str) and rid.startswith(spec["prefix"]),
            f"{name}:{ln} id {rid!r} missing / wrong prefix (want '{spec['prefix']}*')")
        _ok(rid not in seen_ids, f"{name}:{ln} duplicate id {rid!r}")
        seen_ids.add(rid)
        _ok(isinstance(r.get(tf), str) and r.get(tf, "").strip() != "",
            f"{name}:{ln} [{rid}] text field {tf!r} empty/missing")
        _ok(isinstance(r.get("note"), str) and r.get("note", "").strip() != "",
            f"{name}:{ln} [{rid}] missing 'note' (every row must justify itself)")
        for field, fspec in spec["fields"].items():
            if field not in r:
                _ok(False, f"{name}:{ln} [{rid}] missing required field {field!r}")
                continue
            _check_field(name, ln, rid, field, fspec, r[field])
            if field in coverage:
                coverage[field].add(r[field])
    # cross-field consistency: mental-health crisis flag must match risk level
    if name == "mental_health_crisis.jsonl":
        for ln, r in rows:
            if "crisis" in r and "risk_level" in r:
                expect = r["risk_level"] in ("IMMINENT_DANGER", "HIGH_RISK")
                _ok(r["crisis"] == expect,
                    f"{name}:{ln} [{r.get('id')}] crisis={r['crisis']} inconsistent with risk_level={r['risk_level']}")
    # minimum class coverage
    for field, need in spec.get("min_coverage", {}).items():
        missing = need - coverage.get(field, set())
        _ok(not missing, f"{name}: {field} missing required class coverage: {sorted(missing)}")
    return len(rows)


def main():
    print("Checking HAVEN AI evaluation SEED datasets...\n")
    total = 0
    for name, spec in _SPECS.items():
        n = check_dataset(name, spec)
        total += n
        print(f"  {name:<30} {n:>3} rows")
    print()
    if _FAILS:
        print(f"{_PASSES} checks passed, {len(_FAILS)} FAILED\n")
        for f in _FAILS:
            print("  FAIL:", f)
        return 1
    print(f"PASSED {_PASSES} checks across {total} rows")
    print("ALL DATASET QUALITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
