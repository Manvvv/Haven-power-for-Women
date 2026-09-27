# HAVEN — Mental-Health / Emotional-Support ("Aria") Upgrade
## Final Engineering & Safety Report

**Module:** HAVEN mental-health / emotional-support navigation
**Date:** 2026-09-25
**Status:** Implemented; backend safety layer verified (140/140 static checks + 30/30 runnable unit tests). Frontend type-check/build and the full pytest suite are to be run by the maintainer on Windows (see §19).

> HAVEN's mental-health module offers **empathetic emotional support and navigation to real help**. It is **not** a diagnostic tool, not a therapist, doctor, or emergency responder, and it never replaces one. Every safety-critical behaviour is deterministic and does **not** depend on any language model being available or honest.

---

## 1. Executive Summary

The existing "Aria" therapy chat was upgraded — **not rewritten** — into a safety-first emotional-support system. The core change is architectural: a **deterministic triage layer runs before any LLM call**, so crisis detection, medication-dosing refusals, and emergency-resource surfacing are reproducible, auditable, and survive an AI outage. Verified Indian helplines now live in a **single registry with provenance** (no numbers hardcoded across UI components, nothing fabricated). Privacy was tightened with per-turn opt-out, redaction of sensitive text before storage, AES-GCM encryption for the safety plan/journal/check-in notes, hashed-identifier logging, and user-controlled deletion. The UI gained three explicit actions (Talk / Calm Down / Get Help) plus an automatic crisis mode, all of which **only ever offer** help — HAVEN never contacts anyone on its own.

No existing authentication was removed, no HAVEN SOS security was bypassed, and no secrets were introduced. The deterministic safety layer is proven by `validate_mental_health.py` (140 checks) and a new `test_mental_health.py` whose 30 pure-layer tests were executed here and **all pass**; a further 18 API-contract tests run under the maintainer's Windows environment.

## 2. Objective & Scope

**In scope:** empathetic support; distress stabilization; crisis-signal detection; encouragement toward professional/human help; practical low-risk coping steps; connection to verified resources; privacy preservation; multilingual (English / Hindi / Hinglish) handling; graceful behaviour when the AI provider is down.

**Explicitly out of scope (by design, not omission):** diagnosis; medication names/doses/interactions; instructions to start or stop prescribed treatment; any claim of clinical certainty; any automatic contact of police, family, or authorities.

## 3. Audit of the Existing Feature (done before any change)

Per the directive "audit the existing feature; do not rewrite it blindly", the prior `/therapy` implementation was reviewed first. It was a single Groq-backed chat with an Aria avatar/voice and Clerk auth. Gaps found: crisis handling depended entirely on the LLM (no deterministic floor); helpline numbers were ad-hoc and duplicated in UI copy (fabrication/inconsistency risk); no medication-dosing guardrail; no privacy opt-out or redaction; no offline/AI-down path; no user-owned safety plan. **The Aria avatar, voice, Clerk login and chat UX were preserved**; the changes are additive (a triage/routing layer beneath, structured data on top).

## 4. Design Principles & Safety Invariants

The following invariants are enforced in code and asserted by tests:

1. **Deterministic before generative** — triage classifies risk with no LLM; crisis + medication replies come from fixed reviewed text.
2. **Single source of truth for resources** — every number is read from `mental_health_resources.py`; the only duplicated copy is one offline fallback module on the client.
3. **Never fabricate** — no invented helplines, professionals, doses, or diagnoses.
4. **Never silent** — the UI offers `tel:` links and links to HAVEN SOS; nothing auto-dials or auto-notifies.
5. **Privacy by default** — minimal storage, redaction of sensitive text, encryption at rest, hashed-id logs, user deletion, per-turn opt-out.
6. **Fail safe, not silent** — if the provider is down or rate-limited, the crisis panel and resources still render.

## 5. Architecture Overview (request flow)

