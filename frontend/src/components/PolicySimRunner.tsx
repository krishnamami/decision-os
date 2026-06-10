import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'
import { fetchPrebuiltScenarios, runSimulation } from '../api/client'
import type { SimulationResult } from '../types/accord'

interface Scenario {
  name: string
  type: string
  description: string
}
const TYPE_ORDER = ['policy', 'stress', 'regulatory']
const TYPE_BADGE: Record<string, string> = {
  policy: 'bg-blue-100 text-blue-700',
  stress: 'bg-orange-100 text-orange-700',
  regulatory: 'bg-violet-100 text-violet-700',
}

function money(v: number) {
  const m = Math.abs(v)
  if (m >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (m >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

export interface PolicySimHandle {
  run: (scenarioName: string) => void
}

const PolicySimRunner = forwardRef<PolicySimHandle>((_props, ref) => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [runningName, setRunningName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchPrebuiltScenarios().then((r) => setScenarios(r.scenarios)).catch(() => undefined)
  }, [])

  async function run(name: string) {
    setRunningName(name)
    setError(null)
    setResult(null)
    try {
      setResult(await runSimulation(name))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setRunningName(null)
    }
  }

  useImperativeHandle(ref, () => ({ run }))

  const grouped = TYPE_ORDER.map((t) => ({ type: t, items: scenarios.filter((s) => s.type === t) })).filter(
    (g) => g.items.length,
  )
  const im = result?.impact

  return (
    <div className="space-y-5">
      {/* Scenarios grouped by type */}
      <div className="space-y-5">
        {grouped.map((g) => (
          <div key={g.type}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{g.type}</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {g.items.map((s) => (
                <div key={s.name} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900">{s.name}</span>
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${TYPE_BADGE[s.type] ?? 'bg-slate-100 text-slate-600'}`}>
                        {s.type}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{s.description}</p>
                  </div>
                  <button
                    onClick={() => run(s.name)}
                    disabled={!!runningName}
                    className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
                  >
                    {runningName === s.name ? 'Running…' : 'Run →'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {runningName && (
        <div className="rounded-xl bg-brand-light/60 px-5 py-4 text-sm font-medium text-brand">
          Evaluating the portfolio with modified rules…
        </div>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Result */}
      {result && im && (
        <div className="space-y-5">
          {/* A. Impact cards 2x2 */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <ImpactCard label="Apps affected" value={`${result.affected_apps.toLocaleString()}`} sub={`of ${result.total_apps.toLocaleString()}`} />
            <ImpactCard
              label="Volume change"
              value={money(im.volume_change ?? 0)}
              negative={(im.volume_change ?? 0) < 0}
            />
            <ImpactCard
              label="Approval rate"
              value={`${((im.approval_rate_before ?? 0) * 100).toFixed(1)}% → ${((im.approval_rate_after ?? 0) * 100).toFixed(1)}%`}
              negative={(im.approval_rate_change ?? 0) < 0}
            />
            <ImpactCard label="New blocks" value={String(im.new_blocks ?? 0)} negative={(im.new_blocks ?? 0) > 0} />
          </div>

          {/* B. Affected loans table */}
          {result.flipped.length > 0 && (
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Affected loans (first 25 of {result.flipped.length})
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="px-4 py-2 text-left">App ID</th>
                      <th className="px-4 py-2 text-left">Borrower</th>
                      <th className="px-4 py-2 text-left">Decision</th>
                      <th className="px-4 py-2 text-left">From → To</th>
                      <th className="px-4 py-2 text-right">Amount</th>
                      <th className="px-4 py-2 text-left">Agent Reasoning</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {result.flipped.slice(0, 25).map((f, i) => (
                      <tr key={i} className="align-top">
                        <td className="px-4 py-2 font-mono text-xs text-slate-500">{f.application_id}</td>
                        <td className="px-4 py-2 text-slate-700">{f.borrower_name}</td>
                        <td className="px-4 py-2 text-slate-600">{f.decision_id}</td>
                        <td className="px-4 py-2 font-medium text-amber-700 whitespace-nowrap">
                          {f.from_outcome} → {f.to_outcome}
                        </td>
                        <td className="px-4 py-2 text-right text-slate-700">{money(f.loan_amount)}</td>
                        <td className="px-4 py-2 text-xs leading-snug text-slate-600">{f.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* C. Agent insights */}
          {result.agent_insights.length > 0 && (
            <div className="space-y-2">
              <div className="text-base font-semibold text-slate-900">Agent insights</div>
              {result.agent_insights.map((ins, i) => (
                <p key={i} className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{ins}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
})

function ImpactCard({ label, value, sub, negative }: { label: string; value: string; sub?: string; negative?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-bold ${negative ? 'text-red-600' : 'text-slate-900'}`}>{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

export default PolicySimRunner
