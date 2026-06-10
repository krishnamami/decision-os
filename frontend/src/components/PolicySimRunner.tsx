// Policy Simulator — runs a what-if scenario across the whole book and explains
// the impact in plain English: a one-line summary, impact cards, a status-change
// table, per-loan WHY / WHAT-TO-DO, and a should-you-do-this recommendation.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { fetchPipeline, fetchPrebuiltScenarios, runSimulation } from '../api/client'
import type { SimulationFlip, SimulationResult } from '../types/accord'

interface Scenario { name: string; type: string; description: string }

const GROUPS = [
  { type: 'policy', title: 'POLICY CHANGES', sub: 'What if we tighten or loosen our rules?' },
  { type: 'stress', title: 'STRESS TESTS', sub: 'What if the market changes?' },
  { type: 'regulatory', title: 'REGULATORY', sub: 'What if the rules change?' },
]
const TYPE_BADGE: Record<string, string> = {
  policy: 'bg-blue-100 text-blue-700',
  stress: 'bg-orange-100 text-orange-700',
  regulatory: 'bg-violet-100 text-violet-700',
}

// Raw outcome → plain-English status + pill colour.
const STATUS_LABEL: Record<string, string> = { allow: 'Approved', recommend: 'Needs Review', escalate: 'Escalated', block: 'Blocked' }
const STATUS_PILL: Record<string, string> = {
  allow: 'bg-green-100 text-green-800', recommend: 'bg-amber-100 text-amber-800',
  escalate: 'bg-orange-100 text-orange-800', block: 'bg-red-100 text-red-800',
}
const CUR_VERB: Record<string, string> = { allow: 'qualify', recommend: 'need review', escalate: 'are escalated', block: 'are blocked' }
const FUT_VERB: Record<string, string> = { allow: 'qualify automatically', recommend: 'need additional review', escalate: 'be escalated', block: 'be blocked' }
const DECISION_LABEL: Record<string, string> = {
  dti_calculation: 'Debt-to-Income', ltv_assessment: 'Down Payment & Equity',
  credit_assessment: 'Credit', income_verification: 'Income', product_eligibility: 'Loan Program',
  rate_pricing: 'Interest Rate', underwriting_decision: 'Underwriting',
}
const decisionLabel = (k: string) => DECISION_LABEL[k] ?? k.replace(/_/g, ' ')

