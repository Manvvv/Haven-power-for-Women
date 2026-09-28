/**
 * Dashboard identity regression test (issue: "Welcome back, Manav" was hardcoded).
 *
 * The dashboard greeted every user with a literal `const firstName = 'Manav'`,
 * so it showed the developer's name to everyone. The fix derives the greeting
 * from the AUTHENTICATED Clerk identity via a pure helper:
 *   proper display name (fullName) -> first name -> safe localized fallback,
 * gated on `isLoaded` so a wrong name can never flash before hydration.
 *
 * No npm test runner is available (registry blocked), so this is a standalone
 * Node harness. Node strips the TypeScript types from greeting.ts on import, so
 * the REAL derivation code is exercised (not a reimplementation).
 *
 * Run:  node test/dashboardIdentity.spec.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { resolveGreetingName } from '../src/lib/greeting.ts'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PAGE = readFileSync(join(__dirname, '..', 'src', 'app', 'dashboard', 'page.tsx'), 'utf8')
const STRINGS = readFileSync(join(__dirname, '..', 'src', 'locales', 'strings.ts'), 'utf8')

let passed = 0, failed = 0
function check(name, cond) {
  if (cond) { passed++; console.log('PASS ' + name) }
  else { failed++; console.log('FAIL ' + name) }
}

// ── A) BEHAVIOURAL: the pure derivation honours the exact fallback chain ─────

// Tier 1: proper display name (fullName) wins.
check('fullName is preferred when present',
      resolveGreetingName({ fullName: 'Asha Verma', firstName: 'Asha' }, true, 'there') === 'Asha Verma')

// Tier 2: first name when no fullName.
check('firstName used when fullName is empty',
      resolveGreetingName({ fullName: '', firstName: 'Asha' }, true, 'there') === 'Asha')
check('firstName used when fullName is null',
      resolveGreetingName({ fullName: null, firstName: 'Asha' }, true, 'there') === 'Asha')

// Tier 3: safe fallback when neither is available.
check('fallback used when neither name is set',
      resolveGreetingName({ fullName: '', firstName: '' }, true, 'there') === 'there')
check('fallback used when both are null',
      resolveGreetingName({ fullName: null, firstName: null }, true, 'there') === 'there')

// Hydration: never show a name (wrong-name flash) until loaded.
check('not-loaded -> fallback even if a user object leaks through',
      resolveGreetingName({ fullName: 'Asha Verma', firstName: 'Asha' }, false, 'there') === 'there')
check('null user -> fallback',
      resolveGreetingName(null, true, 'there') === 'there')
check('undefined user -> fallback',
      resolveGreetingName(undefined, true, 'there') === 'there')

// The generic fallback is configurable/localizable (not hardcoded English).
check('localized fallback is respected',
      resolveGreetingName(null, true, 'dost') === 'dost')
check('default fallback is the safe generic "there"',
      resolveGreetingName(null, true) === 'there')

// Whitespace-only names are treated as absent (no "Hello,   🌸").
check('whitespace-only fullName falls through to firstName',
      resolveGreetingName({ fullName: '   ', firstName: 'Asha' }, true, 'there') === 'Asha')

// The hardcoded value must NEVER be produced by the helper for any input.
check('helper never returns the old hardcoded name',
      resolveGreetingName({ fullName: '', firstName: '' }, true, 'there') !== 'Manav')

// ── B) STATIC: the dashboard is wired to the authenticated identity ──────────

check('dashboard no longer contains the hardcoded name "Manav"',
      !/Manav/.test(PAGE))
check('dashboard no longer assigns a literal firstName',
      !/const\s+firstName\s*=\s*'[^']*'/.test(PAGE))
check('dashboard imports Clerk useUser',
      /import\s*\{[^}]*\buseUser\b[^}]*\}\s*from\s*'@clerk\/nextjs'/.test(PAGE))
check('dashboard reads user + isLoaded from useUser()',
      /const\s*\{\s*user\s*,\s*isLoaded\s*\}\s*=\s*useUser\(\)/.test(PAGE))
check('dashboard derives the name via resolveGreetingName',
      /resolveGreetingName\(\s*user\s*,\s*isLoaded\s*,/.test(PAGE))
check('dashboard imports the greeting helper',
      /import\s*\{\s*resolveGreetingName\s*\}\s*from\s*'@\/lib\/greeting'/.test(PAGE))
check('greeting renders the derived displayName (not a literal)',
      /\{t\('hello'\)\},\s*\{displayName\}/.test(PAGE))

// The localized generic fallback key exists (so the greeting is never blank).
check('friendFallback string key exists with first-class languages',
      /friendFallback:\s*\{[^}]*\ben:\s*'there'/.test(STRINGS) &&
      /friendFallback:\s*\{[^}]*\bhi:/.test(STRINGS) &&
      /friendFallback:\s*\{[^}]*\bhinglish:/.test(STRINGS))

console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
