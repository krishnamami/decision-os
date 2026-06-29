import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, LabelList } from 'recharts'
import { useAuth } from '../context/AuthContext'

// ─────────────────────────────────────────────────────────────────────────────
// DEMO DATA — illustrative figures matching the product mock.
// TODO(v2): replace each block with the live aggregate endpoints that already
// exist from the prior slice:
//   /api/accord/dashboard/summary           (KPIs + status funnel + aging)
//   /api/accord/dashboard/team-performance  (team table)
//   /api/accord/dashboard/attention         (attention table)
// They return real summit numbers but are sparse today (conditions seeded on
// only a few loans), so this view uses the mock values for a complete picture.
// ─────────────────────────────────────────────────────────────────────────────

const KPIS = [
  { label: 'Active Files', value: '52', delta: '+6', good: true, tone: 'text-slate-900' },        // real source: summary.active_files
  { label: 'Needs Attention', value: '12', delta: '+3', good: false, tone: 'text-amber-600' },     // real: summary.needs_attention
  { label: 'Pending Customer', value: '18', delta: '-2', good: true, tone: 'text-slate-900' },      // demo
  { label: 'Ready to Decide', value: '9', delta: '+1', good: true, tone: 'text-green-700' },        // demo
  { label: 'SLA Breaches', value: '3', delta: '+1', good: false, tone: 'text-red-600' },            // demo
  { label: 'Avg Decision Time', value: '19.9d', delta: '-2.3d', good: true, tone: 'text-slate-900' }, // real: summary.avg_decision_days
]

const DONUT = [
  { name: 'On Track', value: 28, pct: 54, fill: '#16a34a' },
  { name: 'At Risk', value: 12, pct: 23, fill: '#ea580c' },
  { name: 'Delayed', value: 9, pct: 17, fill: '#d97706' },
  { name: 'SLA Breach', value: 3, pct: 6, fill: '#dc2626' },
]
const DONUT_TOTAL = 52

const FUNNEL = [
  { stage: 'Application', n: 76 },
  { stage: 'Processing', n: 62 },
  { stage: 'Underwriting', n: 52 },
  { stage: 'Docs Reviewed', n: 31 },
  { stage: 'Decision', n: 9 },
  { stage: 'Closing', n: 7 },
  { stage: 'Funded', n: 5 },
]

const AGING = [
  { bucket: '0-3 days', n: 16, pct: 31, fill: '#16a34a' },
  { bucket: '4-7 days', n: 12, pct: 23, fill: '#65a30d' },
  { bucket: '8-15 days', n: 11, pct: 21, fill: '#ca8a04' },
  { bucket: '16-30 days', n: 8, pct: 15, fill: '#ea580c' },
  { bucket: '30+ days', n: 5, pct: 10, fill: '#dc2626' },
]

type Delta = { v: string; good: boolean } | null
const TEAM: Array<{
  name: string; role: string; active: number; activeD: Delta; needs: number; needsD: Delta
  pending: number; pendingD: Delta; ready: number; readyD: Delta; avg: string; avgD: Delta
  sla: number; slaD: Delta; capacity: number
}> = [
  { name: 'James Underwriter', role: 'underwriter', active: 6, activeD: { v: '+1', good: true }, needs: 2, needsD: { v: '+1', good: false }, pending: 1, pendingD: null, ready: 1, readyD: null, avg: '14.2d', avgD: { v: '-2.1d', good: true }, sla: 1, slaD: { v: '+1', good: false }, capacity: 80 },
  { name: 'Amy Compliance', role: 'compliance', active: 3, activeD: null, needs: 0, needsD: null, pending: 2, pendingD: { v: '+1', good: false }, ready: 1, readyD: null, avg: '11.3d', avgD: { v: '-1.3d', good: true }, sla: 0, slaD: null, capacity: 40 },
  { name: 'Sarah Reviewer', role: 'senior_uw', active: 8, activeD: { v: '+2', good: true }, needs: 2, needsD: { v: '+1', good: false }, pending: 3, pendingD: { v: '+1', good: false }, ready: 2, readyD: null, avg: '17.8d', avgD: { v: '+1.8d', good: false }, sla: 1, slaD: { v: '+1', good: false }, capacity: 95 },
  { name: 'Mike Processor', role: 'processor', active: 9, activeD: { v: '+1', good: true }, needs: 3, needsD: null, pending: 4, pendingD: { v: '+1', good: false }, ready: 1, readyD: null, avg: '13.6d', avgD: { v: '-0.6d', good: true }, sla: 0, slaD: null, capacity: 75 },
  { name: 'John Closer', role: 'closer', active: 4, activeD: null, needs: 0, needsD: null, pending: 1, pendingD: null, ready: 4, readyD: { v: '+1', good: true }, avg: '8.9d', avgD: { v: '-1.2d', good: true }, sla: 0, slaD: null, capacity: 60 },
]

