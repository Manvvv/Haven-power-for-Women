'use client'

import React, { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Shield, PlayCircle, RotateCcw, Radio, CheckCircle2,
  UserCheck, Mic, AlertTriangle, Users, FileText, Volume2, Clock,
} from 'lucide-react'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { formatServerDateTime } from '@/lib/datetime'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface DemoCase {
  case_id: string
  category: string
  description: string
  severity: string
  location: string
  status: string
  trigger_type: string
  timeline?: Array<{ status: string; actor: string; timestamp: string }>
  simulated_notifications?: Array<{ contact: string; status: string }>
  voice_analysis?: Record<string, any>
  created_at: string
}

interface DemoDispatch {
  dispatch_id: string
  case_id: string
  status: string
  responder_label: string
  distance_m: number
  response_time_seconds?: number | null
  resolution_time_seconds?: number | null
  events?: Array<{ state: string; actor: string; note: string; at: string }>
}

interface DemoState {
  connected: boolean
  is_demo: boolean
  simulation: boolean
  isolation_notice?: string
  accounts?: Record<string, { id: string; name: string; role: string }>
  cases: DemoCase[]
  dispatches: DemoDispatch[]
  responders: Array<{
    responder_id: string
    display_label: string
    provider_category: string
    status: string
    duty_status: string
    verified: boolean
    jurisdiction: string
    distance_m: number
  }>
  contacts: Array<{ contact_id: string; name: string; phone: string; relationship: string; priority: number; verification_status: string }>
  checkins: Array<{ checkin_id: string; activity_label: string; duration_minutes: number; status: string; escalation_summary: string }>
  provider_registrations: Array<{ registration_id: string; unit_name: string; organization: string; provider_category: string; status: string; responder_id?: string }>
  safety_plan?: { warning_signs?: string[]; safe_places?: string[]; things_that_help?: string[]; emergency_numbers?: string[] }
  audit_logs: Array<{ audit_id: string; actor: string; role: string; action: string; details: string; timestamp: string }>
}

const SAMPLE_VOICE_SCENARIOS = [
  {
    id: 'en_stalking',
    lang: 'en',
    label: 'English Sample — Stalking Near Metro',
    text: 'Someone has been following me since the metro station exit. I am near Rajiv Chowk Gate 2 and I need help urgently.',
  },
  {
    id: 'hi_distress',
    lang: 'hi',
    label: 'Hindi Sample — पीछा और असुरक्षित स्थिति',
    text: 'कोई बस स्टैंड के पास मेरा पीछा कर रहा है। मुझे तुरंत मदद चाहिए।',
  },
]

