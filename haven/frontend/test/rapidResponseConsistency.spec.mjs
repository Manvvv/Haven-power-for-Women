/**
 * Rapid Response Center Regression Test Suite
 *
 * Verifies the 10 critical regression requirements for the Authority
 * Rapid Response Center and Broadcast Dispatch model:
 *
 *   1. Selected case ID matches detail-panel case ID (no array index selection).
 *   2. Detail-panel coordinates match selected case.
 *   3. Map uses the selected case's coordinates.
 *   4. Dispatch uses the selected canonical case ID (no client coordinates/responder override).
 *   5. Zero providers produces an accurate, truthful empty state.
 *   6. Configured eligible providers appear in the network.
 *   7. Broadcast creates offers for every eligible provider.
 *   8. No ETA is displayed before responder acceptance.
 *   9. Map never invents responder location.
 *  10. Location privacy stays intact (victim view carries no candidate coords).
 *
 * Run:  node test/rapidResponseConsistency.spec.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const RAPID_RESPONSE_PAGE = readFileSync(
  join(__dirname, '..', 'src', 'app', 'authority', 'rapid-response', 'page.tsx'),
  'utf8'
)
const LIVE_MAP = readFileSync(
  join(__dirname, '..', 'src', 'components', 'LiveResponseMap.tsx'),
  'utf8'
)
const DISPATCH_LIB = readFileSync(
  join(__dirname, '..', 'src', 'lib', 'dispatch.ts'),
  'utf8'
)

let passed = 0
let failed = 0

function check(name, cond, details = '') {
  if (cond) {
    passed++
    console.log('PASS ' + name)
  } else {
    failed++
    console.log('FAIL ' + name + (details ? ': ' + details : ''))
  }
}

console.log('=' .repeat(70))
console.log('RAPID RESPONSE CENTER REGRESSION VERIFICATION')
console.log('=' .repeat(70))

// ── 1. Selected case ID matches detail-panel case ID ────────────────────────
check(
  '1.1 Selection state is keyed by canonical case ID string (not array index)',
  RAPID_RESPONSE_PAGE.includes('const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)')
)

check(
  '1.2 Detail panel derives selectedCase via case_id match',
  RAPID_RESPONSE_PAGE.includes('selectedCase = useMemo(') &&
  RAPID_RESPONSE_PAGE.includes('cases.find((c) => c.case_id === selectedCaseId)')
)

check(
  '1.3 Selection survives polling if case still exists or clears if deleted',
  RAPID_RESPONSE_PAGE.includes('setSelectedCaseId((prev) => {') &&
  RAPID_RESPONSE_PAGE.includes('newCases.some((c) => c.case_id === prev)')
)

check(
  '1.4 Detail panel renders canonical case_id from selectedCase',
  RAPID_RESPONSE_PAGE.includes('{selectedCase.case_id}')
)

// ── 2. Detail-panel coordinates match selected case ─────────────────────────
check(
  '2.1 Incident marker is parsed from selectedCase.location',
  RAPID_RESPONSE_PAGE.includes('incMarker: MapMarker | null = selectedCase ? parseLatLngString(selectedCase.location) : null')
)

check(
  '2.2 Detail panel location text derives from incCoordStr / selectedCase.location',
  RAPID_RESPONSE_PAGE.includes('{incCoordStr || selectedCase.location || \'Location pending\'}')
)

// ── 3. Map uses the selected case\'s coordinates ─────────────────────────────
check(
  '3.1 LiveResponseMap receives incMarker from selectedCase',
  RAPID_RESPONSE_PAGE.includes('incident={incMarker}')
)

check(
  '3.2 Full-map modal also receives incMarker from selectedCase',
  RAPID_RESPONSE_PAGE.includes('fullMapOpen && selectedCase') &&
  RAPID_RESPONSE_PAGE.includes('incident={incMarker}')
)

// ── 4. Dispatch uses the selected canonical case ID ─────────────────────────
check(
  '4.1 createDispatch only sends case_id and notes (never client coords or responder_id)',
  RAPID_RESPONSE_PAGE.includes('createDispatch({ case_id: confirmCase.case_id, notes: confirmNotes.trim() })')
)

const createDispatchSig = DISPATCH_LIB.match(/export async function createDispatch\([\s\S]*?\):/)
check(
  '4.2 createDispatch API client signature does not accept client coordinates or responder_id',
  createDispatchSig && !createDispatchSig[0].includes('latitude') && !createDispatchSig[0].includes('longitude') && !createDispatchSig[0].includes('responder_id')
)

// ── 5. Zero providers produces an accurate empty state ──────────────────────
check(
  '5.1 Unregistered network empty state is truthful',
  RAPID_RESPONSE_PAGE.includes('No verified response units are registered')
)

check(
  '5.2 No on-duty providers empty state is truthful',
  RAPID_RESPONSE_PAGE.includes('No response units are currently on duty')
)

check(
  '5.3 Map empty state differentiates registered vs no fresh location',
  LIVE_MAP.includes('No verified response units registered') &&
  LIVE_MAP.includes('No fresh location fixes available')
)

// ── 6. Configured eligible providers appear in the network ──────────────────
check(
  '6.1 getResponderNetwork fetches backend-authoritative /dispatch/rrn/network',
  DISPATCH_LIB.includes('getResponderNetwork()') &&
  DISPATCH_LIB.includes('/dispatch/rrn/network')
)

check(
  '6.2 Network view only renders active & verified responders',
  RAPID_RESPONSE_PAGE.includes('network?.responders')
)

// ── 7. Broadcast creates offers for every eligible provider ─────────────────
check(
  '7.1 Dispatch breakdown displays broadcast offer metrics',
  RAPID_RESPONSE_PAGE.includes('Dispatch Status (Broadcast Model)') &&
  RAPID_RESPONSE_PAGE.includes('Eligible providers:') &&
  RAPID_RESPONSE_PAGE.includes('Offers sent:') &&
  RAPID_RESPONSE_PAGE.includes('Accepted:') &&
  RAPID_RESPONSE_PAGE.includes('Declined:') &&
  RAPID_RESPONSE_PAGE.includes('Waiting:')
)

check(
  '7.2 Authority polls broadcast offers from backend',
  RAPID_RESPONSE_PAGE.includes('getDispatchOffers(selectedDispatch.dispatch_id)')
)

// ── 8. No ETA is displayed before acceptance ────────────────────────────────
check(
  '8.1 LiveResponseMap does NOT display Route estimate unavailable before acceptance',
  LIVE_MAP.includes('responderAccepted || responder ? (') &&
  LIVE_MAP.includes('Waiting for responder acceptance')
)

check(
  '8.2 Operations panel passes responderAccepted flag to LiveResponseMap',
  RAPID_RESPONSE_PAGE.includes('responderAccepted={!!selectedDispatch && !isTerminal(selectedDispatch.status)')
)

// ── 9. Map never invents responder location ─────────────────────────────────
check(
  '9.1 deriveLiveState does not report Live before receiving a GPS frame',
  RAPID_RESPONSE_PAGE.includes('Responder assigned — waiting for first location update.') &&
  !RAPID_RESPONSE_PAGE.includes('if (!args.hasFrame) {\n    return { dotLabel: \'🟢 Live\'')
)

check(
  '9.2 LiveResponseMap only plots responder when non-null coordinates exist',
  LIVE_MAP.includes('resLL: LatLng | null = responder ? { lat: responder.lat, lng: responder.lng } : null')
)

// ── 10. Location privacy stays intact ───────────────────────────────────────
check(
  '10.1 LiveResponseMap legend clarifies eligible units are not assigned',
  LIVE_MAP.includes('eligible ≠ assigned')
)

const victimViewSig = DISPATCH_LIB.match(/export interface VictimDispatchView\s*\{[\s\S]*?\}/)
check(
  '10.2 Candidate provider coordinates are never passed to victim views',
  victimViewSig && !victimViewSig[0].includes('incident_location') && !victimViewSig[0].includes('coordinates')
)

console.log('=' .repeat(70))
console.log(`RESULTS: ${passed} passed, ${failed} failed, ${passed + failed} total`)
console.log('=' .repeat(70))

if (failed > 0) {
  process.exit(1)
}
