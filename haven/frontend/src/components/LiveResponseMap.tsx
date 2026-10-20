'use client'
/**
 * LiveResponseMap — vendor-neutral OSM raster-tile map for the Rapid Response
 * Network. Purely presentational: the parent owns the authenticated WebSocket and
 * passes down the incident + responder coordinates. Renders with no external map
 * library (none is installed), is SSR-safe (client component, tile math in render),
 * and updates markers in near real time without a page refresh.
 *
 * Honesty rules enforced here: distance is labelled straight-line, ETA is never
 * fabricated (shows "Route estimate unavailable"), and a stale responder fix is
 * clearly marked rather than shown as current.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  LatLng, TILE_SIZE, project, tileUrl, routeProvider, formatDistance,
  freshnessLabel, isStale, MAP_ATTRIBUTION,
} from '@/lib/mapProvider'

export interface MapMarker {
  lat: number
  lng: number
  accuracy?: number | null
  timestamp?: string | null
}

/**
 * A SECONDARY unit marker (authority command map only): an eligible/offered/busy/
 * offline unit plotted as a small ○, deliberately distinct from the single 🚔
 * assigned responder (passed via `responder`). Presence on the map means
 * eligible/visible — NOT assigned. These never appear on the victim map.
 */
export interface UnitMarker {
  id: string
  lat: number
  lng: number
  label?: string
  kind?: 'eligible' | 'offered' | 'assigned' | 'busy' | 'offline'
}

interface LiveResponseMapProps {
  incident: MapMarker | null
  responder: MapMarker | null
  /** True once the live socket is open; drives the connection dot + stale logic. */
  connected?: boolean
  height?: number
  /** Caption under the map, e.g. who is being tracked. */
  caption?: string
  /**
   * When provided, OVERRIDES the built-in "Live / Connecting…" dot with a truthful
   * state label supplied by the parent (e.g. "🟡 Reconnecting…", "⚪ Waiting for
   * responder acceptance"). This lets the Rapid Response Center show a state that
   * matches the authoritative dispatch lifecycle rather than just socket openness.
   */
  connectionLabel?: string
  connectionTone?: 'green' | 'yellow' | 'orange' | 'red' | 'grey'
  /** Render a subtle legend (📍 incident / 🚔 responder) over the map. */
  showLegend?: boolean
  /**
   * Overrides the bottom strip's responder-location line. The parent passes the
   * single honest line here so the map never claims "Awaiting responder location…"
   * before a responder has actually accepted.
   */
  locationNote?: string | null
  /**
   * SECONDARY unit markers (authority command map). Eligible/nearby units plot as
   * ○ around the incident so an operator can see coverage BEFORE dispatch. These
   * are visibility only — the map exposes no way to assign or force a unit.
   */
  units?: UnitMarker[]
  /** Called with a unit id when its ○ marker is clicked (opens a read-only panel). */
  onUnitClick?: (id: string) => void
  /** The unit id currently highlighted/selected (drawn larger with a ring). */
  selectedUnitId?: string | null
  /**
   * Auto-fit is CALM: the view only recomputes when the SET of markers changes
   * (markers added/removed, incident/unit coords, size) — not on every live
   * responder frame. Bump `fitNonce` to force an explicit re-fit from the parent.
   */
  fitNonce?: number
  /** Render a small "Fit map" button that re-fits all markers into view. */
  showFitButton?: boolean
  /** Temporary client-side GPS movement trail for the accepted provider (max 40 in-memory points). */
  trail?: Array<{ lat: number; lng: number }>
  /** Render a "Follow responder" button. */
  showFollowButton?: boolean
  /** Callback when user clicks "Follow responder". */
  onFollow?: () => void
  /** Callback when user clicks "Fit incident + responder". */
  onFitAll?: () => void
  /** Whether a provider has accepted the dispatch (drives Phase 6 truthful ETA display). */
  responderAccepted?: boolean
  /** Authoritative dispatch status (e.g. OFFERED, ACCEPTED, FAILED) for truthful strip presentation. */
  dispatchStatus?: string
  /** Explicit override for the ETA/status line. */
  etaLabel?: string | null
  /** Total count of verified units on the network (used for truthful network empty state). */
  networkTotalCount?: number
  /** Custom empty state message when no markers can be plotted. */
  emptyMessage?: string
}

