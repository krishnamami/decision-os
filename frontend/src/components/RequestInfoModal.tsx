import { useMemo, useState } from 'react'
import Modal from './Modal'
import { requestInfo } from '../api/client'

const DOC_OPTIONS = [
  'W2 / tax return (most recent)',
  'Pay stubs (last 30 days)',
  'Bank statements (2 months)',
  'Employment verification letter',
  'Gift letter',
  'Explanation letter',
  "Driver's license",
  'Insurance binder',
]

export default function RequestInfoModal({
  appId,
  defaultEmail,
  onClose,
  onSent,
}: {
  appId: string
  defaultEmail: string
  onClose: () => void
  onSent: () => void
}) {
  const [email, setEmail] = useState(defaultEmail)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [other, setOther] = useState('')
  const [note, setNote] = useState('')
  const [dueDays, setDueDays] = useState(7)
  const [busy, setBusy] = useState(false)

  const items = useMemo(
    () => [...checked, ...(other.trim() ? [other.trim()] : [])],
    [checked, other],
  )
  const autoNote = items.length
    ? `We need the following documents to continue processing your loan application: ${items.join(', ')}.`
    : 'We need a few documents to continue processing your loan application.'

  function toggle(opt: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      next.has(opt) ? next.delete(opt) : next.add(opt)
      return next
    })
  }

  async function send() {
    setBusy(true)
    try {
      const due = new Date(Date.now() + dueDays * 86400000).toISOString().slice(0, 10)
      await requestInfo({ application_id: appId, recipient_email: email, items, note: note || autoNote, due_date: due })
      onSent()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Request more information" onClose={onClose} width="max-w-lg">
      <label className="mb-1 block text-xs font-medium text-slate-500">To</label>
      <input
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
      />

      <div className="mb-1 text-xs font-medium text-slate-500">What do you need?</div>
      <div className="mb-3 grid grid-cols-1 gap-1 sm:grid-cols-2">
        {DOC_OPTIONS.map((opt) => (
          <label key={opt} className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={checked.has(opt)} onChange={() => toggle(opt)} className="accent-brand" />
            {opt}
          </label>
        ))}
        <label className="col-span-full flex items-center gap-2 text-sm text-slate-700">
          Other:
          <input
            value={other}
            onChange={(e) => setOther(e.target.value)}
            className="flex-1 rounded-lg border border-slate-300 px-2 py-1 text-sm outline-none focus:border-brand"
          />
        </label>
      </div>

      <label className="mb-1 block text-xs font-medium text-slate-500">Note to borrower (editable)</label>
      <textarea
        rows={3}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={autoNote}
        className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
      />

      <label className="mb-1 block text-xs font-medium text-slate-500">Due date</label>
      <select
        value={dueDays}
        onChange={(e) => setDueDays(Number(e.target.value))}
        className="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
      >
        <option value={7}>7 days from now</option>
        <option value={14}>14 days from now</option>
        <option value={30}>30 days from now</option>
      </select>

      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
        <button
          onClick={send}
          disabled={busy || items.length === 0}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
        >
          {busy ? 'Sending…' : 'Send request'}
        </button>
      </div>
    </Modal>
  )
}
