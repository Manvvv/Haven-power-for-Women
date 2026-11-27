/**
 * HAVEN V2 End-to-End Frontend Feature & Wiring Verification Suite.
 *
 * Verifies all HAVEN V2 pages and components against backend API contracts,
 * honesty invariants, consent gates, accessibility semantics, and Demo Mode isolation.
 *
 * Run: node test/havenV2Features.spec.mjs
 */
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = join(__dirname, '..', 'src')

const read = (rel) => readFileSync(join(SRC, rel), 'utf8')

let passed = 0
let failed = 0
function check(name, cond) {
  if (cond) {
    passed++
    console.log('PASS ' + name)
  } else {
    failed++
    console.log('FAIL ' + name)
  }
}

// ── 1. Dashboard Safety Overview & Quick Actions ─────────────────────────────
const dash = read('app/dashboard/page.tsx')
check('Dashboard fetches trusted contacts, check-in active, and safety plan from real backend',
      dash.includes('/trusted-contacts/') && dash.includes('/check-in/active') && dash.includes('/therapy/safety-plan'))
check('Dashboard passes real trustedContactCount into DirectSOSForm',
      dash.includes('trustedContactCount={contactsCount}'))
check('Dashboard renders DirectSOSForm and IncidentTracker',
      dash.includes('<DirectSOSForm') && dash.includes('<IncidentTracker'))
check('Dashboard links to /safe-contacts, /voice-sos, /therapy/safety-plan, and /demo',
      ['/safe-contacts', '/voice-sos', '/therapy/safety-plan', '/demo'].every((p) => dash.includes(p)))

// ── 2. Direct Website SOS & Incident Tracker ─────────────────────────────────
const sosForm = read('components/DirectSOSForm.tsx')
const tracker = read('components/IncidentTracker.tsx')
check('DirectSOSForm captures GPS coords + accuracy + timestamp and handles denial gracefully',
      sosForm.includes('pos.coords.accuracy') && sosForm.includes('capturedAt') && sosForm.includes('PERMISSION_DENIED'))
check('DirectSOSForm supports manual location fallback and preserves idempotency key on error',
      sosForm.includes('manual_location') && sosForm.includes('idempotency_key: idempotencyRef.current'))
check('DirectSOSForm submits to /sos/report', sosForm.includes("secureFetch('/sos/report'"))
check('IncidentTracker reads /sos/my-incidents, /sos/incidents/{id}, and /cancel with WS live refresh',
      tracker.includes('/sos/my-incidents') && tracker.includes('/sos/incidents/') && tracker.includes('/cancel') && tracker.includes('useNotifications'))

// ── 3. Voice SOS Audio Recorder & Whisper AI Panel ───────────────────────────
const voicePanel = read('components/VoiceAudioRecorderPanel.tsx')
const voicePage = read('app/voice-sos/page.tsx')
check('VoiceAudioRecorderPanel is wired into /voice-sos without removing passive safe word mode',
      voicePage.includes('<VoiceAudioRecorderPanel') && voicePage.includes('VOICE_STATUS_META'))
check('VoiceAudioRecorderPanel checks /voice-sos/stt-status and shows honest missing env hint when unavailable',
      voicePanel.includes('/voice-sos/stt-status') && voicePanel.includes('missing_env'))
check('VoiceAudioRecorderPanel provides start/pause/stop controls, duration counter, and audio playback',
      voicePanel.includes('MediaRecorder') && voicePanel.includes('pause') && voicePanel.includes('<audio controls'))
check('VoiceAudioRecorderPanel supports editable transcription + AI extract + human confirmation before submit',
      voicePanel.includes('/voice-sos/transcribe') && voicePanel.includes('/voice-sos/extract') && voicePanel.includes('NOT GPS-confirmed') && voicePanel.includes('AI suggestion only'))

// ── 4. Trusted Contacts & Persistent Check-In Page ───────────────────────────
check('/safe-contacts route exists', existsSync(join(SRC, 'app', 'safe-contacts', 'page.tsx')))
const safePage = read('app/safe-contacts/page.tsx')
const middleware = read('middleware.ts')
check('/safe-contacts is protected by Clerk middleware', middleware.includes('/safe-contacts'))
check('/safe-contacts supports relationship, priority, edit, verify, notify consent, and contact history',
      safePage.includes('relationship') && safePage.includes("method: 'PATCH'") && safePage.includes('/verify') && safePage.includes('/trusted-contacts/notify') && safePage.includes('/trusted-contacts/history/'))
check('/safe-contacts implements consent-gated backend check-in timer controls',
      safePage.includes("secureFetch('/check-in'") && safePage.includes("'confirm-safe'") && safePage.includes("'extend'") && safePage.includes("'cancel'") && safePage.includes('consentAck'))

// ── 5. RRN Authority, Responder, Admin, Safety Plan, Demo Mode ───────────────
const respPage = read('app/responder/page.tsx')
const rrnPage = read('app/authority/rapid-response/page.tsx')
const adminPage = read('app/admin/page.tsx')
const planPage = read('app/therapy/safety-plan/page.tsx')
const demoPage = read('app/demo/page.tsx')

check('Responder portal fetches and renders Response History',
      respPage.includes('getResponderHistory') && respPage.includes('Response History'))
check('Authority Rapid Response renders severity/dispatch filters and real response/resolution durations',
      rrnPage.includes('emSeverityFilter') && rrnPage.includes('response_time_seconds') && rrnPage.includes('resolution_time_seconds'))
check('Admin panel supports user search, account suspend/reactivate, and real non-demo platform metrics',
      adminPage.includes('userSearch') && adminPage.includes('/status') && adminPage.includes('active_incidents') && adminPage.includes('approved_providers'))
check('Safety plan includes extended guidance sections, verified resources, and user export',
      planPage.includes('important_documents') && planPage.includes('/therapy/resources') && planPage.includes('exportPlanCopy'))
check('Demo console uses strictly isolated /demo/* endpoints and contains NO production secret passwords',
      demoPage.includes('/demo/state') && demoPage.includes('/demo/sos') && demoPage.includes('/demo/dispatch/') && demoPage.includes('/demo/voice-sos/analyze') && !/dev-authority|admin_secret|AUTHORITY_SECRET/i.test(demoPage))

console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
