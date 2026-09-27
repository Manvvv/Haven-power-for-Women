"""
HAVEN AI/ML service layer (Parts 6-8).

A small, swappable risk-classification stack. The public entrypoint is
`services.ml.risk_engine.get_engine()` which returns a singleton engine that
picks the best available backend at import time:

    1. DistilBERT  (transformers + torch + a fine-tuned model on disk)
    2. sklearn TF-IDF + LogisticRegression baseline (a trained .joblib on disk)
    3. Rule-based lexicon scorer (pure standard library — always available)

Every backend returns the SAME result shape, so the API and frontend never
change when the model is swapped. See services/ml/README section in the
project README for IMPLEMENTED / DEMO / FUTURE status.
"""
