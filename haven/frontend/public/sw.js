/* HAVEN service worker — responder Web Push only.
 *
 * Shows the lock-screen-safe emergency notification built by the backend
 * (services/web_push.py build_payload). The payload carries NO victim PII and NO
 * location. Clicking it opens /responder?offer=<dispatch_id>; the page itself
 * re-authenticates the responder and fetches the offer from the backend, so the
 * notification never grants access on its own.
 *
 * Limitations (see docs/PUSH_NOTIFICATIONS.md): delivery depends on the browser,
 * OS, notification permission, PWA installation, and battery policy. This worker
 * cannot guarantee a phone alarm and does not record delivery receipts.
 */
self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = {}
  }
  const title = typeof data.title === 'string' && data.title ? data.title : 'HAVEN EMERGENCY REQUEST'
  const options = {
    body: typeof data.body === 'string' ? data.body : 'A verified emergency response is required.',
    tag: typeof data.tag === 'string' ? data.tag : 'haven-offer',
    requireInteraction: true,
    renotify: false,
    data: {
      url: typeof data.url === 'string' && data.url.startsWith('/') ? data.url : '/responder',
      dispatch_id: typeof data.dispatch_id === 'string' ? data.dispatch_id : null,
    },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/responder'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(target).catch(() => {})
          return client.focus()
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target)
      return undefined
    })
  )
})
