# HAVEN Operator Deployment Checklist

Canonical repository: `C:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven`

Do not use `C:\dev\haven`. Do not put real passwords, tokens, or secret values in this file.

Frontend (Vercel) URLs are the public website. Backend (Render) URLs are the API. They are not interchangeable.

No `render.yaml` or `vercel.json` deployment manifest is present in this checkout. Configure the named variables in the Render and Vercel dashboards; this repository does not apply them automatically.

Use the canonical backend venv for database scripts and backend tests: `haven/backend/.venv/Scripts/python.exe` (Windows) or `haven/backend/.venv/bin/python` (Unix). Do not fall back to a global `python` or mix it with `haven/.venv`.

---

## Order of operations

1. **Confirm the target environment and operator authorization.**  
    Use only a dedicated, independently verified staging cluster and database. `ENVIRONMENT=development` is not evidence that a MongoDB endpoint is staging. Follow “Dedicated staging configuration and read-only verification” below; if cluster identity or data ownership is ambiguous, stop.

2. **Take an appropriate MongoDB backup before any later index migration.**  
    A snapshot is not required for this read-only verification. Before separately approved index creation, the operator must take and verify an Atlas snapshot / backup restore point.

3. **Verify staging configuration, review the index plan, and run read-only preflight.**  
    *(STATUS: VERIFIED BY OPERATOR — `SUCCESS: Preflight passed with 0 blockers.` Zero write/drop mutations performed.)*

4. **Review index changes and any blockers.**  
    *(STATUS: VERIFIED BY OPERATOR — Zero blockers, zero duplicates, zero null conflicts. Section 7 indexes ready for approved deployment migration.)*

5. **Configure Render environment variables** (names only; set values in the Render dashboard). See the Render table below. Do not deploy until secrets are non-default.

6. **Deploy the backend** through the operator-controlled Render process. This checklist does not deploy for you.

7. **Verify the deployed backend health endpoint.**  
   Backend API: `https://<your-render-host>/health`  
   Expect JSON `{"status":"ok","timestamp":"<ISO-8601>"}`. Also confirm `https://<your-render-host>/docs` is acceptable for your threat model (disable or protect if not). Do not use the Vercel frontend origin here.

8. **Configure Vercel environment variables.** See the Vercel table below.  
   `NEXT_PUBLIC_API_URL` must be the **HTTPS backend API origin**, not the Vercel frontend URL.

9. **Deploy the frontend** through the operator-controlled Vercel process.

10. **Verify frontend routes and the root-level service worker.**  
    Frontend origin: `https://<your-vercel-host>`  
    Confirm `/` (disguise), `/sign-in`, `/dashboard`, `/authority`, `/authority/rapid-response`, `/authority/providers`, `/responder`, `/admin`, and `https://<your-vercel-host>/sw.js` (service worker at the site root).

11. **Verify authentication and cross-origin communication.**  
    Clerk user login on the frontend for Clerk-protected routes (`/dashboard`, `/sos`, `/therapy`, `/legal`, `/voice-sos`, `/admin`, `/privacy`). Authority login is `POST https://<api>/auth/authority-login` (badge JWT); responder login is `POST https://<api>/auth/responder-login`. `/authority` and `/responder` are **not** Clerk-middleware protected. Confirm browser calls go to the API origin and CORS is the production frontend origin (not `*`). WebSockets must use `wss://<api-host>/...` when the page is HTTPS (`useNotifications` and the live maps derive this from `NEXT_PUBLIC_API_URL`; `https://` becomes `wss://`).

12. **Register a dedicated development/test provider** (staging or a clearly labeled test badge). Do not use production duty officers as the first test identity.

13. **Complete Admin approval and secure account setup.**  
    Authority submits via `/authority/providers`. Admin approves via `/admin`. Provider sets a password through the one-time setup token flow (`/auth/responder-setup`). Never log the raw token.

14. **Verify responder duty and fresh location.**  
    Sign in at `/responder`, go ON_DUTY with location sharing, confirm `location_fresh` / recent `location_updated_at` on the authority roster.

