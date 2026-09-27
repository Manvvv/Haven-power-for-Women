#!/usr/bin/env python3
"""
Evaluate the ACTIVE risk-classification backend on the labeled demo dataset.

Honest by construction: it runs the real engine (whatever backend is installed
— rules / sklearn / DistilBERT) over held-out examples and reports the metrics
that actually come out. Nothing is hard-coded or fabricated. If a backend is
not installed, its numbers simply are not produced.

Usage:
    python ml/evaluate.py                          # evaluate active backend, full dataset
    HAVEN_RISK_BACKEND=rules python ml/evaluate.py # force a specific backend
    python ml/evaluate.py --test-split 0.25        # evaluate only a held-out split

Metrics: per-class precision/recall/F1, macro-F1, accuracy, within-1-band
accuracy (a MODERATE predicted as HIGH is a near-miss, useful for triage), and a
confusion matrix. Uses scikit-learn's metrics when available, otherwise a
pure-stdlib fallback so it still runs on a minimal install.
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

# Make `services` importable whether run from backend/ or backend/ml/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.ml.risk_engine import get_engine  # noqa: E402
from services.ml.preprocessing import SEVERITY_LEVELS, SEVERITY_ORDER  # noqa: E402

DATA_PATH = BACKEND_DIR / "services" / "ml" / "data" / "sos_risk_demo.jsonl"


def load_dataset(path: Path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _stdlib_report(y_true, y_pred, labels):
    """Precision/recall/F1 per class without sklearn."""
    idx = {l: i for i, l in enumerate(labels)}
    n = len(labels)
    cm = [[0] * n for _ in range(n)]
    for t, p in zip(y_true, y_pred):
        cm[idx[t]][idx[p]] += 1

    rows = {}
    macro_f1 = 0.0
    for i, l in enumerate(labels):
        tp = cm[i][i]
        fp = sum(cm[r][i] for r in range(n)) - tp
        fn = sum(cm[i][c] for c in range(n)) - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        support = sum(cm[i])
        rows[l] = (prec, rec, f1, support)
        macro_f1 += f1
    macro_f1 /= n
    return cm, rows, macro_f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--test-split", type=float, default=0.0,
                    help="If >0, evaluate only this held-out fraction (seeded).")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = load_dataset(Path(args.data))
    if args.test_split > 0:
        rng = random.Random(args.seed)
        rng.shuffle(rows)
        cut = int(len(rows) * (1 - args.test_split))
        rows = rows[cut:]

    engine = get_engine()
    labels = SEVERITY_LEVELS
    y_true, y_pred = [], []
    within1 = 0
    for row in rows:
        gold = row["severity"].upper()
        pred = engine.predict(row["text"])["severity"].upper()
        y_true.append(gold)
        y_pred.append(pred)
        if abs(SEVERITY_ORDER[gold] - SEVERITY_ORDER[pred]) <= 1:
            within1 += 1

    n = len(rows)
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0

    print("=" * 62)
    print("HAVEN Risk Classifier — Evaluation")
    print("=" * 62)
    print(f"Active backend : {engine.backend}")
    print(f"is_demo_mode   : {engine.info()['is_demo_mode']}")
    print(f"Dataset        : {args.data}")
    print(f"Examples       : {n}"
          + (f"  (held-out {args.test_split:.0%} split, seed={args.seed})" if args.test_split > 0 else "  (full set)"))
    print("-" * 62)

    try:
        from sklearn.metrics import classification_report, confusion_matrix
        print(classification_report(y_true, y_pred, labels=labels, zero_division=0, digits=3))
        cm = confusion_matrix(y_true, y_pred, labels=labels)
        cm_rows = None
    except Exception:
        cm, cm_rows, macro_f1 = _stdlib_report(y_true, y_pred, labels)
        print("(scikit-learn not installed — using stdlib metrics)\n")
        print(f"{'class':<10}{'precision':>10}{'recall':>10}{'f1':>10}{'support':>10}")
        for l in labels:
            prec, rec, f1, sup = cm_rows[l]
            print(f"{l:<10}{prec:>10.3f}{rec:>10.3f}{f1:>10.3f}{sup:>10d}")
        print(f"\nmacro-F1: {macro_f1:.3f}")

    print("-" * 62)
    print(f"Accuracy (exact)        : {acc:.3f}")
    print(f"Accuracy (within 1 band): {within1 / n:.3f}" if n else "n/a")
    print("-" * 62)
    print("Confusion matrix (rows = gold, cols = predicted):")
    header = " " * 12 + "".join(f"{l[:4]:>7}" for l in labels)
    print(header)
    for i, l in enumerate(labels):
        rowvals = cm[i] if isinstance(cm, list) else cm[i].tolist()
        print(f"{l:<12}" + "".join(f"{v:>7d}" for v in rowvals))
    print("=" * 62)
    print("NOTE: numbers above are computed live from this run. The rule and "
          "sklearn tiers are DEMO (synthetic data); do not cite as production "
          "performance. See README > AI Risk Classifier.")


if __name__ == "__main__":
    main()
