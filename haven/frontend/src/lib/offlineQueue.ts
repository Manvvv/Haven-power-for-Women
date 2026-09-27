/**
 * Haven Offline-First SOS Queue (secure persistence — schema v2)
 * ------------------------------------------------------------------
 * A single, reusable service that guarantees an SOS is never lost to a
 * flaky connection. Every SOS — image, voice, or panic — is written to
 * IndexedDB first, then delivered to the backend with automatic retry.
 *
 * Delivery states (honest, never optimistic):
 *   queued       → saved locally only; NOT yet accepted by the server
 *   sending      → an HTTP request is currently in flight
 *   sent         → server returned 2xx (request accepted)
 *   delivered    → server confirmed the case was persisted (returned a case_id)
 *   acknowledged → an authority has acknowledged the case (confirmed server-side)
 *   failed       → gave up after max retries (retained briefly for manual retry)
 *
 * We NEVER mark an item "delivered" until the server confirms persistence, and
 * NEVER "acknowledged" unless a case-status check confirms it.
 *
 * Idempotency: each queued SOS gets a UUID that is sent to the backend as both an
 * `idempotency_key` field and an `X-Idempotency-Key` header, so retries (or a
 * duplicate submission from another device) can never create a duplicate case.
 *
 * ── SECURITY (P1-6) ────────────────────────────────────────────────
 * The device/browser may be accessible to an abusive person, so we do NOT
 * store the SOS content (message, GPS coordinates, decoded distress text, the
 * outgoing payload) in plaintext. Instead:
 *
 *   1. DATA MINIMIZATION — only the fields required to *resend* the SOS are
 *      persisted. The redundant top-level message/latitude/longitude (which the
 *      old code stored but never resent or displayed) are folded into the
 *      encrypted blob; the UI only ever reads `status`.
 *   2. ENCRYPTION AT REST — sensitive fields are sealed with AES-256-GCM using a
 *      per-device key generated via Web Crypto (`crypto.subtle.generateKey`) that
 *      is **non-extractable**: the raw key bytes are never exposed to JS and are
 *      never written next to the ciphertext. The CryptoKey object is persisted in
 *      a separate IndexedDB store via structured clone. There is NO hardcoded key
 *      and NO key derived from a public constant.
 *   3. BOUNDED RETENTION — permanently `failed` items get an explicit `expiresAt`
 *      TTL and are purged after that window. Pending/retryable items are never
 *      purged. Idempotency keys are preserved.
 *
 * RESIDUAL LIMITATION (documented honestly): a non-extractable key still lets the
 * *same browser profile* decrypt (the app must be able to resend). So this
 * protects against offline/forensic extraction of the IndexedDB files, NOT against
 * an attacker running code in the already-unlocked browser. For that, use the
 * secure wipe (`wipeQueue`) — see the duress-wipe integration note below.
 */

export type SOSType = 'image' | 'voice' | 'panic'

export type DeliveryStatus =
  | 'queued'
  | 'sending'
  | 'sent'
  | 'delivered'
  | 'acknowledged'
  | 'failed'

/**
 * Runtime shape returned to callers. Backwards-compatible with the old interface
 * so consumers (useOfflineStatus, PanicButton, OfflineBanner) need no changes.
 * `message`/`latitude`/`longitude`/`payload` are reconstructed from the decrypted
 * blob on read; they are NOT stored in plaintext.
 */
export interface QueuedSOS {
  id: string // UUID — also used as the idempotency key
  type: SOSType
  endpoint: string // backend path this SOS should be POSTed to
  message: string
  timestamp: string // ISO — when the SOS was created by the user
  latitude: number | null
  longitude: number | null
  status: DeliveryStatus
  retryCount: number
  lastError?: string
  caseId?: string // populated once the server confirms delivery
  updatedAt: string
  nextRetryAt?: string // ISO — earliest time this item should be retried
  expiresAt?: string // ISO — when a permanently-failed item may be purged
  payload: Record<string, unknown>
}

/** Fields that are encrypted together (never persisted in plaintext). */
interface SensitiveContent {
  message: string
  latitude: number | null
  longitude: number | null
  payload: Record<string, unknown>
}

/** A sealed (AES-GCM) blob: base64 IV + base64 ciphertext. Holds no key material. */
interface SealedBlob {
  iv: string
  ct: string
}

