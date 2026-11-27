'use client'

import React, { useState, useEffect, useRef } from 'react'
import {
  Mic, Square, Pause, Play, Sparkles, MapPin, AlertTriangle,
  CheckCircle2, Loader2, ShieldAlert, Volume2,
} from 'lucide-react'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'

interface SttStatus {
  available: boolean
  provider: string | null
  model: string | null
  supported_languages: string[]
  missing_env: string[]
  setup_hint: string | null
}

interface ExtractedInfo {
  transcript: string
  suggested_category: string
  situation_description: string
  mentioned_location: string | null
  is_gps_confirmed: boolean
  location_disclaimer: string
  suggested_urgency: string
  urgency_disclaimer: string
  urgency_indicators: string[]
  contextual_info: string[]
  extraction_mode: string
  requires_human_confirmation: boolean
  auto_dispatched: boolean
}

const CATEGORIES = [
  { id: 'immediate_danger', label: 'Immediate Danger' },
  { id: 'stalking', label: 'Stalking / Being Followed' },
  { id: 'domestic_violence', label: 'Domestic Violence' },
  { id: 'harassment', label: 'Harassment / Threat' },
  { id: 'assault', label: 'Physical Assault' },
  { id: 'unsafe_transit', label: 'Unsafe Transit / Stranded' },
  { id: 'medical', label: 'Medical Emergency' },
  { id: 'other', label: 'Other Safety Concern' },
]

function fmtSeconds(s: number): string {
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('Failed to read audio blob'))
    reader.readAsDataURL(blob)
  })
}

