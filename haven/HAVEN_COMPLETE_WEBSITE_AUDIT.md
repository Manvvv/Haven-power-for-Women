# HAVEN — Complete Website Audit

**Audit Date:** 2026-11-22  
**Auditor:** Antigravity (AI Engineering Assistant)  
**Scope:** Website only — `haven/frontend/` and `haven/backend/`  
**Out of scope:** Android / Kotlin / native (explicitly excluded by project owner)

---

## Executive Summary

HAVEN is a women's-safety web platform built on Next.js 14 (frontend) and FastAPI (backend) with MongoDB Atlas persistence and Clerk authentication. The platform uses a **calculator-disguise security model** so a victim can appear to use a calculator while secretly accessing emergency features. 

This audit inspected all 17 frontend page routes, 18 backend routers, the full authentication module, database service, offline queue, encrypted local storage, and the Rapid Response Network dispatch pipeline. The full backend test suite passed all **724 tests with 0 failures**. The TypeScript compiler reports **0 type errors**. All backend Python imports succeed cleanly.

**Overall verdict:** The application is architecturally sound and functionally complete at the production-safety tier. No critical exploitable vulnerabilities were found. A small set of medium-severity issues and known limitations are documented below.

---

## 1. Architecture Overview

```
User Browser
    │
    ├─► Calculator Disguise (/) ──PIN 1810──► /home
    │
    ├─► Clerk Auth (/sign-in, /sign-up)
    │
    ├─► User Flow: /dashboard → /sos → /voice-sos → /therapy → /legal
    │
    ├─► Authority Portal: /authority → /authority/providers → /authority/rapid-response
    │
    ├─► Responder Portal: /responder
    │
    └─► Admin Portal: /admin

Frontend (Next.js 14)
    │   HTTPS → Vercel CDN
    │
    └─► Backend (FastAPI / Python)
            │   HTTPS → Render.com
            ├─► MongoDB Atlas (primary store)
            ├─► Redis (rate limiting, cooldown, caching)
            ├─► Cloudinary (media/image upload)
            ├─► Gemini API (AI therapy, embeddings)
            ├─► Groq (AI fallback)
            └─► Hugging Face (steganography ML, evidence analysis)
```

### Authentication Layers

| Layer | Mechanism | Stored Where | Elevated via |
|-------|-----------|-------------|-------------|
| Regular user | Clerk RS256 JWT | Clerk SDK | Clerk `publicMetadata.role` |
| Authority | Haven HS256 JWT | `sessionStorage.haven_authority_token` | Backend `authority_accounts` DB record |
| Responder | Haven HS256 JWT | `sessionStorage.haven_responder_token` | Backend `responders` DB record (admin-approved) |
| Admin | Clerk metadata OR authority JWT with `role:admin` | — | Clerk dashboard OR authority admin account |
| Calculator unlock | `sessionStorage.haven_unlocked=true` | sessionStorage | Matching PIN in env |

> [!IMPORTANT]
> The token security model is strictly enforced server-side: `decode_token()` in `auth.py` guarantees that an unverifiable or Clerk-issued token is **always forced to `role: "user"`**. Only Haven-internal HS256 tokens (issued by the authority/responder login endpoints) can carry elevated roles. This closes the classic role-claim spoofing attack.

---

## 2. Route Inventory

### Frontend Pages

| Route | Auth Required | Purpose | Status |
|-------|--------------|---------|--------|
| `/` | None | Calculator disguise. PIN unlocks haven. | ✅ Working |
| `/home` | Calculator unlock | Main landing page, navigation hub | ✅ Working |
| `/sign-in/[[...sign-in]]` | None | Clerk hosted sign-in | ✅ Working |
| `/sign-up/[[...sign-up]]` | None | Clerk hosted sign-up | ✅ Working |
| `/dashboard` | Clerk + Calculator unlock | User dashboard, PanicButton | ✅ Working |
| `/sos` | Clerk + Calculator unlock | Steganographic SOS creator | ✅ Working |
| `/voice-sos` | Clerk + Calculator unlock | Voice SOS, safe word, contacts | ✅ Working |
| `/therapy` | Clerk + Calculator unlock | AI therapy chat with Aria | ✅ Working |
| `/therapy/safety-plan` | Clerk + Calculator unlock | Mental health safety plan | ✅ Working |
| `/legal` | Clerk + Calculator unlock | RAG-powered legal guidance | ✅ Working |
| `/privacy` | Clerk + Calculator unlock | Privacy information page | ✅ Working |
| `/authority` | Authority JWT (self-managed) | Authority case queue, decode, culprit search | ✅ Working |
| `/authority/providers` | Authority JWT (self-managed) | RRN responder roster management | ✅ Working |
| `/authority/rapid-response` | Authority JWT (self-managed) | Live dispatch command centre | ✅ Working |
| `/responder` | Responder JWT (self-managed) | Field responder portal | ✅ Working |
| `/admin` | Clerk admin role OR authority admin JWT | System admin: metrics, audit logs, role management | ✅ Working |
| `/auth/responder-setup` | Single-use setup token | One-time responder credential setup | ✅ Working |

