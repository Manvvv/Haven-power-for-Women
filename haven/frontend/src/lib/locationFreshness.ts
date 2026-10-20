/**
 * Responder location freshness policy (single source of truth on the client).
 *
 * POLICY (must match the backend, backend/services/dispatch_service.py
 * RESPONDER_LOCATION_MAX_AGE_SECONDS, default 300s):
 *
 *   - A responder's GPS FIX is FRESH while its age (now - fix timestamp) is
 *     <= LOCATION_MAX_AGE_SECONDS. Only fresh fixes are eligible for dispatch and
 *     may be plotted as a current position.
 *   - A fix older than that is STALE: it is never shown as the current position.
 *   - A missing or unparseable fix time is UNKNOWN and is treated as NOT fresh.
 *   - A FUTURE timestamp (clock skew or out-of-order delivery) is never trusted as
 *     "fresher than now": it is clamped to age 0 only within a small skew allowance,
 *     otherwise it is UNKNOWN.
 *
 * STREAM STATE is separate from fix age. The live socket is CONNECTED,
 * RECONNECTING or DISCONNECTED; a quiet stream does not by itself make a fix stale,
 * and a fresh fix does not prove the stream is up.
 *
 * Pure functions only (no React, no DOM) so they are unit-testable in Node.
 */

/** Must equal the backend default RESPONDER_LOCATION_MAX_AGE_SECONDS (300). */
export const LOCATION_MAX_AGE_SECONDS = 300

/** Tolerated forward clock skew between device and server, in seconds. */
export const CLOCK_SKEW_TOLERANCE_SECONDS = 30

export type FixState = 'FRESH' | 'STALE' | 'UNKNOWN'

export type StreamState = 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'

/**
 * Age in whole seconds of a fix taken at `fixTimestamp`, relative to `nowMs`.
 * Returns null when the timestamp is missing or unparseable, or when it lies in the
 * future beyond the skew tolerance (never fabricate an age).
 */
export function fixAgeSeconds(fixTimestamp: string | number | null | undefined, nowMs: number): number | null {
  if (fixTimestamp === null || fixTimestamp === undefined || fixTimestamp === '') return null
  const fixMs = typeof fixTimestamp === 'number' ? fixTimestamp : Date.parse(fixTimestamp)
  if (!Number.isFinite(fixMs) || !Number.isFinite(nowMs)) return null
  const deltaSec = (nowMs - fixMs) / 1000
  if (deltaSec < -CLOCK_SKEW_TOLERANCE_SECONDS) return null // future beyond tolerance
  return Math.max(0, Math.round(deltaSec))
}

/** Classify a fix by its age. UNKNOWN when there is no usable age. */
export function classifyFix(ageSeconds: number | null | undefined): FixState {
  if (ageSeconds === null || ageSeconds === undefined || !Number.isFinite(ageSeconds)) return 'UNKNOWN'
  return ageSeconds <= LOCATION_MAX_AGE_SECONDS ? 'FRESH' : 'STALE'
}

/**
 * Whether a coordinate may be shown as the CURRENT responder position.
 * Only a FRESH fix qualifies. Stale or unknown fixes must be withheld.
 */
export function mayShowAsCurrent(fix: FixState): boolean {
  return fix === 'FRESH'
}

/** Human label for a fix state (never claims "live" for a stale/unknown fix). */
export function fixLabel(fix: FixState, ageSeconds: number | null): string {
  if (fix === 'FRESH') return ageSeconds === null ? 'Fresh fix' : `Fix ${ageSeconds}s old`
  if (fix === 'STALE') return ageSeconds === null ? 'Stale fix' : `Stale fix (${ageSeconds}s old)`
  return 'Fix time unknown'
}

/**
 * Combined live-panel status. Stream state and fix state are reported separately,
 * so the panel can say exactly what is known.
 */
export function liveStatus(stream: StreamState, fix: FixState): { tone: 'green' | 'yellow' | 'orange' | 'grey'; text: string } {
  if (stream === 'DISCONNECTED') return { tone: 'grey', text: 'Live connection unavailable' }
  if (stream === 'RECONNECTING') return { tone: 'yellow', text: 'Reconnecting — last known position withheld' }
  if (fix === 'FRESH') return { tone: 'green', text: 'Live — fresh responder location' }
  if (fix === 'STALE') return { tone: 'orange', text: 'Connected, but responder location is stale' }
  return { tone: 'yellow', text: 'Connected, waiting for a timestamped location' }
}
