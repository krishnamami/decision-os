// Portfolio Health Check — the user-facing face of the MiroFish swarm.
// 12 agents scan every loan; this turns their raw findings into plain English
// that a non-expert can act on.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchSwarmLatest, runSwarm } from '../api/client'
import type { SwarmInsight, SwarmResult } from '../types/accord'

// ── What the health check looks for (static explainer cards) ─────────
const CHECK_CARDS = [
  { icon: '🏦', title: 'Fraud & Identity', text: 'Watchlist matches, fake identities, straw buyers' },
  { icon: '💰', title: 'Income & Employment', text: 'Income gaps, employer concentration, job stability patterns' },
  { icon: '🏠', title: 'Property & Value', text: 'Value declines, thin equity, appraisal clustering' },
  { icon: '📊', title: 'Risk & Compliance', text: 'Concentration risk, product diversity, regulatory exposure' },
]

// ── Progressive loading messages (which agent is scanning) ───────────
const LOADING_STAGES = [
  '🏦 Checking for fraud patterns…',
  '💰 Analyzing income discrepancies…',
  '🏠 Evaluating property values…',
  '📊 Looking for concentration risks…',
  '🔗 Cross-referencing all findings…',
]

// ── Urgency buckets ──────────────────────────────────────────────────
const GROUPS = [
  { keys: ['critical'], heading: '🔴 URGENT', sub: 'Act immediately', border: 'border-l-red-500', dot: 'text-red-600', collapsed: false },
  { keys: ['warning'], heading: '🟡 WARNING', sub: 'Review this week', border: 'border-l-amber-400', dot: 'text-amber-600', collapsed: false },
  { keys: ['info', 'emergent'], heading: 'ℹ️ GOOD TO KNOW', sub: 'Informational', border: 'border-l-slate-300', dot: 'text-slate-500', collapsed: true },
]

// ── Plain-English agent names ────────────────────────────────────────
const AGENT_NAME: Record<string, string> = {
  credit_assessment: 'Credit Check',
  fraud_screening: 'Fraud Detection',
  compliance_check: 'Compliance & Fair Lending',
  employment_reconciliation: 'Employment Check',
  income_verification: 'Income Check',
  ltv_assessment: 'Down Payment & Equity',
  dti_calculation: 'Debt-to-Income',
  product_eligibility: 'Loan Program',
  rate_pricing: 'Interest Rate',
  underwriting_decision: 'Final Underwriting',
  approval_routing: 'Routing & Notices',
  closing_readiness: 'Closing Check',
}
const agentName = (k: string) => AGENT_NAME[k] ?? k.replace(/_/g, ' ')

function ev(ins: SwarmInsight): Record<string, any> {
  return (ins.evidence?.[0] as Record<string, any>) ?? {}
}
// The true affected count lives in the evidence; affected_apps is sampled (≤25).
function trueCount(ins: SwarmInsight): number {
  const e = ev(ins)
  return e.count ?? e.expiring ?? e.blocked ?? ins.affected_apps.length
}
const n = (v: number) => v.toLocaleString()
const PRODUCT_AGENCY: Record<string, string> = {
  conforming: 'Fannie Mae or Freddie Mac',
  government: 'the FHA/VA',
  jumbo: 'the investor',
  non_qm: 'the investor',
}

