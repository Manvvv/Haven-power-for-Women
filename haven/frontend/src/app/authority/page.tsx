'use client'
import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { ArrowLeft, Shield, Search, Eye, Upload, Users, AlertTriangle, CheckCircle, Clock, RefreshCw, X, FileText, UserCheck, ShieldAlert, Printer } from 'lucide-react'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { secureFetch, getAuthorityToken, setAuthorityToken, clearAuthorityToken } from '@/lib/api'
import { useNotifications } from '@/hooks/useNotifications'
import { Bell } from 'lucide-react'
import SOSLifecycle from '@/components/SOSLifecycle'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface SOSCase {
  case_id: string; decoded_text: string; severity?: string
  nature_of_abuse?: string; immediate_danger?: boolean; location?: string
  needs?: string[]; summary?: string; status: string; created_at: string
  trigger_type?: string
  has_evidence?: boolean
  evidence_hash?: string
  evidence?: {
    evidence_id?: string
    evidence_hash?: string
    has_audio?: boolean
    has_image?: boolean
    audio_base64?: string
    image_base64?: string
    mime_type_audio?: string
    duration_seconds?: number
    captured_at?: string
  }
}
interface MatchFactor { label: string; strength: string }
interface CulpritMatch {
  name?: string; physical_description: string; behavioral_traits: string
  location?: string; culprit_id: string; profile_id?: string
  score?: number; match_score?: number; match_level?: string
  match_factors?: MatchFactor[]; match_summary?: string
  human_verification_required?: boolean; created_at?: string
  updated_at?: string
  associated_cases?: { case_id: string; relationship: string; associated_at?: string }[]
}
interface DuplicateCandidate {
  profile_id: string; name?: string; physical_description?: string
  location?: string; match_level?: string; reasons?: string[]
}
interface DIRFormData {
  case_id: string
  dir_form_number: string
  generated_at: string
  officer_name: string
  officer_designation: string
  station_name: string
  district: string
  case_severity: string
  case_summary: string
  nature_of_abuse: string
  immediate_danger: boolean
  location: string
  needs: string[]
  has_forensic_evidence: boolean
  evidence_hash: string
  dir_report_text: string
  legal_sections: string[]
  relief_recommended: string[]
}
interface DiscreetDispatchResult {
  dispatch_id: string
  dispatch_type: string
  response_protocol: {
    agency_name: string
    approach: string
    vehicle: string
    siren: boolean
    estimated_minutes: number
    contact_number: string
  }
  status: string
}
type Tab = 'cases' | 'decode' | 'culprit'

