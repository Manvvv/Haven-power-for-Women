'use client'
// Route-segment error boundary (Phase 17).
// Purpose: if any page in a segment throws at render/runtime, Next renders THIS
// in the page slot instead of leaving a silent blank. It is intentionally
// self-contained (inline styles, no i18n / no shared imports) so it still shows
// even if globals.css, a provider, or a shared chunk is the thing that failed.
// Wording is deliberately neutral to preserve the app's discreet nature, and no
// stack trace is shown in production.
import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Surface the real error in the console for diagnosis (dev + prod console).
    // This is the "first meaningful error" the browser console will show.
    console.error('[haven:error-boundary]', error)
  }, [error])

  const isDev = process.env.NODE_ENV !== 'production'

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: '#fdf2f8',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        color: '#1a0a12',
      }}
    >
      <div
        style={{
          maxWidth: 420,
          width: '100%',
          textAlign: 'center',
          background: '#ffffff',
          border: '1px solid rgba(190,24,93,0.15)',
          borderRadius: 20,
          padding: '32px 28px',
          boxShadow: '0 8px 32px rgba(190,24,93,0.1)',
        }}
      >
        <div style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: 8 }}>
          This page didn&apos;t load
        </div>
        <p style={{ fontSize: '0.9rem', color: '#6b5563', lineHeight: 1.5, marginBottom: 20 }}>
          Something interrupted the page. You can try again — your session stays active.
        </p>

        {isDev && (
          <pre
            style={{
              textAlign: 'left',
              fontSize: '0.72rem',
              color: '#9f1239',
              background: '#fff1f5',
              border: '1px solid rgba(190,24,93,0.12)',
              borderRadius: 10,
              padding: '10px 12px',
              overflowX: 'auto',
              marginBottom: 20,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {error?.message}
            {error?.digest ? `\n\ndigest: ${error.digest}` : ''}
          </pre>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={() => reset()}
            style={{
              background: '#be185d',
              color: '#fff',
              border: 'none',
              borderRadius: 24,
              padding: '10px 22px',
              fontSize: '0.85rem',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
          <a
            href="/"
            style={{
              background: 'rgba(190,24,93,0.08)',
              color: '#be185d',
              border: '1px solid rgba(190,24,93,0.2)',
              borderRadius: 24,
              padding: '10px 22px',
              fontSize: '0.85rem',
              fontWeight: 700,
              textDecoration: 'none',
            }}
          >
            Home
          </a>
        </div>
      </div>
    </div>
  )
}
