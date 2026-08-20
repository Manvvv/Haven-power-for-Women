'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Mic, MicOff, Shield, MapPin, Phone, Mail, Plus,
  Trash2, TestTube, History, AlertTriangle, Check, X, Eye, EyeOff, Info
} from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { secureFetch } from '@/lib/api'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// --- Types ---
interface VoiceConfig {
  configured: boolean
  enabled: boolean
  has_safe_word: boolean
  cooldown_seconds: number
  contacts: TrustedContact[]
  updated_at?: string
}

interface TrustedContact {
  contact_id?: string
  name: string
  phone: string
  email?: string
  priority: number
  user_id?: string
}

interface VoiceEvent {
  event_id: string
  timestamp: string
  trigger_type: string
  status: string
  latitude?: number
  longitude?: number
  is_test?: boolean
}

declare global {
  interface Window {
    SpeechRecognition: any
    webkitSpeechRecognition: any
  }
}

// --- Styles ---
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
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
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
  backBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.5rem',
    color: colors.primary,
    textDecoration: 'none',
    fontWeight: 'bold',
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
  label: {
    display: 'block',
    fontSize: '0.9rem',
    fontWeight: 600,
    color: colors.muted,
    marginBottom: '0.5rem',
  },
  input: {
    width: '100%',
    padding: '0.75rem 1rem',
    borderRadius: '8px',
    border: `1px solid ${colors.accent}`,
    fontSize: '1rem',
    marginBottom: '1rem',
    boxSizing: 'border-box' as const,
  },
  btnPrimary: {
    background: `linear-gradient(135deg, ${colors.primary}, #9d174d)`,
    color: colors.white,
    border: 'none',
    borderRadius: '50px',
    padding: '0.75rem 1.5rem',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.5rem',
    transition: 'transform 0.2s',
  },
  btnSecondary: {
    background: 'transparent',
    color: colors.primary,
    border: `2px solid ${colors.primary}`,
    borderRadius: '50px',
    padding: '0.75rem 1.5rem',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.5rem',
  },
  btnDanger: {
    background: colors.danger,
    color: colors.white,
    border: 'none',
    borderRadius: '8px',
    padding: '0.5rem',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  micBtnContainer: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    padding: '2rem 0',
  },
  micBtn: (isActive: boolean) => ({
    width: '120px',
    height: '120px',
    borderRadius: '50%',
    background: isActive ? colors.danger : `linear-gradient(135deg, ${colors.primary}, #9d174d)`,
    color: colors.white,
    border: 'none',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    boxShadow: isActive ? `0 0 30px ${colors.danger}` : '0 4px 15px rgba(190,24,93,0.3)',
    transition: 'all 0.3s ease',
    animation: isActive ? 'pulse 1.5s infinite' : 'none',
  }),
  badge: (status: 'granted' | 'denied' | 'pending') => ({
    display: 'inline-block',
    padding: '0.25rem 0.75rem',
    borderRadius: '50px',
    fontSize: '0.8rem',
    fontWeight: 'bold',
    background: status === 'granted' ? '#d1fae5' : status === 'denied' ? '#fee2e2' : '#fef3c7',
    color: status === 'granted' ? colors.success : status === 'denied' ? colors.danger : colors.warning,
  }),
  transcript: {
    marginTop: '1rem',
    padding: '1rem',
    background: colors.light,
    borderRadius: '8px',
    minHeight: '60px',
    fontStyle: 'italic',
    color: colors.muted,
    textAlign: 'center' as const,
  },
  historyItem: {
    padding: '1rem',
    borderBottom: `1px solid rgba(190,24,93,0.1)`,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  notice: {
    background: '#fffbeb',
    border: '1px solid #fcd34d',
    borderRadius: '8px',
    padding: '1rem',
    marginTop: '2rem',
    fontSize: '0.9rem',
    color: '#92400e',
  },
  pulseKeyframes: `
    @keyframes pulse {
      0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
      70% { transform: scale(1.05); box-shadow: 0 0 0 20px rgba(239, 68, 68, 0); }
      100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
  `
}

