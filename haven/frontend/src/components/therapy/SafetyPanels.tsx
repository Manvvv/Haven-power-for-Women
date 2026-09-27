'use client'
/**
 * SafetyPanels.tsx — user-facing safety UI for HAVEN's mental-health module.
 *
 * Three overlays map to the three primary actions (spec §33): Talk (the chat),
 * Calm Down (CalmDownPanel) and Get Help (GetHelpPanel). CrisisPanel is shown
 * automatically when a turn is triaged as a crisis (spec §5) — simplified,
 * emergency-first, large tap targets.
 *
 * SAFETY INVARIANTS (spec §3, §6, §11, §13):
 *  - Nothing here contacts anyone automatically. Calls are `tel:` links the user
 *    chooses to tap; HAVEN SOS / trusted-contact are links the user activates.
 *  - Numbers render from the backend registry (passed in as props); the offline
 *    constants are the only fallback and live in one module (support.ts).
 *  - No diagnosis, no medication doses, no false "you are safe" reassurance.
 */
import { useEffect, type ReactNode } from 'react'
import Link from 'next/link'
import { Phone, X, Wind, Shield, Users, ExternalLink, LifeBuoy, Heart } from 'lucide-react'
import {
  Resource, CopingTool, telHref, displayNumber, authorityLabel,
  OFFLINE_EMERGENCY, OFFLINE_GROUNDING, OFFLINE_BREATHING, DISCLAIMER,
} from './support'

// Shared modal shell: fixed overlay, Escape-to-close, focus-friendly.
function Overlay({ onClose, children, dark, label }: {
  onClose: () => void; children: ReactNode; dark?: boolean; label: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div
      role="dialog" aria-modal="true" aria-label={label}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 300,
        background: dark ? 'rgba(20,6,12,0.72)' : 'rgba(26,10,18,0.5)',
        backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center',
        justifyContent: 'center', padding: 'clamp(12px,3vw,24px)',
        animation: 'fadeIn 0.25s ease',
      }}
    >
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: 560, maxHeight: '92dvh', overflowY: 'auto' }}>
        {children}
      </div>
    </div>
  )
}

// A large, explicit call button. Placing the call is always the user's choice.
function CallButton({ label, number, tone = 'primary' }: {
  label: string; number: string; tone?: 'emergency' | 'primary'
}) {
  const bg = tone === 'emergency'
    ? 'linear-gradient(135deg,#dc2626,#b91c1c)'
    : 'linear-gradient(135deg,#be185d,#9d174d)'
  return (
    <a
      href={telHref(number)} aria-label={`${label}. Call ${number}`}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none',
        background: bg, color: 'white', borderRadius: 14, padding: '16px 18px',
        minHeight: 56, boxShadow: '0 6px 20px rgba(190,24,93,0.25)', fontWeight: 700,
      }}
    >
      <span style={{ width: 40, height: 40, borderRadius: '50%', background: 'rgba(255,255,255,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <Phone size={20} />
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.25 }}>
        <span style={{ fontSize: '1.02rem' }}>{label}</span>
        <span style={{ fontSize: '0.82rem', opacity: 0.9, fontWeight: 600 }}>Tap to call {number}</span>
      </span>
    </a>
  )
}

