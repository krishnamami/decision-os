import { useEffect, useState } from 'react'
import { fetchTeam, reassignLoans, type TeamMember, type TeamResponse } from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'

function money(v: number | null) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}
const prettyRole = (r: string) => r.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
const STATUS_DOT: Record<string, string> = {
  active: '🟡', halted: '🔴', pending_borrower: '📧', decided: '✅', funded: '✅',
}

export default function TeamOverview({ onViewUser }: { onViewUser: (m: { id: string; name: string }) => void }) {
  const { tenant } = useAuth()
  const [data, setData] = useState<TeamResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [reassignFrom, setReassignFrom] = useState<TeamMember | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true
    setLoading(true)
    fetchTeam()
      .then((d) => alive && setData(d))
      .catch(() => alive && setError('Could not load the team overview.'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [reloadKey])

  function fire(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  if (loading) return <div className="p-12 text-center text-slate-400">Loading team…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!data) return null

  const t = data.totals
  const KPIS = [
    { label: 'Active', n: t.active, accent: 'text-amber-600' },
    { label: 'Pending', n: t.pending, accent: 'text-blue-600' },
    { label: 'Decided', n: t.decided, accent: 'text-green-600' },
    { label: 'Avg time', n: `${t.avg_days} days`, accent: 'text-slate-900' },
  ]

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-semibold text-slate-900">
        Your team{tenant?.name ? <span className="text-slate-400"> · {tenant.name}</span> : null}
      </h1>

      {/* Team KPIs */}
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {KPIS.map((c) => (
          <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{c.label}</div>
            <div className={`mt-1 text-2xl font-semibold ${c.accent}`}>{c.n}</div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        {data.members.map((m) => (
          <MemberCard
            key={m.user_id}
            m={m}
            onView={() => onViewUser({ id: m.user_id, name: m.name })}
            onReassign={() => setReassignFrom(m)}
          />
        ))}
      </div>

      {reassignFrom && (
        <ReassignModal
          from={reassignFrom}
          members={data.members}
          onClose={() => setReassignFrom(null)}
          onDone={(n, toName) => {
            setReassignFrom(null)
            fire(`${n} loan${n === 1 ? '' : 's'} transferred from ${reassignFrom.name.split(' ')[0]} to ${toName}`)
            setReloadKey((k) => k + 1)
          }}
        />
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}

function MemberCard({ m, onView, onReassign }: { m: TeamMember; onView: () => void; onReassign: () => void }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">
          {m.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()}
        </span>
        <div>
          <div className="font-semibold text-slate-900">{m.name}</div>
          <div className="text-xs capitalize text-slate-500">{prettyRole(m.role)}</div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
          <span>{m.active} active · {m.pending} pending</span>
          {(m.active > 0 || m.pending > 0) && (
            <button onClick={onReassign} className="rounded-lg border border-slate-200 px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50">Reassign</button>
          )}
          <button onClick={onView} className="rounded-lg border border-slate-200 px-3 py-1 text-sm font-medium text-brand hover:bg-slate-50">View queue</button>
        </div>
      </div>

      {m.loans.length > 0 ? (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            {m.loans.map((l) => (
              <span key={l.application_id} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 px-2.5 py-1 text-xs text-slate-700">
                <span>{STATUS_DOT[l.loan_status] ?? '🟡'}</span>
                <span className="font-medium">{l.borrower_name}</span>
                <span className="text-slate-400">{money(l.loan_amount)}</span>
                <span className="text-slate-400">· {l.days_in_queue === 0 ? 'today' : `${l.days_in_queue}d`}</span>
              </span>
            ))}
          </div>
          {m.oldest_days > 0 && (
            <div className="mt-2 text-xs text-slate-400">Oldest loan in queue: {m.oldest_days} days</div>
          )}
        </>
      ) : (
        <div className="mt-3 text-xs text-slate-400">No loans assigned.</div>
      )}
    </div>
  )
}

function ReassignModal({
  from,
  members,
  onClose,
  onDone,
}: {
  from: TeamMember
  members: TeamMember[]
  onClose: () => void
  onDone: (n: number, toName: string) => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [toUser, setToUser] = useState('')
  const [busy, setBusy] = useState(false)
  const targets = members.filter((m) => m.user_id !== from.user_id)

  function toggle(app: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(app) ? next.delete(app) : next.add(app)
      return next
    })
  }

  async function transfer() {
    setBusy(true)
    try {
      const res = await reassignLoans([...selected], toUser)
      onDone(res.transferred, res.to_name)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Reassign loans from ${from.name}`} onClose={onClose}>
      <div className="mb-1 text-xs font-medium text-slate-500">Select loans</div>
      <div className="mb-4 max-h-56 space-y-1 overflow-y-auto">
        {from.loans.length === 0 && <p className="text-sm text-slate-400">No selectable loans (showing up to 6 in queue).</p>}
        {from.loans.map((l) => (
          <label key={l.application_id} className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm text-slate-700 hover:bg-slate-50">
            <input type="checkbox" checked={selected.has(l.application_id)} onChange={() => toggle(l.application_id)} className="accent-brand" />
            <span>{STATUS_DOT[l.loan_status] ?? '🟡'}</span>
            <span className="font-medium">{l.borrower_name}</span>
            <span className="text-slate-400">{money(l.loan_amount)}</span>
          </label>
        ))}
      </div>

      <label className="mb-1 block text-xs font-medium text-slate-500">Assign to</label>
      <select value={toUser} onChange={(e) => setToUser(e.target.value)} className="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand">
        <option value="">— Select a teammate —</option>
        {targets.map((m) => (
          <option key={m.user_id} value={m.user_id}>{m.name} ({prettyRole(m.role)})</option>
        ))}
      </select>

      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
        <button
          onClick={transfer}
          disabled={busy || selected.size === 0 || !toUser}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
        >
          {busy ? 'Transferring…' : `Transfer ${selected.size || ''}`}
        </button>
      </div>
    </Modal>
  )
}