/**
 * The record actually written to IndexedDB (schema v2). Only non-sensitive
 * metadata is in the clear; all SOS content lives in `sealed` (encrypted) or, if
 * Web Crypto is unavailable, in `plainContent` with `encrypted:false` so we never
 * *claim* encryption we didn't perform.
 */
interface StoredRecordV2 {
  schema_version: 2
  id: string
  type: SOSType
  endpoint: string
  timestamp: string
  status: DeliveryStatus
  retryCount: number
  lastError?: string
  caseId?: string
  updatedAt: string
  nextRetryAt?: string
  expiresAt?: string
  encrypted: boolean
  sealed?: SealedBlob
  plainContent?: SensitiveContent // only used as an honest fallback when crypto is unavailable
}

const DB_NAME = 'haven_offline'
const DB_VERSION = 2
const STORE_NAME = 'sos_queue'
const KEY_STORE = 'crypto_keys'
const KEY_ID = 'sos_queue_key_v1'
const MAX_RETRIES = 6
const FAILED_TTL_MS = 24 * 60 * 60 * 1000 // keep failed items 24h for manual retry, then purge
const BACKOFF_BASE_MS = 15 * 1000 // 15s, doubled per retry (capped)
const BACKOFF_CAP_MS = 15 * 60 * 1000 // 15 min
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Web Crypto helpers ──────────────────────────────────────────────
function webcrypto(): Crypto | null {
  const c = (globalThis as unknown as { crypto?: Crypto }).crypto
  return c && 'subtle' in c ? c : null
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

// ── Low-level IndexedDB helpers ─────────────────────────────────────
export async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event: IDBVersionChangeEvent) => {
      const db = (event.target as IDBOpenDBRequest).result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
      // v2: a separate store holds the non-extractable CryptoKey object.
      if (!db.objectStoreNames.contains(KEY_STORE)) {
        db.createObjectStore(KEY_STORE, { keyPath: 'id' })
      }
    }
  })
}

function tx(db: IDBDatabase, mode: IDBTransactionMode) {
  return db.transaction([STORE_NAME], mode).objectStore(STORE_NAME)
}

/**
 * Fetch the per-device AES-GCM key, generating and persisting one on first use.
 * The key is non-extractable, so `crypto.subtle` can use it but JS can never read
 * its bytes. Returns null if Web Crypto is unavailable (we then fall back to an
 * honest unencrypted record rather than dropping a safety-critical SOS).
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
    /* if storing the key fails, we simply regenerate next time */
  })
  return key
}

async function seal(key: CryptoKey, content: SensitiveContent): Promise<SealedBlob> {
  const c = webcrypto()
  if (!c) throw new Error('no webcrypto')
  const iv = c.getRandomValues(new Uint8Array(12))
  const data = new TextEncoder().encode(JSON.stringify(content))
  const ct = await c.subtle.encrypt({ name: 'AES-GCM', iv }, key, data as BufferSource)
  return { iv: b64encode(iv), ct: b64encode(new Uint8Array(ct)) }
}

async function unseal(key: CryptoKey, blob: SealedBlob): Promise<SensitiveContent> {
  const c = webcrypto()
  if (!c) throw new Error('no webcrypto')
  const iv = b64decode(blob.iv)
  const ct = b64decode(blob.ct)
  const pt = await c.subtle.decrypt({ name: 'AES-GCM', iv: iv as BufferSource }, key, ct as BufferSource)
  return JSON.parse(new TextDecoder().decode(pt)) as SensitiveContent
}

// ── Record <-> runtime mapping ──────────────────────────────────────
function baseRuntime(rec: StoredRecordV2, content: SensitiveContent): QueuedSOS {
  return {
    id: rec.id,
    type: rec.type,
    endpoint: rec.endpoint,
    message: content.message,
    timestamp: rec.timestamp,
    latitude: content.latitude,
    longitude: content.longitude,
    status: rec.status,
    retryCount: rec.retryCount,
    lastError: rec.lastError,
    caseId: rec.caseId,
    updatedAt: rec.updatedAt,
    nextRetryAt: rec.nextRetryAt,
    expiresAt: rec.expiresAt,
    payload: content.payload,
  }
}

