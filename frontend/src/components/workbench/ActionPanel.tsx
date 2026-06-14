import { useState } from 'react'
import type { DecisionDetail, LoanDetail } from '../../types/accord'
import type { LoanAction, SimilarCase } from '../../api/client'
import { primaryDecision, friendly } from './util'
import ActionModal from './ActionModal'
import SimilarCases from './SimilarCases'

const ACTION_LABEL: Record<string, string> = {
  refer_bsa: '⚠ Refer to BSA/AML', request_documents: '📧 Request documents', escalate: '⬆ Escalate',
  senior_review: '👤 Senior review', approve: '✅ Approve', deny: '❌ Deny', add_note: '📝 Add a note',
}
const ROLE_ACTIONS: Record<string, string[]> = {
  viewer: [],
  compliance: ['add_note'],
  processor: ['request_documents', 'escalate', 'add_note'],
  closer: ['request_documents', 'escalate', 'add_note'],
  underwriter: ['refer_bsa', 'request_documents', 'escalate', 'senior_review', 'add_note'],
  senior_uw: ['approve', 'deny', 'refer_bsa', 'request_documents', 'escalate', 'senior_review', 'add_note'],
  manager: ['approve', 'deny', 'refer_bsa', 'request_documents', 'escalate', 'senior_review', 'add_note'],
  admin: ['approve', 'deny', 'refer_bsa', 'request_documents', 'escalate', 'senior_review', 'add_note'],
}

function recommendedAction(primary: DecisionDetail | null): { action: string; why: string } {
  if (!primary) return { action: 'approve', why: 'All checks passed — ready to advance.' }
  if (primary.decision_id === 'fraud_screening') return { action: 'refer_bsa', why: 'Identity / watchlist risk — mandatory BSA referral before proceeding.' }
  if (['income_verification', 'employment_reconciliation'].includes(primary.decision_id))
    return { action: 'request_documents', why: 'Income / employment not fully verified — request supporting documents.' }
  if (primary.decision_id === 'compliance_check') return { action: 'request_documents', why: 'Disclosure / TRID issue — re-issue and confirm timing.' }
  return { action: 'request_documents', why: `${friendly(primary.decision_id)} needs attention before this advances.` }
}

export default function ActionPanel({ loan, role, similar, similarLoading, onActionDone }: {
  loan: LoanDetail; role: string; similar: SimilarCase[]; similarLoading: boolean; onActionDone: (a: LoanAction) => void
}) {
  const [modalAction, setModalAction] = useState<string | null>(null)
  const decisions = loan.decisions ?? []
  const primary = primaryDecision(decisions)
  const rec = recommendedAction(primary)
  const allowed = ROLE_ACTIONS[role] ?? []
  const hasBlock = decisions.some((d) => d.outcome === 'block')

  // Primary button = the recommendation if this role can do it, else escalate.
  const primaryBtn = allowed.includes(rec.action) ? rec.action : allowed.includes('escalate') ? 'escalate' : allowed[0] || null
  const secondary = allowed.filter((a) => a !== primaryBtn)
  // Actions this role can't take, surfaced as disabled with a reason.
  const unavailable: Array<{ action: string; reason: string }> = []
  if (!allowed.includes('approve')) unavailable.push({ action: 'approve', reason: hasBlock ? 'resolve the block first' : 'requires a senior underwriter' })
  if (!allowed.includes('deny')) unavailable.push({ action: 'deny', reason: 'requires a senior underwriter' })

  const primaryTone = primaryBtn === 'approve' ? 'bg-green-600 hover:bg-green-700'
    : primaryBtn === 'refer_bsa' || primaryBtn === 'deny' ? 'bg-red-600 hover:bg-red-700' : 'bg-brand hover:bg-brand-dark'

  if (allowed.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
        <span className="font-medium text-slate-700">View only</span> — your role can review this file but cannot take action.
        <div className="mt-5"><SimilarCases cases={similar} loading={similarLoading} /></div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Recommended</div>
        <div className="mt-1 text-base font-semibold text-slate-900">{ACTION_LABEL[rec.action]?.replace(/^\S+\s/, '') ?? rec.action}</div>
        <p className="mt-1 text-xs leading-snug text-slate-500">{rec.why}</p>

        <div className="mt-3 space-y-2">
          {primaryBtn && (
            <button onClick={() => setModalAction(primaryBtn)} className={`w-full rounded-lg px-4 py-2.5 text-sm font-semibold text-white ${primaryTone}`}>
              {ACTION_LABEL[primaryBtn] ?? primaryBtn}
            </button>
          )}
          {secondary.map((a) => (
            <button key={a} onClick={() => setModalAction(a)} className={`w-full rounded-lg border px-4 py-2 text-sm font-medium hover:bg-slate-50 ${a === 'deny' ? 'border-red-200 text-red-600' : 'border-slate-200 text-slate-700'}`}>
              {ACTION_LABEL[a] ?? a}
            </button>
          ))}
          {unavailable.map((u) => (
            <div key={u.action} title={u.reason} className="w-full cursor-not-allowed rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-400">
              {ACTION_LABEL[u.action]?.replace(/^\S+\s/, '') ?? u.action} — {u.reason}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <SimilarCases cases={similar} loading={similarLoading} />
      </div>

      {modalAction && (
        <ActionModal
          appId={loan.application_id}
          actionType={modalAction}
          relatedDecisionId={primary?.decision_id ?? null}
          onClose={() => setModalAction(null)}
          onDone={(a) => { setModalAction(null); onActionDone(a) }}
        />
      )}
    </div>
  )
}
