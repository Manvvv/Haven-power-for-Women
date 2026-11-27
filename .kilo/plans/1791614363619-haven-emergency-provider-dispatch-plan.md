# HAVEN — Emergency Provider Management + Broadcast Dispatch + Radius Expansion Plan

**Repo:** `C:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven`
**Stack:** Next.js 14 + TS + Tailwind | FastAPI + MongoDB + Redis | Clerk + Haven JWT | 2dsphere GeoJSON `[lng,lat]`
**Plan ID:** 1791614363619  
**Status:** Draft — 1 open decision blocks finalization

---

## 1) Goal & Scope

Extend the *existing* Rapid Response Network (RRN) into the full **Uber-style broadcast dispatch with automatic radius expansion and real-time responder tracking** described in §2–§33, without breaking current SOS/voice/authority flows.

Must deliver (§33 acceptance criteria):
- Authority can securely provision → verify → activate providers; only verified+active reach dispatch.
- Provider can sign in at `/responder`, go ON/OFF duty with **explicit** location-sharing consent, see offers, ACCEPT/DECLINE, become EN_ROUTE, and stream live GPS over `WS /ws/dispatch/{id}`.
- Freshness rules enforced: stale / OFF_DUTY / assigned / wrong jurisdiction / unverified excluded.
- Authority at `/authority/providers` manages roster with real metrics (TOTAL/VERIFIED/ON_DUTY/AVAILABLE/BUSY/OFFLINE-STALE).
- `POST /dispatch` (human-authorized only) broadcasts **first wave ~5–6 nearest** simultaneously; if none accept, backend expands radius through configurable waves (e.g. 2km → 5km → 10km) without re-offering duplicates, until assignment or FAILED.
- First valid ACCEPT wins atomically; other pending offers cancelled; double-click idempotent.
- Authority & victim maps show **only** the accepted responder live with 40-frame transient trail; victim never sees provider network; staleness shown honestly; no fabricated ETA.
- Audit, rate-limits, WS auth, privacy, and existing tests/build stay green.

Out of scope for this increment: native push beyond Web Push abstraction, offline background tracking guarantees (document limitations), any autonomous dispatch.

---

## 2) Audit Findings (actual code, not prior reports)

**Backend — already solid:**
- `backend/main.py`: `LiveTrackingManager` reused for both `tracking_manager` (`/ws/track/{event_id}`) and `dispatch_manager` (`/ws/dispatch/{dispatch_id}`); `_authorize_ws_dispatch` allows only assigned responder to broadcast (ACCEPTED/EN_ROUTE/ARRIVED), victim + authority subscribe-only; CORS + `BodySizeLimitMiddleware` correct.
- `services/dispatch_service.py`: Human-approved `create_dispatch` only; `_broadcast_offers` creates **PENDING attempt per eligible responder** via `responder_service.find_eligible`; broadcast model, atomic accept chain (attempt PENDING→ACCEPTED → dispatch OFFERED→ACCEPTED with `assigned_responder_id==None` guard → responder AVAILABLE→BUSY), `_cancel_other_offers`, `_has_pending_offers`, `get_offers_for_dispatch`, background sweeper `process_expirations` every 5s (pure/idempotent, Redis fast-lock is optimization only). Terminology: `CREATED/SEARCHING/OFFERED/ACCEPTED/EN_ROUTE/ARRIVED/HELP_PROVIDED/CANCELLED/EXPIRED/FAILED/RESOLVED`.
- `services/responder_service.py`: Separate `responders` collection, PBKDF2+pepper passwords, `verified` gate (INERT until admin approves), `status` (`OFFLINE/AVAILABLE/BUSY/UNAVAILABLE` + aliases ON_DUTY→AVAILABLE, OFF_DUTY→OFFLINE), `find_eligible` hard predicates (active, verified, AVAILABLE, unassigned, jurisdiction, capability, fresh location ≤ `RESPONDER_LOCATION_MAX_AGE_SECONDS`=300, within radius, `$near`), atomic `try_claim_for_dispatch`, `release_from_dispatch`, `availability_counts`. Dev seeder `ensure_dev_responder()` (non-prod).
- `routers/dispatch_routes.py`: `POST /dispatch` resolves incident coords server-side via `resolve_incident_point` (never client-supplied); `GET /by-case`, `/rrn/metrics`, `/rrn/nearby/{caseId}`, `/rrn/network`, `/rrn/active-responders`, `/dispatch/{id}/timeline`, `/offers`, `/cancel`; responder endpoints `/responder/me`, `/active-dispatch`, `/status`, `/location`, `/offers`, `/accept`, `/decline`, `/enroute`, `/arrived`, `/help-provided`. Safe projections `_nearby_responder_view`, `_network_responder_view` (label+distance+freshness only).
- `routers/admin_routes.py`: `GET /admin/responders`, `PATCH /admin/responders/{id}` (verified/active only, role immutable).
- `services/db.py`: collections `responders`, `dispatch_requests`, `dispatch_attempts`, `response_events` isolated from `sos_cases`.
- `provision_responder.py`: CLI operator provisioning (PBKDF2+pepper), no HTTP creation endpoint.