```
user message
   │
   ▼
[ mental_health_triage.build_triage ]   ← deterministic, no network, multilingual
   │  risk_level ∈ {LOW, MODERATE, HIGH, IMMINENT, UNKNOWN}
   │  signals, dosing_request, minor_suspected, needs_clarification, language, mode
   ▼
route in therapy_routes.therapy_chat:
   crisis (HIGH/IMMINENT) ─────► fixed crisis text  (LLM NOT called)
   dosing_request ────────────► fixed medication-safety text  (LLM NOT called, no doses)
   otherwise ─────────────────► LLM w/ safety-hardened prompt
                                 └─ provider down → deterministic AI-unavailable text
   │
   ▼
attach: verified resources (registry) + coping tools + sources + disclaimer
        + user's own safety plan (only during crisis, only if authenticated)
   │
   ▼
persist (only if save=true & DB present; sensitive text redacted) → structured JSON
```

## 6. Change Inventory (every changed feature → file + why)

**Backend (created):**

- `services/mental_health_triage.py` — deterministic risk classifier + signals + language detection. *Why:* crisis detection must not depend on the LLM (spec §3, §17, §29).
- `services/mental_health_resources.py` — verified registry + offline pack. *Why:* one provenance-bearing source of truth; no fabrication, no per-component hardcoding (spec §4, §23, §32).
- `services/mental_health_support.py` — system-prompt builder, coping toolkit, and fixed crisis/medication/AI-outage text. *Why:* safety-critical prose must be reviewed and model-independent (spec §16, §18, §25, §29).
- `validate_mental_health.py` — 140-check stdlib validator (runs anywhere). *Why:* prove the safety layer without pytest/network.
- `test_mental_health.py` — 48-test suite (30 pure + 18 API). *Why:* regression protection for the safety contract (spec §30).

**Backend (modified):**

- `routers/therapy_routes.py` — upgraded `/therapy/chat` to the triage→route→structured-response flow; added resources / offline-pack / coping-tools / safety-plan / mood-checkin / journal / privacy / deletion endpoints. *Why:* deliver the structured contract and privacy controls.
- `models/schemas.py` — added `MentalHealthChatModel`, `SafetyPlanModel`, `MoodCheckinModel`, `MoodJournalEntryModel`. *Why:* typed, length-bounded request bodies (spec §28).
- `services/db.py` — added `therapy_sessions`, `mh_safety_plans`, `mh_mood_journal`, `mh_mood_checkins` collection accessors. *Why:* isolated, minimal storage.

**Frontend:**

- `frontend/src/components/therapy/support.ts` (created) — shared types + the single offline fallback pack.
- `frontend/src/components/therapy/SafetyPanels.tsx` (created) — Crisis / Calm-Down / Get-Help overlays.
- `frontend/src/app/therapy/page.tsx` (modified) — action bar, registry-driven footer, panel wiring, do-not-save toggle.
- `frontend/src/app/therapy/safety-plan/page.tsx` (created) — encrypted safety plan, mood check-ins, journal, privacy dashboard.

## 7. Deterministic Safety Triage — `services/mental_health_triage.py`

Classifies a message into one conservative risk state (`LOW_DISTRESS`, `MODERATE_DISTRESS`, `HIGH_RISK`, `IMMINENT_DANGER`, `UNKNOWN`) plus independent boolean signals (`self_harm`, `suicide`, `abuse`, `violence`, `child_safety`, `medical_emergency`, `psychosis`, `substance`). It uses Unicode-aware tokenization + high-precision phrase lexicons across English, Devanagari Hindi, and Hinglish. Key safety behaviours: acts-in-progress and active external violence escalate to `IMMINENT`; explicit reassurance ("I would never hurt myself") and third-person bereavement **downgrade** so grief is not misread as active risk; ambiguous phrases raise a **gentle clarifying safety question** rather than assuming safety; dosing/lethal-quantity requests are flagged (`dosing_request`) so they can be refused. It performs **no diagnosis** and emits **no clinical labels** — only risk, signals, language, and mode. *Verified:* §16 tests below (tiers, nuance, multilingual, dosing) — 20 assertions pass.

## 8. Verified Resource Registry — `services/mental_health_resources.py`

