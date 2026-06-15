import { useState } from 'react'
import Modal from '../Modal'
import { createLoanAction, type LoanAction } from '../../api/client'

export default function EmailComposerModal({
  appId,
  to,
  subject,
  body,
  onDone, // called after the action is logged — parent refreshes the action list
  onClose,
}: {
  appId: string
  to: string
  subject: string
  body: string
  onDone: (a: LoanAction) => void
  onClose: () => void
}) {
  const [editableBody, setEditableBody] = useState(body)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // One action: copy the email to the clipboard AND log the request_documents
  // action (the document list is the reasoning). Then auto-close.
  async function copyAndLog() {
    if (busy || done) return
    setBusy(true)
    setErr(null)
    const full = `To: ${to}\nSubject: ${subject}\n\n${editableBody}`
    try {
      await navigator.clipboard.writeText(full)
    } catch {
      /* clipboard blocked — still log the action */
    }
    try {
      const a = await createLoanAction(appId, {
        action_type: 'request_documents',
        reason_category: 'documentation_gap',
        reason_text: editableBody.slice(0, 200),
        visible_to: ['senior_uw', 'compliance'],
      })
      setDone(true)
      setTimeout(() => onDone(a), 1500)
    } catch {
      setErr('Could not log the action — please try again.')
      setBusy(false)
    }
  }

  return (
    <Modal title="Request documents — compose email" onClose={onClose} width="max-w-lg">
      <div className="space-y-3 text-sm">
        <div>
          <div className="mb-1 font-medium text-slate-700">To</div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-600">{to || '—'}</div>
        </div>

        <div>
          <div className="mb-1 font-medium text-slate-700">Subject</div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-600">{subject}</div>
        </div>

        <div>
          <div className="mb-1 font-medium text-slate-700">Message</div>
          <textarea
            value={editableBody}
            onChange={(e) => setEditableBody(e.target.value)}
            rows={12}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
          />
        </div>

        {err && <p className="text-sm font-medium text-red-600">{err}</p>}

        <div className="pt-1">
          <button
            onClick={copyAndLog}
            disabled={busy || done}
            className="w-full rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-60"
          >
            {done ? '✓ Email copied · Action logged' : busy ? 'Logging…' : 'Copy email + Log action'}
          </button>
        </div>

        <p className="text-xs text-slate-400">Logging the action creates a permanent record in the audit trail.</p>
      </div>
    </Modal>
  )
}