**Frontend — already solid:**
- `src/app/authority/page.tsx` + `src/app/authority/rapid-response/page.tsx`: Metrics cards, active emergencies list, nearby eligible units (read-only visibility, no force-assign), dispatch confirmation modal, timeline + offers breakdown, live WS observation (`ACCEPTED/EN_ROUTE/ARRIVED`), `deriveLiveState` truthful status (grey/yellow/green/orange).
- `src/app/responder/page.tsx`: Badge+password login, GO ON/OFF DUTY, geolocation watch (eligibility REST throttled 10s + WS stream only while assigned), offers with countdown, ACCEPT/DECLINE, progress (en_route/arrived/help), `LiveResponseMap` with 40-frame trail, follow/fit controls.
- `src/lib/dispatch.ts` + `src/components/LiveResponseMap.tsx` + `src/lib/mapProvider.ts`: Typed API client, vendor-neutral OSM tiles, staleness labeling, no ETA fabrication.
- `src/lib/api.ts`: `secureFetch` already supports `customToken` for responder session isolation.

**Tests / config:**
- Existing tests `test_rapid_response_network.py`, `test_rrn_authority_views.py`, `test_incident_location.py` must stay passing.
- Env: `DISPATCH_ACCEPT_TIMEOUT_SECONDS=45`, `DISPATCH_DEFAULT_RADIUS_M=10000`, `RESPONDER_LOCATION_MAX_AGE_SECONDS=300`, `_MAX_CANDIDATES=25`; sweeper interval 5s; no wave config yet.

---

## 3) Gap Analysis — What the Spec Requires That Is Missing

