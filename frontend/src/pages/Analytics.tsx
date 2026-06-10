import { useEffect, useState, type ReactNode } from 'react'
import { fetchAgents, fetchAnalytics, fetchFunnel, fetchRisk } from '../api/client'
import type { AgentStat, AnalyticsOverview, FunnelStep, RiskData } from '../types/accord'
import PeriodFilter, { type Period, periodParam } from '../components/PeriodFilter'

// Auto-execute personas (system-finalized) — get an "auto" review badge.
const AUTO_DECISIONS = new Set([
  'credit_assessment', 'fraud_screening', 'dti_calculation',
  'ltv_assessment', 'rate_pricing', 'approval_routing',
])
const WAVE_NAME: Record<number, string> = {
  1: 'Pre-UW', 2: 'Underwriting', 3: 'Product', 4: 'Decision', 5: 'Closing',
}

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

function Section({ title, subtext, children }: { title: string; subtext?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
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
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Failed to load analytics'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [period])

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
    return <div className="mx-auto max-w-6xl px-6 py-12 text-center text-red-600">{error}</div>
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

  return (
    <div className="mx-auto max-w-6xl space-y-10 px-6 py-6">
      {/* 1. Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Portfolio Analytics</h1>
          <p className="text-sm text-gray-500">
            Last updated: {new Date().toLocaleDateString(undefined, { dateStyle: 'long' } as any)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PeriodFilter value={period} onChange={setPeriod} />
          <button className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Export Report
          </button>
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

      {/* 3. Funnel */}
      <Section title="Pipeline Funnel">
        <Card>
          {!funnel || funnel.length === 0 ? (
            <p className="text-sm text-gray-400">No data available.</p>
          ) : (
            <div className="space-y-3">
              {funnel.map((f) => {
                const width = (f.entered / maxEntered) * 100
                const passW = f.entered ? (f.passed / f.entered) * 100 : 0
                const blockW = f.entered ? (f.blocked / f.entered) * 100 : 0
                return (
                  <div key={f.wave} className="flex items-center gap-3">
                    <div className="w-40 shrink-0 text-sm">
                      <span className="font-medium text-gray-800">Wave {f.wave}</span>{' '}
                      <span className="text-gray-400">({WAVE_NAME[f.wave] ?? ''})</span>
                    </div>
                    <div className="flex-1">
                      <div className="h-6 w-full overflow-hidden rounded bg-gray-100" style={{ maxWidth: `${width}%` }}>
                        <div className="flex h-full">
                          <div className="bg-green-500" style={{ width: `${passW}%` }} />
                          <div className="bg-red-400" style={{ width: `${blockW}%` }} />
                        </div>
                      </div>
                    </div>
                    <div className="w-56 shrink-0 text-right text-xs text-gray-500">
                      {f.entered.toLocaleString()} entered ·{' '}
                      <span className="font-medium text-green-700">{f.passed.toLocaleString()} passed</span> ·{' '}
                      <span className="font-medium text-red-600">{f.blocked.toLocaleString()} blocked</span> ·{' '}
                      {(f.pass_rate * 100).toFixed(0)}%
                    </div>
                  </div>
                )
              })}
              <div className="flex flex-wrap gap-x-8 gap-y-1 border-t border-gray-100 pt-3 text-sm">
                <span className="text-gray-600">
                  Fallout rate: <span className="font-semibold text-red-600">{fallout}%</span>
                </span>
                {primaryBlocker && (
                  <span className="text-gray-600">
                    Primary blocker:{' '}
                    <span className="font-semibold text-gray-900">
                      Wave {primaryBlocker.wave} ({WAVE_NAME[primaryBlocker.wave]})
                    </span>{' '}
                    — {primaryBlocker.blocked.toLocaleString()} blocked
                  </span>
                )}
              </div>
            </div>
          )}
        </Card>
      </Section>

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
          </>
        )}
      </Section>
    </div>
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
