import { Link } from 'react-router-dom'
import type { SimilarCase } from '../../api/client'
import { money } from './util'

const OUTCOME_CLS: Record<string, string> = {
  'BSA Referral': 'bg-red-50 text-red-700', Denied: 'bg-red-50 text-red-700',
  Approved: 'bg-green-50 text-green-700', 'Docs Requested': 'bg-amber-50 text-amber-700',
  'Senior Review': 'bg-amber-50 text-amber-700', Escalated: 'bg-amber-50 text-amber-700',
}
const shortId = (id: string) => id.replace(/^APP-/, '').replace(/^LOAN-/, '')

export default function SimilarCases({ cases, loading }: { cases: SimilarCase[]; loading: boolean }) {
  return (
    <div>
      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Similar files</div>
      {loading ? (
        <p className="text-sm text-slate-400">Finding similar files…</p>
      ) : cases.length === 0 ? (
        <p className="text-sm text-slate-400">No similar cases found.</p>
      ) : (
        <div className="space-y-2">
          {cases.map((c) => (
            <Link
              key={c.application_id}
              to={`/pipeline/${c.application_id}`}
              className="block rounded-lg border border-slate-200 bg-white p-3 transition hover:border-brand/40 hover:bg-slate-50"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-slate-600">{shortId(c.application_id)}</span>
                <span className="text-xs font-medium text-slate-700">{money(c.loan_amount)}</span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-xs">
                {c.fraud_score != null && <span className="text-slate-500">Fraud {c.fraud_score.toFixed(2)}</span>}
                <span className={`ml-auto rounded-full px-2 py-0.5 font-semibold ${OUTCOME_CLS[c.outcome] || 'bg-slate-100 text-slate-600'}`}>{c.outcome}</span>
              </div>
              <p className="mt-1.5 text-xs leading-snug text-slate-600">“{c.reason_text.slice(0, 80)}{c.reason_text.length > 80 ? '…' : ''}”</p>
              {c.resolved_days != null && <p className="mt-1 text-[11px] text-slate-400">Resolved in {c.resolved_days} day{c.resolved_days === 1 ? '' : 's'}</p>}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