const CONNECTION_TONE_COLORS: Record<string, string> = {
  green: '#22c55e', yellow: '#eab308', orange: '#f59e0b', red: '#dc2626', grey: '#9ca3af',
}

// Secondary-unit marker palette. These are deliberately NOT the 🚔 assigned glyph —
// a ○ in any of these tones means "visible/eligible", never "assigned".
const UNIT_KIND_COLORS: Record<string, string> = {
  eligible: '#2563eb', offered: '#f59e0b', assigned: '#db2777',
  busy: '#9333ea', offline: '#9ca3af',
}

interface View { center: LatLng; zoom: number }

function fitView(points: LatLng[], vw: number, vh: number, pad = 56): View {
  if (points.length === 0) return { center: { lat: 20.5937, lng: 78.9629 }, zoom: 4 } // India fallback
  if (points.length === 1) return { center: points[0], zoom: 15 }
  const lats = points.map((p) => p.lat)
  const lngs = points.map((p) => p.lng)
  const center = { lat: (Math.min(...lats) + Math.max(...lats)) / 2, lng: (Math.min(...lngs) + Math.max(...lngs)) / 2 }
  for (let z = 18; z >= 2; z--) {
    const px = points.map((p) => project(p.lat, p.lng, z))
    const w = Math.max(...px.map((q) => q.x)) - Math.min(...px.map((q) => q.x))
    const h = Math.max(...px.map((q) => q.y)) - Math.min(...px.map((q) => q.y))
    if (w <= vw - pad * 2 && h <= vh - pad * 2) return { center, zoom: z }
  }
  return { center, zoom: 2 }
}

