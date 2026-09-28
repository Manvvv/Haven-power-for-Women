# HAVEN — AI Architecture Report & Roadmap

**Scope:** the AI/ML systems of the HAVEN women's-safety platform (backend `haven/backend/services`).
**Date:** 2026-09-28 · **Author:** AI-intelligence upgrade (Section 28 deliverable).
**Status of numbers:** every metric here is **measured at run time** by the eval
harness on **synthetic seed datasets** — it is a regression signal, **not** a
real-world accuracy claim. Nothing in this report is hand-typed as a result.

---

## 0. How to read this report

This is a 20-point architecture report. It is deliberately blunt about what the
system **is** and **is not**, because the governing constraint for this work was:
*"Do NOT claim an AI is 'trained' unless actual training/fine-tuning/data
optimization has happened"* and *"Do not fabricate real-world accuracy numbers."*

The one-line truth: **HAVEN's shipped default AI is prompt + retrieval (RAG) +
deterministic rule logic — not a model HAVEN trained.** Where an LLM is used it is
a hosted general model behind a strict validation contract, and it is never
allowed to make an authority decision on its own.

---

## 1. What the AI actually is (and is not)

| Layer | What it really is | Trained by HAVEN? |
|-------|-------------------|-------------------|
| SOS free-text risk (default) | deterministic regex **lexicon** + severity rules | No — hand-authored rules |
| Mental-health (Aria) triage | deterministic phrase/keyword triage + verified resource registry | No |
| Legal answers | **RAG** over a verified Indian-law corpus + deterministic category triage | No |
| Profile/culprit match | deterministic name match + embedding-similarity **lead** for descriptions | No — similarity is a lead, not identity |
| Voice-SOS intent | deterministic rules, recognition-confidence aware | No |
| Anomaly / abuse signal | deterministic heuristic score, **separate** from emergency risk | No |
| Generation (Aria replies, legal prose) | hosted LLM (`openai/gpt-oss-120b` default) behind the AI contract | No — inference only, no fine-tune |

There are optional *learned tiers* (embeddings / classifier) referenced in code,
but the **default, always-available** path on a fresh checkout is deterministic,
so the platform degrades to explainable rules, never to nothing.

---

## 2. Subsystem inventory

Files under `haven/backend/services` (+ `services/ml`):
`ml/rule_classifier.py` + `ml/risk_engine.py` (SOS), `mental_health_triage.py` /
`_support.py` / `_resources.py` (Aria), `legal_triage.py` / `legal_corpus.py` /
`legal_rag.py` (legal), `profile_search.py` / `search_service.py` (profile),
`intent_service.py` (voice), `anomaly_signal.py` (abuse signal),
`ai_contract.py` (unified output contract), `prompt_registry.py` (prompt/version
tracking), `ai_service.py` (LLM call + minimization).

---

## 3. Unified AI response contract (`ai_contract.py`, `ai-contract-v1`)

Every subsystem returns ONE typed shape:
`{result, confidence, risk_level, reasoning_summary, signals, sources, grounded,
model, version, degraded, needs_human_review, subsystem}`.

- `validate_and_repair` **never raises** — malformed / partial / hostile model
  output is repaired into a safe, `degraded=true`, `needs_human_review=true`
  response. Invalid output therefore never reaches a user.
- **No chain-of-thought leaks:** `reasoning_summary` is stripped of `<think>`-style
  blocks and deliberation markers; it carries *observable evidence only*.
- The core is **pure standard library** (no pydantic/FastAPI dependency) so the
  "invalid output never reaches users" guarantee is unit-testable on a fresh
  checkout and not coupled to a pydantic version.
- **Hard boundary:** the contract is presentation/validation only. `result` is a
  data payload; nothing in it sets a role, moves an SOS lifecycle, dispatches,
  grants DB access, suspends an account, decides legal status, or asserts identity.

## 4. Prompt & version registry (`prompt_registry.py`, `prompt-registry-v1`)

Each prompt has a stable **id + version + content fingerprint**. `stamp()` adds
`prompt_id` / `prompt_version` / `resolved_model` to responses (additive,
non-breaking). Reviewed prompts stay in their own module and `attach()` their live
text so the registry can **detect drift** without holding a divergeable copy. The
registry never selects a model, routes, or gates anything — metadata only. Default
generation model recorded as `openai/gpt-oss-120b`; the actual answering model can
differ after fallback and `stamp` never claims more than the model it was given.

## 5. SOS free-text risk engine (`ml/rule_classifier.py`, `rule-lexicon-v2`)

Deterministic, fully explainable, zero ML deps. A regex lexicon maps text to seven
indicators (physical_assault, threat, confinement, stalking, immediate_danger,
repeated_abuse, emergency_assistance_request), extended with a Hindi/Hinglish
lexicon (additive — can only *raise* severity). Severity is a **deterministic
safety floor**:

- lethal cue (weapon / asphyxiation / "kill me") **or** abduction in progress → **CRITICAL**
- in-progress danger + (help plea / assault / threat) → **CRITICAL**
- assault / confinement / in-progress danger / threat / stalking / repeated abuse → **≥ HIGH**
- low-grade fear / harassment (no active violence) → **MODERATE** floor
- explicit "I'm safe / no danger" **with no danger signal** → LOW