15. **Create an authorized test dispatch** from `/authority/rapid-response` against a test case that already has stored incident GPS. Do not invent coordinates in the client as authority.

16. **Verify notification, acceptance, and live tracking.**  
    In-app offer on `/responder` is the primary channel. Web Push is an enhancement (`SEND_ATTEMPTED` is not device delivery). Assigned responder location on `/ws/dispatch/{dispatch_id}` (WSS in production).

17. **Verify suspension and revocation behavior** via admin/provider-request flows. Confirm the unit is no longer eligible.

18. **Test background Web Push on a real mobile device** (HTTPS PWA, notification permission, VAPID configured). Until this is done, treat push as unverified.

19. **Clean up dedicated test accounts safely** (deactivate/revoke test badges; do not delete unrelated production data).

20. **Document rollback and release status.**  
    Rollback: Render/Vercel previous deploy; Atlas restore from the pre-index snapshot if index creation caused write failures. Unique indexes are not automatically dropped.

---

## Index creation (operator-controlled)

Index creation is outside this verification procedure and is not authorized by a passing preflight. Do not run `setup_indexes.py` as part of the commands above. Any later staging migration requires separate operator approval and a backup. The script itself now rejects production mode and requires the same explicit staging host/database allowlists plus a separate `HAVEN_ALLOW_INDEX_SETUP=YES` confirmation.

Do not store allowlist settings or the confirmation value in source control. The database endpoint and all credentials remain private in the operator-managed environment.

Do not run `verify_live_concurrency.py` against production dispatch records. That script **writes** `LIVE-TEST-` documents. Use it only on a dedicated test/staging database.

## Dedicated staging configuration and read-only verification

This workflow is limited to MongoDB staging identity verification and the read-only index preflight. It does not contact Redis, create or modify indexes, or change documents. Use a fresh PowerShell session with transcription/logging disabled. The backend script loads `backend/.env` relative to itself, but the commands below put the endpoint into this PowerShell process without displaying it.

### A. Independently confirm the Atlas target

In MongoDB Atlas, sign in to the intended organization and project. Confirm with the database/service owner that the selected cluster is dedicated to staging, not production or shared with production. Verify the Atlas project, cluster name and tags/ownership, the cluster's connection host, the database name `Haven` in Data Explorer, and that the staging application is configured to use that same cluster. Confirm the data is staging/test data and that production traffic or production data is not routed or replicated into it. A cluster label, target ID, URI shape, or application setting alone is not proof. If any of these checks is ambiguous, stop and ask the owner; do not run the remote preflight.

Record the exact host identity shown for the application connection. The allowlist accepts hostnames only, comma-separated, without URI scheme, credentials, port, or path. For a standard multi-host MongoDB URI, allowlist every host in the URI. For `mongodb+srv` the validator compares the URI's seed hostname; it does not resolve SRV records. Do not substitute discovered hosts without confirming the endpoint identity with the Atlas owner. Set this application's database allowlist to `Haven` only.

### B. Configure the required variables privately

From a fresh PowerShell session, run the following from the HAVEN repository root. Replace only the non-secret placeholders with the values independently confirmed in Atlas. The endpoint is entered through a hidden prompt; it is held in this process's environment until the session closes. Do not use `Write-Output`, `echo`, `Get-ChildItem Env:`, shell tracing, or transcripts to inspect variables. Do not paste the endpoint into a command line or this document.

```powershell
Set-Location 'C:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven\backend'

$env:ENVIRONMENT = 'staging'
$env:HAVEN_DATABASE_ENVIRONMENT = 'staging'
$env:HAVEN_STAGING_TARGET_ID = '<operator-approved-safe-id>'
$env:HAVEN_STAGING_MONGO_HOST_ALLOWLIST = '<exact-staging-host-1>,<exact-staging-host-2>'
$env:HAVEN_STAGING_DATABASE_ALLOWLIST = 'Haven'

$secureEndpoint = Read-Host 'Enter the confirmed staging MONGO_ENDPOINT' -AsSecureString
$endpointPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureEndpoint)
try {
    $env:MONGO_ENDPOINT = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($endpointPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($endpointPointer)
    $secureEndpoint.Dispose()
}
```

