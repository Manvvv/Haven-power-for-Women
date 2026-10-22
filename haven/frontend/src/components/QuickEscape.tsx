'use client'
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Search, Heart, Star, ChefHat, Share2 } from 'lucide-react'

export default function QuickEscape({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname() || ''

  // Quick Disguise is strictly for victim portals (/home, /sos, /voice-sos, /therapy, /legal, /dashboard, etc.).
  // It is explicitly removed on:
  // 1. Root calculator camouflage page ('/')
  // 2. Responder login and responder field portal ('/responder', '/auth/responder-setup')
  // 3. Authority portal and all pages after authority login ('/authority', '/authority/providers', '/authority/rapid-response', '/admin')
  const isExcludedRoute =
    pathname === '/' ||
    pathname.startsWith('/responder') ||
    pathname.startsWith('/authority') ||
    pathname.startsWith('/admin') ||
    pathname.startsWith('/auth/responder')

  const [isCamouflaged, setIsCamouflaged] = useState(false)

  // Restore from camouflage and navigate directly to Haven home page
  const restoreToHome = useCallback(() => {
    setIsCamouflaged(false)
    router.push('/home')
  }, [router])
  // Automatically cancel camouflage when navigating to an excluded operational page
  useEffect(() => {
    if (isExcludedRoute && isCamouflaged) {
      restoreToHome()
    }
  }, [isExcludedRoute, isCamouflaged])

  const [typedBuffer, setTypedBuffer] = useState('')
  const [checkedIngredients, setCheckedIngredients] = useState<Record<number, boolean>>({})
  const [isMobile, setIsMobile] = useState(false)

  const lastEscTimeRef = useRef<number>(0)
  const prevTitleRef = useRef<string | null>(null)
  // Private restore code. Intentionally NOT rendered anywhere in the disguise so
  // a shoulder-surfer can never read it off the screen; the user learns their
  // return gesture during setup, not from the camouflage page itself.
  const SECRET_PIN = '1810'

  // Detect mobile width
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 640)
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  // Double-tap Escape key, secret PIN '1810', or 6-7 shake strokes to disguise
  useEffect(() => {
    // Completely disable all listeners on excluded routes (responder, authority, admin)
    if (isExcludedRoute) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Check double-tap Escape key
      if (e.key === 'Escape') {
        const now = Date.now()
        if (now - lastEscTimeRef.current < 600) {
          if (isCamouflaged) {
            restoreToHome()
          } else {
            setIsCamouflaged(true)
          }
          lastEscTimeRef.current = 0
        } else {
          lastEscTimeRef.current = now
        }
      }

      // Check typed buffer for secret unlock PIN '1810'
      if (/^[0-9]$/.test(e.key)) {
        setTypedBuffer(prev => {
          const next = (prev + e.key).slice(-4)
          if (next === SECRET_PIN) {
            restoreToHome()
            return ''
          }
          return next
        })
      }
    }

    // Shake gesture detection for mobile devices:
    // Requires 6-7 deliberate, rapid back-and-forth shake strokes.
    // Accidental movements (like picking up the phone or setting it down on a table)
    // generate only 1 brief motion impulse or smooth gradual delta, which is ignored
    // and automatically resets after 1.4 seconds of no shaking.
    let lastX = 0, lastY = 0, lastZ = 0
    let lastSampleTime = 0
    let lastShakeStrokeTime = 0
    let shakeCount = 0

    const handleDeviceMotion = (e: DeviceMotionEvent) => {
      if (isCamouflaged) return

      const acc = e.accelerationIncludingGravity || e.acceleration
      if (!acc) return

      const curX = acc.x ?? 0
      const curY = acc.y ?? 0
      const curZ = acc.z ?? 0
      const now = Date.now()

      // Initial baseline
      if (lastSampleTime === 0) {
        lastX = curX
        lastY = curY
        lastZ = curZ
        lastSampleTime = now
        return
      }

      const timeDelta = now - lastSampleTime
      // Minimum sample window of 30ms to normalize across high-refresh sensors (60Hz-120Hz)
      if (timeDelta < 30) return

      const diffX = Math.abs(curX - lastX)
      const diffY = Math.abs(curY - lastY)
      const diffZ = Math.abs(curZ - lastZ)
      const speed = diffX + diffY + diffZ

      lastX = curX
      lastY = curY
      lastZ = curZ
      lastSampleTime = now

      // If more than 1.4 seconds passed since the last shake stroke, reset count
      if (lastShakeStrokeTime > 0 && now - lastShakeStrokeTime > 1400) {
        shakeCount = 0
      }

      // A deliberate shake stroke produces a rapid delta speed > 20
      if (speed > 20) {
        // Enforce at least 180ms debounce between counted shake strokes
        // (prevents a single continuous swing from triggering multiple counts)
        if (now - lastShakeStrokeTime > 180) {
          shakeCount++
          lastShakeStrokeTime = now

          // Trigger only when user shakes 6-7 times consecutively
          if (shakeCount >= 6) {
            setIsCamouflaged(true)
            shakeCount = 0
            lastShakeStrokeTime = 0
          }
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    if (typeof window !== 'undefined' && 'ondevicemotion' in window) {
      window.addEventListener('devicemotion', handleDeviceMotion)
    }

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      if (typeof window !== 'undefined' && 'ondevicemotion' in window) {
        window.removeEventListener('devicemotion', handleDeviceMotion)
      }
    }
  }, [isExcludedRoute, isCamouflaged])
  // Discreet-state side effects: mask the browser tab title and give a subtle,
  // silent tactile confirmation when the disguise engages. This keeps the real
  // app name out of the tab / recent-apps preview and confirms activation
  // without any sound or on-screen SOS text. Restores the title on exit.
  useEffect(() => {
    if (typeof document === 'undefined') return
    if (isCamouflaged) {
      if (prevTitleRef.current === null) prevTitleRef.current = document.title
      document.title = 'Creamy Tuscan Garlic Chicken Pasta - TasteCraft'
      try {
        if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
          navigator.vibrate(20)
        }
      } catch { /* Vibration API unavailable (e.g. iOS) — ignore */ }
    } else if (prevTitleRef.current !== null) {
      document.title = prevTitleRef.current
      prevTitleRef.current = null
    }
  }, [isCamouflaged])

  // Reverse / Browser Back / Phone Swipe-Back interception:
  // When disguise is open and user navigates back / reverse, close disguise and open /home
  useEffect(() => {
    if (typeof window === 'undefined') return

    if (isCamouflaged) {
      // Push history entry so phone back gesture or browser back button can be intercepted
      window.history.pushState({ haven_disguise: true }, '', window.location.href)

      const handlePopState = () => {
        setIsCamouflaged(false)
        router.push('/home')
      }

      window.addEventListener('popstate', handlePopState)
      return () => {
        window.removeEventListener('popstate', handlePopState)
      }
    }
  }, [isCamouflaged, router])

  const toggleIngredient = (index: number) => {
    setCheckedIngredients(prev => ({ ...prev, [index]: !prev[index] }))
  }

  // On excluded operational routes (responder login, authority dashboard, admin),
  // render children directly without any Quick Disguise button or disguise overlay.
  if (isExcludedRoute) {
    return <>{children}</>
  }

  return (
    <>
      {/* CSS keyframes for pulse animation */}
      <style>{`
        @keyframes havenPulseRing {
          0% { box-shadow: 0 0 0 0 rgba(190, 24, 93, 0.4), 0 4px 16px rgba(0,0,0,0.2); }
          70% { box-shadow: 0 0 0 8px rgba(190, 24, 93, 0), 0 4px 16px rgba(0,0,0,0.2); }
          100% { box-shadow: 0 0 0 0 rgba(190, 24, 93, 0), 0 4px 16px rgba(0,0,0,0.2); }
        }
        .haven-quick-disguise-btn {
          animation: havenPulseRing 2.4s ease-out infinite;
        }
        .haven-quick-disguise-btn:hover {
          animation: none;
          box-shadow: 0 0 0 3px rgba(190, 24, 93, 0.35), 0 6px 20px rgba(0,0,0,0.3) !important;
        }
      `}</style>

      {/* Real app content (kept alive in background for uninterrupted Voice SOS / GPS) */}
      <div style={{ display: isCamouflaged ? 'none' : 'block' }}>
        {children}

        {/* Discreet Floating Quick Escape Button — improved with pulse & safe-area */}
        <button
          onClick={() => setIsCamouflaged(true)}
          title="Tap to disguise this page"
          aria-label="Quick Disguise"
          className="haven-quick-disguise-btn"
          style={{
            position: 'fixed',
            bottom: 'max(18px, env(safe-area-inset-bottom))',
            left: 'max(18px, env(safe-area-inset-left))',
            zIndex: 99999,
            background: 'rgba(26, 10, 18, 0.88)',
            backdropFilter: 'blur(10px)',
            color: '#fdf2f8',
            border: '1px solid rgba(190, 24, 93, 0.3)',
            borderRadius: '30px',
            padding: isMobile ? '10px 16px' : '8px 14px',
            minHeight: 44,
            fontSize: '0.8rem',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.2s',
          }}
        >
          <span style={{ fontSize: '0.9rem' }}>⚡</span> Quick Disguise
        </button>
      </div>

      {/* ── CAMOUFLAGE OVERLAY ── */}
      {isCamouflaged && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 999999,
            background: '#ffffff',
            overflowY: 'auto',
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
            color: '#1f2937',
          }}
        >
          {/* Disguise Navigation */}
          <header style={{ borderBottom: '1px solid #e5e7eb', background: '#ffffff', position: 'sticky', top: 0, zIndex: 10 }}>
            <div style={{ maxWidth: 1000, margin: '0 auto', padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
                <div onClick={restoreToHome} title="Back to Home" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <ChefHat size={26} color="#e11d48" />
                  <span style={{ fontSize: '1.25rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.02em' }}>
                    TasteCraft
                  </span>
                </div>
                {/* Hide nav links on mobile */}
                {!isMobile && (
                  <nav style={{ display: 'flex', gap: 16, fontSize: '0.88rem', color: '#4b5563', fontWeight: 500 }}>
                    <span style={{ color: '#e11d48', fontWeight: 700, cursor: 'pointer' }}>Recipes</span>
                    <span style={{ cursor: 'pointer' }}>Quick Dinners</span>
                    <span style={{ cursor: 'pointer' }}>Baking</span>
                    <span style={{ cursor: 'pointer' }}>Meal Plans</span>
                  </nav>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <Search size={16} style={{ position: 'absolute', left: 10, color: '#9ca3af' }} />
                  <input
                    type="text"
                    placeholder="Search recipes..."
                    style={{
                      padding: '7px 12px 7px 32px',
                      borderRadius: 20,
                      border: '1px solid #d1d5db',
                      fontSize: '0.82rem',
                      outline: 'none',
                      width: isMobile ? '100%' : 220,
                      minWidth: 0,
                      maxWidth: '100%',
                    }}
                  />
                </div>
                {/* Restore control disguised as a recipe "save to favorites"
                    heart. The tooltip stays in-theme so it never hints at HAVEN. */}
                <button
                  onClick={() => setIsCamouflaged(false)}
                  title="Save to favorites"
                  aria-label="Save to favorites"
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#9ca3af',
                    padding: 4,
                    minHeight: 44,
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <Heart size={20} />
                </button>
              </div>
            </div>
          </header>

          {/* Recipe Content Page */}
          <main style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px 60px' }}>
            <div style={{ fontSize: '0.8rem', color: '#6b7280', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span onClick={restoreToHome} style={{ cursor: 'pointer', color: '#e11d48', fontWeight: 700 }}>
                  ← Back to Home
                </span>
                <span style={{ color: '#9ca3af' }}>•</span>
                <span onClick={restoreToHome} style={{ cursor: 'pointer', textDecoration: 'underline' }}>
                  Home
                </span>
                <span>&gt;</span>
                <span>Dinner</span>
                <span>&gt;</span>
                <span>Italian</span>
                <span>&gt;</span>
                <span style={{ color: '#111827', fontWeight: 600 }}>Pasta</span>
              </div>
            </div>

            <h1 style={{ fontSize: 'clamp(1.8rem, 4vw, 2.4rem)', fontWeight: 800, color: '#111827', lineHeight: 1.2, marginBottom: 12 }}>
              Creamy Tuscan Garlic Chicken Pasta
            </h1>

            <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: '0.84rem', color: '#6b7280', marginBottom: 20, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#f59e0b', fontWeight: 700 }}>
                <Star size={16} fill="#f59e0b" />
                <span>4.9</span>
                <span style={{ color: '#6b7280', fontWeight: 400 }}>(1,428 reviews)</span>
              </div>
              <div>• Prep: <strong>15 mins</strong></div>
              <div>• Cook: <strong>20 mins</strong></div>
              <div>• Servings: <strong>4</strong></div>
            </div>

            {/* Hero Food Image */}
            <div style={{ borderRadius: 16, overflow: 'hidden', background: '#f3f4f6', height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 24, position: 'relative' }}>
              <img
                src="/images/pasta.jpg"
                alt="Creamy Tuscan Garlic Chicken Pasta"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={(e) => {
                  // Fallback container if offline
                  e.currentTarget.src = 'https://images.unsplash.com/photo-1608897013039-887f21d8c804?w=1000&auto=format&fit=crop&q=80'
                }}
              />
              <div style={{ position: 'absolute', bottom: 12, right: 12, background: 'rgba(0,0,0,0.6)', color: 'white', padding: '4px 10px', borderRadius: 20, fontSize: '0.75rem' }}>
                📸 Verified Reader Photo
              </div>
            </div>

            {/* Author bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #e5e7eb', marginBottom: 24, flexWrap: 'wrap', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 40, height: 40, borderRadius: '50%', background: '#fee2e2', color: '#e11d48', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.9rem' }}>
                  EL
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.88rem' }}>Chef Elena Laurent</div>
                  <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>Published Aug 14, 2026 • Updated today</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button style={{ background: '#f3f4f6', border: 'none', padding: '6px 12px', borderRadius: 20, fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Share2 size={14} /> Share
                </button>
                <button style={{ background: '#fee2e2', color: '#e11d48', border: 'none', padding: '6px 14px', borderRadius: 20, fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer' }}>
                  ★ Save Recipe
                </button>
              </div>
            </div>

            {/* Ingredients Checklist */}
            <div style={{ background: '#f9fafb', borderRadius: 16, padding: '20px 24px', border: '1px solid #e5e7eb', marginBottom: 28 }}>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: 14, color: '#111827' }}>
                Ingredients Checklist
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
                {[
                  '2 large chicken breasts, sliced into cutlets',
                  '8 oz fettuccine or penne pasta',
                  '2 tbsp extra virgin olive oil',
                  '4 cloves fresh garlic, minced',
                  '1 cup heavy whipping cream',
                  '1/2 cup grated Parmigiano-Reggiano',
                  '2 cups fresh baby spinach leaves',
                  '1 cup sun-dried tomatoes in oil, drained',
                  '1/2 tsp dried Italian herbs & oregano',
                  'Freshly cracked black pepper and kosher salt',
                ].map((item, idx) => (
                  <label
                    key={idx}
                    onClick={() => toggleIngredient(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      fontSize: '0.86rem',
                      color: checkedIngredients[idx] ? '#9ca3af' : '#374151',
                      textDecoration: checkedIngredients[idx] ? 'line-through' : 'none',
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={!!checkedIngredients[idx]}
                      onChange={() => {}}
                      style={{ cursor: 'pointer', accentColor: '#e11d48' }}
                    />
                    <span>{item}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Step-by-Step Instructions */}
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: 14, color: '#111827' }}>
                Step-by-Step Instructions
              </h2>
              <ol style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 14, lineHeight: 1.6, fontSize: '0.9rem', color: '#374151' }}>
                <li>
                  <strong>Cook the pasta:</strong> Bring a large pot of salted water to a rolling boil. Cook the fettuccine until al dente (about 8–10 minutes). Drain and reserve 1/2 cup of pasta water.
                </li>
                <li>
                  <strong>Sear the chicken:</strong> Heat olive oil in a large skillet over medium-high heat. Season chicken with salt, pepper, and Italian herbs. Cook 5 minutes per side until golden brown and cooked through. Transfer to a cutting board.
                </li>
                <li>
                  <strong>Sauté garlic &amp; sun-dried tomatoes:</strong> In the same skillet, add minced garlic and sun-dried tomatoes. Sauté for 1 minute until fragrant.
                </li>
                <li>
                  <strong>Make the cream sauce:</strong> Pour in heavy cream and chicken broth. Bring to a gentle simmer, then stir in grated parmesan cheese until smooth and velvety.
                </li>
                <li>
                  <strong>Toss and serve:</strong> Fold in fresh baby spinach until just wilted. Toss in the drained pasta and sliced chicken. Serve hot with extra parmesan!
                </li>
              </ol>
            </div>

            {/* Related Recipes — More convincing disguise content */}
            <div style={{ marginTop: 40 }}>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#111827', marginBottom: 16 }}>
                You Might Also Love
              </h2>
              <div style={{ display: 'flex', gap: 16, overflowX: 'auto', paddingBottom: 8 }}>
                {[
                  { title: 'Lemon Herb Roasted Salmon', time: '32 mins', rating: '4.8', gradient: 'linear-gradient(135deg, #fde68a, #fb923c)' },
                  { title: 'Classic Beef Stroganoff', time: '45 mins', rating: '4.7', gradient: 'linear-gradient(135deg, #c4b5fd, #7c3aed)' },
                  { title: 'Thai Basil Fried Rice', time: '20 mins', rating: '4.9', gradient: 'linear-gradient(135deg, #6ee7b7, #059669)' },
                ].map((recipe, i) => (
                  <div key={i} style={{ minWidth: 180, background: '#f9fafb', borderRadius: 12, border: '1px solid #e5e7eb', overflow: 'hidden', cursor: 'pointer', flexShrink: 0 }}>
                    <div style={{ height: 110, background: recipe.gradient }} />
                    <div style={{ padding: '10px 12px' }}>
                      <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#111827', lineHeight: 1.3, marginBottom: 6 }}>{recipe.title}</div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: '#6b7280' }}>
                        <span>⏱ {recipe.time}</span>
                        <span style={{ color: '#f59e0b', fontWeight: 700 }}>⭐ {recipe.rating}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Neutral publisher footer. The restore affordance below is left
                unlabeled on purpose — no exit method or code is ever printed. */}
            <footer style={{ marginTop: 40, paddingTop: 20, borderTop: '1px solid #e5e7eb', textAlign: 'center', fontSize: '0.75rem', color: '#9ca3af' }}>
              <p>
                © 2026 TasteCraft Publishing Group. All rights reserved. •{' '}
                <span
                  onClick={restoreToHome}
                  style={{ cursor: 'pointer', textDecoration: 'underline' }}
                  title="Privacy Policy"
                >
                  Privacy Policy &amp; Nutrition Disclaimer
                </span>
              </p>
            </footer>
          </main>
        </div>
      )}
    </>
  )
}