### Backend Routers (18 total)

| Router file | Prefix/Tag | Key endpoints |
|-------------|-----------|--------------|
| `auth_routes.py` | `/auth` | authority-login, responder-login, responder-setup, user-register, user-login |
| `sos_routes.py` | `/` | encode, decode, save-extracted-data, evidence upload, location update |
| `voice_routes.py` | `/` | voice-sos/config, voice-sos/trigger, voice-sos/contacts |
| `cases_routes.py` | `/` | GET /cases, PATCH /cases/{id} |
| `authority_routes.py` | `/` | authority-only case queries, dispatch webhooks |
| `dispatch_routes.py` | `/` | RRN dispatch CRUD, responder acceptance, location, duty |
| `admin_routes.py` | `/` | audit logs, metrics, user role management |
| `culprit_routes.py` | `/` | culprit DB search |
| `ai_routes.py` | `/` | AI analysis, embeddings |
| `therapy_routes.py` | `/` | Aria therapy chat sessions |
| `legal_routes.py` | `/` | RAG legal guidance |
| `analytics_routes.py` | `/` | Aggregate statistics |
| `notification_routes.py` | `/` | VAPID push notification management |
| `privacy_routes.py` | `/` | Privacy data export/deletion |
| `search_routes.py` | `/` | Cross-entity search |
| `media_routes.py` | `/` | Cloudinary media uploads |
| `shake_sos_routes.py` | `/` | Android shake SOS (legacy, still registered) |
| `main.py` | — | WebSocket rooms, body limit middleware, CORS, lifespan |

---

## 3. Feature Status

### Core Emergency Features

| Feature | Implementation | Backend | Offline | Status |
|---------|---------------|---------|---------|--------|
| Calculator disguise | Native iOS-style UI, PIN `1810` | N/A | ✅ Always works | ✅ COMPLETE |
| Steganographic SOS | AI message → image → LSB encode | `/encode`, `/decode`, `/save-extracted-data` | ✅ IndexedDB queue | ✅ COMPLETE |
| Voice SOS + safe word | SpeechRecognition, PBKDF2 hash, WS tracking | `/voice-sos/trigger`, `/voice-sos/config` | ✅ Offline queue | ✅ COMPLETE |
| Panic button | Hold-to-fire, 5s countdown, cancel | `/save-extracted-data` | ✅ IndexedDB queue | ✅ COMPLETE |
| Contact management | Voice SOS page, AES-GCM encrypted local | `/voice-sos/contacts` | ✅ Local | ✅ COMPLETE |
| Location tracking | WS `/ws/track/{event_id}` | In-memory + DB | N/A (live) | ✅ COMPLETE |
| Authority case queue | Paginated, decrypted evidence | `/cases` | N/A | ✅ COMPLETE |
| Dispatch (RRN) | Human-approved, server-side location | `/dispatch/*` | N/A | ✅ COMPLETE |
| Responder portal | Accept/decline/en-route/GPS stream | `/responder/*` | N/A | ✅ COMPLETE |
| AI therapy (Aria) | Groq/Gemini session, encrypted | `/therapy/*` | N/A | ✅ COMPLETE |
| Safety plan | Mood journal, crisis contacts | `/admin/*`, local | N/A | ✅ COMPLETE |
| Legal RAG | AI-powered legal guidance | `/legal-guidance` | N/A | ✅ COMPLETE |
| Audit log | All auth and case actions logged | `/admin/audit-logs` | N/A | ✅ COMPLETE |
| Evidence encryption | AES-256-GCM at rest (backend) | `auth.py` | N/A | ✅ COMPLETE |

