/**
 * Location freshness policy — behavioural regression tests.
 *
 * Imports the REAL policy module (src/lib/locationFreshness.ts) and asserts on its
 * outputs. Covers fresh, stale, missing, future and out-of-order fix timestamps, the
 * boundary at the 300s policy, and that stream state never upgrades a stale fix.
 *
 * Run: node test/locationFreshness.spec.mjs
 */
import {
  LOCATION_MAX_AGE_SECONDS,
  CLOCK_SKEW_TOLERANCE_SECONDS,
  fixAgeSeconds,
  classifyFix,
  mayShowAsCurrent,
  fixLabel,
  liveStatus,
} from '../src/lib/locationFreshness.ts'

let passed = 0
let failed = 0
function check(name, cond, detail = '') {
  if (cond) { passed++; console.log(`  PASS  ${name}`) }
  else { failed++; console.log(`  FAIL  ${name}${detail ? ' :: ' + detail : ''}`) }
}

const NOW = Date.parse('2026-10-10T12:00:00.000Z')
const iso = (ms) => new Date(ms).toISOString()

console.log('\n[1] policy constants')
check('policy is 300s (matches backend default)', LOCATION_MAX_AGE_SECONDS === 300)
check('skew tolerance is bounded (<= 60s)', CLOCK_SKEW_TOLERANCE_SECONDS > 0 && CLOCK_SKEW_TOLERANCE_SECONDS <= 60)

console.log('\n[2] fresh fix')
const freshAge = fixAgeSeconds(iso(NOW - 10_000), NOW)
check('10s-old fix age is 10', freshAge === 10, `got ${freshAge}`)
check('10s-old fix classifies FRESH', classifyFix(freshAge) === 'FRESH')
check('FRESH fix may be shown as current', mayShowAsCurrent(classifyFix(freshAge)))

console.log('\n[3] boundary at policy limit')
check('exactly 300s is still FRESH', classifyFix(300) === 'FRESH')
check('301s is STALE', classifyFix(301) === 'STALE')
check('STALE fix is NOT shown as current', !mayShowAsCurrent(classifyFix(301)))

console.log('\n[4] stale fix (old timestamp, stream may still be connected)')
const staleAge = fixAgeSeconds(iso(NOW - 3_600_000), NOW)
check('1h-old fix age is 3600', staleAge === 3600, `got ${staleAge}`)
check('1h-old fix classifies STALE', classifyFix(staleAge) === 'STALE')
check('stale fix never shown as current', !mayShowAsCurrent(classifyFix(staleAge)))

console.log('\n[5] missing / unparseable fix time is UNKNOWN, never fabricated')
check('null timestamp -> null age', fixAgeSeconds(null, NOW) === null)
check('undefined timestamp -> null age', fixAgeSeconds(undefined, NOW) === null)
check('empty string -> null age', fixAgeSeconds('', NOW) === null)
check('garbage string -> null age', fixAgeSeconds('not-a-date', NOW) === null)
check('null age classifies UNKNOWN', classifyFix(null) === 'UNKNOWN')
check('UNKNOWN is never shown as current', !mayShowAsCurrent(classifyFix(null)))
check('NaN age classifies UNKNOWN', classifyFix(Number.NaN) === 'UNKNOWN')

console.log('\n[6] future / out-of-order timestamps')
check('small future skew (5s) tolerated as age 0',
  fixAgeSeconds(iso(NOW + 5_000), NOW) === 0)
check('large future timestamp (1h) rejected as unknown',
  fixAgeSeconds(iso(NOW + 3_600_000), NOW) === null)
check('future-beyond-tolerance is UNKNOWN, not FRESH',
  classifyFix(fixAgeSeconds(iso(NOW + 3_600_000), NOW)) === 'UNKNOWN')
// Out-of-order: an OLDER fix arriving after a NEWER one must not be treated as current.
const newer = fixAgeSeconds(iso(NOW - 5_000), NOW)
const olderArrivingLate = fixAgeSeconds(iso(NOW - 900_000), NOW)
check('late-arriving older fix reports its own (stale) age',
  classifyFix(olderArrivingLate) === 'STALE' && classifyFix(newer) === 'FRESH')

console.log('\n[7] stream state never upgrades a stale fix')
check('CONNECTED + STALE -> orange, not green',
  liveStatus('CONNECTED', 'STALE').tone === 'orange')
check('CONNECTED + UNKNOWN -> not green',
  liveStatus('CONNECTED', 'UNKNOWN').tone !== 'green')
check('CONNECTED + FRESH -> green',
  liveStatus('CONNECTED', 'FRESH').tone === 'green')
check('RECONNECTING withholds position even if fix FRESH',
  liveStatus('RECONNECTING', 'FRESH').tone === 'yellow' &&
  /withheld/.test(liveStatus('RECONNECTING', 'FRESH').text))
check('DISCONNECTED is grey, never green',
  liveStatus('DISCONNECTED', 'FRESH').tone === 'grey')

console.log('\n[8] labels are truthful')
check('stale label says stale', /Stale/.test(fixLabel('STALE', 3600)))
check('unknown label says unknown', /unknown/i.test(fixLabel('UNKNOWN', null)))
check('fresh label shows age', fixLabel('FRESH', 12) === 'Fix 12s old')

console.log(`\nRESULTS: ${passed} passed, ${failed} failed, ${passed + failed} total`)
if (failed > 0) process.exitCode = 1