export default function DemoModePage() {
  useHavenAuth()
  const { lang } = useLang()
  const isHi = lang === 'hi'

  const [state, setState] = useState<DemoState | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'sos_flow' | 'voice_flow' | 'admin_flow' | 'samples'>('sos_flow')

  // Workflow 1: SOS input
  const [sosCat, setSosCat] = useState('stalking')
  const [sosDesc, setSosDesc] = useState('Someone is following me near the metro station after evening class.')
  const [sosLoc, setSosLoc] = useState('28.6328, 77.2197 (Demo Metro Gate 2)')
  const [activeCaseId, setActiveCaseId] = useState<string>('')

  // Workflow 2: Voice SOS demo
  const [voiceTranscript, setVoiceTranscript] = useState(SAMPLE_VOICE_SCENARIOS[0].text)
  const [voiceLang, setVoiceLang] = useState<'en' | 'hi'>('en')
  const [voiceExtracted, setVoiceExtracted] = useState<any>(null)
  const [demoVoiceCase, setDemoVoiceCase] = useState<DemoCase | null>(null)

  const loadState = useCallback(async () => {
    setError('')
    try {
      const res = await fetch(`${API}/demo/state`)
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || 'Failed to load demo workspace')
      setState(data)
      if (!activeCaseId && Array.isArray(data.cases) && data.cases.length > 0) {
        const nonResolved = data.cases.find((c: DemoCase) => c.status !== 'RESOLVED') || data.cases[0]
        setActiveCaseId(nonResolved.case_id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backend unavailable — ensure FastAPI backend is running on port 8000.')
    } finally {
      setLoading(false)
    }
  }, [activeCaseId])

  useEffect(() => {
    loadState()
  }, [loadState])

  const resetSandbox = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/reset`, { method: 'POST' })
      const data = await res.json()
      if (data.state) setState(data.state)
      setActiveCaseId('')
      setVoiceExtracted(null)
      setDemoVoiceCase(null)
    } catch {
      setError('Failed to reset demo sandbox.')
    } finally {
      setBusy(false)
    }
  }

  const runDemoSos = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/sos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: sosCat, description: sosDesc, location: sosLoc }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || 'Demo SOS failed')
      setActiveCaseId(data.case.case_id)
      await loadState()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Demo SOS failed')
    } finally {
      setBusy(false)
    }
  }

  const runDemoDispatch = async (caseId: string) => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/dispatch/${encodeURIComponent(caseId)}`, { method: 'POST' })
      if (!res.ok) throw new Error('Could not create demo dispatch')
      await loadState()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Demo dispatch failed')
    } finally {
      setBusy(false)
    }
  }

  const stepDemoDispatch = async (dispatchId: string, action: string) => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/dispatch/${encodeURIComponent(dispatchId)}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      if (!res.ok) throw new Error('Could not update demo dispatch')
      await loadState()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  const playSampleVoiceAudio = (text: string, langCode: string) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(text)
    utter.lang = langCode === 'hi' ? 'hi-IN' : 'en-IN'
    utter.rate = 0.95
    window.speechSynthesis.speak(utter)
  }

  const runDemoVoiceAnalyze = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/voice-sos/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: voiceTranscript, language: voiceLang }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || 'Voice analysis failed')
      setVoiceExtracted(data)
      await loadState()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice AI extraction failed')
    } finally {
      setBusy(false)
    }
  }

  const confirmDemoVoiceIncident = async () => {
    if (!voiceExtracted) return
    setBusy(true)
    try {
      const res = await fetch(`${API}/demo/sos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: voiceExtracted.suggested_category,
          description: voiceExtracted.situation_description,
          location: voiceExtracted.mentioned_location ? `${voiceExtracted.mentioned_location} (AI Mention — Demo)` : 'Demo Location',
          trigger_type: 'demo_voice_ai_sos',
          voice_analysis: voiceExtracted,
        }),
      })
      const data = await res.json()
      if (res.ok && data.case) {
        setDemoVoiceCase(data.case)
        setActiveCaseId(data.case.case_id)
      }
      await loadState()
    } finally {
      setBusy(false)
    }
  }

  const approveDemoProvider = async (regId: string) => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API}/demo/admin/providers/${encodeURIComponent(regId)}/approve`, { method: 'POST' })
      if (!res.ok) throw new Error('Approval failed')
      await loadState()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Provider approval failed')
    } finally {
      setBusy(false)
    }
  }

  const selectedCase = state?.cases?.find((c) => c.case_id === activeCaseId) || state?.cases?.[0] || null
  const selectedDispatch = selectedCase ? state?.dispatches?.find((d) => d.case_id === selectedCase.case_id) || null : null

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(150deg, #fdf2f8 0%, #eff6ff 55%, #f5f0ff 100%)', paddingBottom: 56 }}>
      {/* Top isolation banner */}
      <div style={{ background: '#1e1b4b', color: '#e0e7ff', padding: '10px 16px', fontSize: '0.78rem', textAlign: 'center', fontWeight: 700 }}>
        🧪 ISOLATED DEMO MODE — Writes strictly to <code>demo_*</code> collections. Zero real SMS, WhatsApp, or emergency dispatches are triggered.
      </div>

      <header style={{ background: 'rgba(255,255,255,0.92)', borderBottom: '1px solid #e2e8f0', padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/home" style={{ color: '#be185d', textDecoration: 'none', fontWeight: 700, fontSize: '0.85rem', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <ArrowLeft size={16} /> Back
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontFamily: 'Georgia, serif', color: '#1a0a12', fontSize: '1.1rem' }}>
            <PlayCircle size={20} color="#6d28d9" /> {isHi ? 'HAVEN इंटरैक्टिव डेमो मोड' : 'HAVEN Guided Demo Console'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <LanguageSelector compact />
          <button
            type="button"
            disabled={busy}
            onClick={resetSandbox}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: '1px solid #c4b5fd', background: '#f5f3ff', color: '#5b21b6', fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer' }}
          >
            <RotateCcw size={14} /> Reset Demo Workspace
          </button>
        </div>
      </header>

      <main style={{ maxWidth: 1040, margin: '0 auto', padding: '20px 16px' }}>
        {error && (
          <div role="alert" style={{ marginBottom: 14, padding: 12, borderRadius: 10, background: '#fee2e2', color: '#b91c1c', fontSize: '0.84rem', fontWeight: 600 }}>
            {error}
          </div>
        )}

        {/* Simulated Account Identities */}
        {state?.accounts && (
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10, marginBottom: 18 }}>
            {Object.entries(state.accounts).map(([k, acc]) => (
              <div key={k} style={{ background: 'white', borderRadius: 12, padding: 12, border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '0.68rem', fontWeight: 800, textTransform: 'uppercase', color: '#6d28d9' }}>Demo {acc.role}</div>
                <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '0.88rem', marginTop: 2 }}>{acc.name}</div>
                <code style={{ fontSize: '0.7rem', color: '#64748b' }}>{acc.id}</code>
              </div>
            ))}
          </section>
        )}

        {/* Workflow Tabs */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 18 }}>
          {[
            ['sos_flow', '1. USER → SOS → AUTHORITY → RESPONDER → RESOLVE'],
            ['voice_flow', '2. VOICE SOS → AI EXTRACT → INCIDENT'],
            ['admin_flow', '3. ADMIN → PROVIDER APPROVAL → ACTIVATION'],
            ['samples', '4. Sample Contacts, Check-In & Audit Trail'],
          ].map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k as any)}
              style={{
                padding: '9px 13px', borderRadius: 10, fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer',
                background: tab === k ? '#6d28d9' : 'white', color: tab === k ? 'white' : '#4c1d95',
                border: '1px solid #ddd6fe',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <div style={{ background: 'white', borderRadius: 16, padding: 28, textAlign: 'center', color: '#64748b' }}>Loading demo sandbox…</div>
        ) : (
          <>
            {tab === 'sos_flow' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(310px, 1fr))', gap: 16 }}>
                {/* Step 1: Demo User submits SOS */}
                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #fbcfe8' }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 800, color: '#be185d', marginBottom: 6 }}>STEP 1 · DEMO USER PERSPECTIVE</div>
                  <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.1rem', margin: '0 0 10px' }}>Submit Simulated SOS</h2>
                  <div style={{ display: 'grid', gap: 10 }}>
                    <select value={sosCat} onChange={(e) => setSosCat(e.target.value)} style={{ padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: '0.84rem' }}>
                      <option value="stalking">Stalking / Followed</option>
                      <option value="immediate_danger">Immediate Physical Danger</option>
                      <option value="unsafe_transit">Unsafe Transit</option>
                      <option value="harassment">Harassment / Threat</option>
                    </select>
                    <textarea rows={2} value={sosDesc} onChange={(e) => setSosDesc(e.target.value)} style={{ padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: '0.84rem' }} />
                    <input value={sosLoc} onChange={(e) => setSosLoc(e.target.value)} style={{ padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: '0.84rem' }} />
                    <button
                      type="button"
                      disabled={busy}
                      onClick={runDemoSos}
                      style={{ padding: '10px 16px', borderRadius: 10, border: 'none', background: '#be185d', color: 'white', fontWeight: 800, fontSize: '0.86rem', cursor: 'pointer' }}
                    >
                      🚨 Trigger Demo SOS
                    </button>
                  </div>

                  {selectedCase && (
                    <div style={{ marginTop: 14, padding: 12, borderRadius: 10, background: '#fdf2f8', fontSize: '0.78rem' }}>
                      <div><strong>Active Demo Case:</strong> <code>{selectedCase.case_id}</code></div>
                      <div><strong>Status:</strong> <span style={{ fontWeight: 800, color: '#be185d' }}>{selectedCase.status}</span></div>
                      <div><strong>Location:</strong> {selectedCase.location}</div>
                      {selectedCase.simulated_notifications && (
                        <div style={{ marginTop: 6, color: '#6b5563' }}>
                          Simulated contacts preview: {selectedCase.simulated_notifications.map((n) => `${n.contact} (${n.status})`).join(', ')}
                        </div>
                      )}
                    </div>
                  )}
                </section>

                {/* Step 2 & 3: Demo Authority + Demo Responder */}
                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #bfdbfe' }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 800, color: '#1d4ed8', marginBottom: 6 }}>STEP 2 &amp; 3 · DEMO AUTHORITY → DEMO RESPONDER</div>
                  <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.1rem', margin: '0 0 10px' }}>Dispatch &amp; Resolution Lifecycle</h2>

                  {!selectedCase ? (
                    <p style={{ color: '#64748b', fontSize: '0.84rem' }}>Trigger a Demo SOS on the left to start dispatch.</p>
                  ) : !selectedDispatch ? (
                    <div>
                      <p style={{ fontSize: '0.82rem', color: '#334155', marginBottom: 10 }}>
                        Demo Authority reviews case <code>{selectedCase.case_id}</code> and broadcasts an offer to available Demo Responders.
                      </p>
                      <button
                        type="button"
                        disabled={busy || selectedCase.status === 'RESOLVED'}
                        onClick={() => runDemoDispatch(selectedCase.case_id)}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 16px', borderRadius: 10, border: 'none', background: '#1d4ed8', color: 'white', fontWeight: 800, fontSize: '0.86rem', cursor: 'pointer' }}
                      >
                        <Radio size={16} /> Authority: Create Demo Dispatch
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gap: 10 }}>
                      <div style={{ padding: 12, borderRadius: 10, background: '#eff6ff', fontSize: '0.8rem' }}>
                        <div><strong>Dispatch:</strong> <code>{selectedDispatch.dispatch_id}</code></div>
                        <div><strong>Current State:</strong> <strong style={{ color: '#1d4ed8' }}>{selectedDispatch.status}</strong></div>
                        <div><strong>Unit:</strong> {selectedDispatch.responder_label} ({selectedDispatch.distance_m}m away)</div>
                        {selectedDispatch.response_time_seconds != null && (
                          <div><strong>Accept time:</strong> {selectedDispatch.response_time_seconds}s</div>
                        )}
                        {selectedDispatch.resolution_time_seconds != null && (
                          <div><strong>Total resolution time:</strong> {selectedDispatch.resolution_time_seconds}s</div>
                        )}
                      </div>

                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {selectedDispatch.status === 'OFFERED' && (
                          <button type="button" disabled={busy} onClick={() => stepDemoDispatch(selectedDispatch.dispatch_id, 'accept')}
                            style={{ padding: '9px 14px', borderRadius: 9, border: 'none', background: '#16a34a', color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
                            Responder: Accept Offer
                          </button>
                        )}
                        {selectedDispatch.status === 'ACCEPTED' && (
                          <button type="button" disabled={busy} onClick={() => stepDemoDispatch(selectedDispatch.dispatch_id, 'enroute')}
                            style={{ padding: '9px 14px', borderRadius: 9, border: 'none', background: '#0284c7', color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
                            Responder: Mark En Route
                          </button>
                        )}
                        {selectedDispatch.status === 'EN_ROUTE' && (
                          <button type="button" disabled={busy} onClick={() => stepDemoDispatch(selectedDispatch.dispatch_id, 'arrived')}
                            style={{ padding: '9px 14px', borderRadius: 9, border: 'none', background: '#7c3aed', color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
                            Responder: Mark Arrived
                          </button>
                        )}
                        {selectedDispatch.status === 'ARRIVED' && (
                          <button type="button" disabled={busy} onClick={() => stepDemoDispatch(selectedDispatch.dispatch_id, 'help_provided')}
                            style={{ padding: '9px 14px', borderRadius: 9, border: 'none', background: '#059669', color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
                            Responder: Help Provided
                          </button>
                        )}
                        {selectedDispatch.status === 'HELP_PROVIDED' && (
                          <button type="button" disabled={busy} onClick={() => stepDemoDispatch(selectedDispatch.dispatch_id, 'resolve')}
                            style={{ padding: '9px 14px', borderRadius: 9, border: 'none', background: '#0f172a', color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
                            Authority: Close &amp; Resolve Case
                          </button>
                        )}
                      </div>

                      {selectedDispatch.events && (
                        <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 8 }}>
                          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#64748b', marginBottom: 4 }}>REAL-TIME DEMO TIMELINE</div>
                          {selectedDispatch.events.map((ev, i) => (
                            <div key={i} style={{ fontSize: '0.75rem', padding: '3px 0', color: '#334155' }}>
                              • <strong>{ev.state}</strong> — {ev.note} <span style={{ color: '#94a3b8' }}>({formatServerDateTime(ev.at)})</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </section>
              </div>
            )}

            {tab === 'voice_flow' && (
              <section style={{ background: 'white', borderRadius: 16, padding: 20, border: '1px solid #ddd6fe', display: 'grid', gap: 14 }}>
                <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.15rem', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Mic size={20} color="#6d28d9" /> Voice SOS → Sample Audio → Transcription → AI Extraction → Demo Incident
                </h2>

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {SAMPLE_VOICE_SCENARIOS.map((sc) => (
                    <button
                      key={sc.id}
                      type="button"
                      onClick={() => { setVoiceTranscript(sc.text); setVoiceLang(sc.lang as any); playSampleVoiceAudio(sc.text, sc.lang) }}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderRadius: 9, border: '1px solid #ddd6fe', background: '#f5f3ff', color: '#5b21b6', fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer' }}
                    >
                      <Volume2 size={14} /> Play {sc.label}
                    </button>
                  ))}
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, marginBottom: 4 }}>Sample / Editable Speech Transcript</label>
                  <textarea rows={3} value={voiceTranscript} onChange={(e) => setVoiceTranscript(e.target.value)}
                    style={{ width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 9, border: '1px solid #cbd5e1', fontSize: '0.88rem' }} />
                  <button
                    type="button"
                    disabled={busy || !voiceTranscript.trim()}
                    onClick={runDemoVoiceAnalyze}
                    style={{ marginTop: 8, padding: '9px 16px', borderRadius: 9, border: 'none', background: '#6d28d9', color: 'white', fontWeight: 700, fontSize: '0.84rem', cursor: 'pointer' }}
                  >
                    Run AI Emergency Extraction
                  </button>
                </div>

                {voiceExtracted && (
                  <div style={{ background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: 12, padding: 14, display: 'grid', gap: 8, fontSize: '0.82rem' }}>
                    <div><strong>Emergency Category:</strong> {voiceExtracted.suggested_category}</div>
                    <div><strong>Description:</strong> {voiceExtracted.situation_description}</div>
                    <div>
                      <strong>Mentioned Location:</strong> {voiceExtracted.mentioned_location || 'None mentioned'}{' '}
                      <span style={{ color: '#b45309', fontWeight: 700 }}>({voiceExtracted.location_disclaimer})</span>
                    </div>
                    <div>
                      <strong>Suggested Urgency:</strong> {voiceExtracted.suggested_urgency?.toUpperCase()}{' '}
                      <span style={{ color: '#b45309' }}>({voiceExtracted.urgency_disclaimer})</span>
                    </div>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={confirmDemoVoiceIncident}
                      style={{ justifySelf: 'start', padding: '10px 16px', borderRadius: 9, border: 'none', background: '#be185d', color: 'white', fontWeight: 800, cursor: 'pointer' }}
                    >
                      Confirm &amp; Create Demo Incident
                    </button>
                  </div>
                )}

                {demoVoiceCase && (
                  <div style={{ padding: 12, borderRadius: 10, background: '#f0fdf4', border: '1px solid #86efac', color: '#166534', fontSize: '0.84rem' }}>
                    Created isolated Demo Incident <code>{demoVoiceCase.case_id}</code>! Switch to Tab 1 to dispatch a Demo Responder for it.
                  </div>
                )}
              </section>
            )}

            {tab === 'admin_flow' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #e2e8f0' }}>
                  <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.1rem', margin: '0 0 10px', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <UserCheck size={18} color="#6d28d9" /> Demo Admin: Provider Registrations
                  </h2>
                  {state?.provider_registrations.map((reg) => (
                    <div key={reg.registration_id} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 12, marginBottom: 10, fontSize: '0.82rem' }}>
                      <div style={{ fontWeight: 700 }}>{reg.unit_name}</div>
                      <div style={{ color: '#64748b' }}>{reg.organization} · {reg.provider_category}</div>
                      <div style={{ marginTop: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 800, color: reg.status === 'APPROVED' ? '#166534' : '#b45309' }}>{reg.status}</span>
                        {reg.status === 'PENDING_REVIEW' && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => approveDemoProvider(reg.registration_id)}
                            style={{ padding: '7px 12px', borderRadius: 8, border: 'none', background: '#16a34a', color: 'white', fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer' }}
                          >
                            Approve &amp; Activate Responder
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </section>

                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #e2e8f0' }}>
                  <h2 style={{ fontFamily: 'Georgia, serif', fontSize: '1.1rem', margin: '0 0 10px' }}>Demo Responder Roster</h2>
                  {state?.responders.map((r) => (
                    <div key={r.responder_id} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 12, marginBottom: 10, fontSize: '0.82rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong>{r.display_label}</strong>
                        <span style={{ fontSize: '0.72rem', fontWeight: 800, padding: '2px 8px', borderRadius: 999, background: r.verified && r.status === 'AVAILABLE' ? '#dcfce7' : '#f1f5f9', color: r.verified && r.status === 'AVAILABLE' ? '#166534' : '#475569' }}>
                          {r.verified ? `${r.duty_status} · ${r.status}` : 'UNVERIFIED'}
                        </span>
                      </div>
                      <div style={{ color: '#64748b', marginTop: 4 }}>{r.jurisdiction} · {r.provider_category}</div>
                    </div>
                  ))}
                </section>
              </div>
            )}

            {tab === 'samples' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #e2e8f0' }}>
                  <h3 style={{ fontFamily: 'Georgia, serif', margin: '0 0 10px', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Users size={17} color="#be185d" /> Sample Trusted Contacts
                  </h3>
                  {state?.contacts.map((c) => (
                    <div key={c.contact_id} style={{ padding: '8px 0', borderBottom: '1px solid #f1f5f9', fontSize: '0.8rem' }}>
                      <strong>{c.name}</strong> ({c.relationship}) · P{c.priority}
                      <div style={{ color: '#64748b' }}>{c.phone} · {c.verification_status}</div>
                    </div>
                  ))}
                </section>

                <section style={{ background: 'white', borderRadius: 16, padding: 18, border: '1px solid #e2e8f0' }}>
                  <h3 style={{ fontFamily: 'Georgia, serif', margin: '0 0 10px', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <FileText size={17} color="#be185d" /> Sample Safety Plan &amp; Check-In
                  </h3>
                  {state?.safety_plan?.warning_signs && (
                    <div style={{ fontSize: '0.78rem', color: '#334155', marginBottom: 10 }}>
                      <strong>Warning signs:</strong> {state.safety_plan.warning_signs.join(' · ')}
                      <br />
                      <strong>Safe places:</strong> {state.safety_plan.safe_places?.join(' · ')}
                    </div>
                  )}
                  {state?.checkins.map((chk) => (
                    <div key={chk.checkin_id} style={{ padding: 8, borderRadius: 8, background: '#f8fafc', fontSize: '0.78rem' }}>
                      <Clock size={12} style={{ display: 'inline', marginRight: 4 }} />
                      <strong>{chk.activity_label}</strong> ({chk.duration_minutes}m) — {chk.status}
                    </div>
                  ))}
                </section>

                <section style={{ gridColumn: '1 / -1', background: 'white', borderRadius: 16, padding: 18, border: '1px solid #e2e8f0' }}>
                  <h3 style={{ fontFamily: 'Georgia, serif', margin: '0 0 10px' }}>Isolated Demo Audit Trail</h3>
                  {state?.audit_logs.map((a) => (
                    <div key={a.audit_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9', fontSize: '0.76rem', gap: 8 }}>
                      <span><strong>{a.action}</strong> ({a.actor}) — {a.details}</span>
                      <span style={{ color: '#94a3b8', whiteSpace: 'nowrap' }}>{formatServerDateTime(a.timestamp)}</span>
                    </div>
                  ))}
                </section>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