A contradictory reassurance ("I'm safe now, he has a knife") **never** overrides an
active weapon/violence/threat signal. The engine **only raises on evidence** — it
never downgrades a concrete high-risk signal. Output is decision support; there is
**no auto-dispatch** — a human authority verifies first.

## 6. Mental-health / Aria triage (`mental_health_triage.py`, `_support.py`, `_resources.py`)

Crisis is detected **before** any generation. Levels: IMMINENT_DANGER, HIGH_RISK,
MODERATE_DISTRESS, LOW_DISTRESS, UNKNOWN; `crisis` = level ∈ {HIGH, IMMINENT}. For
crisis, the response is a **deterministic safe message with verified helpline
numbers** (e.g. 112, 14416) drawn from a versioned registry — **the LLM is never
allowed to improvise crisis contact information**. The deterministic safety text
never diagnoses, never promises false safety, and medication/dosing questions
carry **no doses/numbers** and escalate. Reassurance and third-person grief
correctly downgrade. Enforced by `validate_mental_health.py` (208 checks).

## 7. Legal RAG + triage (`legal_rag.py`, `legal_triage.py`, `legal_corpus.py`)

Every substantive answer is **grounded in retrieved sources** from a verified
Indian-law corpus (`CORPUS_VERSION 2026-09-25`). If no adequate source is
retrieved, the response is `grounded:false` / no-context — **it does not
hallucinate law**. A deterministic keyword classifier routes the question into 9
categories (child_safety takes priority when a child + danger signal is present,
unless purely custody/divorce/maintenance). Practical scaffolding text is generic
and contains **no fabricated section numbers, deadlines, fees, or case names** —
those come only from the corpus. `legal-grounded` prompt is versioned.

## 8. Profile / culprit matching (`profile_search.py`, `search_service.py`)

Query routing: NAME_QUERY / DESCRIPTION_QUERY / MIXED_QUERY. Names use a
**deterministic** match; descriptions use embedding similarity as an
**investigative lead, not proof of identity**. Results carry
`match_score` / `match_factors` / `match_level` / `human_verification_required`,
and a `SAFE_PUBLIC_MATCH_FIELDS` allowlist prevents leaking private DB fields.
**An embedding-similarity score alone never claims identity.**
*(Carry-over: `search_service.py`'s own `/search` paths still need to be routed
through this hardening — see §20 roadmap.)*

## 9. Voice-SOS intent (`intent_service.py`, `intent-rules-v1`)

Deterministic intent detection over the ASR transcript, **recognition-confidence
aware** — low ASR confidence caps how far intent may escalate on weak evidence,
but a clear emergency phrase still escalates. Four levels: EMERGENCY,
POSSIBLE_EMERGENCY, UNKNOWN, NON_EMERGENCY.

## 10. Anomaly / abuse signal (`anomaly_signal.py`, `anomaly-signal-v1`)

A deterministic heuristic that is **strictly separate from emergency_risk**. It
never auto-classifies a user as "fake" and never triggers punishment;
`abuse_risk` / `suspicious_activity_score` are advisory signals for **human
authority review only**, which is always final. Enforced by
`validate_anomaly_signal.py` (37 checks).

---

## 11. Output-authority boundaries (the most important safety property)

Raw LLM output must **NEVER** control any of these — and by design it does not,
because each is owned by deterministic backend code, not the model payload:

- user role / authority role
- SOS lifecycle transitions
- emergency dispatch
- database authorization
- account suspension
- legal status determination
- identity determination (culprit match)

The LLM contributes *text and advisory signals*. Decisions are code. This is
enforced structurally by §3's hard boundary and verified by
`validate_ai_contract.py` (215 checks).

## 12. Safety floors & enforcement

For a women's-safety platform the dangerous failure is **under-escalation** — a
real emergency scored calm. So the guarded metrics are **recall on the severe
classes**, floored in the eval harness and CI-enforceable via `--strict`:

| Floor | Threshold | Currently (seed set) |
|-------|-----------|----------------------|
| mental-health crisis recall | ≥ 0.90 | **100.00%** PASS |
| SOS severe (HIGH/CRITICAL) recall | ≥ 0.90 | **100.00%** PASS |
| voice intent emergency-escalation recall | ≥ 0.90 | **100.00%** PASS |

Precision (false alarms) is reported but **not** floored: a false alarm is a
tolerable cost here; a missed emergency is not.

## 13. Multilingual coverage

English + Hindi (Devanagari) + Hinglish (romanized) across SOS lexicon,
mental-health triage, and legal triage. Non-English patterns are **additive** —
they can raise a fired indicator / severity, never silently drop one, so a
Hindi/Hinglish SOS is no longer scored LOW ("no signal"). Localization of UI/
resource text is versioned and validated (`validate_localization.py`, 3362 checks).

## 14. Data minimization & privacy

