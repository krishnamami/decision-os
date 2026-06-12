import { useEffect, useState, type ReactNode } from 'react'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PieChart, Pie, Cell,
} from 'recharts'
import { fetchAgents, fetchAnalytics, fetchFunnel, fetchRisk, fetchTeamPerformance, type TeamPerformanceResponse } from '../api/client'
import type { AgentStat, AnalyticsOverview, FunnelStep, RiskData } from '../types/accord'
import { useAuth } from '../context/AuthContext'
import PeriodFilter, { type Period, periodParam } from '../components/PeriodFilter'
import ExportMenu from '../components/ExportMenu'
import { ErrorState } from '../components/states'
import { downloadCsv, downloadJson, printPdf } from '../utils/export'

// Auto-execute personas (system-finalized) — get an "auto" review badge.
const AUTO_DECISIONS = new Set([
  'credit_assessment', 'fraud_screening', 'dti_calculation',
  'ltv_assessment', 'rate_pricing', 'approval_routing',
])
const WAVE_NAME: Record<number, string> = {
  1: 'Pre-UW', 2: 'Underwriting', 3: 'Product', 4: 'Decision', 5: 'Closing',
}

// Chart palette.
const C_GREEN = '#22C55E'
const C_RED = '#EF4444'
const C_BRAND = '#0F6E56'
const PRODUCT_COLORS = ['#0F6E56', '#1D9E75', '#5DCAA5', '#F59E0B', '#EF4444', '#6366F1']
const prettyName = (s: string) => s.replace(/_/g, '-').replace(/\b\w/g, (c) => c.toUpperCase())

function money(v: number) {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toLocaleString()}`
}
function reviewTime(minutes: number | null, auto: boolean): string {
  if (auto) return 'auto'
  if (minutes == null) return '—'
  if (minutes < 60) return `${Math.round(minutes)}m`
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)}h`
  return `${(minutes / 1440).toFixed(1)}d`
}