Exact variables used by the MongoDB staging validator are `MONGO_ENDPOINT`, `HAVEN_DATABASE_ENVIRONMENT`, `HAVEN_STAGING_TARGET_ID`, `HAVEN_STAGING_MONGO_HOST_ALLOWLIST`, and `HAVEN_STAGING_DATABASE_ALLOWLIST`. `ENVIRONMENT` is also read: `production`/`prod` is rejected, and its default is `development`; neither a development value nor a staging value proves the actual target is staging. The staging identity comes from the explicit staging setting plus the exact allowlists and, critically, the independent Atlas review above. The target ID must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and should be a non-secret label. Never put a URI, password, or token in the target ID or host/database allowlists.

The preflight has no confirmation flag. `--check-target` is an offline validation mode, not a confirmation that Atlas is truly staging. `HAVEN_ALLOW_INDEX_SETUP=YES` is a separate mutation gate for `setup_indexes.py`; do not set it and do not run that script for this task.

### C. Run offline target validation

The following command parses the configured endpoint locally and checks the exact staging settings. It does not resolve hosts or connect to MongoDB or Redis. The CLI normally includes the target ID, application mode, and database name in its output; this wrapper captures that output and displays only a fixed success message. On failure it displays the validator's redacted reason, which does not include the endpoint, hostname, or credentials.

```powershell
$targetCheckOutput = & .\.venv\Scripts\python.exe preflight_index_check.py --check-target 2>&1
$targetCheckExitCode = $LASTEXITCODE
if ($targetCheckExitCode -ne 0) {
    $targetCheckOutput
    throw 'Target validation failed; no remote check is authorized. Stop.'
}
'Offline target validation passed; no database connection was attempted.'
```

Expected success: `TARGET APPROVED — no database connection was attempted.` On rejection, the script states a redacted reason and confirms no connection was attempted. Stop; privately correct the configuration only after re-confirming Atlas identity. Never broaden an allowlist to make a failed check pass.

### D. View the planned index definitions offline

This command renders the local catalog only. It does not read database state or connect to a service.

```powershell
& .\.venv\Scripts\python.exe preflight_index_check.py --show-index-plan
if ($LASTEXITCODE -ne 0) { throw 'Could not render the local index plan; stop.' }
```

Expected success: `Planned standard MongoDB indexes:` and `Planned Atlas Search indexes:` followed by definitions from `backend/index_catalog.py`.

### E. Run the read-only preflight against the confirmed staging target

Proceed only after the operator has completed the Atlas checks in A and `--check-target` succeeds. This command contacts MongoDB: it connects and pings the server, then reads collection counts/fields, BSON types, and existing index metadata. It does not connect to Redis, write documents, or create/drop/modify indexes. The CLI includes target ID, application mode, and database identity lines in its report; the wrapper below filters those lines so environment-variable values are not displayed. Other report content does not include the URI, hostname, credentials, or document identifier values.

```powershell
$preflightOutput = & .\.venv\Scripts\python.exe preflight_index_check.py 2>&1
$preflightExitCode = $LASTEXITCODE
$preflightOutput | Where-Object {
    "$_" -notmatch '^\s*(Approved target ID|Application mode|Database name|Target environment)\s*:'
}
if ($preflightExitCode -ne 0) { throw 'Preflight blocked or incomplete; stop for operator review.' }
```

Expected success is `PREFLIGHT PASSED — no blockers found.` and exit code `0`; the report also states that no index operation was performed. Exit code `1`, connection failure, or any `BLOCKER`, `CONFLICT`, or incomplete-read message means the result is not a pass. A pass does not authorize index creation.

### F. Blockers and operator review

