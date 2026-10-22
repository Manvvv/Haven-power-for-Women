'use client'
/**
 * HAVEN RESPONSE PROVIDERS (/authority/providers)
 *
 * Authority rules (enforced by the BACKEND, mirrored here only for presentation):
 *  - AUTHORITY can VIEW the roster and submit registration requests.
 *    It cannot create, verify, activate, or issue setup tokens directly.
 *  - AUTHORITY can submit Suspension / Revocation requests for active providers;
 *    an ADMIN must approve before any change takes effect.
 *  - ADMIN can provision (one-time setup token), verify/approve, activate and
 *    deactivate. UI hides these controls for non-admins, but backend enforces.
 *
 * Counts are derived ONLY from real roster rows. Nothing is fabricated.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { ArrowLeft, Shield, RefreshCw, Plus, X, ClipboardList, UserPlus } from 'lucide-react'
import { useRole } from '@/hooks/useRole'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import { getAuthorityToken } from '@/lib/api'
import {
  getProviderRoster, adminCreateProvider, adminSetProviderVerified, adminSetProviderActive,
  adminRevokeProvider, ProviderRow,
  authorityRegisterProvider, authorityGetRegistrations, authorityRequestProviderAction,
  ProviderRegistration, ProviderActionRequest,
} from '@/lib/dispatch'

const C = {
  bg: '#f8f4f6', ink: '#1a0a12', panel: '#ffffff', line: '#ecdfe6',
  accent: '#0f766e', muted: '#6b7280', text: '#3b2733', warn: '#b45309', bad: '#b91c1c',
  amber: '#d97706',
}

const CATEGORY_LABELS: Record<string, string> = {
  police: 'Police',
  women_safety_unit: 'Women Safety Unit',
  ngo_response: 'NGO Response Team',
  shelter_response: 'Shelter Response Team',
  medical_partner: 'Medical Response Partner',
  other_authorized: 'Other Authorized Provider',
}

type MainTab = 'roster' | 'registrations'
type RosterTab = 'all' | 'verified' | 'on_duty' | 'available' | 'busy' | 'offline_stale'

const ROSTER_TABS: Array<{ id: RosterTab; label: string }> = [
  { id: 'all', label: 'All Providers' },
  { id: 'verified', label: 'Verified' },
  { id: 'on_duty', label: 'On Duty' },
  { id: 'available', label: 'Available' },
  { id: 'busy', label: 'Busy / Assigned' },
  { id: 'offline_stale', label: 'Offline / Location Stale' },
]

/** Derived operational bucket from real stored fields only. */
function bucket(p: ProviderRow): Exclude<RosterTab, 'all' | 'verified'> | 'none' {
  if (!p.verified || !p.active) return 'none'
  if (!p.on_duty) return 'offline_stale'
  if (p.assigned || p.status === 'BUSY' || p.active_dispatch_id_present) return 'busy'
  if (p.status === 'AVAILABLE' && p.location_fresh) return 'available'
  return 'offline_stale'
}

function freshnessLabel(p: ProviderRow): string {
  if (!p.on_duty) return 'OFF DUTY'
  if (!p.location) return 'LOCATION UNAVAILABLE'
  if (!p.location_fresh) return 'STALE'
  return 'LIVE'
}

function statusBadge(status: string) {
  if (status === 'PENDING_REVIEW') return { bg: '#fef9c3', color: '#854d0e', label: 'Pending Review' }
  if (status === 'APPROVED') return { bg: '#dcfce7', color: '#15803d', label: 'Approved' }
  if (status === 'REJECTED') return { bg: '#fee2e2', color: '#b91c1c', label: 'Rejected' }
  return { bg: '#f3f4f6', color: '#6b7280', label: status }
}

