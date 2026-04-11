'use client'
import { useState } from 'react'
import Link from 'next/link'
import { Shield, ArrowLeft, Wand2, Image, Lock, Share2, AlertCircle, CheckCircle } from 'lucide-react'
import PanicButton from '@/components/PanicButton'


const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
type Step = 'message' | 'generate' | 'encode' | 'share'

export default function SOSPage() {
  const [step, setStep] = useState<Step>('message')
  const [keywords, setKeywords] = useState('')
  const [expandedMsg, setExpandedMsg] = useState('')
  const [imagePrompt, setImagePrompt] = useState('peaceful garden with flowers')
  const [imageBase64, setImageBase64] = useState('')
  const [encodedImageBase64, setEncodedImageBase64] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function expandMessage() {
    if (!keywords.trim()) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/text-generation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keywords }) })
      const data = await res.json()
      setExpandedMsg(data.expanded_message)
      setStep('generate')
    } catch { setError('Could not expand message. Please check your connection.') }
    finally { setLoading(false) }
  }

  async function generateImage() {
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/img-generation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: imagePrompt }) })
      const data = await res.json()
      setImageBase64(data.image_base64)
      setStep('encode')
    } catch { setError('Image generation failed. Please try again.') }
    finally { setLoading(false) }
  }

  async function encodeMessage() {
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/encode`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: expandedMsg, image_base64: imageBase64 }) })
      const data = await res.json()
      setEncodedImageBase64(data.encoded_image_base64)
      setStep('share')
    } catch { setError('Encoding failed. Please try again.') }
    finally { setLoading(false) }
  }

  function downloadImage() {
    const link = document.createElement('a')
    link.download = 'haven_sos_image.png'
    link.href = 'data:image/png;base64,' + encodedImageBase64
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const steps = [
    { id: 'message', label: 'Message', icon: <Wand2 size={14} /> },
    { id: 'generate', label: 'Image', icon: <Image size={14} /> },
    { id: 'encode', label: 'Hide', icon: <Lock size={14} /> },
    { id: 'share', label: 'Share', icon: <Share2 size={14} /> },
  ]
  const stepIndex = steps.findIndex(s => s.id === step)

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #fdf2f8 0%, #fce7f3 100%)' }}>
      {/* Header */}
      <div style={{ background: 'rgba(253,242,248,0.9)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(190,24,93,0.1)', padding: '14px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link href="/"><button style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#be185d', transition: 'all 0.2s' }} title="Go back to home page" aria-label="Go back to home page"><ArrowLeft size={18} /></button></Link>
          <Shield size={20} style={{ color: '#be185d' }} />
          <span style={{ fontWeight: 700, color: '#be185d', fontFamily: 'Georgia', fontSize: 'clamp(0.85rem, 3vw, 0.95rem)' }}>Haven · Discreet SOS</span>
        </div>
        {/* Small panic button in header */}
        <PanicButton size="small" />
      </div>

      <div style={{ maxWidth: 680, margin: '0 auto', padding: 'clamp(20px,4vw,40px) 16px' }}>

        {/* Emergency Banner */}
        <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 12, padding: '12px 16px', marginBottom: 24, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <AlertCircle size={16} style={{ color: '#dc2626', flexShrink: 0, marginTop: 2 }} />
          <p style={{ fontSize: 'clamp(0.78rem, 2.5vw, 0.85rem)', color: '#dc2626', lineHeight: 1.5 }}>
            <strong>In immediate danger?</strong> Call <strong>112</strong> or Women's Helpline <strong>181</strong>
          </p>
        </div>

        {/* Step indicator */}
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 4, marginBottom: 28, flexWrap: 'nowrap', overflowX: 'auto', paddingBottom: 4 }}>
          {steps.map((s, i) => (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 5,
                background: step === s.id ? '#be185d' : i < stepIndex ? '#dcfce7' : 'rgba(190,24,93,0.1)',
                color: step === s.id ? 'white' : i < stepIndex ? '#15803d' : '#be185d',
                padding: 'clamp(6px,1.5vw,8px) clamp(10px,2vw,16px)', borderRadius: 50,
                fontSize: 'clamp(0.72rem, 2vw, 0.8rem)', fontWeight: 600, transition: 'all 0.3s'
              }}>
                {s.icon}<span>{s.label}</span>
              </div>
              {i < steps.length - 1 && <div style={{ width: 'clamp(8px,2vw,20px)', height: 1, background: 'rgba(190,24,93,0.2)', flexShrink: 0 }} />}
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="glass-card" style={{ padding: 'clamp(20px,5vw,36px)' }}>
          {step === 'message' && (
            <div>
              <h2 style={{ fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', fontFamily: 'Georgia', marginBottom: 8, color: '#1a0a12' }}>Describe Your Situation</h2>
              <p style={{ color: '#8b6b7d', marginBottom: 20, fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)', lineHeight: 1.6 }}>
                Type a few keywords. Our AI expands them into a complete message. <em>Even 2-3 words is enough.</em>
              </p>
              <textarea value={keywords} onChange={e => setKeywords(e.target.value)}
                placeholder="e.g. scared, husband hitting me, locked in room"
                style={{ width: '100%', height: 'clamp(90px,20vw,120px)', padding: 14, borderRadius: 12, border: '2px solid rgba(190,24,93,0.2)', background: 'white', fontFamily: 'Georgia', fontSize: 'clamp(0.85rem, 2.5vw, 0.95rem)', resize: 'vertical', outline: 'none', color: '#1a0a12', lineHeight: 1.5 }}
              />
              {error && <p style={{ color: '#dc2626', fontSize: '0.82rem', marginTop: 8 }}>{error}</p>}
              <button className="btn-primary" onClick={expandMessage} disabled={loading || !keywords.trim()} style={{ marginTop: 16, width: '100%', opacity: loading || !keywords.trim() ? 0.6 : 1 }}>
                {loading ? '⏳ Expanding...' : 'Create Distress Message →'}
              </button>
            </div>
          )}

          {step === 'generate' && (
            <div>
              <h2 style={{ fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', fontFamily: 'Georgia', marginBottom: 8, color: '#1a0a12' }}>Message Ready ✓</h2>
              <div style={{ background: 'rgba(190,24,93,0.05)', borderRadius: 12, padding: 14, marginBottom: 20, border: '1px solid rgba(190,24,93,0.1)' }}>
                <p style={{ fontSize: '0.78rem', color: '#be185d', fontWeight: 600, marginBottom: 6 }}>✓ Distress message:</p>
                <p style={{ color: '#1a0a12', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)', lineHeight: 1.6 }}>{expandedMsg}</p>
              </div>
              <p style={{ color: '#8b6b7d', marginBottom: 14, fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>Choose an image theme:</p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 16 }}>
                {['peaceful garden with flowers', 'sunset over mountains', 'cup of tea on wooden table', 'birds flying in blue sky', 'colorful market stall', 'children playing in park'].map(p => (
                  <div key={p} onClick={() => setImagePrompt(p)} style={{ padding: '9px 10px', borderRadius: 10, cursor: 'pointer', fontSize: 'clamp(0.72rem, 2vw, 0.8rem)', textAlign: 'center', transition: 'all 0.2s', background: imagePrompt === p ? 'rgba(190,24,93,0.12)' : 'rgba(190,24,93,0.04)', border: imagePrompt === p ? '2px solid #be185d' : '2px solid transparent', color: imagePrompt === p ? '#be185d' : '#8b6b7d' }}>{p}</div>
                ))}
              </div>
              {error && <p style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: 8 }}>{error}</p>}
              <button className="btn-primary" onClick={generateImage} disabled={loading} style={{ width: '100%', opacity: loading ? 0.6 : 1 }}>
                {loading ? '🎨 Generating... (may take 30s)' : 'Generate Safe Image →'}
              </button>
            </div>
          )}

          {step === 'encode' && (
            <div>
              <h2 style={{ fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', fontFamily: 'Georgia', marginBottom: 8, color: '#1a0a12' }}>Image Generated ✓</h2>
              <p style={{ color: '#8b6b7d', marginBottom: 16, fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>Now we'll hide your message inside this image.</p>
              {imageBase64 && (
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <img src={`data:image/png;base64,${imageBase64}`} alt="Generated" style={{ maxWidth: '100%', maxHeight: 'clamp(160px,40vw,240px)', borderRadius: 12, border: '2px solid rgba(190,24,93,0.1)' }} />
                  <p style={{ fontSize: '0.75rem', color: '#8b6b7d', marginTop: 8 }}>👆 Looks like an ordinary photo</p>
                </div>
              )}
              {error && <p style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: 8 }}>{error}</p>}
              <button className="btn-primary" onClick={encodeMessage} disabled={loading} style={{ width: '100%', opacity: loading ? 0.6 : 1 }}>
                {loading ? '🔐 Hiding message...' : 'Hide Message in Image →'}
              </button>
            </div>
          )}

          {step === 'share' && (
            <div>
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <CheckCircle size={44} style={{ color: '#15803d', margin: '0 auto 10px', display: 'block' }} />
                <h2 style={{ fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', fontFamily: 'Georgia', color: '#1a0a12', marginBottom: 8 }}>SOS Image Ready!</h2>
                <p style={{ color: '#8b6b7d', fontSize: 'clamp(0.82rem, 2.5vw, 0.9rem)' }}>Looks normal to everyone. Only Haven authorities can decode it.</p>
              </div>
              {encodedImageBase64 && (
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <img src={`data:image/png;base64,${encodedImageBase64}`} alt="Encoded SOS" style={{ maxWidth: '100%', maxHeight: 'clamp(160px,40vw,240px)', borderRadius: 12, border: '2px solid rgba(190,24,93,0.1)' }} />
                </div>
              )}
              <div style={{ background: '#f0fdf4', borderRadius: 12, padding: '12px 16px', marginBottom: 20, border: '1px solid #86efac' }}>
                <p style={{ fontSize: 'clamp(0.78rem, 2.2vw, 0.85rem)', color: '#15803d', lineHeight: 1.7 }}>
                  <strong>📋 Instructions:</strong><br />
                  1. Download this image<br />
                  2. Post on social media with <strong>#HavenSOS</strong><br />
                  3. Authorities will decode and contact you
                </p>
              </div>
              <button className="btn-primary" onClick={downloadImage} style={{ width: '100%', marginBottom: 10 }}>⬇️ Download SOS Image</button>
              <p style={{ fontSize: '0.78rem', color: '#8b6b7d', textAlign: 'center', marginBottom: 10 }}>📌 Download first, then share below</p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 10 }}>
                <button onClick={() => window.open(`https://wa.me/?text=${encodeURIComponent('I need help. #HavenSOS')}`, '_blank')} style={{ padding: '11px 10px', borderRadius: 12, border: 'none', background: '#25D366', color: 'white', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>💬 WhatsApp</button>
                <button onClick={() => window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent('I need help. #HavenSOS #WomenSafety')}`, '_blank')} style={{ padding: '11px 10px', borderRadius: 12, border: 'none', background: '#000', color: 'white', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>𝕏 Twitter/X</button>
                <button onClick={() => { navigator.clipboard.writeText('#HavenSOS #WomenSafety'); window.open('https://www.instagram.com/', '_blank') }} style={{ padding: '11px 10px', borderRadius: 12, border: 'none', background: 'linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)', color: 'white', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>📸 Instagram</button>
                <button onClick={() => window.open(`https://www.facebook.com/sharer/sharer.php?quote=${encodeURIComponent('I need help. #HavenSOS')}`, '_blank')} style={{ padding: '11px 10px', borderRadius: 12, border: 'none', background: '#1877F2', color: 'white', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>👤 Facebook</button>
                <button onClick={() => window.open(`https://t.me/share/url?url=https://haven.app&text=${encodeURIComponent('I need help. #HavenSOS')}`, '_blank')} style={{ padding: '11px 10px', borderRadius: 12, border: 'none', background: '#0088cc', color: 'white', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>✈️ Telegram</button>
                <button onClick={() => { navigator.clipboard.writeText(`${expandedMsg}\n\n#HavenSOS`); alert('✓ Copied!') }} style={{ padding: '11px 10px', borderRadius: 12, border: '2px solid #be185d', background: 'white', color: '#be185d', fontWeight: 600, fontSize: 'clamp(0.75rem, 2vw, 0.85rem)', cursor: 'pointer' }}>📋 Copy Text</button>
              </div>
              <button className="btn-secondary" onClick={() => { setStep('message'); setKeywords(''); setExpandedMsg(''); setImageBase64(''); setEncodedImageBase64('') }} style={{ width: '100%' }}>Create Another</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}