'use client'
/**
 * HAVEN Rapid Response Network — protected RESPONDER interface (/responder).
 *
 * A field responder signs in with their badge + own password (reuses the existing
 * /auth/responder-login; identity + role come ONLY from the verified server token).
 * They toggle availability, receive dispatch OFFERS, ACCEPT/DECLINE, and — only
 * while actively assigned — stream their live GPS to the incident's authenticated
 * WebSocket room. No victim PII is ever shown here; only the authorized incident
 * location needed to respond.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Shield, LogOut, Navigation, CheckCircle, XCircle, MapPin } from 'lucide-react'
import LiveResponseMap from '@/components/LiveResponseMap'
import { currentPushState, enablePush, PUSH_STATE_COPY, type PushState } from '@/lib/pushSubscription'
import {
  ResponderSelf, ResponderOffer, ResponderStatus,
  getResponderToken, setResponderSession, clearResponderSession,
  responderMe, setResponderStatus, setResponderDuty, postResponderLocation, getResponderOffers,
  getResponderActiveDispatch, acceptOffer, declineOffer, markEnRoute, markArrived,
  markHelpProvided, helpIsOnTheWay, DISPATCH_STATUS_LABEL, DispatchStatus,
} from '@/lib/dispatch'
import { routeProvider, formatDistance, externalNavUrl } from '@/lib/mapProvider'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const POLL_MS = 5000
const LOCATION_POST_MS = 10000 // eligibility-freshness cadence (REST), rate-limit friendly

interface GeoFix { lat: number; lng: number; accuracy?: number; timestamp: string }

export default function ResponderPage() {
  // ─── session ────────────────────────────────────────────────────────────────
  const [token, setToken] = useState<string | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [authBusy, setAuthBusy] = useState(false)

  // ─── live state ───────────────────────────────────────────────────────────────
  const [me, setMe] = useState<ResponderSelf | null>(null)
  const [offers, setOffers] = useState<ResponderOffer[]>([])
  const [active, setActive] = useState<ResponderOffer | null>(null)
  const [fix, setFix] = useState<GeoFix | null>(null)
  const [trail, setTrail] = useState<Array<{ lat: number; lng: number }>>([])
  const [fitNonce, setFitNonce] = useState(0)
  const [geoError, setGeoError] = useState('')
  const [wsConnected, setWsConnected] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  /**
   * The first genuinely-new pending offer: shown as a prominent full-screen
   * modal so a field responder cannot miss an incoming emergency request.
   * Dismissed when the responder accepts, declines, or the offer disappears.
   */
  const [incomingOffer, setIncomingOffer] = useState<ResponderOffer | null>(null)


  const wsRef = useRef<WebSocket | null>(null)
  const watchRef = useRef<number | null>(null)
  const lastPostRef = useRef<number>(0)
  const seenOfferIds = useRef<Set<string>>(new Set())
  const activeIdRef = useRef<string | null>(null)
  const fixRef = useRef<GeoFix | null>(null)

  // Keep refs in sync so the geolocation callback (a stable closure) sees fresh values.
  useEffect(() => { activeIdRef.current = active?.dispatch_id || null }, [active])
  useEffect(() => { fixRef.current = fix }, [fix])

  // Clear movement trail on active dispatch change, unmount, or terminal state.
  useEffect(() => {
    setTrail([])
  }, [active?.dispatch_id])

  // On mount, adopt any existing responder session token.
  useEffect(() => {
    setToken(getResponderToken())
    setAuthReady(true)
  }, [])

  const login = useCallback(async (e?: React.FormEvent) => {
    e?.preventDefault()
    setAuthError('')
    setAuthBusy(true)
    try {
      const res = await fetch(`${API}/auth/responder-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ badge_number: badge.trim(), password }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error((data && (data.detail || data.message)) || 'Sign-in failed. Check your badge number and password.')
      }
      const t = data.token || data.access_token
      if (!t) throw new Error('Sign-in response did not include a session token.')
      setResponderSession(t)
      setToken(t)
      setPassword('')
      // Ask for notification permission up front (minimal, best-effort).
      try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission() } catch { /* noop */ }
    } catch (err: unknown) {
      setAuthError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setAuthBusy(false)
    }
  }, [badge, password])

  const logout = useCallback(() => {
    try { wsRef.current?.close() } catch { /* noop */ }
    if (watchRef.current != null && typeof navigator !== 'undefined') {
      navigator.geolocation?.clearWatch(watchRef.current)
      watchRef.current = null
    }
    clearResponderSession()
    setToken(null); setMe(null); setOffers([]); setActive(null); setFix(null)
  }, [])

  // ─── poll loop: own account, pending offers, and any active assignment ────────
  const refresh = useCallback(async () => {
    if (!getResponderToken()) return
    try {
      const [meRec, activeRec] = await Promise.all([
        responderMe().catch(() => null),
        getResponderActiveDispatch().catch(() => null),
      ])
      if (meRec) setMe(meRec)
      setActive(activeRec)
      // Offers are only meaningful when not already committed to an assignment.
      if (activeRec) {
        setOffers([])
        // Clear any incoming-offer modal when we become assigned.
        setIncomingOffer(null)
      } else {
        const o = await getResponderOffers().catch(() => [])
        setOffers(o)
        // Minimal, PII-free notification for genuinely new offers.
        for (const off of o) {
          if (!seenOfferIds.current.has(off.dispatch_id)) {
            seenOfferIds.current.add(off.dispatch_id)
            notifyNewOffer(off)
            // Show the full-screen modal for the FIRST new offer seen.
            setIncomingOffer((cur) => cur ?? off)
          }
        }
        // Auto-dismiss the modal if its offer has disappeared (accepted by
        // another responder, expired, or declined on this device).
        setIncomingOffer((cur) => {
          if (!cur) return null
          return o.some((x) => x.dispatch_id === cur.dispatch_id) ? cur : null
        })
      }
      setError('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not refresh.')
    }
  }, [])


  useEffect(() => {
    if (!token) return
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [token, refresh])

  function notifyNewOffer(off: ResponderOffer) {
    const dist = off.distance_m != null ? ` (~${formatDistance(off.distance_m)} away)` : ''
    setNotice(`New response request${dist}.`)
    try {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('HAVEN — response requested', {
          body: `A verified incident needs a responder${dist}. Open HAVEN to accept.`,
          tag: `haven-offer-${off.dispatch_id}`,
        })
      }
    } catch { /* noop */ }
  }

  // ─── geolocation: eligibility freshness (REST) + live stream while assigned ───
  // Privacy by design: we only read GPS while the responder is AVAILABLE/BUSY or
  // holds a live assignment. When OFFLINE and unassigned, no location is read.
  const shouldTrack = !!me && (me.status === 'AVAILABLE' || me.status === 'BUSY' || !!active)

  useEffect(() => {
    if (!token || !shouldTrack) {
      if (watchRef.current != null && typeof navigator !== 'undefined') {
        navigator.geolocation?.clearWatch(watchRef.current)
        watchRef.current = null
      }
      return
    }
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeoError('This device/browser does not support location. Eligibility needs a live GPS fix.')
      return
    }
    const onFix = (pos: GeolocationPosition) => {
      setGeoError('')
      const f: GeoFix = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: new Date().toISOString(),
      }
      setFix(f)
      // Accumulate real GPS frames for movement trail (max 40, in-memory only) while assigned.
      if (activeIdRef.current) {
        setTrail((prev) => {
          const next = [...prev, { lat: f.lat, lng: f.lng }]
          return next.slice(-40)
        })
      }
      // 1) REST post (throttled) keeps eligibility location fresh server-side.
      const now = Date.now()
      if (now - lastPostRef.current >= LOCATION_POST_MS) {
        lastPostRef.current = now
        postResponderLocation({ latitude: f.lat, longitude: f.lng, accuracy: f.accuracy ?? null })
          .catch(() => { /* non-fatal; next fix retries */ })
      }
      // 2) Live stream to the incident room — ONLY while actively assigned.
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN && activeIdRef.current) {
        try {
          ws.send(JSON.stringify({
            dispatch_id: activeIdRef.current,
            latitude: f.lat, longitude: f.lng,
            accuracy: f.accuracy ?? null, timestamp: f.timestamp,
          }))
        } catch { /* noop */ }
      }
    }
    const onErr = (e: GeolocationPositionError) => {
      setGeoError(
        e.code === e.PERMISSION_DENIED
          ? 'Location permission denied. You cannot be dispatched without a live GPS fix.'
          : 'Unable to read your location right now. Retrying…',
      )
    }
    watchRef.current = navigator.geolocation.watchPosition(onFix, onErr, {
      enableHighAccuracy: true, maximumAge: 5000, timeout: 20000,
    })
    return () => {
      if (watchRef.current != null) {
        navigator.geolocation.clearWatch(watchRef.current)
        watchRef.current = null
      }
    }
  }, [token, shouldTrack])

  // ─── authenticated live socket to the incident room (open only while assigned) ─
  const broadcastable = !!active && (active.status === 'ACCEPTED' || active.status === 'EN_ROUTE' || active.status === 'ARRIVED')

  useEffect(() => {
    if (!token || !broadcastable || !active) {
      if (wsRef.current) { try { wsRef.current.close() } catch { /* noop */ } wsRef.current = null }
      setWsConnected(false)
      return
    }
    const base = API.replace(/^http/, 'ws')
    const url = `${base}/ws/dispatch/${encodeURIComponent(active.dispatch_id)}?token=${encodeURIComponent(token)}`
    let closed = false
    const ws = new WebSocket(url)
    wsRef.current = ws
    ws.onopen = () => {
      if (closed) return
      setWsConnected(true)
      // Push one frame immediately so the victim/authority map updates without waiting.
      const f = fixRef.current
      if (f) {
        try {
          ws.send(JSON.stringify({
            dispatch_id: active.dispatch_id,
            latitude: f.lat, longitude: f.lng,
            accuracy: f.accuracy ?? null, timestamp: f.timestamp,
          }))
        } catch { /* noop */ }
      }
    }
    ws.onclose = () => { if (!closed) setWsConnected(false) }
    ws.onerror = () => { if (!closed) setWsConnected(false) }
    return () => {
      closed = true
      try { ws.close() } catch { /* noop */ }
      if (wsRef.current === ws) wsRef.current = null
      setWsConnected(false)
    }
  }, [token, broadcastable, active?.dispatch_id])

  // ─── actions (every one re-reads server truth via refresh afterward) ──────────
  const changeStatus = useCallback(async (status: ResponderStatus) => {
    setBusyAction(`status:${status}`); setError(''); setNotice('')
    try {
      const rec = await setResponderStatus(status)
      setMe(rec)
      setNotice(status === 'AVAILABLE' ? 'You are now AVAILABLE for dispatch.' : `Status set to ${status}.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not update status.')
    } finally { setBusyAction(''); refresh() }
  }, [refresh])

  // Background notifications: explicit user action only, honest state copy.
  const [pushState, setPushState] = useState<PushState | null>(null)
  useEffect(() => {
    if (!token) return
    currentPushState().then(setPushState).catch(() => setPushState('NOT_CONFIGURED'))
  }, [token])
  const onEnablePush = useCallback(async () => {
    setBusyAction('push'); setError('')
    try { setPushState(await enablePush()) } finally { setBusyAction('') }
  }, [])

  // Duty is a SEPARATE axis from availability. ON_DUTY requires explicit consent to
  // share operational location; the backend enforces it, the UI only asks.
  const changeDuty = useCallback(async (duty: 'ON_DUTY' | 'OFF_DUTY') => {
    if (duty === 'ON_DUTY' && !window.confirm(
      'Your operational location will be shared with authorized HAVEN authorities while you are on duty. Continue?')) {
      return
    }
    setBusyAction(`duty:${duty}`); setError(''); setNotice('')
    try {
      const rec = await setResponderDuty(duty, duty === 'ON_DUTY')
      setMe(rec)
      setNotice(duty === 'ON_DUTY'
        ? 'You are ON DUTY. Set AVAILABLE to receive offers.'
        : 'You are OFF DUTY. Location sharing has stopped.')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not change duty status.')
    } finally { setBusyAction(''); refresh() }
  }, [refresh])

  const onAccept = useCallback(async (id: string) => {
    setBusyAction(`accept:${id}`); setError(''); setNotice('')
    try {
      await acceptOffer(id)
      seenOfferIds.current.delete(id)
      setNotice('Offer accepted. Navigate to the incident and keep this screen open.')
    } catch (err: unknown) {
      // A lost race is expected and must read truthfully, not as a hard failure.
      setError(err instanceof Error ? err.message : 'This offer is no longer available.')
    } finally { setBusyAction(''); refresh() }
  }, [refresh])

  const onDecline = useCallback(async (id: string) => {
    setBusyAction(`decline:${id}`); setError('')
    try { await declineOffer(id) } catch { /* already gone — fine */ }
    finally {
      seenOfferIds.current.delete(id)
      setBusyAction(''); refresh()
    }
  }, [refresh])

  const onProgress = useCallback(async (id: string, kind: 'enroute' | 'arrived' | 'help') => {
    setBusyAction(`${kind}:${id}`); setError('')
    try {
      if (kind === 'enroute') await markEnRoute(id)
      else if (kind === 'arrived') await markArrived(id)
      else await markHelpProvided(id)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not update the incident status.')
    } finally { setBusyAction(''); refresh() }
  }, [refresh])

  // ─── derived values for the view ─────────────────────────────────────────────
  const incidentMarker = active?.incident_location
    ? { lat: active.incident_location.coordinates[1], lng: active.incident_location.coordinates[0] }
    : null
  const responderMarker = fix
    ? { lat: fix.lat, lng: fix.lng, accuracy: fix.accuracy, timestamp: fix.timestamp }
    : null
  const offerDistance = (o: ResponderOffer) =>
    o.distance_m != null ? formatDistance(o.distance_m) : null
  const assignedDistance = incidentMarker && responderMarker
    ? routeProvider.calculateRoute(responderMarker, incidentMarker).distance_m
    : null

  // ─── not-signed-in: badge + password form (role comes from the server token) ──
  if (!authReady) {
    return (
      <div style={S.shell}>
        <div style={{ color: '#64748b', padding: 40 }}>Loading…</div>
      </div>
    )
  }

  if (!token) {
    return (
      <div style={S.shell}>
        <div style={S.loginCard}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <Shield size={26} color="#2563eb" />
            <h1 style={{ margin: 0, fontSize: '1.3rem', color: '#0f172a' }}>HAVEN Responder</h1>
          </div>
          <p style={{ color: '#64748b', fontSize: '0.86rem', marginTop: 0 }}>
            Verified field responders only. Sign in with your assigned badge number and password.
          </p>
          <form onSubmit={login}>
            <label style={S.label} htmlFor="r-badge">Badge number</label>
            <input id="r-badge" style={S.input} value={badge} autoComplete="username"
              onChange={(e) => setBadge(e.target.value)} placeholder="e.g. HN-204" />
            <label style={S.label} htmlFor="r-pass">Password</label>
            <input id="r-pass" style={S.input} type="password" value={password} autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)} />
            {authError && <div role="alert" style={S.errorBox}>{authError}</div>}
            <button type="submit" disabled={authBusy || !badge.trim() || !password} style={S.primaryBtn}>
              {authBusy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          <Link href="/" style={{ ...S.backLink, marginTop: 18, justifyContent: 'center' }}>
            <ArrowLeft size={16} /> Back to HAVEN
          </Link>
        </div>
      </div>
    )
  }

  const verified = !!me?.verified
  const activeAssn = !!active
  const statusVal = me?.status || 'OFFLINE'

  // ─── signed-in dashboard ──────────────────────────────────────────────────────
  return (
    <div style={S.shell}>
      <div style={S.container}>
        {/* Header */}
        <div style={S.header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Shield size={24} color="#2563eb" />
            <div>
              <div style={{ fontWeight: 800, color: '#0f172a', fontSize: '1.1rem' }}>HAVEN Responder</div>
              <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
                {me?.display_label || me?.badge_number || 'Verified unit'}
              </div>
            </div>
          </div>
          <button onClick={logout} style={S.ghostBtn} aria-label="Sign out">
            <LogOut size={16} /> Sign out
          </button>
        </div>

        {/* Verification / account banner */}
        {!verified && (
          <div role="status" style={S.warnBox}>
            Your account is not yet verified by an administrator. You can sign in and set
            availability, but you will not receive dispatch offers until an admin verifies you.
          </div>
        )}

        {/* Status / notice strip */}
        <div aria-live="polite">
          {notice && <div style={S.noticeBox}>{notice}</div>}
          {error && <div role="alert" style={S.errorBox}>{error}</div>}
          {geoError && <div role="alert" style={S.warnBox}>{geoError}</div>}
        </div>

        {/* Account facts */}
        <div style={S.card}>
          <div style={S.cardTitle}>Your unit</div>
          <div style={S.kvGrid}>
            <span style={S.k}>Unit label</span><span style={S.v}>{me?.display_label || '—'}</span>
            <span style={S.k}>Badge</span><span style={S.v}>{me?.badge_number || '—'}</span>
            <span style={S.k}>Role</span><span style={S.v}>{me?.role || 'responder'}</span>
            <span style={S.k}>Verified</span>
            <span style={S.v}>{verified ? <span style={{ color: '#15803d', fontWeight: 700 }}>Yes</span> : <span style={{ color: '#b45309', fontWeight: 700 }}>Pending</span>}</span>
            <span style={S.k}>Jurisdiction</span><span style={S.v}>{me?.jurisdiction || '—'}</span>
            <span style={S.k}>Capabilities</span><span style={S.v}>{me?.capabilities?.length ? me.capabilities.join(', ') : '—'}</span>
          </div>
        </div>

        {/* Availability + live location */}
        <div style={S.card}>
          <div style={S.cardTitle}>Status &amp; Availability</div>
          {activeAssn ? (
            <div style={S.lockedRow}>
              <span style={S.pillBusy}>🟡 BUSY — assigned to active emergency</span>
              <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                Availability is locked while you hold an active emergency assignment.
              </span>
            </div>
          ) : (
            <>
              {/* Status display */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ fontSize: '0.88rem', fontWeight: 700, color: '#0f172a' }}>
                  {statusVal === 'AVAILABLE' ? '🟢 ON DUTY' : statusVal === 'BUSY' ? '🟡 BUSY' : '⚪ OFF DUTY'}
                </span>
                <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                  {statusVal === 'AVAILABLE'
                    ? 'Eligible to receive emergency dispatch offers'
                    : 'Not receiving emergency dispatch offers'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button
                  onClick={() => changeDuty('ON_DUTY')}
                  disabled={!!busyAction || !verified}
                  aria-pressed={me?.duty_status === 'ON_DUTY'}
                  style={{
                    ...S.statusBtn,
                    ...(me?.duty_status === 'ON_DUTY' ? S.statusBtnOn : {}),
                    ...(!verified ? S.statusBtnDisabled : {}),
                  }}>
                  🟢 GO ON DUTY
                </button>
                <button
                  onClick={() => changeDuty('OFF_DUTY')}
                  disabled={!!busyAction || me?.duty_status !== 'ON_DUTY'}
                  aria-pressed={me?.duty_status !== 'ON_DUTY'}
                  style={{
                    ...S.statusBtn,
                    ...(me?.duty_status !== 'ON_DUTY' ? S.statusBtnOn : {}),
                  }}>
                  ⚪ GO OFF DUTY
                </button>
                <button
                  onClick={() => changeStatus('AVAILABLE')}
                  disabled={!!busyAction || !verified || me?.duty_status !== 'ON_DUTY'}
                  aria-pressed={statusVal === 'AVAILABLE'}
                  style={{
                    ...S.statusBtn,
                    ...(statusVal === 'AVAILABLE' ? S.statusBtnOn : {}),
                  }}>
                  ✅ MARK AVAILABLE
                </button>
              </div>
            </>
          )}

          {/* Background alerts: honest status, explicit enable */}
          <div style={{ marginTop: 12, fontSize: '0.8rem', color: '#334155' }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Background alerts</div>
            <div aria-live="polite" style={{ marginBottom: 6 }}>
              {pushState ? PUSH_STATE_COPY[pushState] : 'Checking notification status...'}
            </div>
            {pushState && pushState !== 'NOT_SUPPORTED' && pushState !== 'NOT_CONFIGURED' && pushState !== 'SUBSCRIBED' && (
              <button
                onClick={onEnablePush}
                disabled={!!busyAction}
                style={{ ...S.statusBtn }}>
                Enable background alerts
              </button>
            )}
          </div>

          {/* Live location freshness */}
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem' }}>
            <MapPin size={15} color={fix ? '#15803d' : '#94a3b8'} />
            {fix ? (
              <span style={{ color: '#334155' }}>
                Live location shared{fix.accuracy ? ` (±${Math.round(fix.accuracy)} m)` : ''}. Eligibility stays fresh while you are available.
              </span>
            ) : shouldTrack ? (
              <span style={{ color: '#b45309' }}>Acquiring your GPS fix…</span>
            ) : (
              <span style={{ color: '#64748b' }}>Location is only read while you are available or assigned.</span>
            )}
          </div>
        </div>

        {/* Active assignment OR pending offers */}
        {active ? (
          <div style={S.card}>
            <div style={S.cardTitle}>Active assignment</div>
            <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>
              {DISPATCH_STATUS_LABEL[active.status as DispatchStatus] || active.status}
            </div>

            <LiveResponseMap
              incident={incidentMarker}
              responder={responderMarker}
              trail={trail}
              connected={wsConnected}
              height={300}
              showFitButton
              showFollowButton
              fitNonce={fitNonce}
              onFollow={() => setFitNonce((n) => n + 1)}
              onFitAll={() => setFitNonce((n) => n + 1)}
              caption="You are sharing your live location with this incident only."
            />

            {active.required_capability && (
              <div style={{ marginTop: 10, fontSize: '0.82rem', color: '#334155' }}>
                <strong>Capability requested:</strong> {active.required_capability}
              </div>
            )}
            {active.notes && (
              <div style={{ marginTop: 6, fontSize: '0.82rem', color: '#334155' }}>
                <strong>Dispatcher note:</strong> {active.notes}
              </div>
            )}

            {/* Navigation (external, no fabricated ETA) */}
            {incidentMarker && (
              <a href={externalNavUrl(incidentMarker)} target="_blank" rel="noopener noreferrer"
                style={{ ...S.primaryBtn, display: 'inline-flex', alignItems: 'center', gap: 8, textDecoration: 'none', marginTop: 14 }}>
                <Navigation size={18} /> Navigate to incident
              </a>
            )}

            {/* Progress controls — forward-only, mirror the server FSM */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
              {active.status === 'ACCEPTED' && (
                <button onClick={() => onProgress(active.dispatch_id, 'enroute')} disabled={!!busyAction} style={S.progressBtn}>
                  I&apos;m en route
                </button>
              )}
              {active.status === 'EN_ROUTE' && (
                <button onClick={() => onProgress(active.dispatch_id, 'arrived')} disabled={!!busyAction} style={S.progressBtn}>
                  I&apos;ve arrived
                </button>
              )}
              {active.status === 'ARRIVED' && (
                <button onClick={() => onProgress(active.dispatch_id, 'help')} disabled={!!busyAction} style={S.progressBtn}>
                  Help provided
                </button>
              )}
            </div>
          </div>
        ) : (
          <OffersSection
            offers={offers}
            statusVal={statusVal}
            verified={verified}
            busyAction={busyAction}
            offerDistance={offerDistance}
            onAccept={onAccept}
            onDecline={onDecline}
          />
        )}
      </div>

      {/* Full-screen incoming-offer modal — rendered on top of everything. */}
      {incomingOffer && !active && (
        <IncomingOfferModal
          offer={incomingOffer}
          distance={offerDistance(incomingOffer)}
          busyAction={busyAction}
          onAccept={(id) => { setIncomingOffer(null); onAccept(id) }}
          onDecline={(id) => { setIncomingOffer(null); onDecline(id) }}
          onDismiss={() => setIncomingOffer(null)}
        />
      )}
    </div>
  )
}

/**
 * Full-screen overlay shown when a new emergency offer arrives.
 *
 * The overlay is intentionally jarring (pulsing red border, prominent buttons)
 * because a field responder in a vehicle or on foot may have their screen locked
 * when the offer arrives. The Dismiss option lets them close the modal if they
 * want to see the full dashboard first; the offer card remains visible below.
 */
function IncomingOfferModal({
  offer, distance, busyAction, onAccept, onDecline, onDismiss,
}: {
  offer: ResponderOffer
  distance: string | null
  busyAction: string
  onAccept: (id: string) => void
  onDecline: (id: string) => void
  onDismiss: () => void
}) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)

  useEffect(() => {
    if (!offer.offer_expires_at) return
    const calc = () => {
      const diff = Math.max(0, Math.round((new Date(offer.offer_expires_at!).getTime() - Date.now()) / 1000))
      setSecondsLeft(diff)
    }
    calc()
    const id = setInterval(calc, 1000)
    return () => clearInterval(id)
  }, [offer.offer_expires_at])

  const fmt = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="Incoming emergency request"
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div style={{
        background: '#fff', borderRadius: 18, padding: 24,
        maxWidth: 420, width: '100%',
        border: '3px solid #dc2626',
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        animation: 'haven-pulse 1s ease-in-out infinite',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '1.5rem' }}>🚨</span>
            <div>
              <div style={{ fontWeight: 900, color: '#dc2626', fontSize: '1.1rem', letterSpacing: '0.04em' }}>
                EMERGENCY REQUEST
              </div>
              <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600 }}>
                Broadcast to all eligible responders — first to accept wins
              </div>
            </div>
          </div>
        </div>

        {/* Details */}
        <div style={{ background: '#fff5f5', borderRadius: 10, padding: '12px 14px', marginBottom: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 14, rowGap: 6, fontSize: '0.88rem' }}>
            <span style={{ color: '#64748b' }}>Distance:</span>
            <span style={{ fontWeight: 800, color: '#0f172a' }}>{distance ? `${distance} (straight-line)` : 'Calculating…'}</span>

            <span style={{ color: '#64748b' }}>Type:</span>
            <span style={{ fontWeight: 600, color: '#334155' }}>
              {offer.required_capability ? `Emergency (${offer.required_capability})` : 'Emergency response'}
            </span>

            {secondsLeft !== null && (
              <>
                <span style={{ color: '#dc2626', fontWeight: 700 }}>Expires in:</span>
                <span style={{
                  fontWeight: 900, fontFamily: 'monospace', fontSize: '1.05rem',
                  color: secondsLeft <= 10 ? '#dc2626' : '#ea580c',
                }}>
                  {fmt(secondsLeft)}
                </span>
              </>
            )}
          </div>
          {offer.notes && (
            <div style={{ marginTop: 8, fontSize: '0.82rem', color: '#475569', borderTop: '1px solid #fee2e2', paddingTop: 8 }}>
              {offer.notes}
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
          <button
            onClick={() => onAccept(offer.dispatch_id)}
            disabled={!!busyAction}
            style={{
              flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              gap: 8, padding: '16px 14px', fontSize: '1.1rem', fontWeight: 900,
              color: '#fff', background: '#16a34a', border: 'none', borderRadius: 12, cursor: 'pointer',
              opacity: busyAction ? 0.6 : 1,
            }}
            aria-label="Accept this emergency request"
          >
            <CheckCircle size={20} /> ACCEPT
          </button>
          <button
            onClick={() => onDecline(offer.dispatch_id)}
            disabled={!!busyAction}
            style={{
              flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              gap: 8, padding: '16px 14px', fontSize: '1.1rem', fontWeight: 900,
              color: '#b91c1c', background: '#fef2f2', border: '2px solid #fecaca',
              borderRadius: 12, cursor: 'pointer', opacity: busyAction ? 0.6 : 1,
            }}
            aria-label="Decline this emergency request"
          >
            <XCircle size={20} /> DECLINE
          </button>
        </div>

        {/* Dismiss (close modal, offer card still visible in list) */}
        <button
          onClick={onDismiss}
          style={{
            width: '100%', padding: '10px', fontSize: '0.84rem', fontWeight: 700,
            color: '#64748b', background: '#f1f5f9', border: '1px solid #e2e8f0',
            borderRadius: 10, cursor: 'pointer',
          }}
        >
          Dismiss alert — offer still visible below
        </button>

        <style>{`
          @keyframes haven-pulse {
            0%, 100% { box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 0 0 rgba(220,38,38,0.4); }
            50% { box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 0 10px rgba(220,38,38,0); }
          }
        `}</style>
      </div>
    </div>
  )
}