export default function ProvidersPage() {
  useHavenAuth()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { isAdmin, isLoaded } = useRole()
  const [authorized, setAuthorized] = useState<boolean | null>(null)

  // ── Roster ──
  const [rows, setRows] = useState<ProviderRow[]>([])
  const [rosterLoading, setRosterLoading] = useState(true)
  const [rosterError, setRosterError] = useState('')
  const [rosterTab, setRosterTab] = useState<RosterTab>('all')

  // ── Registrations ──
  const [registrations, setRegistrations] = useState<ProviderRegistration[]>([])
  const [regLoading, setRegLoading] = useState(false)
  const [regError, setRegError] = useState('')

  // ── Main tab ──
  const [mainTab, setMainTab] = useState<MainTab>('roster')

  // ── Modals ──
  const [showAdd, setShowAdd] = useState(false)
  const [showRegisterModal, setShowRegisterModal] = useState(false)
  const [issued, setIssued] = useState<{ label: string; token: string } | null>(null)
  const [busy, setBusy] = useState('')
  const [globalError, setGlobalError] = useState('')
  const [confirmModal, setConfirmModal] = useState<{
    action: 'verify' | 'suspend' | 'reinstate' | 'revoke'
    provider: ProviderRow
  } | null>(null)
  const [actionModal, setActionModal] = useState<{
    provider: ProviderRow
  } | null>(null)

  // Open register modal if ?register=true in URL
  useEffect(() => {
    if (searchParams?.get('register') === 'true') {
      setShowRegisterModal(true)
    }
  }, [searchParams])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const token = getAuthorityToken()
      if (!token) { setAuthorized(false); router.replace('/authority'); return }
      setAuthorized(true)
    }
  }, [router])

  const refreshRoster = useCallback(async () => {
    if (typeof window !== 'undefined' && !getAuthorityToken()) {
      setAuthorized(false); router.replace('/authority'); return
    }
    setRosterLoading(true); setRosterError('')
    try {
      setRows(await getProviderRoster())
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not load providers.'
      if (msg.includes('401') || msg.includes('403') || msg.toLowerCase().includes('not authenticated') || msg.toLowerCase().includes('unauthorized')) {
        setAuthorized(false); router.replace('/authority'); return
      }
      setRosterError(msg)
    } finally { setRosterLoading(false) }
  }, [router])

  const refreshRegistrations = useCallback(async () => {
    setRegLoading(true); setRegError('')
    try {
      const data = await authorityGetRegistrations()
      setRegistrations(data.registrations || [])
    } catch (err: unknown) {
      setRegError(err instanceof Error ? err.message : 'Could not load registrations.')
    } finally { setRegLoading(false) }
  }, [])

  useEffect(() => {
    if (authorized === true) {
      refreshRoster()
      refreshRegistrations()
    }
  }, [authorized, refreshRoster, refreshRegistrations])

  const metrics = useMemo(() => ({
    total: rows.length,
    verified: rows.filter(r => r.verified && r.active).length,
    onDuty: rows.filter(r => r.on_duty).length,
    available: rows.filter(r => bucket(r) === 'available').length,
    busy: rows.filter(r => bucket(r) === 'busy').length,
    offline: rows.filter(r => !r.on_duty || bucket(r) === 'offline_stale').length,
  }), [rows])

  const visibleRows = useMemo(() => {
    if (rosterTab === 'all') return rows
    if (rosterTab === 'verified') return rows.filter(r => r.verified && r.active)
    return rows.filter(r => bucket(r) === rosterTab)
  }, [rows, rosterTab])

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setGlobalError('')
    try { await fn(); await refreshRoster() }
    catch (err: unknown) { setGlobalError(err instanceof Error ? err.message : 'Action failed.') }
    finally { setBusy('') }
  }

  const handleConfirmAction = async () => {
    if (!confirmModal) return
    const { action, provider } = confirmModal
    setConfirmModal(null)
    if (action === 'verify') {
      await act(`v:${provider.responder_id}`, () => adminSetProviderVerified(provider.responder_id, true))
    } else if (action === 'suspend') {
      await act(`s:${provider.responder_id}`, () => adminSetProviderActive(provider.responder_id, false))
    } else if (action === 'reinstate') {
      await act(`r:${provider.responder_id}`, () => adminSetProviderActive(provider.responder_id, true))
    } else if (action === 'revoke') {
      await act(`x:${provider.responder_id}`, () => adminRevokeProvider(provider.responder_id))
    }
  }

  if (authorized !== true) {
    return (
      <div style={{ minHeight: '100vh', background: C.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: C.muted, fontSize: 14 }}>Redirecting to authority sign-in...</p>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ background: C.panel, borderBottom: `1px solid ${C.line}`, padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <Link href="/authority" aria-label="Back to Authority Dashboard" style={{ color: C.muted, display: 'flex' }}>
          <ArrowLeft size={18} />
        </Link>
        <Shield size={18} color={C.accent} />
        <div>
          <div style={{ fontWeight: 800, color: C.ink, letterSpacing: 0.3 }}>HAVEN RESPONSE PROVIDERS</div>
          <div style={{ fontSize: 12, color: C.muted }}>Manage verified emergency-response personnel and organizations.</div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => { refreshRoster(); refreshRegistrations() }} aria-label="Refresh" style={{ background: 'none', border: `1px solid ${C.line}`, borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: C.muted, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
            <RefreshCw size={13} /><span>Refresh</span>
          </button>
          {/* Authority: Register provider for admin review */}
          <button
            onClick={() => setShowRegisterModal(true)}
            style={{ background: '#047857', border: '1px solid #047857', borderRadius: 8, padding: '7px 12px', cursor: 'pointer', color: 'white', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700 }}
          >
            <UserPlus size={14} /><span>Register Provider</span>
          </button>
          {/* Admin only: direct provisioning */}
          {isLoaded && isAdmin && (
            <button onClick={() => setShowAdd(true)} style={{ background: C.accent, border: `1px solid ${C.accent}`, borderRadius: 8, padding: '7px 12px', cursor: 'pointer', color: 'white', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700 }}>
              <Plus size={14} /><span>Add Provider (Admin)</span>
            </button>
          )}
        </div>
      </header>

      <main style={{ padding: 20, maxWidth: 1200, margin: '0 auto' }}>
        {globalError && <div role="alert" style={{ background: '#fef2f2', border: `1px solid #fecaca`, color: C.bad, padding: 10, borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{globalError}</div>}

        {/* Metrics */}
        <section aria-label="Provider metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 16 }}>
          {[
            ['TOTAL REGISTERED', metrics.total], ['VERIFIED', metrics.verified], ['ON DUTY', metrics.onDuty],
            ['AVAILABLE', metrics.available], ['BUSY / ASSIGNED', metrics.busy], ['OFFLINE', metrics.offline],
          ].map(([label, value]) => (
            <div key={String(label)} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 11, color: C.muted, fontWeight: 700 }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.ink }}>{rosterLoading ? '—' : value}</div>
            </div>
          ))}
        </section>

        {/* Main tabs: Roster | Registrations */}
        <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${C.line}`, marginBottom: 16 }}>
          {([
            { id: 'roster' as MainTab, label: 'Active Roster', icon: <Shield size={13} /> },
            { id: 'registrations' as MainTab, label: `Registrations (${registrations.length})`, icon: <ClipboardList size={13} /> },
          ]).map(t => (
            <button key={t.id} onClick={() => setMainTab(t.id)} style={{
              display: 'flex', alignItems: 'center', gap: 5, padding: '10px 18px',
              background: 'none', border: 'none', borderBottom: mainTab === t.id ? `2px solid ${C.accent}` : '2px solid transparent',
              cursor: 'pointer', color: mainTab === t.id ? C.accent : C.muted,
              fontWeight: mainTab === t.id ? 700 : 400, fontSize: 13,
            }}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* ── ROSTER TAB ── */}
        {mainTab === 'roster' && (
          <>
            <nav aria-label="Provider filters" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {ROSTER_TABS.map(t => (
                <button key={t.id} onClick={() => setRosterTab(t.id)} aria-pressed={rosterTab === t.id}
                  style={{ padding: '6px 12px', borderRadius: 16, border: `1px solid ${rosterTab === t.id ? C.accent : C.line}`, background: rosterTab === t.id ? C.accent : C.panel, color: rosterTab === t.id ? 'white' : C.text, fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                  {t.label}
                </button>
              ))}
            </nav>

            {rosterError && <div role="alert" style={{ background: '#fef2f2', border: `1px solid #fecaca`, color: C.bad, padding: 10, borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{rosterError}</div>}

            <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', background: '#faf6f8', color: C.muted }}>
                    {['Unit', 'Category', 'Organization', 'Jurisdiction', 'Capabilities', 'Verification', 'Duty', 'Location', 'Assignment', 'Actions'].map(h => (
                      <th key={h} style={{ padding: '10px 8px', borderBottom: `1px solid ${C.line}`, fontWeight: 700 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {!rosterLoading && visibleRows.length === 0 && (
                    <tr><td colSpan={10} style={{ padding: 16, color: C.muted, textAlign: 'center' }}>No providers in this view.</td></tr>
                  )}
                  {visibleRows.map(p => (
                    <tr key={p.responder_id} style={{ borderBottom: `1px solid ${C.line}` }}>
                      <td style={{ padding: 8, fontWeight: 600, color: C.ink }}>{p.display_label || 'Response unit'}</td>
                      <td style={{ padding: 8 }}>{CATEGORY_LABELS[p.provider_category] || p.provider_category}</td>
                      <td style={{ padding: 8 }}>{p.organization || '—'}</td>
                      <td style={{ padding: 8 }}>{p.jurisdiction || '—'}</td>
                      <td style={{ padding: 8 }}>{(p.capabilities || []).join(', ') || '—'}</td>
                      <td style={{ padding: 8 }}>
                        {p.provisioning_state === 'PROVIDER_CREATED' ? 'Provider created'
                          : p.provisioning_state === 'VERIFICATION_PENDING' ? 'Verification pending'
                          : p.provisioning_state === 'SUSPENDED' ? 'Suspended'
                          : p.verified ? 'Verified' : 'Verification pending'}
                        {p.active && p.verified ? ' · Active' : ''}
                      </td>
                      <td style={{ padding: 8 }}>{p.on_duty ? 'ON DUTY' : 'OFF DUTY'}</td>
                      <td style={{ padding: 8 }}>
                        {freshnessLabel(p)}
                        {p.location_age_seconds != null && p.on_duty && (
                          <div style={{ color: C.muted, fontSize: 11 }}>updated {Math.round(p.location_age_seconds)}s ago</div>
                        )}
                      </td>
                      <td style={{ padding: 8 }}>{p.assigned || p.active_dispatch_id_present ? 'Assigned' : bucket(p) === 'available' ? 'Available' : '—'}</td>
                      <td style={{ padding: 8, whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {/* Admin-only direct actions */}
                          {isAdmin && (
                            <>
                              {!p.verified && (
                                <button disabled={!!busy} onClick={() => setConfirmModal({ action: 'verify', provider: p })}
                                  style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: `1px solid ${C.accent}`, background: 'white', color: C.accent, fontWeight: 700, cursor: 'pointer' }}>
                                  Verify
                                </button>
                              )}
                              {p.active ? (
                                <button disabled={!!busy} onClick={() => setConfirmModal({ action: 'suspend', provider: p })}
                                  style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid #f59e0b', background: '#fffbeb', color: '#b45309', fontWeight: 600, cursor: 'pointer' }}>
                                  Suspend
                                </button>
                              ) : (
                                <button disabled={!!busy} onClick={() => setConfirmModal({ action: 'reinstate', provider: p })}
                                  style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: `1px solid ${C.accent}`, background: '#f0fdfa', color: C.accent, fontWeight: 600, cursor: 'pointer' }}>
                                  Reinstate
                                </button>
                              )}
                              {(p.verified || p.active) && (
                                <button disabled={!!busy} onClick={() => setConfirmModal({ action: 'revoke', provider: p })}
                                  style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid #fecaca', background: '#fef2f2', color: C.bad, fontWeight: 600, cursor: 'pointer' }}>
                                  Revoke
                                </button>
                              )}
                            </>
                          )}
                          {/* Authority: request suspension/revocation for admin review */}
                          {!isAdmin && (p.verified || p.active) && (
                            <button disabled={!!busy} onClick={() => setActionModal({ provider: p })}
                              style={{ fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid #f59e0b', background: '#fffbeb', color: '#b45309', fontWeight: 600, cursor: 'pointer' }}>
                              Request Action
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!isAdmin && isLoaded && (
              <p style={{ fontSize: 11, color: C.muted, marginTop: 10 }}>
                Provider creation, verification and activation are restricted to administrators. You can submit Suspension / Revocation requests for admin review.
              </p>
            )}
          </>
        )}

        {/* ── REGISTRATIONS TAB ── */}
        {mainTab === 'registrations' && (
          <>
            {regError && <div role="alert" style={{ background: '#fef2f2', border: `1px solid #fecaca`, color: C.bad, padding: 10, borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{regError}</div>}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
              <button onClick={() => setShowRegisterModal(true)}
                style={{ background: '#047857', border: '1px solid #047857', borderRadius: 8, padding: '7px 12px', cursor: 'pointer', color: 'white', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700 }}>
                <UserPlus size={14} /><span>Register New Provider</span>
              </button>
            </div>
            {regLoading ? (
              <div style={{ textAlign: 'center', padding: 40, color: C.muted }}>Loading registrations…</div>
            ) : registrations.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, background: C.panel, borderRadius: 10, border: `1px solid ${C.line}` }}>
                <ClipboardList size={32} style={{ margin: '0 auto 10px', display: 'block', opacity: 0.3 }} />
                <div style={{ color: C.muted, fontSize: 13 }}>No registrations submitted yet. Use "Register New Provider" to submit a provider for admin review.</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {registrations.map(reg => {
                  const badge = statusBadge(reg.status)
                  return (
                    <div key={reg.registration_id} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: 16 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 700, color: C.ink, fontSize: 14 }}>{reg.unit_name}</div>
                          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
                            {CATEGORY_LABELS[reg.provider_category] || reg.provider_category}
                            {reg.organization ? ` · ${reg.organization}` : ''}
                            {reg.jurisdiction ? ` · ${reg.jurisdiction}` : ''}
                          </div>
                          {reg.badge_number && (
                            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Badge: {reg.badge_number}</div>
                          )}
                          {reg.capabilities?.length > 0 && (
                            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Capabilities: {reg.capabilities.join(', ')}</div>
                          )}
                          {reg.contact && (
                            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Contact: {reg.contact}</div>
                          )}
                          {reg.auth_reference && (
                            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Auth Ref: {reg.auth_reference}</div>
                          )}
                          {reg.notes && (
                            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Notes: {reg.notes}</div>
                          )}
                          {reg.status === 'REJECTED' && reg.rejection_reason && (
                            <div style={{ marginTop: 6, fontSize: 12, color: C.bad, background: '#fef2f2', padding: '4px 8px', borderRadius: 6 }}>
                              Rejection reason: {reg.rejection_reason}
                            </div>
                          )}
                          {reg.status === 'APPROVED' && reg.live_provider && (
                            <div style={{ marginTop: 6, fontSize: 12, color: '#15803d', background: '#dcfce7', padding: '4px 8px', borderRadius: 6 }}>
                              Provider created · State: {reg.live_provider.provisioning_state}
                              {reg.live_provider.verified ? ' · Verified' : ' · Awaiting verification'}
                              {reg.live_provider.on_duty ? ' · On duty' : ''}
                            </div>
                          )}
                          <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>
                            Submitted {new Date(reg.submitted_at).toLocaleString()}
                            {reg.reviewed_at ? ` · Reviewed ${new Date(reg.reviewed_at).toLocaleString()}` : ''}
                          </div>
                        </div>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 12, background: badge.bg, color: badge.color, whiteSpace: 'nowrap' }}>
                          {badge.label}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </main>

      {/* ── Admin direct-create dialog ── */}
      {showAdd && (
        <AddProviderDialog
          onClose={() => setShowAdd(false)}
          onCreated={(label, token) => { setShowAdd(false); setIssued({ label, token }); refreshRoster() }}
        />
      )}

      {/* ── Authority: Register Provider for admin review ── */}
      {showRegisterModal && (
        <RegisterProviderDialog
          onClose={() => setShowRegisterModal(false)}
          onSubmitted={() => { setShowRegisterModal(false); setMainTab('registrations'); refreshRegistrations() }}
        />
      )}

      {/* ── Setup token display (admin provisioning) ── */}
      {issued && (
        <div role="dialog" aria-modal="true" aria-label="Setup token" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 60 }}>
          <div style={{ background: C.panel, borderRadius: 12, padding: 20, maxWidth: 480, width: '100%' }}>
            <div style={{ fontWeight: 800, color: C.ink, marginBottom: 6 }}>Provider created: {issued.label}</div>
            <div style={{ fontSize: 13, color: C.text, marginBottom: 10 }}>
              State: <strong>Provider created</strong>. The provider must set their own password, and an administrator must verify them before they can receive emergency requests.
            </div>
            <div style={{ fontSize: 12, color: C.warn, marginBottom: 6 }}>
              One-time setup token (shown once, expires in 24 hours, single use). Hand it to the provider securely. It will not be shown again.
            </div>
            <code style={{ display: 'block', background: '#faf6f8', padding: 10, borderRadius: 6, wordBreak: 'break-all', fontSize: 12 }}>{issued.token}</code>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
              <button onClick={() => setIssued(null)} style={{ background: C.accent, color: 'white', border: 'none', borderRadius: 8, padding: '8px 14px', fontWeight: 700, cursor: 'pointer' }}>Done</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Admin confirm action modal ── */}
      {confirmModal && (
        <div role="dialog" aria-modal="true" aria-label="Confirm provider action" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 60 }}>
          <div style={{ background: C.panel, borderRadius: 12, padding: 22, maxWidth: 440, width: '100%', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }}>
            <div style={{ fontWeight: 800, fontSize: 16, color: C.ink, marginBottom: 8 }}>
              {confirmModal.action === 'verify' && 'Verify Provider'}
              {confirmModal.action === 'suspend' && 'Suspend Provider'}
              {confirmModal.action === 'reinstate' && 'Reinstate Provider'}
              {confirmModal.action === 'revoke' && 'Revoke Provider'}
            </div>
            <div style={{ fontSize: 13, color: C.text, lineHeight: 1.5, marginBottom: 14 }}>
              {confirmModal.action === 'verify' && (<>Approve <strong>{confirmModal.provider.display_label || confirmModal.provider.responder_id}</strong>? The provider will be marked as verified and can receive emergency dispatches once on duty.</>)}
              {confirmModal.action === 'suspend' && (<>Suspend <strong>{confirmModal.provider.display_label || confirmModal.provider.responder_id}</strong>? This provider will be temporarily deactivated and cannot log in or receive dispatches until reinstated.</>)}
              {confirmModal.action === 'reinstate' && (<>Reinstate <strong>{confirmModal.provider.display_label || confirmModal.provider.responder_id}</strong>? The account will be reactivated.</>)}
              {confirmModal.action === 'revoke' && (<>Revoke <strong>{confirmModal.provider.display_label || confirmModal.provider.responder_id}</strong>? This will revoke verification and deactivate the account permanently.</>)}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button onClick={() => setConfirmModal(null)} style={{ background: 'white', border: `1px solid ${C.line}`, borderRadius: 8, padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer', color: C.text }}>Cancel</button>
              <button onClick={handleConfirmAction} style={{ background: confirmModal.action === 'revoke' ? C.bad : confirmModal.action === 'suspend' ? '#d97706' : C.accent, color: 'white', border: 'none', borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
                {confirmModal.action === 'verify' && 'Confirm Verification'}
                {confirmModal.action === 'suspend' && 'Suspend Provider'}
                {confirmModal.action === 'reinstate' && 'Reinstate Provider'}
                {confirmModal.action === 'revoke' && 'Revoke Provider'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Authority: Request Action modal (submit to admin for approval) ── */}
      {actionModal && (
        <RequestActionDialog
          provider={actionModal.provider}
          onClose={() => setActionModal(null)}
          onSubmitted={() => { setActionModal(null); setMainTab('registrations'); refreshRegistrations() }}
        />
      )}
    </div>
  )
}

// ── Register Provider dialog (Authority submits for admin review) ────────────
function RegisterProviderDialog({ onClose, onSubmitted }: {
  onClose: () => void
  onSubmitted: () => void
}) {
  const [unitName, setUnitName] = useState('')
  const [organization, setOrganization] = useState('')
  const [category, setCategory] = useState('police')
  const [jurisdiction, setJurisdiction] = useState('')
  const [capabilities, setCapabilities] = useState('')
  const [contact, setContact] = useState('')
  const [authRef, setAuthRef] = useState('')
  const [badgeNumber, setBadgeNumber] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!unitName.trim() || !organization.trim() || !jurisdiction.trim() || !contact.trim() || !authRef.trim()) {
      setErr('Unit name, organization, jurisdiction, contact, and authorization reference are required.')
      return
    }
    setBusy(true); setErr('')
    try {
      await authorityRegisterProvider({
        unit_name: unitName.trim(),
        organization: organization.trim(),
        provider_category: category,
        jurisdiction: jurisdiction.trim(),
        capabilities: capabilities.split(',').map(s => s.trim()).filter(Boolean),
        contact: contact.trim(),
        auth_reference: authRef.trim(),
        badge_number: badgeNumber.trim() || undefined,
        notes: notes.trim() || undefined,
      })
      onSubmitted()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Could not submit registration.')
    } finally { setBusy(false) }
  }

  const field = (label: string, value: string, set: (v: string) => void, required = false, max = 200, placeholder = '') => (
    <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
      {label}{required && <span style={{ color: '#b91c1c' }}> *</span>}
      <input value={value} maxLength={max} onChange={e => set(e.target.value)} placeholder={placeholder}
        style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: '1px solid #ecdfe6', borderRadius: 6, fontSize: 13, color: '#1a0a12', boxSizing: 'border-box' }} />
    </label>
  )

  return (
    <div role="dialog" aria-modal="true" aria-label="Register provider" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 50 }}>
      <div style={{ background: '#ffffff', borderRadius: 12, padding: 22, maxWidth: 560, width: '100%', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
          <div>
            <div style={{ fontWeight: 800, color: '#1a0a12', fontSize: 15 }}>Register Response Provider</div>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>Submit for Admin review — the provider account will only be created after approval.</div>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}><X size={18} /></button>
        </div>

        {field('Provider / Response Unit Name', unitName, setUnitName, true, 120, 'e.g. Alpha Women Safety Unit')}
        {field('Organization', organization, setOrganization, true, 120, 'e.g. Delhi Police, iCall NGO')}

        <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
          Provider Category<span style={{ color: '#b91c1c' }}> *</span>
          <select value={category} onChange={e => setCategory(e.target.value)}
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: '1px solid #ecdfe6', borderRadius: 6, fontSize: 13 }}>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>

        {field('Jurisdiction / Service Area', jurisdiction, setJurisdiction, true, 120, 'e.g. South Delhi District')}
        {field('Capabilities (comma separated)', capabilities, setCapabilities, false, 300, 'e.g. crisis-counselling, shelter-referral')}
        {field('Official Contact (phone or email)', contact, setContact, true, 120, 'e.g. +91-9876543210')}
        {field('Registration / Authorization Reference', authRef, setAuthRef, true, 200, 'e.g. Ministry Order No. 2024/DWR/045')}
        {field('Badge / Employee Number (optional)', badgeNumber, setBadgeNumber, false, 40)}

        <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
          Supporting Notes (optional)
          <textarea value={notes} maxLength={500} onChange={e => setNotes(e.target.value)} rows={3}
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: '1px solid #ecdfe6', borderRadius: 6, fontSize: 13, color: '#1a0a12', resize: 'vertical', boxSizing: 'border-box' }} />
        </label>

        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 10, padding: '8px', background: '#f8f4f6', borderRadius: 6 }}>
          This registration will be reviewed by an administrator before a provider account is created. You will be able to track the status in the Registrations tab.
        </div>

        {err && <div role="alert" style={{ color: '#b91c1c', fontSize: 12, marginBottom: 10 }}>{err}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={{ background: 'white', border: '1px solid #ecdfe6', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            style={{ background: '#047857', color: 'white', border: 'none', borderRadius: 8, padding: '8px 16px', fontWeight: 700, cursor: busy ? 'not-allowed' : 'pointer', opacity: busy ? 0.6 : 1, fontSize: 13 }}>
            {busy ? 'Submitting…' : 'Submit for Admin Review'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Authority: Request Suspension / Revocation dialog ────────────────────────
function RequestActionDialog({ provider, onClose, onSubmitted }: {
  provider: ProviderRow
  onClose: () => void
  onSubmitted: () => void
}) {
  const [requestType, setRequestType] = useState<'SUSPENSION' | 'REVOCATION'>('SUSPENSION')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!reason.trim() || reason.trim().length < 20) {
      setErr('Reason must be at least 20 characters.')
      return
    }
    setBusy(true); setErr('')
    try {
      await authorityRequestProviderAction(provider.responder_id, requestType, reason.trim())
      onSubmitted()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Could not submit request.')
    } finally { setBusy(false) }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Request provider action" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 60 }}>
      <div style={{ background: '#ffffff', borderRadius: 12, padding: 22, maxWidth: 460, width: '100%', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontWeight: 800, color: '#1a0a12', fontSize: 15 }}>Request Provider Action</div>
          <button onClick={onClose} aria-label="Close" style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13, color: '#3b2733', marginBottom: 12 }}>
          Provider: <strong>{provider.display_label || provider.responder_id}</strong>
        </div>

        <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
          Action Type
          <select value={requestType} onChange={e => setRequestType(e.target.value as 'SUSPENSION' | 'REVOCATION')}
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: '1px solid #ecdfe6', borderRadius: 6, fontSize: 13 }}>
            <option value="SUSPENSION">Suspension — temporarily deactivate (reinstateable)</option>
            <option value="REVOCATION">Revocation — permanently remove authorization</option>
          </select>
        </label>

        <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
          Reason<span style={{ color: '#b91c1c' }}> *</span> (min 20 characters)
          <textarea value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} rows={4}
            placeholder="Provide a clear, documented reason for this action request…"
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: '1px solid #ecdfe6', borderRadius: 6, fontSize: 13, resize: 'vertical', boxSizing: 'border-box' }} />
          <span style={{ fontSize: 11, color: '#6b7280' }}>{reason.length}/1000</span>
        </label>

        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 10, padding: '8px', background: '#fffbeb', borderRadius: 6, border: '1px solid #fde68a' }}>
          ⚠️ This request will be reviewed by an administrator before any change is made. The provider will not be affected until an admin approves this request.
        </div>

        {err && <div role="alert" style={{ color: '#b91c1c', fontSize: 12, marginBottom: 10 }}>{err}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={{ background: 'white', border: '1px solid #ecdfe6', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            style={{ background: requestType === 'REVOCATION' ? '#b91c1c' : '#d97706', color: 'white', border: 'none', borderRadius: 8, padding: '8px 16px', fontWeight: 700, cursor: busy ? 'not-allowed' : 'pointer', opacity: busy ? 0.6 : 1, fontSize: 13 }}>
            {busy ? 'Submitting…' : `Submit ${requestType === 'REVOCATION' ? 'Revocation' : 'Suspension'} Request`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Admin direct-create dialog ────────────────────────────────────────────────
function AddProviderDialog({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (label: string, token: string) => void
}) {
  const [badge, setBadge] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [category, setCategory] = useState('police')
  const [organization, setOrganization] = useState('')
  const [stationUnit, setStationUnit] = useState('')
  const [jurisdiction, setJurisdiction] = useState('')
  const [caps, setCaps] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      const res = await adminCreateProvider({
        badge_number: badge.trim(),
        display_name: displayName.trim(),
        provider_category: category,
        organization: organization.trim(),
        station_unit: stationUnit.trim(),
        jurisdiction: jurisdiction.trim(),
        capabilities: caps.split(',').map(s => s.trim()).filter(Boolean),
      })
      onCreated(res.provider.display_label || displayName, res.setup_token)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Could not create provider.')
    } finally { setBusy(false) }
  }

  const field = (label: string, value: string, set: (v: string) => void, max = 120) => (
    <label style={{ display: 'block', fontSize: 12, color: C.muted, marginBottom: 8 }}>
      {label}
      <input value={value} maxLength={max} onChange={e => set(e.target.value)}
        style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 13, color: C.ink }} />
    </label>
  )

  return (
    <div role="dialog" aria-modal="true" aria-label="Add provider" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 50 }}>
      <div style={{ background: C.panel, borderRadius: 12, padding: 20, maxWidth: 520, width: '100%', maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontWeight: 800, color: C.ink }}>Add provider (Admin)</div>
          <button onClick={onClose} aria-label="Close" style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: C.muted }}><X size={18} /></button>
        </div>
        {field('Badge / employee number', badge, setBadge, 40)}
        {field('Provider display name (shown to victims as a safe unit label)', displayName, setDisplayName)}
        <label style={{ display: 'block', fontSize: 12, color: C.muted, marginBottom: 8 }}>
          Category
          <select value={category} onChange={e => setCategory(e.target.value)}
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 9px', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 13 }}>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {field('Organization', organization, setOrganization)}
        {field('Police station / response unit', stationUnit, setStationUnit)}
        {field('Jurisdiction / service area', jurisdiction, setJurisdiction)}
        {field('Capabilities (comma separated)', caps, setCaps)}
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 10 }}>
          The provider is created unverified and offline. They must set their own password. An administrator must then verify them before they can be offered any emergency.
        </div>
        {err && <div role="alert" style={{ color: C.bad, fontSize: 12, marginBottom: 8 }}>{err}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={{ background: 'white', border: `1px solid ${C.line}`, borderRadius: 8, padding: '8px 12px', cursor: 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={busy || !badge.trim() || !displayName.trim()}
            style={{ background: C.accent, color: 'white', border: 'none', borderRadius: 8, padding: '8px 14px', fontWeight: 700, cursor: 'pointer', opacity: busy ? 0.6 : 1 }}>
            {busy ? 'Creating…' : 'Create provider'}
          </button>
        </div>
      </div>
    </div>
  )
}
