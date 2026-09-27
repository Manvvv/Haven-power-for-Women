#!/usr/bin/env python3
"""
Train the scikit-learn baseline risk classifier (TF-IDF + LogisticRegression).

Produces services/ml/artifacts/sklearn_risk.joblib, which the RiskEngine loads
automatically (as the 'sklearn' tier) on next start. This is a REAL trained
model, but it is trained on the SYNTHETIC demo dataset, so the engine keeps
is_demo_mode = True. Do not present its metrics as production performance.

Requires: scikit-learn, joblib  (see requirements-ml.txt)

Usage:
    pip install -r requirements-ml.txt
    python ml/train_baseline.py                 # train + save, print held-out metrics
    python ml/train_baseline.py --test-split 0  # train on everything (no eval split)
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.ml.preprocessing import clean_text, SEVERITY_LEVELS  # noqa: E402

DATA_PATH = BACKEND_DIR / "services" / "ml" / "data" / "sos_risk_demo.jsonl"
ARTIFACT_DIR = BACKEND_DIR / "services" / "ml" / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "sklearn_risk.joblib"


def load_dataset(path: Path):
    texts, labels = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            texts.append(clean_text(row["text"]))
            labels.append(row["severity"].upper())
    return texts, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--test-split", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    try:
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, confusion_matrix
    except ImportError:
        print("ERROR: scikit-learn / joblib not installed.\n"
              "Run:  pip install -r requirements-ml.txt")
        sys.exit(1)

    texts, labels = load_dataset(Path(args.data))
    print(f"Loaded {len(texts)} labeled examples from {args.data}")

    if args.test_split > 0:
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=args.test_split,
            random_state=args.seed, stratify=labels,
        )
    else:
        X_train, y_train = texts, labels
        X_test, y_test = [], []

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), min_df=1, sublinear_tf=True, strip_accents="unicode",
    )
    Xtr = vectorizer.fit_transform(X_train)
    model = LogisticRegression(max_iter=1000, class_weight="balanced", C=4.0)
    model.fit(Xtr, y_train)

    if X_test:
        y_hat = model.predict(vectorizer.transform(X_test))
        print("\nHeld-out evaluation (synthetic demo data — NOT production):")
        print(classification_report(y_test, y_hat, labels=SEVERITY_LEVELS, zero_division=0, digits=3))
        print("Confusion matrix (rows=gold, cols=pred):", SEVERITY_LEVELS)
        print(confusion_matrix(y_test, y_hat, labels=SEVERITY_LEVELS))

    # Refit on ALL data for the shipped artifact (more signal for the demo).
    Xall = vectorizer.fit_transform(texts)
    model.fit(Xall, labels)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"vectorizer": vectorizer, "model": model, "labels": SEVERITY_LEVELS,
         "trained_on": "sos_risk_demo.jsonl (synthetic)", "is_demo_mode": True},
        ARTIFACT_PATH,
    )
    print(f"\nSaved baseline model -> {ARTIFACT_PATH}")
    print("RiskEngine will use the 'sklearn' backend automatically on next start.")


if __name__ == "__main__":
    main()
