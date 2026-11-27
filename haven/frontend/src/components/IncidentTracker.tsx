'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Activity, Clock, MapPin, RefreshCw, ShieldCheck, XCircle, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'
import { useNotifications } from '@/hooks/useNotifications'
import { DISPATCH_STATUS_LABEL, helpIsOnTheWay, type VictimDispatchView } from '@/lib/dispatch'
import SOSLifecycle from '@/components/SOSLifecycle'
import { useLang } from '@/components/LanguageContext'

export interface UserIncident {
  case_id: string
  category?: string
  description?: string
  summary?: string
  decoded_text?: string
  status: string
  severity?: string
  location?: string
  location_source?: string
  location_accuracy?: number
  location_captured_at?: string
  trigger_type?: string
  created_at: string
  updated_at?: string
  dispatch?: VictimDispatchView | null
}

const STATUS_STYLE: Record<string, { bg: string; fg: string; labelEn: string; labelHi: string }> = {
  CREATED:      { bg: '#f3f4f6', fg: '#374151', labelEn: 'Submitted',   labelHi: 'सबमिट किया गया' },
  RECEIVED:     { bg: '#fef3c7', fg: '#92400e', labelEn: 'Submitted / Received', labelHi: 'प्राप्त हुआ' },
  ACKNOWLEDGED: { bg: '#dbeafe', fg: '#1e40af', labelEn: 'Verified / Acknowledged', labelHi: 'सत्यापित' },
  IN_PROGRESS:  { bg: '#ede9fe', fg: '#5b21b6', labelEn: 'In Progress', labelHi: 'प्रगति पर' },
  RESOLVED:     { bg: '#dcfce7', fg: '#166534', labelEn: 'Resolved',    labelHi: 'समाधान हुआ' },
  CANCELLED:    { bg: '#f4f4f5', fg: '#52525b', labelEn: 'Cancelled',   labelHi: 'रद्द किया गया' },
}

export default function IncidentTracker({
  userId,
  refreshSignal = 0,
  onIncidentsLoaded,
}: {
  userId?: string
  refreshSignal?: number
  onIncidentsLoaded?: (incidents: UserIncident[]) => void
}) {
  const { lang } = useLang()
  const isHi = lang === 'hi'

  const [incidents, setIncidents] = useState<UserIncident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [clerkToken, setClerkToken] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [lifecycleMap, setLifecycleMap] = useState<Record<string, Array<{ status: string; timestamp: string; actor?: string }>>>({})
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      if (!userId || typeof window === 'undefined') return
      try {
        const tok = await (window as any).Clerk?.session?.getToken?.()
        if (alive && tok) setClerkToken(tok)
      } catch { /* ignore */ }
    })()
    return () => { alive = false }
  }, [userId])

  const { notifications } = useNotifications(userId || undefined, clerkToken)

  const loadIncidents = useCallback(async () => {
    if (!userId) return
    setError('')
    try {
      const res = await secureFetch('/sos/my-incidents?limit=20')
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail || `Could not load incidents (${res.status})`)
      }
      const data = await res.json()
      const list: UserIncident[] = Array.isArray(data.incidents) ? data.incidents : []
      setIncidents(list)
      if (onIncidentsLoaded) onIncidentsLoaded(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to fetch incident history.')
    } finally {
      setLoading(false)
    }
  }, [userId, onIncidentsLoaded])

  useEffect(() => {
    loadIncidents()
  }, [loadIncidents, refreshSignal])

  // Real-time refresh when WebSocket pushes a case/dispatch update
  useEffect(() => {
    if (notifications.length > 0) {
      loadIncidents()
    }
  }, [notifications.length, loadIncidents])

  const toggleExpand = async (caseId: string) => {
    if (expandedId === caseId) {
      setExpandedId(null)
      return
    }
    setExpandedId(caseId)
    try {
      const res = await secureFetch(`/sos/incidents/${encodeURIComponent(caseId)}`)
      if (res.ok) {
        const data = await res.json()
        const hist = Array.isArray(data.lifecycle)
          ? data.lifecycle.map((h: any) => ({
              status: String(h.to_status || h.status || '').toUpperCase(),
              timestamp: h.timestamp,
              actor: h.actor_id,
            }))
          : []
        setLifecycleMap((prev) => ({ ...prev, [caseId]: hist }))
      }
    } catch { /* non-fatal */ }
  }

  const handleCancel = async (caseId: string) => {
    if (!window.confirm(isHi ? 'क्या आप वाकई इस सक्रिय आपातकाल को रद्द करना चाहते हैं?' : 'Are you sure you are safe and want to cancel this incident?')) {
      return
    }
    setCancellingId(caseId)
    setActionMsg('')
    try {
      const res = await secureFetch(`/sos/incidents/${encodeURIComponent(caseId)}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'User confirmed safe and cancelled incident' }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || 'Could not cancel incident')
      }
      setActionMsg(isHi ? `घटना ${caseId} रद्द कर दी गई।` : `Incident ${caseId} cancelled.`)
      await loadIncidents()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to cancel incident.')
    } finally {
      setCancellingId(null)
    }
  }

  const activeIncidents = incidents.filter((i) => i.status !== 'RESOLVED' && i.status !== 'CANCELLED')

  return (
    <section
      aria-labelledby="incident-tracker-heading"
      style={{
        background: 'white',
        borderRadius: 18,
        padding: 'clamp(18px, 4vw, 26px)',
        border: '1px solid rgba(190,24,93,0.12)',
        boxShadow: '0 2px 14px rgba(190,24,93,0.06)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Activity size={20} style={{ color: '#be185d' }} />
          <h2 id="incident-tracker-heading" style={{ fontFamily: 'Georgia, serif', fontSize: 'clamp(1.05rem, 3.5vw, 1.25rem)', color: '#1a0a12', margin: 0 }}>
            {isHi ? 'मेरी घटना स्थिति एवं इतिहास' : 'Live Incident Status & History'}
          </h2>
          {activeIncidents.length > 0 && (
            <span style={{ background: '#fee2e2', color: '#dc2626', fontSize: '0.72rem', fontWeight: 800, padding: '2px 9px', borderRadius: 999 }}>
              {activeIncidents.length} Active
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={loadIncidents}
          aria-label="Refresh incidents"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '7px 12px', borderRadius: 8, border: '1px solid rgba(190,24,93,0.2)',
            background: '#fdf2f8', color: '#be185d', fontWeight: 700, fontSize: '0.76rem', cursor: 'pointer',
          }}
        >
          <RefreshCw size={13} /> {isHi ? 'रीफ्रेश' : 'Refresh'}
        </button>
      </div>

      {actionMsg && (
        <div role="status" style={{ marginBottom: 12, padding: '9px 12px', borderRadius: 10, background: '#f0fdf4', border: '1px solid #86efac', color: '#166534', fontSize: '0.8rem', fontWeight: 600 }}>
          {actionMsg}
        </div>
      )}

      {error && (
        <div role="alert" style={{ marginBottom: 12, padding: '9px 12px', borderRadius: 10, background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '20px 0', textAlign: 'center', color: '#8b6b7d', fontSize: '0.85rem' }}>
          {isHi ? 'घटना डेटा लोड हो रहा है…' : 'Loading your incidents from server…'}
        </div>
      ) : incidents.length === 0 ? (
        <div style={{ padding: '18px 14px', borderRadius: 12, background: '#fdf2f8', textAlign: 'center', color: '#8b6b7d', fontSize: '0.84rem' }}>
          {isHi
            ? 'आपके खाते में अभी कोई आपातकालीन घटना दर्ज नहीं है।'
            : 'No emergency incidents recorded for your account yet.'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {incidents.map((inc) => {
            const st = STATUS_STYLE[inc.status] || { bg: '#f3f4f6', fg: '#374151', labelEn: inc.status, labelHi: inc.status }
            const isOpen = inc.status !== 'RESOLVED' && inc.status !== 'CANCELLED'
            const isExpanded = expandedId === inc.case_id
            const disp = inc.dispatch
            const onTheWay = !!disp?.help_on_the_way || (disp ? helpIsOnTheWay(disp.status) : false)

            return (
              <article
                key={inc.case_id}
                style={{
                  border: isOpen ? '1px solid rgba(190,24,93,0.35)' : '1px solid #f1e4ec',
                  borderRadius: 14,
                  padding: 14,
                  background: isOpen ? '#fffafb' : 'white',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <code style={{ fontWeight: 700, fontSize: '0.82rem', color: '#1a0a12' }}>{inc.case_id}</code>
                      <span style={{ background: st.bg, color: st.fg, fontSize: '0.72rem', fontWeight: 800, padding: '2px 9px', borderRadius: 999 }}>
                        {isHi ? st.labelHi : st.labelEn}
                      </span>
                      {inc.category && (
                        <span style={{ fontSize: '0.72rem', color: '#8b6b7d', textTransform: 'capitalize' }}>
                          {inc.category.replace(/_/g, ' ')}
                        </span>
                      )}
                    </div>
                    <p style={{ fontSize: '0.82rem', color: '#4b3540', margin: '6px 0 4px', lineHeight: 1.45 }}>
                      {inc.description || inc.summary || inc.decoded_text || 'Emergency SOS alert'}
                    </p>
                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: '0.74rem', color: '#8b6b7d' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <Clock size={12} /> {formatServerDateTime(inc.created_at)}
                      </span>
                      {inc.location && (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <MapPin size={12} /> {inc.location}
                          {inc.location_accuracy != null && ` (±${Math.round(inc.location_accuracy)}m)`}
                        </span>
                      )}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {isOpen && (
                      <button
                        type="button"
                        onClick={() => handleCancel(inc.case_id)}
                        disabled={cancellingId === inc.case_id}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          padding: '6px 10px', borderRadius: 8,
                          border: '1px solid #fecaca', background: 'white',
                          color: '#b91c1c', fontSize: '0.74rem', fontWeight: 700, cursor: 'pointer',
                        }}
                      >
                        <XCircle size={13} />
                        {cancellingId === inc.case_id ? 'Cancelling…' : (isHi ? 'रद्द करें' : 'Cancel')}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => toggleExpand(inc.case_id)}
                      aria-expanded={isExpanded}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        padding: '6px 10px', borderRadius: 8,
                        border: '1px solid rgba(190,24,93,0.2)', background: '#fdf2f8',
                        color: '#be185d', fontSize: '0.74rem', fontWeight: 700, cursor: 'pointer',
                      }}
                    >
                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      {isHi ? 'विवरण' : 'Timeline'}
                    </button>
                  </div>
                </div>

                {/* Truthful victim-safe dispatch state */}
                {disp && (
                  <div
                    role="status"
                    style={{
                      marginTop: 10,
                      padding: '8px 12px',
                      borderRadius: 10,
                      background: onTheWay ? '#f0fdf4' : '#fffbeb',
                      border: `1px solid ${onTheWay ? '#86efac' : '#fde68a'}`,
                      fontSize: '0.78rem',
                      color: onTheWay ? '#166534' : '#92400e',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <ShieldCheck size={15} />
                    <span>
                      <strong>{DISPATCH_STATUS_LABEL[disp.status] || disp.status}</strong>
                      {onTheWay && disp.responder_label ? ` — ${disp.responder_label}` : ''}
                    </span>
                  </div>
                )}

                {isExpanded && (
                  <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid #f3e8ee' }}>
                    {inc.status === 'CANCELLED' ? (
                      <div style={{ fontSize: '0.78rem', color: '#52525b' }}>
                        This incident was cancelled and closed.
                      </div>
                    ) : (
                      <SOSLifecycle
                        currentStatus={inc.status}
                        statusHistory={lifecycleMap[inc.case_id] || []}
                      />
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
