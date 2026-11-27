# HAVEN V2 — Implementation Report

**Project:** HAVEN — Power for Women (Website-Only V2 Upgrade)  
**Scope:** Next.js 14 (`haven/frontend/`) & FastAPI (`haven/backend/`) — No Android/Kotlin/TWA modifications  
**Date:** 2026-11-26  
**Overall Implementation Status:** `PASS` for core website workflows with local DB & configured AI; `BLOCKED BY EXTERNAL CONFIGURATION` where Twilio SMS, live Redis, or Clerk backend JWKS env vars are absent; `NOT VERIFIED` for physical mobile browsers and live production deployment (excluded per constraints).

---

## 1. Executive Summary & Prompt Requirement Matrix

| Phase | Feature Area | Status | Notes |
|---|---|---|---|
| Phase 1 | User Dashboard (`/dashboard`) Safety Overview, Quick Actions, Real Incident State | `PASS` | Fetches real `/trusted-contacts/{userId}`, `/check-in/active`, `/therapy/safety-plan`, and `/sos/my-incidents`; passes real `trustedContactCount`. |
| Phase 2 | Website SOS & Incident Tracking (`/sos`, `/dashboard`) | `PASS` | Category selection, optional description, GPS coords + accuracy + timestamp, manual fallback, idempotency key, MongoDB persistence, owner-only `/sos/my-incidents`, `/sos/incidents/{case_id}`, `/cancel`, WebSocket live updates. |
| Phase 3 | Voice SOS with AI (`VoiceAudioRecorderPanel`, `/voice-sos/*`) | `PASS` (backend + UI); `NOT VERIFIED` (live Groq network audio round-trip) | `MediaRecorder` start/pause/stop, MM:SS timer, `<audio controls>` playback, `/voice-sos/stt-status`, `/voice-sos/transcribe` (Whisper large-v3-turbo / `whisper-1`), editable transcript, `/voice-sos/extract` with `is_gps_confirmed=False`, `auto_dispatched=False`, explicit human confirmation. |
| Phase 4A | Trusted Contacts (`/safe-contacts`, `/trusted-contacts/*`) | `PASS` (CRUD/Verify/Notify API); `BLOCKED BY EXTERNAL CONFIGURATION` (Twilio SMS) | Relationship, priority `1..5`, edit (`PATCH`), duplicate phone guard (`409`), verification (`NOT_CONFIGURED` vs manual confirm), audit history (`/trusted-contacts/history/{user_id}`), explicit-consent `/notify` + WhatsApp fallback. |
| Phase 4B | Emergency Check-In Timer (`/check-in/*`, `/safe-contacts`) | `PASS` | Persistent MongoDB `safety_checkins`, mandatory `consent_acknowledged=True`, separate contact vs authority escalation consent toggles, `confirm-safe`, `extend`, `cancel`, backend `_sweep_loop` running `process_due_checkins()`. |
| Phase 5 | Rapid Response Network (Authority & Responder Portals) | `PASS` | Added `GET /responder/history` (`require_responder`, zero victim PII), `/authority/rapid-response` severity & dispatch state filters + response/resolution duration metrics (`response_time_seconds`, `resolution_time_seconds`). |
| Phase 6 | Admin Panel & Real Metrics (`/admin`, `/admin/users/*`, `/admin/system-stats`) | `PASS` | Added user search (`?search=`), `PATCH /admin/users/{user_id}/status` (suspend/reactivate enforced in `auth.py` `_check_user_active` + self-suspend guard + audit log), real non-demo `sos_cases` counts isolated from demo records. |
| Phase 7 | Personalized Safety Plan (`/therapy/safety-plan`) | `PASS` | Added `personal_safety_considerations`, `emergency_preparation`, `important_documents`, `personal_notes` (AES-256-GCM encrypted at rest via `encrypt_evidence_payload`), JSON export with privacy warning, live `/therapy/resources` verified helplines. |
| Phase 8 | Dedicated Demo Mode (`/demo`, `/demo/*`) | `PASS` | Strict `demo_*` collection sandbox (`demo_cases`, `demo_dispatches`, `demo_responders`, `demo_contacts`, `demo_checkins`, `demo_provider_registrations`, `demo_safety_plans`, `demo_audit_logs`); never touches production collections, SMS, or WS channels; zero public credentials/bypass. |
| Phase 9 | Multilingual Support (`src/locales/strings.ts`) | `PASS` (EN/HI/Hinglish); `PARTIALLY IMPLEMENTED` (5 community langs) | `en`, `hi`, `hinglish` 179/179 keys (`100.0%`); `bn`, `mr`, `ta`, `te`, `gu` 80/179 (`44.7%`); `kn`, `ml`, `pa`, `or`, `as` fallback intentionally to English without machine-translating safety text (`validate_localization.py`: 3572 checks passed). |
| Phase 10 | Security & Privacy Audit & Hardening | `PASS` (app controls); `BLOCKED BY EXTERNAL CONFIGURATION` (Clerk JWKS env & live Redis) | Added `_check_user_active` user suspension check in `get_current_user`, strict Zod/Pydantic validation, BOM/XSS/idempotency tests, audio MIME + 10 MB ceiling, Redis/Twilio/Clerk JWKS gaps documented explicitly. |
| Phase 11 | Responsive Design & Accessibility | `PARTIALLY IMPLEMENTED` (`NOT VERIFIED` on physical mobile browsers) | Responsive Tailwind layouts, mobile-friendly header/cards, `aria-pressed`, `aria-live` status regions, semantic controls verified by build/static/component specs; no live mobile device / Playwright matrix executed. |
| Phase 12 | Automated Testing & Verification | `PASS` | `736` backend `pytest` tests + `236` Node frontend test assertions + `9/11` backend validator suites (`2` pre-existing untouched search validators failed) + `npx tsc --noEmit` + `npm run build` (`21/21` routes). |