function Section({ title, subtext, children, className = '' }: { title: string; subtext?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`space-y-3 ${className}`}>
      <div>
        <h2 className="text-lg font-bold text-gray-900">{title}</h2>
        {subtext && <p className="text-sm text-gray-500">{subtext}</p>}
      </div>
      {children}
    </section>
  )
}

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-5 shadow-sm ${className}`}>{children}</div>
  )
}

export default function Analytics() {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null)
  const [funnel, setFunnel] = useState<FunnelStep[] | null>(null)
  const [agents, setAgents] = useState<AgentStat[] | null>(null)
  const [risk, setRisk] = useState<RiskData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>('all')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    const p = periodParam(period)
    Promise.all([fetchAnalytics(p), fetchFunnel(p), fetchAgents(p), fetchRisk(p)])
      .then(([o, f, a, r]) => {
        if (!alive) return
        setOverview(o)
        setFunnel(f.funnel)
        setAgents(a.agents)
        setRisk(r)
      })
      .catch((e) => {
        console.error('Analytics load failed:', e)
        if (alive) setError('Could not load analytics data.')
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [period, reloadKey])

  if (loading && !overview) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-6">
        <div className="mb-6 h-8 w-56 animate-pulse rounded bg-gray-200" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg border border-gray-200 bg-gray-50" />
          ))}
        </div>
        <div className="mt-6 h-64 animate-pulse rounded-lg border border-gray-200 bg-gray-50" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-12">
        <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    )
  }
  if (!overview) {
    return <div className="mx-auto max-w-6xl px-6 py-12 text-center text-gray-400">No data available.</div>
  }

  const kpis: Array<{ label: string; value: string; brand?: boolean }> = [
    { label: 'Pipeline volume', value: `${money(overview.total_volume)}`, brand: true },
    { label: 'Avg credit score', value: String(overview.avg_score), brand: true },
    { label: 'Avg LTV', value: `${overview.avg_ltv}%` },
    { label: 'Avg DTI', value: `${overview.avg_dti}%` },
    { label: 'Approval rate', value: `${(overview.approval_rate * 100).toFixed(1)}%`, brand: true },
  ]

  // Funnel derived stats.
  const maxEntered = funnel ? Math.max(...funnel.map((f) => f.entered), 1) : 1
  const decisionWave = funnel?.find((f) => f.wave === 4)
  const fallout = decisionWave ? (100 - decisionWave.pass_rate * 100).toFixed(1) : '—'
  const primaryBlocker = funnel
    ? funnel.reduce((a, b) => (b.blocked > a.blocked ? b : a))
    : null

  const highOverride = (agents ?? []).filter((a) => a.override_pct > 5)

  // Export: agent table as CSV; everything (overview + funnel + agents + risk) as JSON.
  function exportCsv() {
    const headers = ['Persona', 'Decision', 'Decisions', 'Allow %', 'Block %', 'Recommend %', 'Escalate %', 'Override %', 'Avg Review (min)']
    const out = (agents ?? []).map((a) => [
      a.persona, a.decision_id, a.total, a.allow_pct, a.block_pct, a.recommend_pct, a.escalate_pct, a.override_pct, a.avg_review_minutes ?? '',
    ])
    downloadCsv(headers, out, 'accord_analytics_agents')
  }
  function exportJson() {
    downloadJson({ exported_at: new Date().toISOString(), period, overview, funnel, agents, risk }, 'accord_analytics')
  }
  const exportItems = [
    { label: 'Export as CSV', run: exportCsv },
    { label: 'Export as PDF', run: printPdf },
    { label: 'Export raw JSON', run: exportJson },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-10 px-6 py-6">
      {/* 1. Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Portfolio Analytics</h1>
          <p className="text-sm text-gray-500">
            {overview.total_loans.toLocaleString()} loans · {money(overview.total_volume)} pipeline
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PeriodFilter value={period} onChange={setPeriod} />
          <ExportMenu items={exportItems} />
        </div>
      </div>

      {/* 2. KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {kpis.map((k) => (
          <Card key={k.label}>
            <div className="text-xs uppercase tracking-wide text-gray-500">{k.label}</div>
            <div className={`mt-1 text-2xl font-bold ${k.brand ? 'text-brand' : 'text-gray-900'}`}>
              {k.value}
            </div>
            {k.label === 'Pipeline volume' && (
              <div className="mt-0.5 text-xs text-gray-400">{overview.total_loans.toLocaleString()} loans</div>
            )}
          </Card>
        ))}
      </div>

      {/* 3. Funnel chart + approval donut */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Section title="Pipeline Funnel" className="lg:col-span-2">
          <Card>
            {!funnel || funnel.length === 0 ? (
              <p className="text-sm text-gray-400">No data available.</p>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    layout="vertical"
                    data={funnel.map((f) => ({ wave: `W${f.wave} ${WAVE_NAME[f.wave] ?? ''}`, passed: f.passed, blocked: f.blocked }))}
                    margin={{ left: 10, right: 24, top: 8, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tickFormatter={(v) => v.toLocaleString()} tick={{ fontSize: 11 }} />
                    <YAxis type="category" dataKey="wave" width={120} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v: any) => v.toLocaleString()} />
                    <Legend />
                    <Bar dataKey="passed" stackId="a" fill={C_GREEN} name="Passed" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="blocked" stackId="a" fill={C_RED} name="Blocked" radius={[0, 2, 2, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-2 border-t border-gray-100 pt-3 text-sm text-gray-600">
                  Fallout rate: <span className="font-semibold text-red-600">{fallout}%</span>
                  {primaryBlocker && (
                    <> — biggest drop at <span className="font-semibold text-gray-900">Wave {primaryBlocker.wave} ({WAVE_NAME[primaryBlocker.wave]})</span> ({primaryBlocker.blocked.toLocaleString()} blocked)</>
                  )}
                </div>
              </>
            )}
          </Card>
        </Section>

        <Section title="Approval Rate">
          <Card>
            <div className="relative">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={[
                      { name: 'Approved', value: Math.round(overview.approval_rate * overview.total_loans) },
                      { name: 'Not approved', value: overview.total_loans - Math.round(overview.approval_rate * overview.total_loans) },
                    ]}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={60}
                    outerRadius={85}
                    paddingAngle={2}
                    startAngle={90}
                    endAngle={-270}
                  >
                    <Cell fill={C_GREEN} />
                    <Cell fill={C_RED} />
                  </Pie>
                  <Tooltip formatter={(v: any) => v.toLocaleString()} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-2xl font-bold text-brand">{(overview.approval_rate * 100).toFixed(1)}%</div>
                <div className="text-xs text-gray-500">approval rate</div>
              </div>
            </div>
            <div className="mt-2 flex justify-center gap-4 text-xs text-gray-500">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: C_GREEN }} /> Approved</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: C_RED }} /> Not approved</span>
            </div>
          </Card>
        </Section>
      </div>

      {/* 4. Agent performance */}
      <Section
        title="Agent Performance"
        subtext="Override rates above 5% may indicate boundary rules need adjustment."
      >
        <Card className="overflow-hidden p-0">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Persona</th>
                <th className="px-4 py-3 text-right">Decisions</th>
                <th className="px-4 py-3 text-left">Allow %</th>
                <th className="px-4 py-3 text-left">Block %</th>
                <th className="px-4 py-3 text-right">Override %</th>
                <th className="px-4 py-3 text-right">Avg Review</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(agents ?? []).map((a) => {
                const auto = AUTO_DECISIONS.has(a.decision_id)
                const flagged = a.override_pct > 5
                return (
                  <tr key={a.decision_id} className={flagged ? 'bg-amber-50' : ''}>
                    <td className="px-5 py-2.5 font-medium text-gray-800">{a.persona}</td>
                    <td className="px-4 py-2.5 text-right text-gray-600">{a.total.toLocaleString()}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="w-10 font-medium text-green-700">{a.allow_pct}%</span>
                        <div className="h-1.5 w-16 overflow-hidden rounded bg-gray-100">
                          <div className="h-full bg-green-500" style={{ width: `${a.allow_pct}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className={`w-10 font-medium ${a.block_pct > 15 ? 'text-red-600' : 'text-gray-500'}`}>
                          {a.block_pct}%
                        </span>
                        <div className="h-1.5 w-16 overflow-hidden rounded bg-gray-100">
                          <div className="h-full bg-red-400" style={{ width: `${a.block_pct}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={flagged ? 'font-semibold text-amber-700' : 'text-gray-500'}>
                        {flagged && '⚠ '}
                        {a.override_pct}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {auto ? (
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-500">auto</span>
                      ) : (
                        <span className="text-gray-600">{reviewTime(a.avg_review_minutes, false)}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
        <p className={`text-sm ${highOverride.length ? 'text-amber-700' : 'text-gray-400'}`}>
          {highOverride.length
            ? `⚠ ${highOverride.length} persona(s) have override rates above 5% — consider adjusting boundaries.`
            : 'No personas exceed a 5% override rate.'}
        </p>

        {/* Allow vs Block per persona — see who blocks the most at a glance */}
        <Card>
          <div className="mb-2 text-sm font-semibold text-gray-900">Allow vs Block rate by persona</div>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart
              data={(agents ?? []).map((a) => ({ persona: a.persona, 'Allow %': a.allow_pct, 'Block %': a.block_pct }))}
              margin={{ top: 8, right: 16, left: 0, bottom: 90 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="persona" angle={-45} textAnchor="end" interval={0} height={100} tick={{ fontSize: 11 }} />
              <YAxis unit="%" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => `${v}%`} />
              <Legend verticalAlign="top" />
              <Bar dataKey="Allow %" fill={C_GREEN} radius={[2, 2, 0, 0]} />
              <Bar dataKey="Block %" fill={C_RED} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </Section>

      {/* 5. Risk concentration */}
      <Section title="Risk Concentration">
        {risk && (
          <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <ConcentrationCard
                title="Geographic"
                items={risk.by_geography}
                flagOver={25}
                emptyHint="No geographic data available."
              />
              <ConcentrationCard title="Employer" items={risk.by_employer} flagOver={5} />
              <ConcentrationCard title="Product Mix" items={risk.by_product} flagOver={80} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Card>
                <div className="text-xs uppercase tracking-wide text-gray-500">High LTV ( &gt; 90% )</div>
                <div className="mt-1 text-2xl font-bold text-gray-900">
                  {risk.high_ltv.toLocaleString()}
                  <span className="ml-2 text-sm font-medium text-gray-400">
                    {risk.total ? `${((risk.high_ltv / risk.total) * 100).toFixed(1)}% of book` : ''}
                  </span>
                </div>
              </Card>
              <Card>
                <div className="text-xs uppercase tracking-wide text-gray-500">High DTI ( &gt; 43% )</div>
                <div className="mt-1 text-2xl font-bold text-gray-900">
                  {risk.high_dti.toLocaleString()}
                  <span className="ml-2 text-sm font-medium text-gray-400">
                    {risk.total ? `${((risk.high_dti / risk.total) * 100).toFixed(1)}% of book` : ''}
                  </span>
                </div>
              </Card>
            </div>

            {/* Risk charts: top concentration bar + product-mix pie */}
            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card>
                <div className="mb-2 text-sm font-semibold text-gray-900">
                  Top {(risk.by_geography.length ? 'regions' : 'employers')} by loan count
                </div>
                {(() => {
                  const conc = (risk.by_geography.length ? risk.by_geography : risk.by_employer).slice(0, 5)
                  return conc.length === 0 ? (
                    <p className="py-8 text-center text-sm text-gray-400">No concentration data available.</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart layout="vertical" data={conc} margin={{ left: 10, right: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(v: any) => v.toLocaleString()} />
                        <Bar dataKey="count" fill={C_BRAND} radius={[0, 2, 2, 0]} name="Loans" />
                      </BarChart>
                    </ResponsiveContainer>
                  )
                })()}
              </Card>

              <Card>
                <div className="mb-2 text-sm font-semibold text-gray-900">Product mix</div>
                {risk.by_product.length === 0 ? (
                  <p className="py-8 text-center text-sm text-gray-400">No product data available.</p>
                ) : (
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie
                        data={risk.by_product.map((p) => ({ name: prettyName(p.name), value: p.count }))}
                        dataKey="value"
                        nameKey="name"
                        outerRadius={80}
                        label={(e: any) => `${e.name} ${Math.round((e.percent ?? 0) * 100)}%`}
                        labelLine={false}
                      >
                        {risk.by_product.map((_, i) => (
                          <Cell key={i} fill={PRODUCT_COLORS[i % PRODUCT_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: any) => v.toLocaleString()} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </Card>
            </div>
          </>
        )}
      </Section>

      {/* 6. Team performance (managers/admins only) */}
      <TeamPerformanceSection />
    </div>
  )
}

function TeamPerformanceSection() {
  const { user } = useAuth()
  const isManager = user?.role === 'manager' || user?.role === 'admin'
  const [data, setData] = useState<TeamPerformanceResponse | null>(null)

  useEffect(() => {
    if (isManager) fetchTeamPerformance().then(setData).catch(() => undefined)
  }, [isManager])

  if (!isManager || !data) return null
  const flagged = (n: number) => n > 0 && n > data.avg_overrides

  return (
    <Section title="Team Performance">
      <Card>
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="py-2 pr-4">User</th>
              <th className="py-2 pr-4">Role</th>
              <th className="py-2 pr-4 text-right">Active</th>
              <th className="py-2 pr-4 text-right">Decided</th>
              <th className="py-2 pr-4 text-right">Avg time</th>
              <th className="py-2 text-right">Overrides</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((m) => (
              <tr key={m.name} className="border-b border-gray-50">
                <td className="py-2 pr-4 font-medium text-gray-800">{m.name}</td>
                <td className="py-2 pr-4 capitalize text-gray-500">{m.role.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-4 text-right text-gray-700">{m.active}</td>
                <td className="py-2 pr-4 text-right text-gray-700">{m.decided}</td>
                <td className="py-2 pr-4 text-right text-gray-700">{m.avg_days} days</td>
                <td className={`py-2 text-right font-medium ${flagged(m.overrides) ? 'text-rose-600' : 'text-gray-700'}`}>
                  {m.overrides}{flagged(m.overrides) ? ' ⚠' : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.members.some((m) => flagged(m.overrides)) && (
          <p className="mt-3 text-xs text-rose-600">
            ⚠ Flagged: override count above the team average ({data.avg_overrides}).
          </p>
        )}
      </Card>
    </Section>
  )
}

function ConcentrationCard({
  title,
  items,
  flagOver,
  emptyHint,
}: {
  title: string
  items: { name: string; count: number; pct: number }[]
  flagOver: number
  emptyHint?: string
}) {
  const top = items.slice(0, 3)
  const flagged = items.filter((i) => i.pct > flagOver)
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-3 text-sm font-semibold text-gray-900">{title}</div>
      {top.length === 0 ? (
        <p className="text-sm text-gray-400">{emptyHint ?? 'No data available.'}</p>
      ) : (
        <ul className="space-y-2.5">
          {top.map((i) => (
            <li key={i.name}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="truncate text-gray-700">{i.name}</span>
                <span className="ml-2 shrink-0 font-medium text-gray-900">
                  {i.count.toLocaleString()} · {i.pct}%
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-gray-100">
                <div
                  className={`h-full ${i.pct > flagOver ? 'bg-red-400' : 'bg-brand'}`}
                  style={{ width: `${Math.min(i.pct, 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      {flagged.length > 0 && (
        <p className="mt-3 text-xs font-medium text-red-600">
          ⚠ {flagged[0].name} is {flagged[0].pct}% of the portfolio ( &gt; {flagOver}% concentration ).
        </p>
      )}
    </div>
  )
}
