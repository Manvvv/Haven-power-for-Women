'use client'
/**
 * HAVEN — Rapid Response Center (dedicated authority section, /authority/rapid-response).
 *
 * A top-level operations surface for authorities to see live emergencies, the
 * verified-responder network near each incident, and the state of every
 * human-approved dispatch — WITHOUT touching the SOS case list.
 *
 * Security model (unchanged, enforced server-side):
 *  - The ONLY way a dispatch is created is the human-approved POST /dispatch
 *    (createDispatch). The backend resolves the incident location from the case's
 *    OWN stored GPS fix; this page never sends coordinates and cannot override them.
 *  - "Nearby Response Units" is READ-ONLY visibility. There is deliberately NO
 *    "assign THIS unit" control: the engine auto-offers the nearest ELIGIBLE unit
 *    and that unit must ACCEPT. An authority approves a dispatch, not a responder.
 *  - Every filter/sort here is presentation-only over the backend-authoritative
 *    eligible set — it can never widen or re-rank who is eligible.
 *  - All responder data shown is the SAFE view (label + distance + freshness); no
 *    officer identity, phone, raw GPS, or internal id ever reaches the browser.
 *  - The live map observes the EXISTING authenticated /ws/dispatch room only while
 *    a unit is ACCEPTED / EN_ROUTE / ARRIVED, exactly as the backend authorizes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Shield, RefreshCw, Users, AlertTriangle, Radio,
  MapPin, Clock, CheckCircle, X, Navigation, Lock, Copy, Maximize2,
  Activity, Signal,
} from 'lucide-react'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { secureFetch, getAuthorityToken } from '@/lib/api'
import { fixAgeSeconds, classifyFix } from '@/lib/locationFreshness'
import LiveResponseMap, { MapMarker, UnitMarker } from '@/components/LiveResponseMap'
import {
  listDispatches, createDispatch, cancelDispatch,
  getRrnMetrics, getNearbyResponders, getDispatchTimeline, getDispatchOffers, getResponderNetwork,
  AuthorityDispatchView, DispatchStatus, RrnMetrics,
  NearbyResult, DispatchTimelineEntry, DispatchOffer, ResponderNetwork, NetworkResponder,
} from '@/lib/dispatch'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Rose/maroon palette matching the Authority Dashboard chrome.
const C = {
  bg: '#f8f4f6', ink: '#1a0a12', panel: '#ffffff', line: '#ecdfe6',
  accent: '#db2777', accentSoft: '#fce7f1', muted: '#8b6b7d', text: '#3b2733',
}

// Shared style for the presentation-only filter dropdowns.
const selectStyle: React.CSSProperties = {
  background: '#fff', border: `1px solid ${C.line}`, borderRadius: 8,
  padding: '6px 10px', fontSize: 12, color: C.text, cursor: 'pointer',
}

/**
 * Minimal shape of an SOS case as returned by GET /cases (authority view). We only
 * read presentation fields here; the authoritative case data lives server-side.
 */
interface SOSCase {
  case_id: string
  severity?: string
  nature_of_abuse?: string
  immediate_danger?: boolean
  location?: string
  summary?: string
  status?: string
  created_at?: string
  trigger_type?: string
}

const TERMINAL: ReadonlySet<DispatchStatus> = new Set<DispatchStatus>([
  'HELP_PROVIDED', 'CANCELLED', 'EXPIRED', 'FAILED', 'RESOLVED',
])
const isTerminal = (s?: DispatchStatus | null) => !!s && TERMINAL.has(s)

// Statuses during which the backend authorizes the /ws/dispatch room to carry a
// live responder location frame. Mirrors the backend's broadcast gate exactly.
const OBSERVABLE: ReadonlySet<DispatchStatus> = new Set<DispatchStatus>([
  'ACCEPTED', 'EN_ROUTE', 'ARRIVED',
])
const isObservable = (s?: DispatchStatus | null) => !!s && OBSERVABLE.has(s)

/**
 * Parse a human-entered "lat, lng" case location string into a display-only map
 * marker. This is PRESENTATION ONLY — it never feeds dispatch; the backend resolves
 * the authoritative incident fix from the case's stored GPS and ignores anything
 * the browser sends. Returns null when the string is not a clean coordinate pair.
 */
function parseLatLngString(s?: string | null): MapMarker | null {
  if (!s) return null
  const m = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/.exec(s)
  if (!m) return null
  const lat = Number(m[1])
  const lng = Number(m[2])
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null
  return { lat, lng }
}

/** Visual phase descriptor derived from a dispatch's authoritative status. */
interface PhaseView { label: string; fg: string; bg: string; dot: string }

/**
 * Map a dispatch to a granular, truthful phase label. We NEVER collapse the
 * lifecycle: every FSM state has its own distinct, honest label (section 2). The
 * status itself is always backend-owned. "Escalating" is shown SEPARATELY (as a
 * secondary note derived from attempts_made) rather than overwriting the real
 * state label, so the primary label always tells the literal truth.
 */
