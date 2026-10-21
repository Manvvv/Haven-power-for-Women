/**
 * HAVEN Rapid Response Network — typed frontend client.
 *
 * Thin, typed wrappers over the backend dispatch/responder REST surface. Reuses
 * the EXISTING secureFetch helper (lib/api.ts) for auth-header attachment — no
 * second auth abstraction is introduced.
 *
 * Trust boundary notes:
 *  - Authority calls rely on the authority session token that secureFetch already
 *    attaches (sessionStorage `haven_authority_token`).
 *  - Responder calls pass the responder session token EXPLICITLY as secureFetch's
 *    customToken, so a responder session never pollutes the authority token slot.
 *  - The victim relies on the Clerk session token secureFetch attaches by default.
 *  - Identity/role are ALWAYS derived server-side from the verified token; nothing
 *    here can elevate a role or spoof a responder_id.
 */
import { secureFetch } from './api'

// ─── Dispatch finite-state machine (mirrors backend lifecycle_service) ──────────
export type DispatchStatus =
  | 'CREATED' | 'SEARCHING' | 'OFFERED' | 'ACCEPTED' | 'EN_ROUTE'
  | 'ARRIVED' | 'HELP_PROVIDED' | 'CANCELLED' | 'EXPIRED' | 'FAILED' | 'RESOLVED'

export type ResponderStatus = 'OFFLINE' | 'AVAILABLE' | 'UNAVAILABLE' | 'BUSY'

export interface GeoPoint { type: 'Point'; coordinates: [number, number] } // [lng, lat]

/** Minimal, truthful dispatch view for the victim (no responder PII). */
export interface VictimDispatchView {
  dispatch_id: string
  case_id: string
  status: DispatchStatus
  created_at?: string | null
  updated_at?: string | null
  assigned_at?: string | null
  distance_type: 'straight_line'
  eta_minutes: number | null
  responder_label: string | null
  help_on_the_way: boolean
}

/** Operational dispatch view for an authority/admin (still no victim PII). */
export interface AuthorityDispatchView {
  dispatch_id: string
  case_id: string
  status: DispatchStatus
  created_at?: string | null
  updated_at?: string | null
  assigned_at?: string | null
  distance_type: 'straight_line'
  eta_minutes: number | null
  created_by?: string
  created_by_role?: string
  assigned_responder_id?: string | null
  responder_label?: string | null
  incident_location?: GeoPoint | null
  incident_jurisdiction?: string
  required_capability?: string | null
  radius_m?: number | null
  notes?: string
  offer_expires_at?: string | null
  accept_timeout_seconds?: number | null
  attempts_made?: number
  resolved_at?: string | null
  cancel_reason?: string
  eligible_provider_count?: number
  offers_pending?: number
  offers_declined?: number
  offers_timeout?: number
  offers_accepted?: number
  broadcast_attempt_ids?: string[]
}

/** The responder's own-record view (never password material). */
export interface ResponderSelf {
  responder_id: string
  badge_number?: string
  display_label?: string
  role: string
  active: boolean
  verified: boolean
  status: ResponderStatus
  /** Duty is a separate axis from availability (backend-owned). */
  duty_status?: 'ON_DUTY' | 'OFF_DUTY'
  capabilities: string[]
  jurisdiction: string
  current_location?: GeoPoint | null
  location_updated_at?: string | null
  assigned_dispatch_id?: string | null
}

/** An offer currently addressed to the signed-in responder. */
export interface ResponderOffer {
  dispatch_id: string
  case_id: string
  status: DispatchStatus
  incident_location?: GeoPoint | null
  required_capability?: string | null
  radius_m?: number | null
  notes?: string
  offer_expires_at?: string | null
  accept_timeout_seconds?: number | null
  attempt_id?: string
  distance_m?: number | null
}

/** Live responder-location frame pushed over /ws/dispatch/{dispatch_id}. */
export interface DispatchLocationFrame {
  dispatch_id: string
  latitude: number
  longitude: number
  timestamp: string
  accuracy?: number
}

// ─── Responder session token (kept separate from the authority token slot) ──────
const RESPONDER_TOKEN_KEY = 'haven_responder_token'
const RESPONDER_ROLE_KEY = 'haven_responder_role'

