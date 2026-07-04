import { useEffect, useState } from 'react'
import Modal from '../Modal'
import { createLoanAction, getToken, type LoanAction } from '../../api/client'
import EscalationThread from './EscalationThread'
import type { EscalationThreadItem } from '../../types/accord'

const CATEGORIES = [
  ['policy_requirement', 'Policy Requirement'],
  ['documentation_gap', 'Documentation Gap'],
  ['fraud_concern', 'Fraud Concern'],
  ['income_exception', 'Income Exception'],
  ['credit_exception', 'Credit Exception'],
  ['other', 'Other'],
] as const
const AUDIENCES = ['senior_uw', 'compliance', 'examiner', 'bsa'] as const
const AUD_LABEL: Record<string, string> = { senior_uw: 'Senior UW', compliance: 'Compliance', examiner: 'Examiner', bsa: 'BSA' }
const ACTION_PHRASE: Record<string, string> = {
  refer_bsa: 'referring this file to BSA', request_documents: 'requesting documents',
  escalate: 'escalating this file', senior_review: 'sending this for senior review',
  approve: 'approving this file', deny: 'denying this file', add_note: 'adding a note',
}
const DEFAULT_VISIBLE: Record<string, string[]> = {
  refer_bsa: ['senior_uw', 'compliance', 'examiner', 'bsa'], deny: ['senior_uw', 'compliance', 'examiner'],
  approve: ['senior_uw', 'compliance', 'examiner'], escalate: ['senior_uw', 'compliance'],
  senior_review: ['senior_uw', 'compliance'], request_documents: ['senior_uw', 'compliance'],
  add_note: ['senior_uw', 'compliance'],
}

export default function ActionModal({ appId, actionType, relatedDecisionId, escalationThread, youName, onClose, onDone }: {
  appId: string; actionType: string; relatedDecisionId?: string | null
  escalationThread?: EscalationThreadItem[]; youName?: string | null
  onClose: () => void; onDone: (a: LoanAction) => void
}) {
  const [category, setCategory] = useState('')
  const [text, setText] = useState('')
  const [visible, setVisible] = useState<Set<string>>(new Set(DEFAULT_VISIBLE[actionType] ?? ['senior_uw', 'compliance']))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [seniorUWName, setSeniorUWName] = useState<string | null>(null)
  // Collapse the history when it's long; keep short threads open.
  const [histOpen, setHistOpen] = useState((escalationThread?.length ?? 0) <= 2)
  const len = text.trim().length
  const ready = len >= 25 && !busy

  // Escalate / senior review get assigned to the senior UW — show who.
  useEffect(() => {
    if (actionType !== 'escalate' && actionType !== 'senior_review') return
    let alive = true
    fetch(`/api/accord/loans/${encodeURIComponent(appId)}/senior-uw`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d?.name) setSeniorUWName(d.name) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [actionType, appId])

  function toggleAud(a: string) {
    setVisible((prev) => { const next = new Set(prev); next.has(a) ? next.delete(a) : next.add(a); return next })
  }
  async function confirm() {
    if (!ready) return
    setBusy(true); setErr(null)
    try {
      const a = await createLoanAction(appId, {
        action_type: actionType, reason_category: category || 'other', reason_text: text.trim(),
        related_decision_id: relatedDecisionId ?? null, visible_to: [...visible],
      })
      onDone(a)
    } catch {
      setErr('Could not record the action — please try again.')
      setBusy(false)
    }
  }

  return (
    <Modal title={`You are ${ACTION_PHRASE[actionType] ?? 'acting on this file'}`} onClose={onClose}>
      <div className="space-y-4 text-sm">
        {(actionType === 'escalate' || actionType === 'senior_review') && (escalationThread?.length ?? 0) > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-3">
            <button
              type="button"
              onClick={() => setHistOpen((v) => !v)}
              className="flex w-full items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-amber-800"
            >
              <span>Prior escalation history ({escalationThread!.length})</span>
              <span className="normal-case">{histOpen ? 'Hide ▲' : 'Show ▼'}</span>
            </button>
            {histOpen && (
              <div className="mt-2">
                <EscalationThread items={escalationThread!} youName={youName} />
                <p className="mt-2.5 border-t border-amber-200 pt-2 text-xs font-medium text-amber-800">You are re-escalating this loan.</p>
              </div>
            )}
          </div>
        )}
        {(actionType === 'escalate' || actionType === 'senior_review') && seniorUWName && (
          <p className="-mt-2 mb-2 text-xs text-slate-400">→ Will be assigned to: {seniorUWName}</p>
        )}
        {actionType !== 'add_note' && (
          <div>
            <div className="mb-1 font-medium text-slate-700">Reason category</div>
            <div className="grid grid-cols-2 gap-1.5">
              {CATEGORIES.map(([k, label]) => (
                <label key={k} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 ${category === k ? 'border-brand bg-brand-light/30' : 'border-slate-200'}`}>
                  <input type="radio" name="cat" checked={category === k} onChange={() => setCategory(k)} className="accent-brand" />
                  {label}
                </label>
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="font-medium text-slate-700">{actionType === 'add_note' ? 'Note' : 'Your reasoning'} <span className="text-red-500">*</span></span>
            <span className={`text-xs ${len < 25 ? 'text-slate-400' : 'text-green-600'}`}>{len}/25 min</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder="Explain your reasoning — what you found and why you're taking this action…"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-brand"
          />
        </div>

        <div>
          <div className="mb-1 font-medium text-slate-700">Visible to</div>
          <div className="flex flex-wrap gap-2">
            {AUDIENCES.map((a) => (
              <label key={a} className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${visible.has(a) ? 'border-brand bg-brand-light/30 text-brand-dark' : 'border-slate-200 text-slate-500'}`}>
                <input type="checkbox" checked={visible.has(a)} onChange={() => toggleAud(a)} className="accent-brand" />
                {AUD_LABEL[a]}
              </label>
            ))}
          </div>
        </div>

        {err && <p className="text-sm font-medium text-red-600">{err}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={confirm} disabled={!ready} title={len < 25 ? 'Add at least 25 characters of reasoning' : undefined} className="rounded-lg bg-brand px-4 py-1.5 font-semibold text-white hover:bg-brand-dark disabled:opacity-40">
            {busy ? 'Recording…' : actionType === 'add_note' ? 'Add note' : 'Confirm'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
