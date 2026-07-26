import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, LabelList } from 'recharts'
import { useAuth } from '../context/AuthContext'
import { fetchDashboardSummary, fetchDashboardTeam, fetchDashboardAttention } from '../api/client'

// Live admin/manager dashboard — wired to the aggregate endpoints:
//   /api/accord/dashboard/summary           KPIs + status funnel + aging
//   /api/accord/dashboard/team-performance  team table
//   /api/accord/dashboard/attention         attention table
// All figures below come from these; the right-hand Alerts / AI Insights panels
// remain illustrative (no aggregate source yet, flagged "demo").

const AGING_FILL = ['#16a34a', '#65a30d', '#ca8a04', '#ea580c', '#dc2626']

// Right-panel demo content (no live source yet — clearly flagged in the UI).
const ALERTS = [
  { dot: 'bg-red-500', title: 'Files breaching SLA', sub: 'Review the attention queue', ts: 'live' },
  { dot: 'bg-amber-500', title: 'High-priority conditions', sub: 'Blocking conditions open', ts: 'live' },
  { dot: 'bg-slate-700', title: 'System', sub: 'Fraud score model updated to v0.78', ts: '1h ago' },
  { dot: 'bg-slate-400', title: 'Policy Update', sub: 'FNMA 5.3 updates effective May 24', ts: '2h ago' },
]
const AI_INSIGHTS = [
  { t: 'Income verification causing 42% of delays', s: '+23% vs last week' },
  { t: 'Balance workload across underwriters', s: 'Check the capacity column' },
  { t: 'Fraud reviews averaging extra days', s: 'consider additional resource' },
  { t: 'Reassign files to balance workload', s: 'View recommendations →' },
]

const SLA_BADGE: Record<string, string> = {
  Breach: 'bg-red-50 text-red-700',
  'At Risk': 'bg-orange-50 text-orange-700',
  'Due Soon': 'bg-amber-50 text-amber-700',
}
const PRODUCTS = ['All', 'Conforming', 'FHA', 'VA', 'Non-QM', 'Jumbo']