export function getResponderToken(): string | null {
  if (typeof window === 'undefined') return null
  return sessionStorage.getItem(RESPONDER_TOKEN_KEY)
}
export function setResponderSession(token: string) {
  if (typeof window === 'undefined') return
  sessionStorage.setItem(RESPONDER_TOKEN_KEY, token)
  sessionStorage.setItem(RESPONDER_ROLE_KEY, 'responder')
}
export function clearResponderSession() {
  if (typeof window === 'undefined') return
  sessionStorage.removeItem(RESPONDER_TOKEN_KEY)
  sessionStorage.removeItem(RESPONDER_ROLE_KEY)
}

async function asJson<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `Request failed (${res.status})`
    throw new DispatchError(typeof detail === 'string' ? detail : 'Request failed', res.status)
  }
  return data as T
}

export class DispatchError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'DispatchError'
    this.status = status
  }
}

// ─── AUTHORITY surface (authority session token via secureFetch default) ────────
export async function createDispatch(input: {
  case_id: string
  required_capability?: string | null
  radius_m?: number | null
  notes?: string
}): Promise<{ success: boolean; offered: boolean; dispatch: AuthorityDispatchView }> {
  const res = await secureFetch('/dispatch', {
    method: 'POST',
    body: JSON.stringify({
      case_id: input.case_id,
      required_capability: input.required_capability ?? null,
      radius_m: input.radius_m ?? null,
      notes: input.notes ?? '',
    }),
  })
  return asJson(res)
}

export async function listDispatches(activeOnly = false): Promise<AuthorityDispatchView[]> {
  const res = await secureFetch(`/dispatch?active_only=${activeOnly ? 'true' : 'false'}`)
  const data = await asJson<{ dispatches: AuthorityDispatchView[] }>(res)
  return data.dispatches || []
}

export async function getDispatch(dispatchId: string): Promise<AuthorityDispatchView> {
  const res = await secureFetch(`/dispatch/${encodeURIComponent(dispatchId)}`)
  const data = await asJson<{ dispatch: AuthorityDispatchView }>(res)
  return data.dispatch
}

