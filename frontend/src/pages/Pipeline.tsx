import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchPipeline } from '../api/client'
import type { PipelineResponse, PipelineKPIs } from '../types/accord'
import DecisionPill from '../components/DecisionPill'

// The 12 persona decision columns, in pipeline order, with the labels
// customers know them by.
const COLUMNS: Array<[string, string]> = [
  ['credit_assessment', 'Credit UW'],
  ['fraud_screening', 'Fraud Analyst'],
  ['compliance_check', 'Compliance'],
  ['employment_reconciliation', 'Employment'],
  ['income_verification', 'Income UW'],
  ['ltv_assessment', 'Collateral'],
  ['dti_calculation', 'DTI'],
  ['product_eligibility', 'Product'],
  ['rate_pricing', 'Pricing'],
  ['underwriting_decision', 'Senior UW'],
  ['approval_routing', 'Routing'],
  ['closing_readiness', 'Closer'],
]

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  halted: { label: 'Pipeline Halted', cls: 'bg-rose-700 text-white' },
  blocked: { label: 'Blocked', cls: 'bg-rose-100 text-rose-700' },
  in_review: { label: 'In Review', cls: 'bg-amber-100 text-amber-700' },
  clear_to_close: { label: 'Clear to Close', cls: 'bg-emerald-100 text-emerald-700' },
  in_progress: { label: 'In Progress', cls: 'bg-slate-100 text-slate-600' },
}

const URGENCY_DOT: Record<string, string> = {
  CRITICAL: 'bg-rose-600',
  URGENT: 'bg-orange-500',
  REVIEW: 'bg-amber-400',
  'ON TRACK': 'bg-emerald-400',
}

// KPI cards double as status filters. "Blocked/Halted" spans two statuses.
const CARDS: Array<{
  key: string
  label: string
  statuses: string[]
  count: (k: PipelineKPIs) => number
  accent: string
}> = [
  { key: 'all', label: 'Total Pipeline', statuses: [], count: (k) => k.total, accent: 'text-slate-900' },
  { key: 'in_review', label: 'In Review', statuses: ['in_review'], count: (k) => k.in_review, accent: 'text-amber-600' },
  { key: 'blocked', label: 'Blocked / Halted', statuses: ['blocked', 'halted'], count: (k) => k.blocked + k.halted, accent: 'text-rose-600' },
  { key: 'clear_to_close', label: 'Clear to Close', statuses: ['clear_to_close'], count: (k) => k.clear_to_close, accent: 'text-emerald-600' },
]

const TYPES = ['', 'conforming', 'jumbo', 'government', 'non_qm', 'other']

// Fetch one or more statuses (the combined card needs two) and merge.
async function loadPipeline(
  statuses: string[], type: string, search: string,
): Promise<PipelineResponse> {
  const common = { type, search, limit: 100 }
  if (statuses.length <= 1) {
    return fetchPipeline({ ...common, status: statuses[0] })
  }
  const parts = await Promise.all(statuses.map((s) => fetchPipeline({ ...common, status: s })))
  return {
    kpis: parts[0].kpis, // portfolio-wide, independent of the filter
    total: parts.reduce((a, p) => a + p.total, 0),
    applications: parts.flatMap((p) => p.applications).slice(0, 100),
  }
}

export default function Pipeline() {
  const navigate = useNavigate()
  const [data, setData] = useState<PipelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const [activeCard, setActiveCard] = useState('all')

  useEffect(() => {
    let alive = true
    const statuses = CARDS.find((c) => c.key === activeCard)?.statuses ?? []
    const t = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await loadPipeline(statuses, type, search)
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
  }, [search, type, activeCard])

  const rows = data?.applications ?? []
  const kpis = data?.kpis
  const colSpan = 4 + COLUMNS.length

  return (
    <div className="mx-auto max-w-[1700px] px-6 py-6">
      <div className="mb-5 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Decision Pipeline</h1>
          <p className="text-sm text-slate-500">Every application across all 12 underwriting personas.</p>
        </div>
        <span className="text-sm text-slate-500">
          {data ? `${rows.length} of ${data.total.toLocaleString()} applications` : ' '}
        </span>
      </div>

      {/* KPI cards — click to filter */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {CARDS.map((c) => {
          const active = activeCard === c.key
          return (
            <button
              key={c.key}
              onClick={() => setActiveCard(active && c.key !== 'all' ? 'all' : c.key)}
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

      {/* Search + type filter */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search borrower or application ID…"
            className="w-80 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </div>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm capitalize outline-none focus:border-brand"
        >
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t === '' ? 'All application types' : t}
            </option>
          ))}
        </select>
        {(activeCard !== 'all' || type || search) && (
          <button
            onClick={() => {
              setActiveCard('all')
              setType('')
              setSearch('')
            }}
            className="text-sm font-medium text-brand hover:underline"
          >
            Reset filters
          </button>
        )}
      </div>

      {/* Grid — horizontally scrollable; Application column sticks left */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="sticky left-0 z-10 bg-slate-50 px-4 py-3 text-left">Application</th>
              <th className="px-4 py-3 text-left">Borrower</th>
              <th className="px-4 py-3 text-left whitespace-nowrap">Application Type</th>
              <th className="px-4 py-3 text-left">Status</th>
              {COLUMNS.map(([id, label]) => (
                <th key={id} className="px-3 py-3 text-left whitespace-nowrap">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={colSpan} className="px-4 py-12 text-center text-slate-400">
                  Loading pipeline…
                </td>
              </tr>
            )}
            {error && !loading && (
              <tr>
                <td colSpan={colSpan} className="px-4 py-12 text-center">
                  <div className="text-rose-600">{error}</div>
                  <button
                    onClick={() => setActiveCard((c) => c)}
                    className="mt-2 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-dark"
                  >
                    Retry
                  </button>
                </td>
              </tr>
            )}
            {!loading && !error && rows.length === 0 && (
              <tr>
                <td colSpan={colSpan} className="px-4 py-12 text-center text-slate-400">
                  No applications match these filters.
                </td>
              </tr>
            )}
            {!loading &&
              !error &&
              rows.map((r) => {
                const badge = STATUS_BADGE[r.status] ?? STATUS_BADGE.in_progress
                return (
                  <tr
                    key={r.application_id}
                    onClick={() => navigate(`/pipeline/${r.application_id}`)}
                    className="group cursor-pointer hover:bg-brand-light/40"
                  >
                    <td className="sticky left-0 z-10 bg-white px-4 py-2.5 font-mono text-xs text-slate-600 whitespace-nowrap group-hover:bg-[#eef7f3]">
                      <span className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${URGENCY_DOT[r.urgency] ?? 'bg-slate-300'}`}
                          title={r.urgency}
                        />
                        {r.application_id}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap font-medium text-slate-800">
                      {r.borrower_name}
                    </td>
                    <td className="px-4 py-2.5 capitalize text-slate-500">{r.loan_type ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${badge.cls}`}>
                        {badge.label}
                      </span>
                    </td>
                    {COLUMNS.map(([id]) => {
                      const dec = r.decisions[id]
                      return (
                        <td key={id} className="px-3 py-2.5">
                          <DecisionPill outcome={dec?.outcome ?? null} reviewed={dec?.reviewed} compact />
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