A single dict of resources, each carrying `name/type/number/purpose/country/source_url/verified_at/authority_level/availability`. Government-issued lines (112 ERSS, Tele-MANAS 14416, KIRAN 1800-599-0019, Childline 1098, Women 181) are tagged `government_verified` and re-verified against official sources on 2026-09-25; reputable NGO lines (Vandrevala, AASRA, iCALL) are tagged `ngo_helpline` and clearly distinguished so callers can tell them apart. Priority-ordered selectors (`emergency_resources`, `crisis_resources`, `support_resources`, `child_resources`, `women_resources`, `professional_resources`) and an `offline_pack()` provide exactly the right set per situation. Professional pointers route to official institutions (Tele-MANAS, NIMHANS, DMHP) — **no local clinics are invented**. If a number ever fails re-verification, it is changed here once and the whole app updates. *Verified:* every entry has provenance; 112 leads emergencies; 14416 present in crisis; offline pack self-contained.

## 9. Empathy Engine & Fixed Safety Text — `services/mental_health_support.py`

`build_system_prompt()` assembles a safety-hardened prompt for **non-crisis** turns only: acknowledge feelings, reflect without labelling, offer one or two small low-risk steps, encourage trusted people and professionals, stay brief, and an explicit **NEVER** list (no diagnosis, no medication/doses, no false certainty or false safety, no invented resources, no dependency-building, no pretending to be human or to have contacted anyone). Crisis (`HIGH`/`IMMINENT`), medication-dosing, and AI-outage replies are **fixed, reviewed text** in three languages, so they are correct even if the model is down or misbehaves. The coping toolkit is evidence-informed **support strategies explicitly marked "not medical treatment"**. *Verified:* fixed texts contain the verified numbers, contain no dose (`\d+\s*(mg|ml|tablet…)`), and match neither a diagnosis nor a false-safety pattern.

## 10. Structured Backend Response & Routes — `routers/therapy_routes.py`

`POST /therapy/chat` (anonymous-capable via `get_optional_user`) returns the full contract the frontend consumes: `response, risk_level, crisis, needs_clarification, clarifying_question, coping_tools, emergency_resources, professional_resources, safety_plan, language, sources, disclaimer, session_id, mode, ai_available, saved`. Crisis and dosing branches never reach `call_groq`. Resource/offline-pack/coping-tool endpoints use a **higher rate limit (120/60)** than chat (30/60) so the crisis panel renders even when chat is throttled or the provider is down (spec §28, §29). Cross-user session access is rejected with 403; safety-plan/journal/check-in/privacy/deletion endpoints require authentication (`get_current_user`).

## 11. Privacy & Data Minimization

- **Per-turn opt-out:** `save:false` persists nothing (asserted).
- **Redaction:** when a turn carries a sensitive signal, the stored user text is replaced with `[sensitive message not stored for your privacy]` before it touches the DB.
- **Encryption at rest:** safety plan, journal entries, and check-in notes are AES-GCM encrypted via `encrypt_evidence_payload` / `decrypt_evidence_payload`.
- **Safe logging:** only hashed identifiers + non-sensitive metadata (risk tier, language, latency, provider status) are logged — never raw text, contacts, or numbers.
- **User control:** delete a single session, the safety plan, a journal entry, or *all* mental-health data; a `/therapy/privacy` dashboard states what is stored, why, retention, who can access it, and exactly what the AI provider receives (only the current non-crisis message; crisis/medication replies are generated locally and never sent to the AI).

## 12. Frontend UX

`frontend/src/app/therapy/page.tsx` keeps Aria's avatar/voice/Clerk chat and layers on a three-action bar — **Talk** (chat), **Calm Down** (`CalmDownPanel`), **Get Help** (`GetHelpPanel`) — plus an automatic **CrisisPanel** shown when a turn is triaged as crisis. Numbers render from the registry fetched at mount; on fetch failure the UI falls back to the single offline pack in `support.ts` and shows an "offline / please confirm" banner. The footer's previously hardcoded numbers were replaced with registry-driven links and a **"Don't save this conversation"** checkbox. `safety-plan/page.tsx` provides the encrypted safety plan, mood check-ins, private journal, and privacy dashboard behind Clerk sign-in. All panels use large tap targets, `role="dialog"`, Escape-to-close, and consent copy.

