import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchLoan, fetchPipeline } from '../api/client'
import type {
  DecisionDetail,
  LoanDetail,
  PipelineKPIs,
  PipelineResponse,
  PipelineRow,
} from '../types/accord'
import MirofishDebate from '../components/MirofishDebate'
import LoanSearch from '../components/LoanSearch'
import StatusFilter from '../components/StatusFilter'
import PeriodFilter, { type Period } from '../components/PeriodFilter'

// ── 5 lifecycle stages grouping the 12 personas ──────────────────────
const STAGES: Array<{ key: string; label: string; wave: number; personas: string[] }> = [
  { key: 'pre_uw', label: 'PRE-UNDERWRITING', wave: 1, personas: ['credit_assessment', 'fraud_screening', 'compliance_check', 'employment_reconciliation'] },
  { key: 'uw', label: 'UNDERWRITING', wave: 2, personas: ['income_verification', 'ltv_assessment', 'dti_calculation'] },
  { key: 'product', label: 'PRODUCT', wave: 3, personas: ['product_eligibility', 'rate_pricing'] },
  { key: 'decision', label: 'DECISION', wave: 4, personas: ['underwriting_decision'] },
  { key: 'closing', label: 'CLOSING', wave: 5, personas: ['approval_routing', 'closing_readiness'] },
]

const PERSONA_NAME: Record<string, string> = {
  credit_assessment: 'Credit Underwriter', fraud_screening: 'Fraud Analyst',
  compliance_check: 'Compliance Officer', employment_reconciliation: 'Employment Specialist',
  income_verification: 'Income Underwriter', ltv_assessment: 'Collateral Analyst',
  dti_calculation: 'DTI Calculator', product_eligibility: 'Product Specialist',
  rate_pricing: 'Pricing Analyst', underwriting_decision: 'Senior Underwriter',
  approval_routing: 'Loan Ops Router', closing_readiness: 'Closer',
}

// Stage summary state → icon + pill colour. `pill` is shared by BOTH the grid
// cells and the legend so they always match.
type StageState = 'passed' | 'blocked' | 'flagged' | 'review' | 'pending' | 'skipped'
const STAGE_ICON: Record<StageState, { icon: string; pill: string; label: string }> = {
  passed: { icon: '✓', pill: 'bg-green-100 text-green-800', label: 'Passed' },
  blocked: { icon: '✕', pill: 'bg-red-100 text-red-800', label: 'Blocked' },
  flagged: { icon: '⚠', pill: 'bg-red-100 text-red-800', label: 'Flagged' },
  review: { icon: '◆', pill: 'bg-amber-100 text-amber-800', label: 'Review' },
  pending: { icon: '·', pill: 'bg-gray-100 text-gray-400', label: 'Pending' },
  skipped: { icon: '—', pill: 'bg-gray-100 text-gray-300', label: 'Skipped' },
}

// Legend key shown above the grid (also documents Escalated, used in the
// per-decision expansion). Same colours as the grid cells.
const LEGEND: Array<{ icon: string; label: string; pill: string }> = [
  { icon: '✓', label: 'Passed', pill: 'bg-green-100 text-green-800' },
  { icon: '✕', label: 'Blocked', pill: 'bg-red-100 text-red-800' },
  { icon: '◆', label: 'Review', pill: 'bg-amber-100 text-amber-800' },
  { icon: '▲', label: 'Escalated', pill: 'bg-orange-100 text-orange-800' },
  { icon: '·', label: 'Pending', pill: 'bg-gray-100 text-gray-400' },
  { icon: '—', label: 'Skipped', pill: 'bg-gray-100 text-gray-300' },
]

// Per-decision icon (used in the expansion).
const OUTCOME_ICON: Record<string, { icon: string; cls: string; label: string }> = {
  allow: { icon: '✓', cls: 'text-green-600', label: 'Passed' },
  recommend: { icon: '◆', cls: 'text-amber-600', label: 'Review' },
  escalate: { icon: '▲', cls: 'text-orange-600', label: 'Escalated' },
  block: { icon: '✕', cls: 'text-red-600', label: 'Blocked' },
}
const SIGNAL_ICON: Record<string, { icon: string; cls: string }> = {
  pass: { icon: '✓', cls: 'text-green-600' },
  fail: { icon: '✕', cls: 'text-red-600' },
  warn: { icon: '◆', cls: 'text-amber-600' },
  no_data: { icon: '·', cls: 'text-gray-400' },
  info: { icon: '·', cls: 'text-gray-400' },
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  halted: { label: 'Halted', cls: 'bg-red-700 text-white' },
  blocked: { label: 'Blocked', cls: 'bg-red-100 text-red-800' },
  in_review: { label: 'In Review', cls: 'bg-amber-100 text-amber-800' },
  clear_to_close: { label: 'Clear to Close', cls: 'bg-green-100 text-green-800' },
  in_progress: { label: 'In Progress', cls: 'bg-slate-100 text-slate-600' },
}
const STATUS_SORT: Record<string, number> = {
  halted: 0, blocked: 1, in_review: 2, in_progress: 3, clear_to_close: 4,
}

