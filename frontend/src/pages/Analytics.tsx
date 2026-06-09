import { useEffect, useState } from 'react'
import { fetchAnalytics } from '../api/client'
import type { AnalyticsOverview } from '../types/accord'

// Placeholder — full analytics dashboard (funnel, agent stats, risk
// concentration charts) is built in Session 3. Shows the live overview.
export default function Analytics() {
  const [data, setData] = useState<AnalyticsOverview | null>(null)

  useEffect(() => {
    fetchAnalytics().then(setData).catch(() => setData(null))
  }, [])

  const cards: Array<[string, string]> = data
    ? [
        ['Total loans', data.total_loans.toLocaleString()],
        ['Total volume', `$${(data.total_volume / 1e9).toFixed(2)}B`],
        ['Avg credit score', String(data.avg_score)],
        ['Avg LTV', `${data.avg_ltv}%`],
        ['Avg DTI', `${data.avg_dti}%`],
        ['Approval rate', `${(data.approval_rate * 100).toFixed(1)}%`],
      ]
    : []

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-1 text-xl font-semibold text-slate-900">Analytics</h1>
      <p className="mb-5 text-sm text-slate-500">Portfolio overview · full dashboard coming in Session 3.</p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {cards.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
          </div>
        ))}
        {!data && <div className="text-slate-400">Loading…</div>}
      </div>
    </div>
  )
}