function money(v: number) {
  const m = Math.abs(v)
  if (m >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (m >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (m >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${Math.round(v)}`
}
const mode = (arr: string[]) => {
  const c: Record<string, number> = {}
  arr.forEach((x) => (c[x] = (c[x] || 0) + 1))
  return Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0] ?? ''
}

// Turn a scenario name into a natural clause ("tighten the DTI limit from 43% to 36%").
function describeChange(name: string): string {
  const arrow = name.includes('→') ? '→' : name.includes('->') ? '->' : ''
  if (arrow && name.includes(':')) {
    const label = name.slice(0, name.indexOf(':')).trim()
    const [a, b] = name.slice(name.indexOf(':') + 1).split(arrow).map((s) => s.trim())
    const na = parseFloat(a.replace(/[^0-9.]/g, '')), nb = parseFloat(b.replace(/[^0-9.]/g, ''))
    const L = label.toLowerCase()
    if (L.startsWith('dti')) return `${nb < na ? 'tighten' : 'loosen'} the debt-to-income limit from ${a} to ${b}`
    if (L.startsWith('credit')) return `${nb > na ? 'raise' : 'lower'} the minimum credit score from ${a} to ${b}`
    if (L.startsWith('ltv')) return `${nb < na ? 'tighten' : 'loosen'} the LTV cap from ${a} to ${b}`
    if (L.startsWith('conforming')) return `${nb > na ? 'raise' : 'lower'} the conforming loan limit from ${a} to ${b}`
    return `change ${label} from ${a} to ${b}`
  }
  return `model ${name.charAt(0).toLowerCase()}${name.slice(1)}`
}

// Split the agent reason into WHY (cause) and WHAT TO DO (remedy).
function splitReason(reason: string): { why: string; todo: string } {
  const i = reason.search(/\bTo (qualify|pass|clear|meet|re-?qualify)\b/i)
  if (i > 0) return { why: reason.slice(0, i).trim(), todo: reason.slice(i).trim() }
  return { why: reason, todo: 'To qualify under the new rule, the borrower would need stronger compensating factors — higher income, lower obligations, or a smaller loan amount.' }
}

const CANON: Array<[string, string]> = [
  ['allow', 'recommend'], ['allow', 'block'], ['recommend', 'block'], ['block', 'allow'],
]

export interface PolicySimHandle {
  run: (scenarioName: string) => void
}

const PolicySimRunner = forwardRef<PolicySimHandle>((_props, ref) => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [runningName, setRunningName] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [portfolioTotal, setPortfolioTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchPrebuiltScenarios().then((r) => setScenarios(r.scenarios)).catch(() => undefined)
    fetchPipeline({ limit: 1 }).then((r) => setPortfolioTotal(r.kpis.total)).catch(() => undefined)
  }, [])

  // Ramp a progress bar while a scenario is evaluating.
  useEffect(() => {
    if (!runningName) return
    setProgress(8)
    const id = setInterval(() => setProgress((p) => Math.min(p + Math.random() * 18, 95)), 350)
    return () => clearInterval(id)
  }, [runningName])

  async function run(name: string) {
    setRunningName(name)
    setError(null)
    setResult(null)
    setShowAll(false)
    try {
      const r = await runSimulation(name)
      setProgress(100)
      setResult(r)
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setRunningName(null)
    }
  }

  useImperativeHandle(ref, () => ({ run }))

  const grouped = GROUPS.map((g) => ({ ...g, items: scenarios.filter((s) => s.type === g.type) })).filter((g) => g.items.length)

  return (
    <div className="space-y-5">
      {/* 1. Scenario cards grouped by type */}
      <div className="space-y-6">
        {grouped.map((g) => (
          <div key={g.type}>
            <div className="mb-2">
              <span className="text-sm font-bold text-slate-800">{g.title}</span>
              <span className="text-sm text-slate-500"> — {g.sub}</span>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {g.items.map((s) => (
                <div key={s.name} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900">{s.name}</span>
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${TYPE_BADGE[s.type] ?? 'bg-slate-100 text-slate-600'}`}>{s.type}</span>
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

      {/* 2. Loading */}
      {runningName && (
        <div className="rounded-xl border border-brand/20 bg-brand-light/40 p-5">
          <div className="text-sm font-medium text-brand">
            Evaluating {portfolioTotal ? portfolioTotal.toLocaleString() : 'all'} loans with the new rules…
          </div>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white">
            <div className="h-full rounded-full bg-brand transition-all duration-300" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* 3. Results */}
      {result && !runningName && <Results result={result} total={result.total_apps} showAll={showAll} setShowAll={setShowAll} ref={resultRef} />}
    </div>
  )
})

const Results = forwardRef<HTMLDivElement, { result: SimulationResult; total: number; showAll: boolean; setShowAll: (v: boolean) => void }>(
  ({ result, total, showAll, setShowAll }, ref) => {
    const im = result.impact
    const flipped = result.flipped
    const affected = result.affected_apps
    const vol = im.volume_change ?? 0
    const fromO = mode(flipped.map((f) => f.from_outcome))
    const toO = mode(flipped.map((f) => f.to_outcome))

    // Big-picture sentence.
    const change = describeChange(result.scenario.name)
    const tail = vol === 0 ? 'pipeline volume is unaffected' : `you'd ${vol < 0 ? 'lose' : 'gain'} ${money(Math.abs(vol))} in pipeline volume`
    const summary = affected === 0
      ? `If you ${change}, nothing changes — all ${total.toLocaleString()} loans keep their current status, and pipeline volume is unaffected.`
      : `If you ${change}, ${affected} ${affected === 1 ? 'loan' : 'loans'} that currently ${CUR_VERB[fromO] ?? 'qualify'} would ${FUT_VERB[toO] ?? 'change status'} — ${tail}.`

    // Status-change table rows.
    const affectedVol = flipped.reduce((a, f) => a + (f.loan_amount || 0), 0)
    const byPair: Record<string, { count: number; vol: number }> = {}
    flipped.forEach((f) => {
      const k = `${f.from_outcome}→${f.to_outcome}`
      byPair[k] = byPair[k] || { count: 0, vol: 0 }
      byPair[k].count++
      byPair[k].vol += f.loan_amount || 0
    })
    const seen = new Set<string>()
    const rows = CANON.map(([fr, to]) => {
      const k = `${fr}→${to}`; seen.add(k)
      return { label: `${STATUS_LABEL[fr]} → ${STATUS_LABEL[to]}`, ...(byPair[k] ?? { count: 0, vol: 0 }) }
    })
    Object.entries(byPair).filter(([k]) => !seen.has(k)).forEach(([k, v]) => {
      const [fr, to] = k.split('→')
      rows.push({ label: `${STATUS_LABEL[fr] ?? fr} → ${STATUS_LABEL[to] ?? to}`, ...v })
    })
    rows.push({ label: 'No change', count: total - affected, vol: (im.volume_before ?? 0) - affectedVol })

    const stricter = vol < 0
    const shown = showAll ? flipped : flipped.slice(0, 6)

    return (
      <div ref={ref} className="space-y-5">
        {/* A. Plain-English summary FIRST */}
        <div className="rounded-xl border border-brand/30 bg-brand-light/30 p-5">
          <div className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-brand">
            📋 What happens if you {change}
          </div>
          <p className="text-base leading-relaxed text-slate-800">{summary}</p>
        </div>

        {/* B. Impact cards */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <ImpactCard label="Loans affected" big={`${affected.toLocaleString()}`} sub={`of ${total.toLocaleString()} (${((affected / Math.max(total, 1)) * 100).toFixed(1)}%)`} />
          <ImpactCard label="Money impact" big={money(vol)} sub={`${((vol / Math.max(im.volume_before ?? 1, 1)) * 100).toFixed(1)}% of volume`} negative={vol < 0} />
          <ImpactCard label="Approval rate" big={`${((im.approval_rate_before ?? 0) * 100).toFixed(1)}% → ${((im.approval_rate_after ?? 0) * 100).toFixed(1)}%`} sub="current → simulated" negative={(im.approval_rate_change ?? 0) < 0} />
          <ImpactCard label="New blocks" big={String(im.new_blocks ?? 0)} sub="lost auto-approval" negative={(im.new_blocks ?? 0) > 0} />
        </div>

        {/* C. Status change table */}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            How statuses change
          </div>
          <table className="min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">Status change</th>
                <th className="px-4 py-2 text-right">Count</th>
                <th className="px-4 py-2 text-right">Volume</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.label} className={r.count > 0 && r.label !== 'No change' ? 'bg-amber-50/50' : ''}>
                  <td className="px-4 py-2 font-medium text-slate-700">{r.label}</td>
                  <td className="px-4 py-2 text-right text-slate-700">{r.count.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-slate-600">{money(r.vol)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* D. Affected loans — WHY / WHAT TO DO */}
        {flipped.length > 0 && (
          <div className="space-y-3">
            <div className="text-base font-semibold text-slate-900">Which loans are affected</div>
            {shown.map((f, i) => <AffectedLoan key={i} f={f} />)}
            {flipped.length > 6 && (
              <button onClick={() => setShowAll(!showAll)} className="text-sm font-medium text-brand hover:underline">
                {showAll ? 'Show fewer ▲' : `Show all ${flipped.length} affected loans ▼`}
              </button>
            )}
          </div>
        )}

        {/* E. Recommendation */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="mb-2 text-base font-semibold text-slate-900">🤔 Should you make this change?</div>
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">Trade-off</div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
            <li>{stricter ? 'Stricter rules lower portfolio risk but reduce pipeline volume.' : 'Looser rules grow volume but take on more risk.'}</li>
            <li>{affected.toLocaleString()} loan{affected === 1 ? '' : 's'} affected ({money(Math.abs(vol))}); approval rate {((im.approval_rate_before ?? 0) * 100).toFixed(1)}% → {((im.approval_rate_after ?? 0) * 100).toFixed(1)}%.</li>
          </ul>
          <div className="mt-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Consider</div>
          <p className="mt-1 text-sm text-slate-700">
            {stricter
              ? 'Add an exception process for borrowers within ~1% of the new limit who have strong compensating factors (high credit score, low LTV, long job tenure).'
              : 'Add tighter monitoring of the newly-qualifying cohort for early-payment-default risk, and cap exceptions by credit tier.'}
          </p>
        </div>

        {/* F. Agent insights (kept) */}
        {result.agent_insights.length > 0 && (
          <div className="space-y-2">
            <div className="text-base font-semibold text-slate-900">Agent insights</div>
            {result.agent_insights.map((ins, i) => (
              <p key={i} className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{ins}</p>
            ))}
          </div>
        )}
      </div>
    )
  },
)

function ImpactCard({ label, big, sub, negative }: { label: string; big: string; sub?: string; negative?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-bold ${negative ? 'text-red-600' : 'text-slate-900'}`}>{big}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

function AffectedLoan({ f }: { f: SimulationFlip }) {
  const { why, todo } = splitReason(f.reason)
  const showId = f.borrower_name !== f.application_id
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-900">{f.borrower_name}</span>
        <span className="text-slate-400">·</span>
        <span className="text-slate-700">{money(f.loan_amount)}</span>
        {showId && <span className="font-mono text-xs text-slate-400">{f.application_id}</span>}
        <span className="ml-auto flex items-center gap-1.5 text-xs">
          <span className="text-slate-400">{decisionLabel(f.decision_id)}:</span>
          <span className={`rounded px-1.5 py-0.5 font-medium ${STATUS_PILL[f.from_outcome] ?? 'bg-slate-100'}`}>{STATUS_LABEL[f.from_outcome] ?? f.from_outcome}</span>
          <span className="text-slate-400">→</span>
          <span className={`rounded px-1.5 py-0.5 font-medium ${STATUS_PILL[f.to_outcome] ?? 'bg-slate-100'}`}>{STATUS_LABEL[f.to_outcome] ?? f.to_outcome}</span>
        </span>
      </div>
      <div className="mt-2.5">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Why</div>
        <p className="text-sm leading-relaxed text-slate-600">{why}</p>
      </div>
      <div className="mt-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">What to do</div>
        <p className="text-sm leading-relaxed text-slate-800">{todo}</p>
      </div>
    </div>
  )
}

export default PolicySimRunner
