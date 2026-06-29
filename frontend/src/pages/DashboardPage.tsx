import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import { useAuth } from '../context/AuthContext'
import {
  fetchDashboardSummary, fetchDashboardTeam, fetchDashboardAttention,
} from '../api/client'

// ── helpers ──────────────────────────────────────────────────────────────────
const DASH = '—'
function pretty(s?: string | null): string {
  if (!s) return DASH
  return String(s).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
function money(n: number | null | undefined): string {
  return n == null ? DASH : `$${Math.round(n).toLocaleString()}`
}
function initials(name?: string | null): string {
  const s = String(name || '').trim()
  if (!s) return '?'
  const p = s.split(/\s+/)
  return ((p[0]?.[0] ?? '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase() || '?'
}

const SLA_TAG: Record<string, string> = {
  Breach: 'bg-red-50 text-red-700',
  'At Risk': 'bg-amber-50 text-amber-700',
  'Due Soon': 'bg-blue-50 text-blue-700',
}

// Flagged placeholder AI insights — replace with a real aggregate query in v2.
const AI_INSIGHTS = [
  'Income verification is the most common blocking condition across active files.',
  'Fraud reviews are averaging the longest time-in-queue of any review area.',
  'Workload is uneven — consider rebalancing files from over-capacity underwriters.',
  'Most SLA breaches cluster in the 16–30 day aging bucket.',
]

export default function DashboardPage() {
  const navigate = useNavigate()
  const { effectiveUser } = useAuth()
  const [summary, setSummary] = useState<any>(null)
  const [team, setTeam] = useState<any[]>([])
  const [attention, setAttention] = useState<any[]>([])
  const [attentionTotal, setAttentionTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [activeNav, setActiveNav] = useState('Team Overview')
  const [officerFilter, setOfficerFilter] = useState('all')

  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    Promise.all([
      fetchDashboardSummary(),
      fetchDashboardTeam().catch(() => ({ members: [] })),
      fetchDashboardAttention(12).catch(() => ({ files: [], total: 0 })),
    ])
      .then(([s, t, a]) => {
        if (!alive) return
        setSummary(s)
        setTeam(t.members ?? [])
        setAttention(a.files ?? [])
        setAttentionTotal(a.total ?? (a.files?.length ?? 0))
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Failed to load dashboard'))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [reload])

  const officers = useMemo(
    () => [...new Set(attention.map((f) => f.assigned_to).filter(Boolean))] as string[],
    [attention],
  )
  const shownAttention = useMemo(
    () => (officerFilter === 'all' ? attention : attention.filter((f) => f.assigned_to === officerFilter)),
    [attention, officerFilter],
  )

  if (loading) return <div className="p-12 text-center text-sm text-slate-400">Loading dashboard…</div>
  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-red-600">{error}</p>
        <button onClick={() => setReload((r) => r + 1)} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white">Retry</button>
      </div>
    )
  }

  const s = summary ?? {}
  const active = s.active_files ?? 0
  const slaBreach = s.sla_breaches ?? 0
  const needs = s.needs_attention ?? 0
  const atRisk = Math.max(0, needs - slaBreach)
  const onTrack = Math.max(0, active - needs)
  const donut = [
    { name: 'On Track', value: onTrack, fill: '#16a34a' },
    { name: 'At Risk', value: atRisk, fill: '#d97706' },
    { name: 'SLA Breach', value: slaBreach, fill: '#dc2626' },
  ].filter((d) => d.value > 0)
  const donutTotal = donut.reduce((a, d) => a + d.value, 0)

  const KPIS = [
    { label: 'Active Files', value: active },
    { label: 'Needs Attention', value: needs },
    { label: 'Pending Customer', value: s.pending_customer ?? 0 },
    { label: 'Ready to Decide', value: s.ready_to_decide ?? 0 },
    { label: 'SLA Breaches', value: slaBreach },
    { label: 'Avg Decision Time', value: s.avg_decision_days == null ? DASH : `${s.avg_decision_days}d` },
  ]

  const byStatus: Array<{ status: string; count: number }> = s.by_status ?? []
  const maxStatus = Math.max(1, ...byStatus.map((b) => b.count))
  const aging: Array<{ bucket: string; count: number }> = s.aging ?? []
  const maxAge = Math.max(1, ...aging.map((b) => b.count))
  const AGE_COLORS = ['#16a34a', '#65a30d', '#d97706', '#ea580c', '#dc2626']

  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* ── LEFT SIDEBAR ── */}
      <aside className="hidden w-[200px] shrink-0 border-r border-slate-200 bg-white lg:block">
        <nav className="p-3">
          {[
            ['Team Overview', null], ['All Applications', null],
            ['Queues', active], ['SLA Dashboard', null],
            ['Escalations', slaBreach], ['Reports', null],
            ['Workload', null], ['Settings', null],
          ].map(([label, badge]) => (
            <button
              key={label as string}
              onClick={() => setActiveNav(label as string)}
              className={`mb-0.5 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm ${activeNav === label ? 'bg-[#14532d]/10 font-semibold text-[#14532d]' : 'text-slate-600 hover:bg-slate-50'}`}
            >
              <span>{label as string}</span>
              {badge != null && (badge as number) > 0 && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${label === 'Escalations' ? 'bg-red-100 text-red-700' : 'bg-slate-200 text-slate-600'}`}>{badge as number}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-3 text-xs">
          <div className="mb-2 font-semibold uppercase tracking-wide text-slate-400">Filters</div>
          <FilterStub label="Channel" note="v2" />
          <FilterStub label="Loan Purpose" note="v2" />
          <div className="mb-2">
            <div className="mb-1 text-[11px] text-slate-500">Loan Officer</div>
            <select value={officerFilter} onChange={(e) => setOfficerFilter(e.target.value)} className="w-full rounded-md border border-slate-200 px-2 py-1 text-xs">
              <option value="all">All</option>
              {officers.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <FilterStub label="Product" note="v2" />
          <button onClick={() => setOfficerFilter('all')} className="mt-1 text-[11px] font-medium text-blue-600 hover:underline">Clear all</button>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <main className="min-w-0 flex-1 px-5 py-5">
        <h1 className="mb-1 text-lg font-bold text-slate-900">Pipeline Overview</h1>
        <p className="mb-4 text-xs text-slate-400">{effectiveUser?.name ? `${effectiveUser.name} · ` : ''}{pretty(effectiveUser?.role)} view</p>

        {/* KPI BAR */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {KPIS.map((k) => (
            <div key={k.label} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">{k.label}</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{k.value}</div>
              <div className="mt-0.5 text-[10px] text-slate-300">vs yesterday n/a</div>
            </div>
          ))}
        </div>

        {/* CHARTS */}
        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
          {/* Donut */}
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="text-xs font-semibold text-slate-700">Pipeline Health</div>
            <div className="relative mx-auto mt-2 h-40 w-40">
              {donutTotal > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={donut} dataKey="value" innerRadius={48} outerRadius={70} paddingAngle={2}>
                      {donut.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-slate-400">No active files</div>
              )}
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xl font-bold text-slate-900">{active}</span>
                <span className="text-[10px] text-slate-400">active</span>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap justify-center gap-2 text-[10px]">
              {donut.map((d) => (
                <span key={d.name} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: d.fill }} />{d.name} {d.value}</span>
              ))}
            </div>
          </div>

          {/* Status funnel (real statuses; the idealized 7-stage funnel isn't modelled) */}
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="text-xs font-semibold text-slate-700">Files by Status <span className="font-normal text-slate-300">· live</span></div>
            <div className="mt-3 space-y-1.5">
              {byStatus.length === 0 ? <div className="text-xs text-slate-400">No data</div> : byStatus.map((b, i) => (
                <div key={b.status} className="flex items-center gap-2">
                  <div className="w-24 shrink-0 text-right text-[10px] text-slate-500">{pretty(b.status)}</div>
                  <div className="h-4 rounded bg-[#14532d]" style={{ width: `${Math.max(6, (b.count / maxStatus) * 100 - i * 4)}%`, opacity: 0.85 - i * 0.08 }} />
                  <div className="text-[10px] font-semibold text-slate-600">{b.count}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Aging */}
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="text-xs font-semibold text-slate-700">Aging <span className="font-normal text-slate-300">· active assignments</span></div>
            <div className="mt-3 space-y-1.5">
              {aging.length === 0 ? <div className="text-xs text-slate-400">No active assignments</div> : aging.map((b, i) => (
                <div key={b.bucket} className="flex items-center gap-2">
                  <div className="w-20 shrink-0 text-right text-[10px] text-slate-500">{b.bucket}</div>
                  <div className="h-4 rounded" style={{ width: `${Math.max(4, (b.count / maxAge) * 100)}%`, backgroundColor: AGE_COLORS[i] }} />
                  <div className="text-[10px] font-semibold text-slate-600">{b.count}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* TEAM PERFORMANCE */}
        <div className="mt-4 rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-2.5 text-sm font-bold text-slate-900">Team Performance</div>
          {team.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">No team members with assignments.</div>
          ) : (
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-slate-100 text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2 font-semibold">Team Member</th>
                  <th className="px-2 py-2 font-semibold">Active</th>
                  <th className="px-2 py-2 font-semibold">Needs Attn</th>
                  <th className="px-2 py-2 font-semibold">Ready</th>
                  <th className="px-2 py-2 font-semibold">Avg Time</th>
                  <th className="px-2 py-2 font-semibold">SLA</th>
                  <th className="px-2 py-2 font-semibold">Capacity*</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {team.map((m) => (
                  <tr key={m.user_id} className="border-b border-slate-50">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-900 text-[9px] font-bold text-white">{m.avatar_initials || initials(m.name)}</span>
                        <div><div className="font-semibold text-slate-800">{m.name}</div><div className="text-[9px] text-slate-400">{pretty(m.role)}</div></div>
                      </div>
                    </td>
                    <td className="px-2 py-2">{m.active}</td>
                    <td className="px-2 py-2">{m.needs_attention}</td>
                    <td className="px-2 py-2">{m.ready_to_decide}</td>
                    <td className="px-2 py-2">{m.avg_decision_days == null ? DASH : `${m.avg_decision_days}d`}</td>
                    <td className="px-2 py-2">{m.sla_breaches > 0 ? <span className="font-semibold text-red-600">{m.sla_breaches}</span> : 0}</td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1">
                        <div className="h-1.5 w-14 rounded-full bg-slate-100">
                          <div className="h-1.5 rounded-full" style={{ width: `${Math.min(100, m.capacity_pct)}%`, backgroundColor: m.capacity_pct > 85 ? '#dc2626' : '#16a34a' }} />
                        </div>
                        <span className="text-[9px] text-slate-400">{m.capacity_pct}%</span>
                      </div>
                    </td>
                    <td className="px-2 py-2"><button onClick={() => navigate('/pipeline')} className="rounded border border-slate-200 px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50">View Queue</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="px-4 py-1.5 text-[9px] text-slate-300">*Capacity is a heuristic (active / {15} target) — no capacity model yet.</div>
        </div>

        {/* ATTENTION */}
        <div className="mt-4 rounded-xl border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-bold text-slate-900">Files Needing Attention</span>
            {attentionTotal > 4 && <span className="text-[11px] text-slate-400">{attentionTotal} total</span>}
          </div>
          {shownAttention.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">No files need attention.</div>
          ) : (
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-slate-100 text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2 font-semibold">Borrower</th>
                  <th className="px-2 py-2 font-semibold">Amount</th>
                  <th className="px-2 py-2 font-semibold">Issue</th>
                  <th className="px-2 py-2 font-semibold">SLA</th>
                  <th className="px-2 py-2 font-semibold">In Queue</th>
                  <th className="px-2 py-2 font-semibold">Assigned</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {shownAttention.slice(0, 4).map((f) => (
                  <tr key={f.application_id} className="border-b border-slate-50">
                    <td className="px-3 py-2 font-semibold text-slate-800">{f.borrower ?? f.application_id}</td>
                    <td className="px-2 py-2">{money(f.loan_amount)}</td>
                    <td className="px-2 py-2 max-w-[220px] truncate text-slate-500" title={f.issue ?? ''}>{f.issue ?? DASH}</td>
                    <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${SLA_TAG[f.sla_status] ?? 'bg-slate-100 text-slate-600'}`}>{f.sla_status}</span></td>
                    <td className="px-2 py-2">{f.days_in_queue == null ? DASH : `${f.days_in_queue}d`}</td>
                    <td className="px-2 py-2">{f.assigned_to ? <span className="flex items-center gap-1"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[8px] font-bold text-slate-600">{f.assigned_initials || initials(f.assigned_to)}</span></span> : DASH}</td>
                    <td className="px-2 py-2"><button onClick={() => navigate(`/pipeline/${encodeURIComponent(f.application_id)}`)} className="rounded bg-[#14532d] px-2 py-1 text-[10px] font-semibold text-white">Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {attentionTotal > 4 && (
            <div className="px-4 py-2"><button className="text-[11px] font-medium text-blue-600 hover:underline">View all {attentionTotal} files →</button></div>
          )}
        </div>
      </main>

      {/* ── RIGHT PANEL ── */}
      <aside className="hidden w-[280px] shrink-0 space-y-4 border-l border-slate-200 bg-white p-4 xl:block">
        <Panel title="Alerts & Notifications">
          {slaBreach > 0 && <Alert dot="bg-red-500" title={`${slaBreach} SLA breach${slaBreach === 1 ? '' : 'es'}`} sub="Conditions past due" />}
          {needs > 0 && <Alert dot="bg-amber-500" title={`${needs} file${needs === 1 ? '' : 's'} need attention`} sub="Blocking or overdue conditions" />}
          {slaBreach === 0 && needs === 0 && <div className="text-[11px] text-slate-400">No active alerts.</div>}
        </Panel>

        <Panel title="AI Insights" flag="demo">
          <ul className="space-y-1.5">
            {AI_INSIGHTS.map((t, i) => <li key={i} className="text-[11px] leading-snug text-slate-600">• {t}</li>)}
          </ul>
        </Panel>

        <Panel title="Quick Actions">
          {['Reassign Workload', 'Create Team Message', 'Export Pipeline Report', 'View SLA Dashboard'].map((a) => (
            <button key={a} className="mb-1.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-left text-[11px] font-medium text-slate-600 hover:bg-slate-50">{a}</button>
          ))}
        </Panel>
      </aside>
    </div>
  )
}

function FilterStub({ label, note }: { label: string; note: string }) {
  return (
    <div className="mb-2 opacity-60">
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">{label}<span className="rounded bg-slate-100 px-1 text-[8px] uppercase text-slate-400">{note}</span></div>
      <select disabled className="w-full cursor-not-allowed rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-300"><option>All</option></select>
    </div>
  )
}
function Panel({ title, flag, children }: { title: string; flag?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{title}{flag && <span className="rounded bg-amber-50 px-1 text-[8px] text-amber-600">{flag}</span>}</div>
      {children}
    </div>
  )
}
function Alert({ dot, title, sub }: { dot: string; title: string; sub: string }) {
  return (
    <div className="mb-2 flex items-start gap-2">
      <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${dot}`} />
      <div><div className="text-[11px] font-medium text-slate-700">{title}</div><div className="text-[10px] text-slate-400">{sub}</div></div>
    </div>
  )
}
