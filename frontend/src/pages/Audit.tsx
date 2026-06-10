import { useEffect, useState } from 'react'
import {
  fetchAdverseAction,
  fetchAudit,
  fetchComplianceHealth,
  fetchReports,
} from '../api/client'
import type {
  AdverseAction,
  AuditTrail,
  ComplianceHealth,
  ReportRow,
} from '../types/accord'
import PeriodFilter, { type Period, periodParam } from '../components/PeriodFilter'
import { CardSkeleton, ErrorState } from '../components/states'
import { downloadJson } from '../utils/export'

// Report metadata not in the API — frequency + display status per report id.
const REPORT_META: Record<string, { frequency: string; status: string; action: string }> = {
  hmda_lar: { frequency: 'Quarterly', status: 'submitted', action: 'View' },
  fair_lending: { frequency: 'Monthly', status: 'clean', action: 'View' },
  override_justification: { frequency: 'Monthly', status: 'complete', action: 'View' },
  ai_model: { frequency: 'Quarterly', status: 'validated', action: 'View' },
  examiner_package: { frequency: 'On demand', status: 'ready', action: 'Generate' },
}
const OVERDUE_DAYS = 30

function kpiColor(value: number, good: number, warn: number, invert = false): string {
  const v = value
  if (invert) {
    if (v === 0) return 'text-green-600'
    return v > warn ? 'text-red-600' : 'text-amber-600'
  }
  if (v >= good) return 'text-green-600'
  if (v >= warn) return 'text-amber-600'
  return 'text-red-600'
}