| Spec § | Missing / Incomplete |
|---|---|
| §4–6 Providers section + secure provisioning | No `/authority/providers` route/page; roster only via `/admin` (admin-only); no HTTP `POST /admin/responders` or `/authority/providers` creation endpoint; no single-use invite/token flow; no provider category model (only free-form `capabilities`/`jurisdiction`) — §5 categories need mapping. |
| §7–8 Duty + explicit location consent | Duty is functional but UI conflates GO ON DUTY/AVAILABLE; no explicit “Start duty and share location” consent copy + separate permission grant step; OFF_DUTY correctly stops watch but staleness display needs truthful states (LIVE/STALE/PERMISSION DENIED/LOCATION UNAVAILABLE/RECONNECTING/DISCONNECTED) driven by backend freshness. |
| §9 Freshness 18-min bug | Backend eligibility correctly excludes stale, but `availability_counts` and authority nearby/network views can show ON_DUTY with stale location as “available”; need to surface `ON_DUTY+STALE` / `ON_DUTY+UNAVAILABLE` buckets and exclude stale from `responders_available` count accurately. |
| §10–12 Radius waves | Single-radius broadcast to all eligible (up to 25). No `DISPATCH_RADIUS_WAVES=2000,5000,10000`, no `DISPATCH_MAX_PROVIDERS_PER_WAVE=6`, no `current_wave_index`/`radius_waves` on dispatch, no wave-scoped attempt filtering, no advancement when wave exhausted, no early-advance on all-decline, no “no eligible” FAILED after waves exhausted. |
| §14/28 Notifications | `dispatch_notify` + `notification_service` manager does in-app + durable DB notifications and live WS pushes, but **no Web Push** (no service worker, no VAPID, no subscription storage). Need push abstraction + honest delivery states (CREATED→ATTEMPTED→DELIVERED/FAILED→OPENED/ACCEPTED/DECLINED/TIMEOUT). |
| §15 Offer screen | `OfferCard` exists but spec layout needs exact copy (incident type, jurisdiction, capability, 00:20 countdown, ACCEPT/DECLINE, “already assigned” disabled state) — minor UI alignment. |
| §16–18 Authority/Command/User maps | Authority already has metrics+nearby+network+timeline+offers; missing **Providers** filtered tabs (Verified/OnDuty/Available/Busy/Offline-Stale) + per-provider cards with verification/duty/freshness/assignment; command map legend already honest but needs wave-aware breakdown (wave 0–2km: 6 offered, wave 2–5km: +4, total 10). Victim view privacy is correct (only accepted responder) — verify no regression. |
| §22 Timer/escalation worker | Sweeper handles expiry→FAILED but does not advance radius waves; needs Redis wave-processing lock + idempotent per-wave deadline, “do not expand after assigned”, deduplication. |
| §24–25 Indexes | Need 2dsphere index verification script + dispatch wave fields migration. |

---

## 4) Architecture Decisions (resolved)

- **Provider identity = responder.** Do not introduce a second “provider” collection. Extend `responders` with optional `provider_category` (enum from §5: `police | women_safety_unit | ngo_response | shelter_response | medical_partner | other_authorized`), `organization`, `station_unit`, `contact` (hashed/minimal). Keeps dispatch path unchanged.
- **Provisioning trust boundary.** No public self-registration. Keep `provision_responder.py` as primary prod path. Add **one** admin-only HTTP endpoint `POST /admin/responders` (require_admin) that creates INERT record + returns a **single-use, short-lived setup token** (e.g. 24h, hashed at rest, single-use) for the provider to set their initial password via `POST /auth/responder-setup` — never a shared default password, never plaintext. Authority dashboard “Add Provider” will call this endpoint; only admin/authority with provision permission can invoke (see open question).
- **Duty vs availability.** Preserve backend distinction: ON_DUTY (alias for AVAILABLE) vs AVAILABLE (fresh location). UI will expose two-step consent: “Go on duty” → permission prompt → “Start sharing location” with copy *“Your operational location will be shared with authorized HAVEN authorities while you are on duty.”* OFF_DUTY clears watch, does not fabricate 0,0, and marks location stale.
- **Wave storage.** Dispatch doc gains `radius_waves: number[]`, `current_wave_index: number`, `wave_expires_at: datetime`, `wave_deadlines: datetime[]`, `tried_responder_ids` already exists, `broadcast_attempt_ids` per wave stays. Current `radius_m` becomes the active wave radius (first wave). Backend selects waves deterministically; frontend never supplies radius or candidate list.
- **Offer lifecycle extensions.** `dispatch_attempts` gains `wave_index`, `offer_created_notified`, `notification_status` (attempted/delivered/failed/opened). `DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS` (env, default 20) snapshotted per wave; wave advancement only when zero PENDING remain in current wave.
- **Notification honesty.** Keep existing WS + durable notifications as primary. Add `services/web_push.py` abstraction (VAPID) with `POST /responder/push-subscription` and backend `send_web_push` attempt; surface honest statuses; do not claim alarm delivery when transport unconfigured — document in `/docs` and UI warning.
- **Authority Providers route.** New Next.js segment `src/app/authority/providers/page.tsx` reusing `Authority` chrome, guarded by `require_authority` on API side; **creation guarded by `require_admin`** even when accessed from authority UI (HTTP 403 for non-admin). Avoids duplicating app — same responder store, same dispatch engine.
- **Monitoring.** Extend `GET /dispatch/rrn/metrics` to include provider breakdown from `availability_counts` + stale/offline buckets; no PII.

