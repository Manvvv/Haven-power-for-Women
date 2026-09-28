/**
 * Voice-SOS lifecycle regression test (reported issue: "Voice SOS is unreliable
 * / silently fails").
 *
 * The page ran a Web Speech recognition loop whose only visible states were
 * "Listening..." vs "Ready": a blocked mic, an unsupported browser, a
 * recognition error, an in-flight send, or a cooldown were all invisible, and
 * onerror only did `console.error` + maybe set denied — a silent failure.
 *
 * The fix extracts the lifecycle into a pure, framework-free module
 * (src/lib/voiceSosStatus.ts) so the single visible status can be unit-tested
 * without a browser, and wires the page to it. This harness has two layers:
 *
 *   A) BEHAVIOURAL — exercises the REAL deriveVoiceStatus / mapRecognitionError
 *      (Node v22 strips the TS types on import, so the shipped code runs).
 *   B) STATIC — proves page.tsx is wired to the helper, gates data fetches on a
 *      real authenticated identity, restarts only on recoverable errors, and
 *      never logs or renders the recognized transcript in an error path.
 *
 * No npm test runner is available (registry blocked), so this is a standalone
 * Node harness.  Run:  node test/voiceSosStatus.spec.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { deriveVoiceStatus, mapRecognitionError, VOICE_STATUS_META } from '../src/lib/voiceSosStatus.ts'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PAGE = readFileSync(join(__dirname, '..', 'src', 'app', 'voice-sos', 'page.tsx'), 'utf8')

let passed = 0, failed = 0
function check(name, cond) {
  if (cond) { passed++; console.log('PASS ' + name) }
  else { failed++; console.log('FAIL ' + name) }
}

const base = { isSupported: true, micPermission: 'granted', triggerPhase: 'idle', isListening: false, hasError: false }

// ── A) BEHAVIOURAL: every state + precedence ─────────────────────────────────
check('unsupported when no SpeechRecognition API',
      deriveVoiceStatus({ ...base, isSupported: false }) === 'unsupported')
check('processing while an SOS send is in flight',
      deriveVoiceStatus({ ...base, triggerPhase: 'processing', isListening: true }) === 'processing')
check('triggered right after a successful send',
      deriveVoiceStatus({ ...base, triggerPhase: 'sent' }) === 'triggered')
check('cooldown after send settles',
      deriveVoiceStatus({ ...base, triggerPhase: 'cooldown' }) === 'cooldown')
check('permission_denied when mic is blocked',
      deriveVoiceStatus({ ...base, micPermission: 'denied' }) === 'permission_denied')
check('failed when a surfaced recognition error is outstanding',
      deriveVoiceStatus({ ...base, hasError: true }) === 'failed')
check('listening when the loop is active and nothing is wrong',
      deriveVoiceStatus({ ...base, isListening: true }) === 'listening')
check('idle by default', deriveVoiceStatus({ ...base }) === 'idle')

// precedence: the more urgent / blocking signal must win
check('unsupported beats an active send', deriveVoiceStatus({ ...base, isSupported: false, triggerPhase: 'processing' }) === 'unsupported')
check('in-flight send beats a blocked mic', deriveVoiceStatus({ ...base, triggerPhase: 'processing', micPermission: 'denied' }) === 'processing')
check('blocked mic beats a generic error', deriveVoiceStatus({ ...base, micPermission: 'denied', hasError: true }) === 'permission_denied')
check('a surfaced error beats quiet listening', deriveVoiceStatus({ ...base, hasError: true, isListening: true }) === 'failed')

// every derivable status has presentation metadata (label/tone/live)
const ALL = ['unsupported','processing','triggered','cooldown','permission_denied','failed','listening','idle']
check('VOICE_STATUS_META covers all 8 states with a non-empty label',
      ALL.every(s => VOICE_STATUS_META[s] && typeof VOICE_STATUS_META[s].label === 'string' && VOICE_STATUS_META[s].label.length > 0))
check('VOICE_STATUS_META tones are from the known set',
      ALL.every(s => ['danger','success','warning','info','muted'].includes(VOICE_STATUS_META[s].tone)))
check('active states (processing/triggered/listening) are marked live for a11y',
      VOICE_STATUS_META.processing.live && VOICE_STATUS_META.triggered.live && VOICE_STATUS_META.listening.live)

// ── mapRecognitionError: classified, never swallowed, never a transcript ─────
const TRANSCRIPT = 'help me please secret safe word'
check('not-allowed → permission denied + fatal', (() => { const i = mapRecognitionError('not-allowed'); return i.permissionDenied && i.fatal && !i.benign })())
check('service-not-allowed → permission denied + fatal', (() => { const i = mapRecognitionError('service-not-allowed'); return i.permissionDenied && i.fatal })())
check('no-speech is benign (normal pause, not an alarm)', (() => { const i = mapRecognitionError('no-speech'); return i.benign && !i.fatal && !i.permissionDenied })())
check('aborted is benign', mapRecognitionError('aborted').benign === true)
check('audio-capture → fatal, no mic found (stops retry loop)', (() => { const i = mapRecognitionError('audio-capture'); return i.fatal && !i.permissionDenied && !i.benign })())
check('network error is recoverable (not fatal, not benign)', (() => { const i = mapRecognitionError('network'); return !i.fatal && !i.benign && !i.permissionDenied })())
check('unknown/empty code still yields a shown (non-benign) message', (() => { const i = mapRecognitionError(''); return !i.benign && typeof i.message === 'string' && i.message.length > 0 })())
check('every mapped message is a non-empty string',
      ['not-allowed','service-not-allowed','no-speech','aborted','audio-capture','network','','weird-XYZ'].every(c => typeof mapRecognitionError(c).message === 'string' && mapRecognitionError(c).message.length > 0))
check('NO recognition message ever embeds the transcript',
      ['not-allowed','service-not-allowed','no-speech','aborted','audio-capture','network','','weird-XYZ'].every(c => !mapRecognitionError(c).message.includes(TRANSCRIPT)))

// ── B) STATIC: the page is wired to the helper and stays honest/private ───────
check('page imports the pure lifecycle helper',
      /import\s*\{[\s\S]*deriveVoiceStatus[\s\S]*mapRecognitionError[\s\S]*VOICE_STATUS_META[\s\S]*\}\s*from\s*'@\/lib\/voiceSosStatus'/.test(PAGE))
check('render derives ONE status from the live signals',
      /deriveVoiceStatus\(\{[\s\S]*isSupported[\s\S]*micPermission[\s\S]*triggerPhase[\s\S]*isListening[\s\S]*hasError:\s*!!recognitionError/.test(PAGE))
check('status label is driven by VOICE_STATUS_META (not a hardcoded string)',
      /voiceStatusMeta\.label/.test(PAGE))

// onerror path: classify via mapRecognitionError, never log the transcript
const onErr = PAGE.slice(PAGE.indexOf('recognition.onerror'), PAGE.indexOf('recognition.onend'))
// Strip // comments so we assert on real CODE, not explanatory prose.
// (source uses CRLF, so match to end-of-line without the $ anchor).
const onErrCode = onErr.split('\n').map(l => l.replace(/\/\/.*/, '')).join('\n')
check('onerror classifies via mapRecognitionError', /mapRecognitionError\(/.test(onErrCode))
check('onerror surfaces non-benign errors to the user', /setRecognitionError\(info\.message\)/.test(onErrCode))
check('onerror only logs the error CODE, never the transcript',
      !/transcript/i.test(onErrCode) && /event\?\.error/.test(onErrCode))

// onend: recoverable-only auto-restart (a fatal error must stop the loop)
const onEnd = PAGE.slice(PAGE.indexOf('recognition.onend'), PAGE.indexOf('recognition.onend') + 600)
check('onend auto-restart is gated on !recognitionFatalRef (no infinite retry on a blocked mic)',
      /!recognitionFatalRef\.current/.test(onEnd))

// triggerSOS: visible processing → sent, with duplicate-trigger guard intact
check('triggerSOS shows a visible "processing" state before sending',
      /setTriggerPhase\('processing'\)/.test(PAGE))
check('triggerSOS marks "sent" on a confirmed success',
      /setTriggerPhase\('sent'\)/.test(PAGE))
check('duplicate triggers are still blocked via isTriggeringRef',
      /if\s*\(isTriggeringRef\.current\)\s*return/.test(PAGE))

// identity: user-scoped fetches only after Clerk load; no global placeholder id
check('userId comes from the authenticated Clerk user, gated on isLoaded',
      /const\s+userId\s*=\s*isLoaded\s*\?\s*\(user\?\.id\s*\|\|\s*''\)\s*:\s*''/.test(PAGE))
check('no hardcoded "haven_user" placeholder identity remains',
      !/'haven_user'/.test(PAGE))
check('user-scoped data fetches wait for isLoaded && userId',
      /if\s*\(isLoaded\s*&&\s*userId\)\s*\{[\s\S]*fetchConfig\(\)[\s\S]*fetchContacts\(\)/.test(PAGE))

// stop/cleanup: a true stop (abort + handler-null) so nothing lingers or restarts
check('stopListening detaches handlers and aborts (true stop, no lingering restart)',
      /recognitionRef\.current\.onend\s*=\s*null[\s\S]*abort\(\)/.test(PAGE))

console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
