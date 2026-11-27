# HAVEN V2 — Security & Privacy Audit

**Project:** HAVEN — Power for Women  
**Audit Date:** 2026-11-26  
**Methodology:** Code inspection (`auth.py`, `main.py`, `rate_limiter.py`, routers/services/frontend), automated security regression suites (`pytest` + `*.security.mjs`), and environment key verification (zero secret values logged).

---

## 1. Security Control Matrix

| Control Area | Verification Evidence | Status |
|---|---|---|
| Role & JWT Validation (`auth.py`) | Internal HS256 issuer `"haven-backend"` checked; unverifiable tokens in dev forced to `"user"` (never elevated); production sets `STRICT_AUTH=true` by default (`test_haven_upgrade.py`, `test_shake_sos_auth.py`). | `PASS` (code); `BLOCKED BY EXTERNAL CONFIGURATION` (Clerk JWKS unset in `.env`) |
| Account Suspension Enforcement (`_check_user_active`) | `get_current_user` checks Mongo `users.active is False` and raises HTTP 403 (`test_admin_suspend_and_reactivate_enforced_by_auth`). | `PASS` (note: `get_optional_user` does not call `_check_user_active`) |
| User Ownership & IDOR Prevention | Contacts (`add`/`patch`/`delete`/`verify`/`notify`/`history`), `/sos/*`, `/check-in/*`, and `/therapy/safety-plan` derive `user_id` strictly from `current_user.user_id` (`validate_contacts.py`: 35 passed, `test_haven_v2_features.py`). | `PASS` |
| RBAC on Sensitive Portals | `/admin/*` uses `require_admin`; `/authority/*` & `/dispatch` creation use `require_authority`; `/responder/history` uses `require_responder` and strips victim PII. | `PASS` |
| Responder Location Freshness & Privacy | Candidate responder coords withheld from victim views; `300s` max age enforced (`test_location_freshness.py`, `locationFreshness.spec.mjs`: 30 passed, `rapidResponseConsistency.spec.mjs`: 23 passed). | `PASS` |
| Encryption at Rest | Safety plans, therapeutic journals/notes, and evidence payloads encrypted with AES-256-GCM (`encrypt_evidence_payload` using 96-bit nonces in `auth.py`); safe words hashed with PBKDF2-HMAC-SHA256 (`100,000` iterations). | `PASS` |
| Demo Mode Production Isolation | All `/demo/*` operations touch strictly `demo_*` collections; production `/cases` filters `{"is_demo": {"$ne": True}}`; zero real SMS/WS calls; no hardcoded admin/responder passwords or auth bypass in frontend `/demo`. | `PASS` |
| Consent & Non-Fabrication Controls | Check-in timers require `consent_acknowledged=True`; Voice AI sets `is_gps_confirmed=False`, `requires_human_confirmation=True`, `auto_dispatched=False`; STT & SMS report unavailable rather than faking success. | `PASS` |
| Voice Audio Upload Limits & Validation | `/voice-sos/transcribe` validates MIME allowlist (`webm`, `ogg`, `mp4`, `m4a`, `mpeg`, `wav`, `aac`), valid base64, and `10 MB` cap; `VoiceAudioRecorderPanel` does not expose raw audio publicly. | `PASS` |
| Request Body Ceiling & XSS Protections | ASGI `BodySizeLimitMiddleware` enforces `50 MB` (`52428800` bytes) streaming limit (`main.py`); `dirForm.xss.security.mjs` (`14 passed`) & `offlineQueue.security.mjs` (`12 passed`) verify HTML escaping & encrypted IndexedDB queue. | `PASS` |
| API Rate Limiting (`rate_limiter.py`) | Atomic Lua sorted-set sliding window in Redis when reachable; local fallback logged cleanly when Redis is down (`ConnectionError`); production defaults `REDIS_REQUIRED_IN_PRODUCTION=true` (fail closed 503). | `PARTIALLY IMPLEMENTED` (`NOT VERIFIED` against live Redis daemon) |
| WebSocket Authentication & Role Scoping | `/ws/track/{event_id}` and `/ws/dispatch/{dispatch_id}` verified across existing RRN/WS regression tests in full 736-test suite. | `PASS` |

---

## 2. Specific Security Findings & Gaps Identified