- Missing or invalid staging settings, URI/database mismatch, or a host outside the exact allowlist: stop before connecting. Recheck the Atlas project, cluster endpoint, database, and process configuration privately. Do not infer staging from `ENVIRONMENT` and do not use wildcards.
- Duplicate identifier groups: the report withholds values. The data owner must investigate the affected collection/field using an approved, read-only review. Decide the canonical-record policy and any separately authorized data migration with a verified backup; this tooling does not delete, archive, or rewrite documents.
- Explicit nulls, missing fields, or empty strings: review counts against the intended schema. Sparse unique indexes still index explicit nulls and empty strings; repeated nulls/empty strings can block. A non-sparse unique field also blocks on missing or null values. Do not change index sparsity or repair records to silence a finding without schema-owner approval and a documented migration.
- Incompatible identifier types: identifier values are expected to be scalar strings. Treat non-string types or an inability to inspect BSON types as a schema/read blocker. Have the data owner inspect and plan any correction; do not coerce or rewrite records automatically.
- Incomplete reads, inaccessible collections, failed aggregates, or failed index inventory: the preflight could not establish safety. Check staging availability, permissions, and network access privately, then rerun only after the cause is understood. A partial report is never a pass.
- Conflicting existing indexes: compare the reported keys/options with the catalog and have the database owner review intended semantics and impact. Do not drop or recreate anything from this workflow. Any index change requires a separate approved migration plan and backup.
- Advisory-only fields are not the planned indexes. Review their notes with the application owner; advisory findings do not authorize or require index changes.

After resolving an issue through a separately approved process, repeat Atlas identity confirmation and the full verification sequence. Never automatically delete documents or repair database records. Close the PowerShell session after verification to clear its process-scoped endpoint value.

`check_redis_runtime.py` is not part of this database verification. It PINGs Redis and writes/deletes a unique `haven:redis-diagnostic:*` key. Before running it, configure `HAVEN_REDIS_TARGET_ENVIRONMENT=staging`, `HAVEN_STAGING_REDIS_TARGET_ID`, `HAVEN_STAGING_REDIS_HOST_ALLOWLIST`, and `HAVEN_STAGING_REDIS_DATABASE_ALLOWLIST` with exact approved values. Its guard rejects unapproved targets before connecting. It is not a substitute for production fail-closed boot.

`HAVEN_DEPLOYMENT_REPORT.md` is not in this repository. Use this checklist plus `README.md` production-configuration section as the operator source of truth.

---

## Render (backend) environment checklist — Verified 25-Variable Audit

The backend codebase reads **25 distinct environment variables** across three functional tiers.
Configure these in the Render Web Service dashboard under **Environment**. Values must stay strictly in the dashboard and must never be committed to source control or logged.

### Variable Classification Matrix

#### Tier 1: Required for Backend Startup in Production (`ENVIRONMENT=production`) — 8 Variables
*Missing, weak, or default values in this tier trigger an immediate `RuntimeError` at boot via `auth._validate_production_config()` or `main.resolve_cors_origins()`, refusing container startup.*

| Variable Name | Sensitivity Classification | Source Code Enforcer | Failure Mode if Missing / Default |
|---|---|---|---|
| `ENVIRONMENT` | Public Configuration | `main.py`, `auth.py`, `rate_limiter.py` | Must be set to `production` (activates fail-closed security guards). |
| `JWT_SECRET` | Server-Side Secret | `auth._validate_production_config()` | Refuses boot if missing, default, or <32 characters (`RuntimeError`). Signs HS256 JWTs. |
| `AUTHORITY_SECRET_KEY` | Server-Side Secret | `auth._validate_production_config()` | Refuses boot if missing or default (`RuntimeError`). Password pepper for authority accounts. |
| `EVIDENCE_ENCRYPTION_KEY` | Server-Side Secret | `auth._validate_production_config()` | Refuses boot if missing or default (`RuntimeError`). 32-byte key for AES-256-GCM evidence encryption. |
| `CLERK_ISSUER` | Public Configuration | `auth._validate_production_config()` | Refuses boot if missing (`RuntimeError`). E.g. `https://<domain>.clerk.accounts.dev`. |
| `CLERK_JWKS_URL` | Public Configuration | `auth._validate_production_config()` | Optional override; automatically derives as `{CLERK_ISSUER}/.well-known/jwks.json` if omitted. |
| `ALLOWED_ORIGINS` | Public Configuration | `main.resolve_cors_origins()` | Refuses boot if missing, non-HTTPS, or wildcard `*` (`RuntimeError`). Comma-separated HTTPS frontend origins (e.g. `https://haven.vercel.app`). |
| `MONGO_ENDPOINT` | Server-Side Secret | `services/db.get_db()` | Required for MongoDB Atlas connection. Fails closed on database operations if unreachable. |