export async function cancelDispatch(dispatchId: string, reason = ''): Promise<AuthorityDispatchView> {
  const res = await secureFetch(`/dispatch/${encodeURIComponent(dispatchId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
  const data = await asJson<{ dispatch: AuthorityDispatchView }>(res)
  return data.dispatch
}

/**
 * Read the dispatch for a case. The server returns the authority operational view
 * for an observer role and the minimal victim view for the case owner — the SAME
 * endpoint, shaped server-side by the verified token. Returns null when there is
 * no dispatch yet.
 */
export async function getDispatchByCase(
  caseId: string,
): Promise<AuthorityDispatchView | VictimDispatchView | null> {
  const res = await secureFetch(`/dispatch/by-case/${encodeURIComponent(caseId)}`)
  const data = await asJson<{ dispatch: AuthorityDispatchView | VictimDispatchView | null }>(res)
  return data.dispatch
}

// ─── RESPONDER surface (explicit responder token; never the authority slot) ─────
export async function responderMe(): Promise<ResponderSelf> {
  const res = await secureFetch('/responder/me', {}, getResponderToken() || undefined)
  const data = await asJson<{ responder: ResponderSelf }>(res)
  return data.responder
}

export async function setResponderStatus(status: ResponderStatus): Promise<ResponderSelf> {
  const res = await secureFetch(
    '/responder/status',
    { method: 'POST', body: JSON.stringify({ status }) },
    getResponderToken() || undefined,
  )
  const data = await asJson<{ responder: ResponderSelf }>(res)
  return data.responder
}

export async function postResponderLocation(input: {
  latitude: number
  longitude: number
  accuracy?: number | null
}): Promise<{ success: boolean; location_updated_at?: string }> {
  const res = await secureFetch(
    '/responder/location',
    {
      method: 'POST',
      body: JSON.stringify({
        latitude: input.latitude,
        longitude: input.longitude,
        accuracy: input.accuracy ?? null,
      }),
    },
    getResponderToken() || undefined,
  )
  return asJson(res)
}

/** ON_DUTY requires explicit consent to share operational location (backend-enforced). */
export async function setResponderDuty(
  duty: 'ON_DUTY' | 'OFF_DUTY',
  locationSharingConsent: boolean,
): Promise<ResponderSelf> {
  const res = await secureFetch(
    '/responder/duty',
    { method: 'POST', body: JSON.stringify({ duty, location_sharing_consent: locationSharingConsent }) },
    getResponderToken() || undefined,
  )
  const data = await asJson<{ responder: ResponderSelf }>(res)
  return data.responder
}

/** Public VAPID key only. configured=false means in-app offers are the only channel. */
export async function getPushConfig(): Promise<{ configured: boolean; vapid_public_key: string | null }> {
  const res = await secureFetch('/responder/push/config', {}, getResponderToken() || undefined)
  return asJson(res)
}

export async function registerPushSubscription(subscription: PushSubscriptionJSON): Promise<void> {
  const res = await secureFetch(
    '/responder/push-subscription',
    { method: 'POST', body: JSON.stringify({ subscription }) },
    getResponderToken() || undefined,
  )
  await asJson(res)
}

export async function removePushSubscription(): Promise<void> {
  const res = await secureFetch(
    '/responder/push-subscription',
    { method: 'DELETE' },
    getResponderToken() || undefined,
  )
  await asJson(res)
}

export async function getResponderOffers(): Promise<ResponderOffer[]> {
  const res = await secureFetch('/responder/offers', {}, getResponderToken() || undefined)
  const data = await asJson<{ offers: ResponderOffer[] }>(res)
  return data.offers || []
}

/** The responder's own in-progress assignment (responder view), or null. */
export async function getResponderActiveDispatch(): Promise<ResponderOffer | null> {
  const res = await secureFetch('/responder/active-dispatch', {}, getResponderToken() || undefined)
  const data = await asJson<{ dispatch: ResponderOffer | null }>(res)
  return data.dispatch
}

async function responderDispatchAction(
  dispatchId: string,
  action: 'accept' | 'decline' | 'enroute' | 'arrived' | 'help-provided',
): Promise<{ success: boolean; dispatch?: AuthorityDispatchView }> {
  const res = await secureFetch(
    `/dispatch/${encodeURIComponent(dispatchId)}/${action}`,
    { method: 'POST' },
    getResponderToken() || undefined,
  )
  return asJson(res)
}

export const acceptOffer = (id: string) => responderDispatchAction(id, 'accept')
export const declineOffer = (id: string) => responderDispatchAction(id, 'decline')
export const markEnRoute = (id: string) => responderDispatchAction(id, 'enroute')

// ─── PROVIDERS (authority read-only roster; admin-only provisioning) ─────────────
export interface ProviderRow {
  responder_id: string
  display_label: string | null
  status: string | null
  capabilities: string[]
  jurisdiction: string
  on_duty: boolean
  assigned: boolean
  location: { lat: number; lng: number } | null
  location_fresh: boolean
  location_age_seconds: number | null
  verified: boolean
  active: boolean
  duty_status: string
  provider_category: string
  organization: string
  station_unit: string
  active_dispatch_id_present: boolean
  provisioning_state: string
  push_subscribed: boolean
}

/** Authority: read-only provider roster (counts are derived from these real rows). */
export async function getProviderRoster(): Promise<ProviderRow[]> {
  const res = await secureFetch('/dispatch/rrn/providers')
  const data = await asJson<{ providers: ProviderRow[] }>(res)
  return data.providers || []
}

/** ADMIN only. Returns a one-time setup token for out-of-band hand-off. */
export async function adminCreateProvider(input: {
  badge_number: string
  display_name: string
  provider_category: string
  organization?: string
  station_unit?: string
  jurisdiction?: string
  capabilities?: string[]
  contact?: string
}): Promise<{ provider: ProviderRow; setup_token: string; provisioning_state: string }> {
  const res = await secureFetch('/admin/providers', { method: 'POST', body: JSON.stringify(input) })
  return asJson(res)
}

/** ADMIN only. Verify or revoke verification (the human approval gate). */
export async function adminSetProviderVerified(responderId: string, verified: boolean) {
  const res = await secureFetch(`/admin/responders/${encodeURIComponent(responderId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ verified }),
  })
  return asJson(res)
}

