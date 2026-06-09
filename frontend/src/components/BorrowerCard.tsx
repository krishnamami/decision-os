import type { LoanDetail } from '../types/accord'

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  halted: { label: 'Pipeline Halted', cls: 'bg-red-700 text-white' },
  blocked: { label: 'Blocked', cls: 'bg-red-100 text-red-800' },
  in_review: { label: 'In Review', cls: 'bg-amber-100 text-amber-800' },
  clear_to_close: { label: 'Clear to Close', cls: 'bg-green-100 text-green-800' },
  in_progress: { label: 'In Progress', cls: 'bg-slate-100 text-slate-600' },
}

const URGENCY: Record<string, string> = {
  CRITICAL: 'text-red-600',
  URGENT: 'text-orange-600',
  REVIEW: 'text-amber-600',
  'ON TRACK': 'text-emerald-600',
}

function money(v: number | null) {
  return v == null ? '—' : `$${v.toLocaleString()}`
}

export default function BorrowerCard({ loan }: { loan: LoanDetail }) {
  const m = loan.metrics
  const badge = STATUS_BADGE[loan.status] ?? STATUS_BADGE.in_progress
  const metrics: Array<[string, string]> = [
    ['Loan', money(m.loan_amount)],
    ['Score', m.credit_score != null ? String(m.credit_score) : '—'],
    ['LTV', m.ltv != null ? `${m.ltv}%` : '—'],
    ['DTI', m.dti != null ? `${m.dti}%` : '—'],
    ['Rate', m.interest_rate != null ? `${m.interest_rate}%` : '—'],
    ['Lock', m.lock_days_remaining != null ? `${m.lock_days_remaining}d` : '—'],
  ]
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-light text-lg font-semibold text-brand">
            {(loan.borrower.name || '?').slice(0, 1).toUpperCase()}
          </div>
          <div>
            <div className="text-xl font-semibold text-slate-900">{loan.borrower.name}</div>
            <div className="text-sm text-slate-500">
              {loan.borrower.employer || '—'}
              {loan.borrower.age ? ` · ${loan.borrower.age}` : ''}
              {' · '}
              <span className="font-mono text-xs">{loan.application_id}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${badge.cls}`}>
            {badge.label}
          </span>
          <span className={`text-xs font-medium ${URGENCY[loan.urgency] ?? 'text-slate-400'}`}>
            {loan.urgency}
          </span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-slate-700">{loan.borrower.story}</p>

      <dl className="mt-5 grid grid-cols-3 gap-4 border-t border-slate-100 pt-4 sm:grid-cols-6">
        {metrics.map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs uppercase tracking-wide text-slate-400">{k}</dt>
            <dd className="mt-0.5 font-semibold text-slate-900">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
