'use client'

import React, { useState, useEffect } from 'react'
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
  ArrowLeft
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useUser } from '@clerk/nextjs'
import { secureFetch } from '@/lib/api'
import { formatServerDateTime } from '@/lib/datetime'
import { useHavenAuth } from '@/hooks/useHavenAuth'

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

  const [activeTab, setActiveTab] = useState<'audit' | 'users' | 'system'>('audit')
  const [logs, setLogs] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [systemStats, setSystemStats] = useState<any>(null)
  const [systemConfig, setSystemConfig] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Filters for audit logs
  const [page, setPage] = useState(1)
  const [totalLogs, setTotalLogs] = useState(0)
  const [actionFilter, setActionFilter] = useState('')
  const [actorFilter, setActorFilter] = useState('')
  const [caseFilter, setCaseFilter] = useState('')

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
    }
  }, [isAdmin, activeTab, page, actionFilter, actorFilter, caseFilter])

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
