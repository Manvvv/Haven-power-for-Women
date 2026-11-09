'use client'

import { useEffect } from 'react'

/**
 * ServiceWorkerRegistrar
 *
 * Registers the HAVEN service worker (sw.js) on page load.
 * The SW handles Web Push notifications for responder dispatches.
 *
 * This is a client-only component because navigator.serviceWorker
 * is not available during Next.js server rendering.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/' })
        .then((registration) => {
          console.log('[HAVEN] SW registered:', registration.scope)
        })
        .catch((err) => {
          // Non-fatal — push notifications won't work but the app continues normally
          console.warn('[HAVEN] SW registration failed:', err)
        })
    }
  }, [])

  return null
}
