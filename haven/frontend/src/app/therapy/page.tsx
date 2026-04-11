'use client'
import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Send, Volume2, VolumeX, Sparkles } from 'lucide-react'
import AriaCanvas, { AvatarHandle, AvatarMood } from '@/components/AriaCanvas'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string; time: string }
function getTime() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
const QUICK = ['I feel anxious', "I'm feeling scared", 'I need coping strategies', "Tell me I'm not alone"]

export default function TherapyPage() {
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
  const [voiceOn, setVoiceOn] = useState(true)
  const [poem, setPoem] = useState('')
  const [showPoem, setShowPoem] = useState(false)
  const [avatarSize, setAvatarSize] = useState(300)

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      synthRef.current = window.speechSynthesis
      const update = () => setAvatarSize(Math.min(Math.floor(window.innerWidth * 0.38), 340))
      update()
      window.addEventListener('resize', update)
      return () => window.removeEventListener('resize', update)
    }
  }, [])

  const setMood = useCallback((m: AvatarMood) => {
    setMoodState(m)
    avatarRef.current?.setMood(m)
  }, [])

  const speak = useCallback((text: string) => {
    synthRef.current?.cancel()
    setMood('talking')
    if (!voiceOn || !synthRef.current) {
      const dur = Math.min(text.length * 55, 12000)
      setTimeout(() => setMood('idle'), dur)
      return
    }
    const utter = new SpeechSynthesisUtterance(text)
    utter.rate = 0.88
    utter.pitch = 1.18
    utter.volume = 1
    const voices = synthRef.current.getVoices()
    const pick = voices.find(v => /samantha|karen|victoria|aria|zira|female/i.test(v.name))
    if (pick) utter.voice = pick
    utter.onend = () => setMood('idle')
    utter.onerror = () => setMood('idle')
    utterRef.current = utter
    synthRef.current.speak(utter)
  }, [voiceOn, setMood])

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
    } finally {
      setLoading(false)
    }
  }

  const generatePoem = async () => {
    try {
      const res = await fetch(`${API}/generate-poem`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emotional_state: 'distressed and in need of hope' })
      })
      const data = await res.json()
      setPoem(data.poem || '')
      setShowPoem(true)
    } catch {}
  }

  const moodColor = mood === 'talking' ? '#22c55e' : mood === 'listening' ? '#a855f7' : '#be185d'
  const moodLabel = mood === 'talking' ? 'Speaking' : mood === 'listening' ? 'Listening...' : 'Ready'
  const moodBg = mood === 'talking' ? 'rgba(34,197,94,0.12)' : mood === 'listening' ? 'rgba(168,85,247,0.12)' : 'rgba(190,24,93,0.08)'

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'linear-gradient(150deg,#fdf2f8 0%,#f5f0ff 50%,#fce7f3 100%)' }}>
      <style>{`
        @keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
        @keyframes pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.5);opacity:0.4}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        .msg-in{animation:fadeIn 0.3s ease}
      `}</style>

      {/* ── HEADER ── */}
      <div style={{ background: 'rgba(253,242,248,0.96)', backdropFilter: 'blur(16px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
         <Link href="/"><button aria-label="Go back" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#be185d', padding: 4, display: 'flex', alignItems: 'center' }}><ArrowLeft size={20} /></button></Link>
          <div>
            <div style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: '0.95rem', lineHeight: 1.2 }}>Haven · Aria</div>
            <div style={{ fontSize: '0.6rem', color: '#8b6b7d' }}>Private & Confidential · 24/7</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: moodBg, border: `1px solid ${moodColor}44`, borderRadius: 20, padding: '4px 14px', transition: 'all 0.4s' }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: moodColor, animation: mood !== 'idle' ? 'pulse 1s infinite' : 'none', transition: 'background 0.3s' }} />
            <span style={{ fontSize: '0.7rem', fontWeight: 600, color: moodColor, transition: 'color 0.3s' }}>{moodLabel}</span>
          </div>
          <button aria-label={voiceOn ? 'Mute voice' : 'Enable voice'}onClick={() => { setVoiceOn(v => !v); synthRef.current?.cancel(); if (mood === 'talking') setMood('idle') }}
            title={voiceOn ? 'Mute voice' : 'Enable voice'}
            style={{ background: voiceOn ? 'rgba(190,24,93,0.08)' : 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: 7, cursor: 'pointer', display: 'flex', alignItems: 'center', transition: 'all 0.2s' }}>
            {voiceOn ? <Volume2 size={16} style={{ color: '#be185d' }} /> : <VolumeX size={16} style={{ color: '#8b6b7d' }} />}
          </button>
          <button  aria-label="Generate poem" onClick={generatePoem} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.15)', borderRadius: 8, padding: '7px 11px', cursor: 'pointer', fontSize: '0.72rem', color: '#be185d', fontWeight: 600 }}>
            <Sparkles size={13} />Poem
          </button>
        </div>
      </div>

      {/* ── MAIN ── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>

        {/* Avatar panel */}
        <div style={{ width: avatarSize + 40, flexShrink: 0, background: 'linear-gradient(180deg,#1a0a12 0%,#2d0f1f 60%,#1a0a12 100%)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative', overflow: 'hidden' }}>

          {/* Ambient glow behind avatar */}
          <div style={{ position: 'absolute', width: avatarSize * 1.4, height: avatarSize * 1.4, borderRadius: '50%', background: `radial-gradient(circle, ${moodColor}22 0%, transparent 70%)`, transition: 'background 0.6s', pointerEvents: 'none' }} />

          {/* Avatar */}
          <div style={{ position: 'relative', zIndex: 1 }}>
            <AriaCanvas ref={avatarRef} size={avatarSize} />
          </div>

          {/* Name tag */}
          <div style={{ position: 'absolute', bottom: 18, left: '50%', transform: 'translateX(-50%)', background: 'rgba(26,10,18,0.78)', backdropFilter: 'blur(8px)', borderRadius: 20, padding: '6px 20px', border: `1px solid ${moodColor}44`, whiteSpace: 'nowrap', transition: 'border-color 0.4s' }}>
            <p style={{ fontSize: '0.7rem', color: 'rgba(249,168,212,0.95)', fontFamily: 'Georgia', fontStyle: 'italic', margin: 0 }}>
              {mood === 'talking' ? '✦ Aria is speaking...' : mood === 'listening' ? '◉ Aria is listening...' : '● Aria · Here for you'}
            </p>
          </div>

          {/* Status pills */}
          <div style={{ position: 'absolute', top: 14, right: 10, display: 'flex', flexDirection: 'column', gap: 5 }}>
            {[['#be185d', 'Private'], ['#22c55e', 'Non-judgmental'], ['#a855f7', '24/7']].map(([c, l]) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'rgba(26,10,18,0.65)', borderRadius: 12, padding: '3px 9px', border: `1px solid ${c}33` }}>
                <div style={{ width: 5, height: 5, borderRadius: '50%', background: c }} />
                <span style={{ fontSize: '0.58rem', color: 'rgba(249,168,212,0.8)' }}>{l}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Chat panel */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'rgba(253,242,248,0.5)' }}>

          {/* Messages */}
          <div ref={chatRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 20px 8px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            {messages.map((msg, i) => (
              <div key={i} className="msg-in" style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {msg.role === 'assistant' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg,#be185d,#9d174d)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.65rem' }}>🌸</div>
                    <span style={{ fontSize: '0.65rem', color: '#be185d', fontWeight: 600 }}>Aria</span>
                  </div>
                )}
                <div style={{
                  maxWidth: '88%', padding: '12px 16px',
                  borderRadius: msg.role === 'user' ? '18px 18px 4px 18px' : '4px 18px 18px 18px',
                  background: msg.role === 'user' ? 'linear-gradient(135deg,#be185d,#9d174d)' : 'white',
                  color: msg.role === 'user' ? 'white' : '#1a0a12',
                  fontSize: '0.87rem', lineHeight: 1.65,
                  border: msg.role === 'assistant' ? '1px solid rgba(190,24,93,0.1)' : 'none',
                  boxShadow: msg.role === 'assistant' ? '0 2px 12px rgba(190,24,93,0.08)' : '0 2px 8px rgba(190,24,93,0.2)',
                }}>
                  {msg.content}
                </div>
                <span style={{ fontSize: '0.6rem', color: '#8b6b7d', marginTop: 3, padding: '0 4px' }}>{msg.time}</span>
              </div>
            ))}

            {loading && (
              <div className="msg-in" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg,#a855f7,#7c3aed)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.65rem' }}>🌸</div>
                  <span style={{ fontSize: '0.65rem', color: '#a855f7', fontWeight: 600 }}>Aria is thinking...</span>
                </div>
                <div style={{ background: 'white', borderRadius: '4px 18px 18px 18px', padding: '13px 18px', border: '1px solid rgba(168,85,247,0.15)', display: 'flex', gap: 6, alignItems: 'center' }}>
                  {[0, 1, 2].map(i => <div key={i} style={{ width: 8, height: 8, borderRadius: '50%', background: '#f9a8d4', animation: `bounce 1.1s infinite ${i * 0.18}s` }} />)}
                </div>
              </div>
            )}
          </div>

          {/* Quick replies */}
          <div style={{ padding: '6px 20px 4px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {QUICK.map(q => (
              <button aria-label="Send message" key={q} onClick={() => sendMessage(q)}
                style={{ fontSize: '0.7rem', padding: '5px 13px', borderRadius: 50, border: '1px solid rgba(190,24,93,0.22)', background: 'white', cursor: 'pointer', color: '#be185d', whiteSpace: 'nowrap', transition: 'all 0.18s' }}
                onMouseEnter={e => { e.currentTarget.style.background = '#fce7f3'; e.currentTarget.style.borderColor = '#be185d' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'white'; e.currentTarget.style.borderColor = 'rgba(190,24,93,0.22)' }}>
                {q}
              </button>
            ))}
          </div>

          {/* Input */}
          <div style={{ padding: '8px 20px 16px' }}>
            <div style={{ display: 'flex', gap: 8, background: 'white', borderRadius: 16, border: '2px solid rgba(190,24,93,0.18)', padding: '7px 7px 7px 16px', boxShadow: '0 4px 20px rgba(190,24,93,0.1)', transition: 'border-color 0.2s' }}
              onFocus={e => (e.currentTarget.style.borderColor = 'rgba(190,24,93,0.5)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'rgba(190,24,93,0.18)')}>
              <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder="Tell me how you're feeling..."
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: '0.88rem', fontFamily: 'Georgia', color: '#1a0a12', background: 'transparent', minWidth: 0 }}
              />
              <button aria-label="Send message"
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
                style={{ background: loading || !input.trim() ? 'rgba(190,24,93,0.2)' : 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '10px 16px', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0, transition: 'all 0.2s' }}>
                <Send size={15} />
              </button>
            </div>
            <p style={{ textAlign: 'center', fontSize: '0.6rem', color: '#8b6b7d', marginTop: 8 }}>
              Emergency: <strong>112</strong> · Women's Helpline: <strong>181</strong> · DV Helpline: <strong>1091</strong>
            </p>
          </div>
        </div>
      </div>

      {/* Poem modal */}
      {showPoem && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(26,10,18,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 20 }}>
          <div style={{ background: 'white', borderRadius: 24, padding: '36px 32px', maxWidth: 440, width: '100%', textAlign: 'center', boxShadow: '0 20px 60px rgba(190,24,93,0.2)', animation: 'fadeIn 0.3s ease' }}>
            <Sparkles size={30} style={{ color: '#be185d', display: 'block', margin: '0 auto 14px' }} />
            <h3 style={{ fontFamily: 'Georgia', fontSize: '1.1rem', color: '#be185d', marginBottom: 18 }}>A Poem for You</h3>
            <p style={{ fontFamily: 'Georgia', lineHeight: 2.1, color: '#1a0a12', whiteSpace: 'pre-line', fontStyle: 'italic', fontSize: '0.92rem' }}>{poem}</p>
            <button aria-label="Generate poem"onClick={() => setShowPoem(false)} style={{ marginTop: 22, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 50, padding: '11px 32px', cursor: 'pointer', fontWeight: 600, fontSize: '0.88rem' }}>Close</button>
          </div>
        </div>
      )}
    </div>
  )
}