// Turn a raw finding into a plain-English { title, text, impact? }.
function translate(ins: SwarmInsight, total: number): { title: string; text: string; impact?: string } {
  const e = ev(ins)
  const metric: string = e.metric || (e.loan_type ? 'product_concentration' : e.week ? 'rate_lock_cluster' : '')
  const c = trueCount(ins)
  const pct = (count: number) => Math.round((count / Math.max(total, 1)) * 100)

  switch (metric) {
    case 'watchlist_or_synthetic':
      return {
        title: `${c} LOAN${c === 1 ? '' : 'S'} FLAGGED FOR POSSIBLE FRAUD`,
        text: `${c} borrower${c === 1 ? '' : 's'} matched a federal watchlist or showed signs of a fake / synthetic identity. These loans should be frozen and reviewed before any further processing.`,
      }
    case 'high_ltv_and_high_dti':
      return {
        title: `${c} LOANS ARE HIGH-RISK ON TWO FRONTS AT ONCE`,
        text: `${c} loans have BOTH a small down payment (over 90% loan-to-value) and a stretched budget (over 43% debt-to-income). Thin equity plus tight income means these are the first to fail if rates rise or home prices dip.`,
      }
    case 'portfolio_discrepancy_rate': {
      const p = e.pct ?? pct(c)
      return {
        title: p >= 45 ? 'NEARLY HALF YOUR LOANS HAVE INCOME GAPS' : `${Math.round(p)}% OF YOUR LOANS HAVE INCOME GAPS`,
        text: `${n(c)} loans (${p}%) show a gap between what borrowers say they earn and what their documents show. This isn't random — it's a pattern. Your intake process may not be catching income overstatements early enough.`,
        impact: `${n(c)} loans with a stated-vs-verified income mismatch`,
      }
    }
    case 'ltv_gt_90':
      return {
        title: `${n(c)} LOANS HAVE LESS THAN 10% DOWN PAYMENT`,
        text: `${pct(c)}% of your loans have very thin equity (over 90% loan-to-value). If home prices drop even 5%, these borrowers could owe more than their home is worth.`,
      }
    case 'product_concentration': {
      const lt = String(e.loan_type ?? 'one type')
      const p = pct(e.count ?? c)
      return {
        title: 'ALMOST NO PRODUCT DIVERSIFICATION',
        text: `${p}% of your loans are the same type (${lt}). If ${PRODUCT_AGENCY[lt] ?? 'the agency'} changes one guideline, your entire portfolio is affected. Consider diversifying.`,
      }
    }
    case 'rate_lock_cluster':
      return {
        title: 'ALL RATE LOCKS EXPIRE THE SAME WEEK',
        text: `${n(e.expiring ?? c)} rate locks all expire in ${e.week}. Any loans not closed by then will need to be re-locked at current rates — which usually costs money and can change the borrower's monthly payment.`,
      }
    case 'uw_block_rate': {
      const p = pct(e.blocked ?? c)
      return {
        title: `${Math.round(p / 10)} OUT OF 10 LOANS ARE BEING DECLINED`,
        text: `Your decline rate of ${p}% is unusually high. Either the loans coming in are low quality, or your underwriting rules are too strict. The industry average is around 30%.`,
      }
    }
    case 'title_insurance_gaps':
      return {
        title: `${n(c)} LOANS HAVE CLOSING BLOCKERS`,
        text: `${n(c)} loans have an open title defect, lien dispute, or insurance gap. These need to be worked now, in parallel — not discovered at the closing table.`,
      }
    case 'gap_gt_90d':
      return {
        title: `${n(c)} LOANS HAVE EMPLOYMENT GAPS`,
        text: `${n(c)} borrowers have a gap of more than 90 days in their work history. This is common, but these files likely need a simple gap-explanation letter before closing.`,
      }
    case 'loan_over_5x_income':
      return {
        title: `${n(c)} LOANS ARE LARGE RELATIVE TO INCOME`,
        text: `${n(c)} loans are more than 5× the borrower's verified annual income. High leverage isn't automatically bad, but these are worth a second look.`,
      }
    case 'adverse_action_volume':
      return {
        title: `${n(c)} DECLINE NOTICES MUST GO OUT ON TIME`,
        text: `${n(c)} declined files require an adverse-action notice. By law (ECOA) these have strict timing — make sure none slip past the deadline.`,
      }
    default:
      return { title: ins.insight_type.replace(/_/g, ' ').toUpperCase(), text: ins.description }
  }
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return '—'
  }
}

