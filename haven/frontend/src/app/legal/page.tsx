'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { ArrowLeft, Scale, Send, Upload, BookOpen, ChevronRight, X } from 'lucide-react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string; sources?: string[]; time: string }
function getTime() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }

const QUICK_QUESTIONS = [
  'What should I do if my husband is physically abusing me?',
  'How do I file for divorce in India?',
  'What are my rights under the Domestic Violence Act?',
  'Can I get a restraining order against my abuser?',
  'How do I get emergency custody of my children?',
  'What is Section 498A of the Indian Penal Code?',
]

export default function LegalPage() {
  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: "Hello. I'm Haven's legal assistant, trained on Indian law. Ask me anything about your legal rights — divorce, custody, restraining orders, or filing complaints. Everything is confidential.",
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

  async function sendQuestion(question?: string) {
    const q = question || input
    if (!q.trim() || loading) return
    setMessages(prev => [...prev, { role: 'user', content: q, time: getTime() }])
    setInput(''); setLoading(true); setShowSidebar(false)
    try {
      const res = await fetch(`${API}/legal/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, user_id: 'anonymous' }) })
      const data = await res.json()
      setMessages(prev => [...prev, { role: 'assistant', content: data.answer, sources: data.sources?.filter(Boolean), time: getTime() }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Trouble connecting. For urgent help, call iCall: 9152987821 or NALSA: 15100.', time: getTime() }])
    } finally { setLoading(false) }
  }

  async function uploadPDF(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setUploading(true); setUploadMsg('')
    const form = new FormData(); form.append('file', file); form.append('source_name', file.name)
    try {
      const res = await fetch(`${API}/legal/upload-doc`, { method: 'POST', body: form })
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
          <Link href="/"><button aria-label="Go back" title="Go back" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#be185d', padding: 4 }}><ArrowLeft size={18} /></button></Link>
          <Scale size={18} style={{ color: '#be185d' }} />
          <div>
            <div style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: 'clamp(0.82rem, 3vw, 0.95rem)' }}>Haven · Legal Assistant</div>
            <div style={{ fontSize: '0.65rem', color: '#8b6b7d' }}>Indian Law · Confidential</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => setShowSidebar(!showSidebar)} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 'clamp(0.7rem, 2vw, 0.8rem)', color: '#be185d', fontWeight: 600 }}>
            <BookOpen size={13} />Questions
          </button>
          <input placeholder="Type your message..."  ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={uploadPDF} />
          <button onClick={() => fileRef.current?.click()} disabled={uploading} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '7px 10px', cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 'clamp(0.7rem, 2vw, 0.8rem)', color: '#be185d', fontWeight: 600 }}>
            <Upload size={13} />{uploading ? '...' : 'PDF'}
          </button>
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
              <span style={{ fontWeight: 700, color: '#be185d', fontSize: '0.9rem' }}>Quick Questions</span>
              <button onClick={() => setShowSidebar(false)} title="Close sidebar" style={{ background: 'none', border: 'none', cursor: 'pointer' }}><X size={18} style={{ color: '#8b6b7d' }} /></button>
            </div>
            {QUICK_QUESTIONS.map((q, i) => (
              <button key={i} onClick={() => sendQuestion(q)} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, width: '100%', background: 'none', border: 'none', padding: '10px 0', borderBottom: i < QUICK_QUESTIONS.length - 1 ? '1px solid rgba(190,24,93,0.08)' : 'none', cursor: 'pointer', textAlign: 'left' }}>
                <ChevronRight size={12} style={{ color: '#be185d', marginTop: 3, flexShrink: 0 }} />
                <span style={{ fontSize: '0.82rem', color: '#8b6b7d', lineHeight: 1.4 }}>{q}</span>
              </button>
            ))}
            <div style={{ marginTop: 16, background: '#fef9c3', borderRadius: 10, padding: 12, fontSize: '0.75rem', color: '#a16207', lineHeight: 1.6 }}>
              <strong>Disclaimer:</strong> AI guidance only. Consult a qualified lawyer.
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
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#be185d' }}>Quick Questions</span>
            </div>
            {QUICK_QUESTIONS.map((q, i) => (
              <button key={i} onClick={() => sendQuestion(q)} style={{ display: 'flex', alignItems: 'flex-start', gap: 5, width: '100%', background: 'none', border: 'none', padding: '7px 0', borderBottom: i < QUICK_QUESTIONS.length - 1 ? '1px solid rgba(190,24,93,0.06)' : 'none', cursor: 'pointer', textAlign: 'left' }}>
                <ChevronRight size={11} style={{ color: '#be185d', marginTop: 2, flexShrink: 0 }} />
                <span style={{ fontSize: '0.72rem', color: '#8b6b7d', lineHeight: 1.4 }}>{q}</span>
              </button>
            ))}
          </div>
          <div style={{ background: '#fef9c3', borderRadius: 10, padding: 12, border: '1px solid #fde047', fontSize: '0.72rem', color: '#a16207', lineHeight: 1.5 }}>
            <strong>Disclaimer:</strong> AI guidance only. Consult a qualified lawyer.
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
                <div className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai'} style={{ whiteSpace: 'pre-wrap', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>
                  {msg.content}
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 5, paddingLeft: 4 }}>
                    {msg.sources.map((s, j) => <span key={j} style={{ fontSize: '0.65rem', background: 'rgba(190,24,93,0.08)', color: '#be185d', padding: '2px 7px', borderRadius: 50 }}>📄 {s}</span>)}
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
                  <span style={{ fontSize: '0.68rem', color: '#8b6b7d', fontWeight: 600 }}>Searching...</span>
                </div>
                <div className="chat-bubble-ai" style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '12px 16px' }}>
                  <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8, background: 'white', borderRadius: 16, border: '2px solid rgba(190,24,93,0.15)', padding: '7px 7px 7px 14px', boxShadow: '0 4px 12px rgba(190,24,93,0.08)', marginBottom: 16, flexShrink: 0 }}>
            <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendQuestion()}
              placeholder="Ask about your legal rights..."
              style={{ flex: 1, border: 'none', outline: 'none', fontSize: 'clamp(0.85rem, 2.5vw, 0.9rem)', fontFamily: 'Georgia', color: '#1a0a12', background: 'transparent', minWidth: 0 }}
            />
            <button aria-label="Send message" onClick={() => sendQuestion()} disabled={loading || !input.trim()} style={{ background: loading || !input.trim() ? 'rgba(190,24,93,0.3)' : 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '9px 14px', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', flexShrink: 0 }}>
              <Send size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}