function phaseView(d?: AuthorityDispatchView | null): PhaseView {
  if (!d) return { label: 'No dispatch', fg: C.muted, bg: '#f3eef1', dot: C.muted }
  switch (d.status) {
    case 'CREATED':
      return { label: 'Dispatch created', fg: '#8a5a00', bg: '#fff4e0', dot: '#f59e0b' }
    case 'SEARCHING':
      return { label: '🔎 Searching for eligible responder', fg: '#8a5a00', bg: '#fff4e0', dot: '#f59e0b' }
    case 'OFFERED':
      return { label: '📡 Responder notified — waiting for acceptance', fg: '#8a5a00', bg: '#fff4e0', dot: '#f59e0b' }
    case 'ACCEPTED':
      return { label: '✅ Responder accepted', fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
    case 'EN_ROUTE':
      return { label: '🚔 Help is on the way', fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
    case 'ARRIVED':
      return { label: '📍 Responder has arrived', fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
    case 'HELP_PROVIDED':
      return { label: '🛡 Help provided', fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
    case 'RESOLVED':
      return { label: '✅ Response resolved', fg: '#3f3f46', bg: '#f4f4f5', dot: '#71717a' }
    case 'CANCELLED':
      return { label: 'Dispatch cancelled', fg: '#3f3f46', bg: '#f4f4f5', dot: '#71717a' }
    case 'EXPIRED':
      return { label: 'Offer expired — no responder accepted in time', fg: '#9a3412', bg: '#ffedd5', dot: '#ea580c' }
    case 'FAILED':
      return { label: '⚠ No responder accepted the emergency', fg: '#991b1b', bg: '#fee2e2', dot: '#dc2626' }
    default:
      return { label: String(d.status), fg: C.muted, bg: '#f3eef1', dot: C.muted }
  }
}

/** True when the engine has had to re-offer (a prior unit declined or timed out). */
function isEscalating(d?: AuthorityDispatchView | null): boolean {
  if (!d) return false
  return (d.status === 'SEARCHING' || d.status === 'OFFERED') && (d.attempts_made ?? 0) > 1
}

/** Compact "updated Ns/Nm ago" from an age in seconds (safe freshness only). */
function ageLabel(seconds: number | null): string {
  if (seconds == null) return 'location unknown'
  if (seconds < 60) return `updated ${seconds}s ago`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `updated ${m}m ago`
  const h = Math.floor(m / 60)
  return `updated ${h}h ago`
}

/** One summary metric card. Values come straight from GET /dispatch/rrn/metrics. */
function MetricCard(props: {
  icon: React.ReactNode; label: string; value: number | string; accent: string; hint?: string
}) {
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.line}`, borderRadius: 14,
      padding: '16px 18px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: props.accent }}>
        {props.icon}
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: 'uppercase', color: C.muted }}>
          {props.label}
        </span>
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, color: C.ink, lineHeight: 1 }}>{props.value}</div>
      {props.hint ? <div style={{ fontSize: 12, color: C.muted }}>{props.hint}</div> : null}
    </div>
  )
}

/** A small status pill used for both dispatch phase and responder availability. */
function Pill(props: { text: string; fg: string; bg: string; dot?: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
      borderRadius: 999, fontSize: 12, fontWeight: 700, color: props.fg, background: props.bg,
    }}>
      {props.dot ? <span style={{ width: 7, height: 7, borderRadius: 999, background: props.dot }} /> : null}
      {props.text}
    </span>
  )
}

const SEVERITY_TONE: Record<string, { fg: string; bg: string }> = {
  critical: { fg: '#991b1b', bg: '#fee2e2' },
  high: { fg: '#9a3412', bg: '#ffedd5' },
  medium: { fg: '#8a5a00', bg: '#fff4e0' },
  low: { fg: '#3f3f46', bg: '#f4f4f5' },
}
function severityTone(s?: string) {
  return SEVERITY_TONE[(s || '').toLowerCase()] || { fg: C.muted, bg: '#f3eef1' }
}

/** Straight-line distance label (meters → m/km). Never implies routed travel. */
function fmtDistance(m: number | null): string {
  if (m == null) return 'distance unknown'
  if (m < 1000) return `${m} m away`
  return `${(m / 1000).toFixed(m < 10000 ? 1 : 0)} km away`
}

/** Readable 6-dp coordinate string for display/copy. Never alters backend precision. */
function formatCoord(m: MapMarker | null): string | null {
  if (!m) return null
  return `${m.lat.toFixed(6)}°, ${m.lng.toFixed(6)}°`
}

type LiveTone = 'green' | 'yellow' | 'orange' | 'red' | 'grey'
const MAP_DOT_COLORS: Record<LiveTone, string> = {
  green: '#22c55e', yellow: '#eab308', orange: '#f59e0b', red: '#dc2626', grey: '#9ca3af',
}

/** The single truthful connection + responder-location state for the live panel. */
interface LiveState { dotLabel: string; dotTone: LiveTone; locationLine: string; locationColor: string }

/**
 * Derive the ONE honest live-response state from the authoritative dispatch status
 * and the real socket/frame facts. This is the fix for the misleading
 * "Awaiting responder location" / premature "Connected":
 *  - with no dispatch, or before an actual ACCEPT, we say "waiting for acceptance"
 *    / "no responder assigned yet" and never claim a live connection;
 *  - only once the backend-observable window is open do we talk about connecting,
 *    live, reconnecting, or stale — exactly mirroring the socket;
 *  - "🟢 Live" is only ever reached inside an ACCEPTED/EN_ROUTE/ARRIVED dispatch.
 */
function deriveLiveState(args: {
  dispatch: AuthorityDispatchView | null
  observing: boolean
  wsConnected: boolean
  wsInterrupted: boolean
  hasFrame: boolean
  /** Age of the responder's GPS fix (from its own timestamp), or null if unknown. */
  fixAgeSecs: number | null
}): LiveState {
  const d = args.dispatch
  if (!d) {
    return { dotLabel: '⚪ No responder dispatched', dotTone: 'grey',
      locationLine: 'No responder has been dispatched for this incident yet.', locationColor: C.muted }
  }
  switch (d.status) {
    case 'FAILED':
      return { dotLabel: '🔴 No responder accepted', dotTone: 'red',
        locationLine: 'No responder accepted the emergency.', locationColor: '#991b1b' }
    case 'HELP_PROVIDED':
      return { dotLabel: '⚪ Response ended', dotTone: 'grey',
        locationLine: 'Help was provided — this response is complete.', locationColor: C.muted }
    case 'RESOLVED':
      return { dotLabel: '⚪ Response ended', dotTone: 'grey',
        locationLine: 'This response has been resolved.', locationColor: C.muted }
    case 'CANCELLED':
      return { dotLabel: '⚪ Response ended', dotTone: 'grey',
        locationLine: 'This dispatch was cancelled.', locationColor: C.muted }
    case 'EXPIRED':
      return { dotLabel: '⚪ Response ended', dotTone: 'grey',
        locationLine: 'The offer expired before any responder accepted.', locationColor: C.muted }
    case 'CREATED':
    case 'SEARCHING':
      return { dotLabel: '⚪ Waiting for responder acceptance', dotTone: 'grey',
        locationLine: 'No responder assigned yet.', locationColor: C.muted }
    case 'OFFERED':
      return { dotLabel: '⚪ Waiting for responder acceptance', dotTone: 'grey',
        locationLine: 'Waiting for responder acceptance.', locationColor: C.muted }
    default:
      break
  }
  // Observable window (ACCEPTED / EN_ROUTE / ARRIVED): now the socket is authorized.
  if (!args.wsConnected && args.wsInterrupted) {
    return { dotLabel: '🟡 Reconnecting…', dotTone: 'yellow',
      locationLine: 'Live connection interrupted — reconnecting…', locationColor: '#9a3412' }
  }
  if (!args.wsConnected) {
    return { dotLabel: '🟡 Connecting to live response', dotTone: 'yellow',
      locationLine: 'Awaiting responder location…', locationColor: '#8a5a00' }
  }
  if (!args.hasFrame) {
    return {
      dotLabel: '🟡 Assigned — awaiting GPS',
      dotTone: 'yellow',
      locationLine: 'Responder assigned — waiting for first location update.',
      locationColor: '#8a5a00',
    }
  }
  // Location freshness is the FIX age (from the responder's own GPS timestamp), judged
  // by the shared policy (300s, same as the backend). Stream silence is NOT used as a
  // proxy for location age: a quiet socket with a fresh fix is still a current fix.
  const fix = classifyFix(args.fixAgeSecs)
  if (fix !== 'FRESH') {
    return { dotLabel: fix === 'STALE' ? '🟠 Location update is stale' : '🟡 Location time unknown',
      dotTone: fix === 'STALE' ? 'orange' : 'yellow',
      locationLine: fix === 'STALE'
        ? `Responder location is stale (last GPS fix ${args.fixAgeSecs}s ago). Not shown as current.`
        : 'Responder location time is unknown. Not shown as current.',
      locationColor: '#9a3412' }
  }
  return { dotLabel: '🟢 Live', dotTone: 'green',
    locationLine: `Live responder location — GPS fix ${args.fixAgeSecs}s old.`, locationColor: '#166534' }
}

/**
 * Honest availability pill for a network roster unit.
 *
 * The backend already gates `on_duty` through active+verified+duty_status, and
 * only returns `location_fresh=true` for a fix within MAX_AGE. We surface that
 * here so operators can never be misled by a green "AVAILABLE" badge on a unit
 * that is off-duty or has a stale location fix.
 *
 *  - AVAILABLE + on_duty + location_fresh → green AVAILABLE
 *  - AVAILABLE + on_duty + !location_fresh → amber STALE LOCATION
 *  - BUSY / assigned                        → orange BUSY
 *  - !on_duty                               → grey OFF DUTY
 *  - anything else (OFFLINE / UNAVAILABLE)  → grey
 */
function statusToneForUnit(
  status: string,
  on_duty: boolean,
  location_fresh: boolean,
): { label: string; fg: string; bg: string; dot: string } {
  if (!on_duty) return { label: 'OFF DUTY', fg: C.muted, bg: '#f3eef1', dot: C.muted }
  if (status === 'BUSY') return { label: 'BUSY', fg: '#9a3412', bg: '#ffedd5', dot: '#ea580c' }
  if (status === 'AVAILABLE') {
    if (!location_fresh) return { label: 'STALE LOCATION', fg: '#92400e', bg: '#fef3c7', dot: '#d97706' }
    return { label: 'AVAILABLE', fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
  }
  if (status === 'UNAVAILABLE') return { label: 'UNAVAILABLE', fg: C.muted, bg: '#f3eef1', dot: C.muted }
  return { label: status || 'OFFLINE', fg: C.muted, bg: '#f3eef1', dot: C.muted }
}

/** Availability pill tone for a responder status (shared by nearby + network). */
function statusTone(status: string): { fg: string; bg: string; dot: string } {
  if (status === 'AVAILABLE') return { fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
  if (status === 'BUSY') return { fg: '#9a3412', bg: '#ffedd5', dot: '#ea580c' }
  return { fg: C.muted, bg: '#f3eef1', dot: C.muted }
}

/**
 * Map a verified-network responder to a SECONDARY ○ map marker. This is coverage
 * VISIBILITY only — a ○ never means "assigned". The 🚔 glyph is reserved for the
 * single accepted responder on an incident map; the network map has no 🚔 at all.
 * Kind drives colour only: AVAILABLE+fresh→blue, BUSY/assigned→purple, else grey.
 */
function networkUnitKind(r: NetworkResponder): UnitMarker['kind'] {
  if (r.assigned || r.status === 'BUSY') return 'busy'
  if (r.status === 'AVAILABLE' && r.on_duty && r.location_fresh) return 'eligible'
  return 'offline'
}

export default function RapidResponsePage() {
  // Reuse the SAME authority gate the dashboard uses; no second auth path.
  useHavenAuth()
  const [authorized, setAuthorized] = useState<boolean | null>(null)

  // Live operational data (all backend-authoritative).
  const [metrics, setMetrics] = useState<RrnMetrics | null>(null)
  const [cases, setCases] = useState<SOSCase[]>([])
  const [dispatches, setDispatches] = useState<AuthorityDispatchView[]>([])
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  // Selected incident + its nearby units / timeline.
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [nearby, setNearby] = useState<NearbyResult | null>(null)
  const [nearbyErr, setNearbyErr] = useState<string | null>(null)
  const [nearbyLoading, setNearbyLoading] = useState(false)
  const [nearbyCheckedAt, setNearbyCheckedAt] = useState<number | null>(null)
  const [timeline, setTimeline] = useState<DispatchTimelineEntry[]>([])

  // Presentation-only UI state for the selected-incident panel.
  const [fullMapOpen, setFullMapOpen] = useState(false)
  const [copiedCoord, setCopiedCoord] = useState(false)

  // Presentation-only filters over the backend's already-eligible nearby set.
  const [capFilter, setCapFilter] = useState('')
  const [jurFilter, setJurFilter] = useState('')
  const [maxKm, setMaxKm] = useState<number>(0) // 0 = no cap
  const [sortBy, setSortBy] = useState<'distance' | 'freshness'>('distance')
  const [expandedUnit, setExpandedUnit] = useState<string | null>(null)

  // Which top-level view is showing. "operations" = live incidents + dispatch;
  // "network" = the verified-responder network overview (counts + roster + coverage
  // map). Both are read-only; neither can create or force a dispatch.
  const [view, setView] = useState<'operations' | 'network'>('operations')

  // Verified-responder network overview (authority-only, backend-authoritative).
  const [network, setNetwork] = useState<ResponderNetwork | null>(null)
  const [networkErr, setNetworkErr] = useState<string | null>(null)
  const [networkLoading, setNetworkLoading] = useState(false)
  const [networkCheckedAt, setNetworkCheckedAt] = useState<number | null>(null)
  // Presentation-only network filters (can only hide/reorder the real roster).
  const [netStatusFilter, setNetStatusFilter] = useState('')
  const [netSort, setNetSort] = useState<'status' | 'jurisdiction'>('status')

  // Human-approved dispatch confirmation modal.
  const [confirmCase, setConfirmCase] = useState<SOSCase | null>(null)
  const [confirmNotes, setConfirmNotes] = useState('')
  const [dispatchBusy, setDispatchBusy] = useState(false)
  const [dispatchErr, setDispatchErr] = useState<string | null>(null)

  // Live responder frame over the authenticated /ws/dispatch room.
  const [liveFrame, setLiveFrame] = useState<MapMarker | null>(null)
  const [movementTrail, setMovementTrail] = useState<Array<{ lat: number; lng: number }>>([])
  const [fitNonce, setFitNonce] = useState(0)
  const [offers, setOffers] = useState<DispatchOffer[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [wsInterrupted, setWsInterrupted] = useState(false)
  const [lastFrameAt, setLastFrameAt] = useState<number | null>(null)
  const [, forceTick] = useState(0) // drives the "last updated Ns ago" relative clock

  const nearbyBusyRef = useRef(false)
  const networkBusyRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const wsRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wsClosedByUs = useRef(false)

  // ── Derived lookups ────────────────────────────────────────────────────────
  const dispatchByCase = useMemo(() => {
    const m = new Map<string, AuthorityDispatchView>()
    // listDispatches may contain historical rows; keep the most recent per case.
    for (const d of dispatches) {
      const prev = m.get(d.case_id)
      if (!prev) { m.set(d.case_id, d); continue }
      const a = d.updated_at || d.created_at || ''
      const b = prev.updated_at || prev.created_at || ''
      if (a >= b) m.set(d.case_id, d)
    }
    return m
  }, [dispatches])

  const selectedCase = useMemo(
    () => cases.find((c) => c.case_id === selectedCaseId) || null,
    [cases, selectedCaseId],
  )
  const selectedDispatch = selectedCaseId ? dispatchByCase.get(selectedCaseId) || null : null

  const emergencies = useMemo(() => {
    const rank = (c: SOSCase) => {
      const sev = (c.severity || '').toLowerCase()
      const base = sev === 'critical' ? 0 : sev === 'high' ? 1 : sev === 'medium' ? 2 : 3
      return (c.immediate_danger ? -1 : 0) + base
    }
    return [...cases].sort((a, b) => {
      const r = rank(a) - rank(b)
      if (r !== 0) return r
      return (b.created_at || '').localeCompare(a.created_at || '')
    })
  }, [cases])

  // ── Auth presence (dashboard uses the same sessionStorage token) ────────────
  useEffect(() => {
    setAuthorized(!!getAuthorityToken())
  }, [])

  // ── Poll the operational summary + emergencies + dispatches every 5s ────────
  const loadAll = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true)
    try {
      const [m, ds, caseRes] = await Promise.all([
        getRrnMetrics(),
        listDispatches(false),
        secureFetch('/cases').then((r) => r.json()).catch(() => ({ cases: [] })),
      ])
      setMetrics(m)
      const newDispatches: typeof ds = Array.isArray(ds) ? ds : []
      const newCases: SOSCase[] = Array.isArray(caseRes?.cases) ? caseRes.cases : []
      setDispatches(newDispatches)
      setCases(newCases)
      setLoadErr(null)
      setLastUpdated(new Date().toISOString())

      // ── Selection consistency guard ─────────────────────────────────────
      // After each poll, verify the selected case_id still refers to a real,
      // known case. A case may not be in the top-50 GET /cases response if it
      // is older, but we keep the selection as long as it has an active dispatch
      // (so the detail panel stays stable). Only clear the selection when the
      // case_id is not in the new case list AND has no dispatch at all, which
      // means it no longer exists or was pruned — silently displaying a different
      // case is the exact bug the user reported (Phase 1).
      setSelectedCaseId((prev) => {
        if (!prev) return prev
        const inCases = newCases.some((c) => c.case_id === prev)
        if (inCases) return prev  // still in the active list — keep selection
        const inDispatches = newDispatches.some((d) => d.case_id === prev)
        if (inDispatches) return prev  // has a dispatch even if not in top-50 — keep
        // The case_id is gone from both lists: clear to avoid a phantom selection
        return null
      })
    } catch (e: unknown) {
      setLoadErr(e instanceof Error ? e.message : 'Could not load live data.')
    } finally {
      if (showSpinner) setRefreshing(false)
    }
  }, [])


  useEffect(() => {
    if (authorized !== true) return
    loadAll(false)
    const id = setInterval(() => loadAll(false), 5000)
    return () => clearInterval(id)
  }, [authorized, loadAll])

  // A 1s heartbeat so relative "last updated Ns ago" labels stay honest.
  useEffect(() => {
    const id = setInterval(() => forceTick((n) => (n + 1) % 1_000_000), 1000)
    return () => clearInterval(id)
  }, [])

  // Escape closes the open overlay (full-map viewer, or the dispatch modal when not
  // mid-submit) — keyboard parity for the modal dialogs (accessibility).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (fullMapOpen) { setFullMapOpen(false); return }
      if (confirmCase && !dispatchBusy) setConfirmCase(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullMapOpen, confirmCase, dispatchBusy])

  // ── Nearby eligible units for the selected incident (backend-ranked) ────────
  const loadNearby = useCallback(async (caseId: string) => {
    setNearbyLoading(true)
    try {
      const res = await getNearbyResponders(caseId)
      setNearby(res)
      setNearbyErr(null)
    } catch (e: unknown) {
      setNearby(null)
      setNearbyErr(e instanceof Error ? e.message : 'Could not load nearby units.')
    } finally {
      setNearbyLoading(false)
      setNearbyCheckedAt(Date.now())
    }
  }, [])

  // Debounced "Refresh nearby units" (min 1.5s between manual refreshes).
  const refreshNearby = useCallback(() => {
    if (!selectedCaseId || nearbyBusyRef.current) return
    nearbyBusyRef.current = true
    loadNearby(selectedCaseId).finally(() => {
      setTimeout(() => { nearbyBusyRef.current = false }, 1500)
    })
  }, [selectedCaseId, loadNearby])

  // ── Verified-responder network overview (authority-only, read-only) ─────────
  // The backend decides who is a real verified unit and provides the baseline
  // ordering + duty counts. Anything the UI filters/sorts here is presentation
  // only; it can never widen the network or make a unit assignable.
  const loadNetwork = useCallback(async () => {
    setNetworkLoading(true)
    try {
      const res = await getResponderNetwork()
      setNetwork(res)
      setNetworkErr(null)
    } catch (e: unknown) {
      setNetwork(null)
      setNetworkErr(e instanceof Error ? e.message : 'Could not load the response network.')
    } finally {
      setNetworkLoading(false)
      setNetworkCheckedAt(Date.now())
    }
  }, [])

  // Poll the network only while its view is open (keeps it fresh without extra
  // load when the operator is on the operations view).
  useEffect(() => {
    if (authorized !== true || view !== 'network') return
    loadNetwork()
    const id = setInterval(loadNetwork, 5000)
    return () => clearInterval(id)
  }, [authorized, view, loadNetwork])

  // Debounced manual "Refresh network" (min 1.5s between manual refreshes).
  const refreshNetwork = useCallback(() => {
    if (networkBusyRef.current) return
    networkBusyRef.current = true
    loadNetwork().finally(() => {
      setTimeout(() => { networkBusyRef.current = false }, 1500)
    })
  }, [loadNetwork])

  // On selection change: reset per-incident state and fetch nearby + timeline.
  useEffect(() => {
    setNearby(null); setNearbyErr(null); setTimeline([]); setNearbyCheckedAt(null)
    setLiveFrame(null); setMovementTrail([]); setWsInterrupted(false); setLastFrameAt(null)
    setOffers([]); setFullMapOpen(false); setExpandedUnit(null)
    if (!selectedCaseId) return
    loadNearby(selectedCaseId)
  }, [selectedCaseId, loadNearby])

  // Keep the selected incident's timeline & broadcast offers fresh while a dispatch exists.
  useEffect(() => {
    if (!selectedDispatch) { setTimeline([]); setOffers([]); return }
    let alive = true
    const pull = () => {
      getDispatchTimeline(selectedDispatch.dispatch_id)
        .then((t) => { if (alive) setTimeline(t) })
        .catch(() => { /* timeline is best-effort visibility */ })
      getDispatchOffers(selectedDispatch.dispatch_id)
        .then((o) => { if (alive) setOffers(o) })
        .catch(() => { /* offers is best-effort visibility */ })
    }
    pull()
    const id = setInterval(pull, 5000)
    return () => { alive = false; clearInterval(id) }
  }, [selectedDispatch?.dispatch_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Observe the authenticated /ws/dispatch room (ONLY while observable) ─────
  // The backend authorizes a live responder location frame only during
  // ACCEPTED / EN_ROUTE / ARRIVED. We open the room exactly for those states,
  // mirror the dashboard's WS auth pattern, and reconnect with capped backoff.
  const observeDispatchId = selectedDispatch && isObservable(selectedDispatch.status)
    ? selectedDispatch.dispatch_id
    : null
  const observing = observeDispatchId !== null

  useEffect(() => {
    // Tear down any prior socket + pending retry when the target changes.
    const cleanup = () => {
      wsClosedByUs.current = true
      if (wsRetryRef.current) { clearTimeout(wsRetryRef.current); wsRetryRef.current = null }
      if (wsRef.current) { try { wsRef.current.close() } catch { /* noop */ } wsRef.current = null }
    }
    cleanup()
    setWsConnected(false)

    if (!observeDispatchId) { setWsInterrupted(false); return }

    wsClosedByUs.current = false
    let attempt = 0

    const connect = () => {
      const token = getAuthorityToken() || ''
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsHost = API.replace(/^https?:\/\//, '') || 'localhost:8000'
      const url =
        `${wsProtocol}//${wsHost}/ws/dispatch/${encodeURIComponent(observeDispatchId)}` +
        `?token=${encodeURIComponent(token)}`
      let ws: WebSocket
      try { ws = new WebSocket(url) } catch { scheduleRetry(); return }
      wsRef.current = ws

      ws.onopen = () => { attempt = 0; setWsConnected(true); setWsInterrupted(false) }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          const lat = Number(msg.latitude)
          const lng = Number(msg.longitude)
          if (Number.isFinite(lat) && Number.isFinite(lng)) {
            setLiveFrame({ lat, lng, accuracy: msg.accuracy, timestamp: msg.timestamp })
            setLastFrameAt(Date.now())
            setMovementTrail((prev) => {
              const next = [...prev, { lat, lng }]
              return next.slice(-40) // maximum 40 recent real GPS frames
            })
          }
        } catch { /* ignore non-JSON frames */ }
      }
      ws.onclose = () => {
        setWsConnected(false)
        if (!wsClosedByUs.current) { setWsInterrupted(true); scheduleRetry() }
      }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
    }

    const scheduleRetry = () => {
      if (wsClosedByUs.current) return
      attempt = Math.min(attempt + 1, 5)
      const delay = Math.min(1000 * 2 ** (attempt - 1), 15000) // 1s→15s cap
      wsRetryRef.current = setTimeout(connect, delay)
    }

    connect()
    return cleanup
  }, [observeDispatchId])

  // ── Human-approved dispatch (the ONLY create path) ─────────────────────────
  const submitDispatch = useCallback(async () => {
    if (!confirmCase) return
    setDispatchBusy(true); setDispatchErr(null)
    try {
      // We send ONLY the case id (+ optional operator note). The backend resolves
      // the incident location from the case's own stored GPS and auto-offers the
      // nearest ELIGIBLE unit. The browser never sends coordinates or a responder.
      const r = await createDispatch({ case_id: confirmCase.case_id, notes: confirmNotes.trim() })
      setConfirmCase(null); setConfirmNotes('')
      setSelectedCaseId(r.dispatch.case_id)
      await loadAll(false)
    } catch (e: unknown) {
      // Surface the backend's honest reason (e.g. 409 "no valid GPS fix") verbatim.
      setDispatchErr(e instanceof Error ? e.message : 'Dispatch could not be created.')
    } finally {
      setDispatchBusy(false)
    }
  }, [confirmCase, confirmNotes, loadAll])

  const doCancel = useCallback(async (d: AuthorityDispatchView) => {
    try {
      await cancelDispatch(d.dispatch_id, 'Cancelled by authority from Rapid Response Center')
      await loadAll(false)
    } catch { /* a failed cancel leaves state unchanged; next poll re-syncs */ }
  }, [loadAll])

  // ── Presentation-only view over the backend-eligible nearby set ─────────────
  // These controls can only HIDE or REORDER rows the backend already deemed
  // eligible — they can never add a unit or change who is actually eligible.
  const filteredNearby = useMemo(() => {
    let rows = nearby?.responders ? [...nearby.responders] : []
    if (capFilter) rows = rows.filter((r) => r.capabilities?.includes(capFilter))
    if (jurFilter) rows = rows.filter((r) => (r.jurisdiction || '') === jurFilter)
    if (maxKm > 0) rows = rows.filter((r) => r.distance_m != null && r.distance_m <= maxKm * 1000)
    rows.sort((a, b) => {
      if (sortBy === 'freshness') {
        const av = a.location_age_seconds ?? Number.MAX_SAFE_INTEGER
        const bv = b.location_age_seconds ?? Number.MAX_SAFE_INTEGER
        return av - bv
      }
      const av = a.distance_m ?? Number.MAX_SAFE_INTEGER
      const bv = b.distance_m ?? Number.MAX_SAFE_INTEGER
      return av - bv
    })
    return rows
  }, [nearby, capFilter, jurFilter, maxKm, sortBy])

  const capOptions = useMemo(() => {
    const s = new Set<string>()
    nearby?.responders?.forEach((r) => r.capabilities?.forEach((c) => s.add(c)))
    return Array.from(s).sort()
  }, [nearby])
  const jurOptions = useMemo(() => {
    const s = new Set<string>()
    nearby?.responders?.forEach((r) => { if (r.jurisdiction) s.add(r.jurisdiction) })
    return Array.from(s).sort()
  }, [nearby])

  // Eligible nearby units that carry an authority-only {lat,lng} fix, mapped to
  // SECONDARY ○ markers for the command map. These are visibility only — a ○ never
  // means "assigned". Driven by the SAME presentation filters as the list, so the
  // map and the list always agree. The accepted responder (🚔) is drawn separately
  // from the live frame; it is never one of these ○ markers.
  const mapUnits: UnitMarker[] = useMemo(() => {
    return filteredNearby
      .filter((r) => r.location != null)
      .map((r) => ({
        id: r.responder_id,
        lat: (r.location as { lat: number; lng: number }).lat,
        lng: (r.location as { lat: number; lng: number }).lng,
        label: r.display_label,
        kind: r.status === 'AVAILABLE' ? 'eligible' : r.status === 'BUSY' ? 'busy' : 'offline',
      }))
  }, [filteredNearby])

  // Presentation-only view over the backend-authoritative network roster. Can only
  // hide (status filter) or reorder (sort) the real verified units — never add one.
  const networkFiltered = useMemo(() => {
    let rows = network?.responders ? [...network.responders] : []
    if (netStatusFilter) rows = rows.filter((r) => r.status === netStatusFilter)
    const rank = (s: string) => (s === 'AVAILABLE' ? 0 : s === 'BUSY' ? 1 : 2)
    rows.sort((a, b) => {
      if (netSort === 'jurisdiction') {
        const j = (a.jurisdiction || '').localeCompare(b.jurisdiction || '')
        if (j !== 0) return j
        return a.display_label.localeCompare(b.display_label)
      }
      const r = rank(a.status) - rank(b.status)
      if (r !== 0) return r
      return a.display_label.localeCompare(b.display_label)
    })
    return rows
  }, [network, netStatusFilter, netSort])

  // On-duty units with a fresh fix, mapped to ○ coverage markers for the network
  // map (no incident, no 🚔 — this is a coverage picture, not an assignment view).
  const networkUnits: UnitMarker[] = useMemo(() => {
    return networkFiltered
      .filter((r) => r.location != null)
      .map((r) => ({
        id: r.responder_id,
        lat: (r.location as { lat: number; lng: number }).lat,
        lng: (r.location as { lat: number; lng: number }).lng,
        label: r.display_label,
        kind: networkUnitKind(r),
      }))
  }, [networkFiltered])

  // ── Render ──────────────────────────────────────────────────────────────────
  if (authorized === null) {
    return (
      <div style={{
        minHeight: '100vh', background: C.bg, color: C.muted,
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
      }}>
        Loading Rapid Response Center…
      </div>
    )
  }

  if (authorized === false) {
    return (
      <div style={{
        minHeight: '100vh', background: C.bg, color: C.text,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}>
        <div style={{
          background: C.panel, border: `1px solid ${C.line}`, borderRadius: 16,
          padding: '32px 28px', maxWidth: 420, textAlign: 'center',
        }}>
          <Lock size={28} color={C.accent} style={{ marginBottom: 10 }} />
          <h1 style={{ fontSize: 20, fontWeight: 800, color: C.ink, margin: '0 0 8px' }}>
            Authority sign-in required
          </h1>
          <p style={{ fontSize: 14, color: C.muted, margin: '0 0 20px' }}>
            The Rapid Response Center is restricted to verified authorities. Sign in
            from the Authority Dashboard to continue.
          </p>
          <Link href="/authority" style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, textDecoration: 'none',
            background: C.accent, color: '#fff', fontWeight: 700, fontSize: 14,
            padding: '10px 18px', borderRadius: 10,
          }}>
            <Shield size={16} /> Go to Authority Dashboard
          </Link>
        </div>
      </div>
    )
  }

  const lastUpdatedSecs = lastUpdated
    ? Math.max(0, Math.round((Date.now() - new Date(lastUpdated).getTime()) / 1000))
    : null

  // Single, truthful source for the live-response status shown on the map + strip.
  // Fix age comes from the frame's OWN timestamp (server-stamped GPS time), never from
  // when the socket message arrived. Unknown/absent timestamp -> null (not fresh).
  const fixAgeSecs = liveFrame ? fixAgeSeconds(liveFrame.timestamp ?? null, Date.now()) : null
  const live = deriveLiveState({
    dispatch: selectedDispatch,
    observing,
    wsConnected,
    wsInterrupted,
    hasFrame: !!liveFrame,
    fixAgeSecs,
  })

  // Incident marker from the case's OWN stored string (display only — never sent back).
  const incMarker: MapMarker | null = selectedCase ? parseLatLngString(selectedCase.location) : null
  const incCoordStr = formatCoord(incMarker)
  const copyCoordinates = () => {
    if (!incCoordStr) return
    const plain = incMarker ? `${incMarker.lat.toFixed(6)}, ${incMarker.lng.toFixed(6)}` : incCoordStr
    try {
      navigator.clipboard?.writeText(plain)
      setCopiedCoord(true)
      window.setTimeout(() => setCopiedCoord(false), 1600)
    } catch { /* clipboard may be unavailable; the coordinate is still shown on screen */ }
  }
  const nearbyCheckedLabel = nearbyCheckedAt ? new Date(nearbyCheckedAt).toLocaleTimeString() : null

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text }}>
      {/* ── Dark operations header ──────────────────────────────────────────── */}
      <header style={{ background: C.ink, color: '#fff' }}>
        <div style={{
          maxWidth: 1200, margin: '0 auto', padding: '16px 20px',
          display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
        }}>
          <Link href="/authority" style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, textDecoration: 'none',
            color: '#f9c6dd', fontSize: 13, fontWeight: 600,
          }}>
            <ArrowLeft size={16} /> Dashboard
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Radio size={22} color={C.accent} />
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: 0.2 }}>Rapid Response Center</div>
              <div style={{ fontSize: 12, color: '#d9a7bc' }}>
                Live emergencies, verified response network, and human-approved dispatch
              </div>
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 12, color: '#d9a7bc' }}>
              {lastUpdatedSecs == null ? '—' : `Last updated ${lastUpdatedSecs}s ago`}
            </span>
            <button
              onClick={() => loadAll(true)}
              disabled={refreshing}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                background: refreshing ? '#5a3348' : C.accent, color: '#fff',
                border: 'none', borderRadius: 9, padding: '8px 14px',
                fontSize: 13, fontWeight: 700, cursor: refreshing ? 'default' : 'pointer',
              }}
            >
              <RefreshCw size={15} style={refreshing ? { animation: 'spin 1s linear infinite' } : undefined} />
              {refreshing ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
      </header>

      {/* ── View tabs: Operations (incidents + dispatch) vs Response Network ──── */}
      <div style={{ background: C.panel, borderBottom: `1px solid ${C.line}` }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '0 20px', display: 'flex', gap: 4 }}>
          {([
            { key: 'operations', label: 'Operations', icon: <Radio size={15} /> },
            { key: 'network', label: 'Response Network', icon: <Signal size={15} /> },
          ] as const).map((t) => {
            const active = view === t.key
            return (
              <button
                key={t.key}
                onClick={() => setView(t.key)}
                aria-current={active ? 'page' : undefined}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7, background: 'transparent',
                  border: 'none', borderBottom: `3px solid ${active ? C.accent : 'transparent'}`,
                  padding: '12px 14px', fontSize: 13.5, fontWeight: 700, cursor: 'pointer',
                  color: active ? C.accent : C.muted,
                }}
              >
                {t.icon} {t.label}
              </button>
            )
          })}
        </div>
      </div>

      <main style={{ maxWidth: 1200, margin: '0 auto', padding: '20px 20px 64px' }}>
        {loadErr ? (
          <div style={{
            background: '#fee2e2', border: '1px solid #fca5a5', color: '#991b1b',
            borderRadius: 10, padding: '10px 14px', fontSize: 13, marginBottom: 16,
          }}>
            {loadErr}
          </div>
        ) : null}

        {/* ════════════════ OPERATIONS VIEW (incidents + dispatch) ════════════════ */}
        {view === 'operations' && (
        <>
        {/* ── Summary metric cards (REAL backend counts) ───────────────────── */}
        <section style={{
          display: 'grid', gap: 12, marginBottom: 20,
          gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
        }}>
          <MetricCard
            icon={<AlertTriangle size={16} />} accent={C.accent}
            label="Active dispatches" value={metrics?.active_dispatches ?? '—'}
            hint="Not yet resolved"
          />
          <MetricCard
            icon={<Clock size={16} />} accent="#ea580c"
            label="Waiting for responder" value={metrics?.waiting_for_responder ?? '—'}
            hint="Searching / offered"
          />
          <MetricCard
            icon={<Navigation size={16} />} accent="#16a34a"
            label="Incidents in response" value={metrics?.incidents_in_response ?? '—'}
            hint="Accepted / en route / arrived"
          />
          <MetricCard
            icon={<Users size={16} />} accent="#0ea5e9"
            label="Responders available" value={metrics?.responders_available ?? '—'}
            hint={`of ${metrics?.responders_on_duty ?? 0} verified on duty`}
          />
          <MetricCard
            icon={<Shield size={16} />} accent="#8b6b7d"
            label="Responders busy" value={metrics?.responders_busy ?? '—'}
            hint="Assigned to a dispatch"
          />
        </section>

        <div style={{ fontSize: 11, color: C.muted, marginTop: -8, marginBottom: 20, lineHeight: 1.4 }}>
          Counts are network-wide and refresh every 5s. &ldquo;Available&rdquo; reflects
          responders on duty right now — it is <strong>not</strong> per-incident eligibility,
          which the backend decides when a dispatch is approved.
        </div>

        <div style={{
          display: 'grid', gap: 18, alignItems: 'start',
          gridTemplateColumns: 'minmax(0, 1.1fr) minmax(0, 1fr)',
        }}>
          {/* ── Active Emergencies ─────────────────────────────────────────── */}
          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <AlertTriangle size={18} color={C.accent} />
              <h2 style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: 0 }}>Active Emergencies</h2>
              <span style={{ fontSize: 12, color: C.muted }}>({emergencies.length})</span>
            </div>

            {emergencies.length === 0 ? (
              <div style={{
                background: C.panel, border: `1px dashed ${C.line}`, borderRadius: 12,
                padding: '28px 20px', textAlign: 'center', color: C.muted, fontSize: 14,
              }}>
                <CheckCircle size={22} color="#16a34a" style={{ marginBottom: 8 }} />
                <div style={{ fontWeight: 700, color: C.text }}>No active emergencies</div>
                <div style={{ fontSize: 13, marginTop: 4 }}>New SOS incidents will appear here in real time.</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {emergencies.map((c) => {
                  const d = dispatchByCase.get(c.case_id)
                  const sev = severityTone(c.severity)
                  const ph = d ? phaseView(d) : null
                  const selected = c.case_id === selectedCaseId
                  const canDispatch = !d || d.status === 'FAILED' || d.status === 'EXPIRED' || d.status === 'CANCELLED'
                  const resolvedDone = !!d && (d.status === 'RESOLVED' || d.status === 'HELP_PROVIDED')
                  const reDispatch = !!d && (d.status === 'FAILED' || d.status === 'EXPIRED' || d.status === 'CANCELLED')
                  return (
                    <article
                      key={c.case_id}
                      onClick={() => setSelectedCaseId(c.case_id)}
                      style={{
                        background: C.panel, borderRadius: 12, padding: '14px 16px', cursor: 'pointer',
                        border: `1px solid ${selected ? C.accent : C.line}`,
                        boxShadow: selected ? '0 0 0 3px rgba(219,39,119,0.12)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <Pill text={(c.severity || 'unknown').toUpperCase()} fg={sev.fg} bg={sev.bg} />
                        {c.immediate_danger ? <Pill text="IMMEDIATE DANGER" fg="#991b1b" bg="#fee2e2" /> : null}
                        {ph ? <Pill text={ph.label} fg={ph.fg} bg={ph.bg} dot={ph.dot} /> : null}
                        <span style={{ marginLeft: 'auto', fontSize: 11, color: C.muted }}>
                          {c.case_id}
                        </span>
                      </div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: C.ink, margin: '8px 0 4px' }}>
                        {c.nature_of_abuse || 'Reported emergency'}
                      </div>
                      {c.summary ? (
                        <div style={{ fontSize: 13, color: C.text, marginBottom: 6, lineHeight: 1.4 }}>
                          {c.summary.length > 140 ? `${c.summary.slice(0, 140)}…` : c.summary}
                        </div>
                      ) : null}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: C.muted, flexWrap: 'wrap' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <MapPin size={13} /> {formatCoord(parseLatLngString(c.location)) || c.location || 'location pending'}
                        </span>
                        {c.trigger_type ? <span>via {c.trigger_type}</span> : null}
                      </div>
                      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                        {resolvedDone ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedCaseId(c.case_id) }}
                            style={{
                              background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0',
                              borderRadius: 9, padding: '8px 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                            }}
                          >
                            <CheckCircle size={14} /> Resolved
                          </button>
                        ) : canDispatch ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); setDispatchErr(null); setConfirmNotes(''); setConfirmCase(c) }}
                            style={{
                              background: C.accent, color: '#fff', border: 'none', borderRadius: 9,
                              padding: '8px 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                            }}
                          >
                            {reDispatch
                              ? <><RefreshCw size={14} /> Re-dispatch Help</>
                              : <><Radio size={14} /> Dispatch Help</>}
                          </button>
                        ) : (
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedCaseId(c.case_id) }}
                            style={{
                              background: C.accentSoft, color: C.accent, border: `1px solid ${C.line}`,
                              borderRadius: 9, padding: '8px 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                            }}
                          >
                            <Navigation size={14} /> View Active Response
                          </button>
                        )}
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>

          {/* ── Selected incident detail ───────────────────────────────────── */}
          <section style={{ position: 'sticky', top: 16 }}>
            {!selectedCase ? (
              <div style={{
                background: C.panel, border: `1px dashed ${C.line}`, borderRadius: 12,
                padding: '40px 24px', textAlign: 'center', color: C.muted,
              }}>
                <Navigation size={24} color={C.accent} style={{ marginBottom: 10 }} />
                <div style={{ fontWeight: 700, color: C.text, fontSize: 15 }}>Select an emergency</div>
                <div style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>
                  Choose an incident on the left to see its location, the verified
                  response units nearby, and the live state of any dispatch.
                </div>
              </div>
            ) : (
              <div style={{
                background: C.panel, border: `1px solid ${C.line}`, borderRadius: 14, overflow: 'hidden',
              }}>
                {/* Incident header */}
                <div style={{ padding: '16px 18px', borderBottom: `1px solid ${C.line}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Pill
                      text={(selectedCase.severity || 'unknown').toUpperCase()}
                      fg={severityTone(selectedCase.severity).fg}
                      bg={severityTone(selectedCase.severity).bg}
                    />
                    {selectedCase.immediate_danger ? <Pill text="IMMEDIATE DANGER" fg="#991b1b" bg="#fee2e2" /> : null}
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: C.muted }}>{selectedCase.case_id}</span>
                  </div>
                  <h3 style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: '10px 0 2px' }}>
                    {selectedCase.nature_of_abuse || 'Reported emergency'}
                  </h3>
                </div>

                {/* ── Response status (prominent, single truthful phase) ──────── */}
                <div style={{ padding: '12px 18px', borderBottom: `1px solid ${C.line}` }} aria-live="polite">
                  {(() => {
                    const p = selectedDispatch ? phaseView(selectedDispatch) : null
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span style={{
                          width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                          background: p?.dot || C.muted,
                        }} />
                        <span style={{ fontSize: 15, fontWeight: 800, color: C.ink }}>
                          {p ? p.label : 'No responder dispatched yet'}
                        </span>
                      </div>
                    )
                  })()}
                  {isEscalating(selectedDispatch) ? (
                    <div style={{ fontSize: 12, color: '#9a3412', marginTop: 6, lineHeight: 1.45 }}>
                      Escalating — the first offer was not accepted in time; the system is re-offering to the
                      next nearest eligible unit ({selectedDispatch?.attempts_made} attempts so far).
                    </div>
                  ) : null}
                </div>

                {/* ── Location summary (incident GPS + live responder location) ── */}
                <div style={{ padding: '12px 18px', borderBottom: `1px solid ${C.line}` }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
                    Location
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                    <MapPin size={14} color={C.accent} />
                    <span style={{ fontSize: 13, fontWeight: 700, color: C.ink, fontVariantNumeric: 'tabular-nums' }}>
                      {incCoordStr || selectedCase.location || 'Location pending'}
                    </span>
                    {incCoordStr ? (
                      <button
                        onClick={copyCoordinates}
                        aria-label="Copy coordinates"
                        style={{
                          background: 'transparent', border: `1px solid ${C.line}`, borderRadius: 7,
                          padding: '3px 9px', fontSize: 11, fontWeight: 700, color: C.accent, cursor: 'pointer',
                          display: 'inline-flex', alignItems: 'center', gap: 5,
                        }}
                      >
                        <Copy size={12} /> {copiedCoord ? 'Copied' : 'Copy coordinates'}
                      </button>
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12, color: live.locationColor, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: MAP_DOT_COLORS[live.dotTone], flexShrink: 0 }} />
                    {live.locationLine}
                  </div>
                </div>

                {/* Map: incident + (only while observable) the live responder frame */}
                <div style={{ padding: 14, borderBottom: `1px solid ${C.line}` }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
                    <button
                      onClick={() => setFullMapOpen(true)}
                      style={{
                        background: 'transparent', border: `1px solid ${C.line}`, borderRadius: 7,
                        padding: '3px 9px', fontSize: 11, fontWeight: 700, color: C.accent, cursor: 'pointer',
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                      }}
                    >
                      <Maximize2 size={12} /> Open full map
                    </button>
                  </div>
                  <LiveResponseMap
                    incident={incMarker}
                    responder={observing ? liveFrame : null}
                    trail={movementTrail}
                    connected={wsConnected}
                    height={190}
                    showLegend
                    units={mapUnits}
                    onUnitClick={(id) => setExpandedUnit((cur) => (cur === id ? null : id))}
                    selectedUnitId={expandedUnit}
                    showFitButton
                    showFollowButton={observing}
                    fitNonce={fitNonce}
                    onFollow={() => setFitNonce((n) => n + 1)}
                    onFitAll={() => setFitNonce((n) => n + 1)}
                    connectionLabel={live.dotLabel}
                    connectionTone={live.dotTone}
                    locationNote={live.locationLine}
                    responderAccepted={!!selectedDispatch && !isTerminal(selectedDispatch.status) && (selectedDispatch.status === 'ACCEPTED' || selectedDispatch.status === 'EN_ROUTE' || selectedDispatch.status === 'ARRIVED')}
                    dispatchStatus={selectedDispatch?.status}
                    caption={
                      !incMarker
                        ? 'No plottable coordinate on this case yet.'
                        : observing
                          ? `Active Response: ${selectedDispatch?.responder_label || 'Verified unit'} en route to incident.`
                          : mapUnits.length > 0
                            ? `Incident 📍 with ${mapUnits.length} eligible unit${mapUnits.length === 1 ? '' : 's'} nearby (○). Broadcast offer sent — awaiting first acceptance.`
                            : 'Incident location (from the case GPS fix).'
                    }
                  />
                </div>

                {/* ── Response details + contextual actions ──────────────────── */}
                <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.line}` }}>
                  {/* Broadcast Dispatch Status Summary (when dispatch exists) */}
                  {selectedDispatch && (
                    <div style={{
                      background: '#f8fafc', border: `1px solid ${C.line}`, borderRadius: 10,
                      padding: '12px 14px', marginBottom: 14,
                    }}>
                      <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: C.muted, marginBottom: 8 }}>
                        Dispatch Status (Broadcast Model)
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 12, marginBottom: 8 }}>
                        <div>
                          <span style={{ color: C.muted }}>Eligible providers:</span>{' '}
                          <strong style={{ color: C.ink }}>{selectedDispatch.eligible_provider_count ?? offers.length}</strong>
                        </div>
                        <div>
                          <span style={{ color: C.muted }}>Offers sent:</span>{' '}
                          <strong style={{ color: C.ink }}>{offers.length || (selectedDispatch.eligible_provider_count ?? 1)}</strong>
                        </div>
                        <div>
                          <span style={{ color: C.muted }}>Status:</span>{' '}
                          <strong style={{ color: C.ink }}>{selectedDispatch.status}</strong>
                        </div>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 12, marginBottom: 8 }}>
                        <div>
                          <span style={{ color: '#16a34a' }}>Accepted:</span>{' '}
                          <strong style={{ color: '#16a34a' }}>{offers.filter((o) => o.response === 'ACCEPTED').length || (selectedDispatch.assigned_responder_id ? 1 : 0)}</strong>
                        </div>
                        <div>
                          <span style={{ color: '#dc2626' }}>Declined:</span>{' '}
                          <strong style={{ color: '#dc2626' }}>{offers.filter((o) => o.response === 'DECLINED').length}</strong>
                        </div>
                        <div>
                          <span style={{ color: '#ea580c' }}>Waiting:</span>{' '}
                          <strong style={{ color: '#ea580c' }}>{offers.filter((o) => o.response === 'PENDING').length}</strong>
                        </div>
                      </div>
                      {selectedDispatch.assigned_responder_id && (
                        <div style={{ fontSize: 12, borderTop: `1px solid ${C.line}`, paddingTop: 6, marginTop: 4 }}>
                          <span style={{ color: C.muted }}>Assigned unit:</span>{' '}
                          <strong style={{ color: '#166534' }}>{selectedDispatch.responder_label || 'Verified Response Unit'}</strong>
                        </div>
                      )}
                    </div>
                  )}

                  {!selectedDispatch ? (
                    <div>
                      <div style={{ fontSize: 13, color: C.text, marginBottom: 10, lineHeight: 1.5 }}>
                        No responder has been dispatched for this incident yet. Dispatch is
                        human-approved: the system will resolve the location from the case
                        GPS fix and broadcast the emergency offer to <strong>all eligible</strong> verified nearby providers.
                      </div>
                      <button
                        onClick={() => { setDispatchErr(null); setConfirmNotes(''); setConfirmCase(selectedCase) }}
                        style={{
                          background: C.accent, color: '#fff', border: 'none', borderRadius: 9,
                          padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                          display: 'inline-flex', alignItems: 'center', gap: 6,
                        }}
                      >
                        <Radio size={15} /> Dispatch Help
                      </button>
                    </div>
                  ) : observing ? (
                    <div>
                      {/* Active Response Team (ACCEPTED / EN_ROUTE / ARRIVED only) */}
                      <div style={{
                        background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10,
                        padding: '12px 14px', marginBottom: 12,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
                          <Navigation size={15} color="#16a34a" />
                          <span style={{ fontSize: 13, fontWeight: 800, color: '#166534' }}>Active Response Team</span>
                        </div>
                        <div style={{ fontSize: 13, color: '#166534', fontWeight: 600 }}>
                          {selectedDispatch.responder_label || 'Verified responder'}
                        </div>
                        <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>
                          {phaseView(selectedDispatch).label}. Distance is straight-line only; no ETA is estimated.
                        </div>
                        <div style={{ fontSize: 12, color: live.locationColor, fontWeight: 600, marginTop: 6 }}>
                          {live.locationLine}
                        </div>
                      </div>
                      <button
                        onClick={() => doCancel(selectedDispatch)}
                        style={{
                          background: '#fff', color: '#991b1b', border: '1px solid #fca5a5',
                          borderRadius: 9, padding: '7px 13px', fontSize: 12, fontWeight: 700, cursor: 'pointer',
                          display: 'inline-flex', alignItems: 'center', gap: 6,
                        }}
                      >
                        <X size={13} /> Cancel dispatch
                      </button>
                    </div>
                  ) : (
                    <div>
                      {/* Non-observable states: searching/offered, failed/expired, cancelled, resolved */}
                      {(() => {
                        const s = selectedDispatch.status
                        if (s === 'FAILED' || s === 'EXPIRED') {
                          return (
                            <div style={{
                              background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 10,
                              padding: '10px 12px', fontSize: 13, color: '#9a3412', lineHeight: 1.5,
                            }}>
                              No verified responder accepted this emergency{selectedDispatch.attempts_made ? ` after ${selectedDispatch.attempts_made} offer attempt(s)` : ''}.
                              You can re-dispatch to offer it to eligible units again.
                            </div>
                          )
                        }
                        if (s === 'CANCELLED') {
                          return (
                            <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.5 }}>
                              This dispatch was cancelled. You can re-dispatch help if the emergency is still active.
                            </div>
                          )
                        }
                        if (s === 'RESOLVED' || s === 'HELP_PROVIDED') {
                          return (
                            <div style={{
                              background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10,
                              padding: '10px 12px', fontSize: 13, color: '#166534', lineHeight: 1.5,
                            }}>
                              {phaseView(selectedDispatch).label}. Live tracking has ended for this dispatch.
                            </div>
                          )
                        }
                        // CREATED / SEARCHING / OFFERED — no live location until a responder accepts.
                        return (
                          <div style={{ fontSize: 13, color: C.text, lineHeight: 1.5 }}>
                            A verified responder has not accepted yet. Live location tracking becomes
                            available only after a responder accepts.{' '}
                            {isEscalating(selectedDispatch)
                              ? 'The system is re-offering to the next nearest eligible unit.'
                              : 'The nearest eligible unit has been notified and must accept.'}
                          </div>
                        )
                      })()}

                      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                        {(selectedDispatch.status === 'FAILED' || selectedDispatch.status === 'EXPIRED' || selectedDispatch.status === 'CANCELLED') ? (
                          <button
                            onClick={() => { setDispatchErr(null); setConfirmNotes(''); setConfirmCase(selectedCase) }}
                            style={{
                              background: C.accent, color: '#fff', border: 'none', borderRadius: 9,
                              padding: '8px 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                            }}
                          >
                            <RefreshCw size={14} /> Re-dispatch Help
                          </button>
                        ) : null}
                        {!isTerminal(selectedDispatch.status) ? (
                          <button
                            onClick={() => doCancel(selectedDispatch)}
                            style={{
                              background: '#fff', color: '#991b1b', border: '1px solid #fca5a5',
                              borderRadius: 9, padding: '7px 13px', fontSize: 12, fontWeight: 700, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                            }}
                          >
                            <X size={13} /> Cancel dispatch
                          </button>
                        ) : null}
                      </div>
                    </div>

                  )}
                </div>

                {/* ── Nearby Response Units (authority-only, read-only) ───────── */}
                {!observing ? (
                  <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.line}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                      <Users size={16} color={C.accent} />
                      <h4 style={{ fontSize: 14, fontWeight: 800, color: C.ink, margin: 0 }}>Nearby Response Units</h4>
                      <span style={{ fontSize: 12, color: C.muted }}>
                        ({filteredNearby.length}{nearby ? ` of ${nearby.responders.length}` : ''})
                      </span>
                      <button
                        onClick={refreshNearby}
                        disabled={nearbyLoading}
                        style={{
                          marginLeft: 'auto', background: C.accentSoft, color: C.accent,
                          border: `1px solid ${C.line}`, borderRadius: 8, padding: '5px 10px',
                          fontSize: 12, fontWeight: 700, cursor: nearbyLoading ? 'default' : 'pointer',
                          display: 'inline-flex', alignItems: 'center', gap: 5,
                        }}
                      >
                        <RefreshCw size={12} style={nearbyLoading ? { animation: 'spin 1s linear infinite' } : undefined} />
                        Refresh nearby units
                      </button>
                    </div>

                    {nearbyCheckedLabel ? (
                      <div style={{ fontSize: 11, color: C.muted, marginBottom: 8 }}>
                        Last checked {nearbyCheckedLabel}
                      </div>
                    ) : null}

                    <div style={{
                      fontSize: 11, color: C.muted, background: '#faf5f8', border: `1px solid ${C.line}`,
                      borderRadius: 8, padding: '7px 10px', marginBottom: 10,
                      display: 'flex', alignItems: 'flex-start', gap: 6, lineHeight: 1.45,
                    }}>
                      <Lock size={13} style={{ marginTop: 1, flexShrink: 0 }} />
                      <span>
                        Read-only visibility. Units are ranked server-side by eligibility, then distance.
                        Filters below only hide or reorder this list — they cannot change who is eligible,
                        and there is no way to assign a specific unit. Dispatch auto-offers the nearest
                        eligible unit, which must accept.
                      </span>
                    </div>

                    {/* Presentation-only filters */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                      <select
                        value={capFilter} onChange={(e) => setCapFilter(e.target.value)}
                        style={selectStyle}
                      >
                        <option value="">All capabilities</option>
                        {capOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <select
                        value={jurFilter} onChange={(e) => setJurFilter(e.target.value)}
                        style={selectStyle}
                      >
                        <option value="">All jurisdictions</option>
                        {jurOptions.map((j) => <option key={j} value={j}>{j}</option>)}
                      </select>
                      <select
                        value={String(maxKm)} onChange={(e) => setMaxKm(Number(e.target.value))}
                        style={selectStyle}
                      >
                        <option value="0">Any distance</option>
                        <option value="2">Within 2 km</option>
                        <option value="5">Within 5 km</option>
                        <option value="10">Within 10 km</option>
                      </select>
                      <select
                        value={sortBy} onChange={(e) => setSortBy(e.target.value as 'distance' | 'freshness')}
                        style={selectStyle}
                      >
                        <option value="distance">Sort: nearest</option>
                        <option value="freshness">Sort: freshest location</option>
                      </select>
                    </div>

                    {nearbyLoading && !nearby ? (
                      <div style={{ fontSize: 13, color: C.muted, padding: '12px 0' }}>Loading nearby units…</div>
                    ) : nearbyErr ? (
                      <div style={{
                        background: '#fee2e2', border: '1px solid #fca5a5', color: '#991b1b',
                        borderRadius: 8, padding: '9px 12px', fontSize: 12,
                      }}>{nearbyErr}</div>
                    ) : nearby && !nearby.incident_resolved ? (
                      <div style={{
                        background: '#faf5f8', border: `1px dashed ${C.line}`, borderRadius: 10,
                        padding: '14px', textAlign: 'center',
                      }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>No usable GPS fix on this case</div>
                        <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                          Eligible units cannot be ranked without a stored location, and a dispatch would be
                          rejected until a valid GPS fix is recorded for this incident.
                        </div>
                      </div>
                    ) : nearby && nearby.responders.length === 0 ? (
                      <div style={{
                        background: '#faf5f8', border: `1px dashed ${C.line}`, borderRadius: 10,
                        padding: '14px', textAlign: 'center',
                      }}>
                        {/* Phase 5: truthful empty-state messages using network-wide counts */}
                        {(() => {
                          const onDuty = metrics?.responders_on_duty ?? null
                          const available = metrics?.responders_available ?? null
                          if (onDuty === 0) {
                            return (
                              <>
                                <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>
                                  No verified response units are registered
                                </div>
                                <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                                  No active, verified responder accounts exist on the network yet.
                                  Provision accounts via <code>provision_responder.py</code> and approve them through the admin workflow.
                                </div>
                              </>
                            )
                          }
                          if (available === 0 && onDuty !== null && onDuty > 0) {
                            return (
                              <>
                                <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>
                                  No response units are currently on duty
                                </div>
                                <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                                  {onDuty} verified unit{onDuty === 1 ? '' : 's'} registered, but none are currently AVAILABLE
                                  (they may be BUSY, OFFLINE, or UNAVAILABLE). Check the Response Network view.
                                </div>
                              </>
                            )
                          }
                          return (
                            <>
                              <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>
                                No eligible units match this incident
                              </div>
                              <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                                {available !== null && available > 0
                                  ? `${available} unit${available === 1 ? ' is' : 's are'} available network-wide, but none match this incident's requirements within `
                                  : 'No available units match within '
                                }
                                {nearby.radius_m ? `${Math.round(nearby.radius_m / 1000)} km` : 'range'}
                                {nearby.incident_jurisdiction ? ` in ${nearby.incident_jurisdiction}` : ''}.
                                Reasons may include stale location fixes, capability mismatch, or jurisdiction filters.
                              </div>
                              <div style={{ fontSize: 11, color: C.muted, marginTop: 4, fontStyle: 'italic' }}>
                                Network-wide counts do not equal incident eligibility. The backend decides eligibility on dispatch.
                              </div>
                            </>
                          )
                        })()}
                      </div>
                    ) : filteredNearby.length === 0 ? (
                      <div style={{
                        background: '#faf5f8', border: `1px dashed ${C.line}`, borderRadius: 10,
                        padding: '14px', textAlign: 'center',
                      }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>No units match your filters</div>
                        <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                          {nearby?.responders.length ?? 0} eligible unit(s) exist, but the display filters above
                          hide them all. Clearing a filter will reveal the backend-eligible units again.
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {filteredNearby.map((r) => {
                          const avail = r.status === 'AVAILABLE'
                          const stTone = avail
                            ? { fg: '#166534', bg: '#dcfce7', dot: '#16a34a' }
                            : r.status === 'BUSY'
                              ? { fg: '#9a3412', bg: '#ffedd5', dot: '#ea580c' }
                              : { fg: C.muted, bg: '#f3eef1', dot: C.muted }
                          const open = expandedUnit === r.responder_id
                          return (
                            <div key={r.responder_id} style={{
                              border: `1px solid ${C.line}`, borderRadius: 10, padding: '10px 12px',
                            }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                <span style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{r.display_label}</span>
                                <Pill text={r.status} fg={stTone.fg} bg={stTone.bg} dot={stTone.dot} />
                                <button
                                  onClick={() => setExpandedUnit(open ? null : r.responder_id)}
                                  style={{
                                    marginLeft: 'auto', background: 'transparent', border: `1px solid ${C.line}`,
                                    borderRadius: 7, padding: '3px 10px', fontSize: 12, fontWeight: 700,
                                    color: C.accent, cursor: 'pointer',
                                  }}
                                >{open ? 'Hide' : 'View'}</button>
                              </div>
                              <div style={{ display: 'flex', gap: 14, fontSize: 12, color: C.muted, marginTop: 6, flexWrap: 'wrap' }}>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                  <Navigation size={12} /> {fmtDistance(r.distance_m)}
                                </span>
                                <span style={{
                                  display: 'inline-flex', alignItems: 'center', gap: 4,
                                  color: r.location_fresh ? '#166534' : '#9a3412',
                                }}>
                                  <Clock size={12} /> {ageLabel(r.location_age_seconds)}
                                </span>
                                {r.jurisdiction ? <span>{r.jurisdiction}</span> : null}
                              </div>
                              {open ? (
                                <div style={{ marginTop: 8, borderTop: `1px dashed ${C.line}`, paddingTop: 8 }}>
                                  <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Capabilities</div>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                    {(r.capabilities || []).length
                                      ? r.capabilities.map((c) => (
                                        <span key={c} style={{
                                          fontSize: 11, fontWeight: 600, color: C.text, background: '#faf5f8',
                                          border: `1px solid ${C.line}`, borderRadius: 999, padding: '2px 9px',
                                        }}>{c}</span>
                                      ))
                                      : <span style={{ fontSize: 12, color: C.muted }}>None listed</span>}
                                  </div>
                                  <div style={{ fontSize: 11, color: C.muted, marginTop: 8, lineHeight: 1.45 }}>
                                    Straight-line distance only. Identity, contact details, and exact
                                    coordinates are intentionally withheld. This unit cannot be assigned
                                    directly — the dispatch engine offers it only if it is the nearest eligible unit.
                                  </div>
                                </div>
                              ) : null}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                ) : null}

                {/* ── Operations timeline (truthful state-change markers only) ── */}
                {selectedDispatch ? (
                  <div style={{ padding: '14px 18px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                      <Clock size={15} color={C.accent} />
                      <h4 style={{ fontSize: 14, fontWeight: 800, color: C.ink, margin: 0 }}>Operations timeline</h4>
                    </div>
                    {timeline.length === 0 ? (
                      <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.5 }}>
                        No events recorded yet. State changes (offered, accepted, en route, arrived) will appear
                        here as they happen.
                      </div>
                    ) : (
                    <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {timeline.map((t, i) => {
                        const label = t.event.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase())
                        const when = t.at ? new Date(t.at).toLocaleTimeString() : ''
                        return (
                          <li key={`${t.event}-${i}`} style={{ display: 'flex', gap: 10 }}>
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                              <span style={{ width: 9, height: 9, borderRadius: 999, background: C.accent, marginTop: 4 }} />
                              {i < timeline.length - 1 ? <span style={{ flex: 1, width: 2, background: C.line }} /> : null}
                            </div>
                            <div>
                              <div style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{label}</div>
                              <div style={{ fontSize: 11, color: C.muted }}>
                                {when}
                                {t.detail?.reason ? ` · ${t.detail.reason}` : ''}
                                {t.detail?.via ? ` · via ${t.detail.via}` : ''}
                              </div>
                            </div>
                          </li>
                        )
                      })}
                    </ol>
                    )}
                  </div>
                ) : null}
              </div>
            )}
          </section>
        </div>
        </>
        )}

        {/* ════════════════ RESPONSE NETWORK VIEW ════════════════ */}
        {view === 'network' && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            <Signal size={18} color={C.accent} />
            <h2 style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: 0 }}>Verified Response Network</h2>
            <span style={{ fontSize: 12, color: C.muted }}>
              ({networkFiltered.length}{network ? ` of ${network.responders.length}` : ''})
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: C.muted }}>
              {networkCheckedAt ? `Last checked ${new Date(networkCheckedAt).toLocaleTimeString()}` : '—'}
            </span>
            <button
              onClick={refreshNetwork}
              disabled={networkLoading}
              style={{
                background: C.accentSoft, color: C.accent, border: `1px solid ${C.line}`,
                borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 700,
                cursor: networkLoading ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              <RefreshCw size={13} style={networkLoading ? { animation: 'spin 1s linear infinite' } : undefined} />
              Refresh network
            </button>
          </div>

          {/* Honest scope note: on-duty availability is NOT per-incident eligibility. */}
          <div style={{
            fontSize: 12, color: C.muted, background: '#faf5f8', border: `1px solid ${C.line}`,
            borderRadius: 10, padding: '9px 12px', marginBottom: 16, lineHeight: 1.45,
            display: 'flex', alignItems: 'flex-start', gap: 7,
          }}>
            <Lock size={14} style={{ marginTop: 1, flexShrink: 0 }} />
            <span>
              Network availability is separate from incident eligibility. A unit shown here is on
              duty network-wide; whether it is <strong>eligible</strong> for a specific emergency
              (capability, jurisdiction, radius, fresh location) is decided server-side only when a
              dispatch is approved. This roster is read-only — units cannot be assigned from here.
            </span>
          </div>

          {/* Summary counts (same source as the operations metric cards). */}
          <div style={{
            display: 'grid', gap: 12, marginBottom: 16,
            gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
          }}>
            <MetricCard
              icon={<Users size={16} />} accent="#16a34a"
              label="Available now" value={network?.summary.responders_available ?? '—'}
              hint="On duty & unassigned"
            />
            <MetricCard
              icon={<Shield size={16} />} accent="#ea580c"
              label="Busy / assigned" value={network?.summary.responders_busy ?? '—'}
              hint="Holding an assignment"
            />
            <MetricCard
              icon={<Activity size={16} />} accent={C.accent}
              label="On duty (verified)" value={network?.summary.responders_on_duty ?? '—'}
              hint="Active & verified"
            />
          </div>
          {/* Coverage map: on-duty units with a fresh fix plotted as ○ markers.
              No incident and no 🚔 here — this is a coverage picture, not an
              assignment view. Clicking a ○ highlights its roster card below. */}
          <div style={{
            background: C.panel, border: `1px solid ${C.line}`, borderRadius: 14,
            padding: 14, marginBottom: 16,
          }}>
            {networkLoading && !network ? (
              <div style={{ fontSize: 13, color: C.muted, padding: '28px 0', textAlign: 'center' }}>
                Loading response network…
              </div>
            ) : networkErr ? (
              <div style={{
                background: '#fee2e2', border: '1px solid #fca5a5', color: '#991b1b',
                borderRadius: 8, padding: '9px 12px', fontSize: 12,
              }}>{networkErr}</div>
            ) : (
              <>
                <LiveResponseMap
                  incident={null}
                  responder={null}
                  height={300}
                  units={networkUnits}
                  onUnitClick={(id) => setExpandedUnit((cur) => (cur === id ? null : id))}
                  selectedUnitId={expandedUnit}
                  showFitButton
                  connectionLabel="🗺 Network coverage"
                  connectionTone="grey"
                  networkTotalCount={network?.summary.responders_on_duty ?? 0}
                  emptyMessage={
                    (network?.summary.responders_on_duty ?? 0) === 0
                      ? 'No verified response units are registered on the network.'
                      : 'On-duty responders exist, but no fresh location fixes are available.'
                  }
                  caption={
                    networkUnits.length > 0
                      ? `○ marks ${networkUnits.length} on-duty unit${networkUnits.length === 1 ? '' : 's'} with a fresh location fix. A ○ means on duty — not assigned to any incident.`
                      : 'No on-duty unit currently has a fresh location fix to plot. Units still appear in the roster below.'
                  }
                />
              </>
            )}
          </div>

          {/* Presentation-only roster controls (hide/reorder only). */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <select value={netStatusFilter} onChange={(e) => setNetStatusFilter(e.target.value)} style={selectStyle}>
              <option value="">All statuses</option>
              <option value="AVAILABLE">Available</option>
              <option value="BUSY">Busy</option>
              <option value="UNAVAILABLE">Unavailable</option>
              <option value="OFFLINE">Offline</option>
            </select>
            <select value={netSort} onChange={(e) => setNetSort(e.target.value as 'status' | 'jurisdiction')} style={selectStyle}>
              <option value="status">Sort: availability</option>
              <option value="jurisdiction">Sort: jurisdiction</option>
            </select>
          </div>
          {networkLoading && !network ? null
            : networkErr ? null
            : network && network.responders.length === 0 ? (
              <div style={{ background: '#faf5f8', border: `1px dashed ${C.line}`, borderRadius: 10, padding: '18px', textAlign: 'center' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>No verified responders on the network</div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                  Verified, active responders will appear here as they come on duty.
                </div>
              </div>
            ) : networkFiltered.length === 0 ? (
              <div style={{ background: '#faf5f8', border: `1px dashed ${C.line}`, borderRadius: 10, padding: '18px', textAlign: 'center' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>No units match your filters</div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 5, lineHeight: 1.5 }}>
                  {network?.responders.length ?? 0} verified unit(s) exist, but the filters above hide them all.
                  Clearing a filter will reveal the backend roster again.
                </div>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
                {networkFiltered.map((r) => {
                  const st = statusToneForUnit(r.status, r.on_duty, r.location_fresh)
                  const selected = expandedUnit === r.responder_id
                  return (
                    <div key={r.responder_id}
                      onClick={() => setExpandedUnit(selected ? null : r.responder_id)}
                      style={{
                        border: `1px solid ${selected ? C.accent : C.line}`, borderRadius: 10,
                        padding: '12px 14px', cursor: 'pointer', background: C.panel,
                        boxShadow: selected ? '0 0 0 3px rgba(219,39,119,0.12)' : 'none',
                      }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{r.display_label}</span>
                        <Pill text={st.label} fg={st.fg} bg={st.bg} dot={st.dot} />
                        {r.assigned ? <Pill text="ASSIGNED" fg="#9a3412" bg="#ffedd5" /> : null}
                      </div>
                      <div style={{ display: 'flex', gap: 12, fontSize: 12, color: C.muted, marginTop: 7, flexWrap: 'wrap' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <Shield size={12} /> {r.on_duty ? 'On duty' : 'Off duty'}
                        </span>
                        {r.jurisdiction ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            <MapPin size={12} /> {r.jurisdiction}
                          </span>
                        ) : null}
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: r.location_fresh ? '#166534' : '#9a3412' }}>
                          <Clock size={12} /> {ageLabel(r.location_age_seconds)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                        {(r.capabilities || []).length
                          ? r.capabilities.map((c) => (
                            <span key={c} style={{ fontSize: 11, fontWeight: 600, color: C.text, background: '#faf5f8', border: `1px solid ${C.line}`, borderRadius: 999, padding: '2px 9px' }}>{c}</span>
                          ))
                          : <span style={{ fontSize: 12, color: C.muted }}>No capabilities listed</span>}
                      </div>
                      {selected ? (
                        <div style={{ fontSize: 11, color: C.muted, marginTop: 8, borderTop: `1px dashed ${C.line}`, paddingTop: 8, lineHeight: 1.45 }}>
                          On duty does not mean eligible for a specific incident, and this unit cannot be
                          assigned from here. Identity, contact details, and exact coordinates are withheld;
                          only a coarse on-duty location is shown on the coverage map.
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            )}
        </section>
        )}
      </main>

      {/* ── Human-approved dispatch confirmation modal ───────────────────────── */}
      {confirmCase ? (
        <div
          onClick={() => { if (!dispatchBusy) setConfirmCase(null) }}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(26,10,18,0.55)', zIndex: 50,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="rrn-confirm-title"
            style={{
              background: C.panel, borderRadius: 16, maxWidth: 460, width: '100%',
              padding: '22px 24px', boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 6 }}>
              <Shield size={20} color={C.accent} />
              <h3 id="rrn-confirm-title" style={{ fontSize: 17, fontWeight: 800, color: C.ink, margin: 0 }}>
                Confirm human-approved dispatch
              </h3>
            </div>
            <p style={{ fontSize: 13, color: C.text, lineHeight: 1.5, margin: '0 0 14px' }}>
              You are approving a dispatch for this incident. The system will resolve the
              location from the case&rsquo;s own stored GPS fix and automatically offer the
              nearest <strong>eligible</strong> verified unit, which must accept. You are not
              selecting a specific responder, and no coordinates are sent from this screen.
            </p>

            <div style={{ background: '#faf5f8', border: `1px solid ${C.line}`, borderRadius: 10, padding: '10px 12px', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4, flexWrap: 'wrap' }}>
                <Pill
                  text={(confirmCase.severity || 'unknown').toUpperCase()}
                  fg={severityTone(confirmCase.severity).fg}
                  bg={severityTone(confirmCase.severity).bg}
                />
                <span style={{ fontSize: 11, color: C.muted }}>{confirmCase.case_id}</span>
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>
                {confirmCase.nature_of_abuse || 'Reported emergency'}
              </div>
              <div style={{ fontSize: 12, color: C.muted, marginTop: 2, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <MapPin size={12} /> {confirmCase.location || 'location pending'}
              </div>
            </div>

            <label style={{ fontSize: 12, fontWeight: 700, color: C.text, display: 'block', marginBottom: 5 }}>
              Operator note (optional)
            </label>
            <textarea
              value={confirmNotes}
              onChange={(e) => setConfirmNotes(e.target.value)}
              rows={2}
              placeholder="Context for the response team (no personal victim details)."
              style={{
                width: '100%', border: `1px solid ${C.line}`, borderRadius: 9, padding: '8px 10px',
                fontSize: 13, color: C.text, resize: 'vertical', boxSizing: 'border-box', fontFamily: 'inherit',
              }}
            />

            {dispatchErr ? (
              <div style={{
                background: '#fee2e2', border: '1px solid #fca5a5', color: '#991b1b',
                borderRadius: 8, padding: '9px 12px', fontSize: 12, margin: '12px 0 0',
              }}>{dispatchErr}</div>
            ) : null}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 18 }}>
              <button
                onClick={() => setConfirmCase(null)}
                disabled={dispatchBusy}
                style={{
                  background: '#fff', color: C.text, border: `1px solid ${C.line}`, borderRadius: 9,
                  padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: dispatchBusy ? 'default' : 'pointer',
                }}
              >Cancel</button>
              <button
                onClick={submitDispatch}
                disabled={dispatchBusy}
                style={{
                  background: dispatchBusy ? '#b4537f' : C.accent, color: '#fff', border: 'none', borderRadius: 9,
                  padding: '9px 18px', fontSize: 13, fontWeight: 700, cursor: dispatchBusy ? 'default' : 'pointer',
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                }}
              >
                <Radio size={15} /> {dispatchBusy ? 'Dispatching…' : 'Confirm dispatch'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ── Full-map modal (incident + accepted responder only) ──────────────── */}
      {fullMapOpen && selectedCase ? (
        <div
          onClick={() => setFullMapOpen(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(26,10,18,0.6)', zIndex: 60,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="rrn-fullmap-title"
            style={{
              background: C.panel, borderRadius: 16, maxWidth: 900, width: '100%',
              padding: '18px 20px', boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <MapPin size={18} color={C.accent} />
              <h3 id="rrn-fullmap-title" style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: 0 }}>
                Live response map
              </h3>
              <span style={{ fontSize: 11, color: C.muted }}>{selectedCase.case_id}</span>
              <button
                onClick={() => setFullMapOpen(false)}
                aria-label="Close full map"
                style={{
                  marginLeft: 'auto', background: 'transparent', border: `1px solid ${C.line}`,
                  borderRadius: 8, padding: '5px 9px', cursor: 'pointer', color: C.text,
                  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700,
                }}
              >
                <X size={14} /> Close
              </button>
            </div>
            <LiveResponseMap
              incident={incMarker}
              responder={observing ? liveFrame : null}
              trail={movementTrail}
              connected={wsConnected}
              height={460}
              showLegend
              units={mapUnits}
              onUnitClick={(id) => setExpandedUnit((cur) => (cur === id ? null : id))}
              selectedUnitId={expandedUnit}
              showFitButton
              showFollowButton={observing}
              fitNonce={fitNonce}
              onFollow={() => setFitNonce((n) => n + 1)}
              onFitAll={() => setFitNonce((n) => n + 1)}
              connectionLabel={live.dotLabel}
              connectionTone={live.dotTone}
              locationNote={live.locationLine}
              responderAccepted={!!selectedDispatch && !isTerminal(selectedDispatch.status) && (selectedDispatch.status === 'ACCEPTED' || selectedDispatch.status === 'EN_ROUTE' || selectedDispatch.status === 'ARRIVED')}
              dispatchStatus={selectedDispatch?.status}
              caption="📍 Incident · 🚔 accepted responder · ○ eligible nearby unit. Eligible units are visible for situational awareness only — a ○ never means assigned."
            />
          </div>
        </div>
      ) : null}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
