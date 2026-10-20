/**
 * HAVEN map + routing abstraction (vendor-neutral).
 *
 * The app is NOT tightly coupled to one mapping/routing vendor. All map math and
 * route/ETA estimation go through the small interfaces here, so a different
 * provider can be swapped in via environment configuration without touching UI.
 *
 * Default provider: OpenStreetMap raster tiles. OSM standard tiles require NO API
 * key, so nothing secret is ever shipped to the browser. If a deployment wants a
 * keyed vendor, it sets the public tile URL template below — and any private
 * routing key stays SERVER-SIDE (this module never reads a secret key).
 *
 * Routing/ETA: the default RouteProvider is straight-line only. It returns a
 * labelled straight-line distance and ETA = null — HAVEN never fabricates an ETA.
 * A real routing adapter can implement RouteProvider server-side later.
 *
 * Env var NAMES (values never hardcoded here):
 *   NEXT_PUBLIC_MAP_TILE_URL   — raster XYZ tile template; defaults to OSM.
 *   NEXT_PUBLIC_MAP_ATTRIBUTION — attribution string; defaults to OSM.
 */

import { LOCATION_MAX_AGE_SECONDS, fixAgeSeconds, classifyFix } from './locationFreshness'

export const TILE_SIZE = 256

// Public OSM tile endpoint — no key required, safe for the browser.
const DEFAULT_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const DEFAULT_ATTRIBUTION = '© OpenStreetMap contributors'

export const MAP_TILE_URL: string =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_MAP_TILE_URL) || DEFAULT_TILE_URL
export const MAP_ATTRIBUTION: string =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_MAP_ATTRIBUTION) || DEFAULT_ATTRIBUTION

export interface LatLng { lat: number; lng: number }

export function tileUrl(z: number, x: number, y: number): string {
  return MAP_TILE_URL.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y))
}

// ─── Web Mercator projection (slippy-map standard) ──────────────────────────────
/** Global pixel coordinate of a lon/lat at a given zoom (origin top-left). */
export function project(lat: number, lng: number, zoom: number): { x: number; y: number } {
  const scale = TILE_SIZE * Math.pow(2, zoom)
  const x = ((lng + 180) / 360) * scale
  const sinLat = Math.sin((lat * Math.PI) / 180)
  const clamped = Math.max(-0.9999, Math.min(0.9999, sinLat))
  const y = (0.5 - Math.log((1 + clamped) / (1 - clamped)) / (4 * Math.PI)) * scale
  return { x, y }
}

// ─── Distance (haversine, metres) ───────────────────────────────────────────────
const EARTH_RADIUS_M = 6_371_000

export function haversineMeters(a: LatLng, b: LatLng): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const lat1 = toRad(a.lat)
  const lat2 = toRad(b.lat)
  const h =
    Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2)
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function formatDistance(meters: number | null | undefined): string {
  if (meters == null || !isFinite(meters)) return 'Distance unavailable'
  if (meters < 1000) return `${Math.round(meters)} m`
  return `${(meters / 1000).toFixed(1)} km`
}

// ─── Route / ETA abstraction ────────────────────────────────────────────────────
export interface RouteEstimate {
  distance_m: number | null
  /** ETA in minutes, or null when no routing provider is configured. Never faked. */
  eta_minutes: number | null
  /** 'straight_line' until a real routing adapter is wired in. */
  distance_type: 'straight_line' | 'route'
  /** Optional polyline for a real route; null for straight-line. */
  path: LatLng[] | null
}

export interface RouteProvider {
  readonly id: string
  calculateDistance(from: LatLng, to: LatLng): number | null
  /** Returns null unless a real routing provider is configured — ETA is never invented. */
  estimateEta(from: LatLng, to: LatLng): number | null
  calculateRoute(from: LatLng, to: LatLng): RouteEstimate
}

/**
 * Default provider: straight-line distance only, ETA always null, no network call.
 * This is the safe fallback the spec requires when no routing provider exists —
 * it is honest about being a straight-line estimate and never claims an ETA.
 */
export class StraightLineRouteProvider implements RouteProvider {
  readonly id = 'straight_line'
  calculateDistance(from: LatLng, to: LatLng): number | null {
    return haversineMeters(from, to)
  }
  estimateEta(): number | null {
    return null
  }
  calculateRoute(from: LatLng, to: LatLng): RouteEstimate {
    return {
      distance_m: this.calculateDistance(from, to),
      eta_minutes: null,
      distance_type: 'straight_line',
      path: null,
    }
  }
}

/** The active route provider. Swap here (or by env) when a real adapter is added. */
export const routeProvider: RouteProvider = new StraightLineRouteProvider()

/** External turn-by-turn hand-off (we never pretend HAVEN does navigation itself). */
export function externalNavUrl(dest: LatLng): string {
  return `https://www.openstreetmap.org/directions?to=${dest.lat}%2C${dest.lng}`
}

/** "Last updated 8 seconds ago"-style freshness label from an ISO timestamp. */
export function freshnessLabel(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'No location yet'
  const t = Date.parse(iso)
  if (isNaN(t)) return 'No location yet'
  const secs = Math.max(0, Math.round((now - t) / 1000))
  if (secs < 60) return `Last updated ${secs} second${secs === 1 ? '' : 's'} ago`
  const mins = Math.round(secs / 60)
  return `Last updated ${mins} minute${mins === 1 ? '' : 's'} ago`
}

/**
 * A location fix is stale beyond this many seconds. Delegated to the single shared
 * freshness policy (lib/locationFreshness.ts) so the map, the live panel and the
 * backend eligibility rule all use the same 300s limit.
 */
export const STALE_LOCATION_SECONDS = LOCATION_MAX_AGE_SECONDS

/**
 * True when the fix is NOT fresh under the shared policy: stale, missing,
 * unparseable, or timestamped too far in the future. Never fabricates a position.
 */
export function isStale(iso: string | null | undefined, now = Date.now()): boolean {
  return classifyFix(fixAgeSeconds(iso ?? null, now)) !== 'FRESH'
}