const ATTENTION = [
  { borrower: 'Carlos Smith', amount: '$392,000', purpose: 'Purchase', lo: 'Brian Lopez', issue: 'Fraud score 0.78 (threshold 0.70)', sla: 'Breach', slaDays: '17 days', queue: '12d', assigned: 'James Underwriter', appId: 'APP-LOAN-20260303-06161' },
  { borrower: 'Wayne Hart', amount: '$500,000', purpose: 'Refinance', lo: 'Brian Lopez', issue: 'Income discrepancy 32.6%', sla: 'At Risk', slaDays: '20 days', queue: '14d', assigned: 'James Underwriter', appId: '' },
  { borrower: 'Mia Anderson', amount: '$354,000', purpose: 'Purchase', lo: 'Sarah Miller', issue: 'Employment gap 45 days', sla: 'At Risk', slaDays: '18 days', queue: '10d', assigned: 'Sarah Reviewer', appId: '' },
  { borrower: 'Dwayne Jackson', amount: '$400,000', purpose: 'Purchase', lo: 'Sarah Miller', issue: 'VOE pending', sla: 'Due Soon', slaDays: '2 days', queue: '8d', assigned: 'Mike Processor', appId: '' },
]

const ALERTS = [
  { dot: 'bg-red-500', title: '3 files breached SLA', sub: 'Carlos Smith, Wayne Hart +1', ts: '10m ago' },
  { dot: 'bg-amber-500', title: '5 files need your review', sub: 'High priority conditions', ts: '25m ago' },
  { dot: 'bg-slate-700', title: 'System', sub: 'Fraud score model updated to v0.78', ts: '1h ago' },
  { dot: 'bg-slate-400', title: 'Policy Update', sub: 'FNMA 5.3 updates effective May 24', ts: '2h ago' },
]

// TODO(v2): replace with a real aggregate query over decisions/conditions.
const AI_INSIGHTS = [
  { t: 'Income verification causing 42% of delays', s: '+23% vs last week' },
  { t: 'James Underwriter is over capacity by 32%', s: '6 active vs recommended 4' },
  { t: 'Fraud reviews averaging 5 extra days', s: 'consider additional resource' },
  { t: 'Reassign 3 files to balance workload', s: 'View recommendations →' },
]

const SLA_BADGE: Record<string, string> = {
  Breach: 'bg-red-50 text-red-700',
  'At Risk': 'bg-orange-50 text-orange-700',
  'Due Soon': 'bg-amber-50 text-amber-700',
}
const PRODUCTS = ['All', 'Conforming', 'FHA', 'VA', 'Non-QM', 'Jumbo']
const OFFICERS = ['All', 'Brian Lopez', 'Sarah Miller', 'James Underwriter', 'Mike Processor']

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