// Verified-resource card: name, gov/NGO provenance, purpose, call + official link.
function ResourceCard({ r }: { r: Resource }) {
  const num = displayNumber(r)
  const badge = authorityLabel(r.authority_level)
  const url = r.source_url || r.official_url
  const name = r.name || r.provider_name || 'Resource'
  return (
    <div style={{ background: 'white', border: '1px solid rgba(190,24,93,0.14)', borderRadius: 14, padding: 14, boxShadow: '0 2px 10px rgba(190,24,93,0.06)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <span style={{ fontWeight: 700, color: '#1a0a12', fontSize: '0.92rem', lineHeight: 1.3 }}>{name}</span>
        {badge.text && (
          <span style={{ flexShrink: 0, fontSize: '0.6rem', fontWeight: 700, padding: '3px 8px', borderRadius: 20, whiteSpace: 'nowrap', background: badge.gov ? 'rgba(22,163,74,0.12)' : 'rgba(217,119,6,0.12)', color: badge.gov ? '#15803d' : '#b45309', border: `1px solid ${badge.gov ? 'rgba(22,163,74,0.3)' : 'rgba(217,119,6,0.3)'}` }}>
            {badge.text}
          </span>
        )}
      </div>
      {r.purpose && <p style={{ margin: '6px 0 0', fontSize: '0.78rem', color: '#6b5563', lineHeight: 1.5 }}>{r.purpose}</p>}
      {r.availability && <p style={{ margin: '4px 0 0', fontSize: '0.68rem', color: '#8b6b7d' }}>Available: {r.availability}</p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10, alignItems: 'center' }}>
        {num && (
          <a href={telHref(num)} aria-label={`Call ${name} at ${num}`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', textDecoration: 'none', borderRadius: 10, padding: '9px 14px', fontWeight: 700, fontSize: '0.82rem', minHeight: 40 }}>
            <Phone size={14} /> Call {num}
          </a>
        )}
        {r.alt_number && (
          <a href={telHref(r.alt_number)} style={{ fontSize: '0.74rem', color: '#be185d', fontWeight: 600, textDecoration: 'none' }}>
            or {r.alt_number}
          </a>
        )}
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open official source for ${name} in a new tab`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.72rem', color: '#6b5563', textDecoration: 'none', marginLeft: 'auto' }}>
            Official source <ExternalLink size={11} />
          </a>
        )}
      </div>
    </div>
  )
}

// Consent note reused wherever we offer to reach a person (spec §11, §13).
function ConsentNote({ children }: { children: ReactNode }) {
  return (
    <p style={{ display: 'flex', gap: 6, alignItems: 'flex-start', margin: '4px 0 0', fontSize: '0.7rem', color: '#8b6b7d', lineHeight: 1.5 }}>
      <Shield size={12} style={{ flexShrink: 0, marginTop: 2 }} />
      <span>{children}</span>
    </p>
  )
}

// ── Crisis mode: simplified, emergency-first (spec §5, §33) ──
export function CrisisPanel({ open, onClose, resources, safetyPlan, disclaimer, onCalmDown }: {
  open: boolean; onClose: () => void; resources?: Resource[]
  safetyPlan?: Record<string, unknown> | null; disclaimer?: string | null; onCalmDown: () => void
}) {
  if (!open) return null
  const list = (resources && resources.length ? resources : OFFLINE_EMERGENCY)
  const em112 = list.find(r => displayNumber(r) === '112') || OFFLINE_EMERGENCY[0]
  const teleManas = list.find(r => displayNumber(r) === '14416') || OFFLINE_EMERGENCY[1]
  const others = list.filter(r => displayNumber(r) !== '112' && displayNumber(r) !== '14416')
  const plan = safetyPlan as Record<string, string[]> | null | undefined
  const planPeople = plan?.people_to_contact?.filter(Boolean) || []
  const planHelps = plan?.things_that_help?.filter(Boolean) || []
  const planPlaces = plan?.safe_places?.filter(Boolean) || []

  return (
    <Overlay onClose={onClose} dark label="Crisis support">
      <div style={{ background: 'linear-gradient(160deg,#fff5f7 0%,#fef2f2 100%)', borderRadius: 22, padding: 'clamp(18px,4vw,26px)', border: '1px solid rgba(220,38,38,0.18)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <Heart size={22} style={{ color: '#dc2626' }} />
          <h2 style={{ margin: 0, fontSize: 'clamp(1.1rem,4vw,1.35rem)', color: '#1a0a12', fontFamily: 'Georgia' }}>You're not alone right now</h2>
        </div>
        <p style={{ margin: '0 0 16px', fontSize: '0.9rem', color: '#6b5563', lineHeight: 1.6 }}>
          If you might act on thoughts of harming yourself, please reach a person who can help. You can talk to someone free, 24/7.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <CallButton label="Call emergency services" number={displayNumber(em112) || '112'} tone="emergency" />
          <CallButton label="Talk to Tele-MANAS counsellor" number={displayNumber(teleManas) || '14416'} tone="primary" />
        </div>

        {/* HAVEN handoff — the user chooses; HAVEN never contacts anyone on its own. */}
        <div style={{ marginTop: 16, display: 'grid', gap: 8 }}>
          <Link href="/sos" aria-label="Open HAVEN SOS" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', background: 'white', border: '1px solid rgba(220,38,38,0.25)', borderRadius: 12, padding: '13px 16px', color: '#b91c1c', fontWeight: 700, minHeight: 48 }}>
            <LifeBuoy size={18} /> Activate HAVEN SOS
          </Link>
          <Link href="/sos" aria-label="Reach a trusted contact" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', background: 'white', border: '1px solid rgba(190,24,93,0.22)', borderRadius: 12, padding: '13px 16px', color: '#be185d', fontWeight: 700, minHeight: 48 }}>
            <Users size={18} /> Reach a trusted contact
          </Link>
          <ConsentNote>HAVEN will not call, message, or alert anyone automatically. You choose if and when to reach out.</ConsentNote>
        </div>

        {(planPeople.length || planHelps.length || planPlaces.length) ? (
          <div style={{ marginTop: 16, background: 'rgba(190,24,93,0.05)', border: '1px solid rgba(190,24,93,0.14)', borderRadius: 14, padding: 14 }}>
            <div style={{ fontWeight: 700, color: '#be185d', fontSize: '0.82rem', marginBottom: 6 }}>From your safety plan</div>
            {planPeople.length > 0 && <p style={{ margin: '2px 0', fontSize: '0.8rem', color: '#4b3540' }}><strong>People:</strong> {planPeople.join(', ')}</p>}
            {planHelps.length > 0 && <p style={{ margin: '2px 0', fontSize: '0.8rem', color: '#4b3540' }}><strong>What helps you:</strong> {planHelps.join(', ')}</p>}
            {planPlaces.length > 0 && <p style={{ margin: '2px 0', fontSize: '0.8rem', color: '#4b3540' }}><strong>Safe places:</strong> {planPlaces.join(', ')}</p>}
          </div>
        ) : null}

        {others.length > 0 && (
          <div style={{ marginTop: 16, display: 'grid', gap: 8 }}>
            {others.map((r, i) => <ResourceCard key={r.id || i} r={r} />)}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 18, flexWrap: 'wrap' }}>
          <button onClick={onCalmDown} style={{ flex: 1, minWidth: 140, background: 'white', border: '1px solid rgba(168,85,247,0.3)', color: '#7c3aed', borderRadius: 12, padding: '12px', fontWeight: 700, cursor: 'pointer', minHeight: 46 }}>
            <Wind size={15} style={{ verticalAlign: -2, marginRight: 6 }} />Try a grounding exercise
          </button>
          <button onClick={onClose} style={{ flex: 1, minWidth: 140, background: 'rgba(26,10,18,0.06)', border: '1px solid rgba(26,10,18,0.12)', color: '#4b3540', borderRadius: 12, padding: '12px', fontWeight: 700, cursor: 'pointer', minHeight: 46 }}>
            Continue talking with Aria
          </button>
        </div>

        <p style={{ margin: '14px 0 0', fontSize: '0.68rem', color: '#8b6b7d', lineHeight: 1.5 }}>{disclaimer || DISCLAIMER}</p>
      </div>
    </Overlay>
  )
}

// ── Calm Down: grounding + breathing; works with no network (spec §8, §29) ──
export function CalmDownPanel({ open, onClose, tools, onGetHelp }: {
  open: boolean; onClose: () => void; tools?: CopingTool[]; onGetHelp: () => void
}) {
  if (!open) return null
  const list: CopingTool[] = (tools && tools.length) ? tools : [
    { id: 'grounding_54321', title: OFFLINE_GROUNDING.title, steps: OFFLINE_GROUNDING.steps },
    { id: 'breathing', title: OFFLINE_BREATHING.title, steps: OFFLINE_BREATHING.steps },
  ]
  return (
    <Overlay onClose={onClose} label="Calming exercises">
      <style>{`@keyframes havenBreathe{0%,100%{transform:scale(0.72);opacity:0.7}50%{transform:scale(1.05);opacity:1}}`}</style>
      <div style={{ background: 'linear-gradient(160deg,#f5f0ff 0%,#fdf2f8 100%)', borderRadius: 22, padding: 'clamp(18px,4vw,26px)', border: '1px solid rgba(168,85,247,0.18)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Wind size={20} style={{ color: '#7c3aed' }} />
            <h2 style={{ margin: 0, fontSize: 'clamp(1.05rem,4vw,1.25rem)', color: '#1a0a12', fontFamily: 'Georgia' }}>Let's slow things down</h2>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#8b6b7d', padding: 4 }}><X size={20} /></button>
        </div>

        {/* Breathing pacer — a gentle visual to follow */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '10px 0 16px' }}>
          <div style={{ width: 120, height: 120, borderRadius: '50%', background: 'radial-gradient(circle,#c4b5fd,#a855f7)', animation: 'havenBreathe 14s ease-in-out infinite', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 700, fontSize: '0.8rem' }}>
            breathe
          </div>
          <p style={{ margin: 0, fontSize: '0.78rem', color: '#6b5563' }}>In for 4 · hold for 4 · out for 6</p>
        </div>

        <div style={{ display: 'grid', gap: 10 }}>
          {list.map((tool, i) => (
            <div key={tool.id || i} style={{ background: 'white', border: '1px solid rgba(168,85,247,0.16)', borderRadius: 14, padding: 14 }}>
              <div style={{ fontWeight: 700, color: '#7c3aed', fontSize: '0.88rem', marginBottom: 6 }}>{tool.title}</div>
              <ol style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>
                {tool.steps.map((s, j) => <li key={j} style={{ fontSize: '0.8rem', color: '#4b3540', lineHeight: 1.5 }}>{s}</li>)}
              </ol>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
          <button onClick={onClose} style={{ flex: 1, minWidth: 140, background: 'linear-gradient(135deg,#a855f7,#7c3aed)', border: 'none', color: 'white', borderRadius: 12, padding: '12px', fontWeight: 700, cursor: 'pointer', minHeight: 46 }}>I feel a little calmer</button>
          <button onClick={onGetHelp} style={{ flex: 1, minWidth: 140, background: 'white', border: '1px solid rgba(190,24,93,0.25)', color: '#be185d', borderRadius: 12, padding: '12px', fontWeight: 700, cursor: 'pointer', minHeight: 46 }}>I'd like more help</button>
        </div>
        <p style={{ margin: '12px 0 0', fontSize: '0.68rem', color: '#8b6b7d', lineHeight: 1.5 }}>These are self-help strategies, not medical treatment. If things feel unsafe, tap “I'd like more help”.</p>
      </div>
    </Overlay>
  )
}

// ── Get Help: verified resources + human/professional escalation (spec §6, §23) ──
export function GetHelpPanel({ open, onClose, emergency, professional, disclaimer, offline }: {
  open: boolean; onClose: () => void; emergency?: Resource[]
  professional?: Resource[]; disclaimer?: string | null; offline?: boolean
}) {
  if (!open) return null
  const em = (emergency && emergency.length) ? emergency : OFFLINE_EMERGENCY
  return (
    <Overlay onClose={onClose} label="Get help">
      <div style={{ background: 'linear-gradient(160deg,#fdf2f8 0%,#f5f0ff 100%)', borderRadius: 22, padding: 'clamp(18px,4vw,26px)', border: '1px solid rgba(190,24,93,0.16)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <LifeBuoy size={20} style={{ color: '#be185d' }} />
            <h2 style={{ margin: 0, fontSize: 'clamp(1.05rem,4vw,1.25rem)', color: '#1a0a12', fontFamily: 'Georgia' }}>Getting help</h2>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#8b6b7d', padding: 4 }}><X size={20} /></button>
        </div>

        {offline && (
          <p style={{ margin: '0 0 12px', fontSize: '0.72rem', color: '#b45309', background: 'rgba(217,119,6,0.1)', border: '1px solid rgba(217,119,6,0.25)', borderRadius: 10, padding: '8px 10px' }}>
            You appear to be offline. These are HAVEN's saved verified numbers — please confirm them when you're back online.
          </p>
        )}

        <div style={{ fontWeight: 700, color: '#be185d', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: 0.4, margin: '0 0 8px' }}>Talk to someone now</div>
        <div style={{ display: 'grid', gap: 8 }}>
          {em.map((r, i) => <ResourceCard key={r.id || i} r={r} />)}
        </div>

        {professional && professional.length > 0 && (
          <>
            <div style={{ fontWeight: 700, color: '#be185d', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: 0.4, margin: '16px 0 8px' }}>Talk to a professional</div>
            <div style={{ display: 'grid', gap: 8 }}>
              {professional.map((r, i) => <ResourceCard key={r.official_url || i} r={r} />)}
            </div>
          </>
        )}

        <div style={{ marginTop: 16, display: 'grid', gap: 8 }}>
          <Link href="/sos" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', background: 'white', border: '1px solid rgba(220,38,38,0.22)', borderRadius: 12, padding: '13px 16px', color: '#b91c1c', fontWeight: 700, minHeight: 48 }}>
            <LifeBuoy size={18} /> Open HAVEN SOS
          </Link>
          <Link href="/therapy/safety-plan" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', background: 'white', border: '1px solid rgba(190,24,93,0.22)', borderRadius: 12, padding: '13px 16px', color: '#be185d', fontWeight: 700, minHeight: 48 }}>
            <Shield size={18} /> My safety plan &amp; privacy
          </Link>
          <ConsentNote>Reaching out is always your choice — HAVEN never contacts anyone for you without you starting it.</ConsentNote>
        </div>

        <p style={{ margin: '14px 0 0', fontSize: '0.68rem', color: '#8b6b7d', lineHeight: 1.5 }}>{disclaimer || DISCLAIMER}</p>
      </div>
    </Overlay>
  )
}
