import { useState } from 'react'
import Modal from '../Modal'

export default function EmailComposerModal({
  to,
  subject,
  body,
  onContinue, // called after the underwriter is done — opens the ActionModal
  onClose,
}: {
  to: string
  subject: string
  body: string
  onContinue: () => void
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [editableBody, setEditableBody] = useState(body)

  async function handleCopy() {
    const full = `To: ${to}\nSubject: ${subject}\n\n${editableBody}`
    try {
      await navigator.clipboard.writeText(full)
    } catch {
      /* clipboard blocked — still mark as "copied" so the flow can continue */
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
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

        <div className="flex gap-2 pt-1">
          <button
            onClick={handleCopy}
            className="flex-1 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            {copied ? '✓ Copied!' : 'Copy to clipboard'}
          </button>
          <button
            onClick={onContinue}
            className="flex-1 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
          >
            Continue to log action →
          </button>
        </div>

        <p className="text-xs text-slate-400">Logging the action creates a permanent record in the audit trail.</p>
      </div>
    </Modal>
  )
}
