'use client'
import { useRouter } from 'next/navigation'
import { UserButton } from '@clerk/nextjs'
import { Shield, Heart, Scale, Eye, Phone, AlertTriangle } from 'lucide-react'
import PanicButton from '@/components/PanicButton'
import { useLang, LanguageSelector } from '@/components/LanguageContext'
import { useHavenAuth } from '@/hooks/useHavenAuth'

export default function DashboardPage() {
  useHavenAuth()
  const router = useRouter()
  const { t } = useLang()
  const firstName = 'Manav'
  const navigate = (href: string) => router.push(href)

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #fdf2f8 0%, #fce7f3 100%)' }}>
      {/* Header */}
      <div style={{ background: 'rgba(253,242,248,0.9)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '14px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={22} style={{ color: '#be185d' }} />
          <span style={{ fontSize: 'clamp(1rem, 4vw, 1.25rem)', fontWeight: 700, color: '#be185d', fontFamily: 'Georgia' }}>{t('appName')}</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Language selector on dashboard */}
          <LanguageSelector compact />
          <UserButton afterSignOutUrl="/home" />
          <button onClick={() => navigate('/')} style={{ background: 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 8, padding: '6px 14px', cursor: 'pointer', color: '#be185d', fontSize: '0.82rem', fontWeight: 600 }}>
            {t('home')}
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: 'clamp(24px,5vw,48px) 16px' }}>

        {/* Welcome */}
        <div style={{ marginBottom: 28 }}>
          <p style={{ fontSize: '0.85rem', color: '#8b6b7d', marginBottom: 4 }}>{t('welcomeBack')}</p>
          <h1 style={{ fontSize: 'clamp(1.5rem, 6vw, 2rem)', fontFamily: 'Georgia', color: '#1a0a12', marginBottom: 10 }}>
            {t('hello')}, {firstName} 🌸
          </h1>
          <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.85rem, 2.5vw, 0.95rem)', lineHeight: 1.7, maxWidth: 540 }}>
            {t('havenIsHere')}
          </p>
        </div>

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
      </div>
    </div>
  )
}