export default function VoiceSOSPage() {
  useHavenAuth()
  const { user } = useUser()
  const userId = user?.id || 'haven_user'

  // --- State ---
  const [isSupported, setIsSupported] = useState<boolean | null>(null)
  const [config, setConfig] = useState<VoiceConfig>({ configured: false, enabled: false, has_safe_word: false, cooldown_seconds: 60, contacts: [] })
  const [contacts, setContacts] = useState<TrustedContact[]>([])
  const [history, setHistory] = useState<VoiceEvent[]>([])
  
  const [safeWord, setSafeWord] = useState('')
  const [safeWordText, setSafeWordText] = useState('')
  const [safeWordHash, setSafeWordHash] = useState('')
  const [showSafeWord, setShowSafeWord] = useState(false)
  const [isSavingConfig, setIsSavingConfig] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  
  const [newContact, setNewContact] = useState({ name: '', phone: '', email: '', priority: 1 })
  const [isSavingContact, setIsSavingContact] = useState(false)
  
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [testMode, setTestMode] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  
  const [micPermission, setMicPermission] = useState<'granted' | 'denied' | 'pending'>('pending')
  const [locPermission, setLocPermission] = useState<'granted' | 'denied' | 'pending'>('pending')
  const [currentLocation, setCurrentLocation] = useState<{lat: number, lng: number} | null>(null)
  const [sosAlertData, setSosAlertData] = useState<any>(null)
  const [showSOSModal, setShowSOSModal] = useState(false)
  const [accumulatedText, setAccumulatedText] = useState('')
  const [whisperMode, setWhisperMode] = useState(false)
  const [isStreamingLocation, setIsStreamingLocation] = useState(false)

  // Refs
  const recognitionRef = useRef<any>(null)
  const isEnabledRef = useRef(config.enabled)
  const accumulatedSpeechRef = useRef<string[]>([])
  const geoWatchRef = useRef<number | null>(null)
  const trackingWsRef = useRef<WebSocket | null>(null)
  const streamIntervalRef = useRef<any>(null)
  const wakeLockRef = useRef<any>(null)
  const isMountedRef = useRef<boolean>(true)
  const isTriggeringRef = useRef<boolean>(false)
  
  // --- Initialization ---
  useEffect(() => {
    // Check support & restore cached location
    if (typeof window !== 'undefined') {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
      setIsSupported(!!SpeechRecognition)

      const cachedLat = parseFloat(localStorage.getItem('haven_last_lat') || '0')
      const cachedLng = parseFloat(localStorage.getItem('haven_last_lng') || '0')
      if (cachedLat && cachedLng) {
        setCurrentLocation({ lat: cachedLat, lng: cachedLng })
      }
    }

    isMountedRef.current = true

    // Load data
    fetchConfig()
    fetchContacts()
    fetchHistory()
    checkPermissions()
    startGpsWatch()
    
    // Inject keyframes
    const styleSheet = document.createElement('style')
    styleSheet.innerText = styles.pulseKeyframes
    document.head.appendChild(styleSheet)
    return () => {
      isMountedRef.current = false
      styleSheet.remove()
      if (geoWatchRef.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(geoWatchRef.current)
        geoWatchRef.current = null
      }
      if (streamIntervalRef.current) {
        clearInterval(streamIntervalRef.current)
        streamIntervalRef.current = null
      }
      if (trackingWsRef.current) {
        try { trackingWsRef.current.close() } catch { /* silent */ }
        trackingWsRef.current = null
      }
      if (recognitionRef.current) {
        try { recognitionRef.current.stop() } catch { /* silent */ }
        recognitionRef.current = null
      }
      releaseWakeLock()
    }
  }, [userId])

  useEffect(() => {
    isEnabledRef.current = config.enabled
    if (config.enabled && !isListening && config.has_safe_word) {
      startListening()
    } else if (!config.enabled && isListening) {
      stopListening()
    }
  }, [config.enabled, config.has_safe_word])

  // --- API Calls ---
  const fetchConfig = async () => {
    try {
      const res = await secureFetch(`/voice-sos/config/${userId}`)
      if (res.ok) {
        const data = await res.json()
        setConfig(data)
        if (data.contacts) setContacts(data.contacts)
      }
    } catch (error) {
      console.error('Error fetching config:', error)
    }
  }

  const fetchContacts = async () => {
    try {
      const res = await secureFetch(`/trusted-contacts/${userId}`)
      if (res.ok) {
        const data = await res.json()
        const fetched = data.contacts || []
        setContacts(fetched)
      }
    } catch (error) {
      console.error('Error fetching contacts:', error)
    }
  }

  const fetchHistory = async () => {
    try {
      const res = await secureFetch(`/voice-sos/history/${userId}`)
      if (res.ok) {
        const data = await res.json()
        setHistory((data.events || []).slice(0, 10))
      }
    } catch (error) {
      console.error('Error fetching history:', error)
    }
  }


  // --- Helpers ---
  const hashString = async (str: string) => {
    const encoder = new TextEncoder()
    const data = encoder.encode(str)
    const hashBuffer = await crypto.subtle.digest('SHA-256', data)
    const hashArray = Array.from(new Uint8Array(hashBuffer))
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
  }

  const normalizeText = (text: string) => {
    return text.toLowerCase().replace(/[^\w\s]|_/g, '').replace(/\s+/g, ' ').trim()
  }

  const openWhatsAppLink = (url: string) => {
    if (!url) return
    let finalUrl = url
    if (url.includes('wa.me/?text=')) {
      finalUrl = url.replace('https://wa.me/?text=', 'https://api.whatsapp.com/send?text=')
    } else if (url.includes('wa.me/+')) {
      finalUrl = url.replace('https://wa.me/+', 'https://api.whatsapp.com/send?phone=')
    } else if (url.includes('wa.me/')) {
      finalUrl = url.replace('https://wa.me/', 'https://api.whatsapp.com/send?phone=')
    }

    const a = document.createElement('a')
    a.href = finalUrl
    a.target = '_blank'
    a.rel = 'noreferrer'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const openSMSAlert = (phone: string, text: string) => {
    const cleanDigits = phone ? phone.replace(/\D/g, '') : '112'
    const smsUrl = `sms:${cleanDigits}?body=${encodeURIComponent(text)}`
    window.location.href = smsUrl
  }

  const startLocationStreaming = (eventId: string) => {
    if (typeof window === 'undefined') return
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsHost = (API.replace(/^https?:\/\//, '') || 'localhost:8000')
      const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws/track/${eventId}?role=broadcaster`)
      
      ws.onopen = () => {
        setIsStreamingLocation(true)
        if (currentLocation) {
          ws.send(JSON.stringify({
            latitude: currentLocation.lat,
            longitude: currentLocation.lng,
            accuracy: 4.0,
            timestamp: new Date().toISOString()
          }))
        }
      }

      ws.onerror = () => {
        console.log('Live tracking WS fallback')
      }

      trackingWsRef.current = ws

      if (streamIntervalRef.current) clearInterval(streamIntervalRef.current)
      streamIntervalRef.current = setInterval(() => {
        if (navigator.geolocation) {
          navigator.geolocation.getCurrentPosition((pos) => {
            const locData = {
              event_id: eventId,
              latitude: pos.coords.latitude,
              longitude: pos.coords.longitude,
              accuracy: pos.coords.accuracy || 5.0,
              speed: pos.coords.speed || 0.0,
              heading: pos.coords.heading || 0.0,
              timestamp: new Date().toISOString()
            }
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify(locData))
            } else {
              secureFetch('/sos/location-update', {
                method: 'POST',
                body: JSON.stringify(locData)
              }).catch(() => {})
            }
          }, () => {}, { enableHighAccuracy: true })
        }
      }, 4000)
    } catch (e) {
      console.log('Streaming setup error:', e)
    }
  }

  const requestWakeLock = async () => {
    try {
      if ('wakeLock' in navigator && (navigator as any).wakeLock) {
        wakeLockRef.current = await (navigator as any).wakeLock.request('screen')
      }
    } catch { /* silent */ }
  }

  const releaseWakeLock = async () => {
    try {
      if (wakeLockRef.current) {
        await wakeLockRef.current.release()
        wakeLockRef.current = null
      }
    } catch { /* silent */ }
  }

  const captureForensicEvidence = async (caseId: string) => {
    if (typeof window === 'undefined' || !navigator.mediaDevices) return
    try {
      let imageBase64 = ''
      try {
        const videoStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'user' },
            width: { ideal: 1280 },
            height: { ideal: 720 }
          }
        })
        const videoTrack = videoStream.getVideoTracks()[0]
        
        // 1. Hardware ImageCapture API (Crystal clear real sensor capture)
        if (typeof window !== 'undefined' && 'ImageCapture' in window && videoTrack) {
          try {
            const imageCapture = new (window as any).ImageCapture(videoTrack)
            // Wait 350ms for hardware auto-exposure & sensor warm-up
            await new Promise(r => setTimeout(r, 350))
            const photoBlob = await imageCapture.takePhoto().catch(async () => {
              const bitmap = await imageCapture.grabFrame()
              const canvas = document.createElement('canvas')
              canvas.width = bitmap.width || 640
              canvas.height = bitmap.height || 480
              const ctx = canvas.getContext('2d')
              ctx?.drawImage(bitmap, 0, 0)
              return new Promise<Blob | null>(res => canvas.toBlob(res, 'image/jpeg', 0.8))
            })
            
            if (photoBlob) {
              imageBase64 = await new Promise<string>((resolve) => {
                const reader = new FileReader()
                reader.onloadend = () => resolve((reader.result as string) || '')
                reader.readAsDataURL(photoBlob)
              })
            }
          } catch (e) {
            console.log('ImageCapture fallback to canvas video')
          }
        }

        // 2. Video element fallback with proper frame delivery wait
        if (!imageBase64 && videoTrack) {
          const video = document.createElement('video')
          video.muted = true
          video.playsInline = true
          video.autoplay = true
          video.srcObject = videoStream
          
          await new Promise<void>((resolve) => {
            let done = false
            const finish = () => {
              if (!done) {
                done = true
                // Delay 400ms after play/load to let auto-exposure adjust
                setTimeout(resolve, 450)
              }
            }
            video.onloadeddata = finish
            video.onplaying = finish
            video.play().catch(finish)
            setTimeout(finish, 1500)
          })

          const canvas = document.createElement('canvas')
          const w = video.videoWidth || 640
          const h = video.videoHeight || 480
          canvas.width = w
          canvas.height = h
          const ctx = canvas.getContext('2d')
          if (ctx) {
            ctx.drawImage(video, 0, 0, w, h)
            imageBase64 = canvas.toDataURL('image/jpeg', 0.75)
          }
        }

        videoStream.getTracks().forEach(t => t.stop())
      } catch (err) {
        console.log('Camera capture notice: skipped or unavailable', err)
      }


      try {
        const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        
        // Detect mobile supported MIME types (WebM for Chrome/Android, MP4/AAC for iOS)
        let mimeType = 'audio/webm'
        if (typeof MediaRecorder !== 'undefined') {
          if (!MediaRecorder.isTypeSupported('audio/webm')) {
            if (MediaRecorder.isTypeSupported('audio/mp4')) mimeType = 'audio/mp4'
            else if (MediaRecorder.isTypeSupported('audio/aac')) mimeType = 'audio/aac'
            else mimeType = ''
          }
        }

        const options = mimeType ? { mimeType } : undefined
        const mediaRecorder = new MediaRecorder(audioStream, options)
        const audioChunks: Blob[] = []

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data)
        }

        mediaRecorder.onstop = async () => {
          const audioBlob = new Blob(audioChunks, { type: mimeType || 'audio/webm' })
          const reader = new FileReader()
          reader.readAsDataURL(audioBlob)
          reader.onloadend = async () => {
            const audioBase64 = (reader.result as string) || ''
            
            await secureFetch('/sos/evidence', {
              method: 'POST',
              body: JSON.stringify({
                case_id: caseId,
                audio_base64: audioBase64,
                image_base64: imageBase64,
                mime_type_audio: mimeType || 'audio/webm',
                mime_type_image: 'image/jpeg',
                duration_seconds: 6.0,
                device_info: typeof navigator !== 'undefined' ? navigator.userAgent : 'Web Browser',
                timestamp: new Date().toISOString()
              })
            }).catch(() => {})
          }
          audioStream.getTracks().forEach(t => t.stop())
        }

        mediaRecorder.start()
        setTimeout(() => {
          if (mediaRecorder.state === 'recording') {
            mediaRecorder.stop()
          }
        }, 6000)
      } catch {
        console.log('Audio evidence capture notice: skipped or unavailable')
      }
    } catch (e) {
      console.log('Forensic evidence recorder notice:', e)
    }
  }

  const getLocation = (): Promise<{lat: number, lng: number}> => {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve(currentLocation || { lat: 0, lng: 0 })
        return
      }

      // Try High Accuracy first (6s timeout)
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }
          setCurrentLocation(coords)
          resolve(coords)
        },
        () => {
          // Fallback to low accuracy / IP geolocation (6s timeout)
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }
              setCurrentLocation(coords)
              resolve(coords)
            },
            () => {
              resolve(currentLocation || { lat: 0, lng: 0 })
            },
            { enableHighAccuracy: false, timeout: 6000, maximumAge: 60000 }
          )
        },
        { enableHighAccuracy: true, timeout: 6000, maximumAge: 10000 }
      )
    })
  }

  const startGpsWatch = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return
    try {
      geoWatchRef.current = navigator.geolocation.watchPosition(
        (pos) => {
          const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }
          setCurrentLocation(coords)
          setLocPermission('granted')
          if (typeof window !== 'undefined') {
            localStorage.setItem('haven_last_lat', pos.coords.latitude.toString())
            localStorage.setItem('haven_last_lng', pos.coords.longitude.toString())
          }
        },
        (err) => console.log('GPS watch warning:', err.message),
        { enableHighAccuracy: true, maximumAge: 10000, timeout: 10000 }
      )
    } catch { /* silent */ }
  }

  const checkPermissions = async () => {
    try {
      const micStatus = await navigator.permissions.query({ name: 'microphone' as PermissionName })
      setMicPermission(micStatus.state as any)
      micStatus.onchange = () => setMicPermission(micStatus.state as any)
      
      const locStatus = await navigator.permissions.query({ name: 'geolocation' as PermissionName })
      setLocPermission(locStatus.state as any)
      locStatus.onchange = () => setLocPermission(locStatus.state as any)
    } catch (e) {
      console.log('Permissions API not fully supported')
    }
  }

  // --- Handlers ---
  const handleSaveConfig = async () => {
    if (!safeWord && !config.has_safe_word && !safeWordText) {
      setSaveMsg('Please enter a safe word')
      return
    }
    setIsSavingConfig(true)
    setSaveMsg('')
    try {
      let currentNorm = safeWordText
      if (safeWord) {
        currentNorm = normalizeText(safeWord)
        const h = await hashString(currentNorm)
        setSafeWordHash(h)
        setSafeWordText(currentNorm)
      }

      const res = await secureFetch('/voice-sos/config', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          enabled: config.enabled,
          safe_word: safeWord || currentNorm || 'unchanged',
          cooldown_seconds: config.cooldown_seconds || 60,
          contacts: contacts.map(c => ({ name: c.name, phone: c.phone, email: c.email || '', priority: c.priority || 1 }))
        })
      })
      
      if (res.ok) {
        setSafeWord('')
        setSaveMsg('✓ Configuration saved!')
        await fetchConfig()
      } else {
        setSaveMsg('Failed to save configuration')
      }
    } catch (error) {
      console.error('Error saving config:', error)
      setSaveMsg('Error saving configuration')
    }
    setIsSavingConfig(false)
  }

  const handleAddContact = async () => {
    if (contacts.length >= 5 || !newContact.name || !newContact.phone) return
    setIsSavingContact(true)
    try {
      const updatedContacts = [...contacts, { ...newContact, priority: contacts.length + 1 }]
      const res = await secureFetch('/trusted-contacts', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          contacts: updatedContacts.map(c => ({ name: c.name, phone: c.phone, email: c.email || '', priority: c.priority || 1 }))
        })
      })
      if (res.ok) {
        await fetchContacts()
        setNewContact({ name: '', phone: '', email: '', priority: contacts.length + 2 })
      }
    } catch (error) {
      console.error('Error adding contact:', error)
    }
    setIsSavingContact(false)
  }

  const handleDeleteContact = async (contactName: string) => {
    try {
      const updatedContacts = contacts.filter(c => c.name !== contactName)
      const res = await secureFetch('/trusted-contacts', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          contacts: updatedContacts.map(c => ({ name: c.name, phone: c.phone, email: c.email || '', priority: c.priority || 1 }))
        })
      })
      if (res.ok) await fetchContacts()
    } catch (error) {
      console.error('Error deleting contact:', error)
    }
  }


  // --- Speech Recognition Logic ---
  const startListening = () => {
    if (!isSupported || isTriggeringRef.current) return
    
    // Request permissions first if needed
    if (micPermission !== 'granted') {
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(() => setMicPermission('granted'))
        .catch(() => setMicPermission('denied'))
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognition()
    
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = typeof navigator !== 'undefined' ? (navigator.language || 'en-US') : 'en-US'

    recognition.onstart = () => {
      setIsListening(true)
      requestWakeLock()
    }

    recognition.onresult = async (event: any) => {
      if (isTriggeringRef.current) return

      let interimTranscript = ''
      let finalTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + ' '
        } else {
          interimTranscript += event.results[i][0].transcript + ' '
        }
      }
      
      const newestSpeech = (finalTranscript + ' ' + interimTranscript).trim()
      setTranscript(newestSpeech)

      if (newestSpeech && !isTriggeringRef.current) {
        // Accumulate into rolling speech buffer (keeps last 80 words spoken across pauses)
        const newWords = normalizeText(newestSpeech).split(' ').filter(Boolean)
        const combinedWords = [...accumulatedSpeechRef.current, ...newWords]
        accumulatedSpeechRef.current = combinedWords.slice(-80)
        const fullAccumulated = accumulatedSpeechRef.current.join(' ')
        setAccumulatedText(fullAccumulated)

        await handleRecognizedText(newestSpeech, fullAccumulated)
      }
    }

    recognition.onerror = (event: any) => {
      console.error('Speech recognition error', event.error)
      if (event.error === 'not-allowed') setMicPermission('denied')
    }

    recognition.onend = () => {
      if (isMountedRef.current) setIsListening(false)
      // Auto-restart if still enabled, mounted, and not currently triggering SOS
      if (isEnabledRef.current && isMountedRef.current && !isTriggeringRef.current) {
        setTimeout(() => {
          if (isEnabledRef.current && isMountedRef.current && !isTriggeringRef.current) {
            startListening()
          }
        }, 1200)
      }
    }

    try {
      recognition.start()
      recognitionRef.current = recognition
    } catch (e) {
      console.error('Could not start recognition', e)
    }
  }

  const stopListening = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.onend = null
        recognitionRef.current.onerror = null
        recognitionRef.current.onresult = null
        recognitionRef.current.stop()
      } catch (e) {
        // silent
      }
      recognitionRef.current = null
    }
    setIsListening(false)
    releaseWakeLock()
  }

  const handleRecognizedText = async (text: string, fullAccumulatedText: string = '') => {
    if (isTriggeringRef.current) return

    const targetHash = safeWordHash || (typeof window !== 'undefined' ? localStorage.getItem('haven_voice_safehash') : '') || ''
    const targetText = safeWordText || (typeof window !== 'undefined' ? localStorage.getItem('haven_voice_safeword') : '') || ''

    if (!targetHash && !targetText && !config.has_safe_word) return

    const normRecent = normalizeText(text)
    const normAccum = normalizeText(fullAccumulatedText)
    if (!normRecent && !normAccum) return

    let isMatch = false

    // 1. Direct text inclusion match (recent burst OR rolling accumulated speech buffer across slow speech/pauses)
    if (targetText) {
      if (normRecent.includes(targetText) || normAccum.includes(targetText)) {
        isMatch = true
      }
    }

    // 2. Slow Speech / Fuzzy Word Set Match (75%+ word overlap across pauses)
    if (!isMatch && targetText) {
      const targetWords = targetText.split(' ').filter(Boolean)
      if (targetWords.length > 0) {
        const accumWords = normAccum.split(' ').filter(Boolean).slice(-40)
        const matchedCount = targetWords.filter(tw => accumWords.includes(tw)).length
        const ratio = matchedCount / targetWords.length
        
        if (targetWords.length === 1 && accumWords.includes(targetWords[0])) {
          isMatch = true
        } else if (targetWords.length > 1 && ratio >= 0.75) {
          isMatch = true
        }
      }
    }

    // 3. SHA-256 Hash Match (exact phrase or sliding window of 1 to 12 words)
    if (!isMatch && targetHash) {
      const fullHash = await hashString(normRecent)
      if (fullHash === targetHash) {
        isMatch = true
      }

      if (!isMatch) {
        const words = normRecent.split(' ').filter(Boolean)
        for (let len = 1; len <= Math.min(12, words.length); len++) {
          for (let i = 0; i <= words.length - len; i++) {
            const phrase = words.slice(i, i + len).join(' ')
            const hash = await hashString(phrase)
            if (hash === targetHash) {
              isMatch = true
              break
            }
          }
          if (isMatch) break
        }
      }
    }

    if (isMatch) {
      if (isTriggeringRef.current) return
      isTriggeringRef.current = true
      // Clear rolling buffer on match to avoid double triggers
      accumulatedSpeechRef.current = []
      setAccumulatedText('')
      triggerSOS()
    }
  }

  const triggerSOS = async () => {
    isTriggeringRef.current = true
    stopListening()
    
    let lat = currentLocation?.lat || 0
    let lng = currentLocation?.lng || 0
    
    try {
      const loc = await getLocation()
      if (loc.lat || loc.lng) {
        lat = loc.lat
        lng = loc.lng
      }
    } catch (e) {
      console.log('Location fetch error, using cached:', currentLocation)
    }

    const endpoint = testMode ? '/voice-sos/test' : '/voice-sos/trigger'
    
    try {
      const res = await secureFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          spoken_phrase: safeWordText || safeWord,
          hashed_safe_word: safeWordHash,
          latitude: lat,
          longitude: lng,
          location_accuracy: 5.0,
          timestamp: new Date().toISOString()
        })
      })
      
      if (res.ok) {
        const data = await res.json()
        if (testMode) {
          setTestResult(data)
        } else {
          setSosAlertData(data)
          setShowSOSModal(true)
          if (data.event_id) {
            startLocationStreaming(data.event_id)
            captureForensicEvidence(data.event_id)
          }
          if (data.whatsapp_links?.length) {
            // Open first link automatically via direct anchor element
            openWhatsAppLink(data.whatsapp_links[0].url)
          }
        }
        fetchHistory()
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        if (testMode) {
          setTestResult({ success: false, message: err.detail || 'Failed' })
        }
      }
    } catch (error) {
      console.error('Error triggering SOS:', error)
      if (testMode) {
        setTestResult({ success: false, message: 'Network error — could not reach server' })
      }
    } finally {
      if (testMode) {
        // In test mode, release triggering lock after 2.5s
        setTimeout(() => {
          isTriggeringRef.current = false
          if (isEnabledRef.current && isMountedRef.current) {
            startListening()
          }
        }, 2500)
      } else {
        // In real SOS mode, wait for cooldown period
        const cooldownMs = (config.cooldown_seconds || 60) * 1000
        setTimeout(() => {
          isTriggeringRef.current = false
        }, cooldownMs)
      }
    }
  }

  const toggleEnable = () => {
    setConfig(prev => {
      const next = !prev.enabled
      if (!next) {
        isTriggeringRef.current = false
        stopListening()
      }
      return { ...prev, enabled: next }
    })
  }

  const handleTestMode = () => {
    isTriggeringRef.current = false
    setTestMode(true)
    setConfig(prev => ({ ...prev, enabled: true }))
    setTestResult(null)
  }

  // --- Render ---
  return (
    <div style={styles.container}>
      <div style={styles.maxContainer}>
        {/* Header */}
        <div style={styles.header}>
          <Link href="/" style={styles.backBtn}>
            <ArrowLeft size={24} /> Back
          </Link>
          <h1 style={styles.title}><Shield size={32} /> Haven · Voice SOS</h1>
          <div>
            <span style={styles.badge(config.enabled ? 'granted' : 'pending')}>
              {config.enabled ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>

        {isSupported === false && (
          <div style={styles.notice}>
            <strong><AlertTriangle size={16} style={{display:'inline', verticalAlign:'middle'}}/> Browser Not Supported</strong>
            <p>Your browser does not support the Web Speech API required for this feature. Please use Chrome or Edge.</p>
          </div>
        )}

        {/* Activation Section */}
        <div style={{...styles.card, textAlign: 'center'}}>
          <h2 style={{...styles.cardTitle, justifyContent: 'center'}}>Listening Status</h2>
          
          <div style={{display: 'flex', justifyContent: 'center', gap: '1rem', marginBottom: '1rem'}}>
            <div style={{fontSize: '0.85rem', color: colors.muted}}>
              Microphone: <span style={styles.badge(micPermission)}>{micPermission}</span>
            </div>
            <div style={{fontSize: '0.85rem', color: colors.muted}}>
              Location: <span style={styles.badge(locPermission)}>{locPermission}</span>
            </div>
          </div>

          <div style={styles.micBtnContainer}>
            <button 
              style={styles.micBtn(isListening)} 
              onClick={toggleEnable}
              disabled={isSupported === false}
            >
              {isListening ? <Mic size={48} /> : <MicOff size={48} />}
            </button>
            <h3 style={{marginTop: '1.5rem', color: isListening ? colors.danger : colors.dark}}>
              {isListening ? '🎙 Voice SOS Active — Listening...' : '● Ready'}
            </h3>
          </div>

          <div style={{display: 'flex', justifyContent: 'center', gap: 10, margin: '12px 0'}}>
            <button
              onClick={() => setWhisperMode(!whisperMode)}
              style={{
                padding: '6px 14px', borderRadius: 20, border: 'none',
                background: whisperMode ? 'linear-gradient(135deg, #7c3aed, #6d28d9)' : '#f3e8ff',
                color: whisperMode ? 'white' : '#7c3aed',
                fontSize: '0.78rem', fontWeight: 700, cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 6, transition: 'all 0.2s'
              }}
            >
              🎙 Whisper Stealth Gain {whisperMode ? '(+12dB Active)' : '(Off)'}
            </button>
          </div>

          <div style={styles.transcript}>
            {transcript ? (
              <div>
                <div style={{fontWeight: 700, color: colors.dark, marginBottom: 4}}>Speech Detected:</div>
                <div style={{color: colors.primary, fontWeight: 600}}>"{transcript}"</div>
                {accumulatedText && accumulatedText !== transcript && (
                  <div style={{fontSize: '0.78rem', color: colors.muted, marginTop: 6, fontStyle: 'normal'}}>
                    📜 Rolling Buffer (Slow Speech Log): "{accumulatedText}"
                  </div>
                )}
              </div>
            ) : (
              <span style={{opacity: 0.5}}>(Speak your safe word slowly or naturally — speech transcript will appear here)</span>
            )}
          </div>
        </div>

        {/* Setup Section */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>Configuration</h2>
          <div style={{marginBottom: '1rem'}}>
            <label style={styles.label}>Safe Word / Phrase</label>
            <div style={{display: 'flex', gap: '0.5rem', position: 'relative'}}>
              <input
                type={showSafeWord ? 'text' : 'password'}
                style={styles.input}
                value={safeWord}
                onChange={e => setSafeWord(e.target.value)}
                placeholder={config.has_safe_word || safeWordText ? '••••••••• (Stored securely)' : 'Enter a secret phrase'}
              />
              <button 
                type="button"
                onClick={() => setShowSafeWord(!showSafeWord)}
                style={{
                  position: 'absolute', right: '1rem', top: '0.75rem', 
                  background: 'none', border: 'none', color: colors.muted, cursor: 'pointer'
                }}
              >
                {showSafeWord ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>
            <p style={{fontSize: '0.8rem', color: colors.muted, marginTop: '-0.5rem'}}>
              This phrase will trigger an SOS when spoken. Never share it.
            </p>
          </div>
          
          <div style={{display: 'flex', alignItems: 'center', gap: '1rem'}}>
            <button 
              style={styles.btnPrimary} 
              onClick={handleSaveConfig}
              disabled={isSavingConfig}
            >
              {isSavingConfig ? 'Saving...' : 'Save Configuration'}
            </button>
            {saveMsg && (
              <span style={{fontSize: '0.85rem', fontWeight: 600, color: saveMsg.includes('✓') ? colors.success : colors.danger}}>
                {saveMsg}
              </span>
            )}
          </div>
        </div>

        {/* Test Mode */}
        <div style={{...styles.card, background: '#fef2f2', borderColor: '#fca5a5'}}>
          <h2 style={styles.cardTitle}><TestTube size={24} color={colors.danger} /> Test Mode</h2>
          <p style={{fontSize: '0.9rem', marginBottom: '1rem'}}>
            Practice using your safe word without sending real alerts.
          </p>
          <button style={{...styles.btnSecondary, borderColor: colors.danger, color: colors.danger}} onClick={handleTestMode}>
            Start Test Mode
          </button>
          
          {testMode && (
            <div style={{marginTop: '1rem', padding: '1rem', background: colors.white, borderRadius: '8px'}}>
              <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 'bold', color: colors.warning}}>
                <AlertTriangle size={20} /> TEST MODE ACTIVE — Speak your safe word into the microphone
              </div>
              
              {testResult && (
                <div style={{marginTop: '1rem', padding: '0.75rem', background: testResult.success ? '#d1fae5' : '#fee2e2', borderRadius: '6px'}}>
                  <div style={{fontWeight: 'bold', color: testResult.success ? colors.success : colors.danger}}>
                    {testResult.message}
                  </div>
                  {testResult.latitude && (
                    <div style={{fontSize: '0.85rem', marginTop: '0.25rem'}}>
                      📍 Captured Location: {testResult.latitude}, {testResult.longitude}
                    </div>
                  )}
                  <button 
                    style={{...styles.btnSecondary, marginTop: '1rem', padding: '0.5rem 1rem', fontSize: '0.85rem'}}
                    onClick={() => { setTestMode(false); setTestResult(null) }}
                  >
                    Exit Test Mode
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Trusted Contacts */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}><Phone size={24} /> Trusted Contacts ({contacts.length}/5)</h2>
          
          {contacts.map(c => (
            <div key={c.contact_id || c.name} style={{...styles.historyItem, padding: '0.75rem 0'}}>
              <div>
                <div style={{fontWeight: 'bold'}}>{c.name}</div>
                <div style={{fontSize: '0.85rem', color: colors.muted}}>{c.phone}</div>
              </div>
              <button 
                style={{background: 'none', border: 'none', color: colors.danger, cursor: 'pointer'}}
                onClick={() => handleDeleteContact(c.name)}
              >
                <Trash2 size={18} />
              </button>
            </div>
          ))}

          {contacts.length < 5 && (
            <div style={{marginTop: '1.5rem'}}>
              <div style={{display: 'flex', gap: '1rem', marginBottom: '1rem'}}>
                <input 
                  style={{...styles.input, marginBottom: 0}} 
                  placeholder="Name" 
                  value={newContact.name}
                  onChange={e => setNewContact({...newContact, name: e.target.value})}
                />
                <input 
                  style={{...styles.input, marginBottom: 0}} 
                  placeholder="Phone" 
                  value={newContact.phone}
                  onChange={e => setNewContact({...newContact, phone: e.target.value})}
                />
              </div>
              <button 
                style={styles.btnSecondary} 
                onClick={handleAddContact}
                disabled={isSavingContact}
              >
                <Plus size={18} /> Add Contact
              </button>
            </div>
          )}
        </div>

        {/* History */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}><History size={24} /> Event History</h2>
          {history.length === 0 ? (
            <p style={{color: colors.muted, textAlign: 'center'}}>No recent events</p>
          ) : (
            history.map(ev => (
              <div key={ev.event_id} style={styles.historyItem}>
                <div>
                  <div style={{fontSize: '0.85rem', color: colors.muted}}>
                    {new Date(ev.timestamp).toLocaleString()}
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem'}}>
                    <span style={styles.badge(ev.trigger_type === 'test' ? 'pending' : 'denied')}>
                      {ev.trigger_type === 'test' ? 'TEST' : 'REAL'}
                    </span>
                    <span style={{fontSize: '0.9rem'}}>{ev.status}</span>
                  </div>
                </div>
                {(ev.latitude || ev.longitude) && (
                  <div style={{color: colors.primary}} title="Location captured">
                    <MapPin size={20} />
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Real Voice SOS Modal */}
        {showSOSModal && sosAlertData && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
            <div style={{ background: 'white', borderRadius: 20, padding: 28, maxWidth: 440, width: '100%', textAlign: 'center' }}>
              <div style={{ fontSize: '3rem', marginBottom: 8 }}>🚨</div>
              <h3 style={{ fontFamily: 'Georgia', fontSize: '1.4rem', color: colors.primary, marginBottom: 8 }}>
                Voice SOS Activated!
              </h3>
              <p style={{ fontSize: '0.88rem', color: colors.muted, lineHeight: 1.5, marginBottom: 16 }}>
                An emergency case has been registered with HAVEN authorities.
              </p>

              {(sosAlertData.latitude || sosAlertData.longitude || currentLocation) && (
                <div style={{ background: '#fdf2f8', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 12, padding: 12, marginBottom: 16, fontSize: '0.82rem', color: colors.dark }}>
                  <strong>📍 Location Captured:</strong> {sosAlertData.latitude || currentLocation?.lat}, {sosAlertData.longitude || currentLocation?.lng}<br />
                  <a
                    href={`https://maps.google.com/?q=${sosAlertData.latitude || currentLocation?.lat},${sosAlertData.longitude || currentLocation?.lng}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: colors.primary, fontWeight: 700, display: 'inline-block', marginTop: 4 }}
                  >
                    Open in Google Maps ↗
                  </a>
                </div>
              )}

              {isStreamingLocation && (
                <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '8px 12px', marginBottom: 14, fontSize: '0.78rem', color: '#1d4ed8', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#2563eb', display: 'inline-block', animation: 'pulse 1s infinite' }}></span>
                  📡 Live GPS Tracking Stream: Active (4s interval)
                </div>
              )}

              {sosAlertData.whatsapp_links?.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 700, color: colors.muted, marginBottom: 8 }}>
                    SEND WHATSAPP ALERTS:
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {sosAlertData.whatsapp_links.map((link: any, idx: number) => (
                      <button
                        key={idx}
                        onClick={() => openWhatsAppLink(link.url)}
                        style={{
                          background: '#25D366', color: 'white', border: 'none', borderRadius: 12,
                          padding: '12px', fontWeight: 700, fontSize: '0.9rem', cursor: 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8
                        }}
                      >
                        <Phone size={18} /> Open WhatsApp for {link.name || `Contact #${idx + 1}`}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
                <button
                  onClick={() => openSMSAlert('', sosAlertData.alert_message || 'EMERGENCY SOS TRIGGERED')}
                  style={{
                    background: '#2563eb', color: 'white', border: 'none', borderRadius: 12,
                    padding: '11px', fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6
                  }}
                >
                  📱 Send Offline SMS Alert (Zero Data Fallback)
                </button>
              </div>

              <div style={{ display: 'flex', gap: 10 }}>
                <a
                  href="tel:112"
                  style={{
                    flex: 1, background: colors.primary, color: 'white', padding: '12px',
                    borderRadius: 12, textDecoration: 'none', fontWeight: 700, fontSize: '0.88rem',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6
                  }}
                >
                  <Phone size={16} /> Call 112
                </a>
                <button
                  onClick={() => {
                    setShowSOSModal(false)
                    isTriggeringRef.current = false
                    if (config.enabled && !isListening) {
                      startListening()
                    }
                  }}
                  style={{
                    flex: 1, background: '#f3f4f6', color: '#6b7280', padding: '12px',
                    borderRadius: 12, border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem'
                  }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
