# HAVEN Response Providers + Broadcast Dispatch: Implementation Plan

Canonical repo: `C:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven` (do not use `C:\dev\haven`). No commits, no pushes, never print `.env` values.

## 1. Audit findings (verified by reading code)

Backend (`haven/backend`):
- Dispatch engine exists and is mostly wave-aware: `services/dispatch_service.py` has `DISPATCH_RADIUS_WAVES` (default 2000,5000,10000), `DISPATCH_MAX_PROVIDERS_PER_WAVE` (6), `DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS`, `tried_responder_ids` de-dup, `process_expirations()`, `_try_expand_wave()`, and atomic accept (attempt PENDING->ACCEPTED, dispatch OFFERED&unassigned->ACCEPTED, responder AVAILABLE&unassigned->BUSY, then cancel other offers). Do not rewrite these; extend them.
- Escalation sweeper runs in-process every 5 s (`main.py` `_start_dispatch_sweeper`). Safe across workers only because claims are single-document conditional updates.
- Fail-open gaps: `_acquire_lock` and `_acquire_wave_lock` return `(True, None)` when Redis is absent. This contradicts the project's fail-closed production policy in `rate_limiter.py`.
- Web push is broken silently: `_broadcast_offers` imports `services.web_push.notify_responder`, which does NOT exist. The `except` swallows it. The attempt is still stored with `notification_status: "attempted"`, which is a false delivery signal.
- ON_DUTY/OFF_DUTY are accepted by `set_self_status` but mapped onto AVAILABLE/OFFLINE. There is no separate duty field, so ON_DUTY and AVAILABLE are conflated.
- Freshness: `find_eligible` checks `location_updated_at` against `RESPONDER_LOCATION_MAX_AGE_SECONDS` (300 s) only at dispatch time. A responder stays `status=AVAILABLE` with an 18-minute-old fix. `availability_counts` reports this as "stale" but nothing forces the status back or hides the location in the responder UI.
- Responder location is pushed by `watchPosition` in `frontend/src/app/responder/page.tsx:222` (`maximumAge 5000`). There is no heartbeat, and a backgrounded tab stops fixes. Root cause of the 18-minute stale fixes is the absence of a server-side freshness transition plus browser-side fix delivery. Confirm by reproducing before fixing.
- Provisioning: no HTTP endpoint creates responders. Only `provision_responder.py` (CLI) creates them. `routers/admin_routes.py` (`require_admin`) lists, verifies, and (de)activates. `AUTHORITY` cannot manage responders.
- Dev seeding (`ensure_dev_responder`, non-production only) creates `HN-204` with a default password and a fixed Bengaluru fix. It is correctly guarded by `IS_PRODUCTION`.
- WebSocket `/ws/dispatch/{id}` already enforces: assigned responder may broadcast only in ACCEPTED/EN_ROUTE/ARRIVED; victim and authority are observers. Reuse it.
- `_nearby_responder_view` / `_network_responder_view` expose `{lat,lng}` to authorities only. Victim `public_view` carries no responder coordinates. Keep it that way.

Frontend:
- `/responder` exists (login via `/auth/responder-login`, polling, watchPosition, WS dispatch room).
- `/authority/rapid-response` exists. There is no `/authority/providers` route and no Providers section in the authority nav.
- No service worker, no `PushManager`, no VAPID. `layout.tsx` references `/manifest.json`; `frontend/public` was not verified.

Not verified in this planning session: `git status` and the test suite. Shell was blocked in plan mode. Run them before implementation.

## 2. Target design (decisions with recommended defaults)

D1 Duty model. Add a separate `duty_status` field (`OFF_DUTY` | `ON_DUTY`) on responder records. Keep `status` for operational state (`AVAILABLE`, `BUSY`, `UNAVAILABLE`, `OFFLINE`). Offer eligibility requires `duty_status == ON_DUTY` AND `status == AVAILABLE` AND fresh location. OFFERED/EN_ROUTE/ARRIVED are dispatch states derived from the attempt/dispatch, shown in UI. Going OFF_DUTY clears location sharing and stops WS location broadcasts.

