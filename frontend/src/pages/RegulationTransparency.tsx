import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchRegulationTransparency,
  type RegulationTransparency as RTData,
  type RegulationRule,
  type LenderRuleVersion,
} from '../api/client'

const LAYER_ICON: Record<string, string> = { federal: '🔒', agency: '📋', state: '🏛', lender: '🔧' }
const fmtDate = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—')

function RuleRow({ r }: { r: RegulationRule }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-slate-100 px-4 py-2.5 text-sm last:border-0">
      <span aria-hidden="true">{LAYER_ICON[r.layer]}</span>
      {r.state_code && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold text-slate-600">{r.state_code}</span>}
      <span className="font-medium text-slate-800">{r.rule_name}</span>
      {r.display_value && <span className="font-semibold text-brand">{r.display_value}</span>}
      {r.citation && <span className="text-xs text-slate-400">{r.citation}</span>}
      <span className="ml-auto text-[11px] text-slate-400">Refreshed {fmtDate(r.last_refreshed)}</span>
    </div>
  )
}

function LayerCard({ title, subtitle, count, children, defaultOpen = true }: {
  title: string; subtitle: string; count: number; children: React.ReactNode; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between bg-slate-50 px-4 py-3 text-left">
        <div>
          <div className="text-sm font-bold uppercase tracking-wide text-slate-700">{title} <span className="text-slate-400">({count})</span></div>
          <div className="text-xs text-slate-500">{subtitle}</div>
        </div>
        <span className="text-slate-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div>{children}</div>}
    </section>
  )
}

function LenderCard({ versions }: { versions: LenderRuleVersion[] }) {
  const [open, setOpen] = useState(true)
  const active = versions.find((v) => v.status === 'active')
  const scheduled = versions.find((v) => v.status === 'scheduled')
  const rules = (active?.rules ?? {}) as Record<string, Record<string, unknown>>
  const overlays: Array<[string, unknown, string]> = [
    ['Credit floor', rules.credit?.min_score, 'min credit score'],
    ['DTI max (back-end)', rules.dti?.back_max != null ? `${rules.dti.back_max}%` : undefined, 'debt-to-income'],
    ['LTV max', rules.ltv?.max != null ? `${rules.ltv.max}%` : undefined, 'loan-to-value'],
    ['Fraud threshold', rules.fraud?.watchlist_threshold, 'watchlist score'],
    ['Identity min', rules.fraud?.identity_min, 'identity confidence'],
  ]
  const waivers = (rules.waivers as unknown as Array<Record<string, unknown>>) || []
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between bg-slate-50 px-4 py-3 text-left">
        <div>
          <div className="text-sm font-bold uppercase tracking-wide text-slate-700">Your Policy <span className="text-slate-400">(lender overlays{active ? ` · v${active.version} active` : ''})</span></div>
          <div className="text-xs text-slate-500">Editable by admin{active?.effective_from ? ` · Last changed ${fmtDate(active.effective_from)}` : ''}</div>
        </div>
        <span className="text-slate-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-4 py-3">
          {overlays.filter(([, v]) => v != null && v !== '').map(([label, value, note]) => (
            <div key={label} className="flex flex-wrap items-baseline gap-x-3 border-b border-slate-100 py-2 text-sm last:border-0">
              <span aria-hidden="true">🔧</span>
              <span className="font-medium text-slate-800">{label}</span>
              <span className="font-semibold text-brand">{String(value)}</span>
              <span className="text-xs text-slate-400">{note}</span>
            </div>
          ))}
          {waivers.map((w, i) => (
            <div key={i} className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Waiver: <strong>{String(w.name)}</strong> · {String(w.field)} {String(w.value)}{w.expires ? ` · expires ${fmtDate(String(w.expires))}` : ''}
            </div>
          ))}
          {scheduled && (
            <div className="mt-2 rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600">
              Scheduled: <strong>v{scheduled.version}</strong> · {scheduled.changes_summary || '—'}{scheduled.scheduled_for ? ` · ${fmtDate(scheduled.scheduled_for)}` : ''}
            </div>
          )}
          <Link to="/settings/rules" className="mt-3 inline-block text-sm font-semibold text-brand hover:underline">Edit Policy →</Link>
        </div>
      )}
    </section>
  )
}