/** ADMIN only. Activate or deactivate (suspend) a provider account. */
export async function adminSetProviderActive(responderId: string, active: boolean) {
  const res = await secureFetch(`/admin/responders/${encodeURIComponent(responderId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ active }),
  })
  return asJson(res)
}

/** ADMIN only. Fully revoke a provider: un-verify and deactivate account. */
export async function adminRevokeProvider(responderId: string) {
  const res = await secureFetch(`/admin/responders/${encodeURIComponent(responderId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ verified: false, active: false }),
  })
  return asJson(res)
}

// ─── Authority Provider Registration & Action Requests ───────────────────────────
export interface ProviderRegistration {
  registration_id: string
  unit_name: string
  badge_number: string
  organization: string
  provider_category: string
  jurisdiction: string
  capabilities: string[]
  contact: string
  auth_reference: string
  notes?: string
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED'
  rejection_reason?: string | null
  submitted_by: string
  submitted_by_role: string
  submitted_at: string
  reviewed_by?: string | null
  reviewed_at?: string | null
  created_responder_id?: string | null
  setup_token?: string | null
  setup_token_expires_at?: string | null
  live_provider?: {
    responder_id: string
    provisioning_state: string
    verified: boolean
    active: boolean
    duty_status: string
    status: string
    on_duty: boolean
    location_fresh: boolean
  }
}

export interface ProviderActionRequest {
  request_id: string
  responder_id: string
  badge_number?: string
  display_label?: string
  request_type: 'SUSPENSION' | 'REVOCATION'
  reason: string
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED'
  submitted_by: string
  submitted_at: string
  reviewed_by?: string | null
  reviewed_at?: string | null
  review_notes?: string | null
}

/** Authority submits a provider registration within its jurisdiction for admin review. */
export async function authorityRegisterProvider(input: {
  unit_name: string
  organization: string
  provider_category: string
  jurisdiction: string
  contact: string
  auth_reference: string
  badge_number?: string
  capabilities?: string[]
  notes?: string
}): Promise<{ success: boolean; registration: ProviderRegistration }> {
  const res = await secureFetch('/authority/providers/register', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return asJson(res)
}

/** Authority lists its submitted registrations and their review/setup status. */
export async function authorityGetRegistrations(status?: string): Promise<{ registrations: ProviderRegistration[]; total: number }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await secureFetch(`/authority/providers/registrations${q}`)
  return asJson(res)
}

/** Authority submits a request to suspend or revoke a provider account. */
export async function authorityRequestProviderAction(
  responderId: string,
  requestType: 'SUSPENSION' | 'REVOCATION',
  reason: string,
): Promise<{ success: boolean; request: ProviderActionRequest }> {
  const res = await secureFetch(`/authority/providers/${encodeURIComponent(responderId)}/request-action`, {
    method: 'POST',
    body: JSON.stringify({ request_type: requestType, reason }),
  })
  return asJson(res)
}

/** Authority lists action requests (suspension/revocation) submitted. */
export async function authorityGetActionRequests(status?: string): Promise<{ requests: ProviderActionRequest[]; total: number }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await secureFetch(`/authority/providers/action-requests${q}`)
  return asJson(res)
}

/** ADMIN only: List all provider registrations across jurisdictions. */
export async function adminGetProviderRegistrations(status?: string): Promise<{ registrations: ProviderRegistration[]; total: number }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await secureFetch(`/admin/provider-registrations${q}`)
  return asJson(res)
}

/** ADMIN only: Approve registration, creating inert responder and issuing setup token. */
export async function adminApproveRegistration(registrationId: string): Promise<{
  success: boolean
  registration: ProviderRegistration
  setup_token: string
  setup_token_expires_in_seconds: number
  responder: ProviderRow
  provisioning_state: string
}> {
  const res = await secureFetch(`/admin/provider-registrations/${encodeURIComponent(registrationId)}/approve`, {
    method: 'POST',
  })
  return asJson(res)
}