const CARDS: Array<{ key: string; label: string; statuses: string[]; count: (k: PipelineKPIs) => number; accent: string }> = [
  { key: 'all', label: 'Total', statuses: [], count: (k) => k.total, accent: 'text-slate-900' },
  { key: 'clear_to_close', label: 'Clear to Close', statuses: ['clear_to_close'], count: (k) => k.clear_to_close, accent: 'text-green-600' },
  { key: 'in_review', label: 'In Review', statuses: ['in_review'], count: (k) => k.in_review, accent: 'text-amber-600' },
  { key: 'blocked', label: 'Blocked / Halted', statuses: ['blocked', 'halted'], count: (k) => k.blocked + k.halted, accent: 'text-rose-600' },
]
// Built from the distinct loan_type values that actually exist in the data
// (conforming / government / jumbo / non_qm) so every option filters real rows.
const LOAN_TYPES: Array<{ value: string; label: string }> = [
  { value: '', label: 'All Loan Types' },
  { value: 'conforming', label: 'Conforming' },
  { value: 'government', label: 'Government (FHA/VA)' },
  { value: 'jumbo', label: 'Jumbo' },
  { value: 'non_qm', label: 'Non-QM' },
]

function money(v: number | null) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}

// Stage summary from a row's decision map.
function stageState(personas: string[], wave: number, decisions: PipelineRow['decisions'], halted: boolean): StageState {
  if (halted && wave > 1) return 'skipped'
  if (personas.includes('fraud_screening') && decisions['fraud_screening']?.outcome === 'block') return 'flagged'
  const present = personas.map((p) => decisions[p]).filter(Boolean)
  const outcomes = present.map((d) => d!.outcome)
  if (outcomes.includes('block')) return 'blocked'
  if (outcomes.some((o) => o === 'escalate' || o === 'recommend')) return 'review'
  if (present.length === personas.length && outcomes.every((o) => o === 'allow')) return 'passed'
  if (present.length === 0) return 'pending'
  return 'pending'
}

async function loadPipeline(statuses: string[], type: string, search: string, period: Period): Promise<PipelineResponse> {
  const common = { type, search, limit: 200, period: period === 'all' ? undefined : period }
  if (statuses.length <= 1) return fetchPipeline({ ...common, status: statuses[0] })
  const parts = await Promise.all(statuses.map((s) => fetchPipeline({ ...common, status: s })))
  return {
    kpis: parts[0].kpis,
    total: parts.reduce((a, p) => a + p.total, 0),
    applications: parts.flatMap((p) => p.applications).slice(0, 200),
  }
}

