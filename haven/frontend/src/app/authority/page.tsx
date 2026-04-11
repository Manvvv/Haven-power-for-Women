'use client'
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { ArrowLeft, Shield, Search, Eye, Upload, Users, AlertTriangle, CheckCircle, Clock, RefreshCw, X } from 'lucide-react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface SOSCase {
  case_id: string; decoded_text: string; severity?: string
  nature_of_abuse?: string; immediate_danger?: boolean; location?: string
  needs?: string[]; summary?: string; status: string; created_at: string
}
interface CulpritMatch {
  name?: string; physical_description: string; behavioral_traits: string
  location?: string; culprit_id: string; score?: number
}
type Tab = 'cases' | 'decode' | 'culprit'

export default function AuthorityPage() {
  const [unlocked, setUnlocked] = useState(false)
  const [pass, setPass] = useState('')
  const [passError, setPassError] = useState(false)
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

  useEffect(() => { if (unlocked) fetchCases() }, [severityFilter, statusFilter, unlocked])

  function tryUnlock() {
    if (pass === 'haven2024') { setUnlocked(true); setPassError(false) }
    else { setPassError(true); setPass('') }
  }

  async function fetchCases() {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)
      if (statusFilter) params.set('status', statusFilter)
      const res = await fetch(`${API}/cases?${params}`)
      const data = await res.json()
      setCases(data.cases || [])
    } catch { setCases([]) } finally { setLoading(false) }
  }

  async function updateCaseStatus(caseId: string, status: string) {
    await fetch(`${API}/cases/${caseId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) })
    fetchCases()
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
        const decRes = await fetch(`${API}/decode`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_base64: b64 }) })
        const decData = await decRes.json()
        const msg: string = decData.decoded_message || ''
        setDecodeResult(msg)
        if (msg && msg !== 'No hidden message found') {
          const decompRes = await fetch(`${API}/text-decomposition`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: msg }) })
          const decompData = await decompRes.json()
          setDecomposed(decompData)
          await fetch(`${API}/save-extracted-data`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decoded_text: msg, ...decompData }) })
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
      const res = await fetch(`${API}/culprit/find-match`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: culpritDesc, top_n: 10, search_mode: searchMode, min_score: searchMode === 'description' ? 0.75 : 0 })
      })
      const data = await res.json()
      setMatches(data.matches || [])
      setSearchType(data.search_type || '')
    } catch { setMatches([]) } finally { setSearching(false) }
  }

  async function reportCulprit() {
    if (!reportForm.physical_description || !reportForm.behavioral_traits) return
    setReporting(true); setReportMsg('')
    try {
      const res = await fetch(`${API}/culprit/report`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: reportForm.name || 'Unknown', physical_description: reportForm.physical_description, behavioral_traits: reportForm.behavioral_traits, location: reportForm.location || '', reporter_id: 'authority' }) })
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
          <button onClick={tryUnlock} className="btn-primary" style={{ width: '100%', marginTop: 4, padding: '12px 20px' }}>Enter Dashboard</button>
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
          <button onClick={() => setUnlocked(false)} style={{ background: 'none', border: '1px solid #8b6b7d', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#8b6b7d', fontSize: '0.75rem' }}>Lock</button>
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
                  return (
                    <div key={c.case_id} style={{ background: 'white', borderRadius: 14, padding: 'clamp(14px,3vw,22px)', border: '1px solid #e2d6e0', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', color: '#8b6b7d', background: '#f8f4f6', padding: '2px 7px', borderRadius: 4 }}>{c.case_id}</span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: '0.7rem', fontWeight: 600, padding: '2px 8px', borderRadius: 50, background: cfg.bg, color: cfg.text }}>{cfg.icon}{sev.toUpperCase()}</span>
                            {c.immediate_danger && <span style={{ fontSize: '0.68rem', background: '#fee2e2', color: '#dc2626', padding: '2px 8px', borderRadius: 50, fontWeight: 700 }}>⚠️ DANGER</span>}
                            <span style={{ fontSize: '0.68rem', background: '#f3f4f6', color: '#6b7280', padding: '2px 8px', borderRadius: 50 }}>{c.status}</span>
                          </div>
                          <p style={{ fontSize: 'clamp(0.8rem, 2.5vw, 0.88rem)', color: '#1a0a12', lineHeight: 1.6, marginBottom: 6 }}>
                            {c.decoded_text?.slice(0, 180)}{(c.decoded_text?.length || 0) > 180 ? '...' : ''}
                          </p>
                          {c.summary && <p style={{ fontSize: '0.75rem', color: '#8b6b7d', fontStyle: 'italic' }}>{c.summary}</p>}
                          {c.location && <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginTop: 4 }}>📍 {c.location}</p>}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', flexShrink: 0 }}>
                          <span style={{ fontSize: '0.68rem', color: '#8b6b7d' }}>{c.created_at ? new Date(c.created_at).toLocaleDateString() : ''}</span>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {(['in_progress', 'resolved'] as string[]).filter(s => s !== c.status).map(s => (
                              <button key={s} onClick={() => updateCaseStatus(c.case_id, s)} style={{ fontSize: '0.7rem', padding: '4px 10px', borderRadius: 8, background: s === 'resolved' ? '#dcfce7' : '#fef9c3', color: s === 'resolved' ? '#15803d' : '#a16207', border: 'none', cursor: 'pointer', fontWeight: 600 }}>
                                {s.replace('_', ' ')}
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
    </div>
  )
}