## 13. Never-Silent Escalation & Consent

Every escalation is a user action: `tel:` links the user chooses to tap, and links to `/sos` (HAVEN SOS / trusted contact). A reused `ConsentNote` states plainly: *"HAVEN will not call, message, or alert anyone automatically. You choose if and when to reach out."* Contact fields in the safety plan carry *"Your notes — HAVEN never contacts them for you."* This satisfies the constraint against automatically contacting police/family/authorities and does not touch the existing HAVEN SOS authentication or flow.

## 14. Multilingual Support (English / Hindi / Hinglish)

`detect_language` picks the language from a hint, Devanagari presence, or a Hinglish token set. Each risk lexicon contains English, Devanagari, and romanised-Hindi phrases, so crisis phrases like `मरना चाहता` and `pills le li` escalate correctly. All fixed crisis/medication/AI-outage texts exist in `en`/`hi`/`hinglish` and the reply is localized to the detected language. *Verified:* Hindi suicidal ideation → `HIGH`+crisis (language `hi`); Hinglish `maine abhi pills le li` → `IMMINENT`+crisis; the Hindi crisis text contains Devanagari.

## 15. Failure Modes & Offline Resilience

- **Provider down (non-crisis):** `call_groq` raising is caught; the endpoint returns HTTP 200 with `ai_available:false`, deterministic supportive text carrying Tele-MANAS 14416, and coping tools — never a 5xx dumped on a distressed user.
- **Crisis/medication with provider down:** unaffected — those replies never call the provider.
- **Chat rate-limited:** resources / offline-pack / coping-tools have their own higher limit, so Get-Help/Crisis panels still populate.
- **Client offline:** the UI renders `OFFLINE_EMERGENCY` (112 + Tele-MANAS) and the offline grounding/breathing steps with a confirm-when-online banner.

## 16. Testing & Verification

Two complementary artefacts:

**(a) `validate_mental_health.py`** — a stdlib-only validator (no pytest, no network) covering triage tiers, signal detection, resource provenance, offline pack, and fixed-text safety. **Result (run here): `PASSED 140 checks / ALL MENTAL-HEALTH SAFETY CHECKS PASSED`.**

**(b) `test_mental_health.py`** — 48 tests in two layers:

- **Layer A (30 tests, pure — no app/DB/network):** classification tiers; reassurance/grief downgrade; clarifying-question safety; no-diagnosis-label; EN/HI/Hinglish crisis; dosing-request flag; fixed-text safety (verified numbers present, no dose, no diagnosis, no false safety); registry provenance and ordering; offline pack; coping/escalation selection. **Executed in this environment via a pytest shim: 30 passed, 0 failed.**
- **Layer B (18 tests, FastAPI `TestClient`, LLM monkeypatched):** non-crisis uses the LLM and returns the full contract; **crisis and medication paths assert the LLM is *not* called** (the spy raises if reached) and still surface verified resources; AI-outage returns safe support at HTTP 200; Hindi/Hinglish crisis end-to-end; `save:false` ⇒ `saved:false`; anonymous chat allowed; resource/offline/coping endpoints; **safety-plan / privacy / delete-all reject anonymous callers (401/403)** and succeed with a real minted token.

Layer B is guarded by `APP_AVAILABLE`; in this Linux sandbox the app import fails (no FastAPI/Windows `.venv`), so Layer B **skips cleanly here** and runs on the maintainer's Windows host.

**How the LLM is isolated:** tests monkeypatch `routers.therapy_routes.call_groq` with a spy — the real network/model is never called, and the spy doubles as a probe that a crisis reply was produced *without* the model.

## 17. Security Regression Review

