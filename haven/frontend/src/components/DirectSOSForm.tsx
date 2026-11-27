'use client'

import React, { useState, useRef, useCallback } from 'react'
import { MapPin, AlertTriangle, CheckCircle2, Loader2, ShieldAlert, Navigation, Phone } from 'lucide-react'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'
import { useLang } from '@/components/LanguageContext'

export interface SubmittedIncident {
  case_id: string
  status: string
  category: string
  severity: string
  location: string
  location_source: string
  created_at: string
  duplicate?: boolean
  contact_notifications?: Array<{ contact_id: string; name: string; status: string }>
}

interface CapturedLocation {
  latitude: number
  longitude: number
  accuracy: number | null
  capturedAt: string
}

const CATEGORIES = [
  { id: 'immediate_danger', labelEn: 'Immediate Physical Danger', labelHi: 'तत्काल शारीरिक खतरा' },
  { id: 'stalking', labelEn: 'Stalking / Being Followed', labelHi: 'पीछा किया जाना / स्टॉकिंग' },
  { id: 'domestic_violence', labelEn: 'Domestic Violence / Confinement', labelHi: 'घरेलू हिंसा / बंधक स्थिति' },
  { id: 'harassment', labelEn: 'Harassment / Threat', labelHi: 'उत्पीड़न / धमकी' },
  { id: 'unsafe_transit', labelEn: 'Unsafe Transit / Stranded', labelHi: 'असुरक्षित यात्रा / फंसी हुई स्थिति' },
  { id: 'medical', labelEn: 'Medical Emergency', labelHi: 'चिकित्सीय आपातकाल' },
  { id: 'other', labelEn: 'Other Safety Concern', labelHi: 'अन्य सुरक्षा चिंता' },
]

function makeIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `sos-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export default function DirectSOSForm({
  onSubmitted,
  trustedContactCount = 0,
}: {
  onSubmitted?: (incident: SubmittedIncident) => void
  trustedContactCount?: number
}) {
  const { lang } = useLang()
  const isHi = lang === 'hi'

  const [category, setCategory] = useState('immediate_danger')
  const [description, setDescription] = useState('')
  const [immediateDanger, setImmediateDanger] = useState(true)
  const [gpsLoading, setGpsLoading] = useState(false)
  const [gpsError, setGpsError] = useState('')
  const [capturedLoc, setCapturedLoc] = useState<CapturedLocation | null>(null)
  const [useManualLoc, setUseManualLoc] = useState(false)
  const [manualLocation, setManualLocation] = useState('')
  const [notifyContacts, setNotifyContacts] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [submitted, setSubmitted] = useState<SubmittedIncident | null>(null)

  // Stable idempotency key per incident draft — prevents duplicate DB cases on retries
  const idempotencyRef = useRef<string>(makeIdempotencyKey())
  const inFlightRef = useRef(false)

  const isStale = capturedLoc
    ? (Date.now() - Date.parse(capturedLoc.capturedAt)) > 300_000
    : false

  const captureGPS = useCallback(() => {
    setGpsError('')
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGpsError(isHi
        ? 'इस ब्राउज़र में GPS उपलब्ध नहीं है। कृपया नीचे मैन्युअल स्थान दर्ज करें।'
        : 'Geolocation is unavailable in this browser. Please enter your location manually below.')
      setUseManualLoc(true)
      return
    }
    setGpsLoading(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const next: CapturedLocation = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: Number.isFinite(pos.coords.accuracy) ? Math.round(pos.coords.accuracy) : null,
          capturedAt: new Date(pos.timestamp || Date.now()).toISOString(),
        }
        setCapturedLoc(next)
        setUseManualLoc(false)
        setGpsLoading(false)
      },
      (err) => {
        setGpsLoading(false)
        setUseManualLoc(true)
        if (err.code === err.PERMISSION_DENIED) {
          setGpsError(isHi
            ? 'लोकेशन अनुमति अस्वीकार की गई। आप नीचे मैन्युअल रूप से स्थान लिखकर SOS भेज सकते हैं।'
            : 'Location permission was denied. You can still enter your location manually below and submit.')
        } else if (err.code === err.TIMEOUT) {
          setGpsError(isHi
            ? 'GPS सिग्नल समय समाप्त हो गया। कृपया पुनः प्रयास करें या मैन्युअल स्थान दर्ज करें।'
            : 'GPS timed out waiting for a fix. Retry or enter your location manually below.')
        } else {
          setGpsError(isHi
            ? 'वर्तमान GPS स्थान प्राप्त नहीं हो सका। कृपया मैन्युअल स्थान दर्ज करें।'
            : 'Could not read your GPS coordinates. Please enter your location manually below.')
        }
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 10_000 }
    )
  }, [isHi])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (inFlightRef.current || submitting) return

    setSubmitError('')
    if (!category) {
      setSubmitError(isHi ? 'कृपया आपातकाल की श्रेणी चुनें।' : 'Please select an emergency category.')
      return
    }
    if (useManualLoc && !manualLocation.trim() && !capturedLoc) {
      setSubmitError(isHi ? 'कृपया मैन्युअल स्थान या लैंडमार्क दर्ज करें।' : 'Please enter a manual location or landmark, or capture GPS.')
      return
    }

    const locationSource: 'gps' | 'manual' | 'unavailable' =
      capturedLoc && !useManualLoc
        ? 'gps'
        : manualLocation.trim()
          ? 'manual'
          : 'unavailable'

    inFlightRef.current = true
    setSubmitting(true)
    try {
      const res = await secureFetch('/sos/report', {
        method: 'POST',
        body: JSON.stringify({
          category,
          description: description.trim(),
          immediate_danger: immediateDanger,
          latitude: locationSource === 'gps' ? capturedLoc?.latitude ?? null : null,
          longitude: locationSource === 'gps' ? capturedLoc?.longitude ?? null : null,
          location_accuracy: locationSource === 'gps' ? capturedLoc?.accuracy ?? null : null,
          location_captured_at: locationSource === 'gps' ? capturedLoc?.capturedAt ?? null : null,
          location_source: locationSource,
          manual_location: manualLocation.trim(),
          idempotency_key: idempotencyRef.current,
          notify_contacts: notifyContacts,
          trigger_type: 'website_sos',
        }),
      })

      const data = await res.json().catch(() => ({} as any))
      if (!res.ok) {
        const detail = typeof data?.detail === 'string'
          ? data.detail
          : (isHi ? 'सर्वर त्रुटि। कृपया पुनः प्रयास करें या 112 पर कॉल करें।' : `Server error (${res.status}). Please retry or call 112 immediately.`)
        setSubmitError(detail)
        return
      }

      const result: SubmittedIncident = {
        case_id: data.case_id,
        status: data.status || 'RECEIVED',
        category: data.category || category,
        severity: data.severity || (immediateDanger ? 'critical' : 'high'),
        location: data.location || manualLocation.trim() || 'Location unavailable',
        location_source: data.location_source || locationSource,
        created_at: data.created_at || new Date().toISOString(),
        duplicate: !!data.duplicate,
        contact_notifications: data.contact_notifications || [],
      }
      setSubmitted(result)
      // Rotate key ONLY after server confirmed persistence so a retry before confirmation never duplicates
      idempotencyRef.current = makeIdempotencyKey()
      if (onSubmitted) onSubmitted(result)
    } catch {
      setSubmitError(isHi
        ? 'नेटवर्क त्रुटि: सर्वर से संपर्क नहीं हो सका। यदि आप खतरे में हैं तो 112 पर कॉल करें।'
        : 'Network error: could not reach HAVEN servers. Your report was NOT submitted — retry or call 112 immediately.')
    } finally {
      inFlightRef.current = false
      setSubmitting(false)
    }
  }

  const resetForNew = () => {
    setSubmitted(null)
    setDescription('')
    setSubmitError('')
    idempotencyRef.current = makeIdempotencyKey()
  }

  return (
    <section
      aria-labelledby="direct-sos-heading"
      style={{
        background: 'white',
        borderRadius: 18,
        padding: 'clamp(18px, 4vw, 28px)',
        border: '1px solid rgba(190,24,93,0.16)',
        boxShadow: '0 4px 20px rgba(190,24,93,0.08)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: '#fee2e2', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#dc2626' }}>
            <ShieldAlert size={20} />
          </div>
          <div>
            <h2 id="direct-sos-heading" style={{ fontFamily: 'Georgia, serif', fontSize: 'clamp(1.05rem, 3.5vw, 1.3rem)', color: '#1a0a12', margin: 0 }}>
              {isHi ? 'वेबसाइट SOS रिपोर्ट (सीधी सहायता)' : 'Report Emergency (Website SOS)'}
            </h2>
            <p style={{ fontSize: '0.78rem', color: '#8b6b7d', margin: '2px 0 0' }}>
              {isHi ? 'सटीक श्रेणी और स्थान के साथ तुरंत घटना दर्ज करें' : 'Structured emergency report with live status tracking'}
            </p>
          </div>
        </div>
        <a
          href="tel:112"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 999,
            background: '#dc2626', color: 'white', fontWeight: 700,
            fontSize: '0.78rem', textDecoration: 'none', minHeight: 40,
          }}
        >
          <Phone size={14} /> 112
        </a>
      </div>

      {submitted ? (
        <div
          role="status"
          aria-live="polite"
          style={{
            background: '#f0fdf4',
            border: '1px solid #86efac',
            borderRadius: 14,
            padding: 18,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#15803d', fontWeight: 800, fontSize: '1rem', marginBottom: 8 }}>
            <CheckCircle2 size={20} />
            {submitted.duplicate
              ? (isHi ? 'आपकी पिछली सक्रिय रिपोर्ट सुरक्षित है (डुप्लीकेट रोका गया)' : 'Existing Incident Preserved (Duplicate Prevented)')
              : (isHi ? 'आपातकालीन रिपोर्ट सफलतापूर्वक दर्ज हुई' : 'Emergency Incident Submitted')}
          </div>
          <div style={{ fontSize: '0.85rem', color: '#1a0a12', lineHeight: 1.7 }}>
            <div><strong>{isHi ? 'घटना संदर्भ (Reference ID):' : 'Incident Reference:'}</strong> <code style={{ background: '#dcfce7', padding: '2px 6px', borderRadius: 4 }}>{submitted.case_id}</code></div>
            <div><strong>{isHi ? 'वर्तमान स्थिति:' : 'Current Backend Status:'}</strong> {submitted.status}</div>
            <div><strong>{isHi ? 'स्थान:' : 'Recorded Location:'}</strong> {submitted.location} ({submitted.location_source})</div>
            <div><strong>{isHi ? 'समय:' : 'Submitted At:'}</strong> {formatServerDateTime(submitted.created_at)}</div>
          </div>

          {submitted.contact_notifications && submitted.contact_notifications.length > 0 && (
            <div style={{ marginTop: 12, padding: 10, borderRadius: 10, background: 'white', border: '1px solid #bbf7d0' }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 700, color: '#166534', marginBottom: 6 }}>
                Trusted Contact Notification Status:
              </div>
              {submitted.contact_notifications.map((cn, idx) => (
                <div key={cn.contact_id || idx} style={{ fontSize: '0.76rem', color: '#374151', display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{cn.name}</span>
                  <span style={{ fontWeight: 700, color: cn.status === 'NOT_CONFIGURED' ? '#b45309' : cn.status === 'FAILED' ? '#dc2626' : '#15803d' }}>
                    {cn.status === 'NOT_CONFIGURED' ? 'SMS Not Configured (Use WhatsApp/Manual)' : cn.status}
                  </span>
                </div>
              ))}
            </div>
          )}

          <p style={{ fontSize: '0.76rem', color: '#4b5563', marginTop: 10, marginBottom: 12 }}>
            {isHi
              ? 'सहायता असाइन होने की पुष्टि तभी दिखाई जाएगी जब कोई अधिकृत अधिकारी डिस्पैच स्वीकार करेगा।'
              : 'Responder assignment is only shown once an authorized dispatcher and verified responder confirm it.'}
          </p>

          <button
            type="button"
            onClick={resetForNew}
            style={{
              padding: '10px 16px', borderRadius: 10, border: '1px solid #15803d',
              background: 'white', color: '#15803d', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem',
            }}
          >
            {isHi ? 'नई रिपोर्ट दर्ज करें' : 'File Another Report'}
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label htmlFor="sos-category" style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1a0a12', marginBottom: 6 }}>
              {isHi ? 'आपातकाल श्रेणी *' : 'Emergency Category *'}
            </label>
            <select
              id="sos-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              required
              style={{
                width: '100%', padding: '11px 12px', borderRadius: 10,
                border: '1px solid rgba(190,24,93,0.28)', fontSize: '0.9rem',
                background: 'white', color: '#1a0a12', minHeight: 44,
              }}
            >
              {CATEGORIES.map((c) => (
                <option key={c.id} value={c.id}>{isHi ? c.labelHi : c.labelEn}</option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="sos-desc" style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1a0a12', marginBottom: 6 }}>
              {isHi ? 'स्थिति का विवरण (वैकल्पिक)' : 'Situation Description (optional)'}
            </label>
            <textarea
              id="sos-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder={isHi ? 'जैसे: कोई मेरा पीछा कर रहा है, मैं सुरक्षित स्थान की तलाश में हूँ...' : 'Briefly describe what is happening or what help you need...'}
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 12px',
                borderRadius: 10, border: '1px solid rgba(190,24,93,0.25)',
                fontSize: '0.88rem', color: '#1a0a12', resize: 'vertical',
              }}
            />
          </div>

          {/* Location block */}
          <div style={{ background: '#fdf2f8', borderRadius: 12, padding: 14, border: '1px solid rgba(190,24,93,0.15)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#be185d', display: 'flex', alignItems: 'center', gap: 6 }}>
                <MapPin size={15} /> {isHi ? 'स्थान जानकारी (ब्राउज़र अनुमति)' : 'Location Details (Explicit Permission)'}
              </span>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={captureGPS}
                  disabled={gpsLoading}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    padding: '8px 12px', borderRadius: 8, border: 'none',
                    background: '#be185d', color: 'white', fontWeight: 700,
                    fontSize: '0.78rem', cursor: gpsLoading ? 'wait' : 'pointer', minHeight: 38,
                  }}
                >
                  {gpsLoading ? <Loader2 size={14} className="animate-spin" /> : <Navigation size={14} />}
                  {gpsLoading ? (isHi ? 'प्राप्त कर रहे हैं…' : 'Capturing GPS…') : (isHi ? 'GPS स्थान लें' : 'Capture GPS Location')}
                </button>
                <button
                  type="button"
                  onClick={() => setUseManualLoc((v) => !v)}
                  style={{
                    padding: '8px 12px', borderRadius: 8,
                    border: '1px solid rgba(190,24,93,0.25)', background: 'white',
                    color: '#be185d', fontWeight: 600, fontSize: '0.78rem', cursor: 'pointer', minHeight: 38,
                  }}
                >
                  {useManualLoc ? (isHi ? 'मैन्युअल बंद करें' : 'Use GPS Instead') : (isHi ? 'मैन्युअल स्थान लिखें' : 'Enter Manually')}
                </button>
              </div>
            </div>

            {capturedLoc && !useManualLoc && (
              <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: 'white', border: '1px solid #bbf7d0', fontSize: '0.78rem', color: '#14532d' }}>
                <div>
                  <strong>{isHi ? 'निर्देशांक:' : 'Coordinates:'}</strong> {capturedLoc.latitude.toFixed(6)}, {capturedLoc.longitude.toFixed(6)}
                  {capturedLoc.accuracy !== null && (
                    <span> · <strong>{isHi ? 'सटीकता:' : 'Accuracy:'}</strong> ±{capturedLoc.accuracy} m</span>
                  )}
                </div>
                <div style={{ marginTop: 3, color: '#4b5563' }}>
                  <strong>{isHi ? 'कैप्चर समय:' : 'Captured:'}</strong> {formatServerDateTime(capturedLoc.capturedAt)}
                  {isStale && <span style={{ color: '#b45309', fontWeight: 700 }}> · STALE (&gt;5m old — refresh recommended)</span>}
                </div>
              </div>
            )}

            {gpsError && (
              <div role="alert" style={{ marginTop: 8, fontSize: '0.76rem', color: '#b45309', fontWeight: 600 }}>
                {gpsError}
              </div>
            )}

            {(useManualLoc || !capturedLoc) && (
              <div style={{ marginTop: 10 }}>
                <label htmlFor="sos-manual-loc" style={{ display: 'block', fontSize: '0.76rem', fontWeight: 600, color: '#4b3540', marginBottom: 4 }}>
                  {isHi ? 'मैन्युअल स्थान / पता / लैंडमार्क (जब GPS उपलब्ध न हो)' : 'Manual Location / Landmark (when GPS is unavailable)'}
                </label>
                <input
                  id="sos-manual-loc"
                  type="text"
                  maxLength={300}
                  value={manualLocation}
                  onChange={(e) => setManualLocation(e.target.value)}
                  placeholder={isHi ? 'जैसे: राजीव चौक मेट्रो गेट 2 के पास' : 'e.g. Near Metro Station Gate 2, Main Road'}
                  style={{
                    width: '100%', boxSizing: 'border-box', padding: '9px 12px',
                    borderRadius: 8, border: '1px solid rgba(190,24,93,0.25)',
                    fontSize: '0.85rem', background: 'white', minHeight: 42,
                  }}
                />
              </div>
            )}

            <p style={{ fontSize: '0.7rem', color: '#8b6b7d', margin: '8px 0 0', lineHeight: 1.4 }}>
              {isHi
                ? 'नोट: ब्राउज़र केवल सक्रिय सत्र के दौरान ही लोकेशन पढ़ सकता है (बैकग्राउंड ट्रैकिंग नहीं)।'
                : 'Browser note: Web browsers cannot track GPS continuously when closed or locked.'}
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', color: '#1a0a12', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={immediateDanger}
                onChange={(e) => setImmediateDanger(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: '#be185d' }}
              />
              <span>{isHi ? 'तत्काल खतरा (उच्च प्राथमिकता के रूप में चिह्नित करें)' : 'I am in immediate danger (prioritize critical review)'}</span>
            </label>

            {trustedContactCount > 0 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', color: '#1a0a12', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={notifyContacts}
                  onChange={(e) => setNotifyContacts(e.target.checked)}
                  style={{ width: 18, height: 18, accentColor: '#be185d' }}
                />
                <span>
                  {isHi
                    ? `मेरे ${trustedContactCount} विश्वसनीय संपर्कों को SMS अलर्ट भेजने का प्रयास करें (यदि SMS सेवा कॉन्फ़िगर है)`
                    : `Notify my ${trustedContactCount} trusted contact(s) via SMS (when provider is configured)`}
                </span>
              </label>
            )}
          </div>

          {submitError && (
            <div role="alert" style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '10px 12px', color: '#b91c1c', fontSize: '0.82rem', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
              <span>{submitError}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: '100%', padding: '13px 20px', borderRadius: 12, border: 'none',
              background: submitting ? '#9d174d' : 'linear-gradient(135deg, #dc2626, #be185d)',
              color: 'white', fontWeight: 800, fontSize: '0.95rem',
              cursor: submitting ? 'wait' : 'pointer', minHeight: 48,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              boxShadow: '0 4px 16px rgba(220,38,38,0.28)',
            }}
          >
            {submitting ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                {isHi ? 'आपातकालीन रिपोर्ट भेजी जा रही है…' : 'Submitting Emergency SOS…'}
              </>
            ) : (
              <>
                <ShieldAlert size={18} />
                {isHi ? 'अभी SOS रिपोर्ट सबमिट करें' : 'Submit Emergency SOS'}
              </>
            )}
          </button>
        </form>
      )}
    </section>
  )
}
