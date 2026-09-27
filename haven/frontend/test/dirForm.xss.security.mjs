/**
 * P2-4 regression test: DIR Form-1 print output escapes untrusted content.
 *
 * The authority dashboard's printDIRForm() builds an HTML document via
 * document.write() from DIR data whose fields are AI-generated
 * (dir_report_text = call_groq(...)) and user/case-derived (summary, location,
 * nature_of_abuse, ...). Per the audit, AI output must be treated as untrusted.
 * A crafted case/AI report containing <script> or an onerror attribute must NOT
 * execute in the same-origin print window.
 *
 * No npm test runner is available (registry blocked), so this is a standalone
 * Node harness. It (1) statically verifies every dynamic ${...} interpolation
 * inside the document.write template is escaped, and (2) behaviourally verifies
 * the esc() helper neutralises the classic XSS vectors.
 *
 * Run:  node test/dirForm.xss.security.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = join(__dirname, '..', 'src', 'app', 'authority', 'page.tsx')
const code = readFileSync(SRC, 'utf8')

let passed = 0, failed = 0
function check(name, cond) {
  if (cond) { passed++; console.log('PASS ' + name) }
  else { failed++; console.log('FAIL ' + name) }
}

// ── 1) esc() helper is present with all five HTML-significant replacements ──
const escDef = code.slice(code.indexOf('const esc ='), code.indexOf('const d = dirFormData'))
for (const [label, needle] of [
  ['& -> &amp;', "replace(/&/g, '&amp;')"],
  ['< -> &lt;', "replace(/</g, '&lt;')"],
  ['> -> &gt;', "replace(/>/g, '&gt;')"],
  ['" -> &quot;', "replace(/\"/g, '&quot;')"],
  ["' -> &#39;", "replace(/'/g, '&#39;')"],
]) check('esc() escapes ' + label, escDef.includes(needle))

// ── 2) every dynamic ${...} in the document.write template is escaped ──
const dwStart = code.indexOf('printWindow.document.write(`')
const tplStart = code.indexOf('`', dwStart)
const tplEnd = code.indexOf('`', tplStart + 1)
const template = code.slice(tplStart + 1, tplEnd)
assert.ok(template.includes('DIR Form-1'), 'located the print template')

// Interpolations that are safe WITHOUT esc(): pre-escaped vars + static ternaries.
const SAFE_EXPR = [
  'needs',                       // built above: (d.needs||[]).map(esc).join(', ')
  'legal',                       // built above: badges wrapping esc(s)
  'relief',                      // built above: badges wrapping esc(s)
  "d.immediate_danger ?",        // static literal strings on both branches
  "d.has_forensic_evidence ?",   // static literal strings on both branches
  "d.evidence_hash ?",           // ternary whose truthy branch calls esc(d.evidence_hash)
]
const interp = [...template.matchAll(/\$\{([^}]*)\}/g)].map(m => m[1].trim())
check('template has multiple interpolations', interp.length >= 10)
let unescaped = []
for (const expr of interp) {
  const isEsc = expr.startsWith('esc(')
  const isSafe = SAFE_EXPR.some(s => expr.startsWith(s))
  if (!isEsc && !isSafe) unescaped.push(expr)
}
check('no unescaped dynamic interpolation in print template (' +
      (unescaped.length ? unescaped.join(' | ') : 'none') + ')', unescaped.length === 0)

// The three pre-built vars must themselves escape their items.
check('needs list escapes each item', /needs\s*=\s*\(d\.needs[^\n]*\.map\(esc\)/.test(code))
check('legal badges escape each item', /legal\s*=[\s\S]{0,160}esc\(s\)/.test(code))
check('relief badges escape each item', /relief\s*=[\s\S]{0,160}esc\(r\)/.test(code))

// ── 3) behavioural: esc() neutralises the classic vectors ──
const esc = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
check('esc neutralises <script>', esc('<script>alert(1)</script>') === '&lt;script&gt;alert(1)&lt;/script&gt;')
check('esc neutralises img onerror', !esc('<img src=x onerror=alert(1)>').includes('<'))
check('esc neutralises attribute breakout', !esc('" onmouseover="alert(1)').includes('"'))
check('esc handles null/undefined', esc(null) === '' && esc(undefined) === '')

console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