async function recordToRuntime(db: IDBDatabase, rec: StoredRecordV2): Promise<QueuedSOS> {
  // Honest unencrypted fallback (only when crypto was unavailable at enqueue).
  if (!rec.encrypted || !rec.sealed) {
    const content = rec.plainContent ?? { message: '', latitude: null, longitude: null, payload: {} }
    return baseRuntime(rec, content)
  }
  try {
    const key = await getDeviceKey(db)
    if (!key) throw new Error('no key')
    const content = await unseal(key, rec.sealed)
    return baseRuntime(rec, content)
  } catch {
    // Key lost / undecryptable (e.g. wiped key). Surface as failed so the UI can
    // show it, but never expose plaintext we don't have. Payload is empty so it
    // can't be silently resent with missing data.
    return baseRuntime({ ...rec, status: 'failed', lastError: 'undecryptable' }, {
      message: '',
      latitude: null,
      longitude: null,
      payload: { idempotency_key: rec.id },
    })
  }
}

// ── Legacy v1 migration ─────────────────────────────────────────────
interface LegacyV1 {
  id: string
  type: SOSType
  endpoint: string
  message?: string
  timestamp?: string
  latitude?: number | null
  longitude?: number | null
  status?: DeliveryStatus
  retryCount?: number
  lastError?: string
  caseId?: string
  updatedAt?: string
  payload?: Record<string, unknown>
}

function isV2(rec: unknown): rec is StoredRecordV2 {
  return !!rec && typeof rec === 'object' && (rec as { schema_version?: number }).schema_version === 2
}

/**
 * Migrate a v1 plaintext record into an encrypted v2 record. If the shape is
 * unexpected we build the safest record we can rather than throwing — a malformed
 * legacy record must never crash the queue. Preserves id/idempotency, status, and
 * retry metadata.
 */
async function migrateV1(db: IDBDatabase, raw: LegacyV1): Promise<StoredRecordV2> {
  const now = new Date().toISOString()
  const content: SensitiveContent = {
    message: typeof raw.message === 'string' ? raw.message : '',
    latitude: typeof raw.latitude === 'number' ? raw.latitude : null,
    longitude: typeof raw.longitude === 'number' ? raw.longitude : null,
    payload:
      raw.payload && typeof raw.payload === 'object'
        ? { ...raw.payload, idempotency_key: raw.id }
        : { idempotency_key: raw.id },
  }
  const meta = {
    schema_version: 2 as const,
    id: raw.id,
    type: (raw.type ?? 'panic') as SOSType,
    endpoint: typeof raw.endpoint === 'string' ? raw.endpoint : '/save-extracted-data',
    timestamp: raw.timestamp ?? now,
    status: (raw.status ?? 'queued') as DeliveryStatus,
    retryCount: typeof raw.retryCount === 'number' ? raw.retryCount : 0,
    lastError: raw.lastError,
    caseId: raw.caseId,
    updatedAt: now,
  }
  let rec: StoredRecordV2
  try {
    const key = await getDeviceKey(db)
    if (!key) throw new Error('no key')
    rec = { ...meta, encrypted: true, sealed: await seal(key, content) }
  } catch {
    rec = { ...meta, encrypted: false, plainContent: content }
  }
  // Persist the upgraded record so the old plaintext row is overwritten in place.
  await new Promise<void>((resolve) => {
    const req = tx(db, 'readwrite').put(rec)
    req.onsuccess = () => resolve()
    req.onerror = () => resolve() // best-effort; never throw during a read
  })
  return rec
}

// ── Internal raw read + purge ───────────────────────────────────────
async function readAllRaw(db: IDBDatabase): Promise<unknown[]> {
  return new Promise((resolve, reject) => {
    const req = tx(db, 'readonly').getAll()
    req.onsuccess = () => resolve((req.result as unknown[]) || [])
    req.onerror = () => reject(req.error)
  })
}

/**
 * Delete permanently-failed items whose TTL has elapsed. Only `failed` items with
 * an `expiresAt` in the past are removed — pending/retryable/delivered items are
 * never touched here.
 */
