# HAVEN V2 — Interactive Demo & Presentation Guide

**Project:** HAVEN — Power for Women (College Mini-Project & Live Sandbox Demonstration)  
**Isolated Demo URL (Frontend):** `http://localhost:3000/demo` (also linked from `/` -> `/home` and `/dashboard`)  
**Demo Backend Prefix:** `/demo/*` (Strictly isolated inside `demo_*` MongoDB collections)  
**Isolation Guarantee:** `PASS` — Verified via `TestAdminSafetyPlanAndDemoIsolation::test_demo_mode_workflows_and_strict_production_isolation` and live `TestClient` E2E walkthrough (`POST /demo/reset` cleans state between runs).

---

## 1. Local Startup Commands (Safe Isolated Testing)

1. **Start Backend (`haven/backend/`):**
   ```powershell
   cd c:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven\backend
   .\.venv312\Scripts\uvicorn main:app --host 127.0.0.1 --port 8000
   ```
   Confirm `GET http://127.0.0.1:8000/health` -> `200 OK` and `GET http://127.0.0.1:8000/voice-sos/stt-status` -> `200 OK` (`available: true`, `provider: groq_whisper`).
2. **Start Frontend (`haven/frontend/`):**
   ```powershell
   cd c:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven\frontend
   npm run dev
   ```
3. **Open Isolated Demo Console:** Navigate to `/demo` (no production secrets embedded; zero auth bypass; uses strictly isolated `/demo/*` endpoints).

---

## 2. Live Demonstration Walkthrough (4 Guided Tabs)

### Tab 1: Complete SOS -> Authority -> Responder -> Resolution Flow (`sos_flow`)
- **Features Demonstrated:** Category selection, manual/GPS description, incident creation, simulated authority dispatch, responder accept -> arrive -> resolve lifecycle, real-time timeline transitions.
- **Step-by-step Action:**
  1. Keep or edit sample SOS details (e.g., category `stalking`, location `"28.6328, 77.2197 (Demo Metro Gate 2)"`) and submit (`POST /demo/sos`) -> generates `DEMO-CASE-...` with `"is_demo": true, "simulation": true`.
  2. Click **Dispatch Responder** as Demo Authority (`Inspector Priya (Demo Dispatcher)`, `DEMO-AUTH-PRIYA`) -> `POST /demo/dispatch/{case_id}` creates `DEMO-DISP-...`.
  3. Switch actions as **Demo Unit Alpha** (`DEMO-RESP-101`): **Accept** -> **Resolve** (`POST /demo/dispatch/{dispatch_id}/respond`) and verify live status progression (`ACCEPTED` -> `RESOLVED`) and `DEMO_AUDIT_LOG` timeline entries without touching production `sos_cases` or `responders`.

### Tab 2: Voice SOS AI Triage Simulation (`voice_flow`)
- **Features Demonstrated:** Bilingual sample scenario playback (browser speech synthesis for English & Hindi samples), editable transcript review, AI information extraction, explicit `is_gps_confirmed: false` & `auto_dispatched: false` safeguards.
- **Step-by-step Action:**
  1. Select **"English Sample — Stalking Near Metro"** or **"Hindi Sample — पीछा और असुरक्षित स्थिति"** (`GET /demo/state`).
  2. Click **Analyze Transcript** (`POST /demo/voice-sos/analyze`) -> displays `suggested_category` (`stalking`), `situation_description`, `mentioned_location` (`is_gps_confirmed: false`), `suggested_urgency` + disclaimer (`requires_human_confirmation: true`, `auto_dispatched: false`).
  3. Edit text if desired and confirm creating an isolated demo SOS (`POST /demo/sos`).

### Tab 3: Admin Provider Approval & Responder Activation (`admin_flow`)
- **Features Demonstrated:** Admin governance review workflow inside sandbox without real responder onboarding tokens.
- **Step-by-step Action:**
  1. Review pending demo registration `DEMO-REG-001` (`Sakhi Mobile Support Van (Demo)`, `PENDING_REVIEW`).
  2. Click **Approve Provider** (`POST /demo/admin/providers/DEMO-REG-001/approve`) -> activates `DEMO-RESP-102` (`Demo Unit Sakhi-2 (Crisis NGO)`) inside `demo_responders` only.

