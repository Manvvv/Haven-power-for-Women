// Route transition loading state (Phase 17).
// Next renders this in the page slot while a route segment's code/data is being
// fetched. Without it, a slow chunk fetch shows nothing — indistinguishable from
// a "blank page". A visible loader turns that gap into obvious feedback.
// Server component (no interactivity needed); self-contained inline styles.
export default function Loading() {
  return (
    <div
      style={{
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 14,
        background: '#fdf2f8',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: '50%',
          border: '3px solid rgba(190,24,93,0.2)',
          borderTopColor: '#be185d',
          animation: 'haven-spin 0.8s linear infinite',
        }}
      />
      <span style={{ fontSize: '0.82rem', color: '#8b6b7d', fontWeight: 500 }}>Loading…</span>
      <style>{`@keyframes haven-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