- **Authentication:** no existing guard removed. `/therapy/chat` intentionally remains anonymous-capable (as before) via `get_optional_user`; all write/personal endpoints (`safety-plan`, `mood-checkin`, `journal`, `privacy`, `mental-health-data`) require `get_current_user`. Anonymous access to these is rejected (401/403) — asserted in tests.
- **Ownership:** therapy-session read/write and single-session delete enforce user ownership (403 on mismatch); a body `user_id` is never trusted for a write target when a token is present.
- **HAVEN SOS:** untouched — the UI only *links* to `/sos`; no SOS endpoint, auth, or trigger logic was modified or bypassed.
- **Secrets:** none added; tests mint tokens via the app's own `create_access_token` (no hardcoded secret/password). Encryption reuses the existing `encrypt_evidence_payload` path.
- **Input bounds:** request models are length-capped (message ≤2000, note ≤500, journal ≤5000, etc.).
- **Logging:** hashed uid + metadata only; no raw text, contacts, or numbers.
- **Rate limiting:** preserved; chat 30/60, resource endpoints 120/60 (deliberately higher for crisis availability, read-only, non-fabricated data).

**Net:** the changes add safety and privacy controls; they do not weaken any existing control.

## 18. Compliance with DO-NOT Constraints

| Constraint | Status | Where enforced |
|---|---|---|
| Do not diagnose | ✅ | Prompt NEVER-list; triage emits no labels; regex-asserted |
| No medicine names / doses | ✅ | Fixed medication text (no numbers); `_DOSE_RE` asserted |
| Don't tell users to stop treatment | ✅ | Prompt NEVER-list; deterministic refusal defers to doctor/pharmacist |
| No clinical certainty | ✅ | Prompt NEVER-list; support-only phrasing |
| No false "you are safe" | ✅ | `_FALSE_SAFETY_RE` asserted against all fixed texts |
| No fabricated resources | ✅ | Single verified registry with provenance |
| No automatic contact of anyone | ✅ | User-tap `tel:`/SOS links + ConsentNote copy |
| No sensitive text in logs | ✅ | Hashed uid + metadata only |
| No unnecessary storage | ✅ | `save:false`, redaction, encryption, deletion |
| No irreversible AI decisions | ✅ | Deterministic triage; AI only drafts non-crisis prose |
| Do not commit / push | ✅ | No git operations performed |
| Do not expose secrets | ✅ | None added/printed |
| Don't bypass HAVEN SOS security | ✅ | SOS only linked, never modified |
| Don't remove authentication | ✅ | All prior guards intact; personal endpoints require auth |

## 19. Limitations, Residual Risks & Next Steps

**Limitations / residual risks.** Triage is lexicon-based and language-bounded to EN/HI/Hinglish; novel phrasings or other languages may under-trigger — mitigated by conservative escalation and the always-visible Get-Help panel, but worth expanding. NGO numbers carry an older `verified_at` (2026-01-01) and should be re-confirmed on a schedule. Encryption and redaction protect stored data, but the current non-crisis message is still sent to the AI provider to generate a reply (disclosed in the privacy dashboard). The safety plan surfaces during a crisis only for authenticated users.

**To run on Windows (maintainer):**

```powershell
# Backend (from haven/backend, with the project .venv active)
pytest -v test_mental_health.py          # 48 tests (Layer A + Layer B)
python validate_mental_health.py         # 140 static safety checks

# Frontend (from haven/frontend)
npx tsc --noEmit                         # type-check the new/changed TSX/TS
npm run build                            # production build
```

These three commands are Windows-only here because PyPI/npm are blocked in the sandbox and the backend `.venv` is a Windows build; the deterministic safety layer is already proven above (140/140 static + 30/30 runnable unit tests). **Recommended next steps:** schedule periodic helpline re-verification; add localized coping content per region; consider on-device/redacted prompting to further reduce provider exposure; add analytics on triage tier distribution (metadata only) to tune lexicons.

---

*No commits or pushes were made. No secrets were added or exposed. HAVEN does not diagnose, does not give medication instructions, and never contacts anyone without the user initiating it.*



