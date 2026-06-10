// Policy Simulator — runs a what-if scenario across the whole book and explains
// the impact in plain English: a one-line summary, impact cards, a status-change
// table, per-loan WHY / WHAT-TO-DO, and a should-you-do-this recommendation.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { fetchPipeline, runSimulation, runSimulationCustom } from '../api/client'
import type { SimulationFlip, SimulationResult } from '../types/accord'

type SimType = 'policy' | 'stress' | 'regulatory'
interface SimOpt { label: string; newName: string; override: Record<string, unknown> }
interface SimCard {
  id: string
  title: string
  type: SimType
  current?: string
  subtitle?: string
  options: SimOpt[]
  custom: { range: [number, number]; step: number; unit: string; build: (v: number) => { override: Record<string, unknown>; newName: string } }
  combined?: { rateRange: [number, number]; priceRange: [number, number]; build: (rateBps: number, pricePct: number) => { override: Record<string, unknown>; newName: string } }
}

const CATEGORIES: Array<{ type: SimType; title: string; sub: string }> = [
  { type: 'policy', title: 'POLICY CHANGES', sub: 'What if we tighten or loosen our rules?' },
  { type: 'stress', title: 'STRESS TESTS', sub: 'What if the market changes?' },
  { type: 'regulatory', title: 'REGULATORY CHANGES', sub: 'What if the rules change?' },
]

const opt = (label: string, newName: string, override: Record<string, unknown>): SimOpt => ({ label, newName, override })

