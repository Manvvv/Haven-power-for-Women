'use client'
/**
 * therapy/safety-plan — user-controlled safety plan, mood check-ins, private
 * journal, and a privacy dashboard for HAVEN's mental-health module.
 *
 * Everything here is tied to the signed-in user (backend requires auth) and is
 * stored ENCRYPTED at rest (spec §9, §14, §15, §22, §35). Nothing on this page
 * contacts anyone; the "people/emergency contacts" fields are the user's own
 * private notes, never dialled automatically.
 */
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ArrowLeft, Shield, HeartPulse, BookOpen, Lock, Trash2, Save, Plus } from 'lucide-react'
import { useUser } from '@clerk/nextjs'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { secureFetch } from '@/lib/api'

type Tab = 'plan' | 'checkin' | 'journal' | 'privacy'

const PLAN_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: 'warning_signs', label: 'My warning signs', hint: 'Thoughts, moods or situations that tell me things are getting hard.' },
  { key: 'things_that_help', label: 'Things that help me cope', hint: 'What has helped me feel steadier before.' },
  { key: 'safe_places', label: 'Places I feel safe', hint: 'Where I can go to feel calmer or safer.' },
  { key: 'people_to_contact', label: 'People I can reach out to', hint: 'Friends or family I trust. (Your notes — HAVEN never contacts them for you.)' },
  { key: 'professional_contacts', label: 'Professional contacts', hint: 'Counsellor, doctor or helpline I can call.' },
  { key: 'things_to_remove_or_avoid', label: 'Things to keep away for now', hint: 'What I want to avoid when I am not doing well.' },
  { key: 'emergency_contacts', label: 'Emergency contacts', hint: 'Who to reach in an emergency. (Your notes only.)' },
]

type PlanState = Record<string, string>   // field -> newline-separated text

