'use client'
import { useState, useRef, useEffect, useCallback } from 'react'
import { useOfflineStatus } from '@/hooks/useOfflineStatus'
import { saveSecure, loadSecure, removeSecure } from '@/lib/secureLocal'

interface PanicButtonProps {
  size?: 'small' | 'large'
}

export default function PanicButton({ size = 'large' }: PanicButtonProps) {
  const [holding, setHolding] = useState(false)
  const [progress, setProgress] = useState(0)
  const [fired, setFired] = useState(false)
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'getting' | 'got' | 'failed'>('idle')
  const [location, setLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [showSetup, setShowSetup] = useState(false)
  const [contactNumber, setContactNumber] = useState('')
  const [savedContact, setSavedContact] = useState('')
  const [contactName, setContactName] = useState('')
  const [savedName, setSavedName] = useState('')
  const [showConfirm, setShowConfirm] = useState(false)

  const holdTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const progressRef = useRef(0)
  const HOLD_MS = 3000

  // Offline-first: record the panic SOS to the backend, queuing it in IndexedDB
  // first so it is never lost and is retried automatically when back online.
  const { submitSOS, isOnline } = useOfflineStatus()

  // Load the trusted contact from ENCRYPTED at-rest storage. One-time migration:
  // if a legacy plaintext localStorage contact exists, move it into the encrypted
  // store and then delete the plaintext copy so it never lingers readable.
  const STORE_CONTACT = 'haven_panic_contact'
  const STORE_NAME = 'haven_panic_name'
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const legacyNum = localStorage.getItem(STORE_CONTACT)
        const legacyName = localStorage.getItem(STORE_NAME)
        if (legacyNum !== null || legacyName !== null) {
          if (legacyNum) await saveSecure(STORE_CONTACT, legacyNum)
          if (legacyName) await saveSecure(STORE_NAME, legacyName)
          // Purge plaintext copies regardless, so nothing readable remains.
          localStorage.removeItem(STORE_CONTACT)
          localStorage.removeItem(STORE_NAME)
        }
        const num = (await loadSecure(STORE_CONTACT)) || ''
        const name = (await loadSecure(STORE_NAME)) || ''
        if (cancelled) return
        setSavedContact(num)
        setSavedName(name)
        setContactNumber(num)
        setContactName(name)
      } catch {
        /* storage unavailable — panic button still works without a saved contact */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const getGPS = useCallback((): Promise<{ lat: number; lng: number } | null> => {
    return new Promise(resolve => {
      if (!navigator.geolocation) { resolve(null); return }
      setGpsStatus('getting')
      navigator.geolocation.getCurrentPosition(
        pos => {
          const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }
          setLocation(coords)
          setGpsStatus('got')
          resolve(coords)
        },
        () => { setGpsStatus('failed'); resolve(null) },
        { timeout: 8000, enableHighAccuracy: true }
      )
    })
  }, [])

  const firePanic = useCallback(async () => {
    setFired(true)
    setHolding(false)
    setProgress(0)
    progressRef.current = 0

    // Subtle, silent tactile confirmation that the SOS fired — no extra sound or
    // alarm. No-op where the Vibration API is unavailable (e.g. iOS Safari).
    try {
      if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
        navigator.vibrate([40, 60, 40])
      }
    } catch { /* vibration unavailable — ignore */ }

    const coords = await getGPS()

    const mapsLink = coords
      ? `https://maps.google.com/?q=${coords.lat},${coords.lng}`
      : null

    const msg = coords
      ? `🚨 EMERGENCY ALERT from Haven 🚨\n\nI am in danger and need immediate help!\n\n📍 My location: ${mapsLink}\n\nPlease call me or contact authorities immediately.\n\nSent via Haven Safety App`
      : `🚨 EMERGENCY ALERT from Haven 🚨\n\nI am in danger and need immediate help!\n\n⚠️ Could not get GPS location.\n\nPlease call me or contact authorities immediately.\n\nSent via Haven Safety App`

    // Record the panic SOS to the backend through the offline-first queue.
    // If offline, it is stored locally and delivered automatically on reconnect.
    try {
      await submitSOS({
        type: 'panic',
        endpoint: '/save-extracted-data',
        message: 'Panic button activated — user reported immediate danger.',
        latitude: coords?.lat ?? null,
        longitude: coords?.lng ?? null,
        payload: {
          decoded_text: 'PANIC BUTTON ACTIVATED — user reported being in immediate danger.',
          severity: 'critical',
          immediate_danger: true,
          trigger_type: 'panic',
          location: coords ? `${coords.lat},${coords.lng}` : '',
          needs: ['immediate_assistance'],
          summary: 'Panic button held for 3s. Treat as high-priority.',
        },
      })
    } catch { /* queued locally even if this throws */ }

    // Copy location to clipboard
    if (coords) {
      try {
        await navigator.clipboard.writeText(
          `My location: ${mapsLink}\nCoords: ${coords.lat}, ${coords.lng}`
        )
      } catch { /* silent */ }
    }

    // Open WhatsApp
    const encodedMsg = encodeURIComponent(msg)
    let digits = savedContact.replace(/\D/g, '')
    if (digits.length === 10 && /^[6-9]/.test(digits)) {
      digits = '91' + digits
    } else if (digits.length === 11 && digits.startsWith('0')) {
      digits = '91' + digits.slice(1)
    }

    const waUrl = digits
      ? `https://api.whatsapp.com/send?phone=${digits}&text=${encodedMsg}`
      : `https://api.whatsapp.com/send?text=${encodedMsg}`

    const a = document.createElement('a')
a.href = waUrl
a.target = '_blank'
a.rel = 'noreferrer'
document.body.appendChild(a)
a.click()
document.body.removeChild(a)
    setShowConfirm(true)
  }, [getGPS, savedContact])

  function startHold() {
    if (fired) return
    setHolding(true)
    progressRef.current = 0
    const interval = 50
    holdTimer.current = setInterval(() => {
      progressRef.current += interval
      const pct = Math.min((progressRef.current / HOLD_MS) * 100, 100)
      setProgress(pct)
      if (progressRef.current >= HOLD_MS) {
        clearInterval(holdTimer.current!)
        firePanic()
      }
    }, interval)
  }

  function cancelHold() {
    if (holdTimer.current) clearInterval(holdTimer.current)
    setHolding(false)
    setProgress(0)
    progressRef.current = 0
  }

  async function saveContact() {
    // Persist ENCRYPTED at rest (AES-256-GCM, non-extractable device key). If a
    // field is cleared, remove it rather than storing an empty encrypted blob.
    try {
      if (contactNumber) await saveSecure(STORE_CONTACT, contactNumber)
      else await removeSecure(STORE_CONTACT)
      if (contactName) await saveSecure(STORE_NAME, contactName)
      else await removeSecure(STORE_NAME)
    } catch {
      /* ignore storage errors — the in-memory value is still usable this session */
    }
    setSavedContact(contactNumber)
    setSavedName(contactName)
    setShowSetup(false)
  }

  function reset() {
    setFired(false)
    setShowConfirm(false)
    setGpsStatus('idle')
    setLocation(null)
    setProgress(0)
  }

  const openSMSApp = (phoneNum: string, textMsg: string) => {
    const cleanDigits = phoneNum ? phoneNum.replace(/\D/g, '') : '112'
    const smsUrl = `sms:${cleanDigits}?body=${encodeURIComponent(textMsg)}`
    window.location.href = smsUrl
  }

  const lastMsg = location
    ? `🚨 HAVEN EMERGENCY ALERT!\nI am in danger and need immediate help.\nMy Live Location: https://maps.google.com/?q=${location.lat},${location.lng}\nTime: ${new Date().toLocaleTimeString()}`
    : `🚨 HAVEN EMERGENCY ALERT!\nI am in danger and need immediate help.\nTime: ${new Date().toLocaleTimeString()}`

  const isLarge = size === 'large'

  return (
    <>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {!holding && !fired && (
            <div style={{
              position: 'absolute',
              width: isLarge ? 140 : 100,
              height: isLarge ? 140 : 100,
              borderRadius: '50%',
              border: '3px solid rgba(220,38,38,0.3)',
              animation: 'panicPulse 2s ease-in-out infinite',
              pointerEvents: 'none',
            }} />
          )}

          {holding && (
            <svg
              style={{ position: 'absolute', transform: 'rotate(-90deg)', pointerEvents: 'none' }}
              width={isLarge ? 140 : 100}
              height={isLarge ? 140 : 100}
            >
              <circle
                cx={isLarge ? 70 : 50}
                cy={isLarge ? 70 : 50}
                r={isLarge ? 65 : 46}
                fill="none"
                stroke="rgba(220,38,38,0.15)"
                strokeWidth="6"
              />
              <circle
                cx={isLarge ? 70 : 50}
                cy={isLarge ? 70 : 50}
                r={isLarge ? 65 : 46}
                fill="none"
                stroke="#dc2626"
                strokeWidth="6"
                strokeDasharray={`${2 * Math.PI * (isLarge ? 65 : 46)}`}
                strokeDashoffset={`${2 * Math.PI * (isLarge ? 65 : 46) * (1 - progress / 100)}`}
                strokeLinecap="round"
                style={{ transition: 'stroke-dashoffset 0.05s linear' }}
              />
            </svg>
          )}

          <button
            onMouseDown={startHold}
            onMouseUp={cancelHold}
            onMouseLeave={cancelHold}
            onTouchStart={e => { e.preventDefault(); startHold() }}
            onTouchEnd={e => { e.preventDefault(); cancelHold() }}
            disabled={fired}
            style={{
              width: isLarge ? 120 : 84,
              height: isLarge ? 120 : 84,
              borderRadius: '50%',
              background: fired
                ? 'linear-gradient(135deg, #15803d, #166534)'
                : holding
                  ? 'linear-gradient(135deg, #b91c1c, #991b1b)'
                  : 'linear-gradient(135deg, #dc2626, #b91c1c)',
              border: 'none',
              cursor: fired ? 'default' : 'pointer',
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              boxShadow: holding
                ? '0 0 0 8px rgba(220,38,38,0.2), 0 8px 32px rgba(220,38,38,0.5)'
                : '0 4px 20px rgba(220,38,38,0.4)',
              transition: 'all 0.2s ease',
              transform: holding ? 'scale(0.95)' : 'scale(1)',
              userSelect: 'none',
              WebkitUserSelect: 'none',
              touchAction: 'none',
              zIndex: 1,
            }}
          >
            <span style={{ fontSize: isLarge ? '2rem' : '1.5rem', lineHeight: 1 }}>
              {fired ? '✓' : '🆘'}
            </span>
            <span style={{ color: 'white', fontWeight: 800, fontSize: isLarge ? '0.75rem' : '0.62rem', marginTop: 4, letterSpacing: 1, textTransform: 'uppercase' }}>
              {fired ? 'SENT' : holding ? `${Math.ceil((HOLD_MS - progressRef.current) / 1000)}s` : 'PANIC'}
            </span>
          </button>
        </div>

        <div style={{ textAlign: 'center' }}>
          {!holding && !fired && (
            <p style={{ fontSize: 'clamp(0.72rem, 2vw, 0.78rem)', color: '#8b6b7d', lineHeight: 1.4 }}>
              {isLarge ? 'Hold 3 seconds to send emergency alert' : 'Hold 3s for SOS'}
            </p>
          )}
          {holding && (
            <p style={{ fontSize: 'clamp(0.72rem, 2vw, 0.78rem)', color: '#dc2626', fontWeight: 700, lineHeight: 1.4 }}>
              Keep holding... {Math.ceil((HOLD_MS - progressRef.current) / 1000)}s
            </p>
          )}
          {fired && gpsStatus === 'getting' && (
            <p style={{ fontSize: '0.78rem', color: '#8b6b7d' }}>📍 Getting your location...</p>
          )}
          {fired && gpsStatus === 'got' && (
            <p style={{ fontSize: '0.78rem', color: '#15803d', fontWeight: 600 }}>✓ Location copied + WhatsApp opened</p>
          )}
          {fired && gpsStatus === 'failed' && (
            <p style={{ fontSize: '0.78rem', color: '#dc2626' }}>⚠️ GPS unavailable — WhatsApp opened without location</p>
          )}
        </div>

        {isLarge && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: '0.75rem', color: '#8b6b7d' }}>
              {savedContact ? `→ ${savedName || savedContact}` : 'No contact set'}
            </span>
            <button
              onClick={() => setShowSetup(true)}
              style={{ fontSize: '0.72rem', color: '#be185d', background: 'none', border: '1px solid rgba(190,24,93,0.2)', borderRadius: 20, padding: '3px 10px', cursor: 'pointer' }}
            >
              {savedContact ? 'Change' : '+ Add Contact'}
            </button>
          </div>
        )}

        {fired && (
          <button onClick={reset} style={{ fontSize: '0.75rem', color: '#8b6b7d', background: 'none', border: '1px solid #e2d6e0', borderRadius: 20, padding: '5px 14px', cursor: 'pointer', marginTop: 4 }}>
            Reset
          </button>
        )}
      </div>

      {showConfirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 32, maxWidth: 380, width: '100%', textAlign: 'center' }}>
            <div style={{ fontSize: '3rem', marginBottom: 12 }}>✅</div>
            <h3 style={{ fontFamily: 'Georgia', fontSize: '1.2rem', color: '#15803d', marginBottom: 10 }}>Alert Sent!</h3>
            <p style={{ fontSize: '0.85rem', color: '#8b6b7d', lineHeight: 1.6, marginBottom: 8 }}>
              WhatsApp opened with your emergency message.
              {location && <><br /><strong style={{ color: '#15803d' }}>📍 Location copied to clipboard!</strong></>}
              <br />
              {isOnline ? (
                <span style={{ color: '#15803d' }}>Your alert is being delivered to Haven authorities.</span>
              ) : (
                <span style={{ color: '#c2410c' }}>
                  You are offline — your alert is saved and will be sent to authorities automatically when you reconnect.
                </span>
              )}
            </p>
            {location && (
              <div style={{ background: '#f0fdf4', borderRadius: 10, padding: 10, marginBottom: 16, fontSize: '0.75rem', color: '#15803d' }}>
                {location.lat.toFixed(5)}, {location.lng.toFixed(5)}<br />
                <a href={`https://maps.google.com/?q=${location.lat},${location.lng}`} target="_blank" rel="noreferrer" style={{ color: '#15803d', fontWeight: 700 }}>
                  Open in Google Maps ↗
                </a>
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <button onClick={() => openSMSApp(savedContact, lastMsg)} style={{ background: '#2563eb', color: 'white', padding: '12px', borderRadius: 12, border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
                Send Offline SMS Alert
              </button>
              <div style={{ display: 'flex', gap: 10 }}>
                <a href="tel:112" style={{ flex: 1, background: '#dc2626', color: 'white', padding: '12px', borderRadius: 12, textDecoration: 'none', fontWeight: 700, fontSize: '0.85rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                  📞 Call 112
                </a>
                <button onClick={() => setShowConfirm(false)} style={{ flex: 1, background: '#f3f4f6', color: '#6b7280', padding: '12px', borderRadius: 12, border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showSetup && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: 'white', borderRadius: 20, padding: 28, maxWidth: 380, width: '100%' }}>
            <h3 style={{ fontFamily: 'Georgia', fontSize: '1.1rem', color: '#1a0a12', marginBottom: 6 }}>Trusted Emergency Contact</h3>
            <p style={{ fontSize: '0.8rem', color: '#8b6b7d', marginBottom: 20, lineHeight: 1.5 }}>
              In a panic, Haven will send a WhatsApp alert to this person with your GPS location.
            </p>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#1a0a12', display: 'block', marginBottom: 5 }}>Contact Name</label>
            <input
              value={contactName}
              onChange={e => setContactName(e.target.value)}
              placeholder="e.g. Mom, Sister, Friend"
              style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '2px solid rgba(190,24,93,0.2)', fontSize: '0.9rem', outline: 'none', marginBottom: 12, boxSizing: 'border-box' }}
            />
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#1a0a12', display: 'block', marginBottom: 5 }}>
              WhatsApp Number <span style={{ color: '#8b6b7d', fontWeight: 400 }}>(with country code)</span>
            </label>
            <input
              value={contactNumber}
              onChange={e => setContactNumber(e.target.value)}
              placeholder="e.g. 919876543210"
              type="tel"
              style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '2px solid rgba(190,24,93,0.2)', fontSize: '0.9rem', outline: 'none', marginBottom: 6, boxSizing: 'border-box' }}
            />
            <p style={{ fontSize: '0.72rem', color: '#8b6b7d', marginBottom: 20 }}>
              India format: 91 + 10-digit number (e.g. 919876543210)
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={saveContact} style={{ flex: 1, background: 'linear-gradient(135deg,#be185d,#9d174d)', color: 'white', padding: '12px', borderRadius: 12, border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.88rem' }}>
                Save Contact
              </button>
              <button onClick={() => setShowSetup(false)} style={{ flex: 1, background: '#f3f4f6', color: '#6b7280', padding: '12px', borderRadius: 12, border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CSS animations */}
      <style>{`
        @keyframes panicPulse {
          0%, 100% { transform: scale(1); opacity: 0.6; }
          50% { transform: scale(1.15); opacity: 0.2; }
        }
      `}</style>
    </>
  )
}