### Tab 4: Pre-Seeded Sample Data & Reset (`samples`)
- **Sample Records Inspected (`GET /demo/state`):**
  - Demo Contacts: `DEMO-CTC-1` (`Meera Sharma (Demo Sister)`), `DEMO-CTC-2` (`Aarti Verma (Demo Neighbor)`) — synthetic `.invalid` / `XXX` numbers.
  - Historical Case: `DEMO-CASE-SEED-001` (`RESOLVED`).
  - Sample Check-In: `DEMO-CHK-001` (`Evening Cab Ride Home (Sample)`, `CONFIRMED_SAFE`).
  - Sample Safety Plan: `DEMO-PLAN-001` (`112`, `181`, `1091`).
  - Audit Log: `DEMO-AUD-...` trace of every demo state transition.
- **Reset Between Presentations:** Click **Reset Demo Workspace** (`POST /demo/reset`) to wipe temporary cases/dispatches and re-seed clean initial demo fixtures.

---

## 3. Authenticated User Feature Showcase (Isolated Non-Emergency Testing)

When demonstrating logged-in features (using a test Clerk account on localhost — never delete production data or trigger real emergency partners):
- **`/dashboard`:** Shows real Safety Overview (Trusted Contacts count, Active Check-In banner, Safety Plan status, Recent Incidents), Quick Actions, `DirectSOSForm`, and `IncidentTracker`.
- **`/safe-contacts`:** Demonstrates Add/Edit/Remove Trusted Contact, Relationship + Priority (1–5), Verification status (shows honest `NOT_CONFIGURED` until Twilio creds are added; manual confirm supported), Consent-gated Check-In Timer (`POST /check-in`, Extend, Confirm Safe, Cancel).
- **`/voice-sos`:** Demonstrates browser `MediaRecorder` Start/Pause/Stop + duration timer + audio playback + Whisper `/voice-sos/transcribe` (requires microphone permission and configured `GROQ_API_KEY`) + editable transcript + AI extract review.
- **`/therapy/safety-plan`:** Shows 4 new preparation/document sections, AES-256-GCM save, JSON export with privacy notice, and live `/therapy/resources` Indian helplines (`112`, Tele-MANAS `14416`, KIRAN `1800-599-0019`, iCALL `9152987821`, Vandrevala, AASRA).

---

## 4. Implementation, Testing & Config Reference

| Deliverable Item | Verified Summary | Status |
|---|---|---|
| Demo Isolation & Workflows | Strictly isolated `demo_*` collections (`services/demo_service.py`, `routers/demo_routes.py`, `frontend/src/app/demo/page.tsx`) | `PASS` |
| Files Modified / Created | Demo backend (`demo_service.py`, `demo_routes.py`, `db.py`) & frontend (`demo/page.tsx`, `home/page.tsx`, `dashboard/page.tsx`, `havenV2Features.spec.mjs`) — see `HAVEN_V2_IMPLEMENTATION_REPORT.md` Section 3 | `PASS` |
| API Endpoints & DB Changes | `GET /demo/state`, `POST /demo/{reset,sos,voice-sos/analyze,dispatch/{case_id},dispatch/{dispatch_id}/respond,admin/providers/{registration_id}/approve}`; 8 `demo_*` MongoDB collections + `is_demo` exclusion in production routes | `PASS` |
| Tests Executed & Actual Results | Full `pytest` (`736 passed, 0 failed`), live `TestClient` `/demo/*` E2E cycle (`200 OK` across state/voice/sos/dispatch/accept/resolve/approve/reset), `havenV2Features.spec.mjs` (`21 passed`), `npm run build` (`21/21` routes) | `PASS` |
| Live Browser Demo UI & Mobile Presentation Check | Interactive Chromium/mobile screen inspection & browser speech synthesis audio output | `NOT VERIFIED` |
| Outbound SMS Demo Notifications | Real SMS delivery during check-in/contact notify tests | `BLOCKED BY EXTERNAL CONFIGURATION` (Twilio unset) |

### External Config & Manual Actions Before Live Jury Demo
- Ensure `backend/.env` has `MONGO_ENDPOINT` reachable and `GROQ_API_KEY` set (already verified `[SET]` locally) if demonstrating live Whisper transcription.
- Click **Reset Demo Workspace** (`POST /demo/reset`) right before presenting so only the clean seeded incident/dispatch state appears.
- Clarify to evaluators that Twilio SMS is deliberately disabled/unconfigured so no real SMS alerts fire during live demos, while Whisper STT (`groq_whisper`), MongoDB persistence, AI extraction, and role isolation operate live.
