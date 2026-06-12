import { useEffect, useState } from 'react'
import Modal from './Modal'
import { createAttentionRequest, fetchTeammates, type TeammateLite } from '../api/client'

const PERSONAS: Array<{ id: string; name: string }> = [
  { id: 'credit_assessment', name: 'Credit Underwriter' },
  { id: 'fraud_screening', name: 'Fraud Analyst' },
  { id: 'compliance_check', name: 'Compliance Officer' },
  { id: 'employment_reconciliation', name: 'Employment Specialist' },
  { id: 'income_verification', name: 'Income Underwriter' },
  { id: 'ltv_assessment', name: 'Collateral Analyst' },
  { id: 'dti_calculation', name: 'DTI Calculator' },
  { id: 'product_eligibility', name: 'Product Specialist' },
  { id: 'rate_pricing', name: 'Pricing Analyst' },
  { id: 'underwriting_decision', name: 'Senior Underwriter' },
  { id: 'approval_routing', name: 'Loan Ops Router' },
  { id: 'closing_readiness', name: 'Closer' },
]

export default function AttentionModal({
  appId,
  onClose,
  onSent,
}: {
  appId: string
  onClose: () => void
  onSent: () => void
}) {
  const [decision, setDecision] = useState('')
  const [toUser, setToUser] = useState('')
  const [message, setMessage] = useState('')
  const [priority, setPriority] = useState('normal')
  const [users, setUsers] = useState<TeammateLite[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchTeammates().then((d) => setUsers(d.users)).catch(() => undefined)
  }, [])

  async function submit() {
    setBusy(true)
    try {
      await createAttentionRequest({
        application_id: appId,
        decision_id: decision || undefined,
        to_user_id: toUser,
        message,
        priority,
      })
      onSent()
    } finally {
      setBusy(false)
    }
  }

  const sel = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand'
  return (
    <Modal title="Request internal review" onClose={onClose}>
      <label className="mb-1 block text-xs font-medium text-slate-500">Which decision needs revisiting?</label>
      <select value={decision} onChange={(e) => setDecision(e.target.value)} className={`mb-3 ${sel}`}>
        <option value="">— Select a decision —</option>
        {PERSONAS.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-slate-500">Assign to</label>
      <select value={toUser} onChange={(e) => setToUser(e.target.value)} className={`mb-3 ${sel}`}>
        <option value="">— Select a teammate —</option>
        {users.map((u) => (
          <option key={u.user_id} value={u.user_id}>{u.name} ({u.role.replace(/_/g, ' ')})</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-slate-500">What do you need?</label>
      <textarea
        rows={3}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        className={`mb-3 ${sel}`}
        placeholder="Describe what you need them to look at…"
      />

      <label className="mb-1 block text-xs font-medium text-slate-500">Priority</label>
      <select value={priority} onChange={(e) => setPriority(e.target.value)} className={`mb-4 ${sel}`}>
        <option value="normal">Normal</option>
        <option value="urgent">Urgent</option>
      </select>

      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
        <button
          onClick={submit}
          disabled={busy || !toUser || !message.trim()}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
        >
          {busy ? 'Submitting…' : 'Submit request'}
        </button>
      </div>
    </Modal>
  )
}
