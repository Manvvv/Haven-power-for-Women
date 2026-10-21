'use client'

import React, { useState, useEffect, useCallback } from 'react'
import {
  Shield,
  Search,
  Calendar,
  Users,
  Clock,
  Activity,
  Server,
  Filter,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Lock,
  ArrowLeft,
  ClipboardList,
  X,
  UserCheck,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useUser } from '@clerk/nextjs'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'
import { useHavenAuth } from '@/hooks/useHavenAuth'
import {
  adminGetProviderRegistrations,
  adminApproveRegistration,
  adminRejectRegistration,
  adminGetProviderRequests,
  adminReviewProviderRequest,
  adminReissueSetupToken,
  ProviderRegistration,
  ProviderActionRequest,
} from '@/lib/dispatch'

const colors = {
  primary: '#be185d',
  primaryHover: '#9d174d',
  light: '#fdf2f8',
  dark: '#1a0a12',
  accent: '#f472b6',
  muted: '#71717a',
  border: '#f1f5f9',
  cardBg: '#ffffff',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  info: '#3b82f6',
  bg: 'linear-gradient(165deg, #fdf2f8 0%, #f8fafc 40%, #fce7f3 100%)'
}

export default function AdminPage() {
  useHavenAuth()
  const router = useRouter()
  const { user, isLoaded } = useUser()

  // ── Admin-only route guard (frontend UI/route consistency; the backend
  // remains the real security boundary and already returns 403 to non-admins).
  // 'checking' until auth + role are resolved, so we never flash the admin UI
  // or fire admin fetches before authorization is known.
  const [access, setAccess] = useState<'checking' | 'admin' | 'denied'>('checking')

  useEffect(() => {
    // Do not decide anything until Clerk auth state has finished loading.
    if (!isLoaded) return
    if (typeof window === 'undefined') return

    // Resolve the role from the app's EXISTING sources, matching useRole()'s
    // precedence: an authority-portal session role first, then Clerk metadata.
    let resolved: 'user' | 'authority' | 'admin' = 'user'
    const sessionRole = sessionStorage.getItem('haven_authority_role')
    if (sessionRole === 'admin') {
      resolved = 'admin'
    } else if (sessionRole === 'authority') {
      resolved = 'authority'
    } else {
      const metaRole = user?.publicMetadata?.role as string | undefined
      if (metaRole === 'admin') resolved = 'admin'
      else if (metaRole === 'authority') resolved = 'authority'
      else resolved = 'user'
    }

    if (resolved === 'admin') {
      setAccess('admin')
      return
    }

    // Non-admins never see the admin UI. Route them to an existing page.
    // (Unauthenticated / locked sessions are already redirected to '/' by
    // useHavenAuth above.)
    setAccess('denied')
    router.replace(resolved === 'authority' ? '/authority' : '/home')
  }, [isLoaded, user, router])

  const isAdmin = access === 'admin'

  const [activeTab, setActiveTab] = useState<'audit' | 'users' | 'system' | 'registrations'>('audit')
  const [logs, setLogs] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [systemStats, setSystemStats] = useState<any>(null)
  const [systemConfig, setSystemConfig] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Provider Registrations & Action Requests (admin review)
  const [providerRegs, setProviderRegs] = useState<ProviderRegistration[]>([])
  const [providerRequests, setProviderRequests] = useState<ProviderActionRequest[]>([])
  const [regsLoading, setRegsLoading] = useState(false)
  const [regsError, setRegsError] = useState('')
  const [approveModal, setApproveModal] = useState<ProviderRegistration | null>(null)
  const [rejectModal, setRejectModal] = useState<ProviderRegistration | null>(null)
  const [reviewRequestModal, setReviewRequestModal] = useState<ProviderActionRequest | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [reviewAction, setReviewAction] = useState<'approve' | 'reject'>('approve')
  const [reviewNotes, setReviewNotes] = useState('')
  const [regsActionBusy, setRegsActionBusy] = useState(false)
  const [issuedToken, setIssuedToken] = useState<{ token: string; unitName: string } | null>(null)
  const [reissueModal, setReissueModal] = useState<ProviderRegistration | null>(null)
  const [reissuedToken, setReissuedToken] = useState<{ token: string; unitName: string } | null>(null)

  // Filters for audit logs
  const [page, setPage] = useState(1)
  const [totalLogs, setTotalLogs] = useState(0)
  const [actionFilter, setActionFilter] = useState('')
  const [actorFilter, setActorFilter] = useState('')
  const [caseFilter, setCaseFilter] = useState('')

  const fetchRegistrations = useCallback(async () => {
    setRegsLoading(true); setRegsError('')
    try {
      const [regsData, reqsData] = await Promise.all([
        adminGetProviderRegistrations(),
        adminGetProviderRequests(),
      ])
      setProviderRegs(regsData.registrations || [])
      setProviderRequests(reqsData.requests || [])
    } catch (e) {
      setRegsError(e instanceof Error ? e.message : 'Could not load registrations.')
    } finally { setRegsLoading(false) }
  }, [])

  useEffect(() => {
    // Gate ALL admin data fetches on confirmed admin access, so a non-admin
    // (or a still-loading session) can never trigger the admin API calls just
    // because the component mounted.
    if (!isAdmin) return
    if (activeTab === 'audit') {
      fetchLogs()
    } else if (activeTab === 'users') {
      fetchUsers()
    } else if (activeTab === 'system') {
      fetchSystemInfo()
    } else if (activeTab === 'registrations') {
      fetchRegistrations()
    }
  }, [isAdmin, activeTab, page, actionFilter, actorFilter, caseFilter, fetchRegistrations])

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const query = new URLSearchParams({ page: page.toString(), limit: '15' })
      if (actionFilter) query.append('action', actionFilter)
      if (actorFilter) query.append('actor_id', actorFilter)
      if (caseFilter) query.append('case_id', caseFilter)

      const res = await secureFetch(`/admin/audit-logs?${query.toString()}`)
      if (res.ok) {
        const data = await res.json()
        setLogs(data.logs || [])
        setTotalLogs(data.total || 0)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const res = await secureFetch('/admin/users')
      if (res.ok) {
        const data = await res.json()
        setUsers(data.users || [])
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const fetchSystemInfo = async () => {
    setLoading(true)
    try {
      const [statsRes, configRes] = await Promise.all([
        secureFetch('/admin/system-stats'),
        secureFetch('/admin/system-config')
      ])
      if (statsRes.ok) setSystemStats(await statsRes.json())
      if (configRes.ok) setSystemConfig(await configRes.json())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      const res = await secureFetch(`/admin/users/${userId}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({} as any))
        setMessage({
          type: 'success',
          text: data.message || `User ${userId} role changed to ${newRole}`,
        })
        fetchUsers()
      } else {
        const err = await res.json()
        setMessage({ type: 'error', text: err.detail || 'Failed to update role' })
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e.message || 'Error communicating with server' })
    }
    setTimeout(() => setMessage(null), 4000)
  }

  const getActionBadge = (action: string) => {
    if (action.includes('DECODED') || action.includes('OVERRIDDEN')) {
      return { bg: '#fee2e2', color: '#b91c1c' }
    }
    if (action.includes('VIEWED') || action.includes('SEARCHED')) {
      return { bg: '#e0f2fe', color: '#0369a1' }
    }
    if (action.includes('RESOLVED') || action.includes('CREATED')) {
      return { bg: '#dcfce7', color: '#15803d' }
    }
    return { bg: '#f3e8ff', color: '#7e22ce' }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans p-4 sm:p-8">
      {access !== 'admin' ? (
        // While auth/role is resolving — or while a non-admin is being redirected —
        // render a neutral gate instead of the admin UI (prevents any flash of admin
        // content and blocks admin fetches, which are gated on isAdmin above).
        <div className="max-w-6xl mx-auto flex flex-col items-center justify-center py-32 text-center">
          <Lock className="w-8 h-8 mb-4" style={{ color: colors.muted }} />
          <p className="text-slate-600 font-medium">
            {access === 'checking' ? 'Verifying access…' : 'Redirecting…'}
          </p>
        </div>
      ) : (
      <div className="max-w-6xl mx-auto">
        {/* Top Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <Link
              href="/authority"
              className="p-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-100 transition-colors text-slate-600"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div>
              <div className="flex items-center gap-2">
                <Shield className="w-7 h-7 text-pink-700" />
                <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
                  Administration & Audit Center
                </h1>
              </div>
              <p className="text-sm text-slate-500 mt-0.5">
                Security event trail, role delegation, and platform operations oversight
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (activeTab === 'audit') fetchLogs()
                else if (activeTab === 'users') fetchUsers()
                else if (activeTab === 'registrations') fetchRegistrations()
                else fetchSystemInfo()
              }}
              className="flex items-center gap-2 px-3 py-2 text-sm bg-white border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Alert banner if message */}
        {message && (
          <div
            className={`p-4 mb-6 rounded-xl border flex items-center gap-3 text-sm font-medium ${
              message.type === 'success'
                ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                : 'bg-rose-50 text-rose-800 border-rose-200'
            }`}
          >
            {message.type === 'success' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-rose-600" />
            )}
            {message.text}
          </div>
        )}

        {/* Navigation Tabs */}
        <div className="flex border-b border-slate-200 mb-6 gap-2">
          <button
            onClick={() => setActiveTab('audit')}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              activeTab === 'audit'
                ? 'border-pink-700 text-pink-700'
                : 'border-transparent text-slate-500 hover:text-slate-900'
            }`}
          >
            <Clock className="w-4 h-4" />
            Security Audit Trail
          </button>
          <button
            onClick={() => setActiveTab('users')}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              activeTab === 'users'
                ? 'border-pink-700 text-pink-700'
                : 'border-transparent text-slate-500 hover:text-slate-900'
            }`}
          >
            <Users className="w-4 h-4" />
            User & Role Management
          </button>
          <button
            onClick={() => setActiveTab('registrations')}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
              activeTab === 'registrations'
                ? 'border-pink-700 text-pink-700'
                : 'border-transparent text-slate-500 hover:text-slate-900'
            }`}
          >
            <ClipboardList className="w-4 h-4" />
            Provider Registrations
            {providerRegs.filter(r => r.status === 'PENDING_REVIEW').length > 0 && (
              <span className="ml-1 bg-amber-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
                {providerRegs.filter(r => r.status === 'PENDING_REVIEW').length}
              </span>
            )}
          </button>
                    <button
            onClick={() => setActiveTab('system')}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              activeTab === 'system'
                ? 'border-pink-700 text-pink-700'
                : 'border-transparent text-slate-500 hover:text-slate-900'
            }`}
          >
            <Activity className="w-4 h-4" />
            System Status & Configuration
          </button>
        </div>

        {/* TAB 1: Security Audit Trail */}
        {activeTab === 'audit' && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
            {/* Filter controls */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
              <div>
                <label className="block text-xs font-semibold text-slate-500 mb-1">
                  Filter by Action
                </label>
                <input
                  type="text"
                  placeholder="e.g. SOS_DECODED, CASE_VIEWED"
                  value={actionFilter}
                  onChange={(e) => {
                    setActionFilter(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 mb-1">
                  Filter by Actor ID
                </label>
                <input
                  type="text"
                  placeholder="Actor ID..."
                  value={actorFilter}
                  onChange={(e) => {
                    setActorFilter(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 mb-1">
                  Filter by Case ID
                </label>
                <input
                  type="text"
                  placeholder="Case ID..."
                  value={caseFilter}
                  onChange={(e) => {
                    setCaseFilter(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
            </div>

            {/* Audit Logs Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50/75 text-xs text-slate-500 uppercase font-semibold">
                    <th className="py-3 px-4">Timestamp</th>
                    <th className="py-3 px-4">Actor</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4">Action</th>
                    <th className="py-3 px-4">Case ID</th>
                    <th className="py-3 px-4">Result</th>
                    <th className="py-3 px-4">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {logs.map((log, idx) => {
                    const badge = getActionBadge(log.action || '')
                    return (
                      <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3 px-4 text-xs font-mono text-slate-600 whitespace-nowrap">
                          {log.timestamp ? formatServerDateTime(log.timestamp, '—') : '—'}
                        </td>
                        <td className="py-3 px-4 font-medium text-slate-800">
                          {log.actor_id || 'System'}
                        </td>
                        <td className="py-3 px-4 text-xs text-slate-600">
                          <span className="px-2 py-0.5 rounded bg-slate-100 font-mono">
                            {log.role || 'system'}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className="px-2.5 py-1 rounded-md text-xs font-semibold inline-block font-mono"
                            style={{ backgroundColor: badge.bg, color: badge.color }}
                          >
                            {log.action}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono text-xs text-slate-600">
                          {log.case_id || '—'}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center text-xs font-medium px-2 py-0.5 rounded ${
                              log.result === 'success'
                                ? 'bg-emerald-50 text-emerald-700'
                                : 'bg-rose-50 text-rose-700'
                            }`}
                          >
                            {log.result || 'success'}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-xs text-slate-500 max-w-xs truncate">
                          {log.metadata ? JSON.stringify(log.metadata) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                  {logs.length === 0 && !loading && (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-400">
                        No audit log entries found matching criteria.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100 text-sm">
              <span className="text-slate-500 text-xs">
                Showing {logs.length} of {totalLogs} total events
              </span>
              <div className="flex items-center gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50"
                >
                  Previous
                </button>
                <span className="text-xs font-semibold px-2">Page {page}</span>
                <button
                  disabled={logs.length < 15}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: User & Role Management */}
        {activeTab === 'users' && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
            <h2 className="text-lg font-bold text-slate-900 mb-4">Registered & Active Users</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50/75 text-xs text-slate-500 uppercase font-semibold">
                    <th className="py-3 px-4">User Identifier</th>
                    <th className="py-3 px-4">Safe Word Armed</th>
                    <th className="py-3 px-4">Current Role</th>
                    <th className="py-3 px-4">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {users.map((u, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3 px-4 font-mono font-medium text-slate-800">
                        {u.user_id}
                      </td>
                      <td className="py-3 px-4">
                        {u.configured_safe_word ? (
                          <span className="inline-flex items-center gap-1 text-xs text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Configured
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">Not set</span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-semibold text-xs text-pink-700">
                        <span className="px-2 py-1 rounded-md bg-pink-50 border border-pink-100">
                          {u.role || 'user'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <select
                          defaultValue={u.role || 'user'}
                          onChange={(e) => handleRoleChange(u.user_id, e.target.value)}
                          className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-pink-500 focus:outline-none"
                        >
                          <option value="user">User (Standard)</option>
                          <option value="authority">Authority (Responder)</option>
                          <option value="police">Police Officer</option>
                          <option value="protection_officer">Protection Officer</option>
                          <option value="admin">Administrator</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                  {users.length === 0 && !loading && (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-slate-400">
                        No user records found in current session database.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 3b: Provider Registrations */}
        {activeTab === 'registrations' && (
          <div className="space-y-6">
            {regsError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-sm">{regsError}</div>
            )}

            {/* Pending Registrations */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <ClipboardList className="w-5 h-5 text-pink-700" />
                <h2 className="text-base font-bold text-slate-900">Provider Registration Requests</h2>
                <span className="ml-auto text-xs text-slate-400">{providerRegs.length} total</span>
              </div>
              {regsLoading ? (
                <div className="text-center py-8 text-slate-400 text-sm">Loading…</div>
              ) : providerRegs.length === 0 ? (
                <div className="text-center py-8 text-slate-400 text-sm">No registration requests yet.</div>
              ) : (
                <div className="space-y-4">
                  {providerRegs.map(reg => (
                    <div key={reg.registration_id} className="border border-slate-100 rounded-xl p-4">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="flex-1 min-w-0">
                          <div className="font-bold text-slate-900 text-sm">{reg.unit_name}</div>
                          <div className="text-xs text-slate-500 mt-0.5">
                            {reg.provider_category}{reg.organization ? ` · ${reg.organization}` : ''}{reg.jurisdiction ? ` · ${reg.jurisdiction}` : ''}
                          </div>
                          {reg.contact && <div className="text-xs text-slate-400 mt-0.5">Contact: {reg.contact}</div>}
                          {reg.auth_reference && <div className="text-xs text-slate-400 mt-0.5">Auth Ref: {reg.auth_reference}</div>}
                          {reg.badge_number && <div className="text-xs text-slate-400 mt-0.5">Badge: {reg.badge_number}</div>}
                          {reg.capabilities?.length > 0 && <div className="text-xs text-slate-400 mt-0.5">Capabilities: {reg.capabilities.join(', ')}</div>}
                          {reg.notes && <div className="text-xs text-slate-400 mt-0.5">Notes: {reg.notes}</div>}
                          {reg.status === 'REJECTED' && reg.rejection_reason && (
                            <div className="mt-2 text-xs text-red-700 bg-red-50 px-2 py-1 rounded">Rejected: {reg.rejection_reason}</div>
                          )}
                          {reg.status === 'APPROVED' && reg.live_provider && (
                            <div className="mt-2 text-xs text-emerald-700 bg-emerald-50 px-2 py-1 rounded">
                              Provider created · {reg.live_provider.provisioning_state}
                              {reg.live_provider.verified ? ' · Verified' : ' · Awaiting verification'}
                            </div>
                          )}
                          <div className="text-xs text-slate-300 mt-1">
                            Submitted by: {reg.submitted_by} ({reg.submitted_by_role}) · {new Date(reg.submitted_at).toLocaleString()}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                            reg.status === 'PENDING_REVIEW' ? 'bg-amber-100 text-amber-800' :
                            reg.status === 'APPROVED' ? 'bg-emerald-100 text-emerald-800' :
                            'bg-red-100 text-red-800'
                          }`}>{reg.status}</span>
                          {reg.status === 'PENDING_REVIEW' && (
                            <div className="flex gap-2">
                              <button
                                onClick={() => { setApproveModal(reg) }}
                                className="px-3 py-1 text-xs font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
                              >
                                Approve
                              </button>
                              <button
                                onClick={() => { setRejectModal(reg); setRejectReason('') }}
                                className="px-3 py-1 text-xs font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700"
                              >
                                Reject
                              </button>
                            </div>
                          )}
                          {reg.status === 'APPROVED' && reg.live_provider && !reg.live_provider.verified && (
                            <button
                              onClick={() => { setReissueModal(reg); setReissuedToken(null) }}
                              className="px-3 py-1 text-xs font-semibold bg-violet-600 text-white rounded-lg hover:bg-violet-700"
                              title="Provider hasn't set their password yet — reissue a fresh setup token"
                            >
                              🔑 Reissue Token
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Action Requests (Suspension / Revocation) */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <UserCheck className="w-5 h-5 text-pink-700" />
                <h2 className="text-base font-bold text-slate-900">Suspension &amp; Revocation Requests</h2>
                <span className="ml-auto text-xs text-slate-400">{providerRequests.length} total</span>
              </div>
              {regsLoading ? (
                <div className="text-center py-8 text-slate-400 text-sm">Loading…</div>
              ) : providerRequests.length === 0 ? (
                <div className="text-center py-8 text-slate-400 text-sm">No action requests pending.</div>
              ) : (
                <div className="space-y-4">
                  {providerRequests.map(req => (
                    <div key={req.request_id} className="border border-slate-100 rounded-xl p-4">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="flex-1 min-w-0">
                          <div className="font-bold text-slate-900 text-sm">
                            {req.request_type}: {req.display_label || req.responder_id}
                          </div>
                          {req.badge_number && <div className="text-xs text-slate-400">Badge: {req.badge_number}</div>}
                          <div className="text-xs text-slate-500 mt-1">Reason: {req.reason}</div>
                          <div className="text-xs text-slate-300 mt-1">
                            Submitted by {req.submitted_by} · {new Date(req.submitted_at).toLocaleString()}
                          </div>
                          {req.review_notes && (
                            <div className="mt-1 text-xs text-slate-500">Review notes: {req.review_notes}</div>
                          )}
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                            req.status === 'PENDING_REVIEW' ? 'bg-amber-100 text-amber-800' :
                            req.status === 'APPROVED' ? 'bg-emerald-100 text-emerald-800' :
                            'bg-red-100 text-red-800'
                          }`}>{req.status}</span>
                          {req.status === 'PENDING_REVIEW' && (
                            <button
                              onClick={() => { setReviewRequestModal(req); setReviewAction('approve'); setReviewNotes('') }}
                              className="px-3 py-1 text-xs font-semibold bg-pink-700 text-white rounded-lg hover:bg-pink-800"
                            >
                              Review
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Modals */}
        {approveModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                <h3 className="font-bold text-slate-900">Approve Registration</h3>
                <button onClick={() => setApproveModal(null)} className="ml-auto text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
              </div>
              <p className="text-sm text-slate-600 mb-4">
                Approve <strong>{approveModal.unit_name}</strong>? This will create an inert provider account and issue a one-time setup token.
              </p>
              {issuedToken && (
                <div className="mb-4">
                  <div className="text-xs font-semibold text-amber-700 mb-1">One-time setup token (copy now — not shown again):</div>
                  <code className="block text-xs bg-slate-50 border border-slate-200 p-3 rounded-lg break-all">{issuedToken.token}</code>
                </div>
              )}
              {!issuedToken && (
                <div className="flex justify-end gap-2">
                  <button onClick={() => setApproveModal(null)} className="px-4 py-2 text-sm border border-slate-200 rounded-lg">Cancel</button>
                  <button
                    disabled={regsActionBusy}
                    onClick={async () => {
                      setRegsActionBusy(true)
                      try {
                        const res = await adminApproveRegistration(approveModal.registration_id)
                        setIssuedToken({ token: res.setup_token, unitName: approveModal.unit_name })
                        fetchRegistrations()
                      } catch (e) {
                        setRegsError(e instanceof Error ? e.message : 'Approval failed.')
                        setApproveModal(null)
                      } finally { setRegsActionBusy(false) }
                    }}
                    className="px-4 py-2 text-sm font-semibold bg-emerald-600 text-white rounded-lg disabled:opacity-60"
                  >
                    {regsActionBusy ? 'Approving…' : 'Confirm Approval'}
                  </button>
                </div>
              )}
              {issuedToken && (
                <div className="flex justify-end">
                  <button onClick={() => { setApproveModal(null); setIssuedToken(null) }} className="px-4 py-2 text-sm font-semibold bg-emerald-600 text-white rounded-lg">Done</button>
                </div>
              )}
            </div>
          </div>
        )}

        {rejectModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-5 h-5 text-red-600" />
                <h3 className="font-bold text-slate-900">Reject Registration</h3>
                <button onClick={() => setRejectModal(null)} className="ml-auto text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
              </div>
              <p className="text-sm text-slate-600 mb-3">
                Reject <strong>{rejectModal.unit_name}</strong>? Please provide a reason.
              </p>
              <textarea
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                rows={3}
                placeholder="Rejection reason (required)…"
                className="w-full text-sm border border-slate-200 rounded-lg p-3 mb-3 focus:ring-2 focus:ring-pink-500 focus:outline-none"
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => setRejectModal(null)} className="px-4 py-2 text-sm border border-slate-200 rounded-lg">Cancel</button>
                <button
                  disabled={regsActionBusy || !rejectReason.trim()}
                  onClick={async () => {
                    setRegsActionBusy(true)
                    try {
                      await adminRejectRegistration(rejectModal.registration_id, rejectReason.trim())
                      setRejectModal(null)
                      fetchRegistrations()
                    } catch (e) {
                      setRegsError(e instanceof Error ? e.message : 'Rejection failed.')
                      setRejectModal(null)
                    } finally { setRegsActionBusy(false) }
                  }}
                  className="px-4 py-2 text-sm font-semibold bg-red-600 text-white rounded-lg disabled:opacity-60"
                >
                  {regsActionBusy ? 'Rejecting…' : 'Confirm Rejection'}
                </button>
              </div>
            </div>
          </div>
        )}

        {reviewRequestModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-5 h-5 text-pink-700" />
                <h3 className="font-bold text-slate-900">Review Action Request</h3>
                <button onClick={() => setReviewRequestModal(null)} className="ml-auto text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
              </div>
              <p className="text-sm text-slate-600 mb-1">
                <strong>{reviewRequestModal.request_type}</strong>: {reviewRequestModal.display_label || reviewRequestModal.responder_id}
              </p>
              <p className="text-xs text-slate-500 mb-3">Reason: {reviewRequestModal.reason}</p>
              <div className="mb-3">
                <label className="block text-xs font-semibold text-slate-500 mb-1">Decision</label>
                <select value={reviewAction} onChange={e => setReviewAction(e.target.value as 'approve' | 'reject')}
                  className="w-full text-sm border border-slate-200 rounded-lg p-2 focus:ring-2 focus:ring-pink-500 focus:outline-none">
                  <option value="approve">Approve — execute the {reviewRequestModal.request_type.toLowerCase()}</option>
                  <option value="reject">Reject — deny this request</option>
                </select>
              </div>
              <textarea
                value={reviewNotes}
                onChange={e => setReviewNotes(e.target.value)}
                rows={2}
                placeholder="Review notes (optional)…"
                className="w-full text-sm border border-slate-200 rounded-lg p-3 mb-3 focus:ring-2 focus:ring-pink-500 focus:outline-none"
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => setReviewRequestModal(null)} className="px-4 py-2 text-sm border border-slate-200 rounded-lg">Cancel</button>
                <button
                  disabled={regsActionBusy}
                  onClick={async () => {
                    setRegsActionBusy(true)
                    try {
                      await adminReviewProviderRequest(reviewRequestModal.request_id, reviewAction, reviewNotes.trim() || undefined)
                      setReviewRequestModal(null)
                      fetchRegistrations()
                    } catch (e) {
                      setRegsError(e instanceof Error ? e.message : 'Review failed.')
                      setReviewRequestModal(null)
                    } finally { setRegsActionBusy(false) }
                  }}
                  className={`px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-60 ${reviewAction === 'approve' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-red-600 hover:bg-red-700'}`}
                >
                  {regsActionBusy ? 'Submitting…' : reviewAction === 'approve' ? 'Approve' : 'Reject'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Reissue Setup Token Modal */}
        {reissueModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-lg">🔑</span>
                <h3 className="font-bold text-slate-900">Reissue Setup Token</h3>
                <button onClick={() => { setReissueModal(null); setReissuedToken(null) }} className="ml-auto text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
              </div>
              {!reissuedToken ? (
                <>
                  <p className="text-sm text-slate-600 mb-4">
                    Generate a fresh one-time setup token for <strong>{reissueModal.unit_name}</strong>.
                    The previous token (if any) will be invalidated.
                  </p>
                  <div className="flex justify-end gap-2">
                    <button onClick={() => { setReissueModal(null) }} className="px-4 py-2 text-sm border border-slate-200 rounded-lg">Cancel</button>
                    <button
                      disabled={regsActionBusy}
                      onClick={async () => {
                        if (!reissueModal.live_provider?.responder_id) {
                          setRegsError('No responder_id found on this registration.')
                          setReissueModal(null)
                          return
                        }
                        setRegsActionBusy(true)
                        try {
                          const res = await adminReissueSetupToken(reissueModal.live_provider.responder_id)
                          setReissuedToken({ token: res.setup_token, unitName: reissueModal.unit_name })
                        } catch (e) {
                          setRegsError(e instanceof Error ? e.message : 'Failed to reissue token.')
                          setReissueModal(null)
                        } finally { setRegsActionBusy(false) }
                      }}
                      className="px-4 py-2 text-sm font-semibold bg-violet-600 text-white rounded-lg disabled:opacity-60"
                    >
                      {regsActionBusy ? 'Generating…' : 'Generate New Token'}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="mb-3">
                    <div className="text-xs font-semibold text-amber-700 mb-1">New one-time setup token — copy now, not shown again:</div>
                    <code className="block text-xs bg-slate-50 border border-slate-200 p-3 rounded-lg break-all select-all">{reissuedToken.token}</code>
                  </div>
                  <div className="mb-4 p-3 bg-violet-50 border border-violet-200 rounded-lg">
                    <div className="text-xs font-semibold text-violet-700 mb-1">Provider setup page URL:</div>
                    <code className="text-xs text-violet-800 break-all select-all">
                      {typeof window !== 'undefined' ? window.location.origin : ''}/auth/responder-setup
                    </code>
                    <div className="text-xs text-violet-600 mt-1">Send both the token and this URL to the provider.</div>
                  </div>
                  <div className="flex justify-end">
                    <button onClick={() => { setReissueModal(null); setReissuedToken(null) }} className="px-4 py-2 text-sm font-semibold bg-violet-600 text-white rounded-lg">Done</button>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* TAB 3: System Status & Configuration */}
        {activeTab === 'system' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Health & Metrics Card */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <Server className="w-5 h-5 text-pink-700" />
                <h2 className="text-base font-bold text-slate-900">System Metrics & Health</h2>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
                  <div className="text-xs text-slate-500 font-medium">Total SOS Cases</div>
                  <div className="text-2xl font-bold text-slate-900 mt-1">
                    {systemStats?.metrics?.total_cases ?? '—'}
                  </div>
                </div>
                <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
                  <div className="text-xs text-slate-500 font-medium">Active Users</div>
                  <div className="text-2xl font-bold text-slate-900 mt-1">
                    {systemStats?.metrics?.total_users ?? '—'}
                  </div>
                </div>
                <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
                  <div className="text-xs text-slate-500 font-medium">Voice SOS Events</div>
                  <div className="text-2xl font-bold text-slate-900 mt-1">
                    {systemStats?.metrics?.total_events ?? '—'}
                  </div>
                </div>
                <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
                  <div className="text-xs text-slate-500 font-medium">Audit Trail Records</div>
                  <div className="text-2xl font-bold text-slate-900 mt-1">
                    {systemStats?.metrics?.total_audit_records ?? '—'}
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between text-xs py-2 border-t border-slate-100 text-slate-600">
                <span>Database Connection</span>
                <span className="text-emerald-700 font-semibold flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Connected (MongoDB Atlas)
                </span>
              </div>
            </div>

            {/* Platform Features Card */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <Activity className="w-5 h-5 text-pink-700" />
                <h2 className="text-base font-bold text-slate-900">Feature Modules</h2>
              </div>
              <div className="space-y-2.5 text-xs">
                {systemConfig?.features &&
                  Object.entries(systemConfig.features).map(([feat, statusVal], i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between py-1.5 px-3 rounded-lg bg-slate-50 border border-slate-100"
                    >
                      <span className="capitalize font-medium text-slate-700">
                        {feat.replace(/_/g, ' ')}
                      </span>
                      <span className="font-semibold text-emerald-700 font-mono">
                        {typeof statusVal === 'boolean'
                          ? statusVal
                            ? 'ENABLED'
                            : 'DISABLED'
                          : String(statusVal).toUpperCase()}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  )
}