Per constraint *"Never place real sensitive user conversations into training data
automatically"*: there is **no automatic training pipeline** ingesting user
conversations. `ai_service.py` minimizes/sanitizes what is sent to the hosted LLM
provider, raw sensitive prompts are not logged, and secrets/tokens are not
exposed. Verified-resource text (helplines, law) is server-owned, not model-
generated.

## 15. Degradation & fallback behaviour

Every subsystem has a deterministic floor, so if the LLM/embeddings/network are
unavailable the platform degrades to explainable rules + verified resources with
`degraded=true` / `needs_human_review=true` — never to a crash and never to an
unvalidated model string. `ai_contract.validate_and_repair` is the last line: junk
in → safe degraded response out.

## 16. Evaluation harness (`test/ai_evaluation/`)

`run_eval.py` (+ `metrics.py`) scores the deterministic layers against labelled
seed datasets and computes **real** precision/recall/F1/FPR/FNR + confusion
matrices — no number is hard-coded. `--strict` exits non-zero on any floor breach
(CI tripwire). Only layers that run without torch/sklearn/network are scored; the
SOS engine is scored on its default `rules` backend. Output is written to
`results.json` each run.

## 17. Measured results (synthetic seed set — NOT a production benchmark)

Reproduce with `python3 test/ai_evaluation/run_eval.py`:

| Subsystem | n | accuracy | macro-F1 | safety metric |
|-----------|---:|---------:|---------:|---------------|
| mental_health_crisis | 48 | 97.92% | 57.53%¹ | crisis recall **100%** |
| sos_risk | 32 | 87.50% | 87.20% | severe recall **100%**, under-esc 0 |
| intent | 15 | 93.33% | 92.21% | emergency-esc recall **100%** |
| legal_category | 16 | 100.00% | 100.00% | — |
| profile_query | 13 | 100.00% | 100.00% | — |

¹ The risk-*level* macro-F1 is intentionally soft (LOW vs MODERATE distress
boundary); the *binary crisis* decision — the one that gates the crisis flow — is
the hard, floored metric at 100% recall. **These numbers describe the seed set
only.**

## 18. Dataset provenance & quality checks (`test/ai_evaluation/datasets/`)

Datasets are small, hand-authored, synthetic JSONL seed sets; each row carries a
`note` justifying why it exists and why its label is correct. `DATASETS.md` is the
schema contract; `check_datasets.py` enforces it (789 checks over 124 rows: valid
JSON, unique prefixed ids, non-empty text, allowed label vocab, required note,
crisis↔risk_level consistency, minimum class coverage). Discipline: **labels are
never tuned to model output**; failing rows are documented findings, not deleted.

## 19. Honest limitations & error inventory

- Seed datasets are **not** a real-world benchmark; production accuracy is unknown
  and is **not** claimed anywhere.
- Known residual disagreements retained honestly: `mh40` benign "vitamin pills" →
  CRISIS (fail-safe fuzzy-match false-positive); SOS over-escalations (`sos22`
  slow-following car → HIGH; `sos26–28` admin/test mentioning "sos"/"emergency" →
  MODERATE) — all in the **safe** direction.
- Learned/embedding tiers are **not** measured here (not installable in the build
  sandbox); only the deterministic default paths are scored.
- `search_service.py` still exposes raw similarity and lacks `match_level` /
  `human_verification_required` on some paths (see roadmap #1).

## 20. Roadmap

1. **Profile stack unification** — route `search_service.py` `/search/profiles` and
   `/search/semantic` through the `profile_search` hardening so *every* path
   returns `match_level` + `human_verification_required` and never leaks raw score.
2. **Legal retrieval hardening** — keyword-mode relevance floor, embedding-dim
   renormalization, and a post-generation citation check (drop any sentence not
   traceable to a retrieved source).
3. **Real evaluation at scale** — expand seed sets toward a governed, privacy-safe
   labelled set (opt-in, de-identified) before *any* accuracy claim is made; only
   then consider raising safety floors.
4. **Optional learned tiers, measured honestly** — if/when a classifier or
   embedding tier is trained, evaluate it head-to-head against the deterministic
   floor and **only** ship it where it measurably wins **without** ever lowering a
   safety floor or taking authority from deterministic code.
5. **Continuous safety CI** — wire `run_eval.py --strict`, `check_datasets.py`, and
   the `validate_*.py` suite into CI so a regression fails the build.

---

### Verification snapshot (sandbox, stdlib only, 2026-09-28)

`run_eval.py --strict` exit 0 (all 3 floors PASS) · `check_datasets.py` 789/789 ·
`validate_risk_rules.py` 47 · `validate_legal_corpus.py` 57 ·
`validate_mental_health.py` 208 · `validate_ai_contract.py` 215 ·
`validate_anomaly_signal.py` 37 · `validate_profile_search.py` 44 ·
`validate_prompt_registry.py` 30 · `validate_localization.py` 3362.

**Requires Windows/host verification** (not runnable in this sandbox): `pytest`
suite, pydantic/FastAPI import paths, `next build`, and any network-dependent
(embeddings/LLM) tier.