#### Tier 2: Required for Production Features — 11 Variables
*Subsystems gracefully degrade or return HTTP 502/503 if these feature-specific variables are omitted.*

| Variable Name | Sensitivity Classification | Associated Subsystem | Operational Impact if Omitted |
|---|---|---|---|
| `FRONTEND_URL` | Public Configuration | CORS / Application Links | Added to CORS allowlist. Recommended to match primary `ALLOWED_ORIGINS` entry. |
| `REDIS_URL` | Server-Side Secret | Distributed Rate Limiting & Concurrency | Required for distributed rate limiting & atomic dispatch locks. Fails closed (503) if `REDIS_REQUIRED_IN_PRODUCTION=true`. |
| `VAPID_PUBLIC_KEY` | Public Configuration | Web Push Service | Served to browser via `/responder/push/public-key`. Push disabled (`NOT_CONFIGURED`) if missing. |
| `VAPID_PRIVATE_KEY` | Server-Side Secret | Web Push Signing | Used strictly server-side to sign push payloads. **NEVER expose to client or log.** |
| `VAPID_SUBJECT` | Public Configuration | Web Push Identity | Contact URI (`mailto:...` or `https://...`). Required for push service gateway trust. |
| `GEMINI_API_KEY` | Server-Side Secret | AI Embeddings & Legal RAG | Semantic search and case analysis return 502/fallback if missing. |
| `GROQ_API_KEY` | Server-Side Secret | Aria AI Therapy Chat | High-speed LLM chat returns 502/fallback if missing. |
| `CLOUDINARY_CLOUD_NAME` | Public Configuration | Evidence Media Bucket | Required for evidence image/audio uploads to Cloudinary CDN. |
| `CLOUDINARY_API_KEY` | Server-Side Secret | Media Upload Authentication | Evidence uploads fail without Cloudinary API credentials. |
| `CLOUDINARY_API_SECRET` | Server-Side Secret | Media Upload Signing | Required for signed evidence upload API calls. |
| `HF_API_KEY` | Server-Side Secret | Steganography Disguise Generator | FLUX.1 image generation falls back if missing. |

#### Tier 3: Optional System Flags with Safe Defaults — 6 Variables
*These variables have production-safe defaults hardcoded in the codebase; override only if specialized behavior is needed.*

| Variable Name | Sensitivity Classification | Default in Code | Purpose |
|---|---|---|---|
| `STRICT_AUTH` | Public Configuration | `true` (when `ENVIRONMENT=production`) | Enforces cryptographic RS256 token verification against Clerk JWKS. Rejects unverified tokens. |
| `REDIS_ENABLED` | Public Configuration | `bool(REDIS_URL)` | Enables distributed rate limiter and dispatch concurrency lock. |
| `REDIS_REQUIRED_IN_PRODUCTION` | Public Configuration | `true` (when `ENVIRONMENT=production`) | **MANDATORY POLICY FOR PRODUCTION.** Forces fail-closed (HTTP 503) if Redis is offline in production. Prevents double-assignment races in emergency dispatch. Must NEVER be set to `false` in production. |
| `RESPONDER_SECRET_KEY` | Server-Side Secret | Falls back to `AUTHORITY_SECRET_KEY` | Dedicated pepper for responder PBKDF2 password hashes. |
| `MAX_REQUEST_BODY_BYTES` | Public Configuration | `52428800` (50 MB) | Outer ASGI ceiling for request bodies. Must be positive integer in production. |
| `DISPATCH_RADIUS_WAVES` | Public Configuration | `2000,5000,10000` | Comma-separated geofence expansion waves in meters for dispatch broadcast. |

---

## Render (Backend) Service Configuration

### Determining Root Directory from Connected Repository
The canonical git repository connected to GitHub (`https://github.com/Manvvv/Haven-power-for-Women.git`) has its root at `hacknaovate2.0` and contains `haven/backend` and `haven/frontend`.