function ProtectionCard({ p }: { p: RTData['pipeline_protection'] }) {
  const pct = p.total_locked > 0 ? Math.round((p.pinned / p.total_locked) * 100) : 100
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="text-sm font-bold uppercase tracking-wide text-slate-700">Pipeline Protection</div>
      <p className="mt-1 text-sm text-slate-500">Loans rate-locked before a rule change are evaluated under the rules active at their lock date.</p>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div><div className="text-2xl font-bold text-slate-900">{p.total_locked.toLocaleString()}</div><div className="text-slate-500">Rate-locked loans</div></div>
        <div><div className="text-2xl font-bold text-brand">{p.pinned.toLocaleString()} <span className="text-sm font-medium text-slate-400">({pct}%)</span></div><div className="text-slate-500">Pinned to a rule version</div></div>
        <div><div className="text-2xl font-bold text-slate-900">{p.current_version != null ? `v${p.current_version}` : '—'}</div><div className="text-slate-500">Current version{p.current_effective ? ` · ${fmtDate(p.current_effective)}` : ''}</div></div>
      </div>
      <div className={`mt-4 rounded-lg px-3 py-2 text-sm ${p.unpinned === 0 ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
        {p.unpinned === 0 ? '✅ ' : '⚠ '}{p.note}
      </div>
    </section>
  )
}

const STATES = ['TX', 'NY', 'CA', 'FL', 'IL', 'PA', 'OH', 'GA', 'NC', 'VA']
const TABS = [['all', 'All'], ['federal', 'Federal'], ['agency', 'Agency'], ['state', 'State'], ['lender', 'Your Policy']] as const

export default function RegulationTransparency() {
  const [data, setData] = useState<RTData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<string>('all')
  const [stateFilter, setStateFilter] = useState<string>('')

  useEffect(() => {
    let alive = true
    setErr(null)
    // Fetch all layers once; the state dropdown filters only the state layer
    // client-side so federal/agency stay visible.
    fetchRegulationTransparency()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : 'Failed to load'))
    return () => { alive = false }
  }, [])

  const show = (l: string) => tab === 'all' || tab === l
  const lastUpdated = useMemo(() => {
    if (!data) return null
    const ds = [data.summary.last_federal_refresh, data.summary.last_agency_refresh].filter(Boolean) as string[]
    return ds.length ? ds.sort().slice(-1)[0] : null
  }, [data])

  if (err) return <div className="p-10 text-center text-sm text-red-600">{err}</div>
  if (!data) return <div className="p-10 text-center text-sm text-slate-400">Loading regulation transparency…</div>

  const { layers, summary } = data
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Regulation Transparency</h1>
          <p className="mt-1 text-sm text-slate-500">
            All four layers — federal, agency, state, and your policy — visible on demand.
            {lastUpdated && <> Last updated {fmtDate(lastUpdated)}.</>}
          </p>
        </div>
        <div className="text-xs text-slate-500">
          {summary.federal_count} federal · {summary.agency_count} agency · {summary.state_count} state ({summary.states_covered.length} states) · {summary.lender_versions} policy versions
        </div>
      </div>

      {/* Filter bar */}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${tab === k ? 'bg-brand text-white' : 'border border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
            {label}
          </button>
        ))}
        <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}
          className="ml-auto rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-brand focus:outline-none">
          <option value="">All States</option>
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div className="mt-5 space-y-4">
        {show('federal') && (
          <LayerCard title="Federal" count={layers.federal.length} subtitle={`Maintained by Accord · Last refreshed ${fmtDate(summary.last_federal_refresh)}`}>
            {layers.federal.map((r) => <RuleRow key={r.regulation_id} r={r} />)}
            {layers.federal.length === 0 && <div className="px-4 py-3 text-sm text-slate-400">No federal rules.</div>}
          </LayerCard>
        )}
        {show('agency') && (
          <LayerCard title="Agency" count={layers.agency.length} subtitle={`Verified ${fmtDate(summary.last_agency_refresh)} · Accord compliance team`}>
            {layers.agency.map((r) => <RuleRow key={r.regulation_id} r={r} />)}
            {layers.agency.length === 0 && <div className="px-4 py-3 text-sm text-slate-400">No agency guidelines.</div>}
          </LayerCard>
        )}
        {show('state') && (() => {
          const stateRules = stateFilter ? layers.state.filter((r) => r.state_code === stateFilter) : layers.state
          return (
            <LayerCard title="State" count={stateRules.length} subtitle={`Applied per property location on every loan${summary.states_covered.length ? ` · ${summary.states_covered.length} states` : ''}${stateFilter ? ` · filtered to ${stateFilter}` : ''}`}>
              {stateRules.map((r) => <RuleRow key={r.regulation_id} r={r} />)}
              {stateRules.length === 0 && <div className="px-4 py-3 text-sm text-slate-400">No state rules for this filter.</div>}
            </LayerCard>
          )
        })()}
        {show('lender') && <LenderCard versions={layers.lender} />}
      </div>

      <div className="mt-4"><ProtectionCard p={data.pipeline_protection} /></div>
    </div>
  )
}
