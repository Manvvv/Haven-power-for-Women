import { useState, useEffect, useRef } from 'react'

export interface Notification {
  id: string
  type: string
  message: string
  timestamp: string
  read: boolean
  data?: any
}

export function useNotifications(userId?: string, token?: string | null) {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!userId || typeof window === 'undefined') return
    // The notification stream requires a verified token (the backend rejects
    // anonymous connections). Without one, don't attempt to connect.
    if (!token) return

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/^https?:\/\//, '')

    const connect = () => {
      const ws = new WebSocket(
        `${wsProtocol}//${wsHost}/ws/notifications/${encodeURIComponent(userId)}?token=${encodeURIComponent(token)}`
      )

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          setNotifications(prev => [data, ...prev])
        } catch (e) {
          console.error('Notification parse error', e)
        }
      }

      ws.onclose = () => {
        setTimeout(connect, 3000)
      }

      wsRef.current = ws
    }

    connect()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [userId, token])

  const unreadCount = notifications.filter(n => !n.read).length

  const markAsRead = (id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
    // Call API to mark as read if backend supports it
  }

  return { notifications, unreadCount, markAsRead }
}
