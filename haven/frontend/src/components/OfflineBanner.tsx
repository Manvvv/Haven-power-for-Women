'use client'
import React from 'react'
import { WifiOff, CheckCircle, Clock, Loader2, AlertTriangle } from 'lucide-react'
import { useOfflineStatus } from '@/hooks/useOfflineStatus'

/**
 * App-wide banner that surfaces offline status and the SOS delivery queue.
 * It never claims an SOS was delivered unless the queue item is actually in a
 * confirmed delivered/acknowledged state.
 */
export default function OfflineBanner() {
  const { isOnline, queue, pendingCount } = useOfflineStatus()
  const [flash, setFlash] = React.useState(false)

  const failed = queue.filter((q) => q.status === 'failed').length
  const sending = queue.some((q) => q.status === 'sending' || q.status === 'sent')

  // Briefly celebrate when everything drains while online.
  const prevPending = React.useRef(pendingCount)
  React.useEffect(() => {
    if (isOnline && prevPending.current > 0 && pendingCount === 0) {
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 3500)
      prevPending.current = pendingCount
      return () => clearTimeout(t)
    }
    prevPending.current = pendingCount
  }, [pendingCount, isOnline])

  // Nothing to show when online, nothing queued, and no recent success flash.
  if (isOnline && pendingCount === 0 && failed === 0 && !flash) return null

  let bg = '#f59e0b' // offline / warning amber
  let icon = <WifiOff size={18} />
  let text = 'You are offline. SOS messages will be queued and sent automatically when you reconnect.'

  if (isOnline && flash && pendingCount === 0) {
    bg = '#10b981'
    icon = <CheckCircle size={18} />
    text = 'Back online — all queued SOS messages have been delivered.'
  } else if (isOnline && pendingCount > 0) {
    bg = '#be185d'
    icon = sending ? <Loader2 size={18} className="haven-spin" /> : <Clock size={18} />
    text = `${pendingCount} SOS ${pendingCount === 1 ? 'message is' : 'messages are'} being delivered…`
  } else if (!isOnline && pendingCount > 0) {
    text = `You are offline. ${pendingCount} SOS ${pendingCount === 1 ? 'message is' : 'messages are'} queued and will send automatically when you reconnect.`
  }

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: bg,
        color: '#fff',
        padding: '0.6rem 0.9rem',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: '0.5rem',
        fontWeight: 600,
        fontSize: '0.85rem',
        textAlign: 'center',
        boxShadow: '0 2px 10px rgba(0,0,0,0.12)',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      {icon}
      <span>{text}</span>
      {failed > 0 && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 8, opacity: 0.95 }}>
          <AlertTriangle size={16} /> {failed} could not be sent — will retry.
        </span>
      )}
      <style>{`@keyframes haven-spin{to{transform:rotate(360deg)}}.haven-spin{animation:haven-spin 1s linear infinite}`}</style>
    </div>
  )
}
