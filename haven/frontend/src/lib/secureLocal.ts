/**
 * secureLocal — encrypted-at-rest key/value store for small, sensitive strings
 * (e.g. a trusted emergency-contact name + number for the Panic Button).
 *
 * WHY THIS EXISTS
 * ---------------
 * These values were previously kept in plaintext `localStorage` (keys
 * `haven_panic_contact` / `haven_panic_name`), where any script on the origin —
 * or anyone with device access — could read a victim's trusted contact. This
 * module stores them encrypted with a per-device, NON-EXTRACTABLE AES-256-GCM
 * key held in IndexedDB, mirroring the exact crypto approach already used by the
 * offline SOS queue (`lib/offlineQueue.ts`). `crypto.subtle` can use the key but
 * JavaScript can never read its raw bytes.
 *
 * HONESTY / FALLBACK
 * ------------------
 * If Web Crypto is unavailable we do NOT silently pretend a value is encrypted:
 * the stored record is flagged `enc:false` so we never claim protection we did
 * not apply. Modern browsers always provide Web Crypto, so this is an edge case.
 *
 * PRIVACY
 * -------
 * The contact number is NEVER sent to Haven's backend and is never placed in a
 * Haven API URL/query. It is only ever used client-side to build a WhatsApp
 * deep link the user themselves chooses to open.
 */

const DB_NAME = 'haven_secure_local'
const DB_VERSION = 1
const VALUE_STORE = 'values'
const KEY_STORE = 'keys'
const KEY_ID = 'device-key-v1'

interface SecureRecord {
  id: string
  enc: boolean
  iv?: string
  ct?: string
  plain?: string // only set when enc === false (Web Crypto unavailable)
}

function webcrypto(): Crypto | null {
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle) return crypto
  } catch {
    /* ignore */
  }
  return null
}

function b64encode(bytes: Uint8Array): string {
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return btoa(s)
}

function b64decode(s: string): Uint8Array {
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event: IDBVersionChangeEvent) => {
      const db = (event.target as IDBOpenDBRequest).result
      if (!db.objectStoreNames.contains(VALUE_STORE)) {
        db.createObjectStore(VALUE_STORE, { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains(KEY_STORE)) {
        db.createObjectStore(KEY_STORE, { keyPath: 'id' })
      }
    }
  })
}

/**
 * Per-device AES-GCM key, generated + persisted on first use. Non-extractable:
 * usable via crypto.subtle but its bytes can never be read back into JS. Returns
 * null if Web Crypto is unavailable (caller then stores an honest plaintext
 * record rather than losing the value).
 */
async function getDeviceKey(db: IDBDatabase): Promise<CryptoKey | null> {
  const c = webcrypto()
  if (!c) return null
  const existing = await new Promise<{ id: string; key: CryptoKey } | undefined>(
    (resolve, reject) => {
      const req = db.transaction([KEY_STORE], 'readonly').objectStore(KEY_STORE).get(KEY_ID)
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    },
  ).catch(() => undefined)
  if (existing?.key) return existing.key

  const key = await c.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false /* non-extractable */, [
    'encrypt',
    'decrypt',
  ])
  await new Promise<void>((resolve, reject) => {
    const req = db.transaction([KEY_STORE], 'readwrite').objectStore(KEY_STORE).put({ id: KEY_ID, key })
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  }).catch(() => {
    /* if storing the key fails, we regenerate next time */
  })
  return key
}

function putRecord(db: IDBDatabase, rec: SecureRecord): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = db.transaction([VALUE_STORE], 'readwrite').objectStore(VALUE_STORE).put(rec)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
}

function getRecord(db: IDBDatabase, id: string): Promise<SecureRecord | undefined> {
  return new Promise((resolve, reject) => {
    const req = db.transaction([VALUE_STORE], 'readonly').objectStore(VALUE_STORE).get(id)
    req.onsuccess = () => resolve(req.result as SecureRecord | undefined)
    req.onerror = () => reject(req.error)
  })
}

/** Encrypt (when possible) and persist a small string under `name`. */
export async function saveSecure(name: string, value: string): Promise<void> {
  const db = await openDB()
  const key = await getDeviceKey(db)
  const c = webcrypto()
  if (key && c) {
    const iv = c.getRandomValues(new Uint8Array(12))
    const data = new TextEncoder().encode(value)
    const ct = await c.subtle.encrypt({ name: 'AES-GCM', iv }, key, data as BufferSource)
    await putRecord(db, { id: name, enc: true, iv: b64encode(iv), ct: b64encode(new Uint8Array(ct)) })
    return
  }
  // Honest fallback: no Web Crypto — store flagged as NOT encrypted.
  await putRecord(db, { id: name, enc: false, plain: value })
}

/** Load and decrypt a value previously stored with saveSecure. Null if absent. */
export async function loadSecure(name: string): Promise<string | null> {
  try {
    const db = await openDB()
    const rec = await getRecord(db, name)
    if (!rec) return null
    if (!rec.enc) return rec.plain ?? null
    const c = webcrypto()
    const key = await getDeviceKey(db)
    if (!c || !key || !rec.iv || !rec.ct) return null
    const iv = b64decode(rec.iv)
    const ct = b64decode(rec.ct)
    const pt = await c.subtle.decrypt({ name: 'AES-GCM', iv: iv as BufferSource }, key, ct as BufferSource)
    return new TextDecoder().decode(pt)
  } catch {
    return null
  }
}

/** Permanently remove a stored value. */
export async function removeSecure(name: string): Promise<void> {
  try {
    const db = await openDB()
    await new Promise<void>((resolve, reject) => {
      const req = db.transaction([VALUE_STORE], 'readwrite').objectStore(VALUE_STORE).delete(name)
      req.onsuccess = () => resolve()
      req.onerror = () => reject(req.error)
    })
  } catch {
    /* ignore */
  }
}

