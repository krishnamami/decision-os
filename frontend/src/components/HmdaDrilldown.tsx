import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchHmdaIncomplete, type HmdaIncompleteResponse } from '../api/client'

type Group = 'demographic' | 'loan' | 'property'
const HMDA_FIELDS: Record<string, { label: string; group: Group }> = {
  hmda_ethnicity: { label: 'Ethnicity', group: 'demographic' },
  hmda_race: { label: 'Race', group: 'demographic' },
  hmda_sex: { label: 'Sex', group: 'demographic' },
  hmda_income: { label: 'Gross annual income', group: 'loan' },
  hmda_loan_amount: { label: 'Loan amount', group: 'loan' },
  hmda_loan_purpose: { label: 'Loan purpose', group: 'loan' },
  hmda_rate_spread: { label: 'Rate spread', group: 'loan' },
  hmda_action_taken: { label: 'Action taken', group: 'loan' },
  hmda_denial_reason: { label: 'Denial reason (declined loans)', group: 'loan' },
  hmda_occupancy_type: { label: 'Occupancy type', group: 'property' },
  hmda_tract_number: { label: 'Census tract', group: 'property' },
  hmda_county_code: { label: 'County code', group: 'property' },
  hmda_msa_md: { label: 'MSA / MD', group: 'property' },
}
const fieldLabel = (f: string) => HMDA_FIELDS[f]?.label ?? f.replace(/^hmda_/, '').replace(/_/g, ' ')
const fieldGroup = (f: string): Group | undefined => HMDA_FIELDS[f]?.group

export default function HmdaDrilldown() {
  const [data, setData] = useState<HmdaIncompleteResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | Group>('all')

  useEffect(() => {
    let alive = true
    fetchHmdaIncomplete().then((d) => alive && setData(d)).catch((e) => alive && setErr(e instanceof Error ? e.message : 'Failed to load'))
    return () => { alive = false }
  }, [])

  const loans = useMemo(() => {
    if (!data) return []
    if (filter === 'all') return data.loans
    return data.loans.filter((l) => l.missing_fields.some((f) => fieldGroup(f) === filter))
  }, [data, filter])

  if (err) return <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{err}</div>
  if (!data) return <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-400">Loading HMDA completion…</div>

  if (data.incomplete === 0) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 p-5 text-sm font-medium text-green-800">
        ✅ All HMDA fields complete — {data.complete} of {data.total} loans.
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-slate-900">
            HMDA Completion — {data.pct}% ({data.complete} of {data.total} loans complete)
          </h3>
          <p className="mt-0.5 text-sm text-slate-500">Filing deadline: {data.filing_deadline} · HMDA Reg C 12 CFR §1003</p>
          <p className="mt-1 text-sm font-medium text-amber-700">⚠️ {data.incomplete} loans need attention before the filing deadline.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          Filter by field type
          <select value={filter} onChange={(e) => setFilter(e.target.value as 'all' | Group)} className="rounded-md border border-slate-300 px-2 py-1 text-sm outline-none focus:border-brand">
            <option value="all">All</option>
            <option value="demographic">Demographic</option>
            <option value="loan">Loan</option>
            <option value="property">Property</option>
          </select>
        </label>
      </div>

      <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">{data.note}</p>

      <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Application</th>
              <th className="px-3 py-2 text-left">Borrower</th>
              <th className="px-3 py-2 text-left">Missing fields</th>
              <th className="px-3 py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loans.map((l) => (
              <tr key={l.application_id}>
                <td className="px-3 py-2 font-mono text-xs text-slate-700">{l.application_id}</td>
                <td className="px-3 py-2 text-slate-800">{l.borrower_name}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {l.missing_fields.map((f) => (
                      <span key={f} className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">{fieldLabel(f)}</span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2 text-right">
                  <Link to={`/pipeline/${l.application_id}`} className="text-sm font-medium text-brand hover:underline">Complete →</Link>
                </td>
              </tr>
            ))}
            {loans.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-sm text-slate-400">No loans missing {filter} fields.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-400">Sorted by most fields missing first · {loans.length} of {data.incomplete} incomplete loans shown.</p>
    </div>
  )
}