function initials(name?: string | null): string {
  const s = String(name || '').trim()
  if (!s) return '?'
  const p = s.split(/\s+/)
  return ((p[0]?.[0] ?? '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase()
}
function pretty(s?: string | null): string {
  return s ? String(s).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : ''
}
function capColor(p: number): string {
  return p >= 90 ? '#dc2626' : p >= 70 ? '#ea580c' : '#16a34a'
}
// avg_decision_days: 0 / null (no decided loans) → "—"; else "Nd".
function fmtAvg(v?: number | null): string {
  return v != null && v > 0 ? `${v}d` : '—'
}
function money(v?: number | null): string {
  return v == null ? '—' : `$${Math.round(v / 1000)}k`
}

function EscalationsView() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetch('/api/accord/pipeline?limit=500', { headers: { Authorization: `Bearer ${localStorage.getItem('accord_token')}` } })
      .then(r => r.json())
      .then(d => {
        const escalated = (d.applications || []).filter((a: any) =>
          a.decisions?.underwriting_decision?.outcome === 'escalate' ||
          Object.values(a.decisions || {}).some((dec: any) => dec.outcome === 'escalate')
        )
        setRows(escalated)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-center text-slate-400 text-sm">Loading escalations…</div>
  if (!rows.length) return <div className="p-8 text-center text-slate-400 text-sm">No escalated loans.</div>

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div>
          <div className="font-semibold text-slate-900 text-sm">Escalated Loans</div>
          <div className="text-xs text-slate-400">{rows.length} loans requiring senior review</div>
        </div>
      </div>
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-slate-500 uppercase tracking-wide text-[10px]">
          <tr>
            <th className="px-4 py-2 text-left">Borrower</th>
            <th className="px-4 py-2 text-left">Loan</th>
            <th className="px-4 py-2 text-left">FICO</th>
            <th className="px-4 py-2 text-left">DTI</th>
            <th className="px-4 py-2 text-left">LTV</th>
            <th className="px-4 py-2 text-left">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.application_id} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                onClick={() => window.location.href = `/pipeline/${r.application_id}`}>
              <td className="px-4 py-2 font-medium text-slate-800">{r.borrower_name}<div className="text-[10px] text-slate-400">{r.application_id}</div></td>
              <td className="px-4 py-2">${((r.loan_amount||0)/1000).toFixed(0)}K</td>
              <td className="px-4 py-2">{r.credit_score ?? '—'}</td>
              <td className="px-4 py-2">{r.dti ? `${r.dti.toFixed(1)}%` : '—'}</td>
              <td className="px-4 py-2">{r.ltv ? `${r.ltv.toFixed(1)}%` : '—'}</td>
              <td className="px-4 py-2"><span className="rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-semibold">Escalated</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const { effectiveUser } = useAuth()
  const [activeNav, setActiveNav] = useState('Team Overview')
  const [officer, setOfficer] = useState('All')
  const [product, setProduct] = useState('All')
  const [toast, setToast] = useState<string | null>(null)
  const notify = (msg: string) => { setToast(msg); window.setTimeout(() => setToast(null), 2200) }

  // ── live aggregate data ──
  const [summary, setSummary] = useState<any>(null)
  const [team, setTeam] = useState<any[]>([])
  const [attention, setAttention] = useState<any[]>([])
  const [attentionTotal, setAttentionTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.all([fetchDashboardSummary(), fetchDashboardTeam(), fetchDashboardAttention(50)])
      .then(([s, t, a]) => {
        if (!alive) return
        setSummary(s)
        setTeam(t?.members ?? [])
        setAttention(a?.files ?? [])
        setAttentionTotal(a?.total ?? 0)
        setErr(null)
      })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  // ── derived views (all from live data) ──
  const kpis = summary ? [
    { label: 'Active Files', value: String(summary.active_files ?? 0), tone: 'text-slate-900' },
    { label: 'Needs Attention', value: String(summary.needs_attention ?? 0), tone: 'text-amber-600' },
    { label: 'Pending Customer', value: String(summary.pending_customer ?? 0), tone: 'text-slate-900' },
    { label: 'Ready to Decide', value: String(summary.ready_to_decide ?? 0), tone: 'text-green-700' },
    { label: 'SLA Breaches', value: String(summary.sla_breaches ?? 0), tone: 'text-red-600' },
    { label: 'Avg Decision Time', value: fmtAvg(summary.avg_decision_days), tone: 'text-slate-900' },
  ] : []

  const donut = useMemo(() => {
    if (!summary) return [] as Array<{ name: string; value: number; fill: string; pct: number }>
    const active = summary.active_files ?? 0
    const breach = summary.sla_breaches ?? 0
    const na = summary.needs_attention ?? 0
    const atRisk = Math.max(0, na - breach)
    const onTrack = Math.max(0, active - na)
    const total = active || 1
    return [
      { name: 'On Track', value: onTrack, fill: '#16a34a' },
      { name: 'At Risk', value: atRisk, fill: '#ea580c' },
      { name: 'SLA Breach', value: breach, fill: '#dc2626' },
    ].map((d) => ({ ...d, pct: Math.round((d.value * 100) / total) }))
  }, [summary])
  const donutTotal = summary?.active_files ?? 0

  const funnel: Array<{ stage: string; n: number }> =
    (summary?.by_status ?? []).map((s: any) => ({ stage: pretty(s.status), n: s.count }))

  const aging = useMemo(() => {
    const rows = summary?.aging ?? []
    const tot = rows.reduce((x: number, b: any) => x + (b.count ?? 0), 0) || 1
    return rows.map((a: any, i: number) => ({
      bucket: a.bucket, n: a.count ?? 0,
      pct: Math.round(((a.count ?? 0) * 100) / tot), fill: AGING_FILL[i] ?? '#64748b',
    }))
  }, [summary])

  // Assignee filter derived from the live attention rows so it's always meaningful.
  const officerOptions = useMemo(
    () => ['All', ...Array.from(new Set(attention.map((f) => f.assigned_to).filter(Boolean))) as string[]],
    [attention],
  )
  const shownAttention = attention.filter((f) => officer === 'All' || f.assigned_to === officer)

  const today = useMemo(
    () => new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    [],
  )

  const NAV: Array<[string, number | null]> = [
    ['Team Overview', null], ['Escalations', null],
  ]

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: '#f8f9fa' }}>
      {/* ── LEFT SIDEBAR (200px) ── */}
      <aside className="hidden w-[200px] shrink-0 flex-col justify-between border-r border-slate-200 bg-white lg:flex">
        <nav className="p-3">
          {NAV.map(([label, badge]) => {
            const active = activeNav === label
            return (
              <button
                key={label}
                onClick={() => setActiveNav(label)}
                className={`mb-0.5 flex w-full items-center justify-between border-l-2 px-3 py-2 text-left text-sm ${active ? 'border-[#14532d] bg-[#14532d]/5 font-semibold text-[#14532d]' : 'border-transparent text-slate-600 hover:bg-slate-50'}`}
              >
                <span>{label}</span>
                {badge != null && (
                  <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">{badge}</span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="border-t border-slate-100 p-3 text-xs">
          <div className="mb-2 font-semibold uppercase tracking-wide text-slate-400">Filters</div>
          <FilterStub label="Channel" />
          <FilterStub label="Loan Purpose" />
          <Dropdown label="Assignee" value={officer} onChange={setOfficer} options={officerOptions} />
          <Dropdown label="Product" value={product} onChange={setProduct} options={PRODUCTS} />
          <button onClick={() => { setOfficer('All'); setProduct('All') }} className="mt-1 text-[11px] font-medium text-blue-600 hover:underline">Clear all</button>
        </div>
      </aside>

      {/* ── CENTER MAIN ── */}
      <main className="min-w-0 flex-1 px-5 py-5">
        {/* header */}
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Pipeline Overview</h1>
            <p className="text-xs text-slate-400">Real-time overview of your team's pipeline{effectiveUser?.name ? ` · ${effectiveUser.name}` : ''}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500">📅 {today}</span>
            <button onClick={() => notify('Export started — pipeline report (demo)')} className="rounded-lg bg-[#14532d] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0f3d22]">Export</button>
          </div>
        </div>

        {activeNav !== 'Team Overview' ? (
          activeNav === 'All Applications' ? (
            <iframe src="/pipeline" className="w-full border-0" style={{height: 'calc(100vh - 120px)'}} />
          ) : activeNav === 'Escalations' ? (
            <EscalationsView />
          ) : (
            <ComingSoon section={activeNav} />
          )
        ) : loading ? (
          <div className="flex min-h-[50vh] items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-[#14532d]" />
          </div>
        ) : err ? (
          <div className="flex min-h-[40vh] flex-col items-center justify-center rounded-lg border border-dashed border-red-200 bg-white text-center">
            <div className="text-sm font-semibold text-red-600">Couldn't load the dashboard</div>
            <div className="mt-1 max-w-md text-xs text-slate-400">{err}</div>
          </div>
        ) : (<>
        {/* KPI bar */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {kpis.map((k) => (
            <div key={k.label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">{k.label}</div>
              <div className={`mt-1 text-2xl font-bold ${k.tone}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* charts */}
        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
          {/* donut */}
          <Card title="Pipeline Health">
            <div className="relative mx-auto h-44 w-44">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={donut} dataKey="value" innerRadius={52} outerRadius={74} paddingAngle={2} startAngle={90} endAngle={-270}>
                    {donut.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-slate-900">{donutTotal}</span>
                <span className="text-[10px] text-slate-400">Total Active</span>
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1 text-[10px]">
              {donut.map((d) => (
                <span key={d.name} className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: d.fill }} />
                  {d.name} {d.value} ({d.pct}%)
                </span>
              ))}
            </div>
          </Card>

          {/* funnel — real status distribution */}
          <Card title="Files by Status">
            <div className="mt-1 space-y-1.5">
              {funnel.length === 0 && <div className="py-6 text-center text-[11px] text-slate-400">No status data.</div>}
              {funnel.map((f, i) => {
                const max = Math.max(...funnel.map((x) => x.n), 1)
                const widthPct = Math.max(12, Math.round((f.n * 100) / max))
                const blue = `rgb(${37 + i * 8}, ${99 - i * 6}, ${235 - i * 18})`
                return (
                  <div key={f.stage} className="flex items-center gap-2">
                    <div className="w-24 shrink-0 text-right text-[10px] text-slate-500">{f.stage}</div>
                    <div className="flex h-5 items-center rounded px-2 text-[10px] font-semibold text-white" style={{ width: `${widthPct}%`, backgroundColor: blue, minWidth: 28 }}>{f.n}</div>
                  </div>
                )
              })}
            </div>
          </Card>

          {/* aging (recharts horizontal bar) */}
          <Card title="Aging Active Files">
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={aging} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="bucket" width={66} tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <Bar dataKey="n" radius={[0, 4, 4, 0]} barSize={16}>
                    {aging.map((a: any, i: number) => <Cell key={i} fill={a.fill} />)}
                    <LabelList dataKey="n" position="right" style={{ fontSize: 10, fill: '#475569' }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap justify-center gap-x-2 gap-y-0.5 text-[9px] text-slate-400">
              {aging.map((a: any) => <span key={a.bucket}>{a.bucket} {a.pct}%</span>)}
            </div>
          </Card>
        </div>

        {/* team performance */}
        <Card title="Team Performance" className="mt-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                  <th className="px-2 py-2 font-semibold">Team Member</th>
                  <th className="px-2 py-2 font-semibold">Active</th>
                  <th className="px-2 py-2 font-semibold">Needs Attn</th>
                  <th className="px-2 py-2 font-semibold">Pending</th>
                  <th className="px-2 py-2 font-semibold">Ready</th>
                  <th className="px-2 py-2 font-semibold">Avg Decision Time</th>
                  <th className="px-2 py-2 font-semibold">SLA</th>
                  <th className="px-2 py-2 font-semibold">Capacity</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {team.length === 0 && (
                  <tr><td colSpan={9} className="px-2 py-6 text-center text-[11px] text-slate-400">No team members.</td></tr>
                )}
                {team.map((m) => (
                  <tr key={m.user_id ?? m.name} className="border-b border-slate-50">
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-900 text-[9px] font-bold text-white">{m.avatar_initials ?? initials(m.name)}</span>
                        <div><div className="font-semibold text-slate-800">{m.name}</div><div className="text-[9px] text-slate-400">{pretty(m.role)}</div></div>
                      </div>
                    </td>
                    <td className="px-2 py-2"><Num n={m.active ?? 0} /></td>
                    <td className="px-2 py-2"><Num n={m.needs_attention ?? 0} /></td>
                    <td className="px-2 py-2"><Num n={m.pending ?? 0} /></td>
                    <td className="px-2 py-2"><Num n={m.ready_to_decide ?? 0} /></td>
                    <td className="px-2 py-2 text-slate-700">{fmtAvg(m.avg_decision_days)}</td>
                    <td className="px-2 py-2"><Num n={m.sla_breaches ?? 0} danger /></td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1.5">
                        <div className="h-1.5 w-16 rounded-full bg-slate-100"><div className="h-1.5 rounded-full" style={{ width: `${m.capacity_pct ?? 0}%`, backgroundColor: capColor(m.capacity_pct ?? 0) }} /></div>
                        <span className="text-[9px]" style={{ color: capColor(m.capacity_pct ?? 0) }}>{m.capacity_pct ?? 0}%</span>
                      </div>
                    </td>
                    <td className="px-2 py-2"><button onClick={() => notify(`${m.name}'s queue — coming soon`)} className="rounded border border-slate-200 px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50">View Queue</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[9px] text-slate-300">Capacity is a heuristic (active files / {15} target). Avg decision time is engine turnaround over human-reviewed decisions; “—” means no decided loans yet.</p>
        </Card>

        {/* attention */}
        <Card title="Top Files Needing Attention" className="mt-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                  <th className="px-2 py-2 font-semibold">Borrower</th>
                  <th className="px-2 py-2 font-semibold">Amount</th>
                  <th className="px-2 py-2 font-semibold">Issue</th>
                  <th className="px-2 py-2 font-semibold">SLA Status</th>
                  <th className="px-2 py-2 font-semibold">In Queue</th>
                  <th className="px-2 py-2 font-semibold">Assigned</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {shownAttention.length === 0 && (
                  <tr><td colSpan={7} className="px-2 py-6 text-center text-[11px] text-slate-400">No files need attention.</td></tr>
                )}
                {shownAttention.map((f) => (
                  <tr key={f.application_id} className="border-b border-slate-50">
                    <td className="px-2 py-2 font-semibold text-slate-800">{f.borrower ?? '—'}</td>
                    <td className="px-2 py-2">{money(f.loan_amount)}</td>
                    <td className="px-2 py-2 text-slate-600">{f.issue ?? '—'}</td>
                    <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${SLA_BADGE[f.sla_status] ?? 'bg-slate-100 text-slate-600'}`}>{f.sla_status}</span></td>
                    <td className="px-2 py-2">{f.days_in_queue != null ? `${f.days_in_queue}d` : '—'}</td>
                    <td className="px-2 py-2">
                      <span className="flex items-center gap-1">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[8px] font-bold text-slate-600">{f.assigned_initials ?? '?'}</span>
                        <span className="text-[10px] text-slate-500">{f.assigned_to ? f.assigned_to.split(' ')[0] : 'Unassigned'}</span>
                      </span>
                    </td>
                    <td className="px-2 py-2"><button onClick={() => navigate(`/pipeline/${encodeURIComponent(f.application_id)}`)} className="rounded bg-[#14532d] px-2 py-1 text-[10px] font-semibold text-white">Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button onClick={() => setActiveNav('All Applications')} className="mt-2 text-[11px] font-medium text-blue-600 hover:underline">View all {attentionTotal} files →</button>
        </Card>
        </>)}
      </main>

      {/* ── RIGHT PANEL (280px) ── */}
      <aside className="hidden w-[280px] shrink-0 space-y-5 border-l border-slate-200 bg-white p-4 xl:block">
        <Panel title="Alerts & Notifications" flag="demo" onView={() => setActiveNav('Escalations')}>
          {ALERTS.map((a, i) => (
            <div key={i} className="mb-2.5 flex items-start gap-2">
              <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${a.dot}`} />
              <div className="min-w-0">
                <div className="text-[11px] font-medium text-slate-700">{a.title}</div>
                <div className="truncate text-[10px] text-slate-400">{a.sub}</div>
                <div className="text-[9px] text-slate-300">{a.ts}</div>
              </div>
            </div>
          ))}
        </Panel>

        <Panel title="AI Insights" flag="demo" onView={() => notify('All AI insights (demo)')}>
          {AI_INSIGHTS.map((a, i) => (
            <div key={i} className="mb-2">
              <div className="text-[11px] font-medium leading-snug text-slate-700">{a.t}</div>
              <div
                onClick={a.s.includes('→') ? () => notify('Workload recommendations (demo)') : undefined}
                className={`text-[10px] ${a.s.includes('→') ? 'cursor-pointer text-blue-600 hover:underline' : 'text-slate-400'}`}
              >{a.s}</div>
            </div>
          ))}
        </Panel>

        <Panel title="Quick Actions">
          {([
            ['Reassign Workload', () => setActiveNav('Workload')],
            ['Create Team Message', () => notify('Team message composer (demo)')],
            ['Export Pipeline Report', () => notify('Export started — pipeline report (demo)')],
            ['View SLA Dashboard', () => setActiveNav('SLA Dashboard')],
          ] as Array<[string, () => void]>).map(([label, fn]) => (
            <button key={label} onClick={fn} className="mb-1.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-left text-[11px] font-medium text-slate-600 hover:bg-slate-50">{label}</button>
          ))}
        </Panel>
      </aside>

      {toast && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}

// ── small components ──
function Card({ title, className = '', children }: { title: string; className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-lg border border-slate-200 bg-white p-3 shadow-sm ${className}`}>
      <div className="mb-1 text-xs font-semibold text-slate-700">{title}</div>
      {children}
    </div>
  )
}
function Num({ n, danger }: { n: number; danger?: boolean }) {
  return <span className={danger && n > 0 ? 'font-semibold text-red-600' : 'text-slate-700'}>{n}</span>
}
function ComingSoon({ section }: { section: string }) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-center">
      <div className="text-sm font-semibold text-slate-700">{section}</div>
      <div className="mt-1 text-xs text-slate-400">This section is coming soon.</div>
    </div>
  )
}
function FilterStub({ label }: { label: string }) {
  return (
    <div className="mb-2 opacity-60">
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">{label}<span className="rounded bg-slate-100 px-1 text-[8px] uppercase text-slate-400">soon</span></div>
      <select disabled className="w-full cursor-not-allowed rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-300"><option>All</option></select>
    </div>
  )
}
function Dropdown({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div className="mb-2">
      <div className="mb-1 text-[11px] text-slate-500">{label}</div>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-slate-200 px-2 py-1 text-xs">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}
function Panel({ title, onView, flag, children }: { title: string; onView?: () => void; flag?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{title}{flag && <span className="rounded bg-amber-50 px-1 text-[8px] text-amber-600">{flag}</span>}</span>
        {onView && <button onClick={onView} className="text-[10px] font-medium text-blue-600 hover:underline">View all</button>}
      </div>
      {children}
    </div>
  )
}
