// 404 boundary (Phase 17). Rendered for unmatched routes. Neutral wording to
// preserve the app's discreet nature; self-contained inline styles so it renders
// regardless of the state of shared styling/providers.
import Link from 'next/link'

export default function NotFound() {
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
      <div style={{ textAlign: 'center', maxWidth: 380 }}>
        <div style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: 8 }}>Page not found</div>
        <p style={{ fontSize: '0.9rem', color: '#6b5563', lineHeight: 1.5, marginBottom: 20 }}>
          That page isn&apos;t available.
        </p>
        <Link
          href="/"
          style={{
            background: '#be185d',
            color: '#fff',
            borderRadius: 24,
            padding: '10px 26px',
            fontSize: '0.85rem',
            fontWeight: 700,
            textDecoration: 'none',
          }}
        >
          Home
        </Link>
      </div>
    </div>
  )
}