/* ─── pending-offers section (shown only when there is no active assignment) ──── */
function OffersSection({
  offers, statusVal, verified, busyAction, offerDistance, onAccept, onDecline,
}: {
  offers: ResponderOffer[]
  statusVal: ResponderStatus
  verified: boolean
  busyAction: string
  offerDistance: (o: ResponderOffer) => string | null
  onAccept: (id: string) => void
  onDecline: (id: string) => void
}) {
  if (!offers.length) {
    let msg = 'You are offline. Go available to start receiving response requests.'
    if (statusVal === 'AVAILABLE') msg = verified
      ? 'You are available. Waiting for a response request — this screen updates automatically.'
      : 'Waiting for an administrator to verify your account before requests can reach you.'
    else if (statusVal === 'UNAVAILABLE') msg = 'You are paused. Go available to receive requests again.'
    return (
      <div style={S.card}>
        <div style={S.cardTitle}>Response requests</div>
        <div style={{ color: '#64748b', fontSize: '0.86rem' }}>{msg}</div>
      </div>
    )
  }
  return (
    <div style={S.card}>
      <div style={S.cardTitle}>Emergency Response Offers ({offers.length})</div>
      <div style={{ display: 'grid', gap: 14 }}>
        {offers.map((o) => {
          const dist = offerDistance(o)
          return (
            <OfferCard
              key={o.dispatch_id}
              offer={o}
              distance={dist}
              busyAction={busyAction}
              onAccept={onAccept}
              onDecline={onDecline}
            />
          )
        })}
      </div>
      <div style={{ marginTop: 12, fontSize: '0.74rem', color: '#94a3b8' }}>
        ⚡ Broadcast offer: First verified provider to accept claims this emergency. If another provider accepts first, this offer will automatically close.
      </div>
    </div>
  )
}

