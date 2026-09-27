#!/usr/bin/env python3
"""
Compare the risk-classification backends side by side on the labeled demo set.

Runs every AVAILABLE backend (rule-based → TF-IDF+LogReg → DistilBERT) over the
same examples and prints per-backend precision / recall / F1 / macro-F1 /
accuracy / within-1-band, plus a confusion matrix each. Backends that are not
installed are clearly skipped, never faked.

Honesty:
  * All numbers are computed live from THIS run — nothing is hard-coded.
  * The bundled dataset is SYNTHETIC (services/ml/data/sos_risk_demo.jsonl), so
    every backend here is DEMO. Do not cite these as production metrics.

Usage:
    python ml/compare_backends.py                 # full demo set
    python ml/compare_backends.py --test-split 0.25   # held-out split (seeded)
    python ml/compare_backends.py --backends rules,sklearn
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.ml.preprocessing import SEVERITY_LEVELS, SEVERITY_ORDER  # noqa: E402

DATA_PATH = BACKEND_DIR / "services" / "ml" / "data" / "sos_risk_demo.jsonl"
ALL_BACKENDS = ["rules", "sklearn", "transformer"]


def load_dataset(path: Path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _metrics(y_true, y_pred, labels):
    """Per-class precision/recall/F1 + macro-F1 + confusion matrix (stdlib)."""
    idx = {l: i for i, l in enumerate(labels)}
    n = len(labels)
    cm = [[0] * n for _ in range(n)]
    for t, p in zip(y_true, y_pred):
        cm[idx[t]][idx[p]] += 1
    per_class, macro_f1 = {}, 0.0
    for i, l in enumerate(labels):
        tp = cm[i][i]
        fp = sum(cm[r][i] for r in range(n)) - tp
        fn = sum(cm[i][c] for c in range(n)) - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[l] = {"precision": prec, "recall": rec, "f1": f1, "support": sum(cm[i])}
        macro_f1 += f1
    return cm, per_class, macro_f1 / n


def _build_engine(backend: str):
    """Construct a fresh RiskEngine forced to `backend`.

    Returns (engine, available). `available` is False when the backend could not
    load (e.g. sklearn/torch not installed) and it silently fell back to rules.
    """
    os.environ["HAVEN_RISK_BACKEND"] = backend
    # Import inside so env is read on construction; bypass the cached singleton.
    from services.ml.risk_engine import RiskEngine
    eng = RiskEngine()
    return eng, (eng.backend == backend)


def evaluate_backend(backend: str, rows):
    eng, available = _build_engine(backend)
    if not available:
        return {"backend": backend, "available": False, "actual": eng.backend}
    y_true, y_pred, within1 = [], [], 0
    for row in rows:
        gold = row["severity"].upper()
        pred = eng.predict(row["text"])["severity"].upper()
        y_true.append(gold)
        y_pred.append(pred)
        if abs(SEVERITY_ORDER[gold] - SEVERITY_ORDER[pred]) <= 1:
            within1 += 1
    n = len(rows)
    cm, per_class, macro_f1 = _metrics(y_true, y_pred, SEVERITY_LEVELS)
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0
    return {"backend": backend, "available": True, "n": n, "accuracy": acc,
            "within1": within1 / n if n else 0.0, "macro_f1": macro_f1,
            "per_class": per_class, "cm": cm, "is_demo": eng.info()["is_demo_mode"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--backends", default=",".join(ALL_BACKENDS))
    ap.add_argument("--test-split", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = load_dataset(Path(args.data))
    if args.test_split > 0:
        rng = random.Random(args.seed)
        rng.shuffle(rows)
        rows = rows[int(len(rows) * (1 - args.test_split)):]

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    results = [evaluate_backend(b, rows) for b in backends]

    print("=" * 72)
    print("HAVEN Risk Classifier — Backend Comparison")
    print("=" * 72)
    print(f"Dataset : {args.data}")
    print(f"Examples: {len(rows)}"
          + (f"  (held-out {args.test_split:.0%}, seed={args.seed})" if args.test_split > 0 else "  (full set)"))
    print("All backends here are DEMO (synthetic data) — not production metrics.")
    print("-" * 72)

    # Summary comparison table.
    print(f"{'backend':<14}{'available':<11}{'accuracy':>10}{'within1':>10}{'macro-F1':>10}")
    for r in results:
        if not r["available"]:
            print(f"{r['backend']:<14}{'NO':<11}{'—':>10}{'—':>10}{'—':>10}"
                  f"   (not installed; fell back to '{r['actual']}')")
        else:
            print(f"{r['backend']:<14}{'YES':<11}{r['accuracy']:>10.3f}{r['within1']:>10.3f}{r['macro_f1']:>10.3f}")
    print("-" * 72)

    # Per-backend detail.
    for r in results:
        if not r["available"]:
            continue
        print(f"\n### {r['backend']}  (is_demo_mode={r['is_demo']})")
        print(f"{'class':<10}{'precision':>10}{'recall':>10}{'f1':>10}{'support':>10}")
        for l in SEVERITY_LEVELS:
            pc = r["per_class"][l]
            print(f"{l:<10}{pc['precision']:>10.3f}{pc['recall']:>10.3f}{pc['f1']:>10.3f}{pc['support']:>10d}")
        print("confusion (rows=gold, cols=pred): " + "  ".join(x[:4] for x in SEVERITY_LEVELS))
        for i, l in enumerate(SEVERITY_LEVELS):
            print(f"  {l:<10}" + "".join(f"{v:>6d}" for v in r["cm"][i]))

    print("\n" + "=" * 72)
    installed = [r["backend"] for r in results if r["available"]]
    missing = [r["backend"] for r in results if not r["available"]]
    print(f"Evaluated: {installed or 'none'}")
    if missing:
        print(f"Skipped (not installed): {missing}  — run `pip install -r requirements-ml.txt` "
              f"and train (ml/train_baseline.py / ml/train_distilbert.py) to enable them.")
    print("Numbers computed live this run. No metric is hard-coded or fabricated.")


if __name__ == "__main__":
    main()