// 12 dropdown cards. Each option (and the Custom builder) produces an API
// override object + a short name fragment for the scenario label.
const CARDS: SimCard[] = [
  // ── POLICY ──
  {
    id: 'dti', title: 'Debt-to-Income Limit', type: 'policy', current: '43%',
    options: [
      opt('36% (Fannie preferred)', '36%', { dti_calculation: { back_dti_max: 36 } }),
      opt('38% (Moderate)', '38%', { dti_calculation: { back_dti_max: 38 } }),
      opt('40% (Slight)', '40%', { dti_calculation: { back_dti_max: 40 } }),
      opt('50% (FHA expanded)', '50%', { dti_calculation: { back_dti_max: 50 } }),
    ],
    custom: { range: [20, 60], step: 1, unit: '%', build: (v) => ({ override: { dti_calculation: { back_dti_max: v } }, newName: `${v}%` }) },
  },
  {
    id: 'credit', title: 'Minimum Credit Score', type: 'policy', current: '620',
    options: [
      opt('640 (Slight)', '640', { credit_assessment: { min_score: 640 } }),
      opt('660 (Moderate)', '660', { credit_assessment: { min_score: 660 } }),
      opt('680 (Prime only)', '680', { credit_assessment: { min_score: 680 } }),
      opt('700 (Super-prime)', '700', { credit_assessment: { min_score: 700 } }),
    ],
    custom: { range: [500, 800], step: 1, unit: '', build: (v) => ({ override: { credit_assessment: { min_score: v } }, newName: `${v}` }) },
  },
  {
    id: 'ltv', title: 'Max Loan-to-Value', type: 'policy', current: '97%',
    options: [
      opt('90% (10% down)', '90%', { ltv_assessment: { max_ltv: 90 } }),
      opt('92% (8% down)', '92%', { ltv_assessment: { max_ltv: 92 } }),
      opt('95% (5% down)', '95%', { ltv_assessment: { max_ltv: 95 } }),
      opt('100% (Zero down)', '100%', { ltv_assessment: { max_ltv: 100 } }),
    ],
    custom: { range: [50, 100], step: 1, unit: '%', build: (v) => ({ override: { ltv_assessment: { max_ltv: v } }, newName: `${v}%` }) },
  },
  {
    id: 'dcr', title: 'Debt Coverage Ratio', type: 'policy', current: '1.0x',
    options: [
      opt('1.10x (Slight buffer)', '1.10x', { dti_calculation: { min_dcr: 1.1 } }),
      opt('1.20x (Standard)', '1.20x', { dti_calculation: { min_dcr: 1.2 } }),
      opt('1.25x (Conservative)', '1.25x', { dti_calculation: { min_dcr: 1.25 } }),
      opt('1.50x (Aggressive)', '1.50x', { dti_calculation: { min_dcr: 1.5 } }),
    ],
    custom: { range: [1, 2], step: 0.05, unit: 'x', build: (v) => ({ override: { dti_calculation: { min_dcr: v } }, newName: `${v.toFixed(2)}x` }) },
  },
  // ── STRESS ──
  {
    id: 'rate', title: 'Interest Rate Increase', type: 'stress', subtitle: 'What if rates rise?',
    options: [
      opt('+50bps (Mild +0.50%)', '+50bps', { _stress: { rate_delta: 0.5 } }),
      opt('+100bps (Moderate +1%)', '+100bps', { _stress: { rate_delta: 1 } }),
      opt('+200bps (Significant +2%)', '+200bps', { _stress: { rate_delta: 2 } }),
      opt('+300bps (Severe +3%)', '+300bps', { _stress: { rate_delta: 3 } }),
    ],
    custom: { range: [25, 500], step: 5, unit: 'bps', build: (v) => ({ override: { _stress: { rate_delta: v / 100 } }, newName: `+${v}bps` }) },
  },
  {
    id: 'price', title: 'Home Price Decline', type: 'stress', subtitle: 'What if values drop?',
    options: [
      opt('-5% (Mild)', '-5%', { _stress: { price_delta_pct: -5 } }),
      opt('-10% (Moderate)', '-10%', { _stress: { price_delta_pct: -10 } }),
      opt('-15% (Significant)', '-15%', { _stress: { price_delta_pct: -15 } }),
      opt('-20% (Severe, 2008 level)', '-20%', { _stress: { price_delta_pct: -20 } }),
    ],
    custom: { range: [-40, -1], step: 1, unit: '%', build: (v) => ({ override: { _stress: { price_delta_pct: v } }, newName: `${v}%` }) },
  },
  {
    id: 'unemp', title: 'Unemployment Spike', type: 'stress', subtitle: 'What if jobs are lost?',
    options: [
      opt('5% (Mild, current +1%)', '5%', { _stress: { unemployment_rate: 5 } }),
      opt('6% (Moderate +2%)', '6%', { _stress: { unemployment_rate: 6 } }),
      opt('8% (Recession)', '8%', { _stress: { unemployment_rate: 8 } }),
      opt('10% (Severe recession)', '10%', { _stress: { unemployment_rate: 10 } }),
    ],
    custom: { range: [4, 15], step: 1, unit: '%', build: (v) => ({ override: { _stress: { unemployment_rate: v } }, newName: `${v}%` }) },
  },
  {
    id: 'combined', title: 'Combined Stress', type: 'stress', subtitle: 'Rate shock + price drop together',
    options: [
      opt('Mild: +50bps, -5% price', '+50bps / -5%', { _stress: { rate_delta: 0.5, price_delta_pct: -5 } }),
      opt('Moderate: +100bps, -10% price', '+100bps / -10%', { _stress: { rate_delta: 1, price_delta_pct: -10 } }),
      opt('Severe: +200bps, -15% price', '+200bps / -15%', { _stress: { rate_delta: 2, price_delta_pct: -15 } }),
      opt('Crisis: +300bps, -20% price', '+300bps / -20%', { _stress: { rate_delta: 3, price_delta_pct: -20 } }),
    ],
    custom: { range: [25, 500], step: 5, unit: 'bps', build: (v) => ({ override: { _stress: { rate_delta: v / 100 } }, newName: `+${v}bps` }) },
    combined: { rateRange: [25, 500], priceRange: [-40, -1], build: (r, p) => ({ override: { _stress: { rate_delta: r / 100, price_delta_pct: p } }, newName: `+${r}bps / ${p}%` }) },
  },
  // ── REGULATORY ──
  {
    id: 'conf', title: 'Conforming Loan Limit', type: 'regulatory', current: '$766,550',
    options: [
      opt('$700K (FHFA lowers)', '$700K', { product_eligibility: { conforming_limit: 700000 } }),
      opt('$750K (Slight decrease)', '$750K', { product_eligibility: { conforming_limit: 750000 } }),
      opt('$800K (FHFA raises)', '$800K', { product_eligibility: { conforming_limit: 800000 } }),
      opt('$850K (Significant raise)', '$850K', { product_eligibility: { conforming_limit: 850000 } }),
    ],
    custom: { range: [500000, 1000000], step: 1000, unit: '$', build: (v) => ({ override: { product_eligibility: { conforming_limit: v } }, newName: `$${Math.round(v / 1000)}K` }) },
  },
  {
    id: 'fha_score', title: 'FHA Minimum Credit Score', type: 'regulatory', current: '580',
    options: [
      opt('600 (Slight)', '600', { fha_eligibility: { min_score: 600 } }),
      opt('620 (Moderate)', '620', { fha_eligibility: { min_score: 620 } }),
      opt('640 (Significant)', '640', { fha_eligibility: { min_score: 640 } }),
      opt('660 (Very restrictive)', '660', { fha_eligibility: { min_score: 660 } }),
    ],
    custom: { range: [500, 700], step: 1, unit: '', build: (v) => ({ override: { fha_eligibility: { min_score: v } }, newName: `${v}` }) },
  },
  {
    id: 'fha_mip', title: 'FHA Annual MIP Rate', type: 'regulatory', current: '0.85%',
    options: [
      opt('0.55% (Reduced)', '0.55%', { fha_eligibility: { annual_mip: 0.55 } }),
      opt('0.85% (Current)', '0.85%', { fha_eligibility: { annual_mip: 0.85 } }),
      opt('1.00% (Slight increase)', '1.00%', { fha_eligibility: { annual_mip: 1 } }),
      opt('1.35% (Pre-2015)', '1.35%', { fha_eligibility: { annual_mip: 1.35 } }),
    ],
    custom: { range: [0.3, 2], step: 0.05, unit: '%', build: (v) => ({ override: { fha_eligibility: { annual_mip: v } }, newName: `${v.toFixed(2)}%` }) },
  },
  {
    id: 'usury', title: 'State Interest Rate Cap', type: 'regulatory', subtitle: 'Apply across portfolio',
    options: [
      opt('7% (Strict)', '7%', { rate_pricing: { usury_cap: 7 } }),
      opt('8% (Moderate)', '8%', { rate_pricing: { usury_cap: 8 } }),
      opt('10% (Loose)', '10%', { rate_pricing: { usury_cap: 10 } }),
      opt('12% (Very loose)', '12%', { rate_pricing: { usury_cap: 12 } }),
    ],
    custom: { range: [5, 20], step: 0.5, unit: '%', build: (v) => ({ override: { rate_pricing: { usury_cap: v } }, newName: `${v}%` }) },
  },
]

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
    if (L.startsWith('dti') || L.includes('debt-to-income')) return `${nb < na ? 'tighten' : 'loosen'} the debt-to-income limit from ${a} to ${b}`
    if (L.includes('credit score')) return `${nb > na ? 'raise' : 'lower'} the ${L.startsWith('fha') ? 'FHA ' : ''}minimum credit score from ${a} to ${b}`
    if (L.startsWith('ltv') || L.includes('loan-to-value')) return `${nb < na ? 'tighten' : 'loosen'} the LTV cap from ${a} to ${b}`
    if (L.includes('conforming')) return `${nb > na ? 'raise' : 'lower'} the conforming loan limit from ${a} to ${b}`
    return `change the ${L} from ${a} to ${b}`
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
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [runningName, setRunningName] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [portfolioTotal, setPortfolioTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchPipeline({ limit: 1 }).then((r) => setPortfolioTotal(r.kpis.total)).catch(() => undefined)
  }, [])

  // Ramp a progress bar while a scenario is evaluating.
  useEffect(() => {
    if (!runningName) return
    setProgress(8)
    const id = setInterval(() => setProgress((p) => Math.min(p + Math.random() * 18, 95)), 350)
    return () => clearInterval(id)
  }, [runningName])

  async function launch(name: string, promise: Promise<SimulationResult>) {
    setRunningName(name)
    setError(null)
    setResult(null)
    setShowAll(false)
    try {
      const r = await promise
      setProgress(100)
      setResult(r)
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setRunningName(null)
    }
  }
  const runCustom = (name: string, overrides: Record<string, unknown>, type: SimType) =>
    launch(name, runSimulationCustom(name, overrides, type))

  // Imperative handle (history "View") replays a prebuilt scenario by name.
  useImperativeHandle(ref, () => ({ run: (name: string) => launch(name, runSimulation(name)) }))

  return (
    <div className="space-y-5">
      {/* 1. Dropdown cards in 3 categories */}
      <div className="space-y-6">
        {CATEGORIES.map((cat) => (
          <div key={cat.type}>
            <div className="mb-2">
              <span className="text-sm font-bold text-slate-800">{cat.title}</span>
              <span className="text-sm text-slate-500"> — {cat.sub}</span>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {CARDS.filter((c) => c.type === cat.type).map((card) => (
                <CardView key={card.id} card={card} running={!!runningName} onRun={runCustom} />
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

// One dropdown card: 4 smart options + Custom text entry, with a Run button.
function CardView({ card, running, onRun }: {
  card: SimCard
  running: boolean
  onRun: (name: string, overrides: Record<string, unknown>, type: SimType) => void
}) {
  const [sel, setSel] = useState('0') // '0'..'3' | 'custom'
  const [cv, setCv] = useState('') // custom value (or rate bps for combined)
  const [cv2, setCv2] = useState('') // combined price %
  const isCustom = sel === 'custom'

  const sv = Number(cv)
  const pv = Number(cv2)
  const inRange = (n: number, [lo, hi]: [number, number]) => !Number.isNaN(n) && n >= lo && n <= hi
  const singleValid = cv !== '' && inRange(sv, card.custom.range)
  const combinedValid = !!card.combined && cv !== '' && cv2 !== '' && inRange(sv, card.combined.rateRange) && inRange(pv, card.combined.priceRange)
  const customValid = card.combined ? combinedValid : singleValid
  const disabled = running || (isCustom && !customValid)

  function handleRun() {
    const built = isCustom
      ? card.combined
        ? card.combined.build(sv, pv)
        : card.custom.build(sv)
      : { override: card.options[Number(sel)].override, newName: card.options[Number(sel)].newName }
    const name = card.current ? `${card.title}: ${card.current} → ${built.newName}` : `${card.title}: ${built.newName}`
    onRun(name, built.override, card.type)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="font-semibold text-slate-900">{card.title}</div>
      <div className="text-xs text-slate-500">{card.current ? `Current: ${card.current}` : card.subtitle}</div>

      <div className="mt-3 flex items-center gap-2">
        <select
          value={sel}
          onChange={(e) => setSel(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-sm text-gray-700 outline-none focus:border-brand"
        >
          {card.options.map((o, i) => (
            <option key={i} value={String(i)}>{o.label}</option>
          ))}
          <option value="custom">Custom…</option>
        </select>
        <button
          onClick={handleRun}
          disabled={disabled}
          className="shrink-0 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          Run →
        </button>
      </div>

      {isCustom && !card.combined && (
        <div className="mt-2">
          <input
            type="number"
            value={cv}
            step={card.custom.step}
            onChange={(e) => setCv(e.target.value)}
            placeholder={`${card.custom.range[0]}–${card.custom.range[1]}${card.custom.unit ? ' ' + card.custom.unit : ''}`}
            className={`w-full rounded-lg border px-2.5 py-1.5 text-sm outline-none focus:border-brand ${cv && !singleValid ? 'border-red-300' : 'border-gray-200'}`}
          />
          {cv && !singleValid && (
            <p className="mt-1 text-xs text-red-600">Enter {card.custom.range[0]}–{card.custom.range[1]} {card.custom.unit}</p>
          )}
        </div>
      )}

      {isCustom && card.combined && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <input
            type="number"
            value={cv}
            onChange={(e) => setCv(e.target.value)}
            placeholder={`Rate ${card.combined.rateRange[0]}–${card.combined.rateRange[1]} bps`}
            className={`rounded-lg border px-2.5 py-1.5 text-sm outline-none focus:border-brand ${cv && !inRange(sv, card.combined.rateRange) ? 'border-red-300' : 'border-gray-200'}`}
          />
          <input
            type="number"
            value={cv2}
            onChange={(e) => setCv2(e.target.value)}
            placeholder={`Price ${card.combined.priceRange[0]}–${card.combined.priceRange[1]} %`}
            className={`rounded-lg border px-2.5 py-1.5 text-sm outline-none focus:border-brand ${cv2 && !inRange(pv, card.combined.priceRange) ? 'border-red-300' : 'border-gray-200'}`}
          />
        </div>
      )}
    </div>
  )
}

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