export default function AuthorityPage() {
  useHavenAuth()
  const [unlocked, setUnlocked] = useState(false)
  const [badge, setBadge] = useState('')
  const [pass, setPass] = useState('')
  const [passError, setPassError] = useState(false)
  const [authLoading, setAuthLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('cases')
  const [cases, setCases] = useState<SOSCase[]>([])
  const [loading, setLoading] = useState(false)
  const [severityFilter, setSeverityFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [decodeImg, setDecodeImg] = useState('')
  const [decodeResult, setDecodeResult] = useState('')
  const [decomposed, setDecomposed] = useState<Record<string, unknown> | null>(null)
  const [decoding, setDecoding] = useState(false)
  const [culpritDesc, setCulpritDesc] = useState('')
  const [matches, setMatches] = useState<CulpritMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [searchMode, setSearchMode] = useState<'name' | 'description'>('name')
  const [searchType, setSearchType] = useState('')
  const [reportForm, setReportForm] = useState({ name: '', physical_description: '', behavioral_traits: '', location: '' })
  const [reporting, setReporting] = useState(false)
  const [reportMsg, setReportMsg] = useState('')
  // Case & Profile Intelligence — structured search state
  const [queryType, setQueryType] = useState('')
  const [degraded, setDegraded] = useState(false)
  const [searchNotice, setSearchNotice] = useState('')
  const [searchError, setSearchError] = useState('')
  const [explainOpen, setExplainOpen] = useState<Record<number, boolean>>({})
  const [detailProfile, setDetailProfile] = useState<CulpritMatch | null>(null)
  const [compareMatch, setCompareMatch] = useState<CulpritMatch | null>(null)
  const [regErrors, setRegErrors] = useState<Record<string, string>>({})
  const [dupCandidates, setDupCandidates] = useState<DuplicateCandidate[]>([])
  const [showDupDialog, setShowDupDialog] = useState(false)
  const [dupJustification, setDupJustification] = useState('')
  const [flaggedMatch, setFlaggedMatch] = useState<Record<number, boolean>>({})
  const [activeLiveTrackCase, setActiveLiveTrackCase] = useState<SOSCase | null>(null)
  const [liveCoords, setLiveCoords] = useState<{ lat: number; lng: number; accuracy: number; timestamp: string; speed?: number } | null>(null)
  const [trackingConnected, setTrackingConnected] = useState(false)
  const [dispatchStatusMap, setDispatchStatusMap] = useState<Record<string, { agency: string; status: string; dispatch_id: string }>>({})
  const trackingWsRef = useRef<WebSocket | null>(null)

  // DIR Form & Discreet Dispatch state
  const [dirFormCase, setDirFormCase] = useState<SOSCase | null>(null)
  const [dirFormData, setDirFormData] = useState<DIRFormData | null>(null)
  const [dirGenerating, setDirGenerating] = useState(false)
  const [dirOfficer, setDirOfficer] = useState({ name: '', designation: 'Protection Officer', station: '', district: '' })
  const [discreetDispatchResult, setDiscreetDispatchResult] = useState<DiscreetDispatchResult | null>(null)
  const [discreetDispatching, setDiscreetDispatching] = useState<string>('')

  useEffect(() => {
    // Restore session if existing authority token found
    const existingToken = getAuthorityToken()
    if (existingToken) {
      setUnlocked(true)
    }

    return () => {
      if (trackingWsRef.current) {
        try { trackingWsRef.current.close() } catch { /* silent */ }
        trackingWsRef.current = null
      }
    }
  }, [])

  useEffect(() => { if (unlocked) fetchCases() }, [severityFilter, statusFilter, unlocked])

  // ── Real-time SOS alerting ──────────────────────────────────────
  // Connect to the notification socket only once the dashboard is unlocked.
  // Backend pushes new-SOS events to any socket whose id starts with "auth_".
  const { notifications, unreadCount } = useNotifications(
    unlocked ? 'auth_dashboard' : undefined,
    unlocked ? getAuthorityToken() : null
  )
  const [newSosBanner, setNewSosBanner] = useState<string | null>(null)
  const lastNotifId = useRef<string | null>(null)

  // Per-case lifecycle timeline (fetched on demand from /cases/{id}/lifecycle)
  const [lifecycleCaseId, setLifecycleCaseId] = useState<string | null>(null)
  const [lifecycleHistory, setLifecycleHistory] = useState<{ status: string; timestamp: string; actor?: string }[]>([])
  const [lifecycleLoading, setLifecycleLoading] = useState(false)

  async function toggleLifecycle(caseId: string) {
    if (lifecycleCaseId === caseId) { setLifecycleCaseId(null); return }
    setLifecycleCaseId(caseId)
    setLifecycleLoading(true)
    setLifecycleHistory([])
    try {
      const res = await secureFetch(`/cases/${caseId}/lifecycle`)
      if (res.ok) {
        const data = await res.json()
        setLifecycleHistory(
          (data.history || []).map((h: { to_status?: string; status?: string; timestamp: string; actor_id?: string }) => ({
            status: (h.to_status || h.status || '').toUpperCase(),
            timestamp: h.timestamp,
            actor: h.actor_id,
          })),
        )
      }
    } catch { /* silent */ } finally { setLifecycleLoading(false) }
  }

  useEffect(() => {
    if (!unlocked || notifications.length === 0) return
    const latest = notifications[0]
    if (!latest || latest.id === lastNotifId.current) return
    lastNotifId.current = latest.id
    // Refresh the case list so the new case appears without a manual refresh.
    fetchCases()
    // Show a clear "New SOS Received" indicator.
    setNewSosBanner(latest.message || 'A new SOS case has been received.')
    // Subtle notification sound (best-effort; ignored if audio is blocked).
    try {
      const AudioCtx = (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain); gain.connect(ctx.destination)
      osc.type = 'sine'; osc.frequency.value = 880
      gain.gain.setValueAtTime(0.0001, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.05)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.6)
      osc.start(); osc.stop(ctx.currentTime + 0.6)
    } catch { /* audio optional */ }
  }, [notifications, unlocked])

  async function tryUnlock() {
    setAuthLoading(true)
    setPassError(false)
    try {
      const res = await fetch(`${API}/auth/authority-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Individual credentials only: badge number (username) + the officer's
        // own password. Identity is resolved server-side from these — the client
        // no longer supplies officer_name/role.
        body: JSON.stringify({
          badge_number: badge.trim(),
          password: pass,
        })
      })
      if (res.ok) {
        const data = await res.json()
        setAuthorityToken(data.access_token)
        setUnlocked(true)
        setPassError(false)
      } else {
        setPassError(true)
        setPass('')
      }
    } catch {
      setPassError(true)
    } finally {
      setAuthLoading(false)
    }
  }

  function handleLock() {
    clearAuthorityToken()
    setUnlocked(false)
    setPass('')
  }

  async function fetchCases() {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)
      if (statusFilter) params.set('status', statusFilter)
      const res = await secureFetch(`/cases?${params}`)
      if (!res.ok) throw new Error('Server error')
      const data = await res.json()
      setCases(data.cases || [])
    } catch { setCases([]) } finally { setLoading(false) }
  }

  async function updateCaseStatus(caseId: string, status: string) {
    try {
      const res = await secureFetch(`/cases/${caseId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status })
      })
      if (!res.ok) throw new Error('Server error')
      fetchCases()
    } catch (e) {
      console.error('Failed to update case status', e)
    }
  }


  const startLiveTracking = (c: SOSCase) => {
    if (trackingWsRef.current) {
      try { trackingWsRef.current.close() } catch { /* silent */ }
    }
    setActiveLiveTrackCase(c)
    setLiveCoords(null)
    setTrackingConnected(false)

    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsHost = API.replace(/^https?:\/\//, '') || 'localhost:8000'
      const token = getAuthorityToken() || ''
      const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws/track/${c.case_id}?token=${encodeURIComponent(token)}&role=subscriber`)
      trackingWsRef.current = ws
      
      ws.onopen = () => setTrackingConnected(true)
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)
          if (data.latitude && data.longitude) {
            setLiveCoords({
              lat: data.latitude,
              lng: data.longitude,
              accuracy: data.accuracy || 5,
              timestamp: data.timestamp || new Date().toLocaleTimeString(),
              speed: data.speed || 0
            })
          }
        } catch { /* silent */ }
      }
      ws.onclose = () => setTrackingConnected(false)
    } catch (e) {
      console.log('WS connection notice:', e)
    }
  }

  const closeLiveTracking = () => {
    if (trackingWsRef.current) {
      try { trackingWsRef.current.close() } catch { /* silent */ }
      trackingWsRef.current = null
    }
    setActiveLiveTrackCase(null)
    setLiveCoords(null)
    setTrackingConnected(false)
  }

  const dispatchCase = async (caseId: string, agency: 'ERSS_112' | 'NCW_HELPLINE' | 'SNEHA_CRISIS') => {
    try {
      const res = await secureFetch('/authority/dispatch-webhook', {
        method: 'POST',
        body: JSON.stringify({
          case_id: caseId,
          agency_type: agency,
          priority: 'CRITICAL',
          dispatcher_notes: 'Priority dispatch confirmed by Authority Dashboard Officer'
        })
      })
      if (res.ok) {
        const data = await res.json()
        setDispatchStatusMap(prev => ({
          ...prev,
          [caseId]: { agency, status: 'DISPATCHED', dispatch_id: data.dispatch_id }
        }))
        alert(`🚨 Case ${caseId} dispatched to ${agency}!\nDispatch ID: ${data.dispatch_id}\nEstimated Response: ${data.estimated_arrival_minutes} mins.`)
      }
    } catch (e) {
      alert('Failed to connect to dispatch gateway')
    }
  }

  // ── DIR Form-1 Generation ──
  const generateDIRForm = async (c: SOSCase) => {
    setDirFormCase(c)
    setDirFormData(null)
    setDirGenerating(true)
    try {
      const res = await secureFetch('/authority/generate-dir-form', {
        method: 'POST',
        body: JSON.stringify({
          case_id: c.case_id,
          officer_name: dirOfficer.name,
          officer_designation: dirOfficer.designation,
          station_name: dirOfficer.station,
          district: dirOfficer.district
        })
      })
      if (res.ok) {
        const data = await res.json()
        setDirFormData(data)
      } else {
        alert('Failed to generate DIR Form. Check backend connection.')
      }
    } catch {
      alert('Network error generating DIR Form.')
    } finally {
      setDirGenerating(false)
    }
  }

  const printDIRForm = () => {
    const printWindow = window.open('', '_blank')
    if (!printWindow || !dirFormData) return
    // SECURITY: dirFormData mixes AI-generated text (dir_report_text) and
    // user/case-derived fields (summary, location, nature_of_abuse, …). These
    // are UNTRUSTED and must never be written into the print DOM raw, or a
    // crafted case description / prompt-injected AI report could execute script
    // in this same-origin window. Escape every dynamic value before interpolation.
    const esc = (v: unknown): string =>
      String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    const d = dirFormData
    const needs = (d.needs || []).map(esc).join(', ') || 'N/A'
    const legal = (d.legal_sections || [])
      .map((s: string) => '<span class="legal-badge">' + esc(s) + '</span>').join(' ')
    const relief = (d.relief_recommended || [])
      .map((r: string) => '<span class="legal-badge">' + esc(r) + '</span>').join(' ')
    printWindow.document.write(`
      <html><head><title>DIR Form-1 — ${esc(d.dir_form_number)}</title>
      <style>
        body { font-family: 'Times New Roman', serif; max-width: 800px; margin: 40px auto; padding: 20px; color: #1a1a1a; line-height: 1.7; }
        h1 { text-align: center; font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 10px; }
        h2 { font-size: 14px; background: #f0f0f0; padding: 6px 10px; margin-top: 20px; border-left: 4px solid #be185d; }
        .field { margin: 8px 0; font-size: 13px; }
        .field strong { display: inline-block; min-width: 200px; }
        .report-body { white-space: pre-wrap; font-size: 13px; border: 1px solid #ccc; padding: 16px; border-radius: 6px; margin: 12px 0; background: #fafafa; }
        .legal-badge { display: inline-block; background: #fee2e2; color: #dc2626; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin: 2px; }
        .seal { text-align: center; margin-top: 40px; padding: 20px; border-top: 2px solid #333; font-size: 12px; }
        @media print { body { margin: 20px; } }
      </style></head><body>
      <h1>DOMESTIC INCIDENT REPORT (DIR)<br/>Form-1 under Section 9(b) of PWDVA 2005</h1>
      <h2>CASE REFERENCE</h2>
      <div class="field"><strong>DIR Form Number:</strong> ${esc(d.dir_form_number)}</div>
      <div class="field"><strong>Haven Case ID:</strong> ${esc(d.case_id)}</div>
      <div class="field"><strong>Generated:</strong> ${esc(new Date(d.generated_at).toLocaleString())}</div>
      <div class="field"><strong>Officer:</strong> ${esc(d.officer_name || 'N/A')} (${esc(d.officer_designation || 'Protection Officer')})</div>
      <div class="field"><strong>Station:</strong> ${esc(d.station_name || 'N/A')}</div>
      <div class="field"><strong>District:</strong> ${esc(d.district || 'N/A')}</div>
      <h2>CASE ASSESSMENT</h2>
      <div class="field"><strong>Severity:</strong> ${esc((d.case_severity || 'unknown').toUpperCase())}</div>
      <div class="field"><strong>Nature of Abuse:</strong> ${esc(d.nature_of_abuse || 'N/A')}</div>
      <div class="field"><strong>Immediate Danger:</strong> ${d.immediate_danger ? '⚠️ YES — IMMEDIATE RISK' : 'No immediate risk detected'}</div>
      <div class="field"><strong>Location:</strong> ${esc(d.location || 'N/A')}</div>
      <div class="field"><strong>Summary:</strong> ${esc(d.case_summary || 'N/A')}</div>
      <div class="field"><strong>Victim Needs:</strong> ${needs}</div>
      <h2>FORENSIC EVIDENCE</h2>
      <div class="field"><strong>Evidence Available:</strong> ${d.has_forensic_evidence ? 'YES (SHA-256 Sealed)' : 'No'}</div>
      ${d.evidence_hash ? '<div class="field"><strong>Evidence Hash:</strong> <code>' + esc(d.evidence_hash) + '</code></div>' : ''}
      <h2>DOMESTIC INCIDENT REPORT</h2>
      <div class="report-body">${esc(d.dir_report_text)}</div>
      <h2>APPLICABLE LEGAL PROVISIONS</h2>
      <div>${legal}</div>
      <h2>RELIEF RECOMMENDED</h2>
      <div>${relief}</div>
      <div class="seal">
        <p><strong>HAVEN — Women Safety Intelligence Platform</strong></p>
        <p>This DIR Form-1 was generated under PWDVA 2005 with digital forensic integrity.</p>
        <p>Case ID: ${esc(d.case_id)} | DIR: ${esc(d.dir_form_number)}</p>
      </div>
      </body></html>
    `)
    printWindow.document.close()
    setTimeout(() => printWindow.print(), 500)
  }

  // ── Discreet Dispatch for DV cases ──
  const discreetDispatch = async (caseId: string, dispatchType: 'MAHILA_THANA' | 'PLAINCLOTHES' | 'PROTECTION_OFFICER' | 'OSC_SAKHI') => {
    setDiscreetDispatching(caseId + dispatchType)
    try {
      const res = await secureFetch('/authority/discreet-dispatch', {
        method: 'POST',
        body: JSON.stringify({
          case_id: caseId,
          dispatch_type: dispatchType,
          priority: 'HIGH',
          dispatcher_notes: 'Discreet approach — domestic violence in shared household',
          silent_approach: true
        })
      })
      if (res.ok) {
        const data = await res.json()
        setDiscreetDispatchResult(data)
      } else {
        alert('Failed to dispatch. Check backend.')
      }
    } catch {
      alert('Network error dispatching.')
    } finally {
      setDiscreetDispatching('')
    }
  }

  // ── Domestic Risk Assessment ──
  const getDomesticRiskScore = (c: SOSCase): { score: number; level: string; color: string; bg: string; flags: string[] } => {
    const flags: string[] = []
    let score = 0
    const text = ((c.decoded_text || '') + ' ' + (c.nature_of_abuse || '') + ' ' + (c.summary || '')).toLowerCase()
    if (c.immediate_danger) { score += 3; flags.push('Immediate danger') }
    if (c.severity === 'critical') { score += 3; flags.push('Critical severity') }
    else if (c.severity === 'high') { score += 2; flags.push('High severity') }
    if (/kill|murder|death|threat|knife|weapon|strangle|choke/i.test(text)) { score += 3; flags.push('Lethal threats detected') }
    if (/child|children|baby|pregnant|minor/i.test(text)) { score += 2; flags.push('Children/pregnancy involved') }
    if (/confine|lock|trap|imprison|room/i.test(text)) { score += 2; flags.push('Confinement indicated') }
    if (/husband|in-law|sasural|pati|ghar/i.test(text)) { score += 1; flags.push('Domestic/household abuse') }
    if (/burn|acid|dowry|dahej/i.test(text)) { score += 2; flags.push('Dowry/burn violence') }
    if (/sexual|rape|marital rape|force/i.test(text)) { score += 2; flags.push('Sexual violence') }
    if (/repeat|again|always|daily|everyday/i.test(text)) { score += 1; flags.push('Pattern of repeated abuse') }
    score = Math.min(score, 10)
    if (score >= 8) return { score, level: 'EXTREME', color: '#991b1b', bg: '#fee2e2', flags }
    if (score >= 5) return { score, level: 'HIGH', color: '#c2410c', bg: '#fed7aa', flags }
    if (score >= 3) return { score, level: 'MODERATE', color: '#a16207', bg: '#fef9c3', flags }
    return { score, level: 'LOW', color: '#15803d', bg: '#dcfce7', flags }
  }

  // Stable, content-derived key so re-decoding the SAME evidence image (or a
  // React StrictMode double-invoke) never creates a duplicate SOS case. This is
  // the authority decode tool — identical hidden text = the same case.
  function idempotencyKeyFor(text: string): string {
    let h = 5381
    for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0
    return `authdecode-${(h >>> 0).toString(16)}-${text.length}`
  }

  async function decodeImage(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setDecoding(true); setDecodeResult(''); setDecomposed(null)
    const reader = new FileReader()
    reader.onload = async () => {
      const result = reader.result as string
      const b64 = result.split(',')[1]
      setDecodeImg(result)
      try {
        const decRes = await secureFetch('/decode', { method: 'POST', body: JSON.stringify({ image_base64: b64 }) })
        const decData = await decRes.json().catch(() => ({}))
        if (!decRes.ok) {
          // Structured error from backend: detail = {status, error_code, detail}.
          const info = (decData && decData.detail) || {}
          const friendly: Record<string, string> = {
            CORRUPTED_PAYLOAD: 'A hidden message was found but is corrupted — the image may have been recompressed (e.g. saved as JPEG) after encoding. Ask for the original PNG.',
            UNSUPPORTED_FORMAT: 'This image is a lossy format (JPEG/WebP) and cannot carry a hidden message. Upload the original PNG.',
            INVALID_IMAGE: 'The uploaded file could not be read as an image.',
          }
          const code = typeof info === 'object' ? info.error_code : undefined
          setDecodeResult(friendly[code as string] || (typeof info === 'object' && info.detail) || 'Could not decode this image.')
          return
        }
        // 200 responses: either an OK payload or a clean NO_PAYLOAD.
        if (decData.status === 'NO_PAYLOAD' || !decData.decoded_message) {
          setDecodeResult('No hidden message found in this image.')
          return
        }
        const msg: string = decData.decoded_message
        setDecodeResult(msg)
        const decompRes = await secureFetch('/text-decomposition', { method: 'POST', body: JSON.stringify({ text: msg }) })
        if (decompRes.ok) {
          const decompData = await decompRes.json()
          setDecomposed(decompData)
          // Idempotent save — repeat decodes of the same evidence won't duplicate.
          await secureFetch('/save-extracted-data', {
            method: 'POST',
            body: JSON.stringify({ decoded_text: msg, ...decompData, idempotency_key: idempotencyKeyFor(msg) }),
          })
        }
      } catch { setDecodeResult('Error contacting the decode service. Please try again.') }
      finally { setDecoding(false) }
    }
    reader.readAsDataURL(file)
  }

  async function findCulpritMatches() {
    if (!culpritDesc.trim()) return
    setSearching(true); setMatches([]); setSearchType(''); setQueryType('')
    setDegraded(false); setSearchNotice(''); setSearchError(''); setExplainOpen({})
    try {
      const res = await secureFetch('/culprit/find-match', {
        method: 'POST',
        body: JSON.stringify({ description: culpritDesc, top_n: 10, search_mode: searchMode })
      })
      // Distinguish real failures from an honest empty result (requirement 26).
      if (res.status === 503) {
        setSearchError(searchMode === 'description'
          ? 'AI similarity search is temporarily unavailable. Name search is still available.'
          : 'Profile service is temporarily unavailable.')
        return
      }
      if (res.status === 429) { setSearchError('Too many searches. Please wait a moment and try again.'); return }
      if (res.status === 401) { setSearchError('Your session has expired. Please sign in again.'); return }
      if (res.status === 403) { setSearchError('You do not have authority access for profile search.'); return }
      if (!res.ok) { setSearchError('Search failed. Please try again.'); return }
      const data = await res.json()
      setMatches(data.results || data.matches || [])
      setSearchType(data.search_type || '')
      setQueryType(data.query_type || '')
      setDegraded(!!data.degraded)
      setSearchNotice(data.notice || '')
    } catch { setSearchError('Search failed. Please check your connection.') }
    finally { setSearching(false) }
  }

  async function viewProfile(id: string) {
    if (!id) return
    try {
      const res = await secureFetch(`/culprit/profile/${encodeURIComponent(id)}`)
      if (!res.ok) return
      const data = await res.json()
      if (data.profile) setDetailProfile(data.profile as CulpritMatch)
    } catch { /* silent */ }
  }

  async function submitRegister(force: boolean) {
    setReporting(true); setReportMsg(''); setRegErrors({})
    try {
      const res = await secureFetch('/culprit/report', {
        method: 'POST',
        body: JSON.stringify({
          name: reportForm.name, physical_description: reportForm.physical_description,
          behavioral_traits: reportForm.behavioral_traits, location: reportForm.location,
          force, justification: force ? dupJustification : ''
        })
      })
      if (res.status === 400) {
        const data = await res.json().catch(() => ({}))
        const detail = (data as { detail?: unknown }).detail
        if (detail && typeof detail === 'object' && (detail as { errors?: Record<string, string> }).errors) {
          setRegErrors((detail as { errors: Record<string, string> }).errors)
          setReportMsg('Please correct the highlighted fields.')
        } else if (force && !dupJustification.trim()) {
          setReportMsg('Justification is required to register a possible duplicate.')
        } else setReportMsg('Invalid input.')
        return
      }
      if (res.status === 503) { setReportMsg('Profile service is temporarily unavailable.'); return }
      if (res.status === 401) { setReportMsg('Your session has expired. Please sign in again.'); return }
      if (res.status === 403) { setReportMsg('You do not have authority access to register profiles.'); return }
      if (!res.ok) { setReportMsg('Error saving. Check backend.'); return }
      const data = await res.json()
      if (data.duplicate_found) { setDupCandidates(data.candidates || []); setShowDupDialog(true); return }
      const newId = data.profile_id || data.culprit_id
      if (data.success && newId) {
        setReportMsg(`✓ Registered as investigative record: ${newId}`)
        setReportForm({ name: '', physical_description: '', behavioral_traits: '', location: '' })
        setShowDupDialog(false); setDupCandidates([]); setDupJustification('')
      } else setReportMsg('Error saving profile.')
    } catch { setReportMsg('Error saving. Check backend.') }
    finally { setReporting(false) }
  }

  function reportCulprit() {
    if (!reportForm.physical_description || !reportForm.behavioral_traits) return
    submitRegister(false)
  }

  const sevCfg: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
    critical: { bg: '#fee2e2', text: '#dc2626', icon: <AlertTriangle size={11} /> },
    high: { bg: '#fed7aa', text: '#c2410c', icon: <AlertTriangle size={11} /> },
    medium: { bg: '#fef9c3', text: '#a16207', icon: <Clock size={11} /> },
    low: { bg: '#dcfce7', text: '#15803d', icon: <CheckCircle size={11} /> },
  }

  // Password gate
  if (!unlocked) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#1a0a12', padding: 16 }}>
        <div style={{ background: 'white', padding: 'clamp(28px,6vw,48px)', borderRadius: 20, textAlign: 'center', width: '100%', maxWidth: 360, boxShadow: '0 20px 60px rgba(0,0,0,0.4)' }}>
          <Shield size={44} style={{ color: '#be185d', display: 'block', margin: '0 auto 14px' }} />
          <h2 style={{ fontFamily: 'Georgia', fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', color: '#1a0a12', marginBottom: 6 }}>Authority Access</h2>
          <p style={{ fontSize: '0.8rem', color: '#8b6b7d', marginBottom: 20 }}>Restricted to authorized officers</p>
          <input type="text" placeholder="Badge / Officer ID" value={badge} autoComplete="username"
            onChange={e => { setBadge(e.target.value); setPassError(false) }}
            onKeyDown={e => e.key === 'Enter' && tryUnlock()}
            style={{ width: '100%', padding: '12px 14px', borderRadius: 10, border: passError ? '2px solid #dc2626' : '2px solid #e2d6e0', fontSize: '0.9rem', outline: 'none', marginBottom: 8, boxSizing: 'border-box' }}
          />
          <input type="password" placeholder="Password" value={pass} autoComplete="current-password"
            onChange={e => { setPass(e.target.value); setPassError(false) }}
            onKeyDown={e => e.key === 'Enter' && tryUnlock()}
            style={{ width: '100%', padding: '12px 14px', borderRadius: 10, border: passError ? '2px solid #dc2626' : '2px solid #e2d6e0', fontSize: '0.9rem', outline: 'none', marginBottom: 8, boxSizing: 'border-box' }}
          />
          {passError && <p style={{ fontSize: '0.75rem', color: '#dc2626', marginBottom: 8 }}>❌ Invalid credentials. Try again.</p>}
          <button onClick={tryUnlock} disabled={authLoading} className="btn-primary" style={{ width: '100%', marginTop: 4, padding: '12px 20px' }}>
            {authLoading ? 'Verifying...' : 'Enter Dashboard'}
          </button>
          <Link href="/"><p style={{ marginTop: 14, fontSize: '0.75rem', color: '#8b6b7d', cursor: 'pointer' }}>← Back to Haven</p></Link>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8f4f6' }}>
      {/* Header */}
      <div style={{ background: '#1a0a12', padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
         <Link href="/" prefetch={true}><button aria-label="Go back to home" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f472b6', padding: 4 }}><ArrowLeft size={18} /></button></Link>
          <Shield size={20} style={{ color: '#f472b6' }} />
          <div>
            <div style={{ fontWeight: 700, color: '#f472b6', fontFamily: 'Georgia', fontSize: 'clamp(0.8rem, 3vw, 0.95rem)' }}>Haven · Authority</div>
            <div style={{ fontSize: '0.62rem', color: '#8b6b7d' }}>Officers Only</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {unlocked && (
            <div title={`${unreadCount} unread notification${unreadCount !== 1 ? 's' : ''}`} style={{ position: 'relative', display: 'flex', alignItems: 'center', color: '#f472b6', padding: 4 }}>
              <Bell size={17} />
              {unreadCount > 0 && (
                <span style={{ position: 'absolute', top: -4, right: -6, background: '#dc2626', color: 'white', borderRadius: 10, fontSize: '0.6rem', fontWeight: 700, minWidth: 15, height: 15, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 3px' }}>
                  {unreadCount > 99 ? '99+' : unreadCount}
                </span>
              )}
            </div>
          )}
          <button onClick={fetchCases} style={{ background: 'none', border: '1px solid #f472b6', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#f472b6', display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75rem' }}>
            <RefreshCw size={13} /><span>Refresh</span>
          </button>
          <button onClick={handleLock} style={{ background: 'none', border: '1px solid #8b6b7d', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#8b6b7d', fontSize: '0.75rem' }}>Lock</button>
        </div>
      </div>

      {/* Real-time "New SOS Received" indicator */}
      {unlocked && newSosBanner && (
        <div role="alert" style={{ background: 'linear-gradient(135deg,#dc2626,#b91c1c)', color: 'white', padding: '10px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, animation: 'havenSosPulse 1.6s ease-in-out infinite' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', fontWeight: 700 }}>
            <ShieldAlert size={17} /> New SOS Received — {newSosBanner}
          </div>
          <button onClick={() => { setTab('cases'); setNewSosBanner(null) }} style={{ background: 'rgba(255,255,255,0.2)', border: '1px solid rgba(255,255,255,0.5)', color: 'white', borderRadius: 8, padding: '5px 12px', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}>
            View & acknowledge
          </button>
        </div>
      )}
      <style>{`@keyframes havenSosPulse{0%,100%{opacity:1}50%{opacity:0.82}}`}</style>


      {/* Tabs */}
      <div style={{ background: '#2d1b2e', padding: '0 16px', display: 'flex', gap: 0, overflowX: 'auto' }}>
        {([['cases', 'SOS Cases', <Shield key="s" size={13} />], ['decode', 'Decode', <Eye key="e" size={13} />], ['culprit', 'Case & Profile Intelligence', <Users key="u" size={13} />]] as [Tab, string, React.ReactNode][]).map(([id, label, icon]) => (
          <button key={id} onClick={() => setTab(id)} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: 'clamp(10px,2vw,14px) clamp(12px,3vw,20px)', background: 'none', border: 'none', cursor: 'pointer', color: tab === id ? '#f472b6' : '#8b6b7d', fontSize: 'clamp(0.75rem, 2.5vw, 0.85rem)', fontWeight: tab === id ? 700 : 400, borderBottom: tab === id ? '2px solid #f472b6' : '2px solid transparent', whiteSpace: 'nowrap', transition: 'all 0.2s' }}>
            {icon}{label}
          </button>
        ))}
      </div>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: 'clamp(16px,3vw,28px) 16px' }}>
        {/* Cases Tab */}
        {tab === 'cases' && (
          <div>
            <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <select value={severityFilter} aria-label="Filter by severity" onChange={e => setSeverityFilter(e.target.value)} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', fontSize: 'clamp(0.78rem, 2vw, 0.85rem)', color: '#1a0a12' }}>
                <option value="">All Severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
              <select value={statusFilter} aria-label="Filter by status" onChange={e => setStatusFilter(e.target.value)} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', fontSize: 'clamp(0.78rem, 2vw, 0.85rem)', color: '#1a0a12' }}>
                <option value="">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="in_progress">In Progress</option>
                <option value="resolved">Resolved</option>
              </select>
              <span style={{ fontSize: '0.78rem', color: '#8b6b7d' }}>{cases.length} case{cases.length !== 1 ? 's' : ''}</span>
            </div>

            {loading ? (
              <div style={{ textAlign: 'center', padding: 48, color: '#8b6b7d' }}>Loading cases...</div>
            ) : cases.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 48, color: '#8b6b7d' }}>
                <Shield size={36} style={{ margin: '0 auto 10px', display: 'block', opacity: 0.3 }} />
                No cases yet. They appear here when SOS images are decoded.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {cases.map(c => {
                  const sev = c.severity || 'unknown'
                  const cfg = sevCfg[sev] || { bg: '#f3f4f6', text: '#6b7280', icon: null }
                  const risk = getDomesticRiskScore(c)
                  return (
                    <div key={c.case_id} style={{ background: 'white', borderRadius: 14, padding: 'clamp(14px,3vw,22px)', border: '1px solid #e2d6e0', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', color: '#8b6b7d', background: '#f8f4f6', padding: '2px 7px', borderRadius: 4 }}>{c.case_id}</span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: '0.7rem', fontWeight: 600, padding: '2px 8px', borderRadius: 50, background: cfg.bg, color: cfg.text }}>{cfg.icon}{sev.toUpperCase()}</span>
                            
                            {/* Domestic Violence Lethality Risk Badge */}
                            <span style={{ fontSize: '0.68rem', background: risk.bg, color: risk.color, padding: '2px 8px', borderRadius: 50, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 3 }}>
                              <ShieldAlert size={11} /> DV RISK: {risk.level} ({risk.score}/10)
                            </span>

                            {c.trigger_type === 'voice_code' ? (
                              <span style={{ fontSize: '0.68rem', background: 'rgba(168,85,247,0.15)', color: '#7c3aed', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>🎙 VOICE SOS</span>
                            ) : c.trigger_type === 'panic' ? (
                              <span style={{ fontSize: '0.68rem', background: 'rgba(220,38,38,0.1)', color: '#dc2626', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>🚨 PANIC SOS</span>
                            ) : (
                              <span style={{ fontSize: '0.68rem', background: 'rgba(190,24,93,0.1)', color: '#be185d', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>📷 STEGO SOS</span>
                            )}
                            {c.immediate_danger && <span style={{ fontSize: '0.68rem', background: '#fee2e2', color: '#dc2626', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>⚠️ DANGER</span>}
                            <span style={{ fontSize: '0.68rem', background: '#f3f4f6', color: '#6b7280', padding: '2px 8px', borderRadius: 50 }}>{c.status}</span>
                          </div>

                          {/* Risk Indicator Flags */}
                          {risk.flags.length > 0 && (
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                              {risk.flags.map((fl, idx) => (
                                <span key={idx} style={{ fontSize: '0.62rem', background: '#fef2f2', color: '#991b1b', border: '1px solid #fecaca', padding: '1px 6px', borderRadius: 4, fontWeight: 600 }}>
                                  • {fl}
                                </span>
                              ))}
                            </div>
                          )}

                          <p style={{ fontSize: 'clamp(0.8rem, 2.5vw, 0.88rem)', color: '#1a0a12', lineHeight: 1.6, marginBottom: 6 }}>
                            {c.decoded_text?.slice(0, 180)}{(c.decoded_text?.length || 0) > 180 ? '...' : ''}
                          </p>
                          {c.summary && <p style={{ fontSize: '0.75rem', color: '#8b6b7d', fontStyle: 'italic' }}>{c.summary}</p>}
                          {c.location && <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginTop: 4 }}>📍 {c.location}</p>}

                          {c.has_evidence && c.evidence && (
                            <div style={{ marginTop: 10, padding: '8px 12px', background: '#fdf4ff', border: '1px solid #f0abfc', borderRadius: 10 }}>
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, flexWrap: 'wrap' }}>
                                <span style={{ fontSize: '0.72rem', fontWeight: 800, color: '#86198f' }}>
                                  🔒 FORENSIC BLACKBOX EVIDENCE (SHA-256 SEALED)
                                </span>
                                <span style={{ fontSize: '0.62rem', fontFamily: 'monospace', color: '#a21caf', background: '#fae8ff', padding: '2px 5px', borderRadius: 4 }}>
                                  Hash: {c.evidence_hash?.slice(0, 14)}...
                                </span>
                              </div>
                              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                                {c.evidence.audio_base64 && (
                                  <div style={{ flex: 1, minWidth: 180 }}>
                                    <div style={{ fontSize: '0.68rem', color: '#701a75', fontWeight: 600, marginBottom: 2 }}>🎙️ Ambient Audio:</div>
                                    <audio controls src={c.evidence.audio_base64} style={{ width: '100%', height: 28 }} />
                                  </div>
                                )}
                                {c.evidence.image_base64 && (
                                  <div>
                                    <div style={{ fontSize: '0.68rem', color: '#701a75', fontWeight: 600, marginBottom: 4 }}>📸 Scene Snapshot:</div>
                                    <a href={c.evidence.image_base64} target="_blank" rel="noopener noreferrer" title="Click to view full size">
                                      <img
                                        src={c.evidence.image_base64}
                                        alt="Forensic snapshot"
                                        style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 8, border: '2px solid #f0abfc', display: 'block', cursor: 'zoom-in' }}
                                      />
                                    </a>
                                    <div style={{ fontSize: '0.58rem', color: '#a21caf', marginTop: 2 }}>Click to enlarge</div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', flexShrink: 0 }}>
                          {/* Case Time — IST (New Delhi) */}
                          {c.created_at && (() => {
                            const d = new Date(c.created_at)
                            const istTime = new Intl.DateTimeFormat('en-IN', {
                              timeZone: 'Asia/Kolkata',
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                              hour12: true,
                            }).format(d)
                            const istDate = new Intl.DateTimeFormat('en-IN', {
                              timeZone: 'Asia/Kolkata',
                              day: '2-digit',
                              month: 'short',
                              year: 'numeric',
                              weekday: 'short',
                            }).format(d)
                            return (
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#be185d', letterSpacing: '0.01em' }}>
                                  🕐 {istTime}
                                </div>
                                <div style={{ fontSize: '0.65rem', color: '#8b6b7d' }}>
                                  {istDate}
                                </div>
                                <div style={{ fontSize: '0.58rem', color: '#b45309', fontWeight: 600, marginTop: 1 }}>
                                  🇮🇳 IST (New Delhi)
                                </div>
                              </div>
                            )
                          })()}
                          
                          {/* Primary Actions Row */}
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                            <button
                              onClick={() => startLiveTracking(c)}
                              style={{ fontSize: '0.7rem', padding: '4px 10px', borderRadius: 8, background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', cursor: 'pointer', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 4 }}
                            >
                              📡 Live GPS
                            </button>
                            
                            {/* PWDVA DIR Form-1 Generator Button */}
                            <button
                              onClick={() => generateDIRForm(c)}
                              style={{ fontSize: '0.7rem', padding: '4px 10px', borderRadius: 8, background: '#fdf2f8', color: '#be185d', border: '1px solid #fbcfe8', cursor: 'pointer', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 4 }}
                            >
                              <FileText size={12} /> 📄 DIR Form-1 (PWDVA)
                            </button>

                            <button
                              onClick={() => dispatchCase(c.case_id, 'ERSS_112')}
                              style={{ fontSize: '0.7rem', padding: '4px 10px', borderRadius: 8, background: dispatchStatusMap[c.case_id] ? '#dcfce7' : '#fee2e2', color: dispatchStatusMap[c.case_id] ? '#15803d' : '#dc2626', border: 'none', cursor: 'pointer', fontWeight: 700 }}
                            >
                              {dispatchStatusMap[c.case_id] ? '✅ ERSS 112 Dispatched' : '🚨 112 Siren'}
                            </button>
                          </div>

                          {/* Domestic Violence Discreet Dispatch Actions Row */}
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end', marginTop: 2 }}>
                            <button
                              onClick={() => discreetDispatch(c.case_id, 'MAHILA_THANA')}
                              disabled={discreetDispatching === c.case_id + 'MAHILA_THANA'}
                              title="Send Plainclothes Women Police in Unmarked Car"
                              style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe', cursor: 'pointer', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 3 }}
                            >
                              <UserCheck size={11} /> 🤫 Mahila Police (No Siren)
                            </button>
                            <button
                              onClick={() => discreetDispatch(c.case_id, 'PROTECTION_OFFICER')}
                              disabled={discreetDispatching === c.case_id + 'PROTECTION_OFFICER'}
                              title="Alert PWDVA Protection Officer"
                              style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: '#fdf4ff', color: '#a21caf', border: '1px solid #f5d0fe', cursor: 'pointer', fontWeight: 600 }}
                            >
                              🏠 Protection Officer
                            </button>
                            <button
                              onClick={() => discreetDispatch(c.case_id, 'OSC_SAKHI')}
                              disabled={discreetDispatching === c.case_id + 'OSC_SAKHI'}
                              title="Emergency Safe Shelter Transit"
                              style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: '#ecfdf5', color: '#047857', border: '1px solid #a7f3d0', cursor: 'pointer', fontWeight: 600 }}
                            >
                              🛟 Sakhi Shelter Van
                            </button>
                          </div>

                          {/* Status / triage buttons — full SOS lifecycle workflow */}
                          <div style={{ display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
                            {([
                              ['ACKNOWLEDGED', 'Acknowledge', '#dbeafe', '#1d4ed8'],
                              ['IN_PROGRESS', 'Mark in progress', '#fef9c3', '#a16207'],
                              ['RESOLVED', 'Mark resolved', '#dcfce7', '#15803d'],
                            ] as [string, string, string, string][])
                              .filter(([s]) => (c.status || '').toUpperCase() !== s)
                              .map(([s, label, bg, color]) => (
                                <button key={s} onClick={() => updateCaseStatus(c.case_id, s)} style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: bg, color, border: 'none', cursor: 'pointer', fontWeight: 600 }}>
                                  {label}
                                </button>
                              ))}
                            <button onClick={() => toggleLifecycle(c.case_id)} style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: lifecycleCaseId === c.case_id ? '#be185d' : '#f8f4f6', color: lifecycleCaseId === c.case_id ? 'white' : '#8b6b7d', border: '1px solid #e2d6e0', cursor: 'pointer', fontWeight: 600 }}>
                              {lifecycleCaseId === c.case_id ? 'Hide lifecycle' : 'View lifecycle'}
                            </button>
                          </div>

                          {/* Lifecycle timeline */}
                          {lifecycleCaseId === c.case_id && (
                            <div style={{ marginTop: 10, background: '#faf5f8', border: '1px solid #e2d6e0', borderRadius: 10, padding: '8px 12px' }}>
                              {lifecycleLoading ? (
                                <div style={{ fontSize: '0.75rem', color: '#8b6b7d', padding: 8 }}>Loading lifecycle…</div>
                              ) : (
                                <SOSLifecycle currentStatus={(c.status || 'CREATED').toUpperCase()} statusHistory={lifecycleHistory} />
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Decode Tab */}
        {tab === 'decode' && (
          <div style={{ maxWidth: 640, margin: '0 auto' }}>
            <div style={{ background: 'white', borderRadius: 16, padding: 'clamp(20px,4vw,32px)', border: '1px solid #e2d6e0' }}>
              <h2 style={{ fontFamily: 'Georgia', fontSize: 'clamp(1.1rem, 4vw, 1.3rem)', color: '#1a0a12', marginBottom: 8 }}>Decode SOS Image</h2>
              <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.8rem, 2.5vw, 0.88rem)', marginBottom: 20, lineHeight: 1.6 }}>Upload an image to extract any hidden distress message.</p>
              <label style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', border: '2px dashed rgba(190,24,93,0.3)', borderRadius: 14, padding: 'clamp(24px,5vw,36px)', cursor: 'pointer', marginBottom: 20, background: 'rgba(190,24,93,0.02)' }}>
                <Upload size={28} style={{ color: '#be185d', marginBottom: 8 }} />
                <span style={{ fontWeight: 600, color: '#be185d', marginBottom: 4, fontSize: 'clamp(0.85rem, 2.5vw, 0.95rem)' }}>Click to upload image</span>
                <span style={{ fontSize: '0.75rem', color: '#8b6b7d' }}>PNG, JPG supported</span>
                <input type="file" accept="image/*" style={{ display: 'none' }} onChange={decodeImage} />
              </label>
              {decoding && (
                <div style={{ textAlign: 'center', padding: 16, color: '#8b6b7d' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginBottom: 6 }}><div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" /></div>
                  Decoding...
                </div>
              )}
              {decodeImg && !decoding && (
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={decodeImg} alt="Decoded" style={{ width: 'clamp(100px,30vw,140px)', height: 'clamp(100px,30vw,140px)', objectFit: 'cover', borderRadius: 12, border: '2px solid rgba(190,24,93,0.15)', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {decodeResult && (
                      <div style={{ background: '#fce7f3', borderRadius: 10, padding: 12, marginBottom: 10, border: '1px solid rgba(190,24,93,0.2)' }}>
                        <p style={{ fontSize: '0.72rem', fontWeight: 700, color: '#be185d', marginBottom: 5 }}>DECODED MESSAGE:</p>
                        <p style={{ fontSize: 'clamp(0.8rem, 2.5vw, 0.88rem)', color: '#1a0a12', lineHeight: 1.5 }}>{decodeResult}</p>
                      </div>
                    )}
                    {decomposed && (
                      <div style={{ background: '#f8f4f6', borderRadius: 10, padding: 12, border: '1px solid #e2d6e0' }}>
                        <p style={{ fontSize: '0.72rem', fontWeight: 700, color: '#1a0a12', marginBottom: 8 }}>ANALYSIS:</p>
                        {Object.entries(decomposed).map(([k, v]) => v && k !== 'raw' ? (
                          <div key={k} style={{ display: 'flex', gap: 6, marginBottom: 5 }}>
                            <span style={{ fontSize: '0.68rem', color: '#8b6b7d', textTransform: 'uppercase', fontWeight: 600, minWidth: 70, flexShrink: 0 }}>{k.replace(/_/g, ' ')}:</span>
                            <span style={{ fontSize: '0.72rem', color: '#1a0a12' }}>{Array.isArray(v) ? v.join(', ') : String(v)}</span>
                          </div>
                        ) : null)}
                        <p style={{ fontSize: '0.68rem', color: '#15803d', marginTop: 6 }}>✓ Saved to MongoDB</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Culprit Tab */}
        {tab === 'culprit' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))', gap: 16 }}>
            {/* Search */}
            <div style={{ background: 'white', borderRadius: 16, padding: 'clamp(18px,4vw,28px)', border: '1px solid #e2d6e0' }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(0.95rem, 3vw, 1.1rem)', color: '#1a0a12', marginBottom: 8 }}>Search Case &amp; Profile Records</h3>
              <p style={{ fontSize: '0.7rem', color: '#8b6b7d', marginBottom: 10, lineHeight: 1.5, fontStyle: 'italic' }}>
                Records are investigative references, not confirmations of guilt. Treat all matches as leads for human verification.
              </p>

              {/* Search mode toggle */}
              <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
                <button onClick={() => { setSearchMode('name'); setMatches([]); setSearchType(''); setSearchError(''); setSearchNotice(''); setDegraded(false); setExplainOpen({}) }}
                  style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: searchMode === 'name' ? '2px solid #be185d' : '1px solid #e2d6e0', background: searchMode === 'name' ? 'rgba(190,24,93,0.08)' : 'white', color: searchMode === 'name' ? '#be185d' : '#8b6b7d', fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer' }}>
                  🔍 Search by Name
                </button>
                <button onClick={() => { setSearchMode('description'); setMatches([]); setSearchType(''); setSearchError(''); setSearchNotice(''); setDegraded(false); setExplainOpen({}) }}
                  style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: searchMode === 'description' ? '2px solid #be185d' : '1px solid #e2d6e0', background: searchMode === 'description' ? 'rgba(190,24,93,0.08)' : 'white', color: searchMode === 'description' ? '#be185d' : '#8b6b7d', fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer' }}>
                  🤖 Search by Description
                </button>
              </div>

              <textarea value={culpritDesc} onChange={e => setCulpritDesc(e.target.value)}
                placeholder={searchMode === 'name' ? 'Enter full or partial name...' : 'Example: tall, medium build, black jacket, scar on left cheek, seen near Ghaziabad...'}
                style={{ width: '100%', height: 80, padding: 10, borderRadius: 10, border: '1px solid #e2d6e0', fontSize: 'clamp(0.8rem, 2.5vw, 0.85rem)', resize: 'vertical', outline: 'none', fontFamily: 'Georgia' }}
              />
              <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginTop: 4, marginBottom: 8, lineHeight: 1.5 }}>
                {searchMode === 'name'
                  ? 'Searches by exact or partial name — no similarity threshold required.'
                  : 'AI-assisted similarity search. Matches are investigative leads and require human verification.'}
              </p>

              <button onClick={findCulpritMatches} disabled={searching || !culpritDesc.trim()} className="btn-primary" style={{ width: '100%', opacity: searching || !culpritDesc.trim() ? 0.6 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                <Search size={14} />{searching ? 'Searching...' : 'Find'}
              </button>

              {/* Real failure — never shown as an empty result (req 26) */}
              {searchError && (
                <div role="alert" style={{ marginTop: 14, background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', borderRadius: 10, padding: '10px 12px', fontSize: '0.75rem', lineHeight: 1.5 }}>
                  {searchError}
                </div>
              )}
              {/* Keyword-fallback / degraded notice (req 27) */}
              {degraded && !searchError && (
                <div style={{ marginTop: 14, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e', borderRadius: 10, padding: '10px 12px', fontSize: '0.73rem', lineHeight: 1.5 }}>
                  {searchNotice || 'Semantic similarity unavailable; showing keyword matches.'}
                </div>
              )}

              {/* Search results — investigative leads only (req 8) */}
              {matches.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <p style={{ fontSize: '0.78rem', fontWeight: 700, color: '#be185d', marginBottom: 4 }}>
                    {matches.length} potential match{matches.length !== 1 ? 'es' : ''} — human verification required
                  </p>
                  <p style={{ fontSize: '0.68rem', color: '#8b6b7d', marginBottom: 10 }}>
                    {queryType === 'name' ? 'Name search' : queryType === 'mixed' ? 'Name + description search' : 'Description similarity search'}
                    {(degraded || searchType === 'keyword_fallback') ? ' · keyword matches' : ''}
                  </p>
                  {matches.map((m, i) => {
                    const pct = typeof m.match_score === 'number' ? Math.round(m.match_score * 100) : (typeof m.score === 'number' ? Math.round(m.score * 100) : null)
                    const lvl = m.match_level || ''
                    const lvlLabel = lvl === 'high' ? 'High similarity' : lvl === 'moderate' ? 'Moderate similarity' : lvl === 'weak' ? 'Weak similarity' : ''
                    const lvlBg = lvl === 'high' ? '#dcfce7' : lvl === 'moderate' ? '#fef9c3' : 'rgba(190,24,93,0.08)'
                    const lvlColor = lvl === 'high' ? '#15803d' : lvl === 'moderate' ? '#a16207' : '#be185d'
                    const pctLabel = queryType === 'description' ? 'Description similarity' : 'Match strength'
                    const pid = m.profile_id || m.culprit_id
                    return (
                      <div key={i} style={{ background: '#f8f4f6', borderRadius: 12, padding: 14, marginBottom: 10, border: '1px solid #e2d6e0' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                          <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#be185d', textTransform: 'uppercase', letterSpacing: 0.4 }}>Potential Match #{i + 1}</span>
                          {lvlLabel && (
                            <span style={{ fontSize: '0.66rem', background: lvlBg, color: lvlColor, padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>{lvlLabel}</span>
                          )}
                        </div>
                        <div style={{ marginBottom: 6 }}>
                          <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block' }}>Name</span>
                          <span style={{ fontSize: '0.92rem', fontWeight: 700, color: '#1a0a12' }}>{m.name || 'Not recorded'}</span>
                        </div>
                        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 8 }}>
                          <div>
                            <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block' }}>Profile ID</span>
                            <span style={{ fontSize: '0.76rem', fontFamily: 'monospace', color: '#1a0a12' }}>{pid}</span>
                          </div>
                          {m.location && (
                            <div>
                              <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block' }}>Last known location</span>
                              <span style={{ fontSize: '0.76rem', color: '#1a0a12' }}>📍 {m.location}</span>
                            </div>
                          )}
                          {pct !== null && (
                            <div>
                              <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block' }}>{pctLabel}</span>
                              <span style={{ fontSize: '0.76rem', fontWeight: 700, color: '#be185d' }}>{pct}%</span>
                            </div>
                          )}
                        </div>
                        {Array.isArray(m.match_factors) && m.match_factors.length > 0 && (
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                            {m.match_factors.map((f, fi) => (
                              <span key={fi} style={{ fontSize: '0.64rem', padding: '2px 8px', borderRadius: 50, background: f.strength === 'strong' ? '#dcfce7' : f.strength === 'moderate' ? '#fef9c3' : '#f1e7ee', color: f.strength === 'strong' ? '#15803d' : f.strength === 'moderate' ? '#a16207' : '#8b6b7d', fontWeight: 600 }}>{f.label}</span>
                            ))}
                          </div>
                        )}
                        <div style={{ fontSize: '0.68rem', color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '5px 8px', marginBottom: 8 }}>
                          Status: Investigative lead — human verification required
                        </div>
                        <button onClick={() => setExplainOpen(p => ({ ...p, [i]: !p[i] }))}
                          style={{ background: 'none', border: 'none', color: '#be185d', fontSize: '0.7rem', fontWeight: 600, cursor: 'pointer', padding: 0, marginBottom: explainOpen[i] ? 6 : 0 }}>
                          {explainOpen[i] ? '▾ Hide explanation' : '▸ Why this match?'}
                        </button>
                        {explainOpen[i] && (
                          <div style={{ background: 'white', border: '1px solid #e2d6e0', borderRadius: 8, padding: '8px 10px', marginBottom: 8, fontSize: '0.7rem', color: '#5b4652', lineHeight: 1.5 }}>
                            <p style={{ margin: 0 }}>The system found similarities between the query and this stored record. This is a retrieval result, not an identification.</p>
                            {m.match_summary && <p style={{ margin: '6px 0 0' }}>{m.match_summary}</p>}
                            {Array.isArray(m.match_factors) && m.match_factors.length > 0 && (
                              <p style={{ margin: '6px 0 0' }}><strong>Matched signals:</strong> {m.match_factors.map(f => f.label).join(', ')}.</p>
                            )}
                            {!m.location && <p style={{ margin: '6px 0 0', color: '#8b6b7d' }}>Not matched: last known location (missing information).</p>}
                          </div>
                        )}
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                          <button onClick={() => viewProfile(pid)}
                            style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, cursor: 'pointer' }}>View Profile</button>
                          <button onClick={() => setCompareMatch(m)}
                            style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>Compare Details</button>
                          {Array.isArray(m.associated_cases) && m.associated_cases.length > 0 && (
                            <button onClick={() => viewProfile(pid)}
                              style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>View Related Cases ({m.associated_cases.length})</button>
                          )}
                          <button onClick={() => setFlaggedMatch(p => ({ ...p, [i]: true }))}
                            style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#8b6b7d', fontWeight: 600, cursor: 'pointer' }}>Report Incorrect Match</button>
                        </div>
                        {flaggedMatch[i] && (
                          <p style={{ fontSize: '0.66rem', color: '#8b6b7d', marginTop: 6, marginBottom: 0 }}>Noted — please record incorrect matches in the case file for human review.</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
              {/* No-match experience (req 20) — only when the search truly succeeded but was empty */}
              {matches.length === 0 && culpritDesc && !searching && !searchError && (
                <div style={{ marginTop: 14, background: '#f8f4f6', border: '1px solid #e2d6e0', borderRadius: 12, padding: 14 }}>
                  <p style={{ fontSize: '0.8rem', fontWeight: 700, color: '#1a0a12', marginBottom: 4 }}>
                    {searchMode === 'name' ? 'No matching record found.' : 'No strong description matches were found.'}
                  </p>
                  <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginBottom: 10, lineHeight: 1.5 }}>
                    {searchMode === 'name'
                      ? 'Try a partial name or an alternate spelling.'
                      : 'Try broadening the description, or search by name or location.'}
                  </p>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {searchMode === 'description' && (
                      <button onClick={() => { setSearchMode('name'); setMatches([]); setSearchType(''); setSearchNotice(''); setDegraded(false) }}
                        style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, cursor: 'pointer' }}>Search by name</button>
                    )}
                    {searchMode === 'name' && (
                      <button onClick={() => { setSearchMode('description'); setMatches([]); setSearchType(''); setSearchNotice(''); setDegraded(false) }}
                        style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, cursor: 'pointer' }}>Search by description</button>
                    )}
                    <button onClick={() => { setCulpritDesc(''); setMatches([]) }}
                      style={{ fontSize: '0.68rem', padding: '5px 10px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>Clear query</button>
                  </div>
                </div>
              )}
            </div>

            {/* Register */}
            <div style={{ background: 'white', borderRadius: 16, padding: 'clamp(18px,4vw,28px)', border: '1px solid #e2d6e0' }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(0.95rem, 3vw, 1.1rem)', color: '#1a0a12', marginBottom: 8 }}>Register New Profile</h3>
              <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.75rem, 2vw, 0.82rem)', marginBottom: 14, lineHeight: 1.5 }}>Stored as an investigative reference, searchable by Authority users only. All entries require human verification and are not confirmations of guilt.</p>
              {([
                { key: 'name', label: 'Name (optional)', placeholder: 'Full name if known', helper: '' },
                { key: 'physical_description', label: 'Physical Description *', placeholder: 'Height, approximate build, age range, clothing, distinguishing physical features...', helper: '' },
                { key: 'behavioral_traits', label: 'Behavioral Traits *', placeholder: 'e.g. seen loitering, followed the reporter, raised voice...', helper: 'Observed behavior only. Avoid unverified allegations — not a personality or criminal classification.' },
                { key: 'location', label: 'Last Known Location', placeholder: 'City/area and approximate time if known', helper: '' },
              ] as { key: string; label: string; placeholder: string; helper: string }[]).map(field => (
                <div key={field.key} style={{ marginBottom: 12 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#1a0a12', display: 'block', marginBottom: 4 }}>{field.label}</label>
                  <input value={reportForm[field.key as keyof typeof reportForm]} onChange={e => setReportForm(prev => ({ ...prev, [field.key]: e.target.value }))} placeholder={field.placeholder}
                    style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: regErrors[field.key] ? '1.5px solid #dc2626' : '1px solid #e2d6e0', fontSize: 'clamp(0.8rem, 2.5vw, 0.83rem)', outline: 'none' }}
                  />
                  {field.helper && <p style={{ fontSize: '0.66rem', color: '#8b6b7d', marginTop: 3, lineHeight: 1.4 }}>{field.helper}</p>}
                  {regErrors[field.key] && <p style={{ fontSize: '0.66rem', color: '#dc2626', marginTop: 3 }}>{regErrors[field.key]}</p>}
                </div>
              ))}
              {reportMsg && <p style={{ fontSize: '0.78rem', color: reportMsg.startsWith('✓') ? '#15803d' : '#dc2626', marginBottom: 10 }}>{reportMsg}</p>}
              <button onClick={reportCulprit} disabled={reporting || !reportForm.physical_description || !reportForm.behavioral_traits} className="btn-primary" style={{ width: '100%', opacity: reporting || !reportForm.physical_description || !reportForm.behavioral_traits ? 0.6 : 1 }}>
                {reporting ? 'Saving...' : 'Register Profile'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Duplicate-detection dialog (req 13) ── */}
      {showDupDialog && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 18, padding: 22, maxWidth: 460, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: '1.05rem', color: '#1a0a12', margin: 0 }}>Possible existing record found</h3>
              <button onClick={() => { setShowDupDialog(false); setDupJustification('') }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}><X size={18} /></button>
            </div>
            <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginBottom: 12, lineHeight: 1.5 }}>One or more records look similar. Review before creating a new one to avoid duplicates.</p>
            {dupCandidates.map((c, i) => (
              <div key={i} style={{ background: '#f8f4f6', border: '1px solid #e2d6e0', borderRadius: 10, padding: 10, marginBottom: 8 }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#1a0a12' }}>{c.name || 'Not recorded'}</div>
                <div style={{ fontSize: '0.68rem', fontFamily: 'monospace', color: '#8b6b7d' }}>{c.profile_id}</div>
                {c.location && <div style={{ fontSize: '0.7rem', color: '#be185d', marginTop: 2 }}>📍 {c.location}</div>}
                {Array.isArray(c.reasons) && c.reasons.length > 0 && <div style={{ fontSize: '0.66rem', color: '#8b6b7d', marginTop: 3 }}>Matched on: {c.reasons.join(', ')}</div>}
                <button onClick={() => { viewProfile(c.profile_id); setShowDupDialog(false) }} style={{ marginTop: 6, fontSize: '0.66rem', padding: '4px 9px', borderRadius: 7, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, cursor: 'pointer' }}>Use existing record</button>
              </div>
            ))}
            <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#1a0a12', display: 'block', marginTop: 6, marginBottom: 4 }}>Justification (required to register anyway)</label>
            <textarea value={dupJustification} onChange={e => setDupJustification(e.target.value)} placeholder="Why is this a distinct record?" style={{ width: '100%', height: 54, padding: 8, borderRadius: 8, border: '1px solid #e2d6e0', fontSize: '0.75rem', resize: 'vertical', outline: 'none' }} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button onClick={() => { setShowDupDialog(false); setDupJustification('') }} style={{ flex: 1, fontSize: '0.74rem', padding: '8px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>Cancel</button>
              <button onClick={() => submitRegister(true)} disabled={reporting || !dupJustification.trim()} style={{ flex: 1, fontSize: '0.74rem', padding: '8px', borderRadius: 8, border: 'none', background: '#be185d', color: 'white', fontWeight: 600, cursor: 'pointer', opacity: reporting || !dupJustification.trim() ? 0.6 : 1 }}>Register anyway</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Profile detail modal (req 16) ── */}
      {detailProfile && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 18, padding: 22, maxWidth: 480, width: '100%', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: '1.05rem', color: '#1a0a12', margin: 0 }}>Profile Record</h3>
              <button onClick={() => setDetailProfile(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}><X size={18} /></button>
            </div>
            <div style={{ fontSize: '0.66rem', color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '5px 8px', marginBottom: 12 }}>Investigative reference — human verification required. Not a confirmation of guilt.</div>
            {[
              { l: 'Profile ID', v: detailProfile.profile_id || detailProfile.culprit_id, mono: true },
              { l: 'Name', v: detailProfile.name || 'Not recorded' },
              { l: 'Physical description', v: detailProfile.physical_description },
              { l: 'Behavioral observations', v: detailProfile.behavioral_traits },
              { l: 'Last known location', v: detailProfile.location || 'Unknown' },
              { l: 'Created', v: detailProfile.created_at || '—' },
              { l: 'Updated', v: detailProfile.updated_at || '—' },
            ].map((row, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block' }}>{row.l}</span>
                <span style={{ fontSize: '0.8rem', color: '#1a0a12', fontFamily: row.mono ? 'monospace' : 'inherit', lineHeight: 1.5 }}>{row.v}</span>
              </div>
            ))}
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: '0.62rem', color: '#8b6b7d', display: 'block', marginBottom: 4 }}>Associated cases</span>
              {Array.isArray(detailProfile.associated_cases) && detailProfile.associated_cases.length > 0 ? (
                detailProfile.associated_cases.map((ac, i) => (
                  <div key={i} style={{ fontSize: '0.72rem', color: '#1a0a12', background: '#f8f4f6', border: '1px solid #e2d6e0', borderRadius: 8, padding: '6px 8px', marginBottom: 4 }}>
                    <span style={{ fontFamily: 'monospace' }}>{ac.case_id}</span> — {ac.relationship}
                  </div>
                ))
              ) : <span style={{ fontSize: '0.72rem', color: '#8b6b7d' }}>None linked.</span>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button onClick={() => { setCompareMatch(detailProfile); setDetailProfile(null) }} style={{ flex: 1, fontSize: '0.74rem', padding: '8px', borderRadius: 8, border: '1px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, cursor: 'pointer' }}>Compare with query</button>
              <button onClick={() => setDetailProfile(null)} style={{ flex: 1, fontSize: '0.74rem', padding: '8px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Compare mode (req 17) — query vs profile, never probability of guilt ── */}
      {compareMatch && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 18, padding: 22, maxWidth: 620, width: '100%', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: '1.05rem', color: '#1a0a12', margin: 0 }}>Compare: Query vs Record</h3>
              <button onClick={() => setCompareMatch(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}><X size={18} /></button>
            </div>
            <div style={{ fontSize: '0.66rem', color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '5px 8px', marginBottom: 12 }}>Side-by-side comparison for human review only. Similarity is not proof of identity or guilt.</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div style={{ fontSize: '0.66rem', fontWeight: 700, color: '#be185d', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.4 }}>Your query</div>
                <div style={{ fontSize: '0.62rem', color: '#8b6b7d' }}>{searchMode === 'name' ? 'Name search' : 'Description search'}</div>
                <div style={{ fontSize: '0.78rem', color: '#1a0a12', background: '#f8f4f6', border: '1px solid #e2d6e0', borderRadius: 8, padding: 8, marginTop: 4, lineHeight: 1.5 }}>{culpritDesc || '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.66rem', fontWeight: 700, color: '#be185d', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.4 }}>Stored record</div>
                {[
                  { l: 'Name', v: compareMatch.name || 'Not recorded' },
                  { l: 'Physical', v: compareMatch.physical_description },
                  { l: 'Behavior', v: compareMatch.behavioral_traits },
                  { l: 'Location', v: compareMatch.location || 'Unknown' },
                ].map((row, i) => (
                  <div key={i} style={{ marginBottom: 6 }}>
                    <span style={{ fontSize: '0.6rem', color: '#8b6b7d', display: 'block' }}>{row.l}</span>
                    <span style={{ fontSize: '0.74rem', color: '#1a0a12', lineHeight: 1.5 }}>{row.v}</span>
                  </div>
                ))}
              </div>
            </div>
            <button onClick={() => setCompareMatch(null)} style={{ width: '100%', marginTop: 12, fontSize: '0.74rem', padding: '8px', borderRadius: 8, border: '1px solid #e2d6e0', background: 'white', color: '#5b4652', fontWeight: 600, cursor: 'pointer' }}>Close</button>
          </div>
        </div>
      )}

      {/* ── Live GPS Tracking Modal ── */}
      {activeLiveTrackCase && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 24, maxWidth: 500, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: trackingConnected ? '#22c55e' : '#eab308', display: 'inline-block' }} />
                <h3 style={{ fontFamily: 'Georgia', fontSize: '1.15rem', color: '#1a0a12', margin: 0 }}>
                  Live GPS Tracking Room
                </h3>
              </div>
              <button
                onClick={closeLiveTracking}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 14, marginBottom: 16 }}>
              <div style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: 4 }}>
                <strong>Case ID:</strong> {activeLiveTrackCase.case_id}
              </div>
              <div style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: 4 }}>
                <strong>Stream Status:</strong> {trackingConnected ? '🟢 Connected (Real-Time WebSocket)' : '🟡 Waiting for stream signal...'}
              </div>
              {liveCoords ? (
                <div style={{ marginTop: 10, background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: 10, fontSize: '0.82rem', color: '#166534' }}>
                  <div><strong>📍 Live Coordinates:</strong> {liveCoords.lat.toFixed(5)}, {liveCoords.lng.toFixed(5)}</div>
                  <div><strong>🎯 Accuracy:</strong> ±{liveCoords.accuracy.toFixed(1)}m</div>
                  <div><strong>🕒 Last Ping:</strong> {liveCoords.timestamp}</div>
                </div>
              ) : (
                <div style={{ marginTop: 10, padding: 10, fontSize: '0.8rem', color: '#8b6b7d', textAlign: 'center' }}>
                  ⏳ Listening for victim GPS updates...
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              {liveCoords && (
                <a
                  href={`https://maps.google.com/?q=${liveCoords.lat},${liveCoords.lng}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    flex: 1, background: '#2563eb', color: 'white', padding: '11px',
                    borderRadius: 10, textDecoration: 'none', fontWeight: 700, fontSize: '0.85rem',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6
                  }}
                >
                  🗺️ View Live in Google Maps ↗
                </a>
              )}
              <button
                onClick={() => dispatchCase(activeLiveTrackCase.case_id, 'ERSS_112')}
                style={{
                  flex: 1, background: '#dc2626', color: 'white', border: 'none',
                  padding: '11px', borderRadius: 10, fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer'
                }}
              >
                🚨 Fast Dispatch 112
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── DIR Form-1 Modal (PWDVA 2005) ── */}
      {dirFormCase && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 99999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 20, padding: '24px 28px', maxWidth: 680, width: '100%', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid #fce7f3', paddingBottom: 12 }}>
              <div>
                <span style={{ fontSize: '0.68rem', fontWeight: 800, color: '#be185d', background: '#fdf2f8', padding: '2px 8px', borderRadius: 4, textTransform: 'uppercase' }}>
                  PWDVA 2005 · Section 9(b)
                </span>
                <h3 style={{ fontFamily: 'Georgia', fontSize: '1.25rem', color: '#1a0a12', margin: '4px 0 0' }}>
                  Domestic Incident Report (DIR Form-1)
                </h3>
              </div>
              <button
                onClick={() => { setDirFormCase(null); setDirFormData(null) }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Officer details inputs */}
            {!dirFormData && (
              <div style={{ background: '#fdf4ff', border: '1px solid #f0abfc', borderRadius: 12, padding: 16, marginBottom: 16 }}>
                <p style={{ fontSize: '0.8rem', fontWeight: 700, color: '#86198f', marginBottom: 10 }}>
                  👮 Protection / Police Officer Details for Court Filing:
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <input
                    placeholder="Officer Name"
                    value={dirOfficer.name}
                    onChange={e => setDirOfficer(prev => ({ ...prev, name: e.target.value }))}
                    style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #d8b4fe', fontSize: '0.8rem' }}
                  />
                  <input
                    placeholder="Designation (e.g. Protection Officer / Sub-Inspector)"
                    value={dirOfficer.designation}
                    onChange={e => setDirOfficer(prev => ({ ...prev, designation: e.target.value }))}
                    style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #d8b4fe', fontSize: '0.8rem' }}
                  />
                  <input
                    placeholder="Police Station / Mahila Thana"
                    value={dirOfficer.station}
                    onChange={e => setDirOfficer(prev => ({ ...prev, station: e.target.value }))}
                    style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #d8b4fe', fontSize: '0.8rem' }}
                  />
                  <input
                    placeholder="District / City"
                    value={dirOfficer.district}
                    onChange={e => setDirOfficer(prev => ({ ...prev, district: e.target.value }))}
                    style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #d8b4fe', fontSize: '0.8rem' }}
                  />
                </div>
                <button
                  onClick={() => generateDIRForm(dirFormCase)}
                  disabled={dirGenerating}
                  className="btn-primary"
                  style={{ width: '100%', marginTop: 12, padding: '10px 16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                >
                  <FileText size={16} />
                  {dirGenerating ? 'Drafting Official DIR Form via Legal AI...' : 'Generate Official DIR Form-1'}
                </button>
              </div>
            )}

            {/* Generated DIR Preview */}
            {dirFormData && (
              <div>
                <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, marginBottom: 16, fontSize: '0.83rem', color: '#1e293b', maxHeight: 380, overflowY: 'auto', lineHeight: 1.6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #cbd5e1', paddingBottom: 8, marginBottom: 12 }}>
                    <div>
                      <strong>DIR Form No:</strong> <span style={{ color: '#be185d' }}>{dirFormData.dir_form_number}</span>
                    </div>
                    <div>
                      <strong>Generated:</strong> {new Date(dirFormData.generated_at).toLocaleString()}
                    </div>
                  </div>

                  <div style={{ marginBottom: 10 }}>
                    <strong>Officer:</strong> {dirFormData.officer_name || 'Protection Officer'} ({dirFormData.officer_designation}) | <strong>Station:</strong> {dirFormData.station_name || 'N/A'}
                  </div>

                  <div style={{ marginBottom: 10 }}>
                    <strong>Applicable Legal Sections:</strong>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                      {dirFormData.legal_sections.map((s, idx) => (
                        <span key={idx} style={{ background: '#fee2e2', color: '#991b1b', padding: '2px 8px', borderRadius: 4, fontSize: '0.72rem', fontWeight: 700 }}>
                          ⚖️ {s}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'Georgia, serif', background: 'white', padding: 14, borderRadius: 8, border: '1px solid #e2e8f0', marginTop: 12, fontSize: '0.82rem' }}>
                    {dirFormData.dir_report_text}
                  </div>

                  {dirFormData.has_forensic_evidence && (
                    <div style={{ marginTop: 12, padding: 10, background: '#fdf4ff', border: '1px solid #f0abfc', borderRadius: 8, fontSize: '0.75rem', color: '#86198f' }}>
                      <strong>🔒 Forensic Digital Evidence Seal:</strong><br />
                      <code>SHA-256: {dirFormData.evidence_hash}</code> (Digitally verified for Magistrate Court submission)
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    onClick={printDIRForm}
                    style={{ flex: 1, background: '#be185d', color: 'white', border: 'none', padding: '12px', borderRadius: 10, fontWeight: 700, fontSize: '0.88rem', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                  >
                    <Printer size={16} /> 🖨️ Print / Save Court-Ready PDF
                  </button>
                  <button
                    onClick={() => setDirFormData(null)}
                    style={{ background: '#f3f4f6', color: '#4b5563', border: '1px solid #d1d5db', padding: '12px 18px', borderRadius: 10, fontWeight: 600, fontSize: '0.85rem', cursor: 'pointer' }}
                  >
                    Edit Details
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Discreet Plainclothes Dispatch Result Modal ── */}
      {discreetDispatchResult && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 99999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 24, maxWidth: 480, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '1.4rem' }}>🤫</span>
                <div>
                  <h3 style={{ fontFamily: 'Georgia', fontSize: '1.15rem', color: '#1a0a12', margin: 0 }}>
                    Discreet Response Dispatched
                  </h3>
                  <div style={{ fontSize: '0.72rem', color: '#6d28d9', fontWeight: 700 }}>
                    SILENT ENTRY PROTOCOL ACTIVE (NO SIRENS)
                  </div>
                </div>
              </div>
              <button
                onClick={() => setDiscreetDispatchResult(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ background: '#f5f3ff', border: '1px solid #ddd6fe', borderRadius: 12, padding: 16, marginBottom: 16, fontSize: '0.83rem', color: '#4c1d95' }}>
              <div style={{ marginBottom: 6 }}>
                <strong>Dispatch ID:</strong> <code>{discreetDispatchResult.dispatch_id}</code>
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Responding Agency:</strong> {discreetDispatchResult.response_protocol.agency_name}
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Tactical Approach:</strong> {discreetDispatchResult.response_protocol.approach}
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Vehicle:</strong> {discreetDispatchResult.response_protocol.vehicle}
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Siren / Lights:</strong> {discreetDispatchResult.response_protocol.siren ? 'Active' : '🚫 SILENT / OFF (Abuser Protection)'}
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Estimated Arrival:</strong> ⏱️ ~{discreetDispatchResult.response_protocol.estimated_minutes} minutes
              </div>
              <div>
                <strong>Direct Control Line:</strong> 📞 {discreetDispatchResult.response_protocol.contact_number}
              </div>
            </div>

            <button
              onClick={() => setDiscreetDispatchResult(null)}
              className="btn-primary"
              style={{ width: '100%', padding: '11px 16px' }}
            >
              Understood / Monitor Live Response
            </button>
          </div>
        </div>
      )}
    </div>
  )
}