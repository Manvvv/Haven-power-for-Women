# HAVEN AI Evaluation — Seed Dataset Specification

This document is the **contract** for the labelled seed datasets in this folder.
`check_datasets.py` enforces it programmatically (run it before trusting a metric).

> **Nature & limits.** These are SMALL, HAND-AUTHORED, SYNTHETIC seed sets. They
> are not real user data and not a real-world benchmark — see `../README.md`.
> They exist to (a) trip loudly if safety behaviour regresses and (b) quantify
> known trade-offs. Grow them by *adding* rows for new failure modes; never delete
> a row just because it fails, and **never edit a ground-truth label to match the
> model** — labels encode the clinically / domain-defensible correct answer.

## Common rules (all datasets)

- Format: **JSONL** — one JSON object per line, UTF-8, blank lines ignored.
- `id` — unique, string, uses the file's prefix (below). Stable across edits.
- `note` — required on every row: a short human justification for *why the row
  exists and why the label is correct* (e.g. "hard negative: benign 'pills'").
- The free-text input field is dataset-specific (below) and must be non-empty.
- Multilingual coverage (English / Hindi / Hinglish) is intentional where the
  shipped code claims multilingual support.

## Datasets

### `mental_health_crisis.jsonl`  (prefix `mh`, input `text`)
Mental-health crisis triage for Aria. Fields:

| field        | type / vocab                                                              |
|--------------|---------------------------------------------------------------------------|
| `text`       | non-empty string (the user message)                                       |
| `lang`       | `en` \| `hi` \| `hinglish`                                                 |
| `crisis`     | bool — the primary, floored binary label                                  |
| `risk_level` | `IMMINENT_DANGER` \| `HIGH_RISK` \| `MODERATE_DISTRESS` \| `LOW_DISTRESS` \| `UNKNOWN` |

**Consistency rule (enforced):** `crisis == (risk_level in {IMMINENT_DANGER, HIGH_RISK})`.
Coverage: the four non-UNKNOWN risk levels must all appear. Include hard negatives
(benign look-alikes such as "vitamin pills") and reassurance/third-person-grief
rows that should *downgrade*.

### `sos_risk.jsonl`  (prefix `sos`, input `text`)
Free-text SOS severity on the deterministic `rules` backend. Fields:

| field      | type / vocab                                        |
|------------|-----------------------------------------------------|
| `text`     | non-empty string                                    |
| `severity` | `CRITICAL` \| `HIGH` \| `MODERATE` \| `LOW`          |

Coverage: all four bands. The floored metric is **severe (HIGH/CRITICAL) recall**;
include lethal-weapon, abduction, in-progress-danger, confinement, threat,
stalking, repeated-abuse, low-grade-unease, benign-admin, and de-escalation rows.

### `intent.jsonl`  (prefix `in`, input `transcript`)
Voice-SOS emergency intent (recognition-confidence aware). Fields:

| field                    | type / vocab                                                       |
|--------------------------|--------------------------------------------------------------------|
| `transcript`             | non-empty string (ASR transcript)                                  |
| `recognition_confidence` | number in `0.0 .. 1.0`                                             |
| `intent`                 | `EMERGENCY` \| `POSSIBLE_EMERGENCY` \| `UNKNOWN` \| `NON_EMERGENCY` |

Coverage: at least `EMERGENCY` and `NON_EMERGENCY`. Include low-confidence rows to
exercise the recognition-confidence cap.

### `legal_category.jsonl`  (prefix `lg`, input `question`)
Legal category routing. Fields:

| field      | type / vocab                                                                                                 |
|------------|--------------------------------------------------------------------------------------------------------------|
| `question` | non-empty string                                                                                             |
| `category` | `child_safety` \| `women_rights` \| `cyber` \| `workplace` \| `police` \| `family` \| `court_navigation` \| `legal_aid` \| `general` |

Coverage: at least `child_safety`, `women_rights`, `legal_aid` (the routing gaps
this harness was built to guard). `child_safety` takes priority when a child is
involved and there is a danger signal (abuse/missing/trafficking), unless the
question is purely custody/divorce/visitation/maintenance.

### `profile_query.jsonl`  (prefix `pf`, input `query`)
Culprit-profile query routing. Fields:

| field        | type / vocab                                                |
|--------------|-------------------------------------------------------------|
| `query`      | non-empty string                                            |
| `query_type` | `NAME_QUERY` \| `DESCRIPTION_QUERY` \| `MIXED_QUERY`         |

Coverage: all three types. Per the routing contract, a query with any physical
descriptor routes `DESCRIPTION_QUERY` even if a name is present; genuinely
uncertain recall ("was it ramesh or maybe suresh") is `MIXED_QUERY`.

## Running the checks

```bash
python3 check_datasets.py     # data linter (schema/vocab/coverage/consistency)
python3 ../run_eval.py         # then the model eval that consumes these datasets
```
