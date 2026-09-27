'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { ArrowLeft, Scale, Send, Upload, BookOpen, ChevronRight, X } from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { useRole } from '@/hooks/useRole'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { secureFetch } from '@/lib/api'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Citation {
  document_id?: string
  title: string
  section?: string
  act_name?: string
  authority?: string
  authority_level?: string
  source_type?: string
  source_url?: string
  last_verified?: string
  effective_date?: string
  relevance_score?: number | null
  match_strength?: number | null
  excerpt?: string
}
interface Helpline { name: string; number: string; purpose?: string; source?: string; verified_at?: string }
interface LegalAid { note?: string; helplines?: Helpline[] }
interface Message {
  role: 'user' | 'assistant'
  content: string
  summary?: string
  sources?: Citation[]
  grounded?: boolean
  noContext?: boolean
  status?: string
  topic?: string
  jurisdiction?: string
  urgency?: string
  emergency?: boolean
  immediateDanger?: boolean
  evidenceLevel?: string
  clarifyingQuestions?: string[]
  nextSteps?: string[]
  evidenceChecklist?: string[]
  legalAid?: LegalAid
  emergencyResources?: Helpline[]
  time: string
}
function getTime() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }

const TOPIC_LABELS: Record<string, string> = {
  family: 'Family law', women_rights: "Women's rights / DV", child_safety: 'Child safety',
  police: 'Police / FIR', cyber: 'Cyber safety', workplace: 'Workplace (POSH)',
  legal_aid: 'Free legal aid', court_navigation: 'Court navigation', general: 'General',
}
const EVIDENCE_LABELS: Record<string, { label: string; bg: string; fg: string }> = {
  HIGH: { label: 'High confidence', bg: '#dcfce7', fg: '#15803d' },
  MEDIUM: { label: 'Medium confidence', bg: '#fef9c3', fg: '#a16207' },
  INSUFFICIENT_EVIDENCE: { label: 'Insufficient evidence', bg: '#fee2e2', fg: '#b91c1c' },
}
const AUTH_LABELS: Record<string, string> = {
  tier1_primary_statute: 'Primary statute', tier1_primary_authority: 'Primary authority',
  tier2_official_explanatory: 'Official explanatory', tier3_secondary: 'Secondary',
}

const QUICK_QUESTIONS = [
  'What should I do if my husband is physically abusing me?',
  'How do I file for divorce in India?',
  'What are my rights under the Domestic Violence Act?',
  'Can I get a restraining order against my abuser?',
  'How do I get emergency custody of my children?',
  'What is Section 498A of the Indian Penal Code?',
]