1. **`CLERK_ISSUER` / `CLERK_JWKS_URL` Missing in Backend Environment (`BLOCKED BY EXTERNAL CONFIGURATION` for Production):**
   - Observed in `auth.py` (lines 82–90) and `backend/.env`: neither `CLERK_ISSUER` nor `CLERK_JWKS_URL` is configured locally.
   - Because `STRICT_AUTH` defaults to `False` in `development`, Clerk session JWTs pass with role forced to `"user"` (safe against privilege escalation).
   - **Action Required:** In production (`ENVIRONMENT=production`), `STRICT_AUTH` defaults to `True`, which will reject Clerk RS256 JWTs with HTTP 401 (`_auth_error("unverifiable_strict")`) unless `CLERK_ISSUER` or `CLERK_JWKS_URL` is set on Render.
2. **Optional-Auth Endpoints Do Not Enforce Suspension Check (`PARTIALLY IMPLEMENTED` / Low Severity):**
   - `get_current_user` calls `_check_user_active(uid, role)` and blocks suspended accounts (`403`). `get_optional_user` (`auth.py` lines 316–333) returns an `AuthUser` without calling `_check_user_active`. Anonymous/public support chat paths should remain reachable for crisis help, while stateful user writes all use `get_current_user`.
3. **Redis Offline in Local Dev (`NOT VERIFIED` Live Redis Enforcement):**
   - Runtime logs showed `WARNING:haven_backend:Rate limiter: Redis unavailable (ConnectionError); using in-memory fallback (single process only)`. Rate-limit fail-closed behavior (`REDIS_REQUIRED_IN_PRODUCTION=true`) must be verified against a live Redis service before scaling beyond one worker.
4. **Twilio Unconfigured (`BLOCKED BY EXTERNAL CONFIGURATION`):**
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` are absent from `backend/.env`; SMS notification and contact OTP verification cannot dispatch externally. Phone masking (`_mask_phone`) and explicit error reporting remain active in `sms_service.py`.
5. **Sensitive Logging & Secret Hygiene:**
   - Error responses from `auth.py` return static generic text (`"Invalid or expired authentication token"`); rate-limit keys hash Bearer headers with SHA-256 (`rate_limiter.py`); voice `onerror` logs only error codes (`voiceSosStatus.spec.mjs`: 38 passed); no `.env` values or credentials appear in frontend source (`havenV2Features.spec.mjs`).

---

## 3. Compliance Summary Against Deliverable Checklist

- **Features Implemented:** `_check_user_active`, user status suspension/reactivation with audit trail, contact consent/dedup/history, check-in consent separation, Demo sandbox isolation, AES-256-GCM expanded safety plan storage, MIME/size-checked Whisper upload.
- **Files Modified & New API Endpoints:** See `HAVEN_V2_IMPLEMENTATION_REPORT.md` Sections 3–4 (`auth.py`, `main.py`, `admin_routes.py`, `cases_routes.py`, `voice_routes.py`, `checkin_routes.py`, `demo_routes.py`, `frontend/src/middleware.ts`).
- **Database Changes:** `users.active` enforcement, `trusted_contact_history`, `safety_checkins`, `demo_*` isolation collections, `{"is_demo": {"$ne": True}}` case filters.
- **External Config Requirements:** Set `CLERK_ISSUER` / `CLERK_JWKS_URL`, reachable `REDIS_URL`, and optional Twilio env vars; verify production `JWT_SECRET`, `AUTHORITY_SECRET_KEY`, and `EVIDENCE_ENCRYPTION_KEY` do not match `_INSECURE_JWT_SECRETS` / defaults.
- **Tests Executed & Actual Results:** Full backend suite `736 passed, 0 failed` (`93.69s`), `validate_contacts.py` `35 passed, 0 failed`, `dirForm.xss.security.mjs` `14 passed`, `offlineQueue.security.mjs` `12 passed`, `voiceSosStatus.spec.mjs` `38 passed`, `locationFreshness.spec.mjs` `30 passed`, `havenV2Features.spec.mjs` `21 passed`; `validate_profile_search.py` (`53 passed, 1 failed`) and `validate_search_consolidation.py` (BOM `SyntaxError`) failed cleanly as pre-existing untouched checks.
- **Known Limitations & Manual Actions:** Configure `CLERK_ISSUER` + live Redis + Twilio on production hosting; perform post-deploy smoke test confirming strict Clerk token verification returns `200` with valid Clerk session and `401` on tampered tokens.