export default function LiveResponseMap({
  incident, responder, connected = false, height = 300, caption,
  connectionLabel, connectionTone = 'grey', showLegend = false, locationNote,
  units, onUnitClick, selectedUnitId, fitNonce = 0, showFitButton = false,
  trail = [], showFollowButton = false, onFollow, onFitAll,
  responderAccepted = false, dispatchStatus, etaLabel, networkTotalCount, emptyMessage,
}: LiveResponseMapProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [vw, setVw] = useState(480)
  // Tick every second so freshness labels / stale marking stay live.
  const [, setNow] = useState(Date.now())
  // Local nonce for the built-in [Fit map] button; combined with the parent's.
  const [localFit, setLocalFit] = useState(0)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => setVw(Math.max(240, Math.round(el.getBoundingClientRect().width)))
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure) }
  }, [])

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const vh = height
  const incLL: LatLng | null = incident ? { lat: incident.lat, lng: incident.lng } : null
  const resLL: LatLng | null = responder ? { lat: responder.lat, lng: responder.lng } : null
  const unitList = useMemo(() => (units || []).filter(
    (u) => Number.isFinite(u.lat) && Number.isFinite(u.lng),
  ), [units])
  const points: LatLng[] = [incLL, resLL].filter(Boolean) as LatLng[]
  const fitPoints: LatLng[] = [...points, ...unitList.map((u) => ({ lat: u.lat, lng: u.lng }))]

  // Calm auto-fit (P19): recompute the view only when the SET of markers changes —
  // incident/unit coordinates, the responder's PRESENCE (not its live position),
  // the viewport width, or an explicit fit request. A moving responder frame does
  // NOT refit, so the map stops lurching on every live update.
  const fitSig = useMemo(() => {
    const parts: string[] = []
    if (incLL) parts.push(`i:${incLL.lat.toFixed(4)},${incLL.lng.toFixed(4)}`)
    if (resLL) parts.push('r')  // presence only — intentionally position-independent
    for (const u of unitList) parts.push(`u:${u.id}:${u.lat.toFixed(4)},${u.lng.toFixed(4)}`)
    parts.push(`w:${Math.round(vw / 40)}`, `h:${vh}`, `n:${fitNonce + localFit}`)
    return parts.join('|')
  }, [incLL, resLL, unitList, vw, vh, fitNonce, localFit])

  const [view, setView] = useState<View | null>(null)
  useEffect(() => {
    setView(fitView(fitPoints, vw, vh))
    // Deliberately keyed on the stable signature, not the per-frame coords.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitSig])
  const { center, zoom } = view ?? fitView(fitPoints, vw, vh)

  // Viewport top-left in world pixels.
  const c = project(center.lat, center.lng, zoom)
  const originX = c.x - vw / 2
  const originY = c.y - vh / 2
  const worldTiles = Math.pow(2, zoom)

  const tiles: { key: string; src: string; left: number; top: number }[] = []
  const minTx = Math.floor(originX / TILE_SIZE)
  const maxTx = Math.floor((originX + vw) / TILE_SIZE)
  const minTy = Math.floor(originY / TILE_SIZE)
  const maxTy = Math.floor((originY + vh) / TILE_SIZE)
  for (let tx = minTx; tx <= maxTx; tx++) {
    for (let ty = minTy; ty <= maxTy; ty++) {
      if (ty < 0 || ty >= worldTiles) continue
      const wx = ((tx % worldTiles) + worldTiles) % worldTiles
      tiles.push({
        key: `${tx}_${ty}`, src: tileUrl(zoom, wx, ty),
        left: tx * TILE_SIZE - originX, top: ty * TILE_SIZE - originY,
      })
    }
  }

  const toScreen = (p: LatLng) => { const q = project(p.lat, p.lng, zoom); return { left: q.x - originX, top: q.y - originY } }

  const route = incLL && resLL ? routeProvider.calculateRoute(resLL, incLL) : null
  const responderStale = responder ? isStale(responder.timestamp, Date.now()) : true
  const announce = (() => {
    if (!responder) return 'Responder is assigned, but live location is not available yet.'
    const dist = route?.distance_m != null ? formatDistance(route.distance_m) : 'an unknown distance'
    if (responderStale) return `Responder location is temporarily unavailable. Last known distance about ${dist}.`
    return `Responder is approximately ${dist} away. ${freshnessLabel(responder.timestamp)}.`
  })()
  const incPos = incLL ? toScreen(incLL) : null
  const resPos = resLL ? toScreen(resLL) : null
  const unitPositions = unitList.map((u) => ({ u, pos: toScreen({ lat: u.lat, lng: u.lng }) }))

  return (
    <div>
      <div
        ref={wrapRef}
        style={{
          position: 'relative', width: '100%', height: vh, overflow: 'hidden',
          borderRadius: 12, border: '1px solid #e2e8f0', background: '#e5e7eb',
        }}
        role="img"
        aria-label={announce}
      >
        {fitPoints.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748b', fontSize: '0.85rem', textAlign: 'center', padding: 20, gap: 6 }}>
            {emptyMessage ? (
              <div>{emptyMessage}</div>
            ) : units !== undefined ? (
              networkTotalCount === 0 ? (
                <>
                  <div style={{ fontWeight: 700, color: '#334155' }}>No verified response units registered</div>
                  <div style={{ fontSize: '0.78rem' }}>No responder accounts exist on the network yet.</div>
                </>
              ) : (
                <>
                  <div style={{ fontWeight: 700, color: '#334155' }}>No fresh location fixes available</div>
                  <div style={{ fontSize: '0.78rem' }}>Response units exist, but none currently have a fresh GPS fix to plot on the map.</div>
                </>
              )
            ) : (
              <div>No incident location recorded.</div>
            )}
          </div>
        ) : (
          <>
            {tiles.map((t) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={t.key} src={t.src} alt="" aria-hidden="true" width={TILE_SIZE} height={TILE_SIZE}
                style={{ position: 'absolute', left: t.left, top: t.top, width: TILE_SIZE, height: TILE_SIZE, userSelect: 'none', pointerEvents: 'none' }} />
            ))}

            {/* Movement trail & straight-line connector between responder and incident. */}
            {(incPos && resPos) || (trail && trail.length > 0) ? (
              <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
                {/* Straight-line connector */}
                {incPos && resPos && (
                  <line x1={resPos.left} y1={resPos.top} x2={incPos.left} y2={incPos.top}
                    stroke={responderStale ? '#9ca3af' : '#2563eb'} strokeWidth={3} strokeDasharray="6 6" opacity={0.85} />
                )}
                {/* Client-side GPS movement trail dots (max 40 real GPS frames) */}
                {trail && trail.map((pt, idx) => {
                  const sp = toScreen(pt)
                  const isLatest = idx === trail.length - 1
                  return (
                    <circle
                      key={`trail-${idx}`}
                      cx={sp.left}
                      cy={sp.top}
                      r={isLatest ? 4 : 3}
                      fill={isLatest ? '#2563eb' : '#3b82f6'}
                      opacity={0.3 + (0.7 * (idx + 1) / trail.length)}
                    />
                  )
                })}
              </svg>
            ) : null}

            {/* Secondary ○ unit markers (eligible/visible — NOT assigned). Drawn
                beneath the 📍 incident and 🚔 responder so those stay prominent. */}
            {unitPositions.map(({ u, pos }) => {
              const selected = selectedUnitId != null && u.id === selectedUnitId
              const color = UNIT_KIND_COLORS[u.kind || 'eligible'] || UNIT_KIND_COLORS.eligible
              const d = selected ? 18 : 13
              return (
                <div
                  key={`unit-${u.id}`}
                  role={onUnitClick ? 'button' : undefined}
                  tabIndex={onUnitClick ? 0 : undefined}
                  aria-label={onUnitClick ? `${u.label || u.id} — eligible unit, view details` : undefined}
                  title={u.label || u.id}
                  onClick={onUnitClick ? () => onUnitClick(u.id) : undefined}
                  onKeyDown={onUnitClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onUnitClick(u.id) } } : undefined}
                  style={{
                    position: 'absolute', left: pos.left, top: pos.top,
                    transform: 'translate(-50%,-50%)', width: d, height: d,
                    borderRadius: '50%', background: '#fff', border: `3px solid ${color}`,
                    boxShadow: selected ? `0 0 0 3px ${color}55` : '0 1px 2px rgba(0,0,0,0.35)',
                    cursor: onUnitClick ? 'pointer' : 'default', zIndex: selected ? 5 : 3,
                  }}
                />
              )
            })}

            {incPos && (
              <div style={{ position: 'absolute', left: incPos.left, top: incPos.top, transform: 'translate(-50%,-100%)', fontSize: 26, filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.4))', zIndex: 6 }} title="Incident location" aria-hidden="true">📍</div>
            )}
            {resPos && (
              <div style={{ position: 'absolute', left: resPos.left, top: resPos.top, transform: 'translate(-50%,-50%)', fontSize: 24, opacity: responderStale ? 0.5 : 1, filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.4))', zIndex: 7 }} title="Responder" aria-hidden="true">🚔</div>
            )}

            <div style={{ position: 'absolute', right: 4, bottom: 2, fontSize: '0.55rem', color: '#334155', background: 'rgba(255,255,255,0.7)', padding: '0 4px', borderRadius: 4 }}>
              {MAP_ATTRIBUTION}
            </div>
          </>
        )}

        {/* Map view controls: Fit map, Follow responder, Fit all */}
        <div style={{ position: 'absolute', right: 8, top: 8, display: 'flex', gap: 6, zIndex: 10 }}>
          {showFollowButton && responder && (
            <button
              type="button"
              onClick={onFollow}
              style={{
                border: '1px solid #cbd5e1',
                background: 'rgba(255,255,255,0.95)', borderRadius: 8, padding: '3px 9px',
                fontSize: '0.68rem', fontWeight: 700, color: '#2563eb', cursor: 'pointer',
              }}
            >
              Follow responder
            </button>
          )}
          {onFitAll && incident && responder && (
            <button
              type="button"
              onClick={onFitAll}
              style={{
                border: '1px solid #cbd5e1',
                background: 'rgba(255,255,255,0.95)', borderRadius: 8, padding: '3px 9px',
                fontSize: '0.68rem', fontWeight: 700, color: '#334155', cursor: 'pointer',
              }}
            >
              Fit incident + responder
            </button>
          )}
          {showFitButton && fitPoints.length > 0 && (
            <button
              type="button"
              onClick={() => setLocalFit((n) => n + 1)}
              style={{
                border: '1px solid #cbd5e1',
                background: 'rgba(255,255,255,0.95)', borderRadius: 8, padding: '3px 9px',
                fontSize: '0.68rem', fontWeight: 700, color: '#334155', cursor: 'pointer',
              }}
            >
              Fit map
            </button>
          )}
        </div>

        {/* Connection status dot — truthful parent-supplied state when provided. */}
        <div style={{ position: 'absolute', left: 8, top: 8, display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(255,255,255,0.92)', borderRadius: 999, padding: '3px 9px', fontSize: '0.68rem', fontWeight: 700, color: '#334155', maxWidth: 'calc(100% - 16px)' }}>
          {connectionLabel ? (
            <>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: CONNECTION_TONE_COLORS[connectionTone] || '#9ca3af', display: 'inline-block', flexShrink: 0 }} />
              <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{connectionLabel}</span>
            </>
          ) : (
            <>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: connected ? '#22c55e' : '#eab308', display: 'inline-block' }} />
              {connected ? 'Live' : 'Connecting…'}
            </>
          )}
        </div>

        {/* Subtle legend. When units are present it names the ○ and states plainly
            that an eligible/visible unit is NOT an assigned one (P18). */}
        {showLegend && fitPoints.length > 0 && (
          <div style={{ position: 'absolute', left: 8, bottom: 6, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', background: 'rgba(255,255,255,0.9)', borderRadius: 8, padding: '3px 9px', fontSize: '0.62rem', fontWeight: 600, color: '#334155', maxWidth: 'calc(100% - 16px)' }}>
            <span aria-hidden="true">📍 Incident</span>
            <span aria-hidden="true">🚔 {unitList.length > 0 ? 'Assigned responder' : 'Responder'}</span>
            {unitList.length > 0 && (
              <>
                <span aria-hidden="true" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#fff', border: `3px solid ${UNIT_KIND_COLORS.eligible}`, display: 'inline-block' }} />
                  Eligible nearby unit
                </span>
                <span style={{ color: '#64748b', fontWeight: 500 }}>eligible ≠ assigned</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Truthful distance / ETA / freshness strip */}
      <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', fontSize: '0.78rem', color: '#334155' }}>
        {route?.distance_m != null && (
          <span><strong>Distance:</strong> {formatDistance(route.distance_m)} <span style={{ color: '#94a3b8' }}>(straight-line)</span></span>
        )}

        {/* Phase 6: Truthful ETA Presentation.
            - Before any provider accepts: DO NOT display "ETA: Route estimate unavailable".
              Instead show "Waiting for responder acceptance" or actual dispatch state.
            - After a provider accepts: show ETA only if a trusted routing provider returns one.
              Otherwise: "Route estimate unavailable". Never fabricate an ETA.
            - On coverage map (no incident): do not show ETA at all. */}
        {incident && (
          responderAccepted || responder ? (
            <span>
              <strong>ETA:</strong>{' '}
              {route?.eta_minutes != null ? `${route.eta_minutes} min` : 'Route estimate unavailable'}
            </span>
          ) : (
            <span style={{ color: '#8a5a00', fontWeight: 600 }}>
              {etaLabel || (dispatchStatus ? `Waiting for responder acceptance (${dispatchStatus})` : 'Waiting for responder acceptance')}
            </span>
          )
        )}

        {locationNote ? (
          <span style={{ color: '#334155', fontWeight: 600 }}>{locationNote}</span>
        ) : responder ? (
          <span style={{ color: responderStale ? '#b45309' : '#15803d', fontWeight: 600 }}>
            {responderStale ? 'Responder location temporarily unavailable' : freshnessLabel(responder.timestamp)}
          </span>
        ) : responderAccepted ? (
          <span style={{ color: '#8a5a00' }}>Responder assigned — waiting for first location update.</span>
        ) : incident ? (
          <span style={{ color: '#64748b' }}>No responder accepted yet.</span>
        ) : (
          <span style={{ color: '#64748b' }}>Network coverage view</span>
        )}
      </div>

      {caption && <div style={{ marginTop: 4, fontSize: '0.72rem', color: '#64748b' }}>{caption}</div>}

      {/* Screen-reader live region for critical state changes. */}
      <div aria-live="polite" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }}>
        {announce}
      </div>
    </div>
  )
}

