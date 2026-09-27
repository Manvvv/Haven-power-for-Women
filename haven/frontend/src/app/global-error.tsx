'use client'
// GLOBAL error boundary (Phase 17) — the last line of defense.
// This is the ONLY thing that renders if the ROOT LAYOUT itself throws
// (e.g. a provider like ClerkProvider / LanguageProvider / QuickEscape fails to
// initialize). Without this file, such a failure produces a fully blank screen
// with no button and no content — exactly the "global blank" failure mode.
// It MUST render its own <html> and <body> because it replaces the root layout.
// Fully self-contained: no shared imports, inline styles only.
import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('[haven:global-error-boundary]', error)
  }, [error])

  const isDev = process.env.NODE_ENV !== 'production'

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
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
            Couldn&apos;t start the app
          </div>
          <p style={{ fontSize: '0.9rem', color: '#6b5563', lineHeight: 1.5, marginBottom: 20 }}>
            The app hit a problem while loading. Please try again.
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

          <button
            onClick={() => reset()}
            style={{
              background: '#be185d',
              color: '#fff',
              border: 'none',
              borderRadius: 24,
              padding: '10px 26px',
              fontSize: '0.85rem',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
