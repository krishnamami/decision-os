import type { EscalationThreadItem, LoanDetail } from '../types/accord'
import EscalationThread from './workbench/EscalationThread'

function dotColor(action: string): string {
  const a = action.toLowerCase()
  if (a.includes('block') || a.includes('halt') || a.includes('revert') || a.includes('deny')) return 'bg-red-500'
  if (a.includes('approv')) return 'bg-green-500'
  if (a.includes('override')) return 'bg-amber-500'
  return 'bg-slate-300'
}

// Human label for an override outcome (what the reviewer chose it to become).
const OUTCOME_LABEL: Record<string, string> = {
  clear_block: 'CLEARED', approve: 'APPROVED', deny: 'DENIED', waive_condition: 'WAIVED',
}

type ActivityItem = LoanDetail['activity'][number]

// Rich card for override entries — the exam-ready trail the spec calls for.
function OverrideEntry({ a, d }: { a: ActivityItem; d: Record<string, unknown> }) {
  const decisionName = String(d.decision_name || d.decision_id || a.target || 'a decision')
  const original = String(d.original_outcome || '').toUpperCase() || '—'
  const newLabel = OUTCOME_LABEL[String(d.override_outcome)] || String(d.new_outcome || '').toUpperCase() || '—'
  const reason = d.reason ? String(d.reason) : ''
  const waived = Number(d.conditions_waived || 0)
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
      <div className="text-[13px] font-semibold text-amber-900">🔄 Override by {a.actor}</div>
      <div className="mt-1 text-[12px] text-slate-700">
        Decision: <span className="font-semibold">{decisionName}</span> → <span className="font-semibold">OVERRIDDEN</span>
      </div>
      <div className="text-[12px] text-slate-700">
        Original: <span className="font-semibold">{original}</span> <span className="text-slate-400">|</span> New: <span className="font-semibold text-amber-800">{newLabel}</span>
        {waived > 0 && <span className="text-slate-500"> · {waived} condition{waived === 1 ? '' : 's'} waived</span>}
      </div>
      {reason && <div className="mt-1 text-[12px] italic text-slate-600">Reason: “{reason}”</div>}
      {a.at && <div className="mt-1 text-[11px] text-slate-400">{new Date(a.at).toLocaleString()}</div>}
    </div>
  )
}

export default function ActivityFeed({ activity, escalationThread }: {
  activity: LoanDetail['activity']
  escalationThread?: EscalationThreadItem[]
}) {
  const thread = escalationThread ?? []
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-3 text-sm font-semibold text-slate-900">Audit trail</div>
      {thread.length > 0 && (
        <div className="mb-4 rounded-lg border border-slate-100 bg-slate-50/60 p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Escalation history</div>
          <EscalationThread items={thread} />
        </div>
      )}
      {activity.length === 0 ? (
        <p className="text-sm text-slate-400">No data available.</p>
      ) : (
        <ul className="space-y-3">
          {activity.map((a, i) => {
            const detail = (a.detail && typeof a.detail === 'object') ? a.detail as Record<string, unknown> : null
            const isOverride = a.action.toLowerCase().includes('override') && !!detail?.override_outcome
            return (
              <li key={i} className="flex gap-3 text-sm">
                <span className="relative flex flex-col items-center">
                  <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotColor(a.action)}`} />
                  {i < activity.length - 1 && <span className="mt-1 w-px flex-1 bg-slate-200" />}
                </span>
                <div className="min-w-0 flex-1 pb-1">
                  {isOverride ? (
                    <OverrideEntry a={a} d={detail as Record<string, unknown>} />
                  ) : (
                    <>
                      <div className="text-slate-700">
                        <span className="font-medium">{a.actor}</span> {a.action.replace(/_/g, ' ')}
                        {a.target ? <span className="text-slate-400"> · {a.target}</span> : ''}
                      </div>
                      {a.at && <div className="text-xs text-slate-400">{new Date(a.at).toLocaleString()}</div>}
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