---

## 5) Data & API Changes (minimal, additive, migration-safe)

**MongoDB:**
- `responders`: add `provider_category`, `organization`, `station_unit`, `jurisdiction` already, `category` enum index; `current_location` 2dsphere already (verify via setup script); `location_updated_at` already.
- `dispatch_requests`: add `radius_waves` (int[]), `current_wave_index`, `max_providers_per_wave`, `wave_accept_timeout_seconds`, `wave_expires_at`, `current_wave_attempt_ids` (optional), keep `broadcast_attempt_ids` for all waves, `eligible_provider_count` per wave aggregated.
- `dispatch_attempts`: add `wave_index`, `notification_status`, `notified_at`.
- Ensure indexes: `responders.current_location` 2dsphere, `responders.responder_id` unique, `dispatch_requests.case_id + status`, `dispatch_attempts.dispatch_id + response`, `dispatch_attempts.responder_id + response`.

**Backend config (env names only — never log values):**
- `DISPATCH_RADIUS_WAVES` (CSV, default `2000,5000,10000`)
- `DISPATCH_MAX_PROVIDERS_PER_WAVE` (default 6, 1–25)
- `DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS` (default 20, 5–300)
- `RESPONDER_SETUP_TOKEN_TTL_HOURS` (default 24, 1–72)
- `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` (web push only, document)

**New/changed HTTP endpoints:**
- `POST /admin/responders` — admin-only, body `{badge_number, officer_name, display_label?, provider_category?, organization?, station_unit?, jurisdiction?, capabilities?, provider_contact?}` → `{responder, setup_token}` (token shown once, hashed stored, single-use). Audit `PROVIDER_CREATED`, `PROVIDER_VERIFICATION_PENDING`.
- `POST /auth/responder-setup` — unauthenticated but token-bound: `{token, password}` → creates password hash, consumes token. Rate-limited, audited.
- `PATCH /admin/responders/{id}` already exists (verified/active + new fields: category/org/jurisdiction/capabilities) — extend without breaking.
- `GET /authority/providers` equivalent is `GET /admin/responders` (reuse) + filtered view; optionally `GET /dispatch/rrn/providers` (authority can list with safe view) — prefer reuse to minimize surface.
- `POST /responder/push-subscription` + `DELETE` + web push abstraction (authority never sees subscription secrets).
- Dispatch waves are internal to `POST /dispatch` + `process_expirations`; no new dispatch-create param for waves (backend-owned).

**Frontend routes:**
- `src/app/authority/providers/page.tsx` — tabbed roster (All/Verified/OnDuty/Available/Busy/Offline-Stale) + “+ Add Provider” modal + create flow (admin-only) + metrics header (real counts).
- Extend `src/lib/dispatch.ts` with `createProvider`, `setupResponderPassword`, `getProviders` (thin wrappers over admin endpoints).
- `src/app/responder/page.tsx` — explicit consent copy + permission-denied / stale / reconnecting states (already partially, refine).
- `src/app/authority/rapid-response/page.tsx` — wave-aware breakdown in selected dispatch panel (current wave, offers sent/pending/declined/timeout, “Expanding radius…” notice).

---

## 6) Broadcast Wave Engine (deterministic, auditable)

