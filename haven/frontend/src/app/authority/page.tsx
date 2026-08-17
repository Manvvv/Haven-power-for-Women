'use client'
import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { ArrowLeft, Shield, Search, Eye, Upload, Users, AlertTriangle, CheckCircle, Clock, RefreshCw, X, FileText, UserCheck, ShieldAlert, Printer } from 'lucide-react'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { secureFetch, getAuthorityToken, setAuthorityToken, clearAuthorityToken } from '@/lib/api'

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
interface CulpritMatch {
  name?: string; physical_description: string; behavioral_traits: string
  location?: string; culprit_id: string; score?: number
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

  async function tryUnlock() {
    setAuthLoading(true)
    setPassError(false)
    try {
      const res = await fetch(`${API}/auth/authority-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          password: pass,
          badge_number: 'PO-1091',
          officer_name: dirOfficer.name || 'Protection Officer'
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
    printWindow.document.write(`
      <html><head><title>DIR Form-1 — ${dirFormData.dir_form_number}</title>
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
      <div class="field"><strong>DIR Form Number:</strong> ${dirFormData.dir_form_number}</div>
      <div class="field"><strong>Haven Case ID:</strong> ${dirFormData.case_id}</div>
      <div class="field"><strong>Generated:</strong> ${new Date(dirFormData.generated_at).toLocaleString()}</div>
      <div class="field"><strong>Officer:</strong> ${dirFormData.officer_name || 'N/A'} (${dirFormData.officer_designation || 'Protection Officer'})</div>
      <div class="field"><strong>Station:</strong> ${dirFormData.station_name || 'N/A'}</div>
      <div class="field"><strong>District:</strong> ${dirFormData.district || 'N/A'}</div>
      <h2>CASE ASSESSMENT</h2>
      <div class="field"><strong>Severity:</strong> ${(dirFormData.case_severity || 'unknown').toUpperCase()}</div>
      <div class="field"><strong>Nature of Abuse:</strong> ${dirFormData.nature_of_abuse || 'N/A'}</div>
      <div class="field"><strong>Immediate Danger:</strong> ${dirFormData.immediate_danger ? '⚠️ YES — IMMEDIATE RISK' : 'No immediate risk detected'}</div>
      <div class="field"><strong>Location:</strong> ${dirFormData.location || 'N/A'}</div>
      <div class="field"><strong>Summary:</strong> ${dirFormData.case_summary || 'N/A'}</div>
      <div class="field"><strong>Victim Needs:</strong> ${(dirFormData.needs || []).join(', ') || 'N/A'}</div>
      <h2>FORENSIC EVIDENCE</h2>
      <div class="field"><strong>Evidence Available:</strong> ${dirFormData.has_forensic_evidence ? 'YES (SHA-256 Sealed)' : 'No'}</div>
      ${dirFormData.evidence_hash ? '<div class="field"><strong>Evidence Hash:</strong> <code>' + dirFormData.evidence_hash + '</code></div>' : ''}
      <h2>DOMESTIC INCIDENT REPORT</h2>
      <div class="report-body">${dirFormData.dir_report_text}</div>
      <h2>APPLICABLE LEGAL PROVISIONS</h2>
      <div>${(dirFormData.legal_sections || []).map((s: string) => '<span class="legal-badge">' + s + '</span>').join(' ')}</div>
      <h2>RELIEF RECOMMENDED</h2>
      <div>${(dirFormData.relief_recommended || []).map((r: string) => '<span class="legal-badge">' + r + '</span>').join(' ')}</div>
      <div class="seal">
        <p><strong>HAVEN — Women Safety Intelligence Platform</strong></p>
        <p>This DIR Form-1 was generated under PWDVA 2005 with digital forensic integrity.</p>
        <p>Case ID: ${dirFormData.case_id} | DIR: ${dirFormData.dir_form_number}</p>
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
        if (!decRes.ok) throw new Error('Decode server error')
        const decData = await decRes.json()
        const msg: string = decData.decoded_message || ''
        setDecodeResult(msg)
        if (msg && msg !== 'No hidden message found') {
          const decompRes = await secureFetch('/text-decomposition', { method: 'POST', body: JSON.stringify({ text: msg }) })
          if (decompRes.ok) {
            const decompData = await decompRes.json()
            setDecomposed(decompData)
            await secureFetch('/save-extracted-data', { method: 'POST', body: JSON.stringify({ decoded_text: msg, ...decompData }) })
          }
        }
      } catch { setDecodeResult('Error decoding image.') }
      finally { setDecoding(false) }
    }
    reader.readAsDataURL(file)
  }