export default function DashboardPage() {
  const navigate = useNavigate()
  const { effectiveUser } = useAuth()
  const [activeNav, setActiveNav] = useState('Team Overview')
  const [officer, setOfficer] = useState('All')
  const [product, setProduct] = useState('All')

  const today = useMemo(
    () => new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    [],
  )

  const NAV: Array<[string, number | null]> = [
    ['Team Overview', null], ['All Applications', null], ['Queues', 38], ['SLA Dashboard', null],
    ['Escalations', 5], ['Reports', null], ['Workload', null], ['Settings', null],
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
                  <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${label === 'Escalations' ? 'bg-red-100 text-red-700' : 'bg-slate-200 text-slate-600'}`}>{badge}</span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="border-t border-slate-100 p-3 text-xs">
          <div className="mb-2 font-semibold uppercase tracking-wide text-slate-400">Filters</div>
          <FilterStub label="Channel" />
          <FilterStub label="Loan Purpose" />
          <Dropdown label="Loan Officer" value={officer} onChange={setOfficer} options={OFFICERS} />
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
            <button className="rounded-lg bg-[#14532d] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0f3d22]">Export</button>
          </div>
        </div>

        {/* KPI bar */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {KPIS.map((k) => (
            <div key={k.label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">{k.label}</div>
              <div className={`mt-1 text-2xl font-bold ${k.tone}`}>{k.value}</div>
              <div className={`mt-0.5 flex items-center gap-1 text-[10px] ${k.good ? 'text-green-600' : 'text-red-600'}`}>
                <span>{k.delta.startsWith('-') ? '↓' : '↑'} {k.delta.replace(/^[-+]/, '')}</span>
                <span className="text-slate-300">vs yesterday</span>
              </div>
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
                  <Pie data={DONUT} dataKey="value" innerRadius={52} outerRadius={74} paddingAngle={2} startAngle={90} endAngle={-270}>
                    {DONUT.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-slate-900">{DONUT_TOTAL}</span>
                <span className="text-[10px] text-slate-400">Total Active</span>
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1 text-[10px]">
              {DONUT.map((d) => (
                <span key={d.name} className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: d.fill }} />
                  {d.name} {d.value} ({d.pct}%)
                </span>
              ))}
            </div>
          </Card>

          {/* funnel */}
          <Card title="Files by Stage">
            <div className="mt-1 space-y-1.5">
              {FUNNEL.map((f, i) => {
                const widthPct = 100 - i * 12
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
                <BarChart data={AGING} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="bucket" width={66} tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <Bar dataKey="n" radius={[0, 4, 4, 0]} barSize={16}>
                    {AGING.map((a, i) => <Cell key={i} fill={a.fill} />)}
                    <LabelList dataKey="n" position="right" style={{ fontSize: 10, fill: '#475569' }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap justify-center gap-x-2 gap-y-0.5 text-[9px] text-slate-400">
              {AGING.map((a) => <span key={a.bucket}>{a.bucket} {a.pct}%</span>)}
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
                  <th className="px-2 py-2 font-semibold">Active ↓</th>
                  <th className="px-2 py-2 font-semibold">Needs Attn</th>
                  <th className="px-2 py-2 font-semibold">Pending</th>
                  <th className="px-2 py-2 font-semibold">Ready</th>
                  <th className="px-2 py-2 font-semibold">Avg Time</th>
                  <th className="px-2 py-2 font-semibold">SLA</th>
                  <th className="px-2 py-2 font-semibold">Capacity</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {TEAM.map((m) => (
                  <tr key={m.name} className="border-b border-slate-50">
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-900 text-[9px] font-bold text-white">{initials(m.name)}</span>
                        <div><div className="font-semibold text-slate-800">{m.name}</div><div className="text-[9px] text-slate-400">{pretty(m.role)}</div></div>
                      </div>
                    </td>
                    <td className="px-2 py-2"><Num n={m.active} d={m.activeD} /></td>
                    <td className="px-2 py-2"><Num n={m.needs} d={m.needsD} /></td>
                    <td className="px-2 py-2"><Num n={m.pending} d={m.pendingD} /></td>
                    <td className="px-2 py-2"><Num n={m.ready} d={m.readyD} /></td>
                    <td className="px-2 py-2"><span className="text-slate-700">{m.avg}</span> {m.avgD && <span className={m.avgD.good ? 'text-green-600' : 'text-red-600'}>{m.avgD.v}</span>}</td>
                    <td className="px-2 py-2"><Num n={m.sla} d={m.slaD} danger /></td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1.5">
                        <div className="h-1.5 w-16 rounded-full bg-slate-100"><div className="h-1.5 rounded-full" style={{ width: `${m.capacity}%`, backgroundColor: capColor(m.capacity) }} /></div>
                        <span className="text-[9px]" style={{ color: capColor(m.capacity) }}>{m.capacity}%</span>
                      </div>
                    </td>
                    <td className="px-2 py-2"><button onClick={() => navigate('/pipeline')} className="rounded border border-slate-200 px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50">View Queue</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* attention */}
        <Card title="Top Files Needing Attention" className="mt-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                  <th className="px-2 py-2 font-semibold">Borrower</th>
                  <th className="px-2 py-2 font-semibold">Amount</th>
                  <th className="px-2 py-2 font-semibold">Purpose</th>
                  <th className="px-2 py-2 font-semibold">LO Officer</th>
                  <th className="px-2 py-2 font-semibold">Issue</th>
                  <th className="px-2 py-2 font-semibold">SLA Status</th>
                  <th className="px-2 py-2 font-semibold">In Queue</th>
                  <th className="px-2 py-2 font-semibold">Assigned</th>
                  <th className="px-2 py-2 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {ATTENTION.map((f) => (
                  <tr key={f.borrower} className="border-b border-slate-50">
                    <td className="px-2 py-2 font-semibold text-slate-800">{f.borrower}</td>
                    <td className="px-2 py-2">{f.amount}</td>
                    <td className="px-2 py-2 text-slate-500">{f.purpose}</td>
                    <td className="px-2 py-2 text-slate-500">{f.lo}</td>
                    <td className="px-2 py-2 text-slate-600">{f.issue}</td>
                    <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${SLA_BADGE[f.sla]}`}>{f.sla} · {f.slaDays}</span></td>
                    <td className="px-2 py-2">{f.queue}</td>
                    <td className="px-2 py-2"><span className="flex items-center gap-1"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[8px] font-bold text-slate-600">{initials(f.assigned)}</span><span className="text-[10px] text-slate-500">{f.assigned.split(' ')[0]}</span></span></td>
                    <td className="px-2 py-2"><button onClick={() => f.appId && navigate(`/pipeline/${encodeURIComponent(f.appId)}`)} className="rounded bg-[#14532d] px-2 py-1 text-[10px] font-semibold text-white">Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="mt-2 text-[11px] font-medium text-blue-600 hover:underline">View all 12 files →</button>
        </Card>

        <p className="mt-3 text-[9px] text-slate-300">Figures are illustrative pending live-aggregate wiring (endpoints exist: /api/accord/dashboard/*).</p>
      </main>

      {/* ── RIGHT PANEL (280px) ── */}
      <aside className="hidden w-[280px] shrink-0 space-y-5 border-l border-slate-200 bg-white p-4 xl:block">
        <Panel title="Alerts & Notifications" link>
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

        <Panel title="AI Insights" link flag="demo">
          {AI_INSIGHTS.map((a, i) => (
            <div key={i} className="mb-2">
              <div className="text-[11px] font-medium leading-snug text-slate-700">{a.t}</div>
              <div className={`text-[10px] ${a.s.includes('→') ? 'cursor-pointer text-blue-600' : 'text-slate-400'}`}>{a.s}</div>
            </div>
          ))}
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

// ── small components ──
function Card({ title, className = '', children }: { title: string; className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-lg border border-slate-200 bg-white p-3 shadow-sm ${className}`}>
      <div className="mb-1 text-xs font-semibold text-slate-700">{title}</div>
      {children}
    </div>
  )
}
function Num({ n, d, danger }: { n: number; d: Delta; danger?: boolean }) {
  return (
    <span>
      <span className={danger && n > 0 ? 'font-semibold text-red-600' : 'text-slate-700'}>{n}</span>
      {d && <span className={`ml-1 text-[9px] ${d.good ? 'text-green-600' : 'text-red-600'}`}>{d.v.startsWith('-') ? '↓' : '↑'}{d.v.replace(/^[-+]/, '')}</span>}
    </span>
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
function Panel({ title, link, flag, children }: { title: string; link?: boolean; flag?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{title}{flag && <span className="rounded bg-amber-50 px-1 text-[8px] text-amber-600">{flag}</span>}</span>
        {link && <button className="text-[10px] font-medium text-blue-600 hover:underline">View all</button>}
      </div>
      {children}
    </div>
  )
}
