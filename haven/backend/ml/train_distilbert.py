#!/usr/bin/env python3
"""
Fine-tune DistilBERT for SOS risk severity classification.

Produces a HuggingFace model directory the RiskEngine loads as the top-priority
'transformer' backend. Point the engine at it with:

    export HAVEN_RISK_MODEL_DIR=/path/to/haven-distilbert-risk
    # (optional, only if trained on representative production data:)
    export HAVEN_RISK_PRODUCTION=1

IMPORTANT HONESTY NOTE
----------------------
The bundled dataset (services/ml/data/sos_risk_demo.jsonl) is a small SYNTHETIC
demo set (~80 rows). Fine-tuning DistilBERT on it will overfit and is meant to
demonstrate the *pipeline*, not to produce a deployable model. Leave
HAVEN_RISK_PRODUCTION unset so the engine keeps reporting is_demo_mode = True.
To ship a real model, retrain on a large, representative, ethically-sourced and
labelled dataset and validate on a held-out set from the same distribution.

Requires: torch, transformers, datasets, scikit-learn, accelerate
    pip install -r requirements-ml.txt

Usage:
    python ml/train_distilbert.py --epochs 4 --out ./haven-distilbert-risk
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.ml.preprocessing import clean_text, SEVERITY_LEVELS  # noqa: E402

DATA_PATH = BACKEND_DIR / "services" / "ml" / "data" / "sos_risk_demo.jsonl"
LABEL2ID = {l: i for i, l in enumerate(SEVERITY_LEVELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}


def load_dataset(path: Path):
    texts, labels = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            texts.append(clean_text(row["text"]))
            labels.append(LABEL2ID[row["severity"].upper()])
    return texts, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-model", default="distilbert-base-uncased")
    ap.add_argument("--out", default=str(BACKEND_DIR / "ml" / "haven-distilbert-risk"))
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--test-split", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    try:
        import numpy as np
        import torch  # noqa: F401
        from datasets import Dataset
        from transformers import (
            AutoTokenizer, AutoModelForSequenceClassification,
            TrainingArguments, Trainer, DataCollatorWithPadding,
        )
        from sklearn.metrics import f1_score, accuracy_score
        from sklearn.model_selection import train_test_split
    except ImportError as e:
        print(f"ERROR: ML dependencies missing ({e}).\n"
              "Run:  pip install -r requirements-ml.txt")
        sys.exit(1)

    print("WARNING: training on a small SYNTHETIC demo set — this demonstrates the "
          "pipeline only and will overfit. Keep HAVEN_RISK_PRODUCTION unset.\n")

    texts, labels = load_dataset(DATA_PATH)
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=args.test_split, random_state=args.seed, stratify=labels,
    )

    tok = AutoTokenizer.from_pretrained(args.base_model)

    def to_ds(texts_, labels_):
        ds = Dataset.from_dict({"text": texts_, "label": labels_})
        return ds.map(lambda b: tok(b["text"], truncation=True, max_length=128), batched=True)

    train_ds, test_ds = to_ds(X_train, y_train), to_ds(X_test, y_test)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model, num_labels=len(SEVERITY_LEVELS),
        id2label=ID2LABEL, label2id=LABEL2ID,
    )

    def metrics(eval_pred):
        logits, gold = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {"accuracy": accuracy_score(gold, preds),
                "macro_f1": f1_score(gold, preds, average="macro", zero_division=0)}

    targs = TrainingArguments(
        output_dir=args.out + "-checkpoints",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=10,
        seed=args.seed,
        report_to=[],
    )
    trainer = Trainer(
        model=model, args=targs, train_dataset=train_ds, eval_dataset=test_ds,
        tokenizer=tok, data_collator=DataCollatorWithPadding(tok), compute_metrics=metrics,
    )
    trainer.train()
    print("\nHeld-out metrics (SYNTHETIC demo data — not production):", trainer.evaluate())

    Path(args.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"\nSaved fine-tuned model -> {args.out}")
    print(f"Enable it with:  export HAVEN_RISK_MODEL_DIR={args.out}")


if __name__ == "__main__":
    main()
