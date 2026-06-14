import { useState } from 'react'
import type { LoanAction } from '../../api/client'
import { fmtTs, friendly } from './util'
import ActionModal from './ActionModal'

const ACTION_VERB: Record<string, string> = {
  refer_bsa: 'Referred to BSA', deny: 'Denied', approve: 'Approved', escalate: 'Escalated',
  senior_review: 'Sent for senior review', request_documents: 'Requested documents', add_note: 'Added a note',
}
const CAT_LABEL: Record<string, string> = {
  policy_requirement: 'Policy', documentation_gap: 'Documentation', fraud_concern: 'Fraud',
  income_exception: 'Income', credit_exception: 'Credit', other: 'Other',
}
const initials = (email: string) => (email.split('@')[0] || '?').slice(0, 2).toUpperCase()

type Activity = { actor?: string; action?: string; at?: string; detail?: { note?: string } }

export default function NotesTab({ appId, actions, activity, onActionDone }: {
  appId: string; actions: LoanAction[]; activity: Activity[]; onActionDone: (a: LoanAction) => void
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold uppercase tracking-wide text-slate-500">Decision notes</h3>
        <button onClick={() => setAdding(true)} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Add a note for the team →</button>
      </div>

      {actions.length === 0 ? (
        <p className="text-sm text-slate-400">No documented decisions yet.</p>
      ) : (
        <div className="space-y-3">
          {actions.map((a) => (
            <div key={a.id} className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">{initials(a.performed_by)}</span>
                <span className="text-sm font-semibold text-slate-800">{a.performed_by}</span>
                <span className="text-xs text-slate-400">· {fmtTs(a.performed_at)}</span>
                <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{ACTION_VERB[a.action_type] ?? a.action_type}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {a.reason_category && <span className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700">{CAT_LABEL[a.reason_category] ?? a.reason_category}</span>}
                {a.related_decision_id && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{friendly(a.related_decision_id)}</span>}
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">{a.reason_text}</p>
              {a.visible_to.length > 0 && <div className="mt-2 text-[11px] text-slate-400">Visible to: {a.visible_to.join(', ')}</div>}
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">Activity log</h3>
        {activity.length === 0 ? (
          <p className="text-sm text-slate-400">No system activity recorded.</p>
        ) : (
          <ul className="space-y-1">
            {activity.map((a, i) => (
              <li key={i} className="border-b border-slate-100 py-1.5 text-sm text-slate-500">
                <span className="font-mono text-xs text-slate-400">{fmtTs(a.at)}</span> · <span className="font-medium text-slate-700">{a.actor}</span> · {a.action}{a.detail?.note ? ` — "${a.detail.note}"` : ''}
              </li>
            ))}
          </ul>
        )}
      </div>

      {adding && (
        <ActionModal appId={appId} actionType="add_note" relatedDecisionId={null} onClose={() => setAdding(false)} onDone={(a) => { setAdding(false); onActionDone(a) }} />
      )}
    </div>
  )
}
