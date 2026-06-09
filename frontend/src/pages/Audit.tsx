import { useEffect, useState } from 'react'
import { fetchComplianceHealth } from '../api/client'

// Placeholder — full audit reporting (HMDA LAR, adverse-action queue,
// examiner package) is built in Session 3. Shows the live compliance health.
export default function Audit() {
  const [health, setHealth] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    fetchComplianceHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const cards: Array<[string, string]> = health
    ? [
        ['HMDA clean', `${health.hmda_pct}%`],
        ['Adverse actions pending', String(health.adverse_pending)],
        ['Overrides this month', String(health.overrides)],
        ['SLA compliance', `${health.sla_pct}%`],
        ['Segregation flags', String(health.segregation_flags)],
      ]
    : []

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-1 text-xl font-semibold text-slate-900">Audit & Compliance</h1>
      <p className="mb-5 text-sm text-slate-500">Compliance health · full reporting coming in Session 3.</p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {cards.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
          </div>
        ))}
        {!health && <div className="text-slate-400">Loading…</div>}
      </div>
    </div>
  )
}