  async function findCulpritMatches() {
    if (!culpritDesc.trim()) return
    setSearching(true); setMatches([]); setSearchType('')
    try {
      const res = await secureFetch('/culprit/find-match', {
        method: 'POST',
        body: JSON.stringify({ description: culpritDesc, top_n: 10, search_mode: searchMode, min_score: searchMode === 'description' ? 0.75 : 0 })
      })
      if (!res.ok) throw new Error('Search server error')
      const data = await res.json()
      setMatches(data.matches || [])
      setSearchType(data.search_type || '')
    } catch { setMatches([]) } finally { setSearching(false) }
  }

  async function reportCulprit() {
    if (!reportForm.physical_description || !reportForm.behavioral_traits) return
    setReporting(true); setReportMsg('')
    try {
      const res = await secureFetch('/culprit/report', {
        method: 'POST',
        body: JSON.stringify({ name: reportForm.name || 'Unknown', physical_description: reportForm.physical_description, behavioral_traits: reportForm.behavioral_traits, location: reportForm.location || '', reporter_id: 'authority' })
      })
      if (!res.ok) throw new Error('Report server error')
      const data = await res.json()
      if (data.culprit_id) { setReportMsg(`✓ Registered: ${data.culprit_id}`); setReportForm({ name: '', physical_description: '', behavioral_traits: '', location: '' }) }
      else setReportMsg(`Error: ${JSON.stringify(data)}`)
    } catch { setReportMsg('Error saving. Check backend.') }
    finally { setReporting(false) }
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
          <input type="password" placeholder="Enter access code" value={pass}
            onChange={e => { setPass(e.target.value); setPassError(false) }}
            onKeyDown={e => e.key === 'Enter' && tryUnlock()}
            style={{ width: '100%', padding: '12px 14px', borderRadius: 10, border: passError ? '2px solid #dc2626' : '2px solid #e2d6e0', fontSize: '0.9rem', outline: 'none', marginBottom: 8, boxSizing: 'border-box' }}
          />
          {passError && <p style={{ fontSize: '0.75rem', color: '#dc2626', marginBottom: 8 }}>❌ Wrong code. Try again.</p>}
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
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={fetchCases} style={{ background: 'none', border: '1px solid #f472b6', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#f472b6', display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75rem' }}>
            <RefreshCw size={13} /><span>Refresh</span>
          </button>
          <button onClick={handleLock} style={{ background: 'none', border: '1px solid #8b6b7d', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#8b6b7d', fontSize: '0.75rem' }}>Lock</button>
        </div>
      </div>


      {/* Tabs */}
      <div style={{ background: '#2d1b2e', padding: '0 16px', display: 'flex', gap: 0, overflowX: 'auto' }}>
        {([['cases', 'SOS Cases', <Shield key="s" size={13} />], ['decode', 'Decode', <Eye key="e" size={13} />], ['culprit', 'Culprit DB', <Users key="u" size={13} />]] as [Tab, string, React.ReactNode][]).map(([id, label, icon]) => (
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

                          {/* Status buttons */}
                          <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
                            {(['in_progress', 'resolved'] as string[]).filter(s => s !== c.status).map(s => (
                              <button key={s} onClick={() => updateCaseStatus(c.case_id, s)} style={{ fontSize: '0.67rem', padding: '3px 8px', borderRadius: 6, background: s === 'resolved' ? '#dcfce7' : '#fef9c3', color: s === 'resolved' ? '#15803d' : '#a16207', border: 'none', cursor: 'pointer', fontWeight: 600 }}>
                                Mark {s.replace('_', ' ')}
                              </button>
                            ))}
                          </div>
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
              <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(0.95rem, 3vw, 1.1rem)', color: '#1a0a12', marginBottom: 8 }}>Find Culprit Profiles</h3>

              {/* Search mode toggle */}
              <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
                <button onClick={() => { setSearchMode('name'); setMatches([]); setSearchType('') }}
                  style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: searchMode === 'name' ? '2px solid #be185d' : '1px solid #e2d6e0', background: searchMode === 'name' ? 'rgba(190,24,93,0.08)' : 'white', color: searchMode === 'name' ? '#be185d' : '#8b6b7d', fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer' }}>
                  🔍 Search by Name
                </button>
                <button onClick={() => { setSearchMode('description'); setMatches([]); setSearchType('') }}
                  style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: searchMode === 'description' ? '2px solid #be185d' : '1px solid #e2d6e0', background: searchMode === 'description' ? 'rgba(190,24,93,0.08)' : 'white', color: searchMode === 'description' ? '#be185d' : '#8b6b7d', fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer' }}>
                  🤖 Search by Description
                </button>
              </div>

              <textarea value={culpritDesc} onChange={e => setCulpritDesc(e.target.value)}
                placeholder={searchMode === 'name' ? 'Enter full name, e.g. Manav Choudhary' : 'Describe appearance/behavior, e.g. tall male, aggressive, age 30-35, black beard...'}
                style={{ width: '100%', height: 80, padding: 10, borderRadius: 10, border: '1px solid #e2d6e0', fontSize: 'clamp(0.8rem, 2.5vw, 0.85rem)', resize: 'vertical', outline: 'none', fontFamily: 'Georgia' }}
              />
              <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginTop: 4, marginBottom: 8 }}>
                {searchMode === 'name' ? 'Searches by exact or partial name match.' : 'AI vector search — only shows results above 75% similarity.'}
              </p>

              <button onClick={findCulpritMatches} disabled={searching || !culpritDesc.trim()} className="btn-primary" style={{ width: '100%', opacity: searching || !culpritDesc.trim() ? 0.6 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                <Search size={14} />{searching ? 'Searching...' : 'Find'}
              </button>

              {/* Results */}
              {matches.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <p style={{ fontSize: '0.78rem', fontWeight: 700, color: '#be185d' }}>
                      {matches.length} result{matches.length !== 1 ? 's' : ''} found
                    </p>
                    <span style={{ fontSize: '0.68rem', background: searchType === 'exact_name' ? '#dcfce7' : searchType === 'partial_name' ? '#fef9c3' : 'rgba(190,24,93,0.08)', color: searchType === 'exact_name' ? '#15803d' : searchType === 'partial_name' ? '#a16207' : '#be185d', padding: '2px 8px', borderRadius: 50 }}>
                      {searchType === 'exact_name' ? '✓ Exact match' : searchType === 'partial_name' ? '~ Partial match' : 'AI similarity'}
                    </span>
                  </div>
                  {matches.map((m, i) => (
                    <div key={i} style={{ background: '#f8f4f6', borderRadius: 10, padding: 12, marginBottom: 8, border: searchType === 'exact_name' ? '1.5px solid #86efac' : '1px solid #e2d6e0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#1a0a12' }}>{m.name || 'Unknown'}</span>
                        {m.score !== undefined && (
                          <span style={{ fontSize: '0.68rem', background: (m.score >= 0.9) ? '#dcfce7' : (m.score >= 0.75) ? '#fef9c3' : 'rgba(190,24,93,0.1)', color: (m.score >= 0.9) ? '#15803d' : (m.score >= 0.75) ? '#a16207' : '#be185d', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>
                            {(m.score * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      <p style={{ fontSize: '0.75rem', color: '#8b6b7d', lineHeight: 1.5 }}><strong>Physical:</strong> {m.physical_description}</p>
                      <p style={{ fontSize: '0.75rem', color: '#8b6b7d', lineHeight: 1.5 }}><strong>Behavior:</strong> {m.behavioral_traits}</p>
                      {m.location && <p style={{ fontSize: '0.72rem', color: '#be185d', marginTop: 4 }}>📍 {m.location}</p>}
                    </div>
                  ))}
                </div>
              )}
              {matches.length === 0 && culpritDesc && !searching && (
                <p style={{ marginTop: 12, fontSize: '0.78rem', color: '#8b6b7d', textAlign: 'center' }}>
                  {searchMode === 'name' ? 'No profile found with that name.' : 'No matches above threshold. Try different descriptors.'}
                </p>
              )}
            </div>

            {/* Register */}
            <div style={{ background: 'white', borderRadius: 16, padding: 'clamp(18px,4vw,28px)', border: '1px solid #e2d6e0' }}>
              <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(0.95rem, 3vw, 1.1rem)', color: '#1a0a12', marginBottom: 8 }}>Register New Profile</h3>
              <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.75rem, 2vw, 0.82rem)', marginBottom: 14, lineHeight: 1.5 }}>Profile will be embedded and stored for future searches.</p>
              {[
                { key: 'name', label: 'Name (optional)', placeholder: 'Full name if known' },
                { key: 'physical_description', label: 'Physical Description *', placeholder: 'Height, build, age...' },
                { key: 'behavioral_traits', label: 'Behavioral Traits *', placeholder: 'Aggressive, controlling...' },
                { key: 'location', label: 'Last Known Location', placeholder: 'City, area...' },
              ].map(field => (
                <div key={field.key} style={{ marginBottom: 12 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#1a0a12', display: 'block', marginBottom: 4 }}>{field.label}</label>
                  <input value={reportForm[field.key as keyof typeof reportForm]} onChange={e => setReportForm(prev => ({ ...prev, [field.key]: e.target.value }))} placeholder={field.placeholder}
                    style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1px solid #e2d6e0', fontSize: 'clamp(0.8rem, 2.5vw, 0.83rem)', outline: 'none' }}
                  />
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