D2 Freshness. Enforce `RESPONDER_LOCATION_MAX_AGE_SECONDS` (existing, default 300) as a "stale" flag returned by every projection. Stale ON_DUTY units are excluded from eligibility. Add a configurable `RESPONDER_LOCATION_UPDATE_INTERVAL_SECONDS` (default 3) advisory for the client. Client cadence: ~3 s during an active assignment, slower otherwise. No exact 3 s promise in UI.

D3 Provider management (authority). Route: `/authority/providers` (new top-level nav item after "Rapid Response"). Backend roles: ADMIN may create-with-verification, verify, activate/deactivate, reset setup. AUTHORITY may view the roster and create PENDING (inert) records. Recommended; see Q1.

D4 Provisioning. Create via `create_responder_inert` (random unusable hash, verified=False, OFFLINE). Issue a single-use, random, short-lived setup token stored as a SHA-256 hash in a new `responder_setup_tokens` collection with TTL index. Provider sets password via `/auth/responder-setup`. Never return the token to the authority UI more than once, and never log it.

D5 Radius waves. Keep the existing engine. Changes: enforce wave-level pending/timeout gating explicitly; ensure `process_expirations` handles "all declined" immediately (already does via `decline_offer`); add a `wave_started_at` / `wave_deadline` field for the authority UI; surface wave counts (offers sent, pending, declined, timeout, cancelled) from attempts.

D6 Locks. Fail-closed for accept and wave locks when `REDIS_REQUIRED_IN_PRODUCTION` is true and Redis is unreachable. Mongo conditional updates remain the authoritative guard in all modes. Dev/test keep the in-memory fallback.

D7 Notifications. Replace the missing `services.web_push` import with a real module `services/web_push.py`. Behaviour:
- If VAPID env is not configured: record `notification_status = "NOT_CONFIGURED"` and surface it in the authority dashboard. Never report delivered.
- If configured: deliver via Web Push (requires `pywebpush`; see Q2), record `ATTEMPTED` then `DELIVERED` only on transport acknowledgement; record `FAILED` with a safe reason.
- In-app: persistent incoming-offer card on `/responder`, audio/vibration best-effort, WS-driven plus polling fallback.
- Lock-screen payload: "HAVEN EMERGENCY REQUEST", priority, distance, expiry. No victim PII, no incident ID beyond the opaque dispatch id.

D8 Accept/decline. Keep existing `accept_offer` / `decline_offer` and their idempotency. Add explicit tests for concurrent accept, double-click, and expired/cancelled offer rejection.

D9 Authority map. Show incident, eligible (not offered), offered, assigned, en route. Only the accepted responder's live position appears after acceptance. Reuse `/ws/dispatch/{id}` and `active-responders`. Trail: 40-point in-memory client buffer, cleared on unmount, dispatch switch, and terminal status.

D10 User map. Shows only the accepted responder's position. "Finding an available responder..." before acceptance; "A responder accepted. Waiting for the first location update." after acceptance without a fix; "Responder location is temporarily unavailable." when stale. No ETA.

D11 Audit. Use existing `log_audit` with the event names in the spec. Add `PROVIDER_CREATED`, `PROVIDER_VERIFICATION_APPROVED`, `PROVIDER_ACTIVATED`, `PROVIDER_DEACTIVATED`, `PROVIDER_WENT_ON_DUTY`, `PROVIDER_WENT_OFF_DUTY`, `PROVIDER_LOCATION_SHARING_STARTED/STOPPED`, `PROVIDER_NOTIFICATION_ATTEMPTED`, `PROVIDER_ARRIVED`, `HELP_PROVIDED`. Never log tokens, passwords, GPS streams, or victim PII.

## 3. Ordered implementation steps (small reviewable commits, no git commit by agent)