// ── One finding card ─────────────────────────────────────────────────
function FindingCard({ ins, index, border, total }: { ins: SwarmInsight; index: number; border: string; total: number }) {
  const navigate = useNavigate()
  const [showAll, setShowAll] = useState(false)
  const t = translate(ins, total)
  const ids = ins.affected_apps
  const shown = showAll ? ids : ids.slice(0, 3)
  const extra = trueCount(ins) - 3
  const detected = ins.detected_by.map(agentName)
  const detectedLabel = detected.length > 1 ? `${detected.join(' + ')} working together` : detected[0] ?? 'AI agent'

  return (
    <div className={`rounded-xl border border-l-4 ${border} border-slate-200 bg-white p-4 shadow-sm`}>
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-sm font-bold text-slate-400">{index}.</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold tracking-tight text-slate-900">{t.title}</div>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{t.text}</p>
          {t.impact && (
            <p className="mt-1 text-sm font-medium text-slate-800">📉 {t.impact}</p>
          )}

          {/* Who is affected */}
          {ids.length > 0 && (
            <div className="mt-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Who is affected</div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {shown.map((a) => (
                  <button
                    key={a}
                    onClick={() => navigate(`/pipeline/${a}`)}
                    className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 hover:bg-slate-200"
                  >
                    {a}
                  </button>
                ))}
                {!showAll && extra > 0 && (
                  <button onClick={() => setShowAll(true)} className="text-[11px] font-medium text-brand hover:underline">
                    + {n(extra)} more
                  </button>
                )}
                {showAll && trueCount(ins) > ids.length && (
                  <span className="text-[11px] text-slate-400">…and {n(trueCount(ins) - ids.length)} more not listed</span>
                )}
              </div>
            </div>
          )}

          {/* What found it + action */}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-slate-500">
              Detected by: <span className="font-medium text-slate-700">{detectedLabel}</span>
            </span>
            {ids.length > 0 && (
              <button
                onClick={() => navigate(`/pipeline/${ids[0]}`)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-brand hover:bg-slate-50"
              >
                View flagged loans →
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function SwarmRunner() {
  const [result, setResult] = useState<SwarmResult | null>(null)
  const [latest, setLatest] = useState<SwarmResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [showSummaries, setShowSummaries] = useState(false)
  const [showInfo, setShowInfo] = useState(false)
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchSwarmLatest().then(setLatest).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!loading) return
    setStage(0)
    const id = setInterval(() => setStage((s) => Math.min(s + 1, LOADING_STAGES.length - 1)), 900)
    return () => clearInterval(id)
  }, [loading])

  async function run() {
    setLoading(true)
    setError(null)
    try {
      const r = await runSwarm()
      setResult(r)
      setLatest(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Health check failed')
    } finally {
      setLoading(false)
    }
  }

  function viewLatest() {
    setError(null)
    if (latest) setResult(latest)
  }

  const active = result
  const total = active?.total_apps_scanned ?? 0

  return (
    <div className="space-y-5">
      {/* 1. What this check looks for */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {CHECK_CARDS.map((c) => (
          <div key={c.title} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-2xl">{c.icon}</div>
            <div className="mt-1.5 text-sm font-semibold text-slate-900">{c.title}</div>
            <p className="mt-0.5 text-xs leading-snug text-slate-500">{c.text}</p>
          </div>
        ))}
      </div>

      {/* 2. Run button + last run */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        {latest ? (
          <>
            <span className="text-sm text-slate-600">
              Last checked: <span className="font-medium text-slate-800">{fmtDate(latest.created_at)}</span> ·{' '}
              {latest.insights.length} finding{latest.insights.length === 1 ? '' : 's'}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button onClick={viewLatest} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white">
                View last results
              </button>
              <button onClick={run} disabled={loading} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
                {loading ? 'Scanning…' : '🔍 Run new health check'}
              </button>
            </div>
          </>
        ) : (
          <button onClick={run} disabled={loading} className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
            {loading ? 'Scanning…' : '🔍 Run your first health check'}
          </button>
        )}
      </div>

      {/* 3. Loading */}
      {loading && (
        <div className="rounded-xl border border-brand/20 bg-brand-light/40 p-5">
          <div className="flex items-center gap-3 text-sm font-medium text-brand">
            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-brand" />
            {LOADING_STAGES[stage]}
          </div>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white">
            <div
              className="h-full rounded-full bg-brand transition-all duration-700"
              style={{ width: `${((stage + 1) / LOADING_STAGES.length) * 100}%` }}
            />
          </div>
        </div>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* 4. Results grouped by urgency */}
      {active && !loading && (
        <div ref={resultsRef} className="space-y-5">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Health Check Results</h3>
            <p className="text-sm text-slate-500">
              {n(total)} loans scanned · {active.insights.length} finding{active.insights.length === 1 ? '' : 's'}
            </p>
          </div>

          {GROUPS.map((g) => {
            const items = active.insights.filter((i) => g.keys.includes(i.severity))
            if (!items.length) return null
            const collapsed = g.collapsed && !showInfo
            return (
              <div key={g.heading} className="space-y-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-bold text-slate-800">{g.heading}</span>
                  <span className="text-xs text-slate-500">— {g.sub}</span>
                  <span className="text-xs text-slate-400">({items.length})</span>
                </div>
                {g.collapsed && collapsed ? (
                  <button onClick={() => setShowInfo(true)} className="text-sm font-medium text-brand hover:underline">
                    Show {items.length} more finding{items.length === 1 ? '' : 's'} ▼
                  </button>
                ) : (
                  <div className="space-y-2">
                    {items.map((ins, i) => (
                      <FindingCard key={`${ins.insight_type}-${i}`} ins={ins} index={i + 1} border={g.border} total={total} />
                    ))}
                    {g.collapsed && (
                      <button onClick={() => setShowInfo(false)} className="text-sm font-medium text-brand hover:underline">
                        Hide informational findings ▲
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {/* 5. Agent summaries */}
          {Object.keys(active.agent_summaries).length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <button onClick={() => setShowSummaries((v) => !v)} className="text-sm font-semibold text-brand hover:underline">
                {showSummaries ? '▲ Hide what each AI agent found' : '▼ What each AI agent found'}
              </button>
              {showSummaries && (
                <dl className="mt-4 divide-y divide-slate-100">
                  {Object.entries(active.agent_summaries).map(([agent, summary]) => (
                    <div key={agent} className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[180px_1fr] sm:gap-4">
                      <dt className="text-sm font-semibold text-slate-800">{agentName(agent)}</dt>
                      <dd className="text-sm leading-relaxed text-slate-600">{summary}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
