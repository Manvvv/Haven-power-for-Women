'use client'
import React, { useState, useEffect, useRef } from 'react'
import { Search, Heart, Star, Clock, ChefHat, ShoppingBag, Eye, X, BookOpen, Share2 } from 'lucide-react'

export default function QuickEscape({ children }: { children: React.ReactNode }) {
  const [isCamouflaged, setIsCamouflaged] = useState(false)
  const [disguiseTheme, setDisguiseTheme] = useState<'recipe' | 'shopping'>('recipe')
  const [typedBuffer, setTypedBuffer] = useState('')
  const [checkedIngredients, setCheckedIngredients] = useState<Record<number, boolean>>({})
  const [showExitHint, setShowExitHint] = useState(false)
  
  const lastEscTimeRef = useRef<number>(0)
  const SECRET_PIN = '1810'

  // Double-tap Escape key or type secret PIN '1810' to toggle
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check double-tap Escape key
      if (e.key === 'Escape') {
        const now = Date.now()
        if (now - lastEscTimeRef.current < 600) {
          setIsCamouflaged(prev => !prev)
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
            setIsCamouflaged(false)
            return ''
          }
          return next
        })
      }
    }

    // Shake gesture detection for mobile devices
    let lastX = 0, lastY = 0, lastZ = 0, lastShake = 0
    const handleDeviceMotion = (e: DeviceMotionEvent) => {
      const acc = e.accelerationIncludingGravity
      if (!acc) return
      const curTime = Date.now()
      if (curTime - lastShake > 1000) {
        const diffX = Math.abs((acc.x || 0) - lastX)
        const diffY = Math.abs((acc.y || 0) - lastY)
        const diffZ = Math.abs((acc.z || 0) - lastZ)
        if (diffX + diffY + diffZ > 28) {
          setIsCamouflaged(true)
          lastShake = curTime
        }
        lastX = acc.x || 0
        lastY = acc.y || 0
        lastZ = acc.z || 0
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
  }, [])

  const toggleIngredient = (index: number) => {
    setCheckedIngredients(prev => ({ ...prev, [index]: !prev[index] }))
  }

  return (
    <>
      {/* Real app content (kept alive in background for uninterrupted Voice SOS / GPS) */}
      <div style={{ display: isCamouflaged ? 'none' : 'block' }}>
        {children}

        {/* Discreet Floating Quick Escape Button */}
        <button
          onClick={() => setIsCamouflaged(true)}
          title="Quick Disguise"
          aria-label="Quick Disguise"
          style={{
            position: 'fixed',
            bottom: '18px',
            left: '18px',
            zIndex: 99999,
            background: 'rgba(26, 10, 18, 0.85)',
            backdropFilter: 'blur(10px)',
            color: '#fdf2f8',
            border: '1px solid rgba(190, 24, 93, 0.3)',
            borderRadius: '30px',
            padding: '8px 14px',
            fontSize: '0.74rem',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
            transition: 'all 0.2s',
          }}
        >
          <span style={{ fontSize: '0.85rem' }}>⚡</span> Quick Disguise
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
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <ChefHat size={26} color="#e11d48" />
                  <span style={{ fontSize: '1.25rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.02em' }}>
                    TasteCraft
                  </span>
                </div>
                <nav style={{ display: 'flex', gap: 16, fontSize: '0.88rem', color: '#4b5563', fontWeight: 500 }}>
                  <span style={{ color: '#e11d48', fontWeight: 700, cursor: 'pointer' }}>Recipes</span>
                  <span style={{ cursor: 'pointer' }}>Quick Dinners</span>
                  <span style={{ cursor: 'pointer' }}>Baking</span>
                  <span style={{ cursor: 'pointer' }}>Meal Plans</span>
                </nav>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <Search size={16} style={{ position: 'absolute', left: 10, color: '#9ca3af' }} />
                  <input
                    type="text"
                    placeholder="Search 15,000+ recipes..."
                    style={{
                      padding: '7px 12px 7px 32px',
                      borderRadius: 20,
                      border: '1px solid #d1d5db',
                      fontSize: '0.82rem',
                      outline: 'none',
                      width: 220,
                    }}
                  />
                </div>
                {/* Secret Unlock Logo Icon */}
                <button
                  onClick={() => setIsCamouflaged(false)}
                  title="Secret Restore"
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#9ca3af',
                    padding: 4,
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
              Home &gt; Dinner &gt; Italian &gt; Pasta
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
                src="https://images.unsplash.com/photo-1621996346565-e3d5d6281696?w=1000&auto=format&fit=crop&q=80"
                alt="Creamy Tuscan Garlic Chicken Pasta"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={(e) => {
                  // Fallback container if offline
                  e.currentTarget.style.display = 'none'
                }}
              />
              <div style={{ position: 'absolute', bottom: 12, right: 12, background: 'rgba(0,0,0,0.6)', color: 'white', padding: '4px 10px', borderRadius: 20, fontSize: '0.75rem' }}>
                📸 Verified Reader Photo
              </div>
            </div>

            {/* Author bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #e5e7eb', marginBottom: 24 }}>
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
                  <strong>Sauté garlic & sun-dried tomatoes:</strong> In the same skillet, add minced garlic and sun-dried tomatoes. Sauté for 1 minute until fragrant.
                </li>
                <li>
                  <strong>Make the cream sauce:</strong> Pour in heavy cream and chicken broth. Bring to a gentle simmer, then stir in grated parmesan cheese until smooth and velvety.
                </li>
                <li>
                  <strong>Toss and serve:</strong> Fold in fresh baby spinach until just wilted. Toss in the drained pasta and sliced chicken. Serve hot with extra parmesan!
                </li>
              </ol>
            </div>

            {/* Secret Footer (Tap 3 times or type 1810 to return) */}
            <footer style={{ marginTop: 40, paddingTop: 20, borderTop: '1px solid #e5e7eb', textAlign: 'center', fontSize: '0.75rem', color: '#9ca3af' }}>
              <p>
                © 2026 TasteCraft Publishing Group. All rights reserved. •{' '}
                <span
                  onClick={() => setIsCamouflaged(false)}
                  style={{ cursor: 'pointer', textDecoration: 'underline' }}
                  title="Click to restore HAVEN"
                >
                  Privacy Policy & Nutrition Disclaimer
                </span>
              </p>
              <p style={{ marginTop: 4, fontSize: '0.7rem' }}>
                Tip: Enter PIN <strong>1810</strong> or double-tap <strong>ESC</strong> to exit camouflage.
              </p>
            </footer>
          </main>
        </div>
      )}
    </>
  )
}