1. Audit baseline: run `test_rapid_response_network.py`, `test_rrn_authority_views.py`, `test_incident_location.py`, and the full backend test set. Record results before any change.
2. Backend duty model: `duty_status` on responder records; migrate missing field as OFF_DUTY; endpoints `POST /responder/duty` (ON/OFF) with validated transitions; OFF_DUTY clears `current_location` sharing flag and rejects location POSTs with 409.
3. Freshness: `find_eligible` requires ON_DUTY + fresh fix; projections expose `location_fresh`, `location_age_seconds`, `duty_status`. Add tests: fresh qualifies, stale excluded, off-duty excluded.
4. Web Push module `services/web_push.py` + subscription endpoints `POST/DELETE /responder/push-subscription` (store endpoint hash + keys server-side). Honest status fields on attempt records. Frontend service worker `public/sw.js` with `push` and `notificationclick` handlers.
5. Provisioning: `POST /admin/responders` (ADMIN) and `POST /authority/providers` (AUTHORITY, creates PENDING only). Setup token issue/consume endpoints. Verify/activate/deactivate via existing `PATCH /admin/responders/{id}` extended with audit.
6. Redis fail-closed for accept/wave locks in production; tests for fail-closed behaviour with mocked Redis outage.
7. Wave metadata: `wave_deadline`, per-wave counts in `public_view` (authority). Tests: first wave batch cap, no duplicate offers, second wave excludes tried, early all-decline advances immediately, pending prevents expansion, accepted prevents expansion, no candidates -> FAILED.
8. Accept/decline tests: first valid accept wins, concurrent accept single winner (threaded in-memory test), losers get safe conflict, other pending cancelled, double-click idempotent, expired/cancelled cannot assign.
9. Frontend `/authority/providers` page (metrics from backend counts, roster table with safe fields only, add-provider modal, verify/activate actions gated by role). Add nav entry.
10. Frontend `/responder`: duty controls, explicit location-sharing consent text, LIVE/STALE/PERMISSION DENIED/LOCATION UNAVAILABLE/RECONNECTING/DISCONNECTED states, incoming offer card with server-driven expiry, persistent alert.
11. Authority Rapid Response: wave breakdown panel (backend-provided counts only), command map legend (Incident / Eligible / Offered / Assigned / En route).
12. User live map: accepted-responder-only marker, honest status strings, no ETA, no other providers.
13. Location fix verification: reproduce stale 18-minute case in browser before/after.
14. Regression and security tests; run `npx tsc --noEmit` and `npm run build` in `frontend`.
15. Real-browser E2E with development test providers only (see section 4).

## 4. Validation plan

- Backend: `python -m pytest` (or the existing runner) for the three named suites plus new suites `test_provider_management.py`, `test_dispatch_waves.py`, `test_first_acceptance.py`, `test_responder_location.py`, `test_notifications.py`, `test_privacy_views.py`.
- Frontend: `npx tsc --noEmit`, `npm run build`.
- Browser E2E (development only): create 3-5 providers via `/authority/providers`, verify, sign in, go ON_DUTY and share location, create valid case with stored GPS, dispatch, accept with one provider, observe cancellation of others, EN_ROUTE, ARRIVED, HELP_PROVIDED, OFF_DUTY stops tracking, expansion with all declines.
- Security checks: unauthorized provisioning, unauthorized accept, cross-user WS, fake location, role spoofing, and client-supplied radius/candidate lists must all be rejected.
- Report every result honestly. Do not claim phone alarms, background GPS, or delivered push unless verified.

## 5. Risks and limitations

- Browser/PWA background geolocation and push delivery are not guaranteed on iOS or when the tab is closed without a configured push transport.
- Redis fail-closed may cause accept/dispatch 503s if Redis is misconfigured in production. Intentional.
- Existing dev responder credentials are non-production only and must not carry into production.
- The 5-second sweeper runs in every worker; correctness relies on single-document claims, not leader election.

## 6. Resolved decisions (user-confirmed)

