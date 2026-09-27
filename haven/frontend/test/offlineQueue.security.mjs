/**
 * Self-contained security + behaviour test for the offline SOS queue (P1-6).
 *
 * There is no npm-based test runner available in this environment (registry
 * blocked), so this is a standalone Node harness. It:
 *   1. transpiles src/lib/offlineQueue.ts with the locally-installed `typescript`
 *      compiler (no network),
 *   2. provides a minimal in-memory IndexedDB shim + Node's WebCrypto + btoa/atob,
 *   3. exercises the public API and asserts security + correctness properties.
 *
 * Run:  node test/offlineQueue.security.mjs
 */
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import ts from 'typescript'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = join(__dirname, '..', 'src', 'lib', 'offlineQueue.ts')

// ── Minimal synchronous-ish IndexedDB shim ──────────────────────────
// Enough of the surface the module uses: open/upgrade, objectStore, add/put/get/
// getAll/delete/clear, transaction. Backed by plain JS Maps.
function makeIDB() {
  const stores = new Map() // storeName -> Map(key -> value)
  const keyPaths = new Map()

  function fireOk(req, result) {
    req.result = result
    queueMicrotask(() => req.onsuccess && req.onsuccess({ target: req }))
  }

  function objectStore(name) {
    const data = stores.get(name)
    const keyPath = keyPaths.get(name)
    const req = () => ({ onsuccess: null, onerror: null, result: undefined })
    return {
      add(v) { const r = req(); data.set(v[keyPath], structuredCloneSafe(v)); fireOk(r); return r },
      put(v) { const r = req(); data.set(v[keyPath], structuredCloneSafe(v)); fireOk(r); return r },
      get(k) { const r = req(); fireOk(r, cloneOut(data.get(k))); return r },
      getAll() { const r = req(); fireOk(r, [...data.values()].map(cloneOut)); return r },
      delete(k) { const r = req(); data.delete(k); fireOk(r); return r },
      clear() { const r = req(); data.clear(); fireOk(r); return r },
    }
  }

  const db = {
    objectStoreNames: { contains: (n) => stores.has(n) },
    createObjectStore(name, opts) {
      stores.set(name, new Map())
      keyPaths.set(name, opts.keyPath)
      return objectStore(name)
    },
    transaction(names) {
      const list = Array.isArray(names) ? names : [names]
      return { objectStore: (n) => (list.includes(n) ? objectStore(n) : objectStore(n)) }
    },
    _stores: stores, // test-only access to raw stored bytes
  }
  return db
}

// CryptoKey is not structured-cloneable by our naive clone; keep key objects by reference.
function structuredCloneSafe(v) {
  if (v && typeof v === 'object' && 'key' in v && v.key && typeof v.key === 'object' && 'algorithm' in v.key) {
    return { ...v } // preserve CryptoKey reference
  }
  return JSON.parse(JSON.stringify(v))
}
function cloneOut(v) {
  if (v === undefined) return undefined
  if (v && typeof v === 'object' && 'key' in v && v.key && typeof v.key === 'object' && 'algorithm' in v.key) {
    return { ...v }
  }
  return JSON.parse(JSON.stringify(v))
}

// ── Global environment for the module ───────────────────────────────
let theDB = null
function installGlobals() {
  theDB = makeIDB()
  const indexedDB = {
    open(_name, _version) {
      const req = { onsuccess: null, onerror: null, onupgradeneeded: null, result: null }
      queueMicrotask(() => {
        const fresh = theDB._stores.size === 0
        req.result = theDB
        if (fresh && req.onupgradeneeded) {
          req.onupgradeneeded({ target: { result: theDB } })
        }
        req.onsuccess && req.onsuccess({ target: req })
      })
      return req
    },
  }
  globalThis.indexedDB = indexedDB
  if (!globalThis.crypto || !globalThis.crypto.subtle) {
    Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
  }
  globalThis.btoa = (s) => Buffer.from(s, 'binary').toString('base64')
  globalThis.atob = (s) => Buffer.from(s, 'base64').toString('binary')
  // Emulate a browser-ish window WITHOUT navigator.onLine=false so processQueue is testable.
  globalThis.window = { addEventListener() {} }
  if (!globalThis.navigator) {
    Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true })
  } else {
    try { globalThis.navigator.onLine = true } catch { /* read-only in some runtimes */ }
  }
}