**Config parsing:** `DISPATCH_RADIUS_WAVES` parsed once per dispatch into sorted ascending `radius_waves[]`; `max_per_wave` snapshotted; `timeout` snapshotted.

**Creation (`create_dispatch`):**
1. Resolve incident point server-side, jurisdiction, victim_user_id (existing).
2. Insert dispatch with `status=SEARCHING`, `radius_waves`, `current_wave_index=0`, `radius_m=radius_waves[0]`.
3. Call `_broadcast_wave(dispatch)` for wave 0.

**`_broadcast_wave(d)` (per wave, idempotent):**
- `eligible = find_eligible(lng,lat, radius=radius_waves[wave], exclude=tried_ids, max_age, jurisdiction, capability, limit=max_per_wave)` — already nearest-first; take up to `max_per_wave`.
- If none eligible and no further waves → `FAILED` (honest, no retry).
- For each chosen: insert `PENDING` attempt with `wave_index=wave`, `expires_at=now+timeout`, record `broadcast_attempt_ids` extension, `tried_responder_ids` addToSet.
- Transition `SEARCHING→OFFERED` (conditional on SEARCHING) or remain OFFERED if already offered; set `wave_expires_at=expires_at`.
- Emit notification intents per chosen (WS + durable + web-push attempt) with `notification_status=attempted`.

**Wave advancement (`process_expirations` extended):**
- Pure, sweep-driven (no frontend timer). On each tick:
  - Expire PENDING attempts whose `expires_at < now` → `TIMEOUT` (single-doc guard).
  - For each dispatch that had any expiry: if still `OFFERED` and **no PENDING remain in current wave** (check attempts for that wave), then either:
    - `current_wave_index+1 < len(radius_waves)` → set `current_wave_index+=1`, `radius_m=radius_waves[next]`, `status=SEARCHING`→ re-enter `_broadcast_wave` for next wave (Redis lock `haven:dispatch:wave:{id}` to prevent duplicate broadcasts across workers); audit `DISPATCH_RADIUS_EXPANDED`.
    - else → `FAILED`.
  - If any PENDING remain in current wave → do **not** advance (early all-decline case still exhausts that wave’s pendings before advancing).
  - If at any point `assigned_responder_id` becomes non-null → cancel all remaining PENDING (`OTHER_OFFERS_CANCELLED`), halt expansion forever (guaranteed by status≠OFFERED check).

**Accept path (existing atomic chain preserved):**
- Steps 1–3 unchanged except `current_wave_index` irrelevant — any PENDING from any wave can win. On win: `_cancel_other_offers` across all waves, freeze `wave_expires_at`, emit cancelled intents honestly.

**Decline path:** Mark DECLINED; if that was the last PENDING in wave → trigger same wave-advance logic (either via next sweeper tick or immediate inline advance — inline is allowed only if still holding the wave lock).

**Failure modes:** Redis unavailable → fail-closed for assignment (Mongo guards win), but wave advancement still works via Mongo conditional updates (no duplicate broadcast because attempt creation is guarded by `tried_responder_ids` + wave lock fallback). Never read radius/candidate list from frontend.

---

## 7) Location Freshness & Honest UX

- Eligibility already checks `location_updated_at >= now - max_age`.
- **Fix:** `availability_counts()` and authority views will compute buckets from real rows:
  - `TOTAL_REGISTERED`, `VERIFIED`, `ON_DUTY` (verified+active), `AVAILABLE` (verified+active+AVAILABLE+fresh+unassigned), `BUSY/ASSIGNED` (verified+active+BUSY|assigned), `OFFLINE` + `LOCATION_STALE` (verified+active+AVAILABLE but stale/no location).
- UI: Authority Providers shows per-card freshness dot + `updated Ns/m ago` + stale badge; stale never labelled LIVE.
- Responder page: explicit states `LIVE` (fresh + connected), `STALE` (>30s no frame), `PERMISSION DENIED`, `LOCATION UNAVAILABLE`, `RECONNECTING`, `DISCONNECTED` derived from `deriveLiveState` + geolocation error codes.
- OFF_DUTY: clear watch, no new posts, in-memory trail cleared on unmount / dispatch switch / terminal.

