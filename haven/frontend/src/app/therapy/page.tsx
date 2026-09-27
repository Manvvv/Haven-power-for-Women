'use client'
import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Send, Volume2, VolumeX, Sparkles, Wind, LifeBuoy, MessageCircle, Phone } from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import AriaCanvas, { AvatarHandle, AvatarMood } from '@/components/AriaCanvas'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { secureFetch } from '@/lib/api'
import { CrisisPanel, CalmDownPanel, GetHelpPanel } from '@/components/therapy/SafetyPanels'
import {
  Resource, CopingTool, ChatResponse, telHref, displayNumber,
  OFFLINE_EMERGENCY, DISCLAIMER,
} from '@/components/therapy/support'
// Deterministic warm-female voice selection for the browser Web Speech API.
// Kept in its own module so it can be unit-tested and so it doesn't run into
// Next's App Router page-export constraints.
import { pickVoice, leadLangCode } from '@/components/therapy/voice'

type PanelKind = 'none' | 'crisis' | 'calm' | 'help'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string; time: string }
function getTime() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }

export default function TherapyPage() {
  useHavenAuth()
  const { user } = useUser()
  const userId = user?.id || 'anon'
  const { lang, tn } = useLang()

  // Localized quick-reply prompts (spec §3 — no hardcoded strings on priority surfaces).
  const QUICK = [
    tn('mental_health', 'quickReply1'),
    tn('mental_health', 'quickReply2'),
    tn('mental_health', 'quickReply3'),
    tn('mental_health', 'quickReply4'),
  ]

  const chatRef = useRef<HTMLDivElement>(null)
  const avatarRef = useRef<AvatarHandle>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const synthRef = useRef<SpeechSynthesis | null>(null)
  const isMountedRef = useRef(true)
  // Live mirror of `voiceOn` so async code (a resolved TTS request) reads the
  // CURRENT toggle state, never a stale render closure.
  const voiceOnRef = useRef(true)
  // Generation token: bumped on every stop / new utterance so a superseded or
  // post-OFF utterance can be discarded even after its async request resolves.
  const speechGenRef = useRef(0)
  const [cachedVoices, setCachedVoices] = useState<SpeechSynthesisVoice[]>([])

  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: tn('mental_health', 'ariaGreeting'),
    time: getTime()
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [mood, setMoodState] = useState<AvatarMood>('idle')
  const [voiceOn, setVoiceOn] = useState(true)
  const [voiceUnavailable, setVoiceUnavailable] = useState(false)
  const [poem, setPoem] = useState('')
  const [showPoem, setShowPoem] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [showMobileAvatar, setShowMobileAvatar] = useState(false)
  const [avatarSize, setAvatarSize] = useState(300)

  // ── Safety-first UX state (spec §5, §6, §14, §33) ──
  const [panel, setPanel] = useState<PanelKind>('none')
  const [saveChat, setSaveChat] = useState(true)            // "Do not save" toggle (spec §14)
  const [emergencyRes, setEmergencyRes] = useState<Resource[]>([])   // from last crisis turn
  const [copingTools, setCopingTools] = useState<CopingTool[]>([])
  const [professionalRes, setProfessionalRes] = useState<Resource[]>([])
  const [safetyPlan, setSafetyPlan] = useState<Record<string, unknown> | null>(null)
  const [disclaimer, setDisclaimer] = useState<string>(DISCLAIMER)
  // Registry-backed resources for the footer + Get Help panel (single source, spec §4).
  const [registryEmergency, setRegistryEmergency] = useState<Resource[]>([])
  const [registryProfessional, setRegistryProfessional] = useState<Resource[]>([])
  const [resourcesOffline, setResourcesOffline] = useState(false)

  // Load the verified resource registry once so nothing is hardcoded in the UI.
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await secureFetch('/therapy/resources?category=all')
        if (!res.ok) throw new Error('bad status')
        const data = await res.json()
        if (!alive) return
        const em: Resource[] = [...(data.emergency || []), ...(data.crisis || [])]
        // De-duplicate by id/number while preserving priority order.
        const seen = new Set<string>()
        const merged = em.filter(r => {
          const key = r.id || r.number || ''
          if (seen.has(key)) return false
          seen.add(key); return true
        })
        setRegistryEmergency(merged.length ? merged : OFFLINE_EMERGENCY)
        setRegistryProfessional(data.professional || [])
        setResourcesOffline(false)
      } catch {
        if (!alive) return
        setRegistryEmergency(OFFLINE_EMERGENCY)   // spec §24/§29 offline fallback
        setResourcesOffline(true)
      }
    })()
    return () => { alive = false }
  }, [])

  // Responsive & Voice initialization
  useEffect(() => {
    isMountedRef.current = true
    if (typeof window === 'undefined') return
    synthRef.current = window.speechSynthesis

    // Part 12: if the browser has no Web Speech API, note it (non-blocking) so
    // the UI can tell the user text still works — but never crash.
    if (!window.speechSynthesis) setVoiceUnavailable(true)

    // Part 4: restore the persisted voice preference from a SINGLE namespaced
    // key. Runs in an effect (client-only) to avoid any SSR/hydration mismatch,
    // and is fully guarded so private-mode / disabled storage can't throw.
    try {
      const saved = window.localStorage.getItem('haven_aria_voice_enabled')
      if (saved === '0') { setVoiceOn(false); voiceOnRef.current = false }
      else if (saved === '1') { setVoiceOn(true); voiceOnRef.current = true }
    } catch { /* storage unavailable — keep the default (voice ON) */ }

    const updateVoices = () => {
      if (synthRef.current) {
        const vList = synthRef.current.getVoices()
        if (vList.length > 0 && isMountedRef.current) {
          setCachedVoices(vList)
        }
      }
    }
    updateVoices()
    if (window.speechSynthesis) {
      window.speechSynthesis.onvoiceschanged = updateVoices
    }

    const update = () => {
      const w = window.innerWidth
      const mobile = w < 768
      if (isMountedRef.current) {
        setIsMobile(mobile)
        if (mobile) {
          setAvatarSize(Math.min(Math.floor(w * 0.55), 220))
        } else {
          setAvatarSize(Math.min(Math.floor(w * 0.28), 320))
        }
      }
    }
    update()
    window.addEventListener('resize', update)
    return () => {
      isMountedRef.current = false
      window.removeEventListener('resize', update)
      if (synthRef.current) {
        synthRef.current.cancel()
      }
    }
  }, [])

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Re-localize the opening greeting when the language changes — but ONLY while the
  // conversation is still just that greeting. Never rewrites an in-progress chat
  // (spec §25: switching language must not erase/rewrite the conversation).
  useEffect(() => {
    setMessages(prev => {
      if (prev.length === 1 && prev[0].role === 'assistant') {
        return [{ ...prev[0], content: tn('mental_health', 'ariaGreeting') }]
      }
      return prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang])

  const setMood = useCallback((m: AvatarMood) => {
    if (!isMountedRef.current) return
    setMoodState(m)
    avatarRef.current?.setMood(m)
  }, [])

  // Hard-stop any speech NOW and invalidate anything pending/queued. Bumping the
  // generation token means a TTS request that resolves later is discarded, and
  // `cancel()` silences whatever is currently being spoken (Part 2).
  const stopSpeaking = useCallback(() => {
    speechGenRef.current += 1
    try { synthRef.current?.cancel() } catch { /* ignore */ }
    if (isMountedRef.current) setMood('idle')
  }, [setMood])

  // Keep the async-safe mirror in sync, stop speech the instant voice is turned
  // OFF, and persist the choice. Independent of `lang`, so switching language
  // never resets the voice preference (Part 9).
  useEffect(() => {
    voiceOnRef.current = voiceOn
    if (!voiceOn) stopSpeaking()
    try {
      window.localStorage.setItem('haven_aria_voice_enabled', voiceOn ? '1' : '0')
    } catch { /* storage unavailable — preference is still honored in-session */ }
  }, [voiceOn, stopSpeaking])

  const speak = useCallback((text: string) => {
    if (typeof window === 'undefined' || !synthRef.current) {
      // Part 12: TTS engine missing — surface a gentle note, keep text working.
      if (voiceOnRef.current) setVoiceUnavailable(true)
      return
    }
    // Always silence any current utterance before deciding what to do next.
    try { synthRef.current.cancel() } catch { /* ignore */ }

    // Respect the LIVE toggle, not the closure captured when this was created.
    if (!voiceOnRef.current) { setMood('idle'); return }

    const gen = ++speechGenRef.current   // this utterance's generation

    const utter = new SpeechSynthesisUtterance(text)
    utter.rate = 0.95      // gentle, natural pace
    utter.pitch = 1.1      // warm and soft — not shrill, not dramatic
    utter.volume = 1

    const voices = cachedVoices.length > 0 ? cachedVoices : synthRef.current.getVoices()
    const chosen = pickVoice(voices, lang)
    // Fall back to the language's lead code if no named voice matched at all.
    utter.lang = leadLangCode(lang)
    if (chosen) { utter.voice = chosen; utter.lang = chosen.lang }

    // Guard every callback: ignore a superseded utterance (older generation) or
    // one that resolved after the user turned voice off.
    utter.onstart = () => {
      if (isMountedRef.current && voiceOnRef.current && gen === speechGenRef.current) setMood('talking')
    }
    utter.onend = () => {
      if (isMountedRef.current && gen === speechGenRef.current) setMood('idle')
    }
    utter.onerror = () => {
      if (isMountedRef.current && gen === speechGenRef.current) setMood('idle')
    }

    synthRef.current.speak(utter)
  }, [lang, cachedVoices, setMood])

  const sendMessage = async (msg?: string) => {
    const text = msg || input
    if (!text.trim() || loading) return
    setMessages(prev => [...prev, { role: 'user', content: text, time: getTime() }])
    setInput('')
    setLoading(true)
    setMood('listening')
    // Snapshot the speech generation at send time. If the user turns voice off
    // (which bumps the token via stopSpeaking) while this request is in flight,
    // the guard below drops the resolved reply instead of speaking it (Part 10 #3).
    const genAtSend = speechGenRef.current
    try {
      const res = await secureFetch('/therapy/chat', {
        method: 'POST',
        // New safety-first contract: language hint + per-turn privacy control (spec §14).
        // user_id kept for backward compatibility with the anonymous path.
        body: JSON.stringify({ message: text, user_id: userId, session_id: sessionId, language: lang, save: saveChat })
      })
      if (!res.ok) throw new Error('Server returned error')
      const data = await res.json() as ChatResponse
      const reply = data.response || "I'm here with you."
      if (isMountedRef.current) {
        setMessages(prev => [...prev, { role: 'assistant', content: reply, time: getTime() }])
        if (data.session_id) setSessionId(data.session_id)
        // Absorb structured safety fields (registry-driven; never fabricated).
        if (data.coping_tools?.length) setCopingTools(data.coping_tools)
        if (data.professional_resources?.length) setProfessionalRes(data.professional_resources)
        if (data.disclaimer) setDisclaimer(data.disclaimer)
        setSafetyPlan(data.safety_plan ?? null)
        // A gentle clarifying question when triage was ambiguous (spec §7).
        if (data.needs_clarification && data.clarifying_question &&
            !reply.includes(data.clarifying_question)) {
          setMessages(prev => [...prev, { role: 'assistant', content: data.clarifying_question as string, time: getTime() }])
        }
        // Crisis → surface the emergency-first panel automatically (spec §5).
        if (data.crisis) {
          setEmergencyRes(data.emergency_resources || [])
          setPanel('crisis')
        }
        // Only speak if voice is still ON and no OFF-toggle invalidated this
        // request while it was in flight (Part 2 / Part 10 #3).
        if (voiceOnRef.current && genAtSend === speechGenRef.current) speak(reply)
      }
    } catch {
      if (isMountedRef.current) {
        setMood('idle')
        // Never leave the user without a path to help if the network fails (spec §29).
        setMessages(prev => [...prev, { role: 'assistant', content: tn('errors', 'aiUnavailable'), time: getTime() }])
        setResourcesOffline(true)
        if (registryEmergency.length === 0) setRegistryEmergency(OFFLINE_EMERGENCY)
      }
    } finally {
      if (isMountedRef.current) setLoading(false)
    }
  }

  const generatePoem = async () => {
    try {
      const res = await secureFetch('/generate-poem', {
        method: 'POST',
        body: JSON.stringify({ emotional_state: 'distressed and in need of hope' })
      })
      if (!res.ok) throw new Error('Server returned error')
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
            <button aria-label={tn('mental_health', 'goBack')} title={tn('mental_health', 'goBack')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#be185d', padding: 4, display: 'flex', alignItems: 'center' }}>
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
          <span style={{ fontSize: '0.68rem', background: '#fdf2f8', border: '1px solid rgba(190,24,93,0.2)', padding: '4px 8px', borderRadius: 8, color: '#be185d', fontWeight: 600 }}>
            🗣️ {lang.toUpperCase()}
          </span>
          <LanguageSelector compact />
          <button
            aria-label={voiceOn ? tn('mental_health', 'toggleVoiceOff') : tn('mental_health', 'toggleVoiceOn')}
            aria-pressed={voiceOn}
            title={voiceOn ? tn('mental_health', 'toggleVoiceOff') : tn('mental_health', 'toggleVoiceOn')}
            onClick={() => {
              const next = !voiceOn
              setVoiceOn(next)
              // Turning OFF must stop speech immediately, not on next render.
              if (!next) stopSpeaking()
            }}
            style={{ background: voiceOn ? 'rgba(190,24,93,0.1)' : 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '6px', cursor: 'pointer', display: 'flex' }}
          >
            {voiceOn ? <Volume2 size={15} style={{ color: '#be185d' }} /> : <VolumeX size={15} style={{ color: '#8b6b7d' }} />}
          </button>
          <button
            aria-label={tn('mental_health', 'generatePoem')}
            title={tn('mental_health', 'generatePoem')}
            onClick={generatePoem}
            style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(190,24,93,0.08)', border: '1px solid rgba(190,24,93,0.15)', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', fontSize: 'clamp(0.65rem, 2vw, 0.72rem)', color: '#be185d', fontWeight: 600 }}
          >
            <Sparkles size={13} /><span>{tn('mental_health', 'poem')}</span>
          </button>
        </div>
      </div>

      {/* ── PRIMARY ACTIONS: Talk · Calm Down · Get Help (spec §33) ── */}
      <div style={{
        display: 'flex', gap: 6, padding: '8px clamp(12px,3vw,20px)', flexShrink: 0,
        background: 'rgba(253,242,248,0.6)', borderBottom: '1px solid rgba(190,24,93,0.08)', zIndex: 9,
      }}>
        {[
          { key: 'talk' as const, label: tn('mental_health', 'btnTalk'), Icon: MessageCircle, onClick: () => { setPanel('none'); inputRef.current?.focus() } },
          { key: 'calm' as const, label: tn('mental_health', 'btnCalm'), Icon: Wind, onClick: () => setPanel('calm') },
          { key: 'help' as const, label: tn('mental_health', 'btnGetHelp'), Icon: LifeBuoy, onClick: () => setPanel('help') },
        ].map(({ key, label, Icon, onClick }) => (
          <button key={key} onClick={onClick} aria-label={label} title={label}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              background: 'white', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 12,
              padding: '9px 8px', cursor: 'pointer', color: '#be185d', fontWeight: 700,
              fontSize: 'clamp(0.72rem,2.4vw,0.82rem)', minHeight: 42, transition: 'all 0.18s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#fce7f3' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'white' }}>
            <Icon size={15} /> {label}
          </button>
        ))}
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
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder={tn('mental_health', 'therapyPlaceholder')}
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 'clamp(0.82rem, 2.5vw, 0.88rem)', fontFamily: 'Georgia', color: '#1a0a12', background: 'transparent', minWidth: 0 }}
              />
              <button
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
                title={tn('accessibility', 'sendMessage')}
                aria-label={tn('accessibility', 'sendMessage')}
                style={{ background: loading || !input.trim() ? 'rgba(190,24,93,0.2)' : 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '9px 14px', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0, transition: 'all 0.2s' }}
              >
                <Send size={15} />
              </button>
            </div>
            {/* Part 12: non-blocking notice when the browser has no speech engine.
                Text chat is unaffected; this never blocks input. */}
            {voiceUnavailable && (
              <div role="status" aria-live="polite" style={{ marginTop: 8, fontSize: '0.62rem', color: '#8b6b7d', display: 'flex', alignItems: 'center', gap: 5 }}>
                <VolumeX size={12} style={{ color: '#8b6b7d' }} /> {tn('mental_health', 'voiceUnavailable')}
              </div>
            )}
            {/* Privacy control (spec §14) + registry-driven emergency numbers (spec §4) */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.62rem', color: '#8b6b7d', cursor: 'pointer', userSelect: 'none' }} title="When on, this conversation is not stored anywhere.">
                <input
                  type="checkbox"
                  checked={!saveChat}
                  onChange={e => setSaveChat(!e.target.checked)}
                  aria-label={tn('mental_health', 'dontSave')}
                  style={{ accentColor: '#be185d', width: 14, height: 14, cursor: 'pointer' }}
                />
                {tn('mental_health', 'dontSave')}
              </label>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: '0.62rem', color: '#8b6b7d', flexWrap: 'wrap' }}>
                {(() => {
                  const src = registryEmergency.length ? registryEmergency : OFFLINE_EMERGENCY
                  const e112 = src.find(r => displayNumber(r) === '112')
                  const tele = src.find(r => displayNumber(r) === '14416')
                  return (
                    <>
                      {e112 && <a href={telHref('112')} style={{ color: '#b91c1c', fontWeight: 700, textDecoration: 'none' }} aria-label="Call emergency services 112"><Phone size={10} style={{ verticalAlign: -1 }} /> Emergency 112</a>}
                      {tele && <a href={telHref('14416')} style={{ color: '#be185d', fontWeight: 700, textDecoration: 'none' }} aria-label="Call Tele-MANAS 14416">Tele-MANAS 14416</a>}
                      <button onClick={() => setPanel('help')} style={{ background: 'none', border: 'none', color: '#7c3aed', fontWeight: 700, cursor: 'pointer', fontSize: '0.62rem', padding: 0 }}>{tn('mental_health', 'moreHelp')} →</button>
                    </>
                  )
                })()}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── SAFETY PANELS (crisis auto-opens; calm/help are user-initiated) ── */}
      <CrisisPanel
        open={panel === 'crisis'}
        onClose={() => setPanel('none')}
        onCalmDown={() => setPanel('calm')}
        resources={emergencyRes.length ? emergencyRes : registryEmergency}
        safetyPlan={safetyPlan}
        disclaimer={disclaimer}
      />
      <CalmDownPanel
        open={panel === 'calm'}
        onClose={() => setPanel('none')}
        onGetHelp={() => setPanel('help')}
        tools={copingTools}
      />
      <GetHelpPanel
        open={panel === 'help'}
        onClose={() => setPanel('none')}
        emergency={registryEmergency.length ? registryEmergency : emergencyRes}
        professional={professionalRes.length ? professionalRes : registryProfessional}
        disclaimer={disclaimer}
        offline={resourcesOffline}
      />

      {/* ── POEM MODAL ── */}
      {showPoem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(26,10,18,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 'clamp(16px,4vw,24px)' }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 'clamp(24px,5vw,36px) clamp(20px,4vw,32px)', maxWidth: 440, width: '100%', textAlign: 'center', boxShadow: '0 20px 60px rgba(190,24,93,0.2)', animation: 'fadeIn 0.3s ease' }}>
            <Sparkles size={28} style={{ color: '#be185d', display: 'block', margin: '0 auto 12px' }} />
            <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(1rem, 3vw, 1.1rem)', color: '#be185d', marginBottom: 16 }}>{tn('mental_health', 'aPoemForYou')}</h3>
            <p style={{ fontFamily: 'Georgia', lineHeight: 2, color: '#1a0a12', whiteSpace: 'pre-line', fontStyle: 'italic', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>{poem}</p>
            <button onClick={() => setShowPoem(false)} aria-label={tn('common', 'close')} title={tn('common', 'close')} style={{ marginTop: 20, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 50, padding: '10px 28px', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>{tn('common', 'close')}</button>
          </div>
        </div>
      )}
    </div>
  )
}