---

## 2. Features Implemented (Architecture & Capabilities)

1. **Main User Experience (`/dashboard`):**
   - Live Safety Overview loading real backend state for trusted contact count (`GET /trusted-contacts/{userId}`), active emergency check-in timer (`GET /check-in/active`), personal safety plan summary (`GET /therapy/safety-plan`), and real submitted incident history via `IncidentTracker`.
   - Quick Actions linking to Website SOS (`DirectSOSForm`), Voice SOS (`/voice-sos`), Trusted Contacts & Check-In (`/safe-contacts`), Safety Plan (`/therapy/safety-plan`), Legal Guidance (`/legal`), Therapy/Aria (`/therapy`), and Interactive Demo Mode (`/demo`).
   - Preserved Clerk greeting identity resolution (`resolveGreetingName`), language switching (`LanguageContext`), and Emergency 112/181/1091 references without fabricated dashboard counters.

2. **Website SOS & Incident Tracking (`DirectSOSForm`, `IncidentTracker`, `/sos/*`, `/cases/*`):**
   - `DirectSOSForm` requires category selection, captures browser geolocation coordinates, accuracy (`±m`), and capture timestamp, handles GPS permission denial gracefully, supports manual location fallback, and preserves client `idempotency_key` on retry.
   - `sos_routes.py` persists validated incidents to MongoDB (`sos_cases`), enforces state machine transitions in `lifecycle_service.py` (including `CANCELLED`), blocks unauthorized status transitions for standard users, and emits WebSocket updates on `/ws/track/{event_id}`.
   - `cases_routes.py` filters out demo records (`{"is_demo": {"$ne": True}}`).

3. **Voice SOS with Whisper AI (`voice_ai_service.py`, `VoiceAudioRecorderPanel.tsx`, `/voice-sos`):**
   - Preserved existing hands-free passive safe-word mode while adding browser `MediaRecorder` recording (requesting mic access only on user trigger), live MM:SS duration, pause/resume/stop controls, and `<audio controls>` playback.
   - `/voice-sos/stt-status` inspects `GROQ_API_KEY` (`whisper-large-v3-turbo`) or `OPENAI_API_KEY` (`whisper-1`); never fabricates transcripts when unconfigured.
   - `/voice-sos/transcribe` validates MIME allowlist, base64 structure, and `10 MB` (`10 * 1024 * 1024` bytes) size cap, supporting English (`en`), Hindi (`hi`), and auto-detect (`auto`).
   - `/voice-sos/extract` combines deterministic rules (`intent_service`, `RiskClassifier`, regex landmark matcher) and LLM extraction when available, returning editable transcription, `suggested_category`, `situation_description`, `mentioned_location`, `suggested_urgency`, `is_gps_confirmed=False`, `requires_human_confirmation=True`, and `auto_dispatched=False`.