---

## 8) Security & Privacy (preserved + added)

- Provisioning: only `require_admin` creates/approves; setup token random `secrets.token_urlsafe(32)`, `sha256` stored, TTL 24h, single-use, rate-limited; no shared default password; role fixed to `responder` (client cannot elevate).
- Dispatch: human-authorized only (`require_authority`); incident coords never from client; radius/candidates backend-only; WS auth unchanged.
- Accept guards: verified+active+AVAILABLE+unassigned+PADDING non-expired; atomic chain prevents double-assign; losing accept gets 409 safe conflict; double-click idempotent.
- Location: responder can only update own fix (token identity); spoofing other id rejected; OFF_DUTY stops collection; terminal stops broadcasts; 2dsphere `[lng,lat]` preserved.
- Victim privacy: `public_view` victim only gets `responder_label + help_on_the_way` + live frame after accept; no network roster, no badge, no other providers.
- Notifications: lock-screen body is generic (distance + expiry, no victim PII); credentials server-side only.
- Audit: extend events (§27) with `PROVIDER_CREATED`, `PROVIDER_VERIFICATION_APPROVED`, `PROVIDER_WENT_ON_DUTY/OFF_DUTY`, `PROVIDER_LOCATION_SHARING_STARTED/STOPPED`, `DISPATCH_WAVE_STARTED`, `PROVIDER_OFFER_CREATED`, `PROVIDER_NOTIFICATION_ATTEMPTED`, `PROVIDER_TIMEOUT`, `DISPATCH_RADIUS_EXPANDED`, etc., using hash-chain `log_audit`; no passwords/tokens/GPS history logged.

---

## 9) Incremental Delivery Phases (reviewable PRs)

1. **Audit & index verification** — run existing tests, verify 2dsphere index script, add wave-field migration (no behavior change).
2. **Responder category & admin create endpoint** — extend `responders` schema + `provision_responder.py` + `POST /admin/responders` + setup token flow + `POST /auth/responder-setup`; add `GET` safe provider list for authority.
3. **Authority Providers page** — `src/app/authority/providers/page.tsx` (tabs, metrics, Add Provider modal, verify/activate controls), `src/lib/dispatch.ts` wrappers.
4. **Freshness buckets fix** — `availability_counts` + `_nearby/_network` staleness, UI LIVE/STALE states, 18-min bug regression test.
5. **Explicit location-sharing consent** — responder page consent copy + permission-denied handling.
6. **Wave config + `_broadcast_wave`** — env parsing, dispatch fields, refactored broadcast per wave (max 6), duplicate-offer guard, early-decline inline vs sweeper.
7. **Wave sweeper + Redis wave lock** — extend `process_expirations`, idempotent deadlines, no-expand-after-assigned, FAILED after exhaustion.
8. **Web Push abstraction** — subscription collection + `services/web_push.py` + honest delivery states + docs.
9. **Offer + authority panel wave polish** — `OfferCard` copy alignment, Rapid Response breakdown (wave badges, counts per wave).
10. **Victim/authority live map privacy pass** — verify victim only sees accepted, trail 40 transient, staleness.
11. **Tests + TS + build + browser E2E** — new suites (§29), `npm run build`, 10-step §30 manual checklist with test jurisdiction.

Each phase runs `pytest` subset + `tsc --noEmit` before next.

---

## 10) Test Plan