| Setting | Recommended Value | Detailed Specification & Verification |
|---|---|---|
| **Environment** | Python 3 | Python 3.11 or 3.12 (matches `runtime.txt: python-3.12.4`) |
| **Root Directory** | `haven/backend` | When GitHub repo root is `hacknaovate2.0`, set Root Directory to `haven/backend`. *(Note: If an operator connects a repository whose root is directly `haven/`, set Root Directory to `backend`. Do NOT assume an additional `haven/` level like `haven/haven`.)* |
| **Build Command** | `pip install -r requirements.txt` | Executed inside `haven/backend`. Installs FastAPI, Uvicorn, PyMongo, PyJWT, Cryptography, Redis, PyWebPush, etc. |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` | Executed inside `haven/backend`. Binds to dynamic `$PORT` provided by Render. |
| **Health Check Path** | `/health` | Returns HTTP 200 `{"status":"ok","timestamp":"..."}`; unauthenticated; does not require DB or Redis readiness to respond. |
| **Alternative Monorepo Root Setup** | If Root Directory is left as `.` (repo root):<br>Build: `pip install -r haven/backend/requirements.txt`<br>Start: `uvicorn backend.main:app --app-dir haven/backend --host 0.0.0.0 --port $PORT` | Ensures Python module resolution works if running from repository root. |

---

## Vercel (Frontend) Configuration & Environment Checklist

### Dashboard Build & Project Settings

| Setting | Recommended Value | Notes |
|---|---|---|
| **Framework Preset** | Next.js | Automatically configures build and output directories |
| **Root Directory** | `haven/frontend` | Monorepo subdirectory containing `package.json` *(or `frontend` if repo root is directly `haven/`)* |
| **Build Command** | `next build` (or `npm run build`) | Produces standalone Next.js build with 17 static/dynamic routes |
| **Output Directory** | `.next` | Next.js default output directory |
| **Node.js Version** | `20.x` (or `18.x`) | Matches `@types/node: 20.19.39` in `package.json` |

### Frontend Environment Variables

| Name | Sensitivity Classification | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Public Endpoint (Build-Time) | HTTPS **backend** origin, e.g. `https://haven-api.onrender.com` — no trailing slash, no `/api` path |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Public Identity (Build-Time) | Clerk frontend publishable key (`pk_live_...` or `pk_test_...`) |
| `CLERK_SECRET_KEY` | Server-Side Secret | Clerk secret for Next.js edge middleware. **DO NOT PREFIX WITH NEXT_PUBLIC_.** |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Public Routing | `/sign-in` |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | Public Routing | `/sign-up` |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | Public Routing | `/dashboard` |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` | Public Routing | `/dashboard` |
| `NEXT_PUBLIC_MAP_TILE_URL` | Optional Public Config | Custom raster tile URL template; defaults to OpenStreetMap |
| `NEXT_PUBLIC_MAP_ATTRIBUTION` | Optional Public Config | Tile copyright attribution string |
| `NEXT_PUBLIC_DISGUISE_PIN` | Camouflage Config (Build-Time) | Disguise calculator unlock PIN (default in code: `1810`). **Publicly visible in browser bundle; see Disguise PIN Audit below.** |

> [!IMPORTANT]
> **Next.js Build-Time Inlining Rule:**  
> Next.js inlines all `NEXT_PUBLIC_*` variables into client-side JavaScript bundles **at build time**. Changing any `NEXT_PUBLIC_*` variable in the Vercel dashboard requires triggering a fresh deployment / redeploy for changes to take effect in the browser.

---

## Disguise PIN Security Audit (`NEXT_PUBLIC_DISGUISE_PIN`)

- **Code Location:** [`frontend/src/app/page.tsx:5`](file:///c:/Users/Sagar/OneDrive/Manav/hacknaovate2.0/haven/frontend/src/app/page.tsx#L5) — `const SECRET = process.env.NEXT_PUBLIC_DISGUISE_PIN || '1810'`.
- **Public Visibility:** Because Next.js prefixes client-accessible variables with `NEXT_PUBLIC_`, this variable is compiled directly into browser JavaScript chunks. Anyone inspecting network resources or script files can read the PIN.
- **Security Boundary & Intended Function:**
  - `NEXT_PUBLIC_DISGUISE_PIN` is purely a **client-side screen camouflage/disguise mechanism**. It displays an innocent calculator to hide the application from an abuser looking directly at the device screen.
  - The PIN provides **ZERO authorization** to backend data, case files, victim telemetry, or user accounts.
  - Entering the PIN simply redirects the client browser from `/` to `/home`.
  - All protected frontend routes (`/dashboard`, `/sos`, `/therapy`, `/legal`, `/voice-sos`, `/admin`, `/privacy`) are strictly guarded by Clerk Edge Middleware ([`frontend/src/middleware.ts`](file:///c:/Users/Sagar/OneDrive/Manav/hacknaovate2.0/haven/frontend/src/middleware.ts)).
  - All sensitive backend API endpoints require cryptographically signed Bearer tokens (Clerk RS256 JWT, Authority HS256 JWT, or Responder PBKDF2 session credentials).
  - **Operator Guidance:** Never treat `NEXT_PUBLIC_DISGUISE_PIN` as an access-control or authentication secret.

---

## Production Security Controls Verification

- **Fail-Closed CORS:** `backend/main.py:resolve_cors_origins()` strictly rejects `*` wildcards, non-HTTPS URLs, and localhost-only origins in production. Browser requests with credentials require explicit origin matching.
- **Dynamic HTTPS / WSS Connectivity:** All frontend WebSocket hooks (`useNotifications.ts`, `LiveResponseMap.tsx`, `/authority`, `/responder`, `/voice-sos`) derive protocol dynamically: `window.location.protocol === 'https:' ? 'wss:' : 'ws:'`. WebSockets automatically connect via secure `wss://` on HTTPS origins.
- **Mandatory Redis Distributed Concurrency & Fail-Closed Behavior:**
  - `backend/rate_limiter.py` enforces sliding-window rate limiting via Redis Lua scripts.
  - `backend/services/dispatch_service.py` enforces distributed fast-locks (`haven:dispatch:lock:{id}`) for responder acceptance and wave broadcast (`haven:wave:lock:{id}`).
  - In production (`ENVIRONMENT=production` and `REDIS_REQUIRED_IN_PRODUCTION=true`), any Redis connection failure causes rate-limited endpoints to return HTTP 503 and dispatch acceptances to fail closed rather than silently falling back to local memory.
  - **POLICY:** `REDIS_REQUIRED_IN_PRODUCTION=false` is **strictly prohibited in production**. Redis connectivity must be verified via `backend/check_redis_runtime.py` and service boot logs (`Rate limiter backend: Redis distributed backend initialized`) prior to routing live emergency traffic.