export async function purgeExpired(): Promise<number> {
  const db = await openDB()
  const raw = await readAllRaw(db)
  const now = Date.now()
  let purged = 0
  for (const r of raw) {
    const rec = r as StoredRecordV2 & LegacyV1
    const expiresAt = (rec as StoredRecordV2).expiresAt
    if (rec.status === 'failed' && expiresAt && Date.parse(expiresAt) <= now) {
      await removeItem(rec.id)
      purged += 1
    }
  }
  return purged
}

// ── Public queue API ────────────────────────────────────────────────

/**
 * Enqueue a new SOS. Returns the generated id (idempotency key). Sensitive
 * content is encrypted before it touches IndexedDB.
 */
export async function enqueueSOS(input: {
  type: SOSType
  endpoint: string
  message: string
  latitude?: number | null
  longitude?: number | null
  payload: Record<string, unknown>
}): Promise<string> {
  const db = await openDB()
  const c = webcrypto()
  const id =
    c && 'randomUUID' in c
      ? c.randomUUID()
      : `sos-${Date.now()}-${Math.random().toString(36).slice(2)}`
  const now = new Date().toISOString()

  const content: SensitiveContent = {
    message: input.message,
    latitude: input.latitude ?? null,
    longitude: input.longitude ?? null,
    // The idempotency key travels inside the payload too, so the backend dedupes
    // even if the header is stripped by a proxy.
    payload: { ...input.payload, idempotency_key: id },
  }

  const meta = {
    schema_version: 2 as const,
    id,
    type: input.type,
    endpoint: input.endpoint,
    timestamp: now,
    status: 'queued' as DeliveryStatus,
    retryCount: 0,
    updatedAt: now,
  }

  let rec: StoredRecordV2
  const key = await getDeviceKey(db)
  if (key) {
    rec = { ...meta, encrypted: true, sealed: await seal(key, content) }
  } else {
    // Web Crypto unavailable: never drop a safety-critical SOS. Store honestly as
    // unencrypted so we don't *claim* protection we couldn't provide.
    rec = { ...meta, encrypted: false, plainContent: content }
  }

  await new Promise<void>((resolve, reject) => {
    const req = tx(db, 'readwrite').add(rec)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
  return id
}

/** Read the whole queue (decrypted for the caller). Migrates v1 records and purges expired failures. */
export async function getQueue(): Promise<QueuedSOS[]> {
  const db = await openDB()
  await purgeExpired()
  const raw = await readAllRaw(db)
  const out: QueuedSOS[] = []
  for (const r of raw) {
    const rec = isV2(r) ? (r as StoredRecordV2) : await migrateV1(db, r as LegacyV1)
    out.push(await recordToRuntime(db, rec))
  }
  return out
}

export async function getItem(id: string): Promise<QueuedSOS | undefined> {
  const db = await openDB()
  const raw = await new Promise<unknown>((resolve, reject) => {
    const req = tx(db, 'readonly').get(id)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  if (!raw) return undefined
  const rec = isV2(raw) ? (raw as StoredRecordV2) : await migrateV1(db, raw as LegacyV1)
  return recordToRuntime(db, rec)
}

/**
 * Update only NON-SENSITIVE metadata on a stored record (status, retryCount,
 * error, caseId, timing). The encrypted `sealed` blob is passed through untouched
 * — callers never hand us decrypted content to re-persist, so plaintext can't leak
 * back into storage through this path.
 */
export async function updateStatus(
  id: string,
  updates: Partial<
    Pick<
      QueuedSOS,
      'status' | 'retryCount' | 'lastError' | 'caseId' | 'nextRetryAt' | 'expiresAt'
    >
  >,
): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const store = tx(db, 'readwrite')
    const getReq = store.get(id)
    getReq.onsuccess = () => {
      if (!getReq.result) return resolve()
      const current = getReq.result as StoredRecordV2
      const merged: StoredRecordV2 = {
        ...current,
        ...updates,
        updatedAt: new Date().toISOString(),
      }
      const putReq = store.put(merged)
      putReq.onsuccess = () => resolve()
      putReq.onerror = () => reject(putReq.error)
    }
    getReq.onerror = () => reject(getReq.error)
  })
}

export async function removeItem(id: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const req = tx(db, 'readwrite').delete(id)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
}

/** Remove items that have reached a terminal, confirmed state. */
export async function clearCompleted(): Promise<void> {
  const queue = await getQueue()
  await Promise.all(
    queue
      .filter((q) => q.status === 'delivered' || q.status === 'acknowledged')
      .map((q) => removeItem(q.id)),
  )
}

/**
 * Securely wipe ALL queued SOS data and destroy the device key so any remaining
 * ciphertext becomes permanently undecryptable. This is the integration point for
 * a duress/panic wipe.
 *
 * NOTE: HAVEN does not currently have a global duress-wipe trigger (the disguise/
 * QuickEscape flow only hides the UI; it does not clear storage). Wiring this into
 * a wipe gesture is a deliberate, separate follow-up — this function is the hook it
 * would call. It is intentionally NOT invoked automatically here so we don't
 * silently destroy pending emergency SOSes.
 */
export async function wipeQueue(): Promise<void> {
  const db = await openDB()
  await new Promise<void>((resolve) => {
    const req = db.transaction([STORE_NAME], 'readwrite').objectStore(STORE_NAME).clear()
    req.onsuccess = () => resolve()
    req.onerror = () => resolve()
  })
  await new Promise<void>((resolve) => {
    const req = db.transaction([KEY_STORE], 'readwrite').objectStore(KEY_STORE).delete(KEY_ID)
    req.onsuccess = () => resolve()
    req.onerror = () => resolve()
  })
}

// Prevent overlapping flushes (e.g. interval + online event firing together).
let flushing = false

function backoffMs(retryCount: number): number {
  return Math.min(BACKOFF_BASE_MS * Math.pow(2, Math.max(0, retryCount - 1)), BACKOFF_CAP_MS)
}

/**
 * Attempt to deliver every pending SOS. Safe to call repeatedly.
 * Returns the number of items that reached at least "sent".
 */
export async function processQueue(getToken?: () => Promise<string | null>): Promise<number> {
  if (typeof window === 'undefined' || !navigator.onLine || flushing) return 0
  flushing = true
  let progressed = 0
  try {
    const queue = await getQueue()
    const now = Date.now()
    const pending = queue.filter(
      (q) => q.status === 'queued' || q.status === 'sending' || q.status === 'sent',
    )
    for (const sos of pending) {
      // Respect retry backoff — don't hammer a failing server.
      if (sos.nextRetryAt && Date.parse(sos.nextRetryAt) > now) continue

      if (sos.retryCount >= MAX_RETRIES) {
        if (sos.status !== 'failed') {
          // Permanently failed: set a bounded TTL for retention, then it will be purged.
          await updateStatus(sos.id, {
            status: 'failed',
            expiresAt: new Date(now + FAILED_TTL_MS).toISOString(),
          })
        }
        continue
      }
      const attempt = sos.retryCount + 1
      await updateStatus(sos.id, { status: 'sending', retryCount: attempt })
      try {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
          'X-Idempotency-Key': sos.id,
        }
        if (getToken) {
          try {
            const t = await getToken()
            if (t) headers['Authorization'] = `Bearer ${t}`
          } catch {
            /* token optional */
          }
        }
        const url = sos.endpoint.startsWith('http')
          ? sos.endpoint
          : `${API_BASE}${sos.endpoint.startsWith('/') ? '' : '/'}${sos.endpoint}`
        const res = await fetch(url, {
          method: 'POST',
          headers,
          body: JSON.stringify(sos.payload),
        })
        if (res.ok) {
          await updateStatus(sos.id, { status: 'sent', lastError: undefined })
          let caseId: string | undefined
          try {
            const data = await res.json()
            caseId = data.case_id || data.event_id || data?.data?.case_id
          } catch {
            /* body may be empty */
          }
          if (caseId) {
            await updateStatus(sos.id, { status: 'delivered', caseId })
          }
          progressed += 1
        } else {
          // Server reachable but rejected — back to queued for retry with backoff.
          await updateStatus(sos.id, {
            status: 'queued',
            lastError: `HTTP ${res.status}`,
            nextRetryAt: new Date(now + backoffMs(attempt)).toISOString(),
          })
        }
      } catch (e) {
        await updateStatus(sos.id, {
          status: 'queued',
          lastError: e instanceof Error ? e.message : 'network error',
          nextRetryAt: new Date(now + backoffMs(attempt)).toISOString(),
        })
      }
    }
  } finally {
    flushing = false
  }
  return progressed
}

// Auto-flush when connectivity returns.
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    processQueue()
  })
}