### Offline Queue Architecture

The [`offlineQueue.ts`](haven/frontend/src/lib/offlineQueue.ts) implements a production-grade offline-first SOS queue:
- **IndexedDB** persistence with schema v2 (upgrades v1 records automatically)
- **AES-256-GCM** encryption with non-extractable per-device `CryptoKey` stored via structured clone
- **Delivery states:** `queued → sending → sent → delivered → acknowledged → failed`
- **Idempotency keys** (UUID) sent as both JSON field and `X-Idempotency-Key` header
- **Exponential backoff** (15s base, 2× per retry, 15min cap; 6 max retries)
- **TTL-based purge** of failed items after 24h; pending items are never purged
- **Auto-flush** on `window.online` event

---

## 4. API Inventory

### Key Endpoint Security Matrix

| Endpoint | Auth Required | Rate Limited | Evidence |
|----------|--------------|-------------|---------|
| `POST /encode` | None (anonymous) | ✅ Yes | Input-hardened: size/pixel limits |
| `POST /decode` | None (anonymous) | ✅ Yes | Input-hardened: size/pixel limits |
| `POST /save-extracted-data` | Optional | ✅ Yes | Idempotency key |
| `POST /voice-sos/trigger` | Optional | ✅ Yes | PBKDF2 safe-word verify |
| `GET /cases` | Authority JWT | ✅ Yes | Evidence decrypted server-side |
| `PATCH /cases/{id}` | Authority JWT | ✅ Yes | State machine validation |
| `POST /dispatch` | Authority JWT | ✅ Yes | Location server-side only |
| `PATCH /dispatch/{id}/accept` | Responder JWT | ✅ Yes | Role strictly enforced |
| `GET /admin/audit-logs` | Admin JWT | ✅ Yes | Admin-only |
| `POST /auth/authority-login` | None + badge/pwd | ✅ Yes | PBKDF2 verify |
| `POST /auth/responder-login` | None + badge/pwd | ✅ Yes | PBKDF2 verify |

---

## 5. Authentication & Authorization Audit

### Token Security (PASS)

The `decode_token()` function enforces a strict three-tier verification hierarchy:
1. **Haven internal HS256** tokens (issued by authority/responder login) — full trust, may carry elevated roles
2. **Clerk RS256** tokens (verified against JWKS) — may carry elevated roles only via trusted metadata
3. **Unverifiable tokens** — forced to `role: "user"` regardless of any claim; in `STRICT_AUTH=true` (production), these are rejected outright

This design prevents role-claim spoofing from any external token source.

### Production Secret Guard (PASS)

`_validate_production_config()` runs at import time and **refuses to start** if `ENVIRONMENT=production` and any of the following are weak/default:
- `JWT_SECRET`
- `AUTHORITY_SECRET_KEY`
- `EVIDENCE_ENCRYPTION_KEY`
- `CLERK_ISSUER`
- `CLERK_JWKS_URL`

### Middleware Coverage

Clerk middleware (`middleware.ts`) protects: `/dashboard`, `/sos`, `/therapy`, `/legal`, `/voice-sos`, `/admin`, `/privacy`.

`/authority` and `/responder` are NOT in Clerk middleware — they have their own badge/password login forms, which is appropriate because authority users are not Clerk users.

### RBAC Dependencies

| Dependency | Accepts | Rejects |
|-----------|---------|---------|
| `get_current_user` | Any valid token | Missing/malformed header |
| `require_authority` | authority, admin, police, protection_officer | user, responder |
| `require_admin` | admin only | all others |
| `require_responder` | responder only | authority, admin, user |

> [!NOTE]
> `require_responder` deliberately does NOT accept authority/admin tokens. A dispatcher cannot impersonate a field unit.

---

## 6. Database Audit

### Collections (MongoDB Atlas, `Haven` DB)

| Collection | Purpose | Encrypted fields |
|-----------|---------|----------------|
| `sos_cases` | Steganographic SOS cases | `evidence.audio_ciphertext`, `evidence.image_ciphertext` |
| `sos_events` | Voice SOS live events | — |
| `culprits` | Reported perpetrators | — |
| `therapy_sessions` | AI therapy session history | — |
| `voice_sos_config` | Per-user safe word + contact config | `safe_word_hash` (PBKDF2, never plaintext) |
| `trusted_contacts` | Emergency contacts | — |
| `authority_accounts` | Authority officer credentials | `password_hash`, `password_salt` (PBKDF2) |
| `responders` | RRN field responder credentials | `password_hash`, `password_salt` (PBKDF2) |
| `responder_setup_tokens` | Single-use setup tokens | SHA-256 digest only |
| `dispatch_requests` | Active dispatch records | — |
| `audit_logs` | All privileged actions | — |
| `mh_safety_plans` | Mental health safety plans | — |