function OfferCard({
  offer, distance, busyAction, onAccept, onDecline,
}: {
  offer: ResponderOffer
  distance: string | null
  busyAction: string
  onAccept: (id: string) => void
  onDecline: (id: string) => void
}) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)

  useEffect(() => {
    if (!offer.offer_expires_at) return
    const calc = () => {
      const diff = Math.max(0, Math.round((new Date(offer.offer_expires_at!).getTime() - Date.now()) / 1000))
      setSecondsLeft(diff)
    }
    calc()
    const timer = setInterval(calc, 1000)
    return () => clearInterval(timer)
  }, [offer.offer_expires_at])

  const formatTimer = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div style={{
      ...S.offerCard,
      border: '2px solid #ef4444',
      background: '#fff5f5',
      borderRadius: 12,
      padding: 16,
    }} role="group" aria-label="HAVEN Emergency Request">
      {/* Emergency Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: '1.1rem' }}>🚨</span>
          <span style={{ fontWeight: 800, color: '#dc2626', fontSize: '0.95rem', letterSpacing: '0.04em' }}>
            HAVEN EMERGENCY
          </span>
        </div>
        <span style={{
          background: '#dc2626', color: '#fff', fontSize: '0.68rem', fontWeight: 800,
          padding: '2px 8px', borderRadius: 6, letterSpacing: '0.06em',
        }}>
          CRITICAL
        </span>
      </div>

      <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>
        Immediate response required
      </div>

      {/* Incident details */}
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 12, rowGap: 4, fontSize: '0.82rem', marginBottom: 12 }}>
        <span style={{ color: '#64748b' }}>Distance:</span>
        <span style={{ fontWeight: 700, color: '#0f172a' }}>{distance ? `${distance} (straight-line)` : 'Calculating…'}</span>

        <span style={{ color: '#64748b' }}>Incident type:</span>
        <span style={{ fontWeight: 600, color: '#334155' }}>
          {offer.required_capability ? `Emergency response (${offer.required_capability})` : 'Emergency response'}
        </span>

        {secondsLeft !== null && (
          <>
            <span style={{ color: '#dc2626', fontWeight: 600 }}>Request expires:</span>
            <span style={{ fontWeight: 800, color: secondsLeft <= 10 ? '#dc2626' : '#ea580c', fontFamily: 'monospace' }}>
              {formatTimer(secondsLeft)}
            </span>
          </>
        )}
      </div>

      {offer.notes && (
        <div style={{ fontSize: '0.8rem', color: '#475569', marginBottom: 12, background: '#f8fafc', padding: '6px 10px', borderRadius: 6 }}>
          {offer.notes}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button
          onClick={() => onAccept(offer.dispatch_id)}
          disabled={!!busyAction}
          style={{
            ...S.acceptBtn,
            background: '#16a34a',
            color: '#fff',
            fontWeight: 800,
            padding: '10px 24px',
            fontSize: '0.9rem',
          }}
          aria-label="Accept this emergency request">
          <CheckCircle size={18} /> ACCEPT
        </button>
        <button
          onClick={() => onDecline(offer.dispatch_id)}
          disabled={!!busyAction}
          style={{
            ...S.declineBtn,
            fontWeight: 700,
            padding: '10px 18px',
          }}
          aria-label="Decline this emergency request">
          <XCircle size={18} /> DECLINE
        </button>
      </div>
    </div>
  )
}