export default function Audit() {
  const [health, setHealth] = useState<ComplianceHealth | null>(null)
  const [adverse, setAdverse] = useState<AdverseAction[]>([])
  const [adverseTotal, setAdverseTotal] = useState(0)
  const [reports, setReports] = useState<ReportRow[]>([])
  const [period, setPeriod] = useState<Period>('all')
  const [dashError, setDashError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // Audit trail search
  const [appInput, setAppInput] = useState('')
  const [trail, setTrail] = useState<AuditTrail | null>(null)
  const [trailLoading, setTrailLoading] = useState(false)
  const [trailError, setTrailError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  useEffect(() => {
    let alive = true
    const p = periodParam(period)
    setDashError(false)
    setHealth(null)
    Promise.all([fetchComplianceHealth(p), fetchAdverseAction(p), fetchReports(p)])
      .then(([h, a, r]) => {
        if (!alive) return
        setHealth(h)
        setAdverse(a.adverse_actions)
        setAdverseTotal(a.total)
        setReports(r.reports)
      })
      .catch((e) => {
        console.error('Audit load failed:', e)
        if (alive) setDashError(true)
      })
    return () => {
      alive = false
    }
  }, [period, reloadKey])

  async function searchTrail(id: string) {
    const appId = id.trim()
    if (!appId) return
    setTrailLoading(true)
    setTrailError(null)
    setTrail(null)
    try {
      setTrail(await fetchAudit(appId))
    } catch (e) {
      console.error('Audit trail load failed:', e)
      setTrailError(`No audit records found for ${appId}.`)
    } finally {
      setTrailLoading(false)
    }
  }

  const overdue = adverse.filter((a) => (a.days_since_decision ?? 0) > OVERDUE_DAYS)

  // Examiner package: compliance health + adverse actions + reports + any
  // searched decision trail (versions, authority chain, SLA), as JSON.
  // (A true ZIP needs backend support; JSON carries the same records for now.)
  function exportExaminerPackage() {
    downloadJson(
      {
        exported_at: new Date().toISOString(),
        period,
        compliance_health: health,
        adverse_actions: { total: adverseTotal, items: adverse },
        reports,
        audit_trail: trail,
      },
      'accord_examiner_package',
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-10 px-6 py-6">
      {/* 1. Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit &amp; Compliance</h1>
          <p className="text-sm text-slate-500">Regulatory reporting and decision audit trail</p>
        </div>
        <div className="flex items-center gap-3">
          <PeriodFilter value={period} onChange={setPeriod} />
          <button
            onClick={exportExaminerPackage}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            📦 Export Examiner Package
          </button>
        </div>
      </div>

      {/* 2. Compliance health */}
      {dashError ? (
        <ErrorState message="Could not load compliance data." onRetry={() => setReloadKey((k) => k + 1)} />
      ) : !health ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard label="HMDA Completeness" value={`${health.hmda_pct}%`} color={kpiColor(health.hmda_pct, 95, 80)} />
          <KpiCard label="Adverse Action Pending" value={health.adverse_pending.toLocaleString()}
            color={health.adverse_pending > 0 ? 'text-amber-600' : 'text-slate-900'} />
          <KpiCard label="Overrides This Month" value={health.overrides.toLocaleString()}
            color={health.overrides > 0 ? 'text-amber-600' : 'text-slate-900'} />
          <KpiCard label="SLA Compliance" value={`${health.sla_pct}%`} color={kpiColor(health.sla_pct, 90, 75)} />
        </div>
      )}

      {/* 3. Audit trail search */}
      <section className="space-y-3">
        <h2 className="text-lg font-bold text-slate-900">Decision Audit Trail</h2>
        <form
          onSubmit={(e) => { e.preventDefault(); searchTrail(appInput) }}
          className="flex max-w-xl items-center gap-2"
        >
          <input
            value={appInput}
            onChange={(e) => setAppInput(e.target.value)}
            placeholder="Enter application ID (e.g. APP-SC04-001)"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
          <button type="submit" className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark">
            Search
          </button>
        </form>

        {trailLoading && <p className="text-sm text-slate-400">Loading audit trail…</p>}
        {trailError && <p className="text-sm text-red-600">{trailError}</p>}

        {trail && trail.versions.length === 0 && (
          <p className="text-sm text-slate-400">No audit records found for {trail.application_id}.</p>
        )}

        {trail && trail.versions.length > 0 && (() => {
          const exceeds = trail.versions.filter(
            (v) => v.mode === 'human_approval' && !(v.human_action != null && v.reviewer != null && v.reviewer !== 'system'),
          )
          return (
            <div className="space-y-5">
              {/* A. Version history — version badges + colored block/approve highlight */}
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <div className="mb-3 text-sm font-semibold text-slate-700">Version history</div>
                <ul className="space-y-2">
                  {trail.versions.map((v, i) => {
                    const isBlock = v.outcome === 'block'
                    const isAllow = v.outcome === 'allow'
                    const dot = isBlock ? 'bg-red-500' : isAllow ? 'bg-green-500' : 'bg-slate-300'
                    const action = v.human_action ? `Human ${v.human_action}` : `AI proposed ${v.outcome.toUpperCase()}`
                    const ts = v.acted_at ?? v.decided_at
                    return (
                      <li key={v.decision_id} className="flex gap-3 text-sm">
                        <span className="relative flex flex-col items-center pt-1.5">
                          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
                          {i < trail.versions.length - 1 && <span className="mt-1 w-px flex-1 bg-slate-200" />}
                        </span>
                        <div className={`flex-1 rounded-lg px-3 py-1.5 ${isBlock ? 'bg-red-50' : isAllow ? 'bg-green-50' : ''}`}>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-bold text-white">v{v.version}</span>
                            <span className="font-medium text-slate-800">{v.persona}</span>
                            <span className="text-slate-600">· {action}</span>
                            {v.reviewer && v.reviewer !== 'system' && <span className="text-slate-500">by {v.reviewer}</span>}
                          </div>
                          <div className="text-xs text-slate-400">{ts ? new Date(ts).toLocaleString() : '—'}</div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>

              {/* B. Authority chain */}
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700">
                  Authority chain
                </div>
                {exceeds.length > 0 ? (
                  <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700">
                    ⚠ {exceeds.length} decision{exceeds.length === 1 ? '' : 's'} exceed reviewer authority — human sign-off required.
                  </div>
                ) : (
                  <div className="border-b border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-700">
                    ✓ All decisions within authority.
                  </div>
                )}
                <table className="min-w-full text-sm">
                  <thead className="text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="px-4 py-2 text-left">Persona</th>
                      <th className="px-4 py-2 text-left">Reviewer</th>
                      <th className="px-4 py-2 text-left">Level</th>
                      <th className="px-4 py-2 text-left">Action</th>
                      <th className="px-4 py-2 text-left">Required</th>
                      <th className="px-4 py-2 text-left">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {trail.versions.map((v) => {
                      const needsHuman = v.mode === 'human_approval'
                      const signed = v.human_action != null && v.reviewer != null && v.reviewer !== 'system'
                      const within = !needsHuman || signed
                      const level = v.reviewer && v.reviewer !== 'system' ? 'Human' : 'Automated'
                      const required = v.mode === 'human_approval' ? 'Human sign-off' : v.mode === 'recommend' ? 'Human review' : 'Auto'
                      return (
                        <tr key={v.decision_id}>
                          <td className="px-4 py-2 text-slate-700">{v.persona}</td>
                          <td className="px-4 py-2 text-slate-600">{v.reviewer ?? 'system'}</td>
                          <td className="px-4 py-2 text-slate-500">{level}</td>
                          <td className="px-4 py-2 text-slate-600">{v.human_action ?? '—'}</td>
                          <td className="px-4 py-2 text-slate-500">{required}</td>
                          <td className="px-4 py-2">
                            <span className={within ? 'font-medium text-green-700' : 'font-medium text-red-600'}>
                              {within ? '✓ Within authority' : '⚠ Exceeds'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* C. SLA compliance */}
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <div className="mb-3 text-sm font-semibold text-slate-700">SLA compliance</div>
                <ul className="space-y-2">
                  {trail.sla.map((s) => {
                    const target = s.sla_seconds ?? 0
                    const actual = s.actual_seconds ?? 0
                    const pct = target ? Math.min((actual / target) * 100, 100) : 0
                    return (
                      <li key={s.decision_id} className="flex items-center gap-3 text-sm">
                        <span className="w-40 shrink-0 text-slate-700">{s.persona}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100">
                          <div className={`h-full ${s.met ? 'bg-green-500' : 'bg-red-500'}`} style={{ width: `${pct}%` }} />
                        </div>
                        <span className="w-28 shrink-0 text-right text-xs text-slate-500">
                          {actual.toFixed(1)}s / {target.toFixed(0)}s
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            </div>
          )
        })()}
      </section>

      {/* 4. Adverse action tracker */}
      <section className="space-y-3">
        <h2 className="text-lg font-bold text-slate-900">Adverse Action Notices</h2>
        {overdue.length > 0 && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700">
            ⚠ {overdue.length} notice{overdue.length === 1 ? '' : 's'} overdue (&gt; {OVERDUE_DAYS} days)
          </div>
        )}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {adverseTotal.toLocaleString()} declines awaiting notice · showing {adverse.length}
          </div>
          <table className="min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">App ID</th>
                <th className="px-4 py-2 text-left">Borrower</th>
                <th className="px-4 py-2 text-left">Reason</th>
                <th className="px-4 py-2 text-right">Days Since</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {adverse.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-400">No adverse actions pending.</td></tr>
              ) : (
                adverse.map((a) => {
                  const isOverdue = (a.days_since_decision ?? 0) > OVERDUE_DAYS
                  return (
                    <tr key={a.application_id}>
                      <td className="px-4 py-2 font-mono text-xs text-slate-500">{a.application_id}</td>
                      <td className="px-4 py-2 text-slate-700">{a.borrower}</td>
                      <td className="px-4 py-2 text-slate-500">{a.block_reason}</td>
                      <td className="px-4 py-2 text-right text-slate-600">{a.days_since_decision ?? '—'}</td>
                      <td className="px-4 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          isOverdue ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                        }`}>
                          {isOverdue ? 'Overdue' : 'Pending'}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => showToast('Coming in next release')} className="text-xs font-medium text-brand hover:underline">Generate Notice</button>
                        <span className="px-1 text-slate-300">·</span>
                        <button onClick={() => showToast('Coming in next release')} className="text-xs font-medium text-slate-500 hover:underline">Mark Sent</button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. Reports library */}
      <section className="space-y-3">
        <h2 className="text-lg font-bold text-slate-900">Compliance Reports</h2>
        <div className="flex items-center gap-2.5 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm text-blue-800">
          <span className="text-base">🔒</span>
          <span>
            These regulatory reports require <span className="font-semibold">governance admin access</span>.
            Generating or exporting any report is audit-logged.
          </span>
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">Report</th>
                <th className="px-4 py-2 text-left">Frequency</th>
                <th className="px-4 py-2 text-left">Last Run</th>
                <th className="px-4 py-2 text-right">Records</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {reports.map((r) => {
                const meta = REPORT_META[r.id] ?? { frequency: '—', status: r.status, action: 'View' }
                return (
                  <tr key={r.id}>
                    <td className="px-4 py-2 font-medium text-slate-800">{r.name}</td>
                    <td className="px-4 py-2 text-slate-500">{meta.frequency}</td>
                    <td className="px-4 py-2 text-slate-500">{r.last_run ? new Date(r.last_run).toLocaleDateString() : '—'}</td>
                    <td className="px-4 py-2 text-right text-slate-600">{r.record_count.toLocaleString()}</td>
                    <td className="px-4 py-2">
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">{meta.status}</span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => showToast('Coming in next release')}
                        className="text-sm font-medium text-brand hover:underline"
                      >
                        {meta.action}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}

function KpiCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${color}`}>{value}</div>
    </div>
  )
}