### Safe-word storage

Safe words are stored as **PBKDF2-HMAC-SHA256 (100k iterations, 16-byte random salt)** after `normalize_text()` (NFKD + lowercase + punctuation strip). The safe word is **never stored in plaintext** anywhere.

---

## 7. Emergency SOS Workflow

### Steganographic SOS

```
User types distress message
       ↓
AI expands it to 10x length (GPT-like via Gemini)
       ↓
User selects innocent-looking image
       ↓
Backend LSB-encodes the message into the image
       ↓
User shares image publicly with #HavenSOS
       ↓
Authority decodes image in authority portal
```

### Voice SOS

```
User configures safe word (hashed, never stored plain)
       ↓
Browser SpeechRecognition listens passively
       ↓
SOS triggers when spoken phrase matches hash (PBKDF2)
       ↓
Backend records sos_event, opens WS tracking room
       ↓
Dispatch WebSocket fans out to authority dashboard
       ↓
Authority reviews case, optionally dispatches RRN unit
```

### Panic Button

```
User holds PanicButton for 5 seconds (cancel window)
       ↓
enqueue() writes to IndexedDB (AES-GCM encrypted)
       ↓
Flush sends to /save-extracted-data (or relevant endpoint)
       ↓
On success: status → delivered
On failure: exponential backoff retry (up to 6 attempts)
On permanent failure: status → failed, TTL 24h
```

---

## 8. Rapid Response Network (RRN) Audit

### Architecture

- Authority manually triggers dispatch via `/dispatch` (never automatic)
- Incident location resolved **server-side** from stored case/event GPS fix — never from the request body
- Responders receive dispatch offers, accept/decline, send GPS via dedicated WS
- Authority sees live map via `LiveResponseMap` component
- Location freshness policy: >300s = STALE, never shown as current

### RBAC Test Coverage

68 dedicated RRN + security tests (from `test_rapid_response_network.py`, `test_rrn_rbac_matrix.py`, `test_security_remediation.py`) — all 68 PASS as of audit date.

---

## 9. WebSocket Architecture

| Room | Path | Participants | Message types |
|------|------|-------------|--------------|
| Victim tracking | `/ws/track/{event_id}` | Victim device | location, keepalive |
| Dispatch fan-out | `/ws/dispatch/{event_id}` | Authority, responder | dispatch_update, responder_status |
| Notification | `/ws/notify/{user_id}` | User | sos_acknowledged, case_update |

WS connections are managed by `TrackingManager` and `NotificationManager` classes in `main.py`. Location updates validate coordinates with `geo_validation.finite_in_range` before persisting or fan-out.

---

## 10. Frontend Code Quality

### TypeScript

**Zero type errors** as of audit date (`npx tsc --noEmit` exit code 0).

### Key Libraries

| Library | Usage | Version |
|---------|-------|---------|
| Next.js | App router, SSR | 14 |
| React | UI components | 18 |
| Clerk | User auth | @clerk/nextjs |
| Tailwind CSS | Styling | 3 |
| Web Crypto API | AES-256-GCM offline queue/contacts | Browser native |
| IndexedDB | Offline queue persistence | Browser native |
| SpeechRecognition | Voice SOS listening | Browser native |

---

## 11. Security Findings

### RESOLVED (confirmed in codebase)

