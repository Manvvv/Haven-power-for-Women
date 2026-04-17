'use client'
import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Send, Volume2, VolumeX, Sparkles } from 'lucide-react'
import AriaCanvas, { AvatarHandle, AvatarMood } from '@/components/AriaCanvas'
import { useHavenAuth } from '@/hooks/useHavenAuth'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string; time: string }
function getTime() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
const QUICK = ['I feel anxious', "I'm feeling scared", 'I need coping strategies', "Tell me I'm not alone"]

export default function TherapyPage() {
  useHavenAuth()
  const chatRef = useRef<HTMLDivElement>(null)
  const avatarRef = useRef<AvatarHandle>(null)
  const synthRef = useRef<SpeechSynthesis | null>(null)
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null)

  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: "Hello, I'm Aria. I'm here for you. This is a safe, private space — whatever you share stays between us. How are you feeling right now?",
    time: getTime()
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [mood, setMoodState] = useState<AvatarMood>('idle')
  const voiceOnRef = useRef(true)
  const [voiceOn, setVoiceOn] = useState(true)
  const [poem, setPoem] = useState('')
  const [showPoem, setShowPoem] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [showMobileAvatar, setShowMobileAvatar] = useState(false)
  const [avatarSize, setAvatarSize] = useState(300)

  // Responsive detection
  useEffect(() => {
    if (typeof window === 'undefined') return
    synthRef.current = window.speechSynthesis

    const update = () => {
      const w = window.innerWidth
      const mobile = w < 768
      setIsMobile(mobile)
      if (mobile) {
        setAvatarSize(Math.min(Math.floor(w * 0.55), 220))
      } else {
        setAvatarSize(Math.min(Math.floor(w * 0.28), 320))
      }
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const setMood = useCallback((m: AvatarMood) => {
    setMoodState(m)
    avatarRef.current?.setMood(m)
  }, [])

  const speak = useCallback((text: string) => {
    synthRef.current?.cancel()
    setMood('talking')
    avatarRef.current?.setMood('talking')

    if (!voiceOnRef.current || !synthRef.current) {
      const dur = Math.min(text.length * 55, 12000)
      setTimeout(() => {
        setMood('idle')
        avatarRef.current?.setMood('idle')
      }, dur)
      return
    }

    // Defer the speak command to prevent browser TTS engine from locking up the UI thread after cancel()
    setTimeout(() => {
      const utter = new SpeechSynthesisUtterance(text)
      utter.rate = 0.88; utter.pitch = 1.18; utter.volume = 1
      const voices = synthRef.current?.getVoices() || []
      const pick = voices.find(v => /samantha|karen|victoria|aria|zira|female/i.test(v.name))
      if (pick) utter.voice = pick
      
      utter.onend = () => { setMood('idle'); avatarRef.current?.setMood('idle') }
      utter.onerror = () => { setMood('idle'); avatarRef.current?.setMood('idle') }
      utterRef.current = utter
      
      // Prevent GC bug that freezes TTS
      ;(window as any)._longSpeechHack = utter
      
      synthRef.current?.speak(utter)
    }, 50)
  }, [setMood])

  const sendMessage = async (msg?: string) => {
    const text = msg || input
    if (!text.trim() || loading) return
    setMessages(prev => [...prev, { role: 'user', content: text, time: getTime() }])
    setInput('')
    setLoading(true)
    setMood('listening')
    try {
      const res = await fetch(`${API}/therapy/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, user_id: 'anon', session_id: sessionId })
      })
      const data = await res.json()
      const reply = data.response || "I'm here with you."
      setMessages(prev => [...prev, { role: 'assistant', content: reply, time: getTime() }])
      setSessionId(data.session_id)
      speak(reply)
    } catch {
      setMood('idle')
      setMessages(prev => [...prev, { role: 'assistant', content: "I'm having trouble connecting. If you need immediate help, please call 112.", time: getTime() }])
    } finally { setLoading(false) }
  }

  const generatePoem = async () => {
    try {
      const res = await fetch(`${API}/generate-poem`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emotional_state: 'distressed and in need of hope' })
      })
      const data = await res.json()
      if (data.poem) { setPoem(data.poem); setShowPoem(true) }
    } catch {}
  }

  const moodColor = mood === 'talking' ? '#22c55e' : mood === 'listening' ? '#a855f7' : '#be185d'
  const moodBg = mood === 'talking' ? 'rgba(34,197,94,0.12)' : mood === 'listening' ? 'rgba(168,85,247,0.12)' : 'rgba(190,24,93,0.08)'
  const moodLabel = mood === 'talking' ? '✦ Speaking...' : mood === 'listening' ? '◉ Listening...' : '● Ready'

  return (
    <div style={{ minHeight: '100vh', height: '100dvh', display: 'flex', flexDirection: 'column', background: 'linear-gradient(150deg,#fdf2f8 0%,#f5f0ff 50%,#fce7f3 100%)', overflow: 'hidden' }}>
      <style>{`
        @keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        @keyframes slideDown{from{opacity:0;transform:translateY(-20px)}to{opacity:1;transform:translateY(0)}}
        .msg-in{animation:fadeIn 0.3s ease}
        .avatar-panel{animation:slideDown 0.3s ease}
      `}</style>

      {/* ── HEADER ── */}
      <div style={{
        background: 'rgba(253,242,248,0.96)', backdropFilter: 'blur(16px)',
        borderBottom: '1px solid rgba(190,24,93,0.1)',
        padding: 'clamp(10px,2vw,14px) clamp(12px,3vw,20px)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0, zIndex: 10
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/">
            <button aria-label="Go back" title="Go back" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#be185d', padding: 4, display: 'flex', alignItems: 'center' }}>
              <ArrowLeft size={18} />
            </button>
          </Link>

          {/* Mobile: Aria toggle button */}
          {isMobile && (
            <button
              onClick={() => setShowMobileAvatar(v => !v)}
              aria-label="Toggle Aria avatar"
              title="Toggle Aria avatar"
              style={{
                background: showMobileAvatar ? 'rgba(190,24,93,0.12)' : 'rgba(190,24,93,0.06)',
                border: '1px solid rgba(190,24,93,0.25)', borderRadius: 20,
                padding: '5px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5,
                fontSize: '0.72rem', color: '#be185d', fontWeight: 600
              }}
            >
              🌸 Aria
            </button>
          )}

          <div>
            <div style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: 'clamp(0.82rem, 3vw, 0.95rem)', lineHeight: 1.2 }}>Haven · Aria</div>
            <div style={{ fontSize: '0.58rem', color: '#8b6b7d' }}>Private & Confidential · 24/7</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {/* Mood badge — hide on very small screens */}
          {!isMobile && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: moodBg, border: `1px solid ${moodColor}44`, borderRadius: 20, padding: '4px 12px', transition: 'all 0.4s' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: moodColor, transition: 'background 0.4s' }} />
              <span style={{ fontSize: '0.68rem', color: moodColor, fontWeight: 600, transition: 'color 0.4s' }}>{moodLabel}</span>
            </div>
          )}
          <button
            aria-label={voiceOn ? "Toggle voice off" : "Toggle voice on"}
            title={voiceOn ? "Toggle voice off" : "Toggle voice on"}
            onClick={() => {
              const newVal = !voiceOn
              setVoiceOn(newVal)
              voiceOnRef.current = newVal
              if (!newVal) {
                synthRef.current?.cancel()
                setMood('idle')
                avatarRef.current?.setMood('idle')
              }
            }}
            style={{ background: voiceOn ? 'rgba(190,24,93,0.1)' : 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '6px', cursor: 'pointer', display: 'flex' }}
          >
            {voiceOn ? <Volume2 size={15} style={{ color: '#be185d' }} /> : <VolumeX size={15} style={{ color: '#8b6b7d' }} />}
          </button>
          <button
            aria-label="Generate inspirational poem"
            title="Generate inspirational poem"
            onClick={generatePoem}
            style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.15)', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', fontSize: 'clamp(0.65rem, 2vw, 0.72rem)', color: '#be185d', fontWeight: 600 }}
          >
            <Sparkles size={13} /><span>Poem</span>
          </button>
        </div>
      </div>

      {/* ── MOBILE AVATAR PANEL (collapsible) ── */}
      {isMobile && showMobileAvatar && (
        <div className="avatar-panel" style={{
          background: 'linear-gradient(180deg,#1a0a12 0%,#2d0f1f 100%)',
          flexShrink: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          padding: '16px 0 12px', gap: 8,
          borderBottom: '1px solid rgba(190,24,93,0.2)'
        }}>
          <div style={{ position: 'relative' }}>
            <div style={{ position: 'absolute', inset: -16, borderRadius: '50%', background: `radial-gradient(circle, ${moodColor}22 0%, transparent 70%)`, transition: 'background 0.6s', pointerEvents: 'none' }} />
            <AriaCanvas ref={avatarRef} size={avatarSize} />
          </div>
          <div style={{ background: 'rgba(26,10,18,0.78)', backdropFilter: 'blur(8px)', borderRadius: 20, padding: '5px 16px', border: `1px solid ${moodColor}44` }}>
            <p style={{ fontSize: '0.65rem', color: 'rgba(249,168,212,0.95)', fontFamily: 'Georgia', fontStyle: 'italic', margin: 0 }}>
              {moodLabel}
            </p>
          </div>
        </div>
      )}

      {/* ── MAIN LAYOUT ── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>

        {/* Desktop Avatar Panel */}
        {!isMobile && (
          <div style={{
            width: avatarSize + 40, flexShrink: 0,
            background: 'linear-gradient(180deg,#1a0a12 0%,#2d0f1f 60%,#1a0a12 100%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', position: 'relative', overflow: 'hidden'
          }}>
            {/* Ambient glow */}
            <div style={{ position: 'absolute', width: avatarSize * 1.4, height: avatarSize * 1.4, borderRadius: '50%', background: `radial-gradient(circle, ${moodColor}22 0%, transparent 70%)`, transition: 'background 0.6s', pointerEvents: 'none' }} />

            <div style={{ position: 'relative', zIndex: 1 }}>
              <AriaCanvas ref={avatarRef} size={avatarSize} />
            </div>

            {/* Name tag */}
            <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', background: 'rgba(26,10,18,0.78)', backdropFilter: 'blur(8px)', borderRadius: 20, padding: '5px 18px', border: `1px solid ${moodColor}44`, whiteSpace: 'nowrap', transition: 'border-color 0.4s' }}>
              <p style={{ fontSize: '0.65rem', color: 'rgba(249,168,212,0.95)', fontFamily: 'Georgia', fontStyle: 'italic', margin: 0 }}>
                {mood === 'talking' ? '✦ Aria is speaking...' : mood === 'listening' ? '◉ Aria is listening...' : '● Aria · Here for you'}
              </p>
            </div>

            {/* Status pills */}
            <div style={{ position: 'absolute', top: 12, right: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[['#be185d', 'Private'], ['#22c55e', 'Non-judgmental'], ['#a855f7', '24/7']].map(([c, l]) => (
                <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(26,10,18,0.65)', borderRadius: 12, padding: '3px 8px', border: `1px solid ${c}33` }}>
                  <div style={{ width: 5, height: 5, borderRadius: '50%', background: c }} />
                  <span style={{ fontSize: '0.55rem', color: 'rgba(249,168,212,0.8)' }}>{l}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── CHAT PANEL ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'rgba(253,242,248,0.5)' }}>

          {/* Messages */}
          <div
            ref={chatRef}
            style={{
              flex: 1, overflowY: 'auto',
              padding: 'clamp(12px,3vw,20px) clamp(12px,3vw,20px) 8px',
              display: 'flex', flexDirection: 'column', gap: 12
            }}
          >
            {messages.map((msg, i) => (
              <div key={i} className="msg-in" style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {msg.role === 'assistant' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                    <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'linear-gradient(135deg,#be185d,#9d174d)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6rem' }}>🌸</div>
                    <span style={{ fontSize: '0.62rem', color: '#be185d', fontWeight: 600 }}>Aria</span>
                  </div>
                )}
                <div style={{
                  maxWidth: 'clamp(240px, 88%, 520px)',
                  padding: 'clamp(10px,2vw,13px) clamp(12px,3vw,16px)',
                  borderRadius: msg.role === 'user' ? '18px 18px 4px 18px' : '4px 18px 18px 18px',
                  background: msg.role === 'user' ? 'linear-gradient(135deg,#be185d,#9d174d)' : 'white',
                  color: msg.role === 'user' ? 'white' : '#1a0a12',
                  fontSize: 'clamp(0.82rem, 2.5vw, 0.88rem)', lineHeight: 1.65,
                  border: msg.role === 'assistant' ? '1px solid rgba(190,24,93,0.1)' : 'none',
                  boxShadow: msg.role === 'assistant' ? '0 2px 12px rgba(190,24,93,0.08)' : '0 2px 8px rgba(190,24,93,0.2)',
                  wordBreak: 'break-word'
                }}>
                  {msg.content}
                </div>
                <span style={{ fontSize: '0.58rem', color: '#8b6b7d', marginTop: 3, padding: '0 4px' }}>{msg.time}</span>
              </div>
            ))}

            {loading && (
              <div className="msg-in" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                  <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'linear-gradient(135deg,#a855f7,#7c3aed)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6rem' }}>🌸</div>
                  <span style={{ fontSize: '0.62rem', color: '#a855f7', fontWeight: 600 }}>Aria is thinking...</span>
                </div>
                <div style={{ background: 'white', borderRadius: '4px 18px 18px 18px', padding: '12px 16px', border: '1px solid rgba(168,85,247,0.15)', display: 'flex', gap: 6, alignItems: 'center' }}>
                  {[0, 1, 2].map(i => <div key={i} style={{ width: 7, height: 7, borderRadius: '50%', background: '#f9a8d4', animation: `bounce 1.1s infinite ${i * 0.18}s` }} />)}
                </div>
              </div>
            )}
          </div>

          {/* Quick replies */}
          <div style={{ padding: 'clamp(4px,1vw,6px) clamp(12px,3vw,20px)', display: 'flex', gap: 6, flexWrap: 'wrap', flexShrink: 0 }}>
            {QUICK.map(q => (
              <button key={q} onClick={() => sendMessage(q)} title={q} aria-label={q}
                style={{ fontSize: 'clamp(0.65rem, 2vw, 0.72rem)', padding: '5px 12px', borderRadius: 50, border: '1px solid rgba(190,24,93,0.22)', background: 'white', cursor: 'pointer', color: '#be185d', whiteSpace: 'nowrap', transition: 'all 0.18s' }}
                onMouseEnter={e => { e.currentTarget.style.background = '#fce7f3' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'white' }}>
                {q}
              </button>
            ))}
          </div>

          {/* Input */}
          <div style={{ padding: 'clamp(6px,2vw,10px) clamp(12px,3vw,20px) clamp(10px,3vw,16px)', flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 8, background: 'white', borderRadius: 14, border: '2px solid rgba(190,24,93,0.18)', padding: '7px 7px 7px 14px', boxShadow: '0 4px 20px rgba(190,24,93,0.1)' }}>
              <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder="Tell me how you're feeling..."
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 'clamp(0.82rem, 2.5vw, 0.88rem)', fontFamily: 'Georgia', color: '#1a0a12', background: 'transparent', minWidth: 0 }}
              />
              <button
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
                title="Send message"
                aria-label="Send message"
                style={{ background: loading || !input.trim() ? 'rgba(190,24,93,0.2)' : 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '9px 14px', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0, transition: 'all 0.2s' }}
              >
                <Send size={15} />
              </button>
            </div>
            <p style={{ textAlign: 'center', fontSize: '0.58rem', color: '#8b6b7d', marginTop: 6 }}>
              Emergency: <strong>112</strong> · Women's Helpline: <strong>181</strong> · DV Helpline: <strong>1091</strong>
            </p>
          </div>
        </div>
      </div>

      {/* ── POEM MODAL ── */}
      {showPoem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(26,10,18,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 'clamp(16px,4vw,24px)' }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 'clamp(24px,5vw,36px) clamp(20px,4vw,32px)', maxWidth: 440, width: '100%', textAlign: 'center', boxShadow: '0 20px 60px rgba(190,24,93,0.2)', animation: 'fadeIn 0.3s ease' }}>
            <Sparkles size={28} style={{ color: '#be185d', display: 'block', margin: '0 auto 12px' }} />
            <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(1rem, 3vw, 1.1rem)', color: '#be185d', marginBottom: 16 }}>A Poem for You</h3>
            <p style={{ fontFamily: 'Georgia', lineHeight: 2, color: '#1a0a12', whiteSpace: 'pre-line', fontStyle: 'italic', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>{poem}</p>
            <button onClick={() => setShowPoem(false)} aria-label="Close poem" title="Close poem" style={{ marginTop: 20, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 50, padding: '10px 28px', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>Close</button>
          </div>
        </div>
      )}
    </div>
  )
}