4. **Trusted Contacts & Persistent Check-In Timer (`/safe-contacts`, `/trusted-contacts/*`, `/check-in/*`):**
   - Contact management supports Add, Edit (`PATCH /trusted-contacts/{contact_id}`), Delete (`DELETE`), `relationship` (`ALLOWED_RELATIONSHIPS` via `normalize_relationship`), `priority` (`1..5` via `clamp_priority`), phone/email validation, 409 phone deduplication, verification (`POST /trusted-contacts/{contact_id}/verify` returning honest `NOT_CONFIGURED` unless manually confirmed), consent-gated `/trusted-contacts/notify`, and audit history (`GET /trusted-contacts/history/{user_id}`).
   - `checkin_service.py` + `checkin_routes.py` persist active timers in MongoDB `safety_checkins` (surviving logout/restart), enforce `consent_acknowledged=True`, separate `allow_contact_escalation` vs `allow_authority_escalation`, and expose `confirm-safe`, `extend`, and `cancel`. Background sweeper `_sweep_loop` in `main.py` invokes `process_due_checkins()`.

5. **Rapid Response Network & Admin Governance (`/responder`, `/authority/rapid-response`, `/admin`):**
   - `GET /responder/history` (`require_responder`) returns past dispatches without exposing victim PII.
   - `/authority/rapid-response` adds `emSeverityFilter` and `emDispFilter` filters plus `fmtDuration` helper displaying backend-computed `response_time_seconds` and `resolution_time_seconds`.
   - `/admin` adds user search (`?search=`), account suspension/reactivation (`PATCH /admin/users/{user_id}/status`), self-suspension protection, audit trail logging, and real non-demo platform counts (`active_incidents`, `resolved_incidents`, `approved_providers`, `active_responders`, `demo_cases_isolated`).

6. **Personalized Safety Plan (`/therapy/safety-plan`) & Isolated Demo Mode (`/demo`):**
   - Extended `SafetyPlanModel` and UI with `personal_safety_considerations`, `emergency_preparation`, `important_documents`, and `personal_notes` encrypted via AES-256-GCM at rest, plus user-controlled JSON export with privacy warning and verified government/NGO helplines fetched from `/therapy/resources`.
   - Implemented complete isolated `/demo` console with Guided Workflow tabs (SOS -> Dispatch -> Responder -> Resolve; Voice AI Extract -> Demo SOS; Demo Admin Provider Approve -> Demo Responder Activation; Sample Contacts, Safety Plan, Check-In & Audit Logs) plus One-Click Sandbox Reset.

---

## 3. Files Modified & Created

### Backend Modified (`haven/backend/`)
- `auth.py` — Added `_check_user_active(user_id, role)` in `get_current_user` so suspended accounts receive HTTP 403.
- `main.py` — Wired `checkin_routes` and `demo_routes`; wired `process_due_checkins()` into background `_sweep_loop`.
- `models/schemas.py` — Extended `TrustedContactModel` & `SafetyPlanModel`; added `TrustedContactEditModel`, `TrustedContactVerifyModel`, `TrustedContactNotifyModel`, `SafetyCheckinCreateModel`, `SafetyCheckinExtendModel`, `VoiceTranscribeModel`, `VoiceExtractModel`, `AdminUserStatusModel`.
- `routers/admin_routes.py` — Added user search, `PATCH /admin/users/{user_id}/status`, audit logs, and real non-demo metrics.
- `routers/cases_routes.py` — Enforced `{"is_demo": {"$ne": True}}` production query isolation and lifecycle/WS hooks.
- `routers/dispatch_routes.py` — Added `GET /responder/history` (RBAC-protected, zero victim PII).
- `routers/sos_routes.py` — Website SOS (`/sos/report`, `/sos/my-incidents`, `/sos/incidents/{case_id}`, `/cancel`) validation, idempotency, cancellation support.
- `routers/voice_routes.py` — Added contact edit/verify/history/notify endpoints, contact history recorder, and `/voice-sos/stt-status`, `/voice-sos/transcribe`, `/voice-sos/extract`.
- `services/contact_validation.py` — Added `ALLOWED_RELATIONSHIPS`, `normalize_relationship()`, `clamp_priority()`.
- `services/db.py` — Added `trusted_contact_history()`, `safety_checkins()`, `users()`, `demo_collection(name)`.
- `services/dispatch_service.py`, `services/lifecycle_service.py`, `services/notification_service.py` — Added `CANCELLED` lifecycle transition, response/resolution timing support, owner WebSocket update helpers.
- `diagnose_zero_providers.py`, `seed_demo_responders.py`, `test_broadcast_verification.py`, `test_complete_provider_lifecycle.py`, `test_haven_upgrade.py`, `test_location_freshness.py`, `test_provider_dispatch.py`, `test_rapid_response_network.py`, `test_rrn_authority_views.py` — Updated/repaired timezone-aware `datetime.now(timezone.utc)` imports & compatibility.

### Backend Created (`haven/backend/`)
- `routers/checkin_routes.py` — Persistent check-in HTTP API (`/check-in/*`).
- `routers/demo_routes.py` — Isolated Demo Sandbox HTTP API (`/demo/*`).
- `services/checkin_service.py` — MongoDB timer persistence and `process_due_checkins()` reminder/escalation scheduler.
- `services/demo_service.py` — `demo_*` workspace seeding, simulation workflow, and strict production isolation.
- `services/voice_ai_service.py` — Whisper STT client + rule/LLM emergency information extractor.
- `test_haven_v2_features.py` — 12 automated HAVEN V2 backend regression tests.

### Frontend Modified (`haven/frontend/`)
- `src/app/dashboard/page.tsx` — Real backend Safety Overview, Quick Actions, SOS/Tracking integration, `/safe-contacts` and `/demo` links.
- `src/app/home/page.tsx` — Added Demo Mode entry action (`demoModeBtn`).
- `src/app/voice-sos/page.tsx` — Integrated `VoiceAudioRecorderPanel` alongside passive safe-word listener and `/safe-contacts` link.
- `src/app/responder/page.tsx` — Wired Response History card from `GET /responder/history`.
- `src/app/authority/rapid-response/page.tsx` — Added severity & dispatch state filters and response/resolution duration display.
- `src/app/admin/page.tsx` — Added user search, account suspend/reactivate UI, and real non-demo platform stats.
- `src/app/therapy/safety-plan/page.tsx` — Added 4 guidance sections, JSON export with privacy notice, `/safe-contacts` link, live `/therapy/resources`.
- `src/components/PanicButton.tsx`, `src/hooks/useNotifications.ts`, `src/lib/dispatch.ts`, `src/locales/strings.ts`, `src/middleware.ts` — Protected `/safe-contacts` in Clerk middleware, added `AuthorityDispatchView` timing fields & `getResponderHistory()`, expanded `strings.ts` V2 UI keys.

### Frontend Created (`haven/frontend/`)
- `src/app/safe-contacts/page.tsx` — Trusted Contacts manager (Add/Edit/Delete/Verify/Notify/History) + Safety Check-In Timer page.
- `src/app/demo/page.tsx` — Guided 4-tab Interactive Demo Sandbox console.
- `src/components/DirectSOSForm.tsx` — Website SOS submission form with GPS + accuracy/timestamp, manual location, idempotency protection.
- `src/components/IncidentTracker.tsx` — Authorized user incident tracking + cancel + live WS refresh.
- `src/components/VoiceAudioRecorderPanel.tsx` — Whisper Voice AI recorder (`MediaRecorder`), playback, editable transcript, human-confirmed SOS submission.
- `test/havenV2Features.spec.mjs` — 21 automated HAVEN V2 frontend regression assertions.

*(Also generated runtime artifact `backend/test/ai_evaluation/results.json` from `run_eval.py --strict`, Next build cache `frontend/tsconfig.tsbuildinfo`, and existing untracked local workspace metadata/Android build outputs left untouched.)*

---

## 4. API Endpoints Added / Extended

- **SOS & Tracking:** `POST /sos/report`, `GET /sos/my-incidents`, `GET /sos/incidents/{case_id}`, `POST /sos/incidents/{case_id}/cancel`
- **Voice AI & Trusted Contacts:** `GET /voice-sos/stt-status`, `POST /voice-sos/transcribe`, `POST /voice-sos/extract`, `PATCH /trusted-contacts/{contact_id}`, `POST /trusted-contacts/{contact_id}/verify`, `POST /trusted-contacts/notify`, `GET /trusted-contacts/history/{user_id}`
- **Emergency Check-In:** `POST /check-in`, `GET /check-in/active`, `GET /check-in/history`, `POST /check-in/{checkin_id}/confirm-safe`, `POST /check-in/{checkin_id}/extend`, `POST /check-in/{checkin_id}/cancel`
- **RRN & Admin:** `GET /responder/history`, `PATCH /admin/users/{user_id}/status`, extended `GET /admin/users` (`?search=`) & `GET /admin/system-stats`
- **Isolated Demo Mode:** `GET /demo/state`, `POST /demo/reset`, `POST /demo/sos`, `POST /demo/voice-sos/analyze`, `POST /demo/dispatch/{case_id}`, `POST /demo/dispatch/{dispatch_id}/respond`, `POST /demo/admin/providers/{registration_id}/approve`

---

## 5. Database Changes (MongoDB)

- **New Production Collections:**
  - `trusted_contact_history` — Audit trail of contact additions, edits, verifications, deletions, and notifications scoped by `user_id`.
  - `safety_checkins` — Persistent timer schedules (`checkin_id`, `user_id`, `status`, `expires_at`, `reminder_at`, `consent_acknowledged`, `allow_contact_escalation`, `allow_authority_escalation`, location metadata).
- **Updated Production Collections / Schemas:**
  - `users` — Reads/writes `active` boolean flag enforced by `auth.py` `_check_user_active` on protected endpoints.
  - `trusted_contacts` — Added `relationship`, clamped `priority`, `verification_status`, `verified_at`.
  - `safety_plans` — Encrypted ciphertext payload expanded with `personal_safety_considerations`, `emergency_preparation`, `important_documents`, `personal_notes`.
  - `sos_cases` & `dispatch_requests` — Added `is_demo` exclusion filter and `CANCELLED` lifecycle state / `response_time_seconds` / `resolution_time_seconds`.
- **Isolated Demo Sandbox Collections (completely separate from production):**
  - `demo_cases`, `demo_dispatches`, `demo_responders`, `demo_contacts`, `demo_checkins`, `demo_provider_registrations`, `demo_safety_plans`, `demo_audit_logs`.

---

## 6. External Configuration Requirements

Verified against `backend/.env` and `frontend/.env.local` (key names checked; secret values never exposed):

- **Configured locally (`[SET]`):** `MONGO_ENDPOINT`, `GEMINI_API_KEY`, `GROQ_API_KEY` (powers `/voice-sos/transcribe` via Whisper `whisper-large-v3-turbo`), `CLOUDINARY_*`, `HF_API_KEY`, `JWT_SECRET`, `AUTHORITY_SECRET_KEY`, `EVIDENCE_ENCRYPTION_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`, `VAPID_*`, `REDIS_URL`, `REDIS_ENABLED`, `REDIS_REQUIRED_IN_PRODUCTION`, plus `CLERK_SECRET_KEY` and `NEXT_PUBLIC_*` Clerk/API keys in `frontend/.env.local`.
- **Missing / Unconfigured (`[NOT SET]`):**
  - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — Required for real outbound SMS delivery to trusted contacts and contact verification OTPs (`sms_service` currently returns `STATUS_NOT_CONFIGURED`).
  - `OPENAI_API_KEY` — Optional Whisper fallback (`whisper-1`); not needed while `GROQ_API_KEY` is configured.
  - `CLERK_ISSUER` / `CLERK_JWKS_URL` in `backend/.env` — Required in production (`STRICT_AUTH=true`) so FastAPI cryptographically verifies Clerk RS256 session tokens instead of rejecting them.
- **Service Reachability Note:** Redis (`REDIS_URL`) is configured in `.env`, but no local Redis broker was reachable during execution; `rate_limiter.py` fell back to single-process in-memory rate limiting.

---

## 7. Tests Executed & Actual Results

All checks below ran cleanly after the final code edit (except `live Playwright mobile UI`, marked `NOT VERIFIED`):

