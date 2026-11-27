'use client'
import { useRouter } from 'next/navigation'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { UserButton, useUser } from '@clerk/nextjs'
import {
  Shield, Heart, Scale, Eye, Phone, AlertTriangle, Mic, FileText,
  Users, Clock, Activity, PlayCircle,
} from 'lucide-react'
import PanicButton from '@/components/PanicButton'
import DirectSOSForm from '@/components/DirectSOSForm'
import IncidentTracker, { type UserIncident } from '@/components/IncidentTracker'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { resolveGreetingName } from '@/lib/greeting'
import { secureFetch } from '@/lib/api'

interface ActiveCheckinSummary {
  checkin_id: string
  status: string
  activity_label?: string
  remaining_seconds: number
  expires_at: string
}

export default function DashboardPage() {
  useHavenAuth()
  const router = useRouter()
  const [sosRefreshSignal, setSosRefreshSignal] = useState(0)
  const { t, lang } = useLang()
  const isHi = lang === 'hi'
  const { user, isLoaded } = useUser()
  // Derive the greeting name from the AUTHENTICATED identity only:
  //   proper display name (fullName) -> first name -> safe localized fallback.
  // Until Clerk has hydrated (isLoaded === false) `user` is null, so we show the
  // neutral fallback — never a stale/hardcoded or another user's name, and the
  // wrong name can never flash before the real identity resolves.
  const displayName = resolveGreetingName(user, isLoaded, t('friendFallback'))
  const navigate = (href: string) => router.push(href)

  // Real backend Safety Overview state (never fabricated)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState('')
  const [contactsCount, setContactsCount] = useState<number>(0)
  const [verifiedContactsCount, setVerifiedContactsCount] = useState<number>(0)
  const [activeCheckin, setActiveCheckin] = useState<ActiveCheckinSummary | null>(null)
  const [safetyPlanExists, setSafetyPlanExists] = useState<boolean | null>(null)
  const [incidents, setIncidents] = useState<UserIncident[]>([])

  const loadSafetyOverview = useCallback(async () => {
    if (!isLoaded || !user?.id) {
      if (isLoaded) setOverviewLoading(false)
      return
    }
    setOverviewLoading(true)
    setOverviewError('')
    try {
      const [cRes, chkRes, spRes] = await Promise.allSettled([
        secureFetch(`/trusted-contacts/${encodeURIComponent(user.id)}`),
        secureFetch('/check-in/active'),
        secureFetch('/therapy/safety-plan'),
      ])
      if (cRes.status === 'fulfilled' && cRes.value.ok) {
        const d = await cRes.value.json().catch(() => ({}))
        const list = Array.isArray(d.contacts) ? d.contacts : []
        setContactsCount(list.length)
        setVerifiedContactsCount(list.filter((c: any) => c.verification_status === 'VERIFIED').length)
      }
      if (chkRes.status === 'fulfilled' && chkRes.value.ok) {
        const d = await chkRes.value.json().catch(() => ({}))
        setActiveCheckin(d.checkin || null)
      }
      if (spRes.status === 'fulfilled' && spRes.value.ok) {
        const d = await spRes.value.json().catch(() => ({}))
        setSafetyPlanExists(!!d.exists)
      }
    } catch {
      setOverviewError(isHi ? 'सुरक्षा अवलोकन लोड नहीं हो सका।' : 'Could not refresh safety overview from backend.')
    } finally {
      setOverviewLoading(false)
    }
  }, [isLoaded, user?.id, isHi])

  useEffect(() => {
    loadSafetyOverview()
  }, [loadSafetyOverview])

  const activeIncidentsCount = incidents.filter((i) => i.status !== 'RESOLVED' && i.status !== 'CANCELLED').length
  const latestIncident = incidents[0] || null

  const quickActions = [
    {
      label: t('reportEmergency'),
      href: '#direct-sos-section',
      icon: <AlertTriangle size={16} />,
      bg: '#fee2e2',
      fg: '#b91c1c',
      onClick: () => document.getElementById('direct-sos-section')?.scrollIntoView({ behavior: 'smooth' }),
    },
    {
      label: t('voiceSosTitle'),
      href: '/voice-sos',
      icon: <Mic size={16} />,
      bg: '#f5f0ff',
      fg: '#6d28d9',
      onClick: () => navigate('/voice-sos'),
    },
    {
      label: t('manageContacts'),
      href: '/safe-contacts',
      icon: <Users size={16} />,
      bg: '#fce7f3',
      fg: '#be185d',
      onClick: () => navigate('/safe-contacts'),
    },
    {
      label: t('openSafetyPlan'),
      href: '/therapy/safety-plan',
      icon: <FileText size={16} />,
      bg: '#fff1f2',
      fg: '#9d174d',
      onClick: () => navigate('/therapy/safety-plan'),
    },
    {
      label: isHi ? 'चेक-इन टाइमर' : 'Check-In Timer',
      href: '/safe-contacts',
      icon: <Clock size={16} />,
      bg: '#ecfdf5',
      fg: '#047857',
      onClick: () => navigate('/safe-contacts'),
    },
    {
      label: t('demoModeBtn'),
      href: '/demo',
      icon: <PlayCircle size={16} />,
      bg: '#eff6ff',
      fg: '#1d4ed8',
      onClick: () => navigate('/demo'),
    },
  ]

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #fdf2f8 0%, #fce7f3 100%)' }}>
      {/* Header */}
      <header style={{ background: 'rgba(253,242,248,0.92)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0, zIndex: 30, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={22} style={{ color: '#be185d' }} />
          <span style={{ fontSize: 'clamp(1rem, 4vw, 1.25rem)', fontWeight: 700, color: '#be185d', fontFamily: 'Georgia' }}>{t('appName')}</span>
        </div>
        <nav aria-label="Dashboard navigation" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <LanguageSelector compact />
          <Link href="/demo" style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: '6px 12px', color: '#1d4ed8', fontSize: '0.78rem', fontWeight: 700, textDecoration: 'none' }}>
            {t('demoModeBtn')}
          </Link>
          <UserButton afterSignOutUrl="/home" />
          <button onClick={() => navigate('/')} style={{ background: 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '6px 14px', cursor: 'pointer', color: '#be185d', fontSize: '0.82rem', fontWeight: 600 }}>
            {t('home')}
          </button>
        </nav>
      </header>

      <main style={{ maxWidth: 940, margin: '0 auto', padding: 'clamp(20px,5vw,42px) 16px' }}>

        {/* Welcome */}
        <div style={{ marginBottom: 22 }}>
          <p style={{ fontSize: '0.85rem', color: '#8b6b7d', marginBottom: 4 }}>{t('welcomeBack')}</p>
          <h1 style={{ fontSize: 'clamp(1.5rem, 6vw, 2rem)', fontFamily: 'Georgia', color: '#1a0a12', marginBottom: 8 }}>
            {t('hello')}, {displayName} 🌸
          </h1>
          <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.85rem, 2.5vw, 0.95rem)', lineHeight: 1.65, maxWidth: 600 }}>
            {t('havenIsHere')}
          </p>
        </div>

        {/* Safety Overview (real backend state — zero fabricated stats) */}
        <section aria-labelledby="safety-overview-heading" style={{ background: 'white', borderRadius: 18, padding: 'clamp(16px,3.5vw,22px)', marginBottom: 22, border: '1px solid rgba(190,24,93,0.12)', boxShadow: '0 2px 14px rgba(190,24,93,0.06)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
            <h2 id="safety-overview-heading" style={{ fontFamily: 'Georgia', fontSize: 'clamp(1rem,3.5vw,1.2rem)', color: '#1a0a12', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Activity size={18} style={{ color: '#be185d' }} /> {t('safetyOverviewTitle')}
            </h2>
            {overviewLoading && <span style={{ fontSize: '0.74rem', color: '#8b6b7d' }}>Syncing…</span>}
          </div>

          {overviewError && (
            <div role="alert" style={{ marginBottom: 10, padding: '8px 12px', borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: '0.78rem' }}>
              {overviewError}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 10 }}>
            {/* Active incidents */}
            <div style={{ background: activeIncidentsCount > 0 ? '#fef2f2' : '#fdf2f8', borderRadius: 12, padding: 12, border: '1px solid rgba(190,24,93,0.12)' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#8b6b7d', textTransform: 'uppercase' }}>{t('activeIncidentTitle')}</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 800, color: activeIncidentsCount > 0 ? '#dc2626' : '#1a0a12', marginTop: 4 }}>
                {activeIncidentsCount > 0 ? `${activeIncidentsCount} Active` : t('noActiveIncidents')}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#6b5563', marginTop: 3 }}>
                {latestIncident ? `Latest: ${latestIncident.case_id} (${latestIncident.status})` : `${incidents.length} total recorded`}
              </div>
            </div>

            {/* Check-in status */}
            <div
              onClick={() => navigate('/safe-contacts')}
              style={{ background: activeCheckin ? '#f0fdf4' : '#fdf2f8', borderRadius: 12, padding: 12, border: '1px solid rgba(190,24,93,0.12)', cursor: 'pointer' }}
            >
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#8b6b7d', textTransform: 'uppercase' }}>
                {isHi ? 'सुरक्षा चेक-इन स्थिति' : 'Check-In Status'}
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 800, color: activeCheckin ? '#166534' : '#1a0a12', marginTop: 4 }}>
                {activeCheckin
                  ? `Active (${Math.max(1, Math.ceil((activeCheckin.remaining_seconds || 0) / 60))}m left)`
                  : (isHi ? 'कोई टाइमर सक्रिय नहीं' : 'No Active Timer')}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#be185d', fontWeight: 600, marginTop: 3 }}>
                {activeCheckin ? 'Manage / Confirm Safe →' : 'Start Safety Timer →'}
              </div>
            </div>

            {/* Trusted contacts summary */}
            <div
              onClick={() => navigate('/safe-contacts')}
              style={{ background: '#fdf2f8', borderRadius: 12, padding: 12, border: '1px solid rgba(190,24,93,0.12)', cursor: 'pointer' }}
            >
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#8b6b7d', textTransform: 'uppercase' }}>
                {isHi ? 'विश्वसनीय संपर्क' : 'Emergency Contacts'}
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#1a0a12', marginTop: 4 }}>
                {contactsCount} / 5 Saved
              </div>
              <div style={{ fontSize: '0.72rem', color: '#be185d', fontWeight: 600, marginTop: 3 }}>
                {verifiedContactsCount} verified · Manage →
              </div>
            </div>

            {/* Personal safety plan */}
            <div
              onClick={() => navigate('/therapy/safety-plan')}
              style={{ background: '#fdf2f8', borderRadius: 12, padding: 12, border: '1px solid rgba(190,24,93,0.12)', cursor: 'pointer' }}
            >
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#8b6b7d', textTransform: 'uppercase' }}>
                {t('safetyPlanTitle')}
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#1a0a12', marginTop: 4 }}>
                {safetyPlanExists === null ? '—' : safetyPlanExists ? (isHi ? 'सक्रिय व एन्क्रिप्टेड' : 'Saved (Encrypted)') : (isHi ? 'अभी तक नहीं बना' : 'Not Yet Created')}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#be185d', fontWeight: 600, marginTop: 3 }}>
                {t('openSafetyPlan')} →
              </div>
            </div>
          </div>

          {/* Quick Actions bar */}
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #f5e6ee' }}>
            <div style={{ fontSize: '0.74rem', fontWeight: 700, color: '#8b6b7d', marginBottom: 8, textTransform: 'uppercase' }}>
              {t('quickActionsTitle')}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
              {quickActions.map((qa) => (
                <button
                  key={qa.label}
                  type="button"
                  onClick={qa.onClick}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                    padding: '10px 10px', borderRadius: 10, border: '1px solid rgba(190,24,93,0.1)',
                    background: qa.bg, color: qa.fg, fontWeight: 700, fontSize: '0.78rem',
                    cursor: 'pointer', minHeight: 42,
                  }}
                >
                  {qa.icon}
                  <span>{qa.label}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* PANIC BUTTON */}
        <div style={{ background: 'linear-gradient(135deg, #1a0a12, #2d0f1f)', borderRadius: 20, padding: 'clamp(24px,5vw,36px)', marginBottom: 24, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20, border: '1px solid rgba(220,38,38,0.2)', boxShadow: '0 8px 32px rgba(220,38,38,0.15)' }}>
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ color: 'white', fontFamily: 'Georgia', fontSize: 'clamp(1.1rem, 4vw, 1.4rem)', marginBottom: 6 }}>{t('emergencyPanic')}</h2>
            <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: 'clamp(0.78rem, 2.5vw, 0.85rem)', lineHeight: 1.5 }}>{t('panicDesc')}</p>
          </div>
          <PanicButton size="large" />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
            {[['112', 'Emergency'], ['181', "Women's Help"], ['1091', 'DV Helpline']].map(([num, label]) => (
              <a key={num} href={`tel:${num}`} style={{ background: 'rgba(255,255,255,0.1)', color: 'white', padding: '8px 16px', borderRadius: 50, fontSize: 'clamp(0.72rem, 2vw, 0.8rem)', fontWeight: 700, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 5, border: '1px solid rgba(255,255,255,0.2)' }}>
                <Phone size={11} />{num} · {label}
              </a>
            ))}
          </div>
        </div>

        {/* Report Emergency (Direct Website SOS) */}
        <div id="direct-sos-section" style={{ marginBottom: 24 }}>
          <DirectSOSForm
            trustedContactCount={contactsCount}
            onSubmitted={() => setSosRefreshSignal(s => s + 1)}
          />
        </div>

        {/* My Incidents */}
        <div id="incident-history-section" style={{ marginBottom: 24 }}>
          <IncidentTracker
            userId={user?.id}
            refreshSignal={sosRefreshSignal}
            onIncidentsLoaded={setIncidents}
          />
        </div>

        {/* Emergency strip */}
        <div style={{ background: 'linear-gradient(135deg, #9d174d, #be185d)', borderRadius: 14, padding: 'clamp(14px,3vw,18px) clamp(14px,3vw,24px)', marginBottom: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={18} style={{ color: 'white', flexShrink: 0 }} />
            <span style={{ color: 'white', fontWeight: 700, fontSize: 'clamp(0.85rem, 3vw, 0.95rem)' }}>{t('inImmediateDanger')}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {[['112', 'Emergency'], ['181', "Women's Help"], ['1091', 'DV']].map(([num, label]) => (
              <a key={num} href={`tel:${num}`} style={{ background: 'rgba(255,255,255,0.2)', color: 'white', padding: 'clamp(7px,2vw,9px) 8px', borderRadius: 10, fontSize: 'clamp(0.72rem, 2vw, 0.85rem)', fontWeight: 700, textDecoration: 'none', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, border: '1px solid rgba(255,255,255,0.3)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Phone size={11} />{num}</div>
                <span style={{ fontSize: '0.65rem', opacity: 0.85 }}>{label}</span>
              </a>
            ))}
          </div>
        </div>

        {/* Feature cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))', gap: 16, marginBottom: 24 }}>
          {[
            { icon: <Eye size={32} style={{ color: '#be185d' }} />, title: t('sendDiscreeSOS'), desc: t('sendDiscreSOSDesc'), href: '/sos', cta: t('createSOSImage'), bg: 'linear-gradient(135deg, #fce7f3, #fdf2f8)' },
            { icon: <Mic size={32} style={{ color: '#7c3aed' }} />, title: t('voiceSosTitle'), desc: t('voiceSosCardDesc'), href: '/voice-sos', cta: t('setupVoiceSosBtn'), bg: 'linear-gradient(135deg, #f5f0ff, #fce7f3)' },
            { icon: <Users size={32} style={{ color: '#be185d' }} />, title: t('manageContacts'), desc: isHi ? 'संपर्क प्राथमिकता, सत्यापन, इतिहास और चेक-इन टाइमर प्रबंधित करें।' : 'Manage trusted contacts, verification, history, and safety check-in timers.', href: '/safe-contacts', cta: t('manageContacts'), bg: 'linear-gradient(135deg, #fff1f2, #fce7f3)' },
            { icon: <FileText size={32} style={{ color: '#9d174d' }} />, title: t('safetyPlanTitle'), desc: t('safetyPlanCardDesc'), href: '/therapy/safety-plan', cta: t('openSafetyPlan'), bg: 'linear-gradient(135deg, #fdf2f8, #fce7f3)' },
            { icon: <Heart size={32} style={{ color: '#db2777' }} />, title: t('talkToSomeone'), desc: t('talkDesc'), href: '/therapy', cta: t('startTalking'), bg: 'linear-gradient(135deg, #fdf2f8, #f5f0ff)' },
            { icon: <Scale size={32} style={{ color: '#9d174d' }} />, title: t('knowRights'), desc: t('knowRightsDesc'), href: '/legal', cta: t('askLegalQuestions'), bg: 'linear-gradient(135deg, #f5f0ff, #fce7f3)' },
          ].map((card, i) => (
            <div key={i} style={{ background: card.bg, borderRadius: 18, padding: 'clamp(18px,4vw,28px)', border: '1px solid rgba(190,24,93,0.1)', display: 'flex', flexDirection: 'column' }}>
              <div style={{ marginBottom: 12 }}>{card.icon}</div>
              <h3 style={{ fontSize: 'clamp(0.95rem, 3vw, 1.1rem)', fontWeight: 700, color: '#1a0a12', marginBottom: 8, fontFamily: 'Georgia' }}>{card.title}</h3>
              <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.8rem, 2.5vw, 0.85rem)', lineHeight: 1.6, flex: 1 }}>{card.desc}</p>
              <button onClick={() => navigate(card.href)} className="btn-primary" style={{ marginTop: 16, width: '100%', fontSize: 'clamp(0.8rem, 2.5vw, 0.85rem)', padding: '11px 16px' }}>
                {card.cta} →
              </button>
            </div>
          ))}
        </div>

        {/* Resources */}
        <div style={{ background: 'white', borderRadius: 16, padding: 'clamp(16px,4vw,24px)', border: '1px solid rgba(190,24,93,0.1)' }}>
          <h3 style={{ fontFamily: 'Georgia', fontSize: 'clamp(0.9rem, 3vw, 1rem)', color: '#1a0a12', marginBottom: 14 }}>{t('trustedResources')}</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 170px), 1fr))', gap: 10 }}>
            {[
              { name: 'iCall Counseling', contact: '9152987821' },
              { name: 'Snehi Helpline', contact: '044-24640050' },
              { name: 'NALSA Legal Aid', contact: '15100' },
              { name: 'NCW Helpline', contact: '7827170170' },
              { name: 'Childline', contact: '1098' },
              { name: 'Police Emergency', contact: '100' },
            ].map((r, i) => (
              <a key={i} href={`tel:${r.contact}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderRadius: 10, background: '#fdf2f8', border: '1px solid rgba(190,24,93,0.1)', textDecoration: 'none' }}>
                <span style={{ fontSize: 'clamp(0.72rem, 2vw, 0.8rem)', color: '#1a0a12', fontWeight: 600 }}>{r.name}</span>
                <span style={{ fontSize: 'clamp(0.72rem, 2vw, 0.82rem)', color: '#be185d', fontWeight: 700 }}>{r.contact}</span>
              </a>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}
