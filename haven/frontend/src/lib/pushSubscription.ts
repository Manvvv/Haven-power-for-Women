/**
 * Responder Web Push registration (explicit user action only).
 *
 * Returns a PushState that the UI displays verbatim. The state never claims a
 * phone received an alarm: the strongest truthful outcome is "subscribed", and the
 * backend records SEND_ATTEMPTED per offer, not DELIVERED.
 *
 *   NOT_SUPPORTED          Browser has no Service Worker / Push / Notification API.
 *   NOT_CONFIGURED         Backend has no VAPID public key (server-side config).
 *   PERMISSION_DENIED      The user denied notification permission.
 *   PERMISSION_DEFAULT     Permission not yet asked.
 *   SUBSCRIPTION_REQUIRED  Permission granted but no subscription registered yet.
 *   SUBSCRIBED             Subscription registered with the backend.
 *   REGISTRATION_FAILED    Subscribe or upload failed (safe message only).
 */
import { getPushConfig, registerPushSubscription, removePushSubscription } from './dispatch'

export type PushState =
  | 'NOT_SUPPORTED'
  | 'NOT_CONFIGURED'
  | 'PERMISSION_DENIED'
  | 'PERMISSION_DEFAULT'
  | 'SUBSCRIPTION_REQUIRED'
  | 'SUBSCRIBED'
  | 'REGISTRATION_FAILED'

export function pushSupported(): boolean {
  return typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window
}

/** Decode a base64url VAPID public key into the Uint8Array PushManager requires. */
function urlBase64ToUint8Array(b64: string): ArrayBuffer {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const base64 = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const buffer = new ArrayBuffer(raw.length)
  const out = new Uint8Array(buffer)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return buffer
}

/** Current state, without prompting the user. */
export async function currentPushState(): Promise<PushState> {
  if (!pushSupported()) return 'NOT_SUPPORTED'
  const cfg = await getPushConfig().catch(() => ({ configured: false, vapid_public_key: null }))
  if (!cfg.configured) return 'NOT_CONFIGURED'
  if (Notification.permission === 'denied') return 'PERMISSION_DENIED'
  if (Notification.permission === 'default') return 'PERMISSION_DEFAULT'
  const reg = await navigator.serviceWorker.getRegistration('/sw.js')
  const sub = reg ? await reg.pushManager.getSubscription() : null
  return sub ? 'SUBSCRIBED' : 'SUBSCRIPTION_REQUIRED'
}

/**
 * Explicit user action: request permission, register the service worker, subscribe,
 * and upload the subscription. Never called automatically.
 */
export async function enablePush(): Promise<PushState> {
  if (!pushSupported()) return 'NOT_SUPPORTED'
  const cfg = await getPushConfig().catch(() => ({ configured: false, vapid_public_key: null }))
  if (!cfg.configured || !cfg.vapid_public_key) return 'NOT_CONFIGURED'

  const permission = await Notification.requestPermission()
  if (permission === 'denied') return 'PERMISSION_DENIED'
  if (permission !== 'granted') return 'PERMISSION_DEFAULT'

  try {
    const reg = (await navigator.serviceWorker.getRegistration('/sw.js'))
      || (await navigator.serviceWorker.register('/sw.js'))
    await navigator.serviceWorker.ready
    let sub = await reg.pushManager.getSubscription()
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key),
      })
    }
    await registerPushSubscription(sub.toJSON())
    return 'SUBSCRIBED'
  } catch {
    return 'REGISTRATION_FAILED'
  }
}

/** Remove the browser subscription and the server copy. */
export async function disablePush(): Promise<PushState> {
  if (!pushSupported()) return 'NOT_SUPPORTED'
  try {
    const reg = await navigator.serviceWorker.getRegistration('/sw.js')
    const sub = reg ? await reg.pushManager.getSubscription() : null
    if (sub) await sub.unsubscribe()
    await removePushSubscription().catch(() => {})
  } catch {
    return 'REGISTRATION_FAILED'
  }
  return 'SUBSCRIPTION_REQUIRED'
}

/** Human-facing copy for each state. Deliberately never says "delivered". */
export const PUSH_STATE_COPY: Record<PushState, string> = {
  NOT_SUPPORTED: 'This browser does not support background notifications. You will only see offers while HAVEN is open.',
  NOT_CONFIGURED: 'Background notifications are not configured on this server. Offers appear in HAVEN only.',
  PERMISSION_DENIED: 'Notifications are blocked for HAVEN. Enable them in browser settings. Offers appear in HAVEN only.',
  PERMISSION_DEFAULT: 'Notifications are not enabled yet. Enable them to receive alerts when HAVEN is in the background.',
  SUBSCRIPTION_REQUIRED: 'Notifications are allowed but not registered on this device yet.',
  SUBSCRIBED: 'Registered for background alerts. Delivery depends on your browser, OS and battery settings and cannot be guaranteed.',
  REGISTRATION_FAILED: 'Could not register background alerts on this device. Offers still appear in HAVEN.',
}
