import { useEffect, useRef, useState } from 'react'
import { fetchSimHistory, type SimHistoryRow } from '../api/client'
import DebateRunner from '../components/DebateRunner'
import PolicySimRunner, { type PolicySimHandle } from '../components/PolicySimRunner'
import SwarmRunner from '../components/SwarmRunner'
import PeriodFilter, { type Period } from '../components/PeriodFilter'

const PERIOD_DAYS: Record<Period, number | null> = {
  month: 30, quarter: 90, year: 365, all: null,
}

const MODES = [
  { key: 'debate', icon: '💬', title: 'Agent Debate', desc: 'Pick a loan. Watch 12 AI agents argue about it in 3 rounds.', accent: 'border-l-green-500' },
  { key: 'simulate', icon: '📋', title: 'Policy Simulator', desc: 'Change DTI, credit, LTV thresholds. See impact across your portfolio.', accent: 'border-l-blue-500' },
  { key: 'swarm', icon: '🔍', title: 'Portfolio Health Check', desc: '12 AI agents scan every loan for hidden risks, fraud, and concentration patterns.', accent: 'border-l-violet-500' },
]

function money(v: number) {
  const m = Math.abs(v)
  if (m >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (m >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

export default function Simulation() {
  const debateRef = useRef<HTMLDivElement>(null)
  const simRef = useRef<HTMLDivElement>(null)
  const swarmRef = useRef<HTMLDivElement>(null)
  const policy = useRef<PolicySimHandle>(null)
  const [history, setHistory] = useState<SimHistoryRow[]>([])
  const [period, setPeriod] = useState<Period>('all')

  useEffect(() => {
    fetchSimHistory().then((r) => setHistory(r.simulations)).catch(() => undefined)
  }, [])

  // Past runs are filtered client-side by their created_at against the range.
  const days = PERIOD_DAYS[period]
  const cutoff = days == null ? null : Date.now() - days * 86_400_000
  const visibleHistory =
    cutoff == null
      ? history
      : history.filter((h) => h.created_at && new Date(h.created_at).getTime() >= cutoff)

  function scrollTo(key: string) {
    const ref = key === 'debate' ? debateRef : key === 'simulate' ? simRef : swarmRef
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function viewHistory(row: SimHistoryRow) {
    simRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    policy.current?.run(row.scenario_name)
  }

  return (
    <div>
      {/* 1. Hero */}
      <div className="px-6 py-12 text-center text-white" style={{ background: 'linear-gradient(135deg, #0F6E56, #1D9E75)' }}>
        <div className="text-5xl">🐟</div>
        <h1 className="mt-3 text-3xl font-bold">MiroFish Portfolio Simulator</h1>
        <p className="mt-2 text-base text-white/80">Change a rule. Debate a loan. Scan for patterns.</p>
      </div>

      <div className="mx-auto max-w-6xl space-y-12 px-6 py-8">
        {/* 2. Mode cards */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {MODES.map((m) => (
            <button
              key={m.key}
              onClick={() => scrollTo(m.key)}
              className={`rounded-xl border border-slate-200 border-l-4 bg-white p-5 text-left shadow-sm transition hover:shadow-md ${m.accent}`}
            >
              <div className="text-2xl">{m.icon}</div>
              <div className="mt-2 text-lg font-semibold text-slate-900">{m.title}</div>
              <p className="mt-1 text-sm text-slate-500">{m.desc}</p>
            </button>
          ))}
        </div>

        {/* 3. Debate */}
        <section ref={debateRef} className="scroll-mt-24 space-y-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Agent Debate</h2>
            <p className="text-sm text-slate-500">Pick a loan, watch 12 agents deliberate.</p>
          </div>
          <DebateRunner />
        </section>

        {/* 4. Policy Simulator */}
        <section ref={simRef} className="scroll-mt-24 space-y-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Policy Simulator</h2>
            <p className="text-sm text-slate-500">Change a rule, see the impact across your portfolio.</p>
          </div>
          <PolicySimRunner ref={policy} />
        </section>

        {/* 5. Swarm */}
        <section ref={swarmRef} className="scroll-mt-24 space-y-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Portfolio Health Check</h2>
            <p className="text-sm text-slate-500">12 AI agents scan every loan looking for hidden risks and patterns.</p>
          </div>
          <SwarmRunner />
        </section>

        {/* 6. History */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">Simulation History</h2>
            <PeriodFilter value={period} onChange={setPeriod} />
          </div>
          {history.length === 0 ? (
            <p className="text-sm text-slate-400">No simulations run yet.</p>
          ) : visibleHistory.length === 0 ? (
            <p className="text-sm text-slate-400">No simulations in this period.</p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Date</th>
                    <th className="px-4 py-2 text-left">Type</th>
                    <th className="px-4 py-2 text-left">Scenario</th>
                    <th className="px-4 py-2 text-right">Affected</th>
                    <th className="px-4 py-2 text-right">Volume Δ</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visibleHistory.map((h) => (
                    <tr key={h.simulation_id}>
                      <td className="px-4 py-2 text-slate-600">
                        {h.created_at ? new Date(h.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-2 capitalize text-slate-500">{h.scenario_type}</td>
                      <td className="px-4 py-2 text-slate-800">{h.scenario_name}</td>
                      <td className="px-4 py-2 text-right text-slate-600">{h.affected_apps.toLocaleString()}</td>
                      <td className="px-4 py-2 text-right text-slate-600">
                        {h.impact?.volume_change != null ? money(h.impact.volume_change) : '—'}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => viewHistory(h)} className="text-sm font-medium text-brand hover:underline">
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