// ── Transpile the TS module and import it ───────────────────────────
async function loadModule() {
  const source = readFileSync(SRC, 'utf8')
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const dataUrl = 'data:text/javascript;base64,' + Buffer.from(js, 'utf8').toString('base64')
  return import(dataUrl)
}

// ── Test runner ─────────────────────────────────────────────────────
let passed = 0
const results = []
async function test(name, fn) {
  try {
    installGlobals() // fresh DB per test
    await fn()
    passed += 1
    results.push(`  ✓ ${name}`)
  } catch (e) {
    results.push(`  ✗ ${name}\n      ${e.message}`)
    throw e
  }
}

// The known sensitive values we will hunt for in raw storage.
const SECRET_MSG = 'PANIC BUTTON ACTIVATED - immediate danger'
const SECRET_LAT = 12.9716007
const SECRET_LNG = 77.5946001
const SECRET_DECODED = 'help me he is in the house right now'
const SECRET_ADDR = '221B Baker Street secret safehouse'

function rawStoreJSON() {
  // Serialize everything actually written to the sos_queue store.
  const store = theDB._stores.get('sos_queue')
  return JSON.stringify([...store.values()])
}

const mod = await loadModule()

try {
  // 1. enqueue + read-back round-trips content faithfully
  await test('enqueue then getQueue reconstructs message, coords, payload', async () => {
    const id = await mod.enqueueSOS({
      type: 'panic', endpoint: '/save-extracted-data', message: SECRET_MSG,
      latitude: SECRET_LAT, longitude: SECRET_LNG,
      payload: { decoded_text: SECRET_DECODED, location: `${SECRET_LAT},${SECRET_LNG}` },
    })
    assert.ok(id, 'id returned')
    const q = await mod.getQueue()
    assert.equal(q.length, 1)
    assert.equal(q[0].message, SECRET_MSG)
    assert.equal(q[0].latitude, SECRET_LAT)
    assert.equal(q[0].payload.decoded_text, SECRET_DECODED)
  })

  // 2. SECURITY ASSERTION — no sensitive value present in plaintext in raw storage
  await test('SECURITY: sensitive values absent from raw IndexedDB record', async () => {
    await mod.enqueueSOS({
      type: 'panic', endpoint: '/save-extracted-data', message: SECRET_MSG,
      latitude: SECRET_LAT, longitude: SECRET_LNG,
      payload: { decoded_text: SECRET_DECODED, address: SECRET_ADDR, location: `${SECRET_LAT},${SECRET_LNG}` },
    })
    const raw = rawStoreJSON()
    // The exact secret strings must NOT appear anywhere in the stored bytes.
    assert.ok(!raw.includes(SECRET_MSG), 'message leaked in plaintext')
    assert.ok(!raw.includes(SECRET_DECODED), 'decoded distress text leaked')
    assert.ok(!raw.includes(SECRET_ADDR), 'address leaked')
    assert.ok(!raw.includes(String(SECRET_LAT)), 'latitude leaked')
    assert.ok(!raw.includes(String(SECRET_LNG)), 'longitude leaked')
    assert.ok(!raw.includes('221B'), 'address fragment leaked')
    // And it must genuinely be encrypted, not just renamed.
    const rec = JSON.parse(raw)[0]
    assert.equal(rec.encrypted, true, 'record must be marked encrypted')
    assert.ok(rec.sealed && rec.sealed.iv && rec.sealed.ct, 'sealed blob present')
    assert.equal(rec.plainContent, undefined, 'no plainContent when encrypted')
  })

  // 3. idempotency key preserved in plaintext metadata AND inside payload
  await test('idempotency key preserved (id === payload.idempotency_key)', async () => {
    const id = await mod.enqueueSOS({
      type: 'image', endpoint: '/save-extracted-data', message: 'm', payload: {},
    })
    const q = await mod.getQueue()
    assert.equal(q[0].id, id)
    assert.equal(q[0].payload.idempotency_key, id)
    // id itself is fine in plaintext (it's an opaque UUID, not sensitive content)
    const raw = rawStoreJSON()
    assert.ok(raw.includes(id), 'id retained as plaintext metadata for dedup')
  })

  // 4. schema_version 2 stamped on stored records
  await test('stored record carries schema_version: 2', async () => {
    await mod.enqueueSOS({ type: 'voice', endpoint: '/x', message: 'm', payload: {} })
    const rec = JSON.parse(rawStoreJSON())[0]
    assert.equal(rec.schema_version, 2)
  })

  // 5. updateStatus changes metadata WITHOUT touching the sealed blob
  await test('updateStatus mutates metadata, leaves ciphertext intact', async () => {
    const id = await mod.enqueueSOS({
      type: 'panic', endpoint: '/x', message: SECRET_MSG, latitude: SECRET_LAT,
      longitude: SECRET_LNG, payload: { decoded_text: SECRET_DECODED },
    })
    const before = JSON.parse(rawStoreJSON())[0].sealed
    await mod.updateStatus(id, { status: 'delivered', caseId: 'HAVEN-123' })
    const after = JSON.parse(rawStoreJSON())[0]
    assert.equal(after.status, 'delivered')
    assert.equal(after.caseId, 'HAVEN-123')
    assert.deepEqual(after.sealed, before, 'ciphertext unchanged by metadata update')
    // still no plaintext leak after update
    assert.ok(!rawStoreJSON().includes(SECRET_DECODED))
    // still decryptable
    const q = await mod.getQueue()
    assert.equal(q[0].payload.decoded_text, SECRET_DECODED)
  })

  // 6. clearCompleted removes only delivered/acknowledged
  await test('clearCompleted removes only confirmed-terminal items', async () => {
    const a = await mod.enqueueSOS({ type: 'panic', endpoint: '/x', message: 'a', payload: {} })
    const b = await mod.enqueueSOS({ type: 'panic', endpoint: '/x', message: 'b', payload: {} })
    await mod.updateStatus(a, { status: 'delivered', caseId: 'C1' })
    await mod.clearCompleted()
    const q = await mod.getQueue()
    const ids = q.map((x) => x.id)
    assert.ok(!ids.includes(a), 'delivered item removed')
    assert.ok(ids.includes(b), 'queued item retained')
  })

  // 7. failed-item TTL: expired failed items purged; pending never purged
  await test('purgeExpired removes expired failed items, spares pending', async () => {
    const failed = await mod.enqueueSOS({ type: 'panic', endpoint: '/x', message: 'f', payload: {} })
    const pending = await mod.enqueueSOS({ type: 'panic', endpoint: '/x', message: 'p', payload: {} })
    // Mark one failed with an expiry in the past.
    await mod.updateStatus(failed, { status: 'failed', expiresAt: new Date(Date.now() - 1000).toISOString() })
    const purged = await mod.purgeExpired()
    assert.equal(purged, 1)
    const q = await mod.getQueue()
    const ids = q.map((x) => x.id)
    assert.ok(!ids.includes(failed), 'expired failed item purged')
    assert.ok(ids.includes(pending), 'pending item preserved')
  })

  // 8. a failed item still WITHIN its TTL is retained (bounded, not immediate delete)
  await test('failed item within TTL is retained for manual retry', async () => {
    const id = await mod.enqueueSOS({ type: 'panic', endpoint: '/x', message: 'f', payload: {} })
    await mod.updateStatus(id, { status: 'failed', expiresAt: new Date(Date.now() + 60_000).toISOString() })
    await mod.purgeExpired()
    const q = await mod.getQueue()
    assert.ok(q.map((x) => x.id).includes(id), 'not-yet-expired failed item kept')
  })

  // 9. legacy v1 plaintext record is migrated to encrypted v2 (and no longer leaks)
  await test('legacy v1 record migrated to encrypted v2 on read', async () => {
    await mod.getQueue() // initialize the DB/stores via upgradeneeded
    // Write a raw v1-shaped record directly into the store (bypassing enqueue).
    const store = theDB._stores.get('sos_queue')
    store.set('legacy-1', {
      id: 'legacy-1', type: 'panic', endpoint: '/save-extracted-data',
      message: SECRET_MSG, latitude: SECRET_LAT, longitude: SECRET_LNG,
      status: 'queued', retryCount: 2, updatedAt: '2025-01-01T00:00:00Z',
      payload: { decoded_text: SECRET_DECODED },
      // NOTE: no schema_version → treated as v1
    })
    // Confirm it starts as plaintext.
    assert.ok(rawStoreJSON().includes(SECRET_MSG), 'precondition: v1 is plaintext')
    const q = await mod.getQueue()
    const item = q.find((x) => x.id === 'legacy-1')
    assert.ok(item, 'legacy item still readable')
    assert.equal(item.message, SECRET_MSG, 'content preserved through migration')
    assert.equal(item.retryCount, 2, 'retry metadata preserved')
    assert.equal(item.payload.idempotency_key, 'legacy-1', 'idempotency preserved')
    // After migration the raw store must no longer contain plaintext.
    const raw = rawStoreJSON()
    assert.ok(!raw.includes(SECRET_MSG), 'plaintext purged after migration')
    assert.ok(!raw.includes(SECRET_DECODED), 'decoded text purged after migration')
    const rec = JSON.parse(raw).find((r) => r.id === 'legacy-1')
    assert.equal(rec.schema_version, 2)
    assert.equal(rec.encrypted, true)
  })

  // 10. malformed legacy record does not crash the queue
  await test('malformed legacy record is handled without throwing', async () => {
    await mod.getQueue() // initialize the DB/stores
    const store = theDB._stores.get('sos_queue')
    store.set('junk-1', { id: 'junk-1' }) // missing almost everything
    const q = await mod.getQueue() // must not throw
    const item = q.find((x) => x.id === 'junk-1')
    assert.ok(item, 'malformed item surfaced safely')
    assert.equal(typeof item.message, 'string')
    assert.equal(item.payload.idempotency_key, 'junk-1')
  })

  // 11. wipeQueue destroys all records AND the key (ciphertext unrecoverable)
  await test('wipeQueue clears records and destroys the device key', async () => {
    await mod.enqueueSOS({
      type: 'panic', endpoint: '/x', message: SECRET_MSG, latitude: SECRET_LAT,
      longitude: SECRET_LNG, payload: { decoded_text: SECRET_DECODED },
    })
    await mod.wipeQueue()
    const q = await mod.getQueue()
    assert.equal(q.length, 0, 'all records removed')
    const keyStore = theDB._stores.get('crypto_keys')
    assert.equal(keyStore.size, 0, 'device key destroyed')
  })

  // 12. processQueue delivers, honors idempotency header, sets delivered on case_id
  await test('processQueue posts payload, sends idempotency header, marks delivered', async () => {
    let seenBody = null
    let seenHeader = null
    globalThis.fetch = async (_url, opts) => {
      seenBody = JSON.parse(opts.body)
      seenHeader = opts.headers['X-Idempotency-Key']
      return { ok: true, json: async () => ({ case_id: 'HAVEN-999' }) }
    }
    const id = await mod.enqueueSOS({
      type: 'panic', endpoint: '/save-extracted-data', message: SECRET_MSG,
      latitude: SECRET_LAT, longitude: SECRET_LNG,
      payload: { decoded_text: SECRET_DECODED },
    })
    const n = await mod.processQueue()
    assert.equal(n, 1, 'one item progressed')
    assert.equal(seenHeader, id, 'idempotency header equals id')
    assert.equal(seenBody.idempotency_key, id, 'idempotency key in body')
    assert.equal(seenBody.decoded_text, SECRET_DECODED, 'decrypted payload sent to server')
    const q = await mod.getQueue()
    assert.equal(q[0].status, 'delivered')
    assert.equal(q[0].caseId, 'HAVEN-999')
    delete globalThis.fetch
  })

  console.log('\nOffline SOS queue — security & behaviour tests\n')
  console.log(results.join('\n'))
  console.log(`\n${passed}/12 passed\n`)
  process.exit(0)
} catch (e) {
  console.log('\nOffline SOS queue — security & behaviour tests\n')
  console.log(results.join('\n'))
  console.log(`\nFAILED after ${passed} passing test(s):`)
  console.error(e)
  process.exit(1)
}
