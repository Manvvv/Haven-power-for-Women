'use client'

import React, { useState, useEffect } from 'react'
import { Shield, History, MapPin, Trash2, AlertTriangle, MessageSquare } from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'
import { useHavenAuth } from '@/hooks/useHavenAuth'

const colors = {
  primary: '#be185d',
  light: '#fdf2f8',
  dark: '#1a0a12',
  accent: '#f472b6',
  muted: '#8b6b7d',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  white: '#ffffff',
  bg: 'linear-gradient(150deg, #fdf2f8 0%, #f5f0ff 50%, #fce7f3 100%)'
}

const styles = {
  container: {
    minHeight: '100vh',
    background: colors.bg,
    color: colors.dark,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    padding: '2rem 1rem',
  },
  maxContainer: {
    maxWidth: '800px',
    margin: '0 auto',
  },
  header: {
    marginBottom: '2rem',
  },
  title: {
    fontFamily: 'Georgia, serif',
    fontSize: 'clamp(1.5rem, 5vw, 2.5rem)',
    color: colors.primary,
    margin: 0,
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  },
  card: {
    background: colors.white,
    border: `1px solid rgba(190,24,93,0.1)`,
    borderRadius: '16px',
    boxShadow: '0 2px 12px rgba(190,24,93,0.08)',
    padding: '1.5rem',
    marginBottom: '1.5rem',
  },
  cardTitle: {
    fontFamily: 'Georgia, serif',
    fontSize: '1.5rem',
    color: colors.dark,
    marginTop: 0,
    marginBottom: '1rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  },
  btnDanger: {
    background: colors.danger,
    color: colors.white,
    border: 'none',
    borderRadius: '50px',
    padding: '0.75rem 1.5rem',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.5rem',
  },
  listItem: {
    padding: '1rem',
    borderBottom: `1px solid ${colors.light}`,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center'
  }
}

export default function PrivacyPage() {
  useHavenAuth()
  const { user } = useUser()
  const userId = user?.id || 'haven_user'

  const [data, setData] = useState<any>(null)

  useEffect(() => {
    if (userId) {
      secureFetch(`/privacy/my-data/${userId}`)
        .then(res => res.json())
        .then(d => setData(d))
        .catch(console.error)
    }
  }, [userId])

  const deleteTherapySession = async (id: string) => {
    if (!confirm('Are you sure you want to delete this session?')) return
    await secureFetch(`/privacy/therapy-sessions/${id}`, { method: 'DELETE' })
    setData((prev: any) => ({
      ...prev,
      sessions: prev.sessions.filter((s: any) => s.id !== id)
    }))
  }

  const requestDeletion = async () => {
    if (!confirm('This will request complete deletion of your account. Proceed?')) return
    await secureFetch('/privacy/deletion-request', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId })
    })
    alert('Deletion request submitted.')
  }

  return (
    <div style={styles.container}>
      <div style={styles.maxContainer}>
        <div style={styles.header}>
          <h1 style={styles.title}><Shield /> Privacy & Data Hub</h1>
        </div>

        <div style={styles.card}>
          <h2 style={styles.cardTitle}><History /> SOS History</h2>
          {data?.sos_history?.map((h: any, i: number) => (
            <div key={i} style={styles.listItem}>
              <div>
                <strong>{formatServerDateTime(h.timestamp)}</strong>
                <div style={{ color: colors.muted, fontSize: '0.9rem' }}>Status: {h.status}</div>
              </div>
            </div>
          )) || <p>No history found.</p>}
        </div>

        <div style={styles.card}>
          <h2 style={styles.cardTitle}><MessageSquare /> AI Therapy Conversations</h2>
          {data?.sessions?.map((s: any) => (
            <div key={s.id} style={styles.listItem}>
              <div>
                <strong>Session {s.id}</strong>
                <div style={{ color: colors.muted, fontSize: '0.9rem' }}>{formatServerDateTime(s.timestamp)}</div>
              </div>
              <button
                onClick={() => deleteTherapySession(s.id)}
                style={{ background: 'transparent', border: 'none', color: colors.danger, cursor: 'pointer' }}
              >
                <Trash2 />
              </button>
            </div>
          )) || <p>No sessions found.</p>}
        </div>

        <div style={styles.card}>
          <h2 style={styles.cardTitle}><MapPin /> Location Data</h2>
          <p>We only track your location when an SOS is active or when you explicitly enable tracking.</p>
          <div>
            <strong>Current status: </strong>
            <span style={{ color: data?.is_tracking ? colors.success : colors.muted }}>
              {data?.is_tracking ? 'Tracking Active' : 'Not Tracking'}
            </span>
          </div>
        </div>

        <div style={styles.card}>
          <h2 style={styles.cardTitle}><AlertTriangle color={colors.danger} /> Danger Zone</h2>
          <p style={{ marginBottom: '1rem', color: colors.muted }}>Request to permanently delete all your data and account.</p>
          <button style={styles.btnDanger} onClick={requestDeletion}>
            <Trash2 size={18} /> Request Account Deletion
          </button>
        </div>
      </div>
    </div>
  )
}