export default function SafetyPlanPage() {
  useHavenAuth()
  const { isSignedIn, isLoaded } = useUser()
  const [tab, setTab] = useState<Tab>('plan')
  const [msg, setMsg] = useState<string>('')

  // Safety plan
  const [plan, setPlan] = useState<PlanState>({})
  const [planExists, setPlanExists] = useState(false)
  const [planUpdated, setPlanUpdated] = useState<string | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // Check-ins
  const [checkin, setCheckin] = useState<Record<string, number | ''>>({ mood: '', stress: '', sleep: '', safety: '', support_connection: '' })
  const [checkinNote, setCheckinNote] = useState('')
  const [checkins, setCheckins] = useState<any[]>([])

  // Journal
  const [jMood, setJMood] = useState('')
  const [jTags, setJTags] = useState('')
  const [jNotes, setJNotes] = useState('')
  const [entries, setEntries] = useState<any[]>([])

  // Privacy
  const [privacy, setPrivacy] = useState<any | null>(null)

  const flash = useCallback((m: string) => { setMsg(m); setTimeout(() => setMsg(''), 3500) }, [])

  // ── Loaders & handlers ──
  const loadPlan = useCallback(async () => {
    setPlanLoading(true)
    try {
      const res = await secureFetch('/therapy/safety-plan')
      if (!res.ok) throw new Error('load failed')
      const data = await res.json()
      const p: PlanState = {}
      const sp = data.safety_plan || {}
      for (const f of PLAN_FIELDS) p[f.key] = ((sp[f.key] as string[]) || []).join('\n')
      setPlan(p)
      setPlanExists(!!data.exists)
      setPlanUpdated(data.updated_at || null)
    } catch { /* keep empty form */ } finally { setPlanLoading(false) }
  }, [])

  const savePlan = async () => {
    setSaving(true)
    try {
      const body: Record<string, string[]> = {}
      for (const f of PLAN_FIELDS) {
        body[f.key] = (plan[f.key] || '').split('\n').map(s => s.trim()).filter(Boolean)
      }
      const res = await secureFetch('/therapy/safety-plan', { method: 'PUT', body: JSON.stringify(body) })
      if (!res.ok) throw new Error('save failed')
      flash('Safety plan saved securely.'); setPlanExists(true); loadPlan()
    } catch { flash('Could not save right now. Please try again.') } finally { setSaving(false) }
  }

  const deletePlan = async () => {
    if (!confirm('Delete your safety plan? This cannot be undone.')) return
    try {
      const res = await secureFetch('/therapy/safety-plan', { method: 'DELETE' })
      if (!res.ok) throw new Error('delete failed')
      const cleared: PlanState = {}; for (const f of PLAN_FIELDS) cleared[f.key] = ''
      setPlan(cleared); setPlanExists(false); setPlanUpdated(null); flash('Safety plan deleted.')
    } catch { flash('Could not delete right now.') }
  }

  const loadCheckins = useCallback(async () => {
    try {
      const res = await secureFetch('/therapy/mood-checkins?limit=14')
      if (res.ok) setCheckins((await res.json()).checkins || [])
    } catch { /* ignore */ }
  }, [])

  const submitCheckin = async () => {
    try {
      const payload: Record<string, unknown> = { note: checkinNote || null }
      for (const k of Object.keys(checkin)) payload[k] = checkin[k] === '' ? null : checkin[k]
      const res = await secureFetch('/therapy/mood-checkin', { method: 'POST', body: JSON.stringify(payload) })
      if (!res.ok) throw new Error('failed')
      setCheckin({ mood: '', stress: '', sleep: '', safety: '', support_connection: '' }); setCheckinNote('')
      flash('Check-in saved. This is just for your own reflection.'); loadCheckins()
    } catch { flash('Could not save your check-in right now.') }
  }

  const loadJournal = useCallback(async () => {
    try {
      const res = await secureFetch('/therapy/journal?limit=30')
      if (res.ok) setEntries((await res.json()).entries || [])
    } catch { /* ignore */ }
  }, [])

  const submitJournal = async () => {
    if (!jNotes.trim()) { flash('Write a few words first.'); return }
    try {
      const body = { mood: jMood || null, tags: jTags.split(',').map(s => s.trim()).filter(Boolean), notes: jNotes }
      const res = await secureFetch('/therapy/journal', { method: 'POST', body: JSON.stringify(body) })
      if (!res.ok) throw new Error('failed')
      setJMood(''); setJTags(''); setJNotes(''); flash('Journal entry saved (encrypted).'); loadJournal()
    } catch { flash('Could not save your entry right now.') }
  }

  const deleteEntry = async (id: string) => {
    try {
      const res = await secureFetch(`/therapy/journal/${id}`, { method: 'DELETE' })
      if (res.ok) { setEntries(prev => prev.filter(e => e.entry_id !== id)); flash('Entry deleted.') }
    } catch { flash('Could not delete right now.') }
  }

  const loadPrivacy = useCallback(async () => {
    try {
      const res = await secureFetch('/therapy/privacy')
      if (res.ok) setPrivacy(await res.json())
    } catch { /* ignore */ }
  }, [])

  const deleteAll = async () => {
    if (!confirm('Delete ALL your mental-health data (conversations, safety plan, journal, check-ins)? This cannot be undone.')) return
    try {
      const res = await secureFetch('/therapy/mental-health-data', { method: 'DELETE' })
      if (!res.ok) throw new Error('failed')
      flash('All your mental-health data has been deleted.')
      setPrivacy(null); loadPrivacy(); loadPlan(); loadCheckins(); loadJournal()
    } catch { flash('Could not delete right now.') }
  }

  useEffect(() => {
    if (!isSignedIn) return
    if (tab === 'plan') loadPlan()
    else if (tab === 'checkin') loadCheckins()
    else if (tab === 'journal') loadJournal()
    else if (tab === 'privacy') loadPrivacy()
  }, [tab, isSignedIn, loadPlan, loadCheckins, loadJournal, loadPrivacy])

  if (isLoaded && !isSignedIn) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(150deg,#fdf2f8,#f5f0ff)', padding: 24 }}>
        <div style={{ background: 'white', borderRadius: 18, padding: 28, maxWidth: 360, textAlign: 'center', boxShadow: '0 10px 40px rgba(190,24,93,0.12)' }}>
          <Lock size={26} style={{ color: '#be185d', marginBottom: 10 }} />
          <h2 style={{ margin: '0 0 8px', fontFamily: 'Georgia', color: '#be185d', fontSize: '1.1rem' }}>Please sign in</h2>
          <p style={{ fontSize: '0.85rem', color: '#6b5563', lineHeight: 1.5, margin: '0 0 16px' }}>Your safety plan and journal are private and encrypted, so they&apos;re tied to your account.</p>
          <Link href="/sign-in" style={{ display: 'inline-block', background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', textDecoration: 'none', borderRadius: 50, padding: '10px 24px', fontWeight: 700, fontSize: '0.85rem' }}>Sign in</Link>
        </div>
      </div>
    )
  }

  // ── Body ──
  const TABS: { key: Tab; label: string; Icon: any }[] = [
    { key: 'plan', label: 'Safety plan', Icon: Shield },
    { key: 'checkin', label: 'Check-in', Icon: HeartPulse },
    { key: 'journal', label: 'Journal', Icon: BookOpen },
    { key: 'privacy', label: 'Privacy', Icon: Lock },
  ]

  return (
    <div style={{ minHeight: '100dvh', background: 'linear-gradient(150deg,#fdf2f8 0%,#f5f0ff 50%,#fce7f3 100%)', paddingBottom: 40 }}>
      {/* Header */}
      <div style={{ background: 'rgba(253,242,248,0.96)', backdropFilter: 'blur(16px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '12px clamp(12px,4vw,24px)', display: 'flex', alignItems: 'center', gap: 10, position: 'sticky', top: 0, zIndex: 10 }}>
        <Link href="/therapy" aria-label="Back to Aria" style={{ color: '#be185d', display: 'flex' }}><ArrowLeft size={18} /></Link>
        <div>
          <div style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: '0.95rem' }}>Your safety &amp; privacy</div>
          <div style={{ fontSize: '0.6rem', color: '#8b6b7d' }}>Private · Encrypted · Only you can see this</div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 6, padding: '12px clamp(12px,4vw,24px) 0', maxWidth: 720, margin: '0 auto', flexWrap: 'wrap' }}>
        {TABS.map(({ key, label, Icon }) => (
          <button key={key} onClick={() => setTab(key)} aria-current={tab === key}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: tab === key ? 'linear-gradient(135deg,#be185d,#9d174d)' : 'white', color: tab === key ? 'white' : '#be185d', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '8px 13px', cursor: 'pointer', fontWeight: 700, fontSize: '0.78rem' }}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {msg && (
        <div role="status" style={{ maxWidth: 720, margin: '12px auto 0', padding: '0 clamp(12px,4vw,24px)' }}>
          <div style={{ background: 'rgba(22,163,74,0.1)', border: '1px solid rgba(22,163,74,0.3)', color: '#15803d', borderRadius: 10, padding: '10px 14px', fontSize: '0.8rem', fontWeight: 600 }}>{msg}</div>
        </div>
      )}

      <div style={{ maxWidth: 720, margin: '0 auto', padding: 'clamp(14px,4vw,20px)' }}>
        {tab === 'plan' && (
          <div>
            <div style={{ background: 'white', borderRadius: 14, padding: 16, border: '1px solid rgba(190,24,93,0.12)', marginBottom: 14 }}>
              <p style={{ margin: 0, fontSize: '0.82rem', color: '#6b5563', lineHeight: 1.6 }}>
                A safety plan is a short note-to-self for hard moments — in your own words. It is not a medical document. Write one line per item. Everything is stored encrypted and only you can read it.
              </p>
              {planUpdated && <p style={{ margin: '8px 0 0', fontSize: '0.68rem', color: '#8b6b7d' }}>Last saved: {new Date(planUpdated).toLocaleString()}</p>}
            </div>

            {PLAN_FIELDS.map(f => (
              <div key={f.key} style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontWeight: 700, color: '#be185d', fontSize: '0.82rem', marginBottom: 2 }}>{f.label}</label>
                <div style={{ fontSize: '0.68rem', color: '#8b6b7d', marginBottom: 6 }}>{f.hint}</div>
                <textarea
                  value={plan[f.key] || ''}
                  onChange={e => setPlan(prev => ({ ...prev, [f.key]: e.target.value }))}
                  placeholder="One item per line…"
                  rows={3}
                  style={{ width: '100%', boxSizing: 'border-box', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '10px 12px', fontSize: '0.85rem', fontFamily: 'inherit', color: '#1a0a12', resize: 'vertical', outline: 'none' }}
                />
              </div>
            ))}

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
              <button onClick={savePlan} disabled={saving || planLoading}
                style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '11px 20px', fontWeight: 700, cursor: saving ? 'wait' : 'pointer', fontSize: '0.85rem' }}>
                <Save size={15} /> {saving ? 'Saving…' : 'Save safely'}
              </button>
              {planExists && (
                <button onClick={deletePlan}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'white', color: '#b91c1c', border: '1px solid rgba(220,38,38,0.3)', borderRadius: 10, padding: '11px 18px', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem' }}>
                  <Trash2 size={15} /> Delete plan
                </button>
              )}
            </div>
          </div>
        )}
        {tab === 'checkin' && (
          <div>
            <div style={{ background: 'white', borderRadius: 14, padding: 16, border: '1px solid rgba(190,24,93,0.12)', marginBottom: 14 }}>
              <p style={{ margin: 0, fontSize: '0.82rem', color: '#6b5563', lineHeight: 1.6 }}>
                A quick check-in to notice how you&apos;re doing. This is <strong>not</strong> a diagnosis or a score anyone judges — it just helps you see your own patterns. 1 = low, 5 = high.
              </p>
            </div>

            {([
              ['mood', 'Mood'], ['stress', 'Stress'], ['sleep', 'Sleep quality'],
              ['safety', 'Feeling safe'], ['support_connection', 'Feeling connected'],
            ] as [string, string][]).map(([key, label]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.82rem', color: '#4b3540', fontWeight: 600, minWidth: 130 }}>{label}</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  {[1, 2, 3, 4, 5].map(n => (
                    <button key={n} onClick={() => setCheckin(prev => ({ ...prev, [key]: prev[key] === n ? '' : n }))}
                      aria-label={`${label} ${n}`} aria-pressed={checkin[key] === n}
                      style={{ width: 40, height: 40, borderRadius: 10, border: '1px solid rgba(190,24,93,0.25)', cursor: 'pointer', fontWeight: 700, background: checkin[key] === n ? 'linear-gradient(135deg,#be185d,#9d174d)' : 'white', color: checkin[key] === n ? 'white' : '#be185d' }}>
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <textarea value={checkinNote} onChange={e => setCheckinNote(e.target.value)} rows={2} maxLength={500}
              placeholder="Anything you want to note (optional, encrypted)…"
              style={{ width: '100%', boxSizing: 'border-box', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '10px 12px', fontSize: '0.85rem', fontFamily: 'inherit', marginTop: 6, resize: 'vertical', outline: 'none' }} />

            <button onClick={submitCheckin} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '11px 20px', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem', marginTop: 12 }}>
              <Plus size={15} /> Save check-in
            </button>

            {checkins.length > 0 && (
              <div style={{ marginTop: 22 }}>
                <div style={{ fontWeight: 700, color: '#be185d', fontSize: '0.8rem', marginBottom: 8 }}>Recent check-ins</div>
                <div style={{ display: 'grid', gap: 8 }}>
                  {checkins.map((c, i) => (
                    <div key={c.checkin_id || i} style={{ background: 'white', border: '1px solid rgba(190,24,93,0.12)', borderRadius: 10, padding: '10px 12px' }}>
                      <div style={{ fontSize: '0.66rem', color: '#8b6b7d', marginBottom: 4 }}>{c.created_at ? new Date(c.created_at).toLocaleString() : ''}</div>
                      <div style={{ fontSize: '0.78rem', color: '#4b3540' }}>
                        {['mood', 'stress', 'sleep', 'safety', 'support_connection'].filter(k => c[k]).map(k => `${k.replace('support_connection', 'connected')}: ${c[k]}`).join(' · ') || 'No ratings'}
                      </div>
                      {c.note && <div style={{ fontSize: '0.76rem', color: '#6b5563', marginTop: 4, fontStyle: 'italic' }}>{c.note}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {tab === 'journal' && (
          <div>
            <div style={{ background: 'white', borderRadius: 14, padding: 16, border: '1px solid rgba(190,24,93,0.12)', marginBottom: 14 }}>
              <p style={{ margin: 0, fontSize: '0.82rem', color: '#6b5563', lineHeight: 1.6 }}>
                A private space to write. Entries are encrypted and only you can read or delete them. HAVEN never sends journal entries to any AI.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <input value={jMood} onChange={e => setJMood(e.target.value)} maxLength={60} placeholder="Mood (optional)"
                style={{ flex: 1, minWidth: 140, boxSizing: 'border-box', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '10px 12px', fontSize: '0.85rem', outline: 'none' }} />
              <input value={jTags} onChange={e => setJTags(e.target.value)} placeholder="Tags, comma-separated (optional)"
                style={{ flex: 1, minWidth: 140, boxSizing: 'border-box', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '10px 12px', fontSize: '0.85rem', outline: 'none' }} />
            </div>
            <textarea value={jNotes} onChange={e => setJNotes(e.target.value)} rows={5} maxLength={5000}
              placeholder="Write whatever is on your mind…"
              style={{ width: '100%', boxSizing: 'border-box', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 10, padding: '10px 12px', fontSize: '0.85rem', fontFamily: 'inherit', resize: 'vertical', outline: 'none' }} />
            <button onClick={submitJournal} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', border: 'none', borderRadius: 10, padding: '11px 20px', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem', marginTop: 10 }}>
              <Save size={15} /> Save entry
            </button>

            {entries.length > 0 && (
              <div style={{ marginTop: 22, display: 'grid', gap: 8 }}>
                {entries.map((e, i) => (
                  <div key={e.entry_id || i} style={{ background: 'white', border: '1px solid rgba(190,24,93,0.12)', borderRadius: 10, padding: '12px 14px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <div style={{ fontSize: '0.66rem', color: '#8b6b7d' }}>{e.created_at ? new Date(e.created_at).toLocaleString() : ''}{e.mood ? ` · ${e.mood}` : ''}</div>
                      <button onClick={() => deleteEntry(e.entry_id)} aria-label="Delete entry" style={{ background: 'none', border: 'none', color: '#b91c1c', cursor: 'pointer', display: 'flex', padding: 2 }}><Trash2 size={14} /></button>
                    </div>
                    {e.tags?.length > 0 && <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', margin: '6px 0' }}>{e.tags.map((t: string, j: number) => <span key={j} style={{ fontSize: '0.62rem', background: '#fce7f3', color: '#be185d', borderRadius: 20, padding: '2px 8px' }}>{t}</span>)}</div>}
                    <div style={{ fontSize: '0.82rem', color: '#4b3540', lineHeight: 1.6, whiteSpace: 'pre-wrap', marginTop: 4 }}>{e.notes}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === 'privacy' && (
          <div>
            <div style={{ background: 'white', borderRadius: 14, padding: 16, border: '1px solid rgba(190,24,93,0.12)', marginBottom: 14 }}>
              <p style={{ margin: 0, fontSize: '0.82rem', color: '#6b5563', lineHeight: 1.6 }}>
                Here is exactly what HAVEN keeps for you, why, and how to remove it. You are in control.
              </p>
            </div>

            {privacy?.stored && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 8, marginBottom: 14 }}>
                {Object.entries(privacy.stored).map(([k, v]) => (
                  <div key={k} style={{ background: 'white', border: '1px solid rgba(190,24,93,0.12)', borderRadius: 10, padding: '12px', textAlign: 'center' }}>
                    <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#be185d' }}>{String(v)}</div>
                    <div style={{ fontSize: '0.66rem', color: '#8b6b7d', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
                  </div>
                ))}
              </div>
            )}

            {privacy?.details?.length > 0 && (
              <div style={{ display: 'grid', gap: 8 }}>
                {privacy.details.map((d: any, i: number) => (
                  <div key={i} style={{ background: 'white', border: '1px solid rgba(190,24,93,0.12)', borderRadius: 10, padding: '12px 14px' }}>
                    <div style={{ fontWeight: 700, color: '#be185d', fontSize: '0.82rem' }}>{d.item}</div>
                    <p style={{ margin: '4px 0 0', fontSize: '0.74rem', color: '#6b5563', lineHeight: 1.5 }}><strong>Why:</strong> {d.why}</p>
                    <p style={{ margin: '2px 0 0', fontSize: '0.74rem', color: '#6b5563', lineHeight: 1.5 }}><strong>Kept:</strong> {d.retention}</p>
                    <p style={{ margin: '2px 0 0', fontSize: '0.74rem', color: '#6b5563', lineHeight: 1.5 }}><strong>Who can see it:</strong> {d.access}</p>
                    <p style={{ margin: '2px 0 0', fontSize: '0.74rem', color: '#6b5563', lineHeight: 1.5 }}><strong>Sent to AI:</strong> {d.ai_provider_receives}</p>
                  </div>
                ))}
              </div>
            )}

            <div style={{ marginTop: 18, background: 'rgba(220,38,38,0.05)', border: '1px solid rgba(220,38,38,0.2)', borderRadius: 12, padding: 16 }}>
              <div style={{ fontWeight: 700, color: '#b91c1c', fontSize: '0.85rem', marginBottom: 4 }}>Delete everything</div>
              <p style={{ margin: '0 0 12px', fontSize: '0.76rem', color: '#6b5563', lineHeight: 1.5 }}>Permanently remove all your conversations, safety plan, journal entries and check-ins. This cannot be undone.</p>
              <button onClick={deleteAll} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg,#dc2626,#b91c1c)', color: 'white', border: 'none', borderRadius: 10, padding: '11px 18px', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem' }}>
                <Trash2 size={15} /> Delete all my data
              </button>
            </div>

            {privacy?.disclaimer && <p style={{ margin: '14px 0 0', fontSize: '0.68rem', color: '#8b6b7d', lineHeight: 1.5 }}>{privacy.disclaimer}</p>}
          </div>
        )}
      </div>
    </div>
  )
}
