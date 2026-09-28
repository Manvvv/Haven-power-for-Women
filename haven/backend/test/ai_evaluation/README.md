# HAVEN AI Evaluation Harness

Measured, reproducible evaluation of HAVEN's **deterministic** AI layers against
small, hand-authored labelled seed datasets. Every number this harness prints is
**computed at run time from the actual output of the shipped code** — nothing is
hard-coded.

> **Honesty first.** The datasets here are SMALL, HAND-AUTHORED, SYNTHETIC SEED
> sets. They are **NOT** real user data and **NOT** a real-world accuracy
> benchmark. The metrics describe behaviour *on this seed set only*. Treat them
> as (a) a **regression tripwire** that fails loudly if safety behaviour
> degrades, and (b) a way to **quantify known trade-offs** (e.g. the fuzzy-match
> false-positive on the benign "vitamin pills" probe). They are not a claim of
> production accuracy, and no accuracy figure from here should be quoted as one.

---

## What is measured (and what is not)

Only layers that run **without** `torch` / `sklearn` / network access are scored,
because the learned tiers are not installable in the build sandbox. The SOS risk
engine is scored on its **default deterministic `rules` backend**. Concretely:

| # | Subsystem            | Code under test                         | Task                                   |
|---|----------------------|-----------------------------------------|----------------------------------------|
| 1 | Mental-health triage | `services.mental_health_triage`         | binary CRISIS vs NON_CRISIS (+ level)  |
| 2 | SOS free-text risk   | `services.ml.risk_engine` (`rules`)     | 4-band severity CRITICAL/HIGH/MOD/LOW  |
| 3 | Voice-SOS intent     | `services.intent_service`               | 4-level emergency intent               |
| 4 | Legal category       | `services.legal_triage`                 | 9-way category routing                 |
| 5 | Profile query        | `services.profile_search`               | name / description / mixed routing     |

The learned/embedding tiers, the LLM-backed generation paths, and anything that
requires network or heavy ML deps are **out of scope** for this harness by design
— they cannot be measured deterministically here, so they are not measured here.

---

## How to run

```bash
# from haven/backend/test/ai_evaluation
python3 run_eval.py            # human-readable report; writes results.json
python3 run_eval.py --strict   # additionally exit non-zero if a SAFETY FLOOR regresses
```

Pure standard library — no third-party install required. `--strict` is intended
for CI: it fails the build if any safety floor drops below its threshold.

---

## Safety floors (regression tripwires)

For a women's-safety platform the dangerous failure is **under-escalation** — a
real emergency scored as calm. So the floors guard **recall on the severe
classes**, not overall accuracy. They are set to the *current measured* behaviour
so they guard against future **downgrades**, not aspirations:

| Floor                                            | Threshold | Rationale                        |
|--------------------------------------------------|-----------|----------------------------------|
| mental-health **crisis recall**                  | ≥ 0.90    | missed-crisis guard              |
| SOS **severe (HIGH/CRITICAL) recall**            | ≥ 0.90    | under-escalation guard           |
| intent **escalation recall** on true EMERGENCY   | ≥ 0.90    | voice-SOS miss guard             |

Precision (false alarms) is reported but deliberately **not** floored: on this
platform a false alarm is a tolerable cost, a missed emergency is not. Over-
escalations in the error inventory (e.g. a slow-following car scored HIGH) are
retained as honest findings in the safe direction.

## Latest measured results (this seed set)

Reproduce with `python3 run_eval.py`; the authoritative machine-readable copy is
written to `results.json` on every run. Snapshot:

| Subsystem            |  n | accuracy | macro-F1 | safety metric                     |
|----------------------|---:|---------:|---------:|-----------------------------------|
| mental_health_crisis | 48 |   97.92% |   57.53% | crisis recall = **100.00%**       |
| sos_risk             | 32 |   87.50% |   87.20% | severe recall = **100.00%**       |
| intent               | 15 |   93.33% |   92.21% | emergency-esc recall = **100.00%**|
| legal_category       | 16 |  100.00% |  100.00% | —                                 |
| profile_query        | 13 |  100.00% |  100.00% | —                                 |

All three safety floors **PASS**; `--strict` exits 0. The mental-health risk-level
macro-F1 (57.53%) is low **by design**: the secondary risk-*level* boundaries
(LOW vs MODERATE distress) are intentionally soft, while the *binary* crisis
decision — the one that actually gates the crisis flow — is the hard, floored
metric. Known residual disagreements are listed by the harness itself as an
"honest error inventory" (e.g. `mh40` benign "vitamin pills" → CRISIS, a known
fail-safe fuzzy-match false-positive).

---

## Dataset provenance & format

Each dataset is a JSONL file under `datasets/`, one labelled example per line,
hand-authored to cover: clear positives, hard negatives (benign look-alikes),
multilingual distress (English / Hindi / Hinglish), and known boundary/edge
cases. Every row carries a short `note` documenting *why* it exists.

| File                          | Rows | Label field(s)                    |
|-------------------------------|-----:|-----------------------------------|
| `mental_health_crisis.jsonl`  |  48  | `crisis` (bool), `risk_level`     |
| `sos_risk.jsonl`              |  32  | `severity`                        |
| `intent.jsonl`                |  15  | `intent`                          |
| `legal_category.jsonl`        |  16  | `category`                        |
| `profile_query.jsonl`         |  13  | `query_type`                      |

Because the sets are synthetic and small, they are **honest about their own
limits**: a passing run means "no known safety behaviour regressed and the
documented trade-offs still hold", not "the model is accurate in production".

## Changing the datasets / floors

- Add rows to cover new failure modes rather than deleting rows that fail — a
  failing row is a documented finding, not noise.
- **Never tune a ground-truth label to match the model's output.** Labels reflect
  the clinically / domain-defensible correct answer; the code is fixed to meet
  the label, not the other way around.
- If you *raise* a floor, do it only after the measured metric genuinely improves
  and stays there. Floors ratchet up, never down.

## Files

- `run_eval.py` — the harness (loads datasets, calls the shipped code, computes metrics, prints report, writes `results.json`).
- `metrics.py` — pure-stdlib precision/recall/F1/FPR/FNR + confusion-matrix helpers.
- `datasets/*.jsonl` — the labelled seed sets described above.
- `results.json` — machine-readable output of the most recent run (regenerated each run).