Q1 Provider authority: ADMIN ONLY via existing `require_admin` (`auth.py:371`) for create/provision, verify/approve, activate/deactivate. AUTHORITY (`require_authority`) may only view provider roster/availability, review eligible units, initiate human-approved dispatch, and monitor responses. AUTHORITY must not create trusted credentials, approve verification, or change roles. Frontend-supplied role/verified flags are never trusted; offers require an active, verified, ON_DUTY backend record.

Q2 Push: add `pywebpush` to `requirements.txt` (currently absent; verified). VAPID config via env names: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`. Private key is server-only; never sent to the frontend, never logged. Public key only is served to the client for subscription.
- Notification status values, stored per attempt and shown to authority: `NOT_CONFIGURED` (VAPID missing), `SUBSCRIPTION_REQUIRED` (no push subscription for responder), `PERMISSION_DENIED` (browser denied notifications, reported by client), `SEND_FAILED` (transport error, safe reason), `SEND_ATTEMPTED` (request handed to push service), `DELIVERED` (only if a delivery receipt is actually available; with standard Web Push this is generally NOT available, so expect SEND_ATTEMPTED as the highest truthful status).
- Push is never a prerequisite for a valid in-app offer. The in-app incoming-offer card on `/responder` remains the primary channel.
- Subscription flow: client requests permission on explicit user action, fetches VAPID public key, subscribes via service worker `PushManager`, posts the subscription to `POST /responder/push-subscription` (responder-only, rate-limited). Stored hashed endpoint key plus encrypted-at-rest keys where feasible; deleted on OFF_DUTY or logout.
- Service worker `public/sw.js`: `push` shows "HAVEN EMERGENCY REQUEST / Priority: CRITICAL / Distance / Expires in"; no victim PII; `notificationclick` opens `/responder?offer=<dispatch_id>` after auth.
- Docs must state: background delivery depends on the browser/OS, PWA install (iOS requires home-screen install and recent iOS), notification permission, battery optimisation, and no native ringtone or guaranteed alarm.

Q3 Infrastructure: do not assume MongoDB or Redis are reachable. Before E2E: (1) confirm MongoDB reachable with a ping using the configured `MONGODB_URI`-equivalent env var from `.env` without printing it; (2) confirm Redis reachable with `PING` via `REDIS_URL` without printing it; (3) confirm app logs show Redis backend actually active (`rate_limiter._resolve_backend` returns `redis`); (4) run concurrency test against the live config; (5) browser verification. If Redis is unreachable the report must say distributed coordination was NOT validated. Fail-closed in production (`REDIS_REQUIRED_IN_PRODUCTION`). Dev may use fallback only with explicit labelling.

## 6a. Known contradictions to resolve during implementation

- Plan earlier said AUTHORITY could create PENDING provider records (step 5). Per Q1, creation is ADMIN-only; AUTHORITY gets read-only roster.
- `responder_service.set_self_status` maps ON_DUTY to AVAILABLE; this must be replaced by a separate `duty_status` field (see D1), otherwise ON_DUTY and AVAILABLE remain conflated.
- `_broadcast_offers` records `notification_status: "attempted"` regardless of outcome; this must be replaced with the real status set above.

## 7. Manual production setup (documented, not executed)

- Env names only: `ENVIRONMENT`, `JWT_SECRET`, `AUTHORITY_SECRET_KEY`, `RESPONDER_SECRET_KEY` (optional), `REDIS_URL`, `REDIS_ENABLED`, `REDIS_REQUIRED_IN_PRODUCTION`, `DISPATCH_RADIUS_WAVES`, `DISPATCH_MAX_PROVIDERS_PER_WAVE`, `DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS`, `RESPONDER_LOCATION_MAX_AGE_SECONDS`, `RESPONDER_LOCATION_UPDATE_INTERVAL_SECONDS`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (names only).
- Run `setup_indexes.py` for new indexes on `responders` (2dsphere on `current_location`, unique `responder_id`, `location_updated_at`) and `responder_setup_tokens` (TTL on `expires_at`).
- Provision real providers through the admin workflow. No test providers, no fake GPS, no default passwords in production.