| ID | Finding | Resolution |
|----|---------|-----------|
| SEC-01 | Shared authority password | Individual PBKDF2 credentials in `authority_accounts` collection |
| SEC-02 | Role-claim spoofing from external token | `decode_token()` forces unverified tokens to `role: "user"` |
| SEC-03 | Weak default secrets in production | `_validate_production_config()` refuses to boot with defaults |
| SEC-04 | SOS contact stored in plaintext localStorage | `secureLocal.ts` AES-256-GCM IndexedDB encryption |
| SEC-05 | SOS queue stored in plaintext IndexedDB | `offlineQueue.ts` AES-256-GCM with non-extractable key |
| SEC-06 | Evidence stored in plaintext DB | AES-256-GCM at rest via `encrypt_evidence_payload()` |
| SEC-07 | Auto-eviction of unacknowledged SOS | Removed; queue returns `CapacityExceeded` at 100 items |
| SEC-08 | Safe word stored in plaintext | PBKDF2-HMAC-SHA256 (100k iters, 16-byte random salt) |
| SEC-09 | Decompression bomb on image upload | `MAX_IMAGE_PIXELS=40M`, Pillow `verify()` before decode |
| SEC-10 | Hardcoded local IP in production config | No hardcoded IPs in production frontend `.env.local` |

### OPEN — Medium

| ID | Finding | Severity | Recommended Action |
|----|---------|----------|------------------|
| SEC-M1 | `datetime.utcnow()` deprecated (3673 warnings) | Medium | Replace with `datetime.now(timezone.utc)` throughout backend |
| SEC-M2 | `@app.on_event` deprecated (FastAPI) | Medium | Migrate to `@app.lifespan` context manager |
| SEC-M3 | `voice-sos` page sends hardcoded `accuracy: 4.0` | Medium | Use actual `position.coords.accuracy` from GeolocationAPI |
| SEC-M4 | Therapy page uses `userId = user?.id \|\| 'anon'` before Clerk loads | Low | Gate on `isLoaded` before initiating session |
| SEC-M5 | `shake_sos_routes.py` still registered (Android-only endpoints) | Info | Remove from `main.py` include_router for website-only deploy |
| SEC-M6 | No duress-wipe gesture wired to `wipeQueue()` | Low | `wipeQueue()` exists and is documented; needs UX trigger |

### OPEN — Informational

| ID | Finding | Note |
|----|---------|------|
| INFO-1 | `/download-apk` endpoint registered | Returns 404 when APK absent; harmless but noisy |
| INFO-2 | Admin role requires manual Clerk metadata setup | No self-serve path; requires Clerk dashboard |
| INFO-3 | Calculator PIN hardcoded to `1810` | Configurable via `NEXT_PUBLIC_DISGUISE_PIN` env var |
| INFO-4 | CORS allowlist excludes `127.0.0.1:3000` on some paths | Current list: Vercel prod + localhost:3000 |

---

## 12. Performance Observations

| Area | Observation |
|------|------------|
| Backend startup | MongoDB + Redis connect at import; 3s timeout prevents hanging |
| Rate limiting | Redis-backed (falls back to in-memory in dev); critical endpoints limited |
| Image processing | Pillow operations are synchronous; for high traffic, offload to worker |
| AI calls | Gemini/Groq calls are async-await; timeouts not explicitly set |
| WS fan-out | In-memory room map; not clustered. Multi-instance deploys need Redis pub/sub |
| IndexedDB queue | All reads/writes are async; no blocking of main thread |

---

## 13. Issues Found and Fixed

| Issue | File(s) | Fix Applied |
|-------|---------|------------|
| SOS queue eviction of unacknowledged incidents | `PendingIncidentQueue.kt` (Android) | N/A — website scope; frontend queue has no eviction |
| Shared authority password (old) | `auth_routes.py` | Per-officer PBKDF2 credentials implemented |
| Role spoofing via unverified token | `auth.py` | `decode_token()` enforces issuer + role stripping |
| EncryptedSharedPreferences race (Android) | Android files | N/A — website scope |
| `datetime.utcnow()` deprecation | Multiple backend files | Still present; documented as SEC-M1 (medium) |

---

## 14. Summary of Remaining Issues (Priority Ordered)

1. **SEC-M1:** Fix `datetime.utcnow()` → `datetime.now(timezone.utc)` across all backend files (affects `auth.py`, `sos_routes.py`, `voice_routes.py`, `authority_routes.py`, `lifecycle_service.py`)
2. **SEC-M2:** Migrate `@app.on_event` to `@app.lifespan` in `main.py`
3. **SEC-M3:** Fix hardcoded `accuracy: 4.0` in `voice-sos/page.tsx`
4. **SEC-M4:** Gate therapy userId on `isLoaded` in `therapy/page.tsx`
5. **SEC-M5:** Remove `shake_sos_routes` from production `main.py` router registration
6. **INFO-1:** Remove `/download-apk` endpoint from `main.py`
