'use client'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import Link from 'next/link'
import { Shield, MessageCircle, Scale, Eye, ChevronRight, Heart } from 'lucide-react'

export default function HomePage() {
  useHavenAuth()

  return (
    <main className="min-h-screen" style={{ background: 'linear-gradient(135deg, #fdf2f8 0%, #fce7f3 40%, #f5f0ff 100%)' }}>
      {/* Nav */}
      <nav style={{ background: 'rgba(253,242,248,0.9)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(190,24,93,0.1)', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '14px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Shield size={24} style={{ color: '#be185d' }} />
            <span style={{ fontSize: '1.25rem', fontWeight: 700, color: '#be185d', fontFamily: 'Georgia, serif' }}>Haven</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link href="/dashboard">
              <button className="btn-primary" style={{ padding: '9px 18px', fontSize: '0.82rem' }}>Dashboard</button>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ maxWidth: 1200, margin: '0 auto', padding: 'clamp(40px,8vw,80px) 16px clamp(30px,5vw,60px)', textAlign: 'center' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(190,24,93,0.08)', borderRadius: 50, padding: '7px 16px', marginBottom: 24, border: '1px solid rgba(190,24,93,0.15)' }}>
          <span style={{ fontSize: '0.75rem', color: '#be185d', fontWeight: 600 }}>🏆 Team - Byte Me</span>
        </div>
        <h1 style={{ fontSize: 'clamp(2rem, 7vw, 4.5rem)', fontFamily: 'Georgia, serif', fontWeight: 700, color: '#1a0a12', lineHeight: 1.15, margin: '0 auto 20px', maxWidth: 800 }}>
          A Silent Shield.<br />
          <span style={{ color: '#be185d' }}>A Strong Voice.</span>
        </h1>
        <p style={{ fontSize: 'clamp(0.95rem, 2.5vw, 1.15rem)', color: '#8b6b7d', maxWidth: 560, margin: '0 auto 36px', lineHeight: 1.75, padding: '0 8px' }}>
          Haven empowers women in abusive situations with discreet AI-powered help —
          from hidden SOS messages to legal guidance and mental health support.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', padding: '0 16px' }}>
          <Link href="/sos">
            <button className="btn-primary" style={{ fontSize: 'clamp(0.85rem, 2vw, 1rem)', padding: 'clamp(12px,2vw,15px) clamp(24px,4vw,36px)' }}>
              Get Help Discreetly →
            </button>
          </Link>
          <Link href="/authority">
            <button className="btn-secondary" style={{ fontSize: 'clamp(0.85rem, 2vw, 1rem)', padding: 'clamp(12px,2vw,15px) clamp(24px,4vw,36px)' }}>
              Authority Dashboard
            </button>
          </Link>
        </div>
        <p style={{ marginTop: 16, fontSize: '0.8rem', color: '#be185d' }}>
          Emergency: <strong>112</strong> · Women Helpline: <strong>181</strong>
        </p>
      </section>

      {/* Features */}
      <section style={{ maxWidth: 1200, margin: '0 auto', padding: '20px 16px clamp(40px,6vw,80px)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 260px), 1fr))', gap: 16 }}>
          {[
            { icon: <Eye size={28} style={{ color: '#be185d' }} />, title: 'Discreet SOS', desc: 'Hide distress messages inside innocent-looking images using AI steganography.', href: '/sos', color: '#fce7f3' },
            { icon: <Heart size={28} style={{ color: '#db2777' }} />, title: 'Talk to Aria', desc: 'Compassionate AI companion with animated face. Available 24/7, completely private.', href: '/therapy', color: '#fdf2f8' },
            { icon: <Scale size={28} style={{ color: '#9d174d' }} />, title: 'Legal Guidance', desc: 'Instant plain-language answers on Indian domestic violence law and your rights.', href: '/legal', color: '#f5f0ff' },
            { icon: <MessageCircle size={28} style={{ color: '#be185d' }} />, title: 'Authority Dashboard', desc: 'For officials: monitor SOS cases, decode hidden messages, search culprit profiles.', href: '/authority', color: '#fce7f3' },
          ].map((f, i) => (
            <Link href={f.href} key={i} style={{ textDecoration: 'none' }}>
              <div style={{ background: f.color, borderRadius: 16, padding: 'clamp(20px,4vw,32px)', cursor: 'pointer', transition: 'transform 0.2s', border: '1px solid rgba(190,24,93,0.1)', height: '100%' }}
                onMouseEnter={e => (e.currentTarget.style.transform = 'translateY(-4px)')}
                onMouseLeave={e => (e.currentTarget.style.transform = 'translateY(0)')}>
                <div style={{ marginBottom: 14 }}>{f.icon}</div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 10, color: '#1a0a12' }}>{f.title}</h3>
                <p style={{ color: '#8b6b7d', lineHeight: 1.6, fontSize: '0.9rem' }}>{f.desc}</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 16, color: '#be185d', fontWeight: 600, fontSize: '0.82rem' }}>
                  <span>Open</span><ChevronRight size={13} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* Stats */}
      <section style={{ background: 'linear-gradient(135deg, #9d174d, #be185d)', padding: 'clamp(40px,6vw,60px) 16px', textAlign: 'center' }}>
        <h2 style={{ color: 'white', fontSize: 'clamp(1.3rem, 4vw, 1.8rem)', fontFamily: 'Georgia, serif', marginBottom: 36 }}>Why Haven Matters</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 24, maxWidth: 600, margin: '0 auto' }}>
          {[
            { stat: '1 in 3', label: 'women face violence globally' },
            { stat: '30%', label: 'of Indian women face domestic abuse' },
            { stat: '10%', label: 'only seek mental health support' },
            { stat: '14%', label: 'have access to legal assistance' },
          ].map((s, i) => (
            <div key={i} style={{ color: 'white', textAlign: 'center' }}>
              <div style={{ fontSize: 'clamp(1.8rem, 5vw, 2.5rem)', fontWeight: 800, fontFamily: 'Georgia, serif' }}>{s.stat}</div>
              <div style={{ fontSize: '0.82rem', opacity: 0.85, marginTop: 4 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      <footer style={{ padding: '24px 16px', textAlign: 'center', borderTop: '1px solid rgba(190,24,93,0.1)' }}>
        <p style={{ color: '#8b6b7d', fontSize: '0.85rem' }}>© 2024 Haven · Built with love for women's safety</p>
        <p style={{ color: '#be185d', fontSize: '0.82rem', marginTop: 6 }}>Emergency: 112 · Women's Helpline: 181 · DV Helpline: 1091</p>
      </footer>
    </main>
  )
}