export default function VoiceAudioRecorderPanel({
  userId,
  onIncidentCreated,
}: {
  userId?: string
  onIncidentCreated?: (caseId: string) => void
}) {
  const [sttStatus, setSttStatus] = useState<SttStatus | null>(null)
  const [language, setLanguage] = useState<'auto' | 'en' | 'hi'>('auto')

  // Recording state
  const [recState, setRecState] = useState<'idle' | 'recording' | 'paused' | 'recorded'>('idle')
  const [durationSec, setDurationSec] = useState(0)
  const [audioUrl, setAudioUrl] = useState<string>('')
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [audioMime, setAudioMime] = useState('audio/webm')
  const [micErr, setMicErr] = useState('')
  const [pauseSupported, setPauseSupported] = useState(true)

  // Transcription & AI extraction state
  const [transcribing, setTranscribing] = useState(false)
  const [sttErr, setSttErr] = useState('')
  const [transcript, setTranscript] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [extracted, setExtracted] = useState<ExtractedInfo | null>(null)

  // Editable confirmation state
  const [category, setCategory] = useState('immediate_danger')
  const [description, setDescription] = useState('')
  const [mentionedLoc, setMentionedLoc] = useState('')
  const [gpsLoc, setGpsLoc] = useState<{ lat: number; lng: number; accuracy: number | null; capturedAt: string } | null>(null)
  const [manualLoc, setManualLoc] = useState('')
  const [isTestSubmission, setIsTestSubmission] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<{ caseId: string; isTest: boolean; status: string } | null>(null)
  const [submitErr, setSubmitErr] = useState('')

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const idempotencyRef = useRef<string>(
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `vai-${Date.now()}`
  )

  useEffect(() => {
    secureFetch('/voice-sos/stt-status')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setSttStatus(d) })
      .catch(() => {})

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startRecording = async () => {
    setMicErr('')
    setSttErr('')
    setSubmitResult(null)
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setMicErr('Audio recording is not supported in this browser. Type your situation below instead.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      let mime = 'audio/webm'
      if (!MediaRecorder.isTypeSupported('audio/webm')) {
        mime = MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : (MediaRecorder.isTypeSupported('audio/ogg') ? 'audio/ogg' : '')
      }
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      setAudioMime(mime || recorder.mimeType || 'audio/webm')
      setPauseSupported(typeof recorder.pause === 'function' && typeof recorder.resume === 'function')
      chunksRef.current = []

      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mime || recorder.mimeType || 'audio/webm' })
        if (audioUrl) URL.revokeObjectURL(audioUrl)
        setAudioUrl(URL.createObjectURL(blob))
        setAudioBlob(blob)
        setRecState('recorded')
        if (timerRef.current) clearInterval(timerRef.current)
        stream.getTracks().forEach((t) => t.stop())
      }

      recorder.start(500)
      mediaRecorderRef.current = recorder
      setDurationSec(0)
      setRecState('recording')
      if (timerRef.current) clearInterval(timerRef.current)
      timerRef.current = setInterval(() => setDurationSec((d) => d + 1), 1000)
    } catch {
      setMicErr('Microphone permission was denied or unavailable. You can still type your distress text below.')
    }
  }

  const pauseOrResume = () => {
    const rec = mediaRecorderRef.current
    if (!rec) return
    if (recState === 'recording' && typeof rec.pause === 'function') {
      rec.pause()
      if (timerRef.current) clearInterval(timerRef.current)
      setRecState('paused')
    } else if (recState === 'paused' && typeof rec.resume === 'function') {
      rec.resume()
      timerRef.current = setInterval(() => setDurationSec((d) => d + 1), 1000)
      setRecState('recording')
    }
  }

  const stopRecording = () => {
    const rec = mediaRecorderRef.current
    if (rec && rec.state !== 'inactive') rec.stop()
  }

  const handleTranscribe = async () => {
    if (!audioBlob || transcribing) return
    setTranscribing(true)
    setSttErr('')
    try {
      const b64 = await blobToBase64(audioBlob)
      const res = await secureFetch('/voice-sos/transcribe', {
        method: 'POST',
        body: JSON.stringify({ audio_base64: b64, mime_type: audioMime, language }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detailObj = data?.detail
        const msg = typeof detailObj === 'object'
          ? `${detailObj.detail} ${detailObj.missing_env?.length ? `(Missing env: ${detailObj.missing_env.join(', ')})` : ''}`
          : (detailObj || `Transcription unavailable (${res.status}).`)
        setSttErr(msg)
        return
      }
      setTranscript(data.transcript || '')
      if (data.transcript) {
        await runExtraction(data.transcript)
      }
    } catch {
      setSttErr('Network error uploading audio for transcription.')
    } finally {
      setTranscribing(false)
    }
  }

  const runExtraction = async (textOverride?: string) => {
    const text = (textOverride ?? transcript).trim()
    if (!text || extracting) return
    setExtracting(true)
    setSttErr('')
    try {
      const res = await secureFetch('/voice-sos/extract', {
        method: 'POST',
        body: JSON.stringify({ transcript: text, language }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setSttErr(data?.detail || 'AI extraction failed.')
        return
      }
      setExtracted(data)
      setCategory(data.suggested_category || 'immediate_danger')
      setDescription(data.situation_description || text)
      setMentionedLoc(data.mentioned_location || '')
      if (!manualLoc && data.mentioned_location) {
        setManualLoc(data.mentioned_location)
      }
    } catch {
      setSttErr('Could not analyze transcript right now.')
    } finally {
      setExtracting(false)
    }
  }

  const captureGPS = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGpsLoc({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: Number.isFinite(pos.coords.accuracy) ? Math.round(pos.coords.accuracy) : null,
          capturedAt: new Date(pos.timestamp || Date.now()).toISOString(),
        })
      },
      () => setSubmitErr('Could not obtain GPS coordinates — manual location remains editable.'),
      { enableHighAccuracy: true, timeout: 8000 }
    )
  }

  const handleConfirmSubmit = async () => {
    if (submitting) return
    setSubmitErr('')
    setSubmitting(true)
    try {
      if (isTestSubmission) {
        const res = await secureFetch('/voice-sos/test', {
          method: 'POST',
          body: JSON.stringify({
            user_id: userId || 'user',
            mode: 'voice_ai_test',
            transcript: transcript.trim(),
            latitude: gpsLoc?.lat ?? null,
            longitude: gpsLoc?.lng ?? null,
            location_accuracy: gpsLoc?.accuracy ?? null,
            location_captured_at: gpsLoc?.capturedAt ?? null,
            timestamp: new Date().toISOString(),
          }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          setSubmitErr(data?.detail || 'Could not record Voice AI test.')
          return
        }
        setSubmitResult({ caseId: data.event_id, isTest: true, status: 'TEST_COMPLETE' })
        return
      }

      const locSource = gpsLoc ? 'gps' : manualLoc.trim() ? 'manual' : 'unavailable'
      const res = await secureFetch('/sos/report', {
        method: 'POST',
        body: JSON.stringify({
          category,
          description: description.trim() || transcript.trim(),
          immediate_danger: extracted?.suggested_urgency === 'critical' || category === 'immediate_danger',
          latitude: gpsLoc?.lat ?? null,
          longitude: gpsLoc?.lng ?? null,
          location_accuracy: gpsLoc?.accuracy ?? null,
          location_captured_at: gpsLoc?.capturedAt ?? null,
          location_source: locSource,
          manual_location: manualLoc.trim(),
          idempotency_key: idempotencyRef.current,
          trigger_type: 'voice_ai_sos',
          voice_transcript: transcript.trim(),
          ai_suggested_urgency: extracted?.suggested_urgency || null,
          mentioned_location: mentionedLoc.trim() || null,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setSubmitErr(data?.detail || `Submission failed (${res.status}).`)
        return
      }
      idempotencyRef.current = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `vai-${Date.now()}`
      setSubmitResult({ caseId: data.case_id, isTest: false, status: data.status || 'RECEIVED' })
      if (onIncidentCreated && data.case_id) onIncidentCreated(data.case_id)
    } catch {
      setSubmitErr('Network error submitting incident.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section
      aria-labelledby="voice-ai-recorder-heading"
      style={{
        background: 'white',
        border: '1px solid rgba(190,24,93,0.14)',
        borderRadius: 16,
        boxShadow: '0 2px 12px rgba(190,24,93,0.08)',
        padding: '1.5rem',
        marginBottom: '1.5rem',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <div>
          <h2 id="voice-ai-recorder-heading" style={{ fontFamily: 'Georgia, serif', fontSize: '1.35rem', margin: 0, color: '#1a0a12', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sparkles size={20} color="#be185d" /> Record Voice SOS &amp; AI Assist (Whisper)
          </h2>
          <p style={{ fontSize: '0.8rem', color: '#6b5563', margin: '4px 0 0' }}>
            Record audio, review/edit Whisper transcription, confirm extracted incident details before submitting.
          </p>
        </div>
        <select
          aria-label="Speech language"
          value={language}
          onChange={(e) => setLanguage(e.target.value as any)}
          style={{ padding: '7px 12px', borderRadius: 8, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.82rem', background: 'white' }}
        >
          <option value="auto">Auto (English / Hindi)</option>
          <option value="en">English (en)</option>
          <option value="hi">Hindi (hi)</option>
        </select>
      </div>

      {/* Honest Whisper STT status banner */}
      {sttStatus && !sttStatus.available && (
        <div role="status" style={{ background: '#fffbeb', border: '1px solid #fcd34d', color: '#92400e', borderRadius: 10, padding: '10px 12px', fontSize: '0.8rem', marginBottom: 14 }}>
          <strong>Whisper Speech Transcription Unavailable:</strong> {sttStatus.setup_hint}{' '}
          {sttStatus.missing_env?.length > 0 && <code>Missing: {sttStatus.missing_env.join(', ')}</code>}
        </div>
      )}

      {/* Recording controls */}
      <div style={{ background: '#fdf2f8', borderRadius: 12, padding: 14, border: '1px solid rgba(190,24,93,0.12)', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {(recState === 'idle' || recState === 'recorded') && (
            <button
              type="button"
              onClick={startRecording}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 16px', borderRadius: 10, border: 'none', background: '#be185d', color: 'white', fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer' }}
            >
              <Mic size={16} /> {recState === 'recorded' ? 'Re-record Audio' : 'Start Audio Recording'}
            </button>
          )}
          {(recState === 'recording' || recState === 'paused') && (
            <>
              {pauseSupported && (
                <button
                  type="button"
                  onClick={pauseOrResume}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderRadius: 10, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 700, fontSize: '0.84rem', cursor: 'pointer' }}
                >
                  {recState === 'recording' ? <><Pause size={15} /> Pause</> : <><Play size={15} /> Resume</>}
                </button>
              )}
              <button
                type="button"
                onClick={stopRecording}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 16px', borderRadius: 10, border: 'none', background: '#dc2626', color: 'white', fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer' }}
              >
                <Square size={15} /> Stop Recording
              </button>
            </>
          )}
          <span style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: '1rem', color: recState === 'recording' ? '#dc2626' : '#1a0a12' }}>
            {recState === 'recording' ? '● REC ' : recState === 'paused' ? '⏸ PAUSED ' : ''}
            {fmtSeconds(durationSec)}
          </span>
        </div>

        {micErr && <div role="alert" style={{ marginTop: 8, color: '#b91c1c', fontSize: '0.8rem', fontWeight: 600 }}>{micErr}</div>}

        {audioUrl && recState === 'recorded' && (
          <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
            <div style={{ fontSize: '0.76rem', fontWeight: 700, color: '#4b3540', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Volume2 size={14} /> Playback before submission ({fmtSeconds(durationSec)}):
            </div>
            <audio controls src={audioUrl} style={{ width: '100%' }} />
            <div>
              <button
                type="button"
                disabled={transcribing || sttStatus?.available === false}
                onClick={handleTranscribe}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '9px 16px', borderRadius: 9, border: 'none',
                  background: sttStatus?.available === false ? '#d1d5db' : '#7c3aed',
                  color: 'white', fontWeight: 700, fontSize: '0.84rem',
                  cursor: sttStatus?.available === false ? 'not-allowed' : 'pointer',
                }}
              >
                {transcribing ? <><Loader2 size={15} className="animate-spin" /> Transcribing Audio…</> : 'Transcribe Audio (Whisper)'}
              </button>
            </div>
          </div>
        )}
      </div>

      {sttErr && (
        <div role="alert" style={{ marginBottom: 12, background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', borderRadius: 10, padding: 10, fontSize: '0.8rem' }}>
          {sttErr}
        </div>
      )}

      {/* Editable Transcription */}
      <div style={{ marginBottom: 14 }}>
        <label htmlFor="voice-ai-transcript" style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1a0a12', marginBottom: 6 }}>
          Editable Transcript (English / Hindi)
        </label>
        <textarea
          id="voice-ai-transcript"
          rows={3}
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder='Example: "Someone is following me near the metro station. I need help."'
          style={{ width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 10, border: '1px solid rgba(190,24,93,0.25)', fontSize: '0.88rem' }}
        />
        <button
          type="button"
          disabled={!transcript.trim() || extracting}
          onClick={() => runExtraction()}
          style={{
            marginTop: 8, display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 9, border: 'none',
            background: !transcript.trim() ? '#e5e7eb' : '#be185d', color: !transcript.trim() ? '#6b7280' : 'white',
            fontWeight: 700, fontSize: '0.8rem', cursor: !transcript.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          {extracting ? 'Extracting Emergency Details…' : 'Extract Emergency Info (AI Review)'}
        </button>
      </div>

      {/* Confirmation & Review Form */}
      {extracted && (
        <div style={{ border: '1px solid rgba(190,24,93,0.22)', borderRadius: 12, padding: 14, background: '#fffafb', display: 'grid', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <strong style={{ color: '#be185d', fontSize: '0.9rem' }}>Confirm Extracted Emergency Information</strong>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: '#fef3c7', color: '#92400e' }}>
              Suggested Urgency: {extracted.suggested_urgency.toUpperCase()} (AI suggestion only)
            </span>
          </div>

          {extracted.urgency_indicators?.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {extracted.urgency_indicators.map((u) => (
                <span key={u} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, background: '#fce7f3', color: '#be185d', fontWeight: 700 }}>
                  {u}
                </span>
              ))}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, marginBottom: 4 }}>Emergency Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ width: '100%', padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', fontSize: '0.85rem' }}
              >
                {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, marginBottom: 4 }}>
                Mentioned Location <span style={{ color: '#b45309' }}>(NOT GPS-confirmed)</span>
              </label>
              <input
                value={mentionedLoc}
                onChange={(e) => setMentionedLoc(e.target.value)}
                placeholder="Landmark mentioned in speech"
                style={{ width: '100%', boxSizing: 'border-box', padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, marginBottom: 4 }}>Confirmed Situation Description</label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{ width: '100%', boxSizing: 'border-box', padding: 9, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.85rem' }}
            />
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              onClick={captureGPS}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '8px 12px', borderRadius: 8, border: 'none', background: '#be185d', color: 'white', fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer' }}
            >
              <MapPin size={14} /> Capture Verified GPS
            </button>
            <input
              value={manualLoc}
              onChange={(e) => setManualLoc(e.target.value)}
              placeholder="Or enter confirmed location manually"
              style={{ flex: 1, minWidth: 200, padding: 8, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.82rem' }}
            />
          </div>
          {gpsLoc && (
            <div style={{ fontSize: '0.74rem', color: '#166534' }}>
              GPS Captured: {gpsLoc.lat.toFixed(5)}, {gpsLoc.lng.toFixed(5)} {gpsLoc.accuracy != null ? `(±${gpsLoc.accuracy}m)` : ''} · {formatServerDateTime(gpsLoc.capturedAt)}
            </div>
          )}

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', cursor: 'pointer' }}>
            <input type="checkbox" checked={isTestSubmission} onChange={(e) => setIsTestSubmission(e.target.checked)} />
            <span>Submit in Test Mode (verify Voice AI flow without creating a live emergency incident)</span>
          </label>

          {submitErr && <div role="alert" style={{ color: '#b91c1c', fontSize: '0.8rem', fontWeight: 600 }}>{submitErr}</div>}

          <button
            type="button"
            disabled={submitting}
            onClick={handleConfirmSubmit}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              padding: '11px 18px', borderRadius: 10, border: 'none',
              background: isTestSubmission ? '#7c3aed' : '#dc2626', color: 'white', fontWeight: 800, fontSize: '0.9rem', cursor: 'pointer',
            }}
          >
            <ShieldAlert size={17} />
            {submitting ? 'Submitting…' : (isTestSubmission ? 'Confirm & Submit Voice Test' : 'Confirm & Submit Real SOS Incident')}
          </button>
        </div>
      )}

      {submitResult && (
        <div role="status" style={{ marginTop: 12, padding: 12, borderRadius: 10, background: '#f0fdf4', border: '1px solid #86efac', color: '#166534', fontSize: '0.84rem' }}>
          <CheckCircle2 size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />
          {submitResult.isTest ? 'Voice AI Test Recorded:' : 'Incident Submitted:'} <code>{submitResult.caseId}</code> ({submitResult.status})
        </div>
      )}
    </section>
  )
}
