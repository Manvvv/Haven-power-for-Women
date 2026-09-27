import { useState, useEffect, useCallback } from 'react'
import {
  getQueue,
  processQueue as processOfflineQueue,
  enqueueSOS,
  clearCompleted,
  QueuedSOS,
  SOSType,
} from '@/lib/offlineQueue'

/**
 * useOfflineStatus — reusable hook for the offline-first SOS workflow.
 *
 * Exposes:
 *   isOnline      – live navigator.onLine state (updates on online/offline events)
 *   queue         – the full local SOS queue (for status display)
 *   pendingCount  – items not yet confirmed delivered/acknowledged
 *   submitSOS()   – queue an SOS then immediately try to flush it (works on- or offline)
 *   processQueue()– manually trigger a delivery attempt
 */
export function useOfflineStatus(getToken?: () => Promise<string | null>) {
  const [isOnline, setIsOnline] = useState(
    typeof window !== 'undefined' ? navigator.onLine : true,
  )
  const [queue, setQueue] = useState<QueuedSOS[]>([])

  const refresh = useCallback(async () => {
    try {
      setQueue(await getQueue())
    } catch (e) {
      console.error('Failed to read offline queue', e)
    }
  }, [])

  const processQueue = useCallback(async () => {
    const n = await processOfflineQueue(getToken)
    await refresh()
    return n
  }, [refresh, getToken])

  const submitSOS = useCallback(
    async (input: {
      type: SOSType
      endpoint: string
      message: string
      latitude?: number | null
      longitude?: number | null
      payload: Record<string, unknown>
    }) => {
      const id = await enqueueSOS(input)
      await refresh()
      // Try to deliver right away; if offline this is a no-op and it stays queued.
      await processQueue()
      return id
    },
    [refresh, processQueue],
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    const handleOnline = () => {
      setIsOnline(true)
      processQueue()
    }
    const handleOffline = () => setIsOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    refresh()
    const interval = setInterval(() => {
      refresh()
      if (navigator.onLine) processQueue()
    }, 5000)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      clearInterval(interval)
    }
  }, [refresh, processQueue])

  const pendingCount = queue.filter(
    (q) => q.status !== 'delivered' && q.status !== 'acknowledged',
  ).length

  return {
    isOnline,
    queue,
    pendingCount,
    // kept for backwards-compat with existing callers:
    queuedCount: pendingCount,
    submitSOS,
    processQueue,
    clearCompleted: async () => {
      await clearCompleted()
      await refresh()
    },
  }
}