/* small coloured dot describing the current availability state */
function s_dot(status: ResponderStatus) {
  const color = status === 'AVAILABLE' ? '#22c55e' : status === 'BUSY' ? '#f59e0b'
    : status === 'UNAVAILABLE' ? '#eab308' : '#94a3b8'
  return (
    <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: color, marginLeft: 8, verticalAlign: 'middle' }} />
  )
}

/* ─── styles (inline, high-contrast, large touch targets for field use) ──────── */
const S: Record<string, React.CSSProperties> = {
  shell: {
    minHeight: '100vh', background: '#f1f5f9',
    display: 'flex', justifyContent: 'center',
    padding: '20px 14px', fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  },
  container: { width: '100%', maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 14 },
  loginCard: {
    width: '100%', maxWidth: 400, background: '#fff', borderRadius: 16,
    padding: 28, boxShadow: '0 10px 30px rgba(2,6,23,0.08)', alignSelf: 'center',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    background: '#fff', borderRadius: 14, padding: '12px 16px', boxShadow: '0 2px 10px rgba(2,6,23,0.05)',
  },
  card: { background: '#fff', borderRadius: 14, padding: 16, boxShadow: '0 2px 10px rgba(2,6,23,0.05)' },
  cardTitle: { fontSize: '0.72rem', fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#64748b', marginBottom: 10 },
  kvGrid: { display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 14, rowGap: 7, fontSize: '0.86rem' },
  k: { color: '#64748b' },
  v: { color: '#0f172a', fontWeight: 600, textAlign: 'right' },
  label: { display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', margin: '12px 0 5px' },
  input: {
    width: '100%', boxSizing: 'border-box', padding: '12px 14px', fontSize: '1rem',
    border: '1px solid #cbd5e1', borderRadius: 10, outline: 'none', color: '#0f172a',
  },
  primaryBtn: {
    width: '100%', marginTop: 16, padding: '14px 16px', fontSize: '1rem', fontWeight: 800,
    color: '#fff', background: '#2563eb', border: 'none', borderRadius: 12, cursor: 'pointer',
  },
  ghostBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 12px', fontSize: '0.84rem',
    fontWeight: 700, color: '#334155', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 10, cursor: 'pointer',
  },
  backLink: { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#2563eb', textDecoration: 'none', fontSize: '0.86rem', fontWeight: 600 },
  statusBtn: {
    flex: '1 1 120px', padding: '14px 12px', fontSize: '0.95rem', fontWeight: 800,
    color: '#334155', background: '#f1f5f9', border: '2px solid #e2e8f0', borderRadius: 12, cursor: 'pointer',
  },
  statusBtnOn: { color: '#fff', background: '#2563eb', borderColor: '#2563eb' },
  statusBtnDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  progressBtn: {
    flex: '1 1 160px', padding: '16px 14px', fontSize: '1.05rem', fontWeight: 800,
    color: '#fff', background: '#1d4ed8', border: 'none', borderRadius: 12, cursor: 'pointer',
  },
  acceptBtn: {
    flex: '1 1 140px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    padding: '16px 14px', fontSize: '1.05rem', fontWeight: 800, color: '#fff',
    background: '#16a34a', border: 'none', borderRadius: 12, cursor: 'pointer',
  },
  declineBtn: {
    flex: '1 1 140px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    padding: '16px 14px', fontSize: '1.05rem', fontWeight: 800, color: '#b91c1c',
    background: '#fef2f2', border: '2px solid #fecaca', borderRadius: 12, cursor: 'pointer',
  },
  offerCard: { border: '2px solid #bfdbfe', background: '#eff6ff', borderRadius: 12, padding: 14 },
  lockedRow: { display: 'flex', flexDirection: 'column', gap: 6 },
  pillBusy: {
    alignSelf: 'flex-start', padding: '6px 12px', borderRadius: 999, fontSize: '0.82rem', fontWeight: 800,
    color: '#92400e', background: '#fef3c7', border: '1px solid #fde68a',
  },
  warnBox: { background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e', borderRadius: 10, padding: '10px 12px', fontSize: '0.84rem' },
  errorBox: { background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', borderRadius: 10, padding: '10px 12px', fontSize: '0.84rem', marginTop: 8 },
  noticeBox: { background: '#ecfdf5', border: '1px solid #a7f3d0', color: '#065f46', borderRadius: 10, padding: '10px 12px', fontSize: '0.84rem' },
}



