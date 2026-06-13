import { useEffect, useState } from 'react'
import { fetchComparisonStatus, recordManual } from '../api/client'

const RESULT: Record<string, { label: string; cls: string }> = {
  agree: { label: '✅ AGREEMENT', cls: 'text-green-700' },
  accord_stricter: { label: '⚠ DISAGREEMENT — Accord stricter', cls: 'text-amber-700' },
  accord_looser: { label: '⚠ DISAGREEMENT — Accord looser', cls: 'text-amber-700' },
  disagree: { label: '❌ DISAGREEMENT', cls: 'text-red-700' },
}

// Loan-detail section, shown only during an active comparison period.
export default function ComparisonDecision({ applicationId }: { applicationId: string }) {
  const [active, setActive] = useState(false)
  const [existing, setExisting] = useState<{ accord_outcome: string; manual_outcome: string; agreement: string } | null>(null)
  const [outcome, setOutcome] = useState('')
  const [reasoning, setReasoning] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchComparisonStatus(applicationId).then((s) => { setActive(s.active); setExisting(s.existing) }).catch(() => undefined)
  }, [applicationId])

  if (!active) return null

  async function record() {
    if (!outcome) { setErr('Select your decision.'); return }
    if (!reasoning.trim()) { setErr('Your reasoning is required.'); return }
    setBusy(true); setErr(null)
    try {
      const r = await recordManual(applicationId, outcome, reasoning.trim())
      setExisting({ accord_outcome: r.accord_outcome, manual_outcome: r.manual_outcome, agreement: r.agreement })
    } catch (e: any) {
      setErr(e?.message || 'Could not record')
    } finally { setBusy(false) }
  }

  if (existing) {
    const res = RESULT[existing.agreement] || { label: existing.agreement, cls: 'text-slate-700' }
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-5 border-l-4 border-l-slate-400">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">🔄 Comparison mode</div>
        <div className="mt-1 text-sm font-semibold text-green-700">✅ Your decision recorded</div>
        <div className="mt-2 space-y-1 text-sm text-slate-700">
          <div><span className="font-medium text-slate-600">Accord:</span> {String(existing.accord_outcome).toUpperCase()}</div>
          <div><span className="font-medium text-slate-600">You:</span> {String(existing.manual_outcome).toUpperCase()}</div>
          <div className={`font-semibold ${res.cls}`}>Result: {res.label}</div>
        </div>
        <p className="mt-2 text-xs text-slate-400">This appears in the comparison report for manager review.</p>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 border-l-4 border-l-brand">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">🔄 Comparison mode — record your independent decision</div>
      <p className="mt-1 text-sm text-slate-600">Review Accord’s recommendation above, then make your own call. Both decisions are logged for comparison.</p>
      <div className="mt-3 space-y-1.5">
        {[['approved', 'Approve (I would approve this loan)'], ['denied', 'Deny (I would deny this loan)'], ['suspended', 'Suspend (I would suspend for more info)']].map(([v, label]) => (
          <label key={v} className="flex items-center gap-2 text-sm text-slate-700">
            <input type="radio" name="manual-decision" checked={outcome === v} onChange={() => setOutcome(v)} className="accent-brand" />
            {label}
          </label>
        ))}
      </div>
      <div className="mt-3">
        <label className="mb-1 block text-xs font-medium text-slate-500">Your reasoning (required)</label>
        <textarea value={reasoning} onChange={(e) => setReasoning(e.target.value)} rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand" />
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <button onClick={record} disabled={busy} className="mt-3 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">Record my decision</button>
    </section>
  )
}
