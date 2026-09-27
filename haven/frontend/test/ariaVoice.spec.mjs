/**
 * Aria voice regression test (16-part voice audit, Parts 2/3/4/6/9/11/12/14).
 *
 * Two problems were reported in the therapy/Aria voice UI:
 *   (1) the speaker button did not reliably STOP speech, and
 *   (2) Aria spoke with a MALE-sounding voice.
 *
 * The fix keeps the existing provider (browser Web Speech API — no cloud TTS,
 * no secrets) and is presentation-only: it never touches Aria's wording or any
 * mental-health safety logic. This harness proves the two behaviours that were
 * broken, without a browser:
 *
 *   A) BEHAVIOURAL — the pure voice-selection module (voice.ts) deterministically
 *      prefers a warm FEMALE voice and never falls back to voices[0] while any
 *      usable voice exists; a MALE language-default must NOT win.
 *   B) STATIC — therapy/page.tsx wires the toggle to a real stop + generation
 *      token + single persisted key, reads live voice state (not a stale
 *      closure), guards in-flight TTS, exposes aria-pressed, and shows the
 *      Part-12 "voice unavailable" notice — with the safety imports intact.
 *
 * No npm test runner is available (registry blocked), so this is a standalone
 * Node harness. Node v22 strips the TypeScript types from voice.ts on import,
 * so the real selection code is exercised (not a reimplementation).
 *
 * Run:  node test/ariaVoice.spec.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { pickVoice, leadLangCode, FEMALE_VOICE, MALE_VOICE } from '../src/components/therapy/voice.ts'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PAGE = readFileSync(join(__dirname, '..', 'src', 'app', 'therapy', 'page.tsx'), 'utf8')
const VOICE = readFileSync(join(__dirname, '..', 'src', 'components', 'therapy', 'voice.ts'), 'utf8')

let passed = 0, failed = 0
function check(name, cond) {
  if (cond) { passed++; console.log('PASS ' + name) }
  else { failed++; console.log('FAIL ' + name) }
}
// Convenience: build a fake voice list (duck-typed; only name+lang are read).
const V = (name, lang) => ({ name, lang })

// ── A) BEHAVIOURAL: deterministic warm-FEMALE selection (Parts 6, 8, 9) ──────

// Realistic Windows list: a male default (David) listed first, plus female
// options. The fix must pick a female, never the male-first default.
const WINDOWS = [
  V('Microsoft David - English (United States)', 'en-US'),   // male, listed first
  V('Microsoft Zira - English (United States)', 'en-US'),    // female en-US
  V('Microsoft Heera - English (India)', 'en-IN'),           // female en-IN
  V('Microsoft Hemant - Hindi (India)', 'hi-IN'),            // male hi
  V('Microsoft Kalpana - Hindi (India)', 'hi-IN'),           // female hi
]
const enPick = pickVoice(WINDOWS, 'en')
check('en: does NOT pick the male-first default (David)', enPick.name !== WINDOWS[0].name)
check('en: picks a FEMALE voice', FEMALE_VOICE.test(enPick.name) && !MALE_VOICE.test(enPick.name))
// Deterministic: female en-IN (Heera) beats female en-US (Zira) even though Zira
// is listed FIRST in the OS array — the fix walks codes, not array order.
check('en: prefers female en-IN (Heera) over the earlier-listed female en-US (Zira)',
      enPick.name.includes('Heera') && enPick.lang === 'en-IN')

// Hinglish must resolve to a female English voice (Indian-English is the ideal).
const hiEnglishPick = pickVoice(WINDOWS, 'hinglish')
check('hinglish: picks a female English voice, not male',
      FEMALE_VOICE.test(hiEnglishPick.name) && !MALE_VOICE.test(hiEnglishPick.name) &&
      hiEnglishPick.lang.toLowerCase().startsWith('en'))
check('hinglish: also prefers female en-IN (Heera) deterministically',
      hiEnglishPick.name.includes('Heera') && hiEnglishPick.lang === 'en-IN')

// Hindi must resolve to a FEMALE Hindi voice (Kalpana), not the male Hemant.
const hiPick = pickVoice(WINDOWS, 'hi')
check('hi: picks female Hindi voice (Kalpana), not male Hemant',
      hiPick.name.includes('Kalpana') && !MALE_VOICE.test(hiPick.name))

// ── Deterministic English preference order: en-IN > en-US > en-GB > other en ──
// Build a female voice per English locale and shuffle so array order is WRONG;
// pickVoice must still honour the code priority regardless of ordering.
const fIN = V('Aditi Female - English (India)', 'en-IN')
const fUS = V('Samantha - English (United States)', 'en-US')
const fGB = V('Google UK English Female', 'en-GB')
const fAU = V('Karen - English (Australia)', 'en-AU')
const shuffled = [fAU, fGB, fUS, fIN]   // en-IN listed LAST on purpose
check('pref#1: female en-IN wins from a shuffled list', pickVoice(shuffled, 'en') === fIN)
check('pref#2: female en-US wins when no en-IN female', pickVoice([fAU, fGB, fUS], 'en') === fUS)
check('pref#3: female en-GB wins when no en-IN/en-US female', pickVoice([fAU, fGB], 'en') === fGB)
check('pref#4: other female English (en-AU) wins when it is the only English female',
      pickVoice([fAU], 'en') === fAU)
check('same deterministic order applies to Hinglish', pickVoice(shuffled, 'hinglish') === fIN)

// pref#5: no English female at all -> any clearly-female language-compatible voice.
const noEnFemale = [
  V('Microsoft David - English (United States)', 'en-US'),  // male en
  V('Microsoft Kalpana - Hindi (India)', 'hi-IN'),          // female, non-English
]
const p5 = pickVoice(noEnFemale, 'en')
check('pref#5: falls to any female (Kalpana) when no English female exists',
      p5.name.includes('Kalpana') && !MALE_VOICE.test(p5.name))

// pref#6: no female anywhere -> existing safe fallback still avoids male if it can,
// and never crashes (already covered by the all-male case below too).
const onlyMaleEn = [V('Microsoft Mark', 'en-US'), V('Microsoft David', 'en-US')]
check('pref#6: all-male list returns a usable voice (safe fallback, no crash)',
      pickVoice(onlyMaleEn, 'en') != null)

// The core root cause: a MALE language-default must never win over a female.
// List where the ONLY in-language voice is male, but a female English exists.
const MALE_DEFAULT = [
  V('Microsoft Ravi - English (India)', 'en-IN'),   // male, and the en-IN "default"
  V('Google UK English Female', 'en-GB'),           // female
]
const md = pickVoice(MALE_DEFAULT, 'hinglish')
check('male en-IN default does NOT beat a female English voice',
      !MALE_VOICE.test(md.name) && FEMALE_VOICE.test(md.name))

// Never returns a MALE_VOICE name when ANY female exists, across languages.
for (const lang of ['en', 'hi', 'hinglish', 'gu', 'mr', 'te', 'bn', 'ta']) {
  const p = pickVoice(WINDOWS, lang)
  check(`${lang}: never returns a male voice while a female exists`, !MALE_VOICE.test(p.name))
}

// Graceful fallbacks: empty list -> null (no crash); all-male -> still returns
// SOMETHING (last-resort) rather than throwing.
check('empty voice list returns null (no crash)', pickVoice([], 'en') === null)
check('null voice list returns null (no crash)', pickVoice(null, 'en') === null)
const ALL_MALE = [V('Microsoft David', 'en-US'), V('Microsoft Mark', 'en-US')]
check('all-male list still returns a usable voice (last resort)', pickVoice(ALL_MALE, 'en') != null)

// Unknown language falls through to the en map (Hinglish-friendly), never crashes.
check('unknown lang falls back to en map without crashing',
      pickVoice(WINDOWS, 'zz') != null)

// leadLangCode: the utterance fallback lang is Indian-English for en/hinglish.
check('leadLangCode(en) === en-IN', leadLangCode('en') === 'en-IN')
check('leadLangCode(hinglish) === en-IN (Hinglish -> Indian English)', leadLangCode('hinglish') === 'en-IN')
check('leadLangCode(hi) === hi-IN', leadLangCode('hi') === 'hi-IN')
check('leadLangCode(unknown) falls back to en-IN', leadLangCode('zz') === 'en-IN')

// ── B) STATIC: therapy/page.tsx wires the toggle + async races correctly ─────

// Part 5/6: uses the centralized voice module, not an inline voices[0] pick.
check('page imports pickVoice + leadLangCode from the voice module',
      /import\s*\{\s*pickVoice\s*,\s*leadLangCode\s*\}\s*from\s*'@\/components\/therapy\/voice'/.test(PAGE))

// Part 2: generation token + live-state ref exist.
check('has generation token ref (speechGenRef)', /const\s+speechGenRef\s*=\s*useRef\(0\)/.test(PAGE))
check('has live voice-state ref (voiceOnRef)', /const\s+voiceOnRef\s*=\s*useRef\(/.test(PAGE))

// Part 2: stopSpeaking bumps the generation AND cancels the engine.
const stopBlock = PAGE.slice(PAGE.indexOf('const stopSpeaking'), PAGE.indexOf('const stopSpeaking') + 260)
check('stopSpeaking increments the generation token', /speechGenRef\.current\s*\+=\s*1/.test(stopBlock))
check('stopSpeaking cancels the speech engine', /synthRef\.current\?\.cancel\(\)/.test(stopBlock))

// Part 3: the toggle turns OFF -> immediate stop (not deferred to next render).
const toggle = PAGE.slice(PAGE.indexOf('aria-pressed={voiceOn}'), PAGE.indexOf('aria-pressed={voiceOn}') + 400)
check('toggle exposes aria-pressed={voiceOn}', /aria-pressed=\{voiceOn\}/.test(PAGE))
check('toggle calls stopSpeaking() when turning OFF', /if\s*\(!next\)\s*stopSpeaking\(\)/.test(toggle))
check('toggle uses accessible on/off labels', /toggleVoiceOff/.test(toggle) && /toggleVoiceOn/.test(toggle))

// Part 2 (stale closure): speak() reads the LIVE ref, not the captured voiceOn.
const speakBlock = PAGE.slice(PAGE.indexOf('const speak'), PAGE.indexOf('synthRef.current.speak(utter)') + 40)
check('speak() reads voiceOnRef.current (live), not the voiceOn closure',
      /if\s*\(!voiceOnRef\.current\)/.test(speakBlock))
check('speak() cancels any prior utterance before speaking', /synthRef\.current\.cancel\(\)/.test(speakBlock))
check('speak() stamps this utterance with a generation (++speechGenRef.current)',
      /\+\+speechGenRef\.current/.test(speakBlock))
check('speak() guards onstart/onend against a stale generation',
      /gen\s*===\s*speechGenRef\.current/.test(speakBlock))
check('speak() uses pickVoice + leadLangCode', /pickVoice\(/.test(speakBlock) && /leadLangCode\(/.test(speakBlock))

// Part 2: an in-flight TTS request must NOT play if voice went OFF (or a newer
// generation started) while the network reply was pending.
check('sendMessage captures the generation before fetch (genAtSend)',
      /const\s+genAtSend\s*=\s*speechGenRef\.current/.test(PAGE))
check('sendMessage only speaks if still enabled AND same generation',
      /voiceOnRef\.current\s*&&\s*genAtSend\s*===\s*speechGenRef\.current/.test(PAGE))

// Part 4: exactly ONE namespaced persistence key, both read and written.
const keyHits = [...PAGE.matchAll(/'haven_aria_voice_enabled'/g)].length
check('reads the persisted key', /getItem\('haven_aria_voice_enabled'\)/.test(PAGE))
check('writes the persisted key', /setItem\('haven_aria_voice_enabled'/.test(PAGE))
check('uses a SINGLE localStorage key (no competing keys)',
      keyHits >= 2 && !/getItem\('(?!haven_aria_voice_enabled)[^']*voice[^']*'\)/i.test(PAGE))
check('persistence is wrapped in try/catch (private-mode/SSR safe)',
      /try\s*\{\s*[^]*?getItem\('haven_aria_voice_enabled'\)[^]*?\}\s*catch/.test(PAGE))

// Part 9: switching language must not reset voiceOn (no setVoiceOn in a lang effect).
check('changing language never resets voiceOn',
      !/lang[^]{0,120}setVoiceOn/.test(PAGE))

// Part 11: unmount cleanup cancels speech + clears the mount flag.
const initCleanup = PAGE.slice(PAGE.indexOf('isMountedRef.current = false'), PAGE.indexOf('isMountedRef.current = false') + 160)
check('unmount cleanup cancels the speech engine', /synthRef\.current\.cancel\(\)/.test(initCleanup))

// Part 6: waits for voices to load (getVoices() can be empty initially).
check('subscribes to voiceschanged so late voices are used', /onvoiceschanged\s*=/.test(PAGE))

// Part 12: non-blocking "voice unavailable" notice, driven by i18n (not hardcoded).
check('renders the voiceUnavailable notice', /voiceUnavailable\s*&&/.test(PAGE))
check('notice text comes from i18n', /tn\('mental_health',\s*'voiceUnavailable'\)/.test(PAGE))
check('notice is a polite live region (aria-live)', /aria-live="polite"/.test(PAGE))

// Part 13: safety architecture untouched — the safety panels/support imports
// must still be present (a crude but real guard that voice work didn't strip them).
check('safety panels still imported (safety logic untouched)',
      /CrisisPanel/.test(PAGE) && /CalmDownPanel/.test(PAGE) && /GetHelpPanel/.test(PAGE))

// ── C) STATIC: voice.ts preference order + the female/male regex boundaries ──

// The selection must walk cfg.codes IN ORDER for the female tier (so en-IN beats
// en-US beats en-GB deterministically), keep gender (female, not-male) ahead of
// a bare language match, and use voices[0] only as the very last resort.
const loopStart = VOICE.indexOf('for (const code of cfg.codes)')
check('pickVoice walks cfg.codes in priority order for the female tier',
      loopStart !== -1)
const loopBody = VOICE.slice(loopStart, loopStart + 200)
check('the per-code tier requires female + not-male (name filter preserved)',
      /startsWith\(v,\s*code\)\s*&&\s*female\(v\)\s*&&\s*!male\(v\)/.test(loopBody))

const retStart = VOICE.indexOf('return (')
const v0 = VOICE.lastIndexOf('voices[0]')   // the REAL last-resort, not a comment mention
const returnBlock = VOICE.slice(retStart, v0 + 'voices[0]'.length)
// The code-priority loop must run BEFORE the return-chain fallback.
check('per-code priority loop runs before the fallback return chain',
      loopStart < retStart)
check('pickVoice uses bare voices[0] only as the LAST fallback',
      returnBlock.trimEnd().endsWith('voices[0]'))
check('female filter precedes the plain in-language fallback',
      returnBlock.indexOf('female(v)') < returnBlock.indexOf('voices.find(v => inLang(v))'))
// Guard: no hardcoded browser-specific voice INDEX (only voices[0] as last resort).
check('no hardcoded browser-specific voice index (e.g. voices[1], voices[2])',
      !/voices\[\s*[1-9]\d*\s*\]/.test(VOICE))


// The word-boundary trick: "male" inside "female" must NOT flag a female voice.
check('MALE_VOICE does not match "…Female" voices',
      MALE_VOICE.test('Google UK English Female') === false &&
      MALE_VOICE.test('Microsoft Zira Female') === false)
check('MALE_VOICE still flags real male names', MALE_VOICE.test('Microsoft David') && MALE_VOICE.test('Microsoft Ravi'))
check('FEMALE_VOICE flags the common Indian/female voices',
      FEMALE_VOICE.test('Microsoft Heera') && FEMALE_VOICE.test('Microsoft Zira') &&
      FEMALE_VOICE.test('Microsoft Kalpana'))

// Utterance is tuned warm/gentle (rate/pitch), per Part 8 — presentation only.
check('utterance is tuned warm (rate < 1, pitch > 1)',
      /utter\.rate\s*=\s*0\.9\d?/.test(PAGE) && /utter\.pitch\s*=\s*1\.[1-9]/.test(PAGE))


console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