export default function Pipeline() {
  const navigate = useNavigate()
  const [data, setData] = useState<PipelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const [period, setPeriod] = useState<Period>('all')
  // statuses = actual query filter; statusSel = the dropdown's single selection
  // (also drives KPI-card highlight, keeping cards and dropdown in sync).
  const [statuses, setStatuses] = useState<string[]>([])
  const [statusSel, setStatusSel] = useState('')
  const [expanded, setExpanded] = useState<{ appId: string; stage: string } | null>(null)
  const [loanCache, setLoanCache] = useState<Record<string, LoanDetail>>({})
  const [loanLoading, setLoanLoading] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const t = setTimeout(async () => {
      setLoading(true)
      setError(null)
      setExpanded(null)
      try {
        const res = await loadPipeline(statuses, type, search, period)
        if (alive) setData(res)
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : 'Failed to load pipeline')
      } finally {
        if (alive) setLoading(false)
      }
    }, 250)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [search, type, period, statuses])

  // Clicking a KPI card sets the status filter (and syncs the dropdown).
  function pickCard(card: (typeof CARDS)[number]) {
    const isActive = cardActive(card.key)
    setStatuses(isActive && card.key !== 'all' ? [] : card.statuses)
    setStatusSel(isActive && card.key !== 'all' ? '' : card.key === 'all' ? '' : card.key)
  }
  // Dropdown selection sets a single granular status (and syncs the card).
  function pickStatus(val: string) {
    setStatusSel(val)
    setStatuses(val ? [val] : [])
  }
  // A card is "active" when its key matches the current selection
  // (the Blocked card also lights up for the granular "Halted").
  function cardActive(key: string): boolean {
    if (key === 'all') return statusSel === ''
    if (key === 'blocked') return statusSel === 'blocked' || statusSel === 'halted'
    return statusSel === key
  }

  function resetFilters() {
    setSearch('')
    setType('')
    setPeriod('all')
    setStatuses([])
    setStatusSel('')
  }

  function toggleStage(appId: string, stageKey: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (expanded?.appId === appId && expanded?.stage === stageKey) {
      setExpanded(null)
      return
    }
    setExpanded({ appId, stage: stageKey })
    if (!loanCache[appId]) {
      setLoanLoading(appId)
      fetchLoan(appId)
        .then((d) => setLoanCache((c) => ({ ...c, [appId]: d })))
        .catch(() => undefined)
        .finally(() => setLoanLoading(null))
    }
  }

  const rows = [...(data?.applications ?? [])].sort(
    (a, b) => (STATUS_SORT[a.status] ?? 9) - (STATUS_SORT[b.status] ?? 9),
  )
  const kpis = data?.kpis
  const COLS = 4 + STAGES.length

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-5 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">All Applications</h1>
          <p className="text-sm text-slate-500">
            {data ? `${data.total.toLocaleString()} loans across 5 lifecycle stages` : ' '}
          </p>
        </div>
        <span className="text-sm text-slate-500">
          {data ? `${rows.length} of ${data.total.toLocaleString()} applications` : ' '}
        </span>
      </div>

      {/* KPI filter cards */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {CARDS.map((c) => {
          const active = cardActive(c.key)
          return (
            <button
              key={c.key}
              onClick={() => pickCard(c)}
              className={`rounded-xl border bg-white p-4 text-left transition hover:shadow-sm ${
                active ? 'border-brand ring-1 ring-brand/30' : 'border-slate-200'
              }`}
            >
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{c.label}</div>
              <div className={`mt-1 text-3xl font-semibold ${c.accent}`}>
                {kpis ? c.count(kpis).toLocaleString() : '—'}
              </div>
            </button>
          )
        })}
      </div>

      {/* Filters: search (≈40%) + loan type + status + date range, one row */}
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <LoanSearch value={search} onSubmit={setSearch} className="min-w-[260px] flex-[2]" />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="min-w-[150px] flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand"
        >
          {LOAN_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <StatusFilter value={statusSel} onChange={pickStatus} className="min-w-[150px] flex-1" />
        <PeriodFilter value={period} onChange={setPeriod} className="min-w-[140px] flex-1" />
      </div>
      <div className="mb-4 h-5">
        {(search || type || statusSel || period !== 'all') && (
          <button onClick={resetFilters} className="text-sm font-medium text-brand hover:underline">
            Reset filters
          </button>
        )}
      </div>

      {/* Grid — 9 columns, no horizontal scroll */}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="min-w-full table-fixed text-sm">
          <colgroup>
            <col style={{ width: '20%' }} />
            <col style={{ width: '10%' }} />
            <col style={{ width: '12%' }} />
            <col style={{ width: '14%' }} />
            {STAGES.map((s) => (
              <col key={s.key} style={{ width: `${44 / STAGES.length}%` }} />
            ))}
          </colgroup>
          <thead>
            <tr className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3 text-left">Borrower</th>
              <th className="px-4 py-3 text-left">Loan</th>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-left">Status</th>
              {STAGES.map((s) => (
                <th key={s.key} className="px-2 py-3 text-center">{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {/* Legend row — colored word chips matching the grid cells */}
            <tr>
              <td colSpan={COLS} className="bg-gray-50 px-4 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  {LEGEND.map((l) => (
                    <span key={l.label} className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${l.pill}`}>
                      {l.label}
                    </span>
                  ))}
                </div>
              </td>
            </tr>

            {loading && (
              <tr><td colSpan={COLS} className="px-4 py-12 text-center text-slate-400">Loading pipeline…</td></tr>
            )}
            {error && !loading && (
              <tr><td colSpan={COLS} className="px-4 py-12 text-center text-rose-600">{error}</td></tr>
            )}
            {!loading && !error && rows.length === 0 && (
              <tr><td colSpan={COLS} className="px-4 py-12 text-center text-slate-400">No applications match these filters.</td></tr>
            )}

            {!loading && !error && rows.map((r) => {
              const badge = STATUS_BADGE[r.status] ?? STATUS_BADGE.in_progress
              const halted = r.status === 'halted' || r.decisions['fraud_screening']?.outcome === 'block'
              const isExpandedRow = expanded?.appId === r.application_id
              return (
                <Fragment key={r.application_id}>
                  <tr
                    onClick={() => navigate(`/pipeline/${r.application_id}`)}
                    className="cursor-pointer hover:bg-brand-light/40"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-slate-800">{r.borrower_name}</div>
                      <div className="font-mono text-xs text-slate-400">{r.application_id}</div>
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">{money(r.loan_amount)}</td>
                    <td className="px-4 py-2.5 capitalize text-slate-500">{r.loan_type ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${badge.cls}`}>
                        {badge.label}
                      </span>
                    </td>
                    {STAGES.map((s) => {
                      const st = stageState(s.personas, s.wave, r.decisions, halted)
                      const meta = STAGE_ICON[st]
                      const open = isExpandedRow && expanded?.stage === s.key
                      return (
                        <td key={s.key} className="px-2 py-2.5 text-center">
                          <button
                            onClick={(e) => toggleStage(r.application_id, s.key, e)}
                            title={`${s.label}: ${meta.label} — click for detail`}
                            className={`mx-auto inline-flex items-center justify-center rounded-md px-2 py-1 text-[11px] font-semibold leading-tight transition hover:brightness-95 ${meta.pill} ${
                              open ? 'ring-2 ring-slate-400' : ''
                            }`}
                          >
                            {meta.label}
                          </button>
                        </td>
                      )
                    })}
                  </tr>

                  {isExpandedRow && (
                    <tr>
                      <td colSpan={COLS} className="bg-slate-50 px-4 py-4">
                        <StageExpansion
                          stageKey={expanded!.stage}
                          loan={loanCache[r.application_id]}
                          loading={loanLoading === r.application_id || !loanCache[r.application_id]}
                          onViewLoan={() => navigate(`/pipeline/${r.application_id}`)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Expanded stage detail ────────────────────────────────────────────
function StageExpansion({
  stageKey,
  loan,
  loading,
  onViewLoan,
}: {
  stageKey: string
  loan: LoanDetail | undefined
  loading: boolean
  onViewLoan: () => void
}) {
  const stage = STAGES.find((s) => s.key === stageKey)!
  if (loading || !loan) {
    return <div className="text-sm text-slate-400">Loading {stage.label.toLowerCase()} decisions…</div>
  }
  const decisions = loan.decisions.filter((d) => stage.personas.includes(d.decision_id))
  const counts: Record<string, number> = {}
  decisions.forEach((d) => { counts[d.outcome] = (counts[d.outcome] || 0) + 1 })
  const summary = Object.entries(counts)
    .filter(([o]) => o !== 'allow')
    .map(([o, n]) => `${n} ${o}`)
    .join(', ')

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700">
        {stage.label} (Wave {stage.wave}){summary ? ` — ${summary}` : ' — all clear'}
      </div>
      <div className="divide-y divide-slate-100">
        {decisions.map((d) => (
          <DecisionBlock key={d.decision_id} d={d} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-4 py-3">
        <button onClick={onViewLoan} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-brand hover:bg-slate-50">
          View full loan detail →
        </button>
        <div className="min-w-[280px] flex-1">
          <MirofishDebate appId={loan.application_id} />
        </div>
      </div>
    </div>
  )
}

function DecisionBlock({ d }: { d: DecisionDetail }) {
  const m = OUTCOME_ICON[d.outcome] ?? { icon: '·', cls: 'text-gray-400', label: d.outcome }
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2">
        <span className={`text-base font-bold ${m.cls}`}>{m.icon}</span>
        <span className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {PERSONA_NAME[d.decision_id] ?? d.persona_name}
        </span>
        <span className={`text-sm font-medium ${m.cls}`}>— {m.label}</span>
      </div>
      <p className="mt-1.5 pl-6 text-sm leading-relaxed text-slate-600">{d.explanation}</p>

      {d.signals.length > 0 && (
        <div className="mt-2 pl-6">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-400">Signals</div>
          <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {d.signals.map((s, i) => {
              const si = SIGNAL_ICON[s.status] ?? SIGNAL_ICON.info
              return (
                <div key={i} className="flex items-center gap-1.5 text-sm">
                  <span className={si.cls}>{si.icon}</span>
                  <span className="text-slate-600">{s.key}:</span>
                  <span className="font-medium text-slate-900">{s.value}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {d.rule && (
        <div className="mt-2 pl-6 font-mono text-xs text-slate-500">Rule: {d.rule}</div>
      )}
      <div className="mt-1 pl-6 text-xs text-slate-400">
        Confidence: {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'}
        {d.reviewer ? ` · ${d.reviewer}` : ' · System'}
        {d.reviewed_at ? ` · ${new Date(d.reviewed_at).toLocaleString()}` : ''}
      </div>
    </div>
  )
}
