"""
run_eval.py — HAVEN AI evaluation harness (pure standard library).

Runs each DETERMINISTIC AI layer against a labelled seed dataset and reports REAL
measured metrics (precision / recall / F1 / FPR / FNR + confusion matrices). No
numbers are hard-coded; everything is computed from the actual output of the
shipped code via metrics.py.

HONESTY (per project constraints):
  * The datasets under ./datasets are SMALL, HAND-AUTHORED SYNTHETIC SEED sets —
    NOT real user data and NOT a real-world accuracy benchmark. Numbers here
    describe behaviour on this seed set only. They are a regression tripwire and a
    way to quantify known trade-offs (e.g. the fuzzy-match false-positive on
    benign "pills" mentions), not a claim of production accuracy.
  * Only layers that run WITHOUT torch/sklearn/network are scored here (the
    learned tiers are not installable in the build sandbox). The SOS risk engine
    is scored on its default deterministic 'rules' backend.

Usage:
    python3 run_eval.py            # human-readable report, writes results.json
    python3 run_eval.py --strict   # also exit non-zero if a SAFETY FLOOR regresses

Safety floors (regression tripwires on THIS seed set — chosen to match current
measured behaviour, so they guard against future downgrades, not aspirations):
    * mental-health crisis recall            >= 0.90   (missed-crisis guard)
    * SOS severe (HIGH/CRITICAL) recall      >= 0.90   (under-escalation guard)
    * intent escalation recall on emergencies>= 0.90   (voice-SOS miss guard)
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import metrics as M  # local, pure-stdlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_HERE, "datasets")

CRISIS_RECALL_FLOOR = 0.90
SOS_SEVERE_RECALL_FLOOR = 0.90
INTENT_EMERGENCY_RECALL_FLOOR = 0.90


def _load(name):
    rows = []
    with open(os.path.join(_DATA, name), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _hr(title):
    return "\n" + "=" * 72 + f"\n{title}\n" + "=" * 72


def _mismatches(rows, y_true, y_pred, key):
    out = []
    for r, t, p in zip(rows, y_true, y_pred):
        if t != p:
            out.append({"id": r.get("id"), key: r.get(key), "true": t, "pred": p,
                        "note": r.get("note", "")})
    return out


# ── Mental-health crisis triage ─────────────────────────────────────────────
def eval_mental_health():
    from services import mental_health_triage as MH
    rows = _load("mental_health_crisis.jsonl")
    yb_true, yb_pred, yl_true, yl_pred = [], [], [], []
    for r in rows:
        t = MH.build_triage(r["text"], r.get("lang"))
        yb_true.append("CRISIS" if r["crisis"] else "NON_CRISIS")
        yb_pred.append("CRISIS" if t.crisis else "NON_CRISIS")
        yl_true.append(r["risk_level"])
        yl_pred.append(t.risk_level)
    binr = M.binary_report(yb_true, yb_pred, "CRISIS")
    cm, lab = M.confusion_matrix(yb_true, yb_pred, ["CRISIS", "NON_CRISIS"])
    levels = ["IMMINENT_DANGER", "HIGH_RISK", "MODERATE_DISTRESS", "LOW_DISTRESS", "UNKNOWN"]
    lvl = M.per_class_report(yl_true, yl_pred, levels)
    fps = _mismatches(rows, yb_true, yb_pred, "text")
    print(_hr("1. MENTAL-HEALTH CRISIS TRIAGE  (binary: CRISIS vs NON_CRISIS)"))
    print(M.format_confusion(cm, lab))
    print(f"\n  recall (crisis caught)   = {M._pct(binr['recall'])}   "
          f"[FNR missed-crisis = {M._pct(binr['fnr'])}]")
    print(f"  precision (of alarms)    = {M._pct(binr['precision'])}   "
          f"[FPR false-alarm  = {M._pct(binr['fpr'])}]")
    print(f"  F1 = {M._pct(binr['f1'])}   accuracy = {M._pct(binr['accuracy'])}   "
          f"(tp={binr['tp']} fp={binr['fp']} tn={binr['tn']} fn={binr['fn']})")
    print("\n  " + M.format_multiclass(lvl, "risk-level (secondary, softer boundaries):").replace("\n", "\n  "))
    if fps:
        print("\n  binary crisis disagreements (honest error inventory):")
        for m in fps:
            print(f"    [{m['id']}] true={m['true']} pred={m['pred']}  \"{m['text']}\"  ({m['note']})")
    return {"subsystem": "mental_health_crisis", "n": binr["n"], "binary": binr,
            "risk_level_macro_f1": lvl["macro"]["f1"], "risk_level_accuracy": lvl["accuracy"],
            "disagreements": fps, "floor": {"crisis_recall": binr["recall"],
            "floor_value": CRISIS_RECALL_FLOOR, "pass": binr["recall"] >= CRISIS_RECALL_FLOOR}}


# ── SOS free-text risk (deterministic 'rules' backend) ──────────────────────
def eval_sos_risk():
    from services.ml import risk_engine as RE
    eng = RE.get_engine()
    rows = _load("sos_risk.jsonl")
    order = RE.SEVERITY_ORDER
    labels = ["CRITICAL", "HIGH", "MODERATE", "LOW"]
    y_true, y_pred = [], []
    under = 0                       # predicted STRICTLY below truth (unsafe direction)
    severe_true = severe_hit = 0    # truth in {HIGH,CRITICAL} -> pred in {HIGH,CRITICAL}
    for r in rows:
        out = eng.predict(r["text"])
        t, p = r["severity"], out.get("severity", "LOW")
        y_true.append(t); y_pred.append(p)
        if order.get(p, 0) < order.get(t, 0):
            under += 1
        if order.get(t, 0) >= order["HIGH"]:
            severe_true += 1
            if order.get(p, 0) >= order["HIGH"]:
                severe_hit += 1
    rep = M.per_class_report(y_true, y_pred, labels)
    cm, lab = M.confusion_matrix(y_true, y_pred, labels)
    severe_recall = (severe_hit / severe_true) if severe_true else 0.0
    mism = _mismatches(rows, y_true, y_pred, "text")
    print(_hr("2. SOS FREE-TEXT RISK  (backend='rules', 4-band severity)"))
    print(M.format_confusion(cm, lab))
    print("\n  " + M.format_multiclass(rep).replace("\n", "\n  "))
    print(f"\n  SAFETY: severe (HIGH/CRITICAL) recall = {M._pct(severe_recall)} "
          f"({severe_hit}/{severe_true})   under-escalations (pred<true) = {under}/{len(rows)}")
    if mism:
        print("\n  band disagreements:")
        for m in mism:
            direction = "UNDER" if order.get(m["pred"], 0) < order.get(m["true"], 0) else "over"
            print(f"    [{m['id']}] true={m['true']} pred={m['pred']} ({direction})  \"{m['text']}\"")
    return {"subsystem": "sos_risk", "n": len(rows), "accuracy": rep["accuracy"],
            "macro_f1": rep["macro"]["f1"], "under_escalations": under,
            "severe_recall": severe_recall, "disagreements": mism,
            "floor": {"severe_recall": severe_recall, "floor_value": SOS_SEVERE_RECALL_FLOOR,
                      "pass": severe_recall >= SOS_SEVERE_RECALL_FLOOR}}


# ── Voice-SOS emergency intent ──────────────────────────────────────────────
def eval_intent():
    from services import intent_service as IS
    rows = _load("intent.jsonl")
    labels = ["EMERGENCY", "POSSIBLE_EMERGENCY", "UNKNOWN", "NON_EMERGENCY"]
    y_true, y_pred = [], []
    esc_true = esc_hit = 0   # true EMERGENCY -> pred escalates (EMERGENCY or POSSIBLE)
    for r in rows:
        out = IS.detect_intent(r["transcript"], r.get("recognition_confidence"))
        t, p = r["intent"], out.get("intent", "UNKNOWN")
        y_true.append(t); y_pred.append(p)
        if t == "EMERGENCY":
            esc_true += 1
            if p in ("EMERGENCY", "POSSIBLE_EMERGENCY"):
                esc_hit += 1
    rep = M.per_class_report(y_true, y_pred, labels)
    cm, lab = M.confusion_matrix(y_true, y_pred, labels)
    esc_recall = (esc_hit / esc_true) if esc_true else 0.0
    mism = _mismatches(rows, y_true, y_pred, "transcript")
    print(_hr("3. VOICE-SOS EMERGENCY INTENT  (4 levels, recognition-confidence aware)"))
    print(M.format_confusion(cm, lab))
    print("\n  " + M.format_multiclass(rep).replace("\n", "\n  "))
    print(f"\n  SAFETY: escalation recall on true EMERGENCY = {M._pct(esc_recall)} "
          f"({esc_hit}/{esc_true})  [escalates to EMERGENCY or POSSIBLE_EMERGENCY]")
    if mism:
        print("\n  intent disagreements:")
        for m in mism:
            print(f"    [{m['id']}] true={m['true']} pred={m['pred']}  \"{m['transcript']}\"  ({m['note']})")
    return {"subsystem": "intent", "n": len(rows), "accuracy": rep["accuracy"],
            "macro_f1": rep["macro"]["f1"], "emergency_escalation_recall": esc_recall,
            "disagreements": mism,
            "floor": {"emergency_escalation_recall": esc_recall,
                      "floor_value": INTENT_EMERGENCY_RECALL_FLOOR,
                      "pass": esc_recall >= INTENT_EMERGENCY_RECALL_FLOOR}}


# ── Legal category triage ───────────────────────────────────────────────────
def eval_legal():
    from services import legal_triage as LT
    rows = _load("legal_category.jsonl")
    labels = ["child_safety", "women_rights", "cyber", "workplace", "police",
              "family", "court_navigation", "legal_aid", "general"]
    y_true = [r["category"] for r in rows]
    y_pred = [LT.classify_category(r["question"]) for r in rows]
    rep = M.per_class_report(y_true, y_pred, labels)
    cm, lab = M.confusion_matrix(y_true, y_pred, labels)
    mism = _mismatches(rows, y_true, y_pred, "question")
    print(_hr("4. LEGAL CATEGORY TRIAGE  (deterministic keyword classifier)"))
    print(M.format_confusion(cm, lab))
    print("\n  " + M.format_multiclass(rep).replace("\n", "\n  "))
    if mism:
        print("\n  category disagreements (keyword-coverage gaps / boundary cases):")
        for m in mism:
            print(f"    [{m['id']}] true={m['true']} pred={m['pred']}  \"{m['question']}\"  ({m['note']})")
    return {"subsystem": "legal_category", "n": len(rows), "accuracy": rep["accuracy"],
            "macro_f1": rep["macro"]["f1"], "disagreements": mism}


# ── Profile query routing ───────────────────────────────────────────────────
def eval_profile():
    from services import profile_search as PS
    rows = _load("profile_query.jsonl")
    labels = ["NAME_QUERY", "DESCRIPTION_QUERY", "MIXED_QUERY"]
    y_true = [r["query_type"] for r in rows]
    y_pred = [PS.classify_query(r["query"]) for r in rows]
    rep = M.per_class_report(y_true, y_pred, labels)
    cm, lab = M.confusion_matrix(y_true, y_pred, labels)
    mism = _mismatches(rows, y_true, y_pred, "query")
    print(_hr("5. PROFILE QUERY ROUTING  (name / description / mixed)"))
    print(M.format_confusion(cm, lab))
    print("\n  " + M.format_multiclass(rep).replace("\n", "\n  "))
    if mism:
        print("\n  routing disagreements:")
        for m in mism:
            print(f"    [{m['id']}] true={m['true']} pred={m['pred']}  \"{m['query']}\"")
    return {"subsystem": "profile_query", "n": len(rows), "accuracy": rep["accuracy"],
            "macro_f1": rep["macro"]["f1"], "disagreements": mism}


def main():
    strict = "--strict" in sys.argv
    print("HAVEN AI EVALUATION HARNESS  —  measured on synthetic seed datasets")
    print("(NOT a real-world accuracy benchmark; see README.md for provenance/limits)")
    results = [eval_mental_health(), eval_sos_risk(), eval_intent(),
               eval_legal(), eval_profile()]

    print(_hr("SUMMARY (measured on seed sets)"))
    hdr = f"{'subsystem':>22} {'n':>4} {'accuracy':>10} {'macro-F1':>10} {'safety metric':>26}"
    print(hdr)
    safety_map = {"mental_health_crisis": ("crisis recall", "binary", "recall"),
                  "sos_risk": ("severe recall", None, "severe_recall"),
                  "intent": ("emergency-esc recall", None, "emergency_escalation_recall")}
    for r in results:
        acc = r.get("accuracy", r.get("binary", {}).get("accuracy", 0.0))
        mf1 = r.get("macro_f1", r.get("risk_level_macro_f1", 0.0))
        smeta = safety_map.get(r["subsystem"])
        if smeta:
            label, sub, key = smeta
            val = r["binary"][key] if sub == "binary" else r[key]
            sm = f"{label}={M._pct(val)}"
        else:
            sm = "-"
        print(f"{r['subsystem']:>22} {r['n']:>4} {M._pct(acc):>10} {M._pct(mf1):>10} {sm:>26}")

    floors = [r["floor"] for r in results if "floor" in r]
    breached = [f for f in floors if not f["pass"]]
    print(_hr("SAFETY FLOORS (regression tripwires on seed set)"))
    for r in results:
        f = r.get("floor")
        if f:
            metric = [k for k in f if k not in ("floor_value", "pass")][0]
            status = "PASS" if f["pass"] else "*** FAIL ***"
            print(f"  {status:>12}  {r['subsystem']:>22}  {metric} = {M._pct(f[metric])} "
                  f"(floor {M._pct(f['floor_value'])})")

    out_path = os.path.join(_HERE, "results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"note": "Measured on synthetic seed datasets — not a real-world benchmark.",
                   "results": results}, fh, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}")

    if strict and breached:
        print(f"\nSTRICT MODE: {len(breached)} safety floor(s) breached — exiting non-zero.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





