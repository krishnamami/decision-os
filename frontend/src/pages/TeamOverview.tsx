import { useEffect, useState } from 'react'
import { fetchTeam, type TeamMember, type TeamResponse } from '../api/client'

function money(v: number | null) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}
const prettyRole = (r: string) => r.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

// loan_status → chip dot.
const STATUS_DOT: Record<string, string> = {
  active: '🟡', halted: '🔴', pending_borrower: '📧', decided: '✅', funded: '✅',
}

export default function TeamOverview({ onViewUser }: { onViewUser: (m: { id: string; name: string }) => void }) {
  const [data, setData] = useState<TeamResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchTeam()
      .then((d) => alive && setData(d))
      .catch(() => alive && setError('Could not load the team overview.'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <div className="p-12 text-center text-slate-400">Loading team…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!data) return null

  const t = data.totals
  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Your team's pipeline</h1>
        <button
          onClick={() => {
            setToast('Reassignment is coming soon (demo)')
            setTimeout(() => setToast(null), 2500)
          }}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Reassign loans
        </button>
      </div>

      {/* Team totals */}
      <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        Team totals: <span className="font-semibold text-slate-900">{t.active} active</span> ·{' '}
        <span className="font-semibold text-slate-900">{t.pending} pending</span> ·{' '}
        <span className="font-semibold text-slate-900">{t.decided} decided</span> this month
      </div>

      <div className="space-y-3">
        {data.members.map((m) => (
          <MemberCard key={m.user_id} m={m} onView={() => onViewUser({ id: m.user_id, name: m.name })} />
        ))}
      </div>

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}

function MemberCard({ m, onView }: { m: TeamMember; onView: () => void }) {
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
          <button onClick={onView} className="rounded-lg border border-slate-200 px-3 py-1 text-sm font-medium text-brand hover:bg-slate-50">
            View
          </button>
        </div>
      </div>

      {m.loans.length > 0 ? (
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
      ) : (
        <div className="mt-3 text-xs text-slate-400">No loans assigned.</div>
      )}
    </div>
  )
}