export default function LegalPage() {
  useHavenAuth()
  const { user } = useUser()
  const { isAdmin } = useRole()
  const { lang, tn } = useLang()
  const userId = user?.id || 'anonymous'

  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: tn('legal', 'legalGreeting'),
    time: getTime(),
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const [showSidebar, setShowSidebar] = useState(false)
  const chatRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Re-localize the opening greeting on language change — only while the chat is
  // still just that greeting (never rewrites an in-progress conversation, spec §25).
  useEffect(() => {
    setMessages(prev => {
      if (prev.length === 1 && prev[0].role === 'assistant') {
        return [{ ...prev[0], content: tn('legal', 'legalGreeting') }]
      }
      return prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang])

  async function sendQuestion(question?: string) {
    const q = question || input
    if (!q.trim() || loading) return
    setMessages(prev => [...prev, { role: 'user', content: q, time: getTime() }])
    setInput(''); setLoading(true); setShowSidebar(false)
    try {
      const res = await secureFetch('/legal/query', {
        method: 'POST',
        // Pass the user's selected language so the backend prompts the model in it
        // (spec §8/§12). Retrieval stays grounded; sources are shown in their original language.
        body: JSON.stringify({ question: q, user_id: userId, language: lang })
      })
      if (!res.ok) throw new Error('Server error')
      const data = await res.json()
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        summary: data.summary || '',
        sources: Array.isArray(data.sources) ? data.sources : [],
        grounded: !!data.grounded,
        noContext: !!data.no_context,
        status: data.status,
        topic: data.topic,
        jurisdiction: data.jurisdiction,
        urgency: data.urgency,
        emergency: !!data.emergency,
        immediateDanger: !!data.immediate_danger,
        evidenceLevel: data.evidence_level,
        clarifyingQuestions: Array.isArray(data.clarifying_questions) ? data.clarifying_questions : [],
        nextSteps: Array.isArray(data.next_steps) ? data.next_steps : [],
        evidenceChecklist: Array.isArray(data.evidence_checklist) ? data.evidence_checklist : [],
        legalAid: data.legal_aid || undefined,
        emergencyResources: Array.isArray(data.emergency_resources) ? data.emergency_resources : [],
        time: getTime(),
      }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Trouble connecting. For urgent help, call iCall: 9152987821 or NALSA: 15100.', time: getTime() }])
    } finally { setLoading(false) }
  }

  async function uploadPDF(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setUploading(true); setUploadMsg('')
    const form = new FormData(); form.append('file', file); form.append('source_name', file.name)
    try {
      const res = await secureFetch('/legal/upload-doc', { method: 'POST', body: form })
      if (!res.ok) throw new Error('Upload error')
      const data = await res.json()
      setUploadMsg(`✓ "${file.name}" added (${data.chunks_embedded} chunks)`)
    } catch { setUploadMsg('Upload failed.') }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }


  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #fdf2f8 0%, #f5f0ff 100%)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ background: 'rgba(253,242,248,0.9)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/"><button aria-label={tn('mental_health', 'goBack')} title={tn('mental_health', 'goBack')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#be185d', padding: 4 }}><ArrowLeft size={18} /></button></Link>
          <Scale size={18} style={{ color: '#be185d' }} />
          <div>
            <div style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: 'clamp(0.82rem, 3vw, 0.95rem)' }}>{tn('legal', 'legalTitle')}</div>
            <div style={{ fontSize: '0.65rem', color: '#8b6b7d' }}>{tn('legal', 'legalSubtitle')}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <LanguageSelector compact />
          <button onClick={() => setShowSidebar(!showSidebar)} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 'clamp(0.7rem, 2vw, 0.8rem)', color: '#be185d', fontWeight: 600 }}>
            <BookOpen size={13} />{tn('legal', 'questions')}
          </button>
          {/* Verified-document upload is admin-only (backend enforces require_admin). */}
          {isAdmin && (
            <>
              <input ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={uploadPDF} />
              <button onClick={() => fileRef.current?.click()} disabled={uploading} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '7px 10px', cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 'clamp(0.7rem, 2vw, 0.8rem)', color: '#be185d', fontWeight: 600 }}>
                <Upload size={13} />{uploading ? '...' : 'PDF'}
              </button>
            </>
          )}
        </div>
      </div>

      {uploadMsg && (
        <div style={{ background: '#f0fdf4', borderBottom: '1px solid #86efac', padding: '8px 16px', fontSize: '0.8rem', color: '#15803d', flexShrink: 0 }}>{uploadMsg}</div>
      )}

      {/* Mobile sidebar overlay */}
      {showSidebar && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 50 }} onClick={() => setShowSidebar(false)}>
          <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 'min(85vw, 320px)', background: 'white', padding: 20, overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <span style={{ fontWeight: 700, color: '#be185d', fontSize: '0.9rem' }}>{tn('legal', 'quickQuestions')}</span>
              <button onClick={() => setShowSidebar(false)} title="Close sidebar" style={{ background: 'none', border: 'none', cursor: 'pointer' }}><X size={18} style={{ color: '#8b6b7d' }} /></button>
            </div>
            {QUICK_QUESTIONS.map((q, i) => (
              <button key={i} onClick={() => sendQuestion(q)} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, width: '100%', background: 'none', border: 'none', padding: '10px 0', borderBottom: i < QUICK_QUESTIONS.length - 1 ? '1px solid rgba(190,24,93,0.08)' : 'none', cursor: 'pointer', textAlign: 'left' }}>
                <ChevronRight size={12} style={{ color: '#be185d', marginTop: 3, flexShrink: 0 }} />
                <span style={{ fontSize: '0.82rem', color: '#8b6b7d', lineHeight: 1.4 }}>{q}</span>
              </button>
            ))}
            <div style={{ marginTop: 16, background: '#fef9c3', borderRadius: 10, padding: 12, fontSize: '0.75rem', color: '#a16207', lineHeight: 1.6 }}>
              <strong>{tn('legal', 'disclaimer')}</strong>
            </div>
            <div style={{ marginTop: 12, background: '#fdf2f8', borderRadius: 10, padding: 12, fontSize: '0.75rem', color: '#8b6b7d', lineHeight: 1.7 }}>
              <strong style={{ color: '#be185d' }}>Emergency:</strong><br />
              📞 iCall: 9152987821<br />
              📞 NALSA: 15100<br />
              📞 NCW: 7827170170
            </div>
          </div>
        </div>
      )}

      {/* Main layout */}
      <div style={{ flex: 1, display: 'flex', maxWidth: 1000, margin: '0 auto', width: '100%', padding: '16px 16px 0', gap: 16, minHeight: 0 }}>
        {/* Desktop sidebar */}
        <div style={{ width: 210, flexShrink: 0, display: 'none', flexDirection: 'column', gap: 10 }} className="desktop-only">
          <div style={{ background: 'white', borderRadius: 16, padding: 16, border: '1px solid rgba(190,24,93,0.1)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
              <BookOpen size={14} style={{ color: '#be185d' }} />
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#be185d' }}>{tn('legal', 'quickQuestions')}</span>
            </div>
            {QUICK_QUESTIONS.map((q, i) => (
              <button key={i} onClick={() => sendQuestion(q)} style={{ display: 'flex', alignItems: 'flex-start', gap: 5, width: '100%', background: 'none', border: 'none', padding: '7px 0', borderBottom: i < QUICK_QUESTIONS.length - 1 ? '1px solid rgba(190,24,93,0.06)' : 'none', cursor: 'pointer', textAlign: 'left' }}>
                <ChevronRight size={11} style={{ color: '#be185d', marginTop: 2, flexShrink: 0 }} />
                <span style={{ fontSize: '0.72rem', color: '#8b6b7d', lineHeight: 1.4 }}>{q}</span>
              </button>
            ))}
          </div>
          <div style={{ background: '#fef9c3', borderRadius: 10, padding: 12, border: '1px solid #fde047', fontSize: '0.72rem', color: '#a16207', lineHeight: 1.5 }}>
            <strong>{tn('legal', 'disclaimer')}</strong>
          </div>
          <div style={{ background: 'white', borderRadius: 10, padding: 12, border: '1px solid rgba(190,24,93,0.1)', fontSize: '0.72rem', color: '#8b6b7d', lineHeight: 1.6 }}>
            <strong style={{ color: '#be185d' }}>Emergency:</strong><br />
            📞 iCall: 9152987821<br />
            📞 NALSA: 15100<br />
            📞 NCW: 7827170170
          </div>
        </div>

        {/* Chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div ref={chatRef} style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14, paddingBottom: 12, maxHeight: 'calc(100vh - 240px)' }}>
            {messages.map((msg, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {msg.role === 'assistant' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                    <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg,#be185d,#9d174d)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Scale size={11} style={{ color: 'white' }} />
                    </div>
                    <span style={{ fontSize: '0.68rem', color: '#8b6b7d', fontWeight: 600 }}>Legal Assistant</span>
                  </div>
                )}

                {/* EMERGENCY panel — shown first when the situation looks urgent */}
                {msg.role === 'assistant' && (msg.emergency || msg.immediateDanger) && msg.emergencyResources && msg.emergencyResources.length > 0 && (
                  <div style={{ background: '#fef2f2', border: '2px solid #fca5a5', borderRadius: 12, padding: '10px 12px', marginBottom: 8, maxWidth: '95%' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 800, color: '#b91c1c', marginBottom: 6 }}>
                      🚨 If you are in immediate danger, call now:
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {msg.emergencyResources.map((h, j) => (
                        <a key={j} href={`tel:${h.number}`} style={{ display: 'flex', flexDirection: 'column', background: 'white', border: '1px solid #fecaca', borderRadius: 8, padding: '5px 9px', textDecoration: 'none' }}>
                          <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#b91c1c' }}>📞 {h.number}</span>
                          <span style={{ fontSize: '0.6rem', color: '#8b6b7d' }}>{h.name}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                {/* Classification badges */}
                {msg.role === 'assistant' && msg.topic && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 6 }}>
                    <span style={{ fontSize: '0.62rem', fontWeight: 700, background: 'rgba(190,24,93,0.1)', color: '#be185d', padding: '2px 8px', borderRadius: 50 }}>
                      {TOPIC_LABELS[msg.topic] || msg.topic}
                    </span>
                    {msg.jurisdiction && (
                      <span style={{ fontSize: '0.62rem', fontWeight: 600, background: 'rgba(139,107,125,0.12)', color: '#8b6b7d', padding: '2px 8px', borderRadius: 50 }}>
                        📍 {msg.jurisdiction}
                      </span>
                    )}
                    {msg.urgency && msg.urgency !== 'normal' && (
                      <span style={{ fontSize: '0.62rem', fontWeight: 700, background: msg.urgency === 'emergency' ? '#fee2e2' : '#fef9c3', color: msg.urgency === 'emergency' ? '#b91c1c' : '#a16207', padding: '2px 8px', borderRadius: 50 }}>
                        {msg.urgency === 'emergency' ? '🚨 Urgent' : '⏱ Time-sensitive'}
                      </span>
                    )}
                    {msg.evidenceLevel && EVIDENCE_LABELS[msg.evidenceLevel] && (
                      <span style={{ fontSize: '0.62rem', fontWeight: 700, background: EVIDENCE_LABELS[msg.evidenceLevel].bg, color: EVIDENCE_LABELS[msg.evidenceLevel].fg, padding: '2px 8px', borderRadius: 50 }}>
                        {EVIDENCE_LABELS[msg.evidenceLevel].label}
                      </span>
                    )}
                  </div>
                )}

                <div className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai'} style={{ whiteSpace: 'pre-wrap', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>
                  {msg.content}
                </div>

                {/* Provenance indicator (assistant only) */}
                {msg.role === 'assistant' && msg.grounded && msg.sources && msg.sources.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6, paddingLeft: 4, fontSize: '0.65rem', color: '#15803d', fontWeight: 600 }}>
                    <span style={{ background: '#dcfce7', padding: '2px 8px', borderRadius: 50 }}>✓ AI-generated from verified sources</span>
                    {typeof msg.sources[0]?.relevance_score === 'number' && (
                      <span style={{ background: 'rgba(190,24,93,0.08)', color: '#be185d', padding: '2px 8px', borderRadius: 50 }}>
                        Top relevance {Math.round((msg.sources[0].relevance_score as number) * 100)}%
                      </span>
                    )}
                  </div>
                )}
                {msg.role === 'assistant' && msg.noContext && (
                  <div style={{ marginTop: 6, paddingLeft: 4, fontSize: '0.65rem', color: '#a16207', fontWeight: 600 }}>
                    <span style={{ background: '#fef9c3', padding: '2px 8px', borderRadius: 50 }}>⚠ No verified source found — not answered from sources</span>
                  </div>
                )}
                {msg.role === 'assistant' && msg.status === 'llm_unavailable' && (
                  <div style={{ marginTop: 6, paddingLeft: 4, fontSize: '0.65rem', color: '#b91c1c', fontWeight: 600 }}>
                    <span style={{ background: '#fee2e2', padding: '2px 8px', borderRadius: 50 }}>Answer service unavailable — showing sources only</span>
                  </div>
                )}

                {/* Practical next steps (deterministic scaffolding, not fabricated law) */}
                {msg.role === 'assistant' && msg.nextSteps && msg.nextSteps.length > 0 && (
                  <div style={{ marginTop: 8, paddingLeft: 4, maxWidth: '92%' }}>
                    <span style={{ fontSize: '0.62rem', color: '#be185d', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4 }}>What you can do</span>
                    <ol style={{ margin: '4px 0 0', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 3 }}>
                      {msg.nextSteps.map((s, j) => (
                        <li key={j} style={{ fontSize: '0.72rem', color: '#5f4453', lineHeight: 1.45 }}>{s}</li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Evidence checklist */}
                {msg.role === 'assistant' && msg.evidenceChecklist && msg.evidenceChecklist.length > 0 && (
                  <div style={{ marginTop: 8, paddingLeft: 4, maxWidth: '92%' }}>
                    <span style={{ fontSize: '0.62rem', color: '#be185d', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4 }}>Evidence to keep safe</span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {msg.evidenceChecklist.map((s, j) => (
                        <span key={j} style={{ fontSize: '0.68rem', background: 'rgba(190,24,93,0.06)', color: '#7a2348', padding: '3px 8px', borderRadius: 6 }}>☑ {s}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Clarifying questions — tap to ask */}
                {msg.role === 'assistant' && msg.clarifyingQuestions && msg.clarifyingQuestions.length > 0 && (
                  <div style={{ marginTop: 8, paddingLeft: 4, maxWidth: '92%' }}>
                    <span style={{ fontSize: '0.62rem', color: '#be185d', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4 }}>To help you better, could you share</span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                      {msg.clarifyingQuestions.map((q, j) => (
                        <button key={j} onClick={() => sendQuestion(q)} disabled={loading} style={{ textAlign: 'left', fontSize: '0.7rem', color: '#5f4453', background: 'white', border: '1px dashed rgba(190,24,93,0.35)', borderRadius: 8, padding: '5px 9px', cursor: loading ? 'not-allowed' : 'pointer', lineHeight: 1.4 }}>
                          💬 {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Free legal-aid escalation */}
                {msg.role === 'assistant' && msg.legalAid && msg.legalAid.helplines && msg.legalAid.helplines.length > 0 && (
                  <div style={{ marginTop: 8, paddingLeft: 4, maxWidth: '92%' }}>
                    <div style={{ background: '#f5f0ff', border: '1px solid #ddd6fe', borderRadius: 10, padding: '9px 11px' }}>
                      <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#6d28d9', marginBottom: 4 }}>⚖️ Free legal help</div>
                      {msg.legalAid.note && (
                        <div style={{ fontSize: '0.68rem', color: '#5f4453', lineHeight: 1.5, marginBottom: 5 }}>{msg.legalAid.note}</div>
                      )}
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {msg.legalAid.helplines.map((h, j) => (
                          <a key={j} href={`tel:${h.number}`} style={{ fontSize: '0.68rem', color: '#6d28d9', textDecoration: 'none', fontWeight: 600, background: 'white', border: '1px solid #ddd6fe', borderRadius: 6, padding: '3px 8px' }}>
                            📞 {h.name}: {h.number}
                          </a>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* Citations actually used */}
                {msg.sources && msg.sources.length > 0 && (
                  <div style={{ marginTop: 8, paddingLeft: 4, display: 'flex', flexDirection: 'column', gap: 5, maxWidth: '92%' }}>
                    <span style={{ fontSize: '0.62rem', color: '#8b6b7d', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4 }}>
                      {msg.sources.length} official source{msg.sources.length > 1 ? 's' : ''} found
                    </span>
                    {msg.sources.map((s, j) => (
                      <div key={j} style={{ fontSize: '0.68rem', background: 'rgba(190,24,93,0.06)', color: '#7a2348', padding: '7px 10px', borderRadius: 8, lineHeight: 1.45 }}>
                        <div>
                          📄 <strong>{s.title}</strong>{s.section ? ` — ${s.section}` : ''}
                          {typeof s.relevance_score === 'number' ? (
                            <span style={{ color: '#be185d', marginLeft: 6 }}>({Math.round((s.relevance_score as number) * 100)}% match)</span>
                          ) : (typeof s.match_strength === 'number' && s.match_strength > 0 ? (
                            <span style={{ color: '#be185d', marginLeft: 6 }}>({Math.round((s.match_strength as number) * 100)}% keyword match)</span>
                          ) : null)}
                        </div>
                        {(s.act_name || s.authority) && (
                          <div style={{ fontSize: '0.62rem', color: '#8b6b7d', marginTop: 2 }}>
                            {s.act_name ? s.act_name : ''}{s.act_name && s.authority ? ' · ' : ''}{s.authority ? s.authority : ''}
                          </div>
                        )}
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 4 }}>
                          {s.authority_level && AUTH_LABELS[s.authority_level] && (
                            <span style={{ fontSize: '0.58rem', fontWeight: 700, background: 'rgba(21,128,61,0.1)', color: '#15803d', padding: '1px 7px', borderRadius: 50 }}>
                              {AUTH_LABELS[s.authority_level]}
                            </span>
                          )}
                          {s.last_verified && (
                            <span style={{ fontSize: '0.58rem', color: '#8b6b7d' }}>Verified {s.last_verified}</span>
                          )}
                          {s.source_url && (
                            <a href={s.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '0.62rem', color: '#be185d', textDecoration: 'underline' }}>official source ↗</a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <span style={{ fontSize: '0.65rem', color: '#8b6b7d', marginTop: 3, paddingLeft: 4, paddingRight: 4 }}>{msg.time}</span>
              </div>
            ))}
            {loading && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                  <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg,#be185d,#9d174d)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Scale size={11} style={{ color: 'white' }} />
                  </div>
                  <span style={{ fontSize: '0.68rem', color: '#8b6b7d', fontWeight: 600 }}>{tn('legal', 'searching')}</span>
                </div>
                <div className="chat-bubble-ai" style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '12px 16px' }}>
                  <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8, background: 'white', borderRadius: 16, border: '2px solid rgba(190,24,93,0.15)', padding: '7px 7px 7px 14px', boxShadow: '0 4px 12px rgba(190,24,93,0.08)', marginBottom: 16, flexShrink: 0 }}>
            <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendQuestion()}
              placeholder={tn('legal', 'legalPlaceholder')}
              style={{ flex: 1, border: 'none', outline: 'none', fontSize: 'clamp(0.85rem, 2.5vw, 0.9rem)', fontFamily: 'Georgia', color: '#1a0a12', background: 'transparent', minWidth: 0 }}
            />
            <button aria-label={tn('accessibility', 'sendMessage')} title={tn('accessibility', 'sendMessage')} onClick={() => sendQuestion()} disabled={loading || !input.trim()} style={{ background: loading || !input.trim() ? 'rgba(190,24,93,0.3)' : 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '9px 14px', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', flexShrink: 0 }}>
              <Send size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}