/** ADMIN only: Reject registration with reason. */
export async function adminRejectRegistration(registrationId: string, reason: string): Promise<{
  success: boolean
  registration: ProviderRegistration
}> {
  const res = await secureFetch(`/admin/provider-registrations/${encodeURIComponent(registrationId)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
  return asJson(res)
}

/** ADMIN only: List all suspension/revocation action requests. */
export async function adminGetProviderRequests(status?: string): Promise<{ requests: ProviderActionRequest[]; total: number }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await secureFetch(`/admin/provider-requests${q}`)
  return asJson(res)
}

/** ADMIN only: Review (approve or reject) a suspension or revocation request. */
export async function adminReviewProviderRequest(requestId: string, action: 'approve' | 'reject', notes?: string): Promise<{
  success: boolean
  request: ProviderActionRequest
}> {
  const res = await secureFetch(`/admin/provider-requests/${encodeURIComponent(requestId)}/review`, {
    method: 'POST',
    body: JSON.stringify({ action, notes }),
  })
  return asJson(res)
}

/** ADMIN only: Re-issue a fresh setup token for an approved-but-password-not-set provider. */
export async function adminReissueSetupToken(responderId: string): Promise<{
  success: boolean
  responder_id: string
  setup_token: string
  setup_token_expires_in_seconds: number
}> {
  const res = await secureFetch(`/admin/providers/${encodeURIComponent(responderId)}/reissue-setup-token`, {
    method: 'POST',
  })
  return asJson(res)
}


export const markArrived = (id: string) => responderDispatchAction(id, 'arrived')
export const markHelpProvided = (id: string) => responderDispatchAction(id, 'help-provided')

// ─── Human-readable, truthful status labels (shared by all audiences) ───────────
export const DISPATCH_STATUS_LABEL: Record<DispatchStatus, string> = {
  CREATED: 'Dispatch created',
  SEARCHING: 'Finding eligible providers…',
  OFFERED: 'Offer sent to eligible providers…',
  ACCEPTED: 'A verified responder accepted',
  EN_ROUTE: 'Responder is en route',
  ARRIVED: 'Responder has arrived',
  HELP_PROVIDED: 'Help provided',
  CANCELLED: 'Dispatch cancelled',
  EXPIRED: 'Offer expired',
  FAILED: 'No eligible responder accepted',
  RESOLVED: 'Resolved',
}

export function helpIsOnTheWay(status: DispatchStatus): boolean {
  return status === 'ACCEPTED' || status === 'EN_ROUTE' || status === 'ARRIVED'
}

// ─── Rapid Response Center read-only authority views (operational visibility) ───
// These three endpoints are READ-ONLY and authority-only. None of them can create,
// route, or force a dispatch — the only way a dispatch is ever created remains the
// human-approved POST /dispatch (createDispatch), which resolves the incident
// location server-side and auto-offers the nearest ELIGIBLE unit. Nothing here lets
// the frontend pick, rank, or force a specific responder.

/** Live operational counts for the summary cards (counts only — never PII). */
export interface RrnMetrics {
  active_dispatches: number
  waiting_for_responder: number
  incidents_in_response: number
  responders_available: number
  responders_busy: number
  responders_on_duty: number
  generated_at: string
}

/**
 * SAFE, authority-facing summary of ONE eligible responder near an incident.
 * This is VISIBILITY only — it is deliberately not an assignment handle. It never
 * carries the officer's real identity, phone, raw GPS, or internal user id.
 *
 * `location` is a deliberate authority/admin-ONLY exposure: a clean {lat,lng} the
 * backend derives from the stored GeoJSON fix (range-validated, 6-dp rounded) so an
 * eligible unit can plot as a real marker on the command map. It is null when no
 * valid fix exists, and it is NEVER present on the victim dispatch view.
 */
export interface NearbyResponder {
  responder_id: string
  display_label: string
  status: ResponderStatus
  capabilities: string[]
  jurisdiction: string
  distance_m: number | null
  distance_type: 'straight_line'
  location_age_seconds: number | null
  location_fresh: boolean
  location: { lat: number; lng: number } | null
}

export interface NearbyResult {
  incident_resolved: boolean
  incident_jurisdiction?: string
  radius_m?: number
  responders: NearbyResponder[]
}

/** One truthful marker on a dispatch's state-change timeline (safe detail only). */
export interface DispatchTimelineEntry {
  event: string
  at: string | null
  detail: { responder_id?: string; reason?: string; via?: string }
}

/** Live Rapid Response Center summary counts (authority session token). */
export async function getRrnMetrics(): Promise<RrnMetrics> {
  const res = await secureFetch('/dispatch/rrn/metrics')
  const data = await asJson<{ metrics: RrnMetrics }>(res)
  return data.metrics
}

/**
 * Backend-ranked eligible responders near a case's incident (authority-only).
 * The incident point and the eligible set are decided SERVER-SIDE; the frontend
 * cannot widen or re-order who is eligible — any filter/sort applied in the UI is
 * presentation-only over this already-authoritative list.
 */
export async function getNearbyResponders(caseId: string): Promise<NearbyResult> {
  const res = await secureFetch(`/dispatch/rrn/nearby/${encodeURIComponent(caseId)}`)
  return asJson<NearbyResult>(res)
}

/** One broadcast offer attempt for an incident (authority-only visibility). */
export interface DispatchOffer {
  attempt_id: string
  responder_id: string
  display_label: string
  response: 'PENDING' | 'ACCEPTED' | 'DECLINED' | 'TIMEOUT' | 'CANCELLED'
  offered_at: string | null
  responded_at: string | null
  distance_m: number | null
}

/** Chronological state-change markers for one dispatch (authority-only). */
export async function getDispatchTimeline(dispatchId: string): Promise<DispatchTimelineEntry[]> {
  const res = await secureFetch(`/dispatch/${encodeURIComponent(dispatchId)}/timeline`)
  const data = await asJson<{ timeline: DispatchTimelineEntry[] }>(res)
  return data.timeline || []
}

/** All broadcast offers sent for an emergency dispatch (authority-only). */
export async function getDispatchOffers(dispatchId: string): Promise<DispatchOffer[]> {
  const res = await secureFetch(`/dispatch/${encodeURIComponent(dispatchId)}/offers`)
  const data = await asJson<{ offers: DispatchOffer[] }>(res)
  return data.offers || []
}

/**
 * SAFE, authority-facing roster row for ONE verified responder (network-wide).
 * Like NearbyResponder this is VISIBILITY only, never an assignment handle, and
 * never carries officer identity, phone, badge, internal id, or which dispatch a
 * busy unit holds. `on_duty` = active AND verified; `assigned` = holds a live
 * assignment OR is BUSY. `location` is the clean {lat,lng} map pin ONLY for an
 * on-duty unit with a fresh fix (null otherwise); it is never on the victim path.
 */
export interface NetworkResponder {
  responder_id: string
  display_label: string
  status: ResponderStatus
  capabilities: string[]
  jurisdiction: string
  on_duty: boolean
  assigned: boolean
  location: { lat: number; lng: number } | null
  location_fresh: boolean
  location_age_seconds: number | null
}

/**
 * Authority-only overview of the whole verified-responder network. `summary`
 * reuses the same counts as the Rapid Response Center metric cards, so network
 * availability and the summary never disagree. This is NOT incident eligibility —
 * a unit here is on duty, not necessarily eligible for a specific incident.
 */
export interface ResponderNetwork {
  summary: {
    responders_available: number
    responders_busy: number
    responders_on_duty: number
  }
  responders: NetworkResponder[]
  generated_at: string
}

/**
 * The verified-responder roster + duty counts (authority-only). The backend
 * decides who is a real unit (verified + active) and provides a safe, baseline
 * ordering; any re-sort/filter the UI applies is presentation-only and can never
 * widen the network or force a unit onto a dispatch.
 */
export async function getResponderNetwork(): Promise<ResponderNetwork> {
  const res = await secureFetch('/dispatch/rrn/network')
  return asJson<ResponderNetwork>(res)
}

