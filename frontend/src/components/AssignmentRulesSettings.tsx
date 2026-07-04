import { useEffect, useState } from 'react'
import {
  fetchAssignmentRules, createAssignmentRule, toggleAssignmentRule,
  type AssignmentRule, type NewAssignmentRule,
} from '../api/client'

const ROLES = ['senior_uw', 'underwriter', 'compliance']
const prettyRole = (r: string) => r.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
const money = (n: number | null) => (n == null ? '—' : `$${n.toLocaleString()}`)

const EMPTY: NewAssignmentRule = {
  rule_name: '', priority: 0, min_loan_amount: null, max_loan_amount: null,
  loan_type: null, min_fraud_score: null, min_ltv: null,
  assign_to_role: 'senior_uw', assign_to_user_id: null,
}

// One condition summarized for the table (only the conditions that are set).
function conditionSummary(r: AssignmentRule): string {
  const parts: string[] = []
  if (r.min_loan_amount != null) parts.push(`amount ≥ ${money(r.min_loan_amount)}`)
  if (r.max_loan_amount != null) parts.push(`amount ≤ ${money(r.max_loan_amount)}`)
  if (r.loan_type) parts.push(`type = ${r.loan_type}`)
  if (r.min_fraud_score != null) parts.push(`fraud ≥ ${r.min_fraud_score}`)
  if (r.min_ltv != null) parts.push(`LTV ≥ ${r.min_ltv}`)
  return parts.length ? parts.join(' AND ') : 'any loan'
}

export default function AssignmentRulesSettings() {
  const [rules, setRules] = useState<AssignmentRule[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<NewAssignmentRule>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = () => fetchAssignmentRules().then((d) => setRules(d.rules)).catch(() => setErr('Could not load rules')).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  async function toggle(r: AssignmentRule) {
    // optimistic
    setRules((prev) => prev.map((x) => x.rule_id === r.rule_id ? { ...x, is_active: !x.is_active } : x))
    try { await toggleAssignmentRule(r.rule_id, !r.is_active) } catch { load() }
  }

  const num = (v: string): number | null => (v.trim() === '' ? null : Number(v))

  async function submit() {
    if (!form.rule_name.trim()) { setErr('Rule name is required'); return }
    setBusy(true); setErr(null)
    try {
      await createAssignmentRule({ ...form, loan_type: form.loan_type?.trim() || null })
      setForm(EMPTY); setAdding(false); load()
    } catch {
      setErr('Could not create rule')
    } finally { setBusy(false) }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Assignment rules</h2>
          <p className="text-sm text-slate-500">Route loans directly to a role at intake based on loan characteristics — highest priority match wins. No deploy needed.</p>
        </div>
        <button onClick={() => { setAdding((v) => !v); setErr(null) }} className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">
          {adding ? 'Cancel' : '+ Add rule'}
        </button>
      </div>

      {adding && (
        <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3 sm:grid-cols-3">
          <label className="col-span-2 sm:col-span-1"><span className="mb-0.5 block text-xs text-slate-500">Rule name</span>
            <input value={form.rule_name} onChange={(e) => setForm({ ...form, rule_name: e.target.value })} placeholder="Jumbo to Senior UW" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Priority</span>
            <input type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) || 0 })} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Assign to role</span>
            <select value={form.assign_to_role} onChange={(e) => setForm({ ...form, assign_to_role: e.target.value })} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand">
              {ROLES.map((r) => <option key={r} value={r}>{prettyRole(r)}</option>)}
            </select></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Min loan amount</span>
            <input type="number" value={form.min_loan_amount ?? ''} onChange={(e) => setForm({ ...form, min_loan_amount: num(e.target.value) })} placeholder="766550" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Max loan amount</span>
            <input type="number" value={form.max_loan_amount ?? ''} onChange={(e) => setForm({ ...form, max_loan_amount: num(e.target.value) })} placeholder="—" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Loan type</span>
            <input value={form.loan_type ?? ''} onChange={(e) => setForm({ ...form, loan_type: e.target.value || null })} placeholder="JUMBO / NON_QM" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Min fraud score</span>
            <input type="number" step="0.01" value={form.min_fraud_score ?? ''} onChange={(e) => setForm({ ...form, min_fraud_score: num(e.target.value) })} placeholder="0.75" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <label><span className="mb-0.5 block text-xs text-slate-500">Min LTV</span>
            <input type="number" step="0.1" value={form.min_ltv ?? ''} onChange={(e) => setForm({ ...form, min_ltv: num(e.target.value) })} placeholder="—" className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand" /></label>
          <div className="col-span-2 flex items-end sm:col-span-1">
            <button onClick={submit} disabled={busy} className="w-full rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40">{busy ? 'Saving…' : 'Save rule'}</button>
          </div>
        </div>
      )}

      {err && <p className="mt-2 text-sm font-medium text-red-600">{err}</p>}

      <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Priority</th>
              <th className="px-3 py-2 text-left">Rule</th>
              <th className="px-3 py-2 text-left">Conditions (AND)</th>
              <th className="px-3 py-2 text-left">Assign to</th>
              <th className="px-3 py-2 text-left">Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-400">Loading…</td></tr>
            ) : rules.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-400">No assignment rules yet — add one above.</td></tr>
            ) : rules.map((r) => (
              <tr key={r.rule_id} className={r.is_active ? '' : 'opacity-50'}>
                <td className="px-3 py-2 font-mono text-slate-500">{r.priority}</td>
                <td className="px-3 py-2 font-medium text-slate-800">{r.rule_name}</td>
                <td className="px-3 py-2 text-slate-600">{conditionSummary(r)}</td>
                <td className="px-3 py-2 capitalize text-slate-700">{prettyRole(r.assign_to_role)}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => toggle(r)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition ${r.is_active ? 'bg-green-500' : 'bg-slate-300'}`}
                    aria-label={r.is_active ? 'Deactivate' : 'Activate'}
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${r.is_active ? 'translate-x-4' : 'translate-x-1'}`} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