- **VAPID Secret Isolation:** `backend/services/web_push.py` isolates `VAPID_PRIVATE_KEY` strictly on the backend. Only `VAPID_PUBLIC_KEY` is served to clients via `GET /responder/push/public-key`. The push delivery model strictly records `SEND_ATTEMPTED` (HTTP 2xx from Web Push gateway) and never fabricates `DELIVERED`. Push payloads omit victim PII, case IDs, and GPS coordinates.
- **Root-Level Service Worker:** `haven/frontend/public/sw.js` is served from site root (`https://<vercel-host>/sw.js`). This guarantees root service worker scope (`/`), enabling background push interception across all frontend routes. Tapping an alert opens `/responder?offer=<dispatch_id>`, requiring complete re-authentication.

---

## Restricted MongoDB Atlas Network Access Policy

> [!CAUTION]
> **Prohibition of Open Network Access (`0.0.0.0/0`):**  
> `0.0.0.0/0` (Allow Access from Anywhere) is **strictly prohibited** as a normal production configuration. Exposing database ports to the public internet creates severe vulnerability to credential stuffing, distributed denial-of-service, and connection exhaustion attacks.

### Approved Production Network Access Methods
1. **Render Static Outbound IPs (Recommended for Render):**
   - On Render Team or Organization plans, provision dedicated static outbound IP addresses for the Web Service.
   - In MongoDB Atlas Console → **Network Access** → **IP Access List** → Add the specific Render static outbound IP addresses with descriptive comments (e.g. `Render-Prod-Backend-Egress`).
