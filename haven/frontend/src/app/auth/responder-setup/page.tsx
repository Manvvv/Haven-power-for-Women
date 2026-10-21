'use client'

import { useState, useEffect, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Shield, CheckCircle2, AlertTriangle, Eye, EyeOff } from 'lucide-react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function ResponderSetupForm() {
  const searchParams = useSearchParams()
  const [token, setToken] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    // Pre-fill token from URL query param ?token=... if admin shared a direct link.
    const t = searchParams.get('token')
    if (t) setToken(t)
  }, [searchParams])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (password.length < 12) {
      setError('Password must be at least 12 characters.')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    if (!token.trim()) {
      setError('Setup token is required.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API}/auth/responder-setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim(), password }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success) {
        setSuccess(true)
      } else {
        // Surface backend error messages but never raw internal details.
        const msg = data?.detail || ''
        if (msg.includes('invalid') || msg.includes('used') || msg.includes('expired')) {
          setError('This setup link is invalid, has already been used, or has expired. Contact your administrator for a new token.')
        } else if (msg.includes('12') || msg.toLowerCase().includes('password')) {
          setError('Password must be at least 12 characters.')
        } else {
          setError('Setup failed. Please check your token and try again.')
        }
      }
    } catch {
      setError('Could not reach the server. Please check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div style={{ textAlign: 'center' }}>
        <CheckCircle2 size={48} style={{ color: '#10b981', margin: '0 auto 16px', display: 'block' }} />
        <h2 style={{ fontFamily: 'Georgia', fontSize: '1.3rem', color: '#1a0a12', marginBottom: 8 }}>
          Password Set Successfully
        </h2>
        <p style={{ color: '#6b7280', fontSize: '0.875rem', marginBottom: 20, lineHeight: 1.6 }}>
          Your password has been saved. An administrator must verify your account before you can receive emergency dispatch requests.
          You will be notified when your account is approved.
        </p>
        <Link href="/responder" style={{ display: 'inline-block', background: '#be185d', color: 'white', padding: '11px 24px', borderRadius: 10, fontWeight: 700, textDecoration: 'none', fontSize: '0.9rem' }}>
          Go to Responder Portal →
        </Link>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#4b5563', marginBottom: 6 }}>
          Setup Token
        </label>
        <textarea
          value={token}
          onChange={e => { setToken(e.target.value); setError('') }}
          placeholder="Paste your one-time setup token here…"
          rows={3}
          style={{
            width: '100%', padding: '10px 12px', borderRadius: 10, border: '2px solid #e2d6e0',
            fontSize: '0.8rem', outline: 'none', resize: 'vertical', boxSizing: 'border-box',
            fontFamily: 'monospace',
          }}
          required
        />
        <p style={{ fontSize: '0.7rem', color: '#9ca3af', marginTop: 4 }}>
          Your administrator provided this token after approving your registration.
        </p>
      </div>

      <div>
        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#4b5563', marginBottom: 6 }}>
          New Password <span style={{ color: '#9ca3af', fontWeight: 400 }}>(min. 12 characters)</span>
        </label>
        <div style={{ position: 'relative' }}>
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={e => { setPassword(e.target.value); setError('') }}
            placeholder="Choose a strong password…"
            autoComplete="new-password"
            style={{
              width: '100%', padding: '11px 40px 11px 12px', borderRadius: 10,
              border: '2px solid #e2d6e0', fontSize: '0.9rem', outline: 'none', boxSizing: 'border-box',
            }}
            required
            minLength={12}
          />
          <button
            type="button"
            onClick={() => setShowPassword(v => !v)}
            style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: 4 }}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>

      <div>
        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#4b5563', marginBottom: 6 }}>
          Confirm Password
        </label>
        <input
          type={showPassword ? 'text' : 'password'}
          value={confirmPassword}
          onChange={e => { setConfirmPassword(e.target.value); setError('') }}
          placeholder="Re-enter your password…"
          autoComplete="new-password"
          style={{
            width: '100%', padding: '11px 12px', borderRadius: 10,
            border: error && confirmPassword && password !== confirmPassword ? '2px solid #dc2626' : '2px solid #e2d6e0',
            fontSize: '0.9rem', outline: 'none', boxSizing: 'border-box',
          }}
          required
          minLength={12}
        />
      </div>

      {error && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '10px 12px' }}>
          <AlertTriangle size={16} style={{ color: '#dc2626', flexShrink: 0, marginTop: 1 }} />
          <p style={{ fontSize: '0.8rem', color: '#991b1b', margin: 0 }}>{error}</p>
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        style={{
          width: '100%', padding: '12px 20px', background: loading ? '#d1d5db' : '#be185d',
          color: 'white', border: 'none', borderRadius: 10, fontWeight: 700, fontSize: '0.95rem',
          cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
        }}
      >
        {loading ? 'Setting password…' : 'Set Password & Activate Account'}
      </button>

      <p style={{ textAlign: 'center', fontSize: '0.75rem', color: '#9ca3af', marginTop: 4 }}>
        Already have credentials?{' '}
        <Link href="/responder" style={{ color: '#be185d', fontWeight: 600 }}>
          Sign in to Responder Portal
        </Link>
      </p>
    </form>
  )
}

export default function ResponderSetupPage() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#1a0a12', padding: 16 }}>
      <div style={{ background: 'white', padding: 'clamp(28px, 6vw, 48px)', borderRadius: 20, width: '100%', maxWidth: 440, boxShadow: '0 20px 60px rgba(0,0,0,0.4)' }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Shield size={44} style={{ color: '#be185d', display: 'block', margin: '0 auto 12px' }} />
          <h1 style={{ fontFamily: 'Georgia', fontSize: 'clamp(1.15rem, 4vw, 1.4rem)', color: '#1a0a12', marginBottom: 6 }}>
            Responder Account Setup
          </h1>
          <p style={{ fontSize: '0.8rem', color: '#8b6b7d', margin: 0 }}>
            Set your password to activate your field-responder account
          </p>
        </div>

        {/* Security notice */}
        <div style={{ background: '#fdf4ff', border: '1px solid #f0abfc', borderRadius: 10, padding: '10px 14px', marginBottom: 20 }}>
          <p style={{ fontSize: '0.75rem', color: '#6d28d9', margin: 0, lineHeight: 1.5 }}>
            🔒 Your setup token expires within 24 hours and can only be used once. After setting your password, an administrator must verify your account before you can receive emergency dispatches.
          </p>
        </div>

        {/* Form with Suspense for searchParams */}
        <Suspense fallback={<div style={{ textAlign: 'center', color: '#9ca3af', padding: 20 }}>Loading…</div>}>
          <ResponderSetupForm />
        </Suspense>
      </div>
    </div>
  )
}
