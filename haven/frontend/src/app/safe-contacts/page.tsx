'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Users, Plus, Edit3, Trash2, CheckCircle2, ShieldAlert,
  Clock, History, Send, AlertTriangle, Check, X, MapPin, Shield,
} from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime, parseServerDate } from '@/lib/datetime'

interface TrustedContact {
  contact_id: string
  name: string
  phone: string
  email?: string
  relationship?: string
  priority: number
  verification_status?: string
  verified_at?: string | null
  created_at?: string
}

interface ContactHistoryEntry {
  history_id: string
  contact_name: string
  action: string
  details: string
  timestamp: string
}

interface CheckinRecord {
  checkin_id: string
  status: 'ACTIVE' | 'CONFIRMED_SAFE' | 'CANCELLED' | 'ESCALATED'
  duration_minutes: number
  reminder_before_minutes: number
  activity_label: string
  allow_contact_escalation: boolean
  allow_authority_escalation: boolean
  escalation_summary: string
  manual_location?: string
  created_at: string
  expires_at: string
  remaining_seconds: number
  reminder_sent?: boolean
  escalation_outcome?: {
    user_notified?: boolean
    contacts_attempted?: boolean
    contact_results?: Array<{ contact_id: string; name: string; status: string }>
    authority_case_created?: string | null
  } | null
}

const RELATIONSHIPS = [
  { id: 'family', en: 'Family', hi: 'परिवार' },
  { id: 'parent', en: 'Parent', hi: 'माता/पिता' },
  { id: 'sibling', en: 'Sibling', hi: 'भाई/बहन' },
  { id: 'spouse_partner', en: 'Partner / Spouse', hi: 'जीवनसाथी' },
  { id: 'friend', en: 'Friend', hi: 'मित्र' },
  { id: 'colleague', en: 'Colleague', hi: 'सहकर्मी' },
  { id: 'neighbor', en: 'Neighbor', hi: 'पड़ोसी' },
  { id: 'counselor', en: 'Counselor', hi: 'परामर्शदाता' },
  { id: 'other', en: 'Other', hi: 'अन्य' },
]

function formatCountdown(secs: number): string {
  const s = Math.max(0, Math.floor(secs))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rem = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(rem).padStart(2, '0')}s`
  return `${String(m).padStart(2, '0')}:${String(rem).padStart(2, '0')}`
}

export default function SafeContactsAndCheckinPage() {
  useHavenAuth()
  const { user, isLoaded } = useUser()
  const { lang } = useLang()
  const isHi = lang === 'hi'
  const userId = isLoaded ? user?.id : undefined

  const [tab, setTab] = useState<'contacts' | 'checkin'>('contacts')
  const [banner, setBanner] = useState<{ kind: 'ok' | 'warn' | 'err'; text: string } | null>(null)

  // Trusted contacts state
  const [contacts, setContacts] = useState<TrustedContact[]>([])
  const [contactHistory, setContactHistory] = useState<ContactHistoryEntry[]>([])
  const [loadingContacts, setLoadingContacts] = useState(true)
  const [newForm, setNewForm] = useState({ name: '', phone: '', email: '', relationship: 'family', priority: 1 })
  const [savingAdd, setSavingAdd] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ name: '', phone: '', email: '', relationship: 'family', priority: 1 })
  const [savingEdit, setSavingEdit] = useState(false)

  // Notify panel
  const [notifyConsent, setNotifyConsent] = useState(false)
  const [notifySummary, setNotifySummary] = useState('Emergency assistance needed — please check on me.')
  const [notifyLocation, setNotifyLocation] = useState('')
  const [notifyIncludeLoc, setNotifyIncludeLoc] = useState(true)
  const [notifying, setNotifying] = useState(false)
  const [notifyResult, setNotifyResult] = useState<{
    reference: string
    deliveries: Array<{ contact_id: string; name: string; status: string }>
    whatsapp_links: Array<{ name: string; url: string }>
  } | null>(null)

  // Check-in timer state
  const [activeCheckin, setActiveCheckin] = useState<CheckinRecord | null>(null)
  const [checkinHistory, setCheckinHistory] = useState<CheckinRecord[]>([])
  const [loadingCheckin, setLoadingCheckin] = useState(true)
  const [durationMins, setDurationMins] = useState(30)
  const [reminderMins, setReminderMins] = useState(5)
  const [activityLabel, setActivityLabel] = useState('')
  const [checkinLocation, setCheckinLocation] = useState('')
  const [checkinCoords, setCheckinCoords] = useState<{ lat: number; lng: number } | null>(null)
  const [consentAck, setConsentAck] = useState(false)
  const [allowContactEsc, setAllowContactEsc] = useState(false)
  const [allowAuthorityEsc, setAllowAuthorityEsc] = useState(false)
  const [checkinBusy, setCheckinBusy] = useState(false)
  const [liveRemaining, setLiveRemaining] = useState<number>(0)
  const lastZeroSyncRef = useRef<number>(0)

  const showBanner = (kind: 'ok' | 'warn' | 'err', text: string) => {
    setBanner({ kind, text })
  }

  const loadContacts = useCallback(async (silent = false) => {
    if (!userId) return
    if (!silent) setLoadingContacts(true)
    try {
      const [cRes, hRes] = await Promise.all([
        secureFetch(`/trusted-contacts/${encodeURIComponent(userId)}`),
        secureFetch(`/trusted-contacts/history/${encodeURIComponent(userId)}`),
      ])
      if (cRes.ok) {
        const d = await cRes.json()
        setContacts(Array.isArray(d.contacts) ? d.contacts : [])
      }
      if (hRes.ok) {
        const h = await hRes.json()
        setContactHistory(Array.isArray(h.history) ? h.history : [])
      }
    } catch {
      if (!silent) showBanner('err', 'Could not reach server to load contacts.')
    } finally {
      if (!silent) setLoadingContacts(false)
    }
  }, [userId])

  const loadCheckins = useCallback(async (silent = false) => {
    if (!userId) return
    if (!silent) setLoadingCheckin(true)
    try {
      const [aRes, hRes] = await Promise.all([
        secureFetch('/check-in/active'),
        secureFetch('/check-in/history?limit=15'),
      ])
      if (aRes.ok) {
        const d = await aRes.json()
        setActiveCheckin(d.checkin || null)
        if (d.checkin) setLiveRemaining(d.checkin.remaining_seconds || 0)
      }
      if (hRes.ok) {
        const h = await hRes.json()
        setCheckinHistory(Array.isArray(h.checkins) ? h.checkins : [])
      }
    } catch {
      /* handled softly */
    } finally {
      if (!silent) setLoadingCheckin(false)
    }
  }, [userId])

  useEffect(() => {
    if (!userId) return
    loadContacts()
    loadCheckins()
  }, [userId, loadContacts, loadCheckins])

  // Countdown tick based on authoritative backend expires_at
  useEffect(() => {
    if (!activeCheckin || activeCheckin.status !== 'ACTIVE') return
    lastZeroSyncRef.current = 0
    const calc = () => {
      const parsedExp = parseServerDate(activeCheckin.expires_at)
      const diff = parsedExp
        ? Math.max(0, Math.floor((parsedExp.getTime() - Date.now()) / 1000))
        : Math.max(0, Math.floor(activeCheckin.remaining_seconds || 0))
      setLiveRemaining(diff)
      if (diff === 0) {
        const nowMs = Date.now()
        if (nowMs - lastZeroSyncRef.current >= 10_000) {
          lastZeroSyncRef.current = nowMs
          // Re-sync silently with backend escalation sweeper when timer hits 0
          loadCheckins(true)
        }
      }
    }
    calc()
    const iv = setInterval(calc, 1000)
    return () => clearInterval(iv)
  }, [activeCheckin, loadCheckins])

  const handleAddContact = async (e: React.FormEvent) => {
    e.preventDefault()
    if (savingAdd) return
    setSavingAdd(true)
    setBanner(null)
    try {
      const res = await secureFetch('/trusted-contacts/add', {
        method: 'POST',
        body: JSON.stringify(newForm),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Failed to add trusted contact.')
        return
      }
      setContacts(data.contacts || [])
      setNewForm({ name: '', phone: '', email: '', relationship: 'family', priority: Math.min(5, (data.contacts?.length || 0) + 1) })
      showBanner('ok', isHi ? 'विश्वसनीय संपर्क सहेजा गया।' : 'Trusted contact saved.')
      loadContacts()
    } catch {
      showBanner('err', 'Network error while saving contact.')
    } finally {
      setSavingAdd(false)
    }
  }

  const startEdit = (c: TrustedContact) => {
    setEditingId(c.contact_id)
    setEditForm({
      name: c.name,
      phone: c.phone,
      email: c.email || '',
      relationship: c.relationship || 'other',
      priority: c.priority || 1,
    })
  }

  const handleSaveEdit = async (contactId: string) => {
    setSavingEdit(true)
    setBanner(null)
    try {
      const res = await secureFetch(`/trusted-contacts/${encodeURIComponent(contactId)}`, {
        method: 'PATCH',
        body: JSON.stringify(editForm),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Failed to update contact.')
        return
      }
      setEditingId(null)
      setContacts(data.contacts || [])
      showBanner('ok', isHi ? 'संपर्क अपडेट किया गया।' : 'Contact updated.')
      loadContacts()
    } catch {
      showBanner('err', 'Network error while updating contact.')
    } finally {
      setSavingEdit(false)
    }
  }

  const handleDelete = async (contact: TrustedContact) => {
    if (!window.confirm(`Remove ${contact.name} from your trusted contacts?`)) return
    setBanner(null)
    try {
      const res = await secureFetch(`/trusted-contacts/${encodeURIComponent(contact.contact_id)}`, { method: 'DELETE' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Could not remove contact.')
        return
      }
      setContacts(data.contacts || [])
      showBanner('ok', `Removed ${contact.name}.`)
      loadContacts()
    } catch {
      showBanner('err', 'Network error removing contact.')
    }
  }

  const handleVerify = async (contact: TrustedContact, mode: 'confirm_manual' | 'send_sms_otp') => {
    setBanner(null)
    try {
      const res = await secureFetch(`/trusted-contacts/${encodeURIComponent(contact.contact_id)}/verify`, {
        method: 'POST',
        body: JSON.stringify({ mode, manual_verified: true }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Verification request failed.')
        return
      }
      if (mode === 'send_sms_otp' && data.sms_configured === false) {
        showBanner('warn', data.message || 'SMS provider not configured. Confirm manually after checking with your contact.')
      } else {
        showBanner('ok', `${contact.name} verification status updated.`)
      }
      if (Array.isArray(data.contacts)) setContacts(data.contacts)
      loadContacts()
    } catch {
      showBanner('err', 'Network error verifying contact.')
    }
  }

  const handleSendEmergencyNotice = async () => {
    if (!notifyConsent || notifying) return
    setNotifying(true)
    setBanner(null)
    setNotifyResult(null)
    try {
      const res = await secureFetch('/trusted-contacts/notify', {
        method: 'POST',
        body: JSON.stringify({
          include_location: notifyIncludeLoc,
          location_text: notifyLocation.trim(),
          incident_summary: notifySummary.trim(),
          explicit_consent: true,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Could not dispatch contact notifications.')
        return
      }
      setNotifyResult({
        reference: data.reference,
        deliveries: data.deliveries || [],
        whatsapp_links: data.whatsapp_links || [],
      })
      loadContacts()
    } catch {
      showBanner('err', 'Network error notifying contacts.')
    } finally {
      setNotifying(false)
    }
  }

  const captureCheckinGPS = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCheckinCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude })
        setCheckinLocation(`${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}`)
      },
      () => showBanner('warn', 'Could not read GPS — enter landmark manually if desired.'),
      { enableHighAccuracy: true, timeout: 8000 }
    )
  }

  const handleStartCheckin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!consentAck || checkinBusy) return
    setCheckinBusy(true)
    setBanner(null)
    try {
      const res = await secureFetch('/check-in', {
        method: 'POST',
        body: JSON.stringify({
          duration_minutes: durationMins,
          reminder_before_minutes: reminderMins,
          activity_label: activityLabel.trim(),
          consent_acknowledged: true,
          allow_contact_escalation: allowContactEsc,
          allow_authority_escalation: allowAuthorityEsc,
          manual_location: checkinLocation.trim(),
          latitude: checkinCoords?.lat ?? null,
          longitude: checkinCoords?.lng ?? null,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Could not start safety check-in.')
        return
      }
      setActiveCheckin(data.checkin)
      setLiveRemaining(data.checkin?.remaining_seconds || durationMins * 60)
      showBanner('ok', isHi ? 'सुरक्षा चेक-इन टाइमर प्रारंभ हुआ (बैकएंड में सहेजा गया)।' : 'Safety check-in timer started on backend.')
      loadCheckins()
    } catch {
      showBanner('err', 'Network error starting safety check-in.')
    } finally {
      setCheckinBusy(false)
    }
  }

  const checkinAction = async (kind: 'confirm-safe' | 'cancel' | 'extend') => {
    if (!activeCheckin || checkinBusy) return
    setCheckinBusy(true)
    setBanner(null)
    try {
      const res = await secureFetch(`/check-in/${encodeURIComponent(activeCheckin.checkin_id)}/${kind}`, {
        method: 'POST',
        body: kind === 'extend' ? JSON.stringify({ extra_minutes: 15 }) : JSON.stringify({}),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        showBanner('err', data?.detail || 'Check-in action failed.')
        return
      }
      showBanner(
        'ok',
        kind === 'confirm-safe'
          ? 'Marked safe! Timer completed.'
          : kind === 'cancel'
            ? 'Check-in cancelled.'
            : 'Timer extended by 15 minutes.'
      )
      await loadCheckins()
    } catch {
      showBanner('err', 'Network error updating check-in.')
    } finally {
      setCheckinBusy(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(145deg, #fdf2f8 0%, #f5f0ff 55%, #fce7f3 100%)', paddingBottom: 48 }}>
      <header style={{ background: 'rgba(253,242,248,0.95)', borderBottom: '1px solid rgba(190,24,93,0.12)', padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0, zIndex: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/dashboard" style={{ color: '#be185d', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: '0.88rem' }}>
            <ArrowLeft size={18} /> {isHi ? 'डैशबोर्ड' : 'Dashboard'}
          </Link>
        </div>
        <div style={{ fontFamily: 'Georgia, serif', fontWeight: 700, color: '#be185d', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: 6 }}>
          <Shield size={18} /> {isHi ? 'संपर्क और चेक-इन' : 'Trusted Contacts & Check-In'}
        </div>
        <LanguageSelector compact />
      </header>

      <main style={{ maxWidth: 880, margin: '0 auto', padding: '20px 16px' }}>
        {/* Navigation tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 18, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => setTab('contacts')}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 7,
              padding: '10px 16px', borderRadius: 10, fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer',
              background: tab === 'contacts' ? '#be185d' : 'white',
              color: tab === 'contacts' ? 'white' : '#be185d',
              border: '1px solid rgba(190,24,93,0.22)',
            }}
          >
            <Users size={16} /> {isHi ? `विश्वसनीय संपर्क (${contacts.length}/5)` : `Trusted Contacts (${contacts.length}/5)`}
          </button>
          <button
            type="button"
            onClick={() => setTab('checkin')}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 7,
              padding: '10px 16px', borderRadius: 10, fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer',
              background: tab === 'checkin' ? '#be185d' : 'white',
              color: tab === 'checkin' ? 'white' : '#be185d',
              border: '1px solid rgba(190,24,93,0.22)',
            }}
          >
            <Clock size={16} /> {isHi ? 'आपातकालीन चेक-इन टाइमर' : 'Safety Check-In Timer'}
            {activeCheckin?.status === 'ACTIVE' && (
              <span style={{ background: '#dcfce7', color: '#166534', padding: '1px 7px', borderRadius: 999, fontSize: '0.7rem' }}>
                ACTIVE
              </span>
            )}
          </button>
        </div>

        {banner && (
          <div
            role="status"
            style={{
              marginBottom: 16, padding: '11px 14px', borderRadius: 10, fontSize: '0.84rem', fontWeight: 600,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
              background: banner.kind === 'ok' ? '#f0fdf4' : banner.kind === 'warn' ? '#fffbeb' : '#fef2f2',
              color: banner.kind === 'ok' ? '#166534' : banner.kind === 'warn' ? '#92400e' : '#b91c1c',
              border: `1px solid ${banner.kind === 'ok' ? '#86efac' : banner.kind === 'warn' ? '#fcd34d' : '#fecaca'}`,
            }}
          >
            <span>{banner.text}</span>
            <button type="button" onClick={() => setBanner(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>
              <X size={15} />
            </button>
          </div>
        )}

        {tab === 'contacts' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* Saved contacts list */}
            <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)', boxShadow: '0 2px 12px rgba(190,24,93,0.06)' }}>
              <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.15rem', margin: '0 0 12px', color: '#1a0a12' }}>
                {isHi ? 'सहेजे गए विश्वसनीय संपर्क' : 'Your Trusted Contacts'}
              </h2>
              {loadingContacts ? (
                <div style={{ color: '#8b6b7d', fontSize: '0.85rem' }}>Loading contacts…</div>
              ) : contacts.length === 0 ? (
                <div style={{ padding: 14, borderRadius: 10, background: '#fdf2f8', color: '#8b6b7d', fontSize: '0.84rem' }}>
                  No trusted contacts added yet. Add up to 5 people below.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {contacts.map((c) => (
                    <div key={c.contact_id} style={{ border: '1px solid #f1e4ec', borderRadius: 12, padding: 14 }}>
                      {editingId === c.contact_id ? (
                        <div style={{ display: 'grid', gap: 8 }}>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
                            <input
                              value={editForm.name}
                              onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                              placeholder="Name"
                              style={{ padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                            />
                            <input
                              value={editForm.phone}
                              onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                              placeholder="Phone"
                              style={{ padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                            />
                            <input
                              value={editForm.email}
                              onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                              placeholder="Email (optional)"
                              style={{ padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                            />
                            <select
                              value={editForm.relationship}
                              onChange={(e) => setEditForm({ ...editForm, relationship: e.target.value })}
                              style={{ padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem', background: 'white' }}
                            >
                              {RELATIONSHIPS.map((r) => (
                                <option key={r.id} value={r.id}>{isHi ? r.hi : r.en}</option>
                              ))}
                            </select>
                            <select
                              value={editForm.priority}
                              onChange={(e) => setEditForm({ ...editForm, priority: Number(e.target.value) })}
                              style={{ padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem', background: 'white' }}
                            >
                              {[1, 2, 3, 4, 5].map((p) => (
                                <option key={p} value={p}>Priority {p}</option>
                              ))}
                            </select>
                          </div>
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button
                              type="button"
                              disabled={savingEdit}
                              onClick={() => handleSaveEdit(c.contact_id)}
                              style={{ padding: '7px 14px', borderRadius: 8, border: 'none', background: '#be185d', color: 'white', fontWeight: 700, fontSize: '0.8rem', cursor: 'pointer' }}
                            >
                              {savingEdit ? 'Saving…' : 'Save Changes'}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingId(null)}
                              style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#4b3540', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              <strong style={{ color: '#1a0a12', fontSize: '0.95rem' }}>{c.name}</strong>
                              <span style={{ fontSize: '0.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: '#fce7f3', color: '#be185d' }}>
                                Priority {c.priority || 1}
                              </span>
                              <span style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, background: '#f3f4f6', color: '#374151', textTransform: 'capitalize' }}>
                                {(c.relationship || 'other').replace(/_/g, ' ')}
                              </span>
                              <span
                                style={{
                                  fontSize: '0.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: 999,
                                  background: c.verification_status === 'VERIFIED' ? '#dcfce7' : '#fef3c7',
                                  color: c.verification_status === 'VERIFIED' ? '#166534' : '#92400e',
                                }}
                              >
                                {c.verification_status || 'UNVERIFIED'}
                              </span>
                            </div>
                            <div style={{ fontSize: '0.82rem', color: '#4b3540', marginTop: 4 }}>
                              {c.phone}{c.email ? ` · ${c.email}` : ''}
                            </div>
                          </div>

                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {c.verification_status !== 'VERIFIED' && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => handleVerify(c, 'confirm_manual')}
                                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #86efac', background: '#f0fdf4', color: '#166534', fontSize: '0.74rem', fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                >
                                  <Check size={13} /> Confirm Verified
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleVerify(c, 'send_sms_otp')}
                                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#4b3540', fontSize: '0.74rem', fontWeight: 600, cursor: 'pointer' }}
                                >
                                  Test SMS Check
                                </button>
                              </>
                            )}
                            <button
                              type="button"
                              onClick={() => startEdit(c)}
                              aria-label={`Edit ${c.name}`}
                              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(190,24,93,0.2)', background: '#fdf2f8', color: '#be185d', fontSize: '0.74rem', fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                            >
                              <Edit3 size={13} /> Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDelete(c)}
                              aria-label={`Remove ${c.name}`}
                              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #fecaca', background: '#fef2f2', color: '#b91c1c', fontSize: '0.74rem', fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                            >
                              <Trash2 size={13} /> Remove
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Add contact form */}
            {contacts.length < 5 && (
              <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)' }}>
                <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.1rem', margin: '0 0 12px', color: '#1a0a12' }}>
                  {isHi ? 'नया विश्वसनीय संपर्क जोड़ें' : 'Add Trusted Contact'}
                </h2>
                <form onSubmit={handleAddContact} style={{ display: 'grid', gap: 10 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
                    <input
                      required
                      value={newForm.name}
                      onChange={(e) => setNewForm({ ...newForm, name: e.target.value })}
                      placeholder={isHi ? 'पूरा नाम *' : 'Full Name *'}
                      style={{ padding: 10, borderRadius: 9, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem' }}
                    />
                    <input
                      required
                      type="tel"
                      value={newForm.phone}
                      onChange={(e) => setNewForm({ ...newForm, phone: e.target.value })}
                      placeholder={isHi ? 'फ़ोन (10 अंक या +91...) *' : 'Phone (e.g. 9876543210) *'}
                      style={{ padding: 10, borderRadius: 9, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem' }}
                    />
                    <input
                      type="email"
                      value={newForm.email}
                      onChange={(e) => setNewForm({ ...newForm, email: e.target.value })}
                      placeholder="Email (optional)"
                      style={{ padding: 10, borderRadius: 9, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem' }}
                    />
                    <select
                      aria-label="Relationship"
                      value={newForm.relationship}
                      onChange={(e) => setNewForm({ ...newForm, relationship: e.target.value })}
                      style={{ padding: 10, borderRadius: 9, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem', background: 'white' }}
                    >
                      {RELATIONSHIPS.map((r) => (
                        <option key={r.id} value={r.id}>{isHi ? r.hi : r.en}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Contact Priority"
                      value={newForm.priority}
                      onChange={(e) => setNewForm({ ...newForm, priority: Number(e.target.value) })}
                      style={{ padding: 10, borderRadius: 9, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem', background: 'white' }}
                    >
                      {[1, 2, 3, 4, 5].map((p) => (
                        <option key={p} value={p}>Priority {p} {p === 1 ? '(Primary)' : ''}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="submit"
                    disabled={savingAdd}
                    style={{ justifySelf: 'start', display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 18px', borderRadius: 10, border: 'none', background: '#be185d', color: 'white', fontWeight: 700, fontSize: '0.86rem', cursor: 'pointer' }}
                  >
                    <Plus size={16} /> {savingAdd ? 'Adding…' : (isHi ? 'संपर्क जोड़ें' : 'Add Contact')}
                  </button>
                </form>
              </section>
            )}

            {/* Notify Trusted Contacts (Consented + Honest Delivery Status) */}
            {contacts.length > 0 && (
              <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)' }}>
                <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.08rem', margin: '0 0 8px', color: '#1a0a12', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Send size={16} style={{ color: '#be185d' }} /> Notify Trusted Contacts
                </h2>
                <p style={{ fontSize: '0.78rem', color: '#6b5563', margin: '0 0 12px', lineHeight: 1.5 }}>
                  Only user-approved details and location are shared. Delivery is tracked honestly from the SMS provider; WhatsApp deep links are prepared as fallback if Twilio is unconfigured.
                </p>
                <div style={{ display: 'grid', gap: 10 }}>
                  <input
                    value={notifySummary}
                    onChange={(e) => setNotifySummary(e.target.value)}
                    placeholder="User-approved alert summary"
                    style={{ padding: 10, borderRadius: 9, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                  />
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <input
                      value={notifyLocation}
                      onChange={(e) => setNotifyLocation(e.target.value)}
                      placeholder="User-approved location / landmark (optional)"
                      style={{ flex: 1, minWidth: 200, padding: 10, borderRadius: 9, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                    />
                    <label style={{ fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                      <input type="checkbox" checked={notifyIncludeLoc} onChange={(e) => setNotifyIncludeLoc(e.target.checked)} />
                      Include location
                    </label>
                  </div>
                  <label style={{ fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: '#1a0a12' }}>
                    <input type="checkbox" checked={notifyConsent} onChange={(e) => setNotifyConsent(e.target.checked)} />
                    <span>I explicitly authorize sharing these approved alert details with my trusted contacts right now.</span>
                  </label>
                  <button
                    type="button"
                    disabled={!notifyConsent || notifying}
                    onClick={handleSendEmergencyNotice}
                    style={{
                      justifySelf: 'start', padding: '10px 18px', borderRadius: 10, border: 'none',
                      background: !notifyConsent ? '#d1d5db' : '#dc2626', color: 'white',
                      fontWeight: 700, fontSize: '0.85rem', cursor: !notifyConsent ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {notifying ? 'Sending…' : 'Send Notification'}
                  </button>

                  {notifyResult && (
                    <div style={{ padding: 12, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0', fontSize: '0.8rem' }}>
                      <div style={{ fontWeight: 700, marginBottom: 6 }}>Reference: {notifyResult.reference}</div>
                      {notifyResult.deliveries.map((d, i) => (
                        <div key={d.contact_id || i} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}>
                          <span>{d.name}</span>
                          <strong style={{ color: d.status === 'SENT_TO_PROVIDER' || d.status === 'QUEUED' ? '#15803d' : '#b45309' }}>
                            {d.status === 'NOT_CONFIGURED' ? 'SMS NOT_CONFIGURED (Use WhatsApp below)' : d.status}
                          </strong>
                        </div>
                      ))}
                      {notifyResult.whatsapp_links.length > 0 && (
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                          {notifyResult.whatsapp_links.map((w, i) => (
                            <a
                              key={i}
                              href={w.url}
                              target="_blank"
                              rel="noreferrer noopener"
                              style={{ padding: '6px 12px', borderRadius: 8, background: '#16a34a', color: 'white', fontWeight: 700, fontSize: '0.76rem', textDecoration: 'none' }}
                            >
                              Open WhatsApp: {w.name}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Contact management history */}
            <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)' }}>
              <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.05rem', margin: '0 0 10px', color: '#1a0a12', display: 'flex', alignItems: 'center', gap: 6 }}>
                <History size={16} style={{ color: '#be185d' }} /> Contact Management History
              </h2>
              {contactHistory.length === 0 ? (
                <p style={{ fontSize: '0.82rem', color: '#8b6b7d', margin: 0 }}>No contact activity recorded yet.</p>
              ) : (
                <div style={{ display: 'grid', gap: 8 }}>
                  {contactHistory.slice(0, 12).map((h) => (
                    <div key={h.history_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 0', borderBottom: '1px solid #f3e8ee', fontSize: '0.78rem' }}>
                      <div>
                        <strong style={{ color: '#1a0a12' }}>{h.action}</strong> · {h.contact_name}
                        {h.details ? <span style={{ color: '#6b5563' }}> — {h.details}</span> : null}
                      </div>
                      <span style={{ color: '#8b6b7d', whiteSpace: 'nowrap' }}>{formatServerDateTime(h.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {tab === 'checkin' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* Active timer panel */}
            {loadingCheckin ? (
              <div style={{ background: 'white', borderRadius: 16, padding: 20, color: '#8b6b7d' }}>Loading check-in timer…</div>
            ) : activeCheckin && activeCheckin.status === 'ACTIVE' ? (
              <section style={{ background: 'white', borderRadius: 16, padding: 22, border: '2px solid #be185d', boxShadow: '0 4px 20px rgba(190,24,93,0.1)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                  <div>
                    <span style={{ fontSize: '0.72rem', fontWeight: 800, padding: '2px 9px', borderRadius: 999, background: '#dcfce7', color: '#166534' }}>
                      PERSISTENT BACKEND TIMER ACTIVE
                    </span>
                    <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.25rem', margin: '8px 0 4px', color: '#1a0a12' }}>
                      {activeCheckin.activity_label || 'Safety Check-In Timer'}
                    </h2>
                    <div style={{ fontSize: '0.8rem', color: '#6b5563' }}>
                      Deadline: {formatServerDateTime(activeCheckin.expires_at)}
                    </div>
                  </div>
                  <div style={{ fontFamily: 'monospace', fontSize: '2rem', fontWeight: 900, color: liveRemaining < 120 ? '#dc2626' : '#be185d' }}>
                    {formatCountdown(liveRemaining)}
                  </div>
                </div>

                <div style={{ marginTop: 12, padding: 10, borderRadius: 10, background: '#fdf2f8', fontSize: '0.78rem', color: '#4b3540' }}>
                  <strong>Configured Escalation Rule:</strong> {activeCheckin.escalation_summary}
                  {activeCheckin.manual_location ? <div><strong>Shared Note/Location:</strong> {activeCheckin.manual_location}</div> : null}
                </div>

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
                  <button
                    type="button"
                    disabled={checkinBusy}
                    onClick={() => checkinAction('confirm-safe')}
                    style={{ padding: '11px 18px', borderRadius: 10, border: 'none', background: '#16a34a', color: 'white', fontWeight: 800, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                  >
                    <CheckCircle2 size={16} /> I Am Safe (Complete)
                  </button>
                  <button
                    type="button"
                    disabled={checkinBusy}
                    onClick={() => checkinAction('extend')}
                    style={{ padding: '11px 16px', borderRadius: 10, border: '1px solid rgba(190,24,93,0.25)', background: 'white', color: '#be185d', fontWeight: 700, cursor: 'pointer' }}
                  >
                    +15 Minutes
                  </button>
                  <button
                    type="button"
                    disabled={checkinBusy}
                    onClick={() => checkinAction('cancel')}
                    style={{ padding: '11px 16px', borderRadius: 10, border: '1px solid #fecaca', background: '#fef2f2', color: '#b91c1c', fontWeight: 700, cursor: 'pointer' }}
                  >
                    Cancel Timer
                  </button>
                </div>
              </section>
            ) : (
              <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)' }}>
                <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.15rem', margin: '0 0 8px', color: '#1a0a12' }}>
                  {isHi ? 'नया सुरक्षा चेक-इन टाइमर सेट करें' : 'Start Emergency Check-In Timer'}
                </h2>
                <p style={{ fontSize: '0.8rem', color: '#6b5563', margin: '0 0 14px', lineHeight: 1.55 }}>
                  Stored securely on HAVEN&apos;s backend scheduler — survives closing your browser or logging out. Nobody is contacted automatically unless you enable that escalation rule below.
                </p>
                <form onSubmit={handleStartCheckin} style={{ display: 'grid', gap: 12 }}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 700 }}>Duration:</span>
                    {[15, 30, 60, 120].map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setDurationMins(m)}
                        style={{
                          padding: '6px 12px', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: '0.8rem',
                          background: durationMins === m ? '#be185d' : '#fdf2f8',
                          color: durationMins === m ? 'white' : '#be185d',
                          border: '1px solid rgba(190,24,93,0.2)',
                        }}
                      >
                        {m} min
                      </button>
                    ))}
                    <input
                      type="number"
                      min={5}
                      max={720}
                      value={durationMins}
                      onChange={(e) => setDurationMins(Math.max(5, Math.min(720, Number(e.target.value) || 15)))}
                      aria-label="Custom duration minutes"
                      style={{ width: 84, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                    />
                    <span style={{ fontSize: '0.78rem', color: '#6b5563' }}>minutes</span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                    <input
                      value={activityLabel}
                      onChange={(e) => setActivityLabel(e.target.value)}
                      placeholder="Trip / activity (e.g. Late commute home)"
                      style={{ padding: 10, borderRadius: 9, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                    />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        value={checkinLocation}
                        onChange={(e) => setCheckinLocation(e.target.value)}
                        placeholder="Optional landmark or coordinates"
                        style={{ flex: 1, padding: 10, borderRadius: 9, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
                      />
                      <button
                        type="button"
                        onClick={captureCheckinGPS}
                        style={{ padding: '8px 12px', borderRadius: 9, border: '1px solid rgba(190,24,93,0.2)', background: '#fdf2f8', color: '#be185d', fontWeight: 700, fontSize: '0.76rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                      >
                        <MapPin size={14} /> GPS
                      </button>
                    </div>
                  </div>

                  <div style={{ background: '#fdf2f8', borderRadius: 12, padding: 12, display: 'grid', gap: 8, fontSize: '0.82rem' }}>
                    <div style={{ fontWeight: 700, color: '#be185d', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <ShieldAlert size={15} /> Expiry Escalation Preferences &amp; Consent
                    </div>
                    <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                      <input type="checkbox" checked={allowContactEsc} onChange={(e) => setAllowContactEsc(e.target.checked)} />
                      <span>If timer expires, attempt SMS alert to my trusted contacts (when SMS provider is configured)</span>
                    </label>
                    <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                      <input type="checkbox" checked={allowAuthorityEsc} onChange={(e) => setAllowAuthorityEsc(e.target.checked)} />
                      <span>If timer expires, raise a missed check-in alert on the HAVEN authority queue</span>
                    </label>
                    <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer', fontWeight: 700, color: '#1a0a12' }}>
                      <input type="checkbox" checked={consentAck} onChange={(e) => setConsentAck(e.target.checked)} required style={{ marginTop: 3 }} />
                      <span>
                        I consent to starting this check-in timer and understand that a reminder will be sent {reminderMins}m before expiry and my selected escalation actions will run if I do not confirm safe before the deadline.
                      </span>
                    </label>
                  </div>

                  <button
                    type="submit"
                    disabled={!consentAck || checkinBusy}
                    style={{
                      justifySelf: 'start', padding: '11px 20px', borderRadius: 10, border: 'none',
                      background: !consentAck ? '#d1d5db' : '#be185d', color: 'white', fontWeight: 800, fontSize: '0.88rem', cursor: !consentAck ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {checkinBusy ? 'Starting…' : 'Start Check-In Timer'}
                  </button>
                </form>
              </section>
            )}

            {/* Check-in history */}
            <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid rgba(190,24,93,0.12)' }}>
              <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.05rem', margin: '0 0 10px', color: '#1a0a12' }}>
                Check-In History
              </h2>
              {checkinHistory.length === 0 ? (
                <p style={{ fontSize: '0.82rem', color: '#8b6b7d', margin: 0 }}>No previous check-ins recorded.</p>
              ) : (
                <div style={{ display: 'grid', gap: 8 }}>
                  {checkinHistory.map((chk) => (
                    <div key={chk.checkin_id} style={{ border: '1px solid #f1e4ec', borderRadius: 10, padding: 10, fontSize: '0.8rem', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                      <div>
                        <strong>{chk.activity_label || chk.checkin_id}</strong> ({chk.duration_minutes}m)
                        <div style={{ fontSize: '0.74rem', color: '#6b5563' }}>
                          Started: {formatServerDateTime(chk.created_at)} · Rule: {chk.escalation_summary}
                        </div>
                        {chk.escalation_outcome?.authority_case_created && (
                          <div style={{ fontSize: '0.74rem', color: '#b91c1c', fontWeight: 700 }}>
                            Escalated Case: {chk.escalation_outcome.authority_case_created}
                          </div>
                        )}
                        {Array.isArray(chk.escalation_outcome?.contact_results) && chk.escalation_outcome!.contact_results!.length > 0 && (
                          <div style={{ fontSize: '0.72rem', color: '#6b5563', marginTop: 2 }}>
                            SMS Escalation:{' '}
                            {chk.escalation_outcome!.contact_results!.map((cr) => `${cr.name} (${cr.status})`).join(', ')}
                          </div>
                        )}
                      </div>
                      <span
                        style={{
                          alignSelf: 'center', fontSize: '0.7rem', fontWeight: 800, padding: '3px 9px', borderRadius: 999,
                          background: chk.status === 'CONFIRMED_SAFE' ? '#dcfce7' : chk.status === 'ESCALATED' ? '#fee2e2' : chk.status === 'ACTIVE' ? '#fef3c7' : '#f4f4f5',
                          color: chk.status === 'CONFIRMED_SAFE' ? '#166534' : chk.status === 'ESCALATED' ? '#991b1b' : chk.status === 'ACTIVE' ? '#92400e' : '#52525b',
                        }}
                      >
                        {chk.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  )
}