2. **Private Network Peering / Dedicated VPC:**
   - If utilizing enterprise hosting or VPC infrastructure, configure VPC peering or private endpoints to keep database traffic entirely off the public internet.
3. **Operator Maintenance & Preflight Allowlisting:**
   - For operator running database migrations or read-only preflight checks (`run_staging_preflight.ps1`), add only the operator workstation's current public IP address with an explicit expiration window (e.g., 6 hours).
4. **Least-Privilege Database User Enforcement:**
   - Configure a dedicated database user for HAVEN production with privileges strictly limited to `readWrite@Haven` and `dbAdmin@Haven`.
   - Never grant `atlasAdmin`, `clusterAdmin`, or cluster-wide root privileges.
   - Maintain completely separate clusters and database users for staging and production environments.

---

## Potential Production Startup Blockers & Mismatches

1. **Render Root Directory / Start Command Mismatch:** If Render Root Directory is left as `.` but Start Command is `uvicorn main:app`, boot fails (`ModuleNotFoundError`). Set Root Directory to `haven/backend` with `uvicorn main:app --host 0.0.0.0 --port $PORT`, or use repo root with `uvicorn backend.main:app --app-dir haven/backend`.
2. **Insecure Default Secrets in Production:** If `JWT_SECRET`, `AUTHORITY_SECRET_KEY`, or `EVIDENCE_ENCRYPTION_KEY` match their `.env.example` placeholders, or if `JWT_SECRET` is shorter than 32 characters, the backend raises `RuntimeError` and refuses to start.
3. **Clerk Issuer & Automatic JWKS Derivation:**
   - `CLERK_ISSUER` is **mandatory** at startup (e.g. `https://<domain>.clerk.accounts.dev`).
   - `CLERK_JWKS_URL` is automatically derived as `{CLERK_ISSUER}/.well-known/jwks.json` if omitted. It does not need to be manually defined unless overriding the default path.
   - **Environment Compatibility:** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in Vercel and `CLERK_ISSUER` in Render must point to the identical Clerk environment (e.g., both production live instances). Mismatched test and live keys cause token verification to fail (HTTP 401).
4. **CORS Wildcard or Non-HTTPS Origin:** Setting `ALLOWED_ORIGINS=*` or `http://` URLs triggers an immediate `RuntimeError`. Origins must be valid HTTPS origins without paths or trailing slashes (e.g. `https://haven.vercel.app`).
5. **Vercel `NEXT_PUBLIC_API_URL` Path Formatting:** Must be the bare HTTPS origin (e.g. `https://haven-backend.onrender.com`). Do not append `/api` or trailing `/`.
6. **Redis Unavailability with Mandatory Fail-Closed:**
   - `REDIS_REQUIRED_IN_PRODUCTION=true` is mandatory.
   - If `REDIS_URL` is missing, misconfigured, or unreachable, rate-limited endpoints fail with HTTP 503 and dispatch operations refuse local locks.
   - Redis must be provisioned and verified (via `backend/check_redis_runtime.py`) before production release.

---

## Rollback Procedures

- **Frontend Rollback:** In Vercel dashboard, navigate to Deployments → select previous stable deployment → click "Instant Rollback".
- **Backend Rollback:** In Render dashboard, navigate to Events/Deploys → select previous successful deploy → click "Rollback to this build".
- **Database Safety:** Unique indexes created in Section 7 (`provider_registrations`, `provider_requests`, `responder_setup_tokens`) do not alter document contents. If index mutations ever cause unexpected write rejections, drop Section 7 indexes manually in Atlas UI/shell without data loss:
  ```javascript
  db.provider_registrations.dropIndexes();
  db.provider_requests.dropIndexes();
  db.responder_setup_tokens.dropIndexes();
  ```
  Sections 1–6 indexes are baseline and idempotent; do not drop them. Restore from the pre-index Atlas snapshot if emergency document recovery is required.