- **Backend AST `timezone` check:** `MISSING_TZ_IMPORT: []`, `SKIPPED: []` -> `PASS` (exit 0)
- **Full Backend Pytest (`pytest --tb=short -q`):** **`736 passed, 3 warnings in 93.69s (0:01:33)`**, `0 failed`, `0 skipped` -> `PASS`
- **Backend Safety/Contract Validators:**
  - `validate_ai_contract.py`: `215` passed -> `PASS`
  - `validate_anomaly_signal.py`: `37` passed -> `PASS`
  - `validate_contacts.py`: `35 passed, 0 failed` -> `PASS`
  - `validate_legal_corpus.py`: `85 passed, 0 failed` -> `PASS`
  - `validate_legal_normalization.py`: `90 passed, 0 failed` -> `PASS`
  - `validate_localization.py`: `3572` checks passed -> `PASS`
  - `validate_mental_health.py`: `208` passed -> `PASS`
  - `validate_prompt_registry.py`: `31` passed -> `PASS`
  - `validate_risk_rules.py`: `47` passed -> `PASS`
  - `test/ai_evaluation/run_eval.py --strict`: `100.00%` crisis, severe, and emergency-escalation recall -> `PASS`
  - Pre-existing untouched validators: `validate_profile_search.py` (`53 passed, 1 failed` — `degraded False when semantic backend simply absent`) -> `FAIL`; `validate_search_consolidation.py` (`SyntaxError` U+FEFF BOM on `routers/culprit_routes.py`) -> `FAIL`
- **Frontend TypeScript, Production Build & Node Specs:**
  - `npx tsc --noEmit`: exit 0 -> `PASS`
  - `npm run build`: exit 0, `21/21` Next.js routes built (`Middleware 78.5 kB`) -> `PASS`
  - All 9 Node `.mjs` spec suites: `236 passed, 0 failed` total (`ariaVoice` 66, `contactsPersistence` 12, `dashboardIdentity` 20, `dirForm.xss.security` 14, `havenV2Features` 21, `locationFreshness` 30, `offlineQueue.security` 12, `rapidResponseConsistency` 23, `voiceSosStatus` 38) -> `PASS`
- **Live `TestClient` App & Demo E2E Smoke:** Verified HTTP 200 on `/health`, `/voice-sos/stt-status`, `/therapy/resources`, and full `/demo/state` -> `/demo/voice-sos/analyze` -> `/demo/sos` -> `/demo/dispatch/{case_id}` -> `/demo/dispatch/{dispatch_id}/respond` (`accept` & `resolve`) -> `/demo/admin/providers/DEMO-REG-001/approve` -> `/demo/reset` -> `PASS`

---

## 8. Known Limitations

1. Outbound SMS delivery and OTP phone verification for trusted contacts are `BLOCKED BY EXTERNAL CONFIGURATION` until Twilio credentials are added.
2. Distributed multi-worker Redis rate limiting falls back locally because Redis was unreachable; production enforces `REDIS_REQUIRED_IN_PRODUCTION=true` (returns 503 if unreachable).
3. Live Groq Whisper audio transcription (`POST /voice-sos/transcribe`) against `api.groq.com` with captured browser mic audio bytes was tested via mocked unit tests and live `/voice-sos/stt-status` config inspection, not a live external network audio upload (`NOT VERIFIED`).
4. Physical Android/iOS mobile viewport & Web Speech / `MediaRecorder` permission flows require manual interactive browser testing (`NOT VERIFIED`).
5. Regional UI languages `kn`, `ml`, `pa`, `or`, `as` remain English fallback (`0/179`); `bn`, `mr`, `ta`, `te`, `gu` remain `80/179`.
6. Two pre-existing untouched static/semantic validators (`validate_profile_search.py`, `validate_search_consolidation.py`) fail as noted above.

---

## 9. Manual Actions Required

1. Populate `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` in Render/deployment environment if real SMS emergency alerts and contact OTP verification are needed.
2. Configure `CLERK_ISSUER` / `CLERK_JWKS_URL` in production backend env so Clerk session JWTs are cryptographically verified when `STRICT_AUTH=true`.
3. Provision reachable Redis (`REDIS_URL`) before running multi-worker production uvicorn/gunicorn with `REDIS_REQUIRED_IN_PRODUCTION=true`.
4. Perform interactive browser walkthrough across `/dashboard`, `/safe-contacts`, `/voice-sos`, `/therapy/safety-plan`, and `/demo` on desktop and mobile before presentation/deployment.
