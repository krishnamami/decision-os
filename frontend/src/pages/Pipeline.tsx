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
import ExportMenu from '../components/ExportMenu'
import Pagination from '../components/Pagination'
import { ErrorState, EmptyState, SkeletonRows, CardSkeleton } from '../components/states'
import { downloadCsv, downloadJson, printPdf } from '../utils/export'
import { useAuth } from '../context/AuthContext'
import MyQueue from './MyQueue'
import TeamOverview from './TeamOverview'

// ── 5 lifecycle stages grouping the 12 personas ──────────────────────
const STAGES: Array<{ key: string; label: string; tip: string; wave: number; personas: string[] }> = [
  { key: 'pre_uw', label: 'VERIFY', tip: 'Credit, fraud, compliance & employment checks', wave: 1, personas: ['credit_assessment', 'fraud_screening', 'compliance_check', 'employment_reconciliation'] },
  { key: 'uw', label: 'UNDERWRITE', tip: 'Income verification, property value & debt analysis', wave: 2, personas: ['income_verification', 'ltv_assessment', 'dti_calculation'] },
  { key: 'product', label: 'ELIGIBILITY', tip: 'Loan program & pricing eligibility', wave: 3, personas: ['product_eligibility', 'rate_pricing'] },
  { key: 'decision', label: 'DECIDE', tip: 'Senior underwriter final review', wave: 4, personas: ['underwriting_decision'] },
  { key: 'closing', label: 'CLOSE', tip: 'Routing & closing readiness', wave: 5, personas: ['approval_routing', 'closing_readiness'] },
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

// Single-status cards (key === the status filter value) so the view is always
// one status → clean server-side pagination.
const CARDS: Array<{ key: string; label: string; count: (k: PipelineKPIs) => number; accent: string }> = [
  { key: 'all', label: 'Total', count: (k) => k.total, accent: 'text-slate-900' },
  { key: 'clear_to_close', label: 'Clear to Close', count: (k) => k.clear_to_close, accent: 'text-green-600' },
  { key: 'blocked', label: 'Blocked', count: (k) => k.blocked, accent: 'text-rose-600' },
  { key: 'halted', label: 'Halted', count: (k) => k.halted, accent: 'text-red-700' },
]
// Loan-type dropdown options are populated dynamically from the distinct
// loan_type values in the API response (see `loanTypes` state). These are the
// display labels for known codes; anything else is title-cased generically.
const LOAN_TYPE_LABEL: Record<string, string> = {
  conforming: 'Conforming', government: 'Government (FHA/VA)', jumbo: 'Jumbo',
  non_qm: 'Non-QM', fha: 'FHA', va: 'VA', usda: 'USDA', other: 'Other',
}
const prettyLoanType = (t: string) =>
  LOAN_TYPE_LABEL[t] ?? t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

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

function loadPipeline(
  status: string, type: string, search: string, period: Period, limit: number, offset: number,
): Promise<PipelineResponse> {
  return fetchPipeline({
    status: status || undefined,
    type,
    search,
    period: period === 'all' ? undefined : period,
    limit,
    offset,
  })
}

// ── Role-aware Pipeline shell: My Queue / Team Overview / All Applications ──
const OPS_ROLES = ['processor', 'underwriter', 'senior_uw', 'closer']

export default function Pipeline() {
  const { effectiveUser, viewAs } = useAuth()
  const role = effectiveUser?.role ?? 'viewer'
  const isManager = role === 'admin' || role === 'manager'
  const isOps = OPS_ROLES.includes(role)

  const tabs = isManager
    ? [{ key: 'team', label: 'Team Overview' }, { key: 'all', label: 'All Applications' }]
    : isOps
      ? [{ key: 'queue', label: 'My Queue' }, { key: 'all', label: 'All Applications' }]
      : [{ key: 'all', label: 'All Applications' }]

  const [tab, setTab] = useState(tabs[0].key)
  const [viewUser, setViewUser] = useState<{ id: string; name: string } | null>(null)
  // Reset to the default tab when the effective role changes (e.g. impersonation).
  useEffect(() => { setTab(tabs[0].key) }, [role]) // eslint-disable-line react-hooks/exhaustive-deps

  // Manager drilling into a teammate's queue (read-only).
  if (tab === 'team' && viewUser) {
    return (
      <>
        <SubTabs tabs={tabs} active={tab} onChange={(k) => { setViewUser(null); setTab(k) }} />
        <MyQueue userId={viewUser.id} readOnly onBack={() => setViewUser(null)} />
      </>
    )
  }

  return (
    <>
      {tabs.length > 1 && <SubTabs tabs={tabs} active={tab} onChange={setTab} />}
      {tab === 'queue' && <MyQueue userId={viewAs?.user_id} />}
      {tab === 'team' && <TeamOverview onViewUser={setViewUser} />}
      {tab === 'all' && <AllApplications />}
    </>
  )
}

function SubTabs({ tabs, active, onChange }: { tabs: Array<{ key: string; label: string }>; active: string; onChange: (k: string) => void }) {
  return (
    <div className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl gap-6 px-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={`-mb-px border-b-2 py-3 text-sm font-medium transition ${
              active === t.key ? 'border-brand text-brand' : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function AllApplications() {
  const navigate = useNavigate()
  const [data, setData] = useState<PipelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const [period, setPeriod] = useState<Period>('all')
  const [statusSel, setStatusSel] = useState('') // single status filter; '' = all
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [reloadKey, setReloadKey] = useState(0) // bump to retry after an error
  const [expanded, setExpanded] = useState<{ appId: string; stage: string } | null>(null)
  const [loanCache, setLoanCache] = useState<Record<string, LoanDetail>>({})
  const [loanLoading, setLoanLoading] = useState<string | null>(null)
  const [loanTypes, setLoanTypes] = useState<string[]>([])

  // One-time: collect the distinct loan_type values to populate the dropdown.
  useEffect(() => {
    fetchPipeline({ limit: 500 })
      .then((r) => {
        const uniq = [...new Set(r.applications.map((a) => a.loan_type).filter(Boolean))] as string[]
        setLoanTypes(uniq.sort())
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    let alive = true
    const t = setTimeout(async () => {
      setLoading(true)
      setError(null)
      setExpanded(null)
      try {
        const res = await loadPipeline(statusSel, type, search, period, limit, offset)
        if (alive) setData(res)
      } catch (e) {
        console.error('Pipeline load failed:', e)
        if (alive) setError('Could not load pipeline data.')
      } finally {
        if (alive) setLoading(false)
      }
    }, 250)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [search, type, period, statusSel, limit, offset, reloadKey])

  // Any filter change resets back to page 1.
  function applySearch(q: string) { setSearch(q); setOffset(0) }
  function applyType(v: string) { setType(v); setOffset(0) }
  function applyPeriod(p: Period) { setPeriod(p); setOffset(0) }
  function applyLimit(l: number) { setLimit(l); setOffset(0) }
  function pickCard(card: (typeof CARDS)[number]) {
    setStatusSel(cardActive(card.key) && card.key !== 'all' ? '' : card.key === 'all' ? '' : card.key)
    setOffset(0)
  }
  function pickStatus(val: string) { setStatusSel(val); setOffset(0) }
  function cardActive(key: string): boolean {
    return key === 'all' ? statusSel === '' : statusSel === key
  }

  function resetFilters() {
    setSearch('')
    setType('')
    setPeriod('all')
    setStatusSel('')
    setOffset(0)
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

  // Export the current (filtered) grid — one row per loan, one column per stage.
  function exportCsv() {
    const headers = ['Application', 'Borrower', 'Loan', 'Type', 'Status', ...STAGES.map((s) => s.label)]
    const out = rows.map((r) => {
      const halted = r.status === 'halted' || r.decisions['fraud_screening']?.outcome === 'block'
      return [
        r.application_id, r.borrower_name, r.loan_amount ?? '', r.loan_type ?? '',
        STATUS_BADGE[r.status]?.label ?? r.status,
        ...STAGES.map((s) => STAGE_ICON[stageState(s.personas, s.wave, r.decisions, halted)].label),
      ]
    })
    downloadCsv(headers, out, 'accord_pipeline')
  }
  function exportJson() {
    downloadJson(
      { exported_at: new Date().toISOString(), count: rows.length, filters: { search, type, status: statusSel, period }, applications: rows },
      'accord_pipeline',
    )
  }
  const exportItems = [
    { label: 'Export as CSV', run: exportCsv },
    { label: 'Export as PDF', run: printPdf },
    { label: 'Export raw JSON', run: exportJson },
  ]

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-slate-900">All Applications</h1>
        <p className="text-sm text-slate-500">
          {data ? `${data.total.toLocaleString()} loans across 5 lifecycle stages` : ' '}
        </p>
      </div>

      {/* KPI filter cards */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!kpis
          ? Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)
          : CARDS.map((c) => {
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
                  <div className={`mt-1 text-3xl font-semibold ${c.accent}`}>{c.count(kpis).toLocaleString()}</div>
                </button>
              )
            })}
      </div>

      {/* Filters: search (≈40%) + loan type + status + date range, one row */}
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <LoanSearch value={search} onSubmit={applySearch} className="min-w-[260px] flex-[2]" />
        <select
          value={type}
          onChange={(e) => applyType(e.target.value)}
          className="min-w-[150px] flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand"
        >
          <option value="">All Loan Types</option>
          {loanTypes.map((t) => (
            <option key={t} value={t}>
              {prettyLoanType(t)}
            </option>
          ))}
        </select>
        <StatusFilter value={statusSel} onChange={pickStatus} className="min-w-[150px] flex-1" />
        <div className="ml-auto flex items-center gap-3">
          <PeriodFilter value={period} onChange={applyPeriod} />
          <ExportMenu items={exportItems} />
        </div>
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
                <th key={s.key} title={s.tip} className="cursor-help px-2 py-3 text-center">{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {/* Legend row — colored word chips matching the grid cells */}
            {!error && !(!loading && rows.length === 0) && (
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
            )}

            {loading && <SkeletonRows rows={8} cols={COLS} />}
            {error && !loading && (
              <tr>
                <td colSpan={COLS} className="p-4">
                  <ErrorState message="Could not load pipeline data." onRetry={() => setReloadKey((k) => k + 1)} />
                </td>
              </tr>
            )}
            {!loading && !error && rows.length === 0 && (
              <tr>
                <td colSpan={COLS} className="p-4">
                  <EmptyState
                    title="No loans match this filter"
                    hint="Try adjusting your search or filters."
                    actionLabel="Clear filters"
                    onAction={resetFilters}
                  />
                </td>
              </tr>
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
                      <td colSpan={COLS} className="bg-gray-50 px-6 py-4">
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
        {!loading && !error && data && data.total > 0 && (
          <Pagination total={data.total} limit={limit} offset={offset} onOffset={setOffset} onLimit={applyLimit} />
        )}
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

  // Left border reflects the stage's worst outcome (matching the grid pill).
  const borderColor = decisions.some((d) => d.outcome === 'block')
    ? 'border-l-red-500'
    : decisions.some((d) => d.outcome === 'escalate' || d.outcome === 'recommend')
      ? 'border-l-amber-500'
      : 'border-l-green-500'

  return (
    <div className={`overflow-hidden rounded-lg border border-l-4 border-slate-200 bg-white ${borderColor}`}>
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
