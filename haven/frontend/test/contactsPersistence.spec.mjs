/**
 * Trusted-contacts add/delete regression test (issues: "contacts cannot be added"
 * and "contacts cannot be deleted").
 *
 * The old UI full-replaced the whole contact array on every change and deleted by
 * name, so a stale client could wipe or resurrect contacts, and a failed persist
 * could still look successful. The fix wires the page to atomic per-contact
 * endpoints and only reflects success after the server confirms it.
 *
 * No npm test runner is available (registry blocked), so this is a standalone
 * static harness that asserts the page source is wired to the correct, secure
 * contract. The full HTTP behaviour matrix lives in the backend suite
 * (test_voice_sos.py::TestPerContactAddDelete) and validate_contacts.py.
 *
 * Run:  node test/contactsPersistence.spec.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PAGE = readFileSync(join(__dirname, '..', 'src', 'app', 'voice-sos', 'page.tsx'), 'utf8')

let passed = 0, failed = 0
function check(name, cond) {
  if (cond) { passed++; console.log('PASS ' + name) }
  else { failed++; console.log('FAIL ' + name) }
}

// Isolate the two handlers so assertions can't accidentally match elsewhere.
const addFn = PAGE.slice(PAGE.indexOf('const handleAddContact'),
                         PAGE.indexOf('const handleDeleteContact'))
const delFn = PAGE.slice(PAGE.indexOf('const handleDeleteContact'),
                         PAGE.indexOf('const handleDeleteContact') + 1600)

// ── ADD ──────────────────────────────────────────────────────────────────────
check('add POSTs to the atomic /trusted-contacts/add endpoint',
      /secureFetch\('\/trusted-contacts\/add',\s*\{[\s\S]*?method:\s*'POST'/.test(addFn))
check('add does NOT send a client user_id/owner_id (identity is the token)',
      !/\b(user_id|owner_id)\s*:/.test(addFn))
check('add only claims success after res.ok',
      /if\s*\(res\.ok\)\s*\{[\s\S]*?Contact saved/.test(addFn))
check('add surfaces the real server error (data.detail) on failure',
      /data\.detail\s*\|\|\s*'Failed to save contact'/.test(addFn))
check('add adopts the authoritative server list (data.contacts) or refetches',
      /Array\.isArray\(data\.contacts\)\s*\)\s*setContacts\(data\.contacts\)/.test(addFn) &&
      /else\s+await\s+fetchContacts\(\)/.test(addFn))

// ── DELETE ─────────────────────────────────────────────────────────────────────
check('delete uses DELETE method against the per-contact endpoint',
      /secureFetch\(`\/trusted-contacts\/\$\{encodeURIComponent\(cid\)\}`,\s*\{[\s\S]*?method:\s*'DELETE'/.test(delFn))
check('delete keys off the stable contact_id',
      /const\s+cid\s*=\s*contact\?\.contact_id/.test(delFn))
check('delete adopts authoritative list or refetches on success',
      /if\s*\(res\.ok\)\s*\{[\s\S]*?Array\.isArray\(data\.contacts\)/.test(delFn))
check('delete resyncs from the server on failure (no silent optimistic removal)',
      /else\s*\{[\s\S]*?data\.detail\s*\|\|\s*'Failed to delete contact'[\s\S]*?await\s+fetchContacts\(\)/.test(delFn))

// ── WIRING ─────────────────────────────────────────────────────────────────────
check('delete button passes the whole contact object (not just the name)',
      /onClick=\{\(\)\s*=>\s*handleDeleteContact\(c\)\}/.test(PAGE))
check('TrustedContact carries a contact_id used for deletion',
      /contact_id\?:\s*string/.test(PAGE))
check('list is (re)hydrated from the server via fetchContacts -> /trusted-contacts/',
      /const\s+fetchContacts\s*=\s*async[\s\S]*?secureFetch\(`\/trusted-contacts\/\$\{userId\}`\)/.test(PAGE))

console.log(`\n==== ${passed} passed, ${failed} failed ====`)
process.exit(failed ? 1 : 0)