**New suites (in `backend/`):**
- `test_provider_management.py`: authorized create (admin 201), non-admin 403, token single-use, role-spoof rejected, off-duty receives no offers, unverified not eligible.
- `test_broadcast_waves.py`: first wave sends ≤6 nearest, duplicate offers prevented, second wave excludes already-offered, radius expands only after wave exhausted, early all-decline advances, pending prevents premature expansion, accepted prevents further expansion, no candidates → FAILED.
- `test_location_freshness.py`: fresh qualifies, stale does not, OFF_DUTY stops tracking, EN_ROUTE WS streams, terminal stops.
- `test_notification_honesty.py`: per-wave attempt, cancelled stops accepting, idempotent retry, failed not reported delivered.
- `test_privacy.py`: victim sees only accepted responder, never network, provider receives only incident location (no victim PII).

**Regression gates (must stay green):**
- `test_rapid_response_network.py`, `test_rrn_authority_views.py`, `test_incident_location.py` (existing), plus full `pytest` and frontend `npx tsc --noEmit` + `npm run build`.

**Browser E2E (§30, safe test jurisdiction, no real dispatches):** 10-step checklist (5 test providers, on-duty + location, dispatch wave 1 offers, accept cancels others, live movement, expand on decline, arrival/help-provided/resolution, off-duty stops, security probes).

---

## 11) Risks & Mitigations

- **Role escalation via client `role` claim** → decode_token forces unverified→`user`; `require_responder` strict `role==responder`; setup token cannot set role.
- **Duplicate broadcast across workers** → Redis `haven:dispatch:wave:{id}` NX lock + Mongo `tried_responder_ids` guard; sweeper idempotent single-doc claims.
- **Stale GPS treated as live** → eligibility + counts + UI all key off `location_updated_at`; never fabricate 0,0.
- **Notification spam** → wave-advance emits only for newly-offered wave; cancelled intents deduplicated by attempt id.
- **Trail persistence leak** → client-only `useState` array sliced to 40, cleared on unmount/dispatch-switch/terminal.

---

## 12) Rollout & Ops Notes

- **Dev:** seed responders via `seed_dev_responders.py` (non-prod only, verified+fresh fix), fake/test push transport, safe test incidents.
- **Prod:** no seeding, verification required, VAPID keys configured, Redis/Mongo required (fail-closed), no shared credentials, audit trail enabled.
- **Env names only:** `DISPATCH_RADIUS_WAVES`, `DISPATCH_MAX_PROVIDERS_PER_WAVE`, `DISPATCH_WAVE_ACCEPT_TIMEOUT_SECONDS`, `DISPATCH_DEFAULT_RADIUS_M`, `RESPONDER_LOCATION_MAX_AGE_SECONDS`, `VAPID_*`, `RESPONDER_SETUP_TOKEN_TTL_HOURS`, `MONGO_ENDPOINT`; never log values.
- **Migration:** additive fields with defaults; old dispatches without `radius_waves` behave as single wave (backward compat).

---

## 13) Open Question (1 remaining to finalize)

**Q1 — Who may open the “Add Provider” form?**

Spec §5–6 says *authority* dashboard has “+ Add Provider” and lists provisioning/approval, but existing code’s trusted provisioning is **admin-only** (`PATCH /admin/responders`, `provision_responder.py`). Two options:

- **A (recommended): Keep creation/verification admin-only.** The `/authority/providers` page is visible to authorities (read-only roster + live views), but the “+ Add Provider” button and the `POST /admin/responders` call are **gated to `require_admin`** (authority sees disabled button + “Contact an admin to add providers” hint). This preserves the existing security invariant that no authority can mint police/provider identities, and requires no RBAC expansion.

- **B:** Allow any `require_authority` to call `POST /admin/responders` → every authority can create police accounts. This is a security expansion and contradicts the current admin workflow.

**Recommendation: Option A.** It matches the existing “verified + admin approval gate”, needs no new elevated-role plumbing, and still satisfies the §16 requirement that authorities can *view* providers while keeping provisioning in the admin’s trusted workflow. If product needs authority-led creation later, add a narrow `provider_manager` role in a follow-up.

*Please confirm Option A, or specify B / another variant, and the plan will be finalized.*

