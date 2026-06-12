import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMyQueue, type MyQueueResponse, type QueueCard } from '../api/client'
import { useAuth } from '../context/AuthContext'

function money(v: number | null) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}
const greeting = () => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}
const firstName = (n: string) => n.split(' ')[0]
const prettyType = (t: string | null) =>
  t ? t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '—'

// queue_type/urgency → dot + tag shown on each action card.
function cardTag(c: QueueCard): { dot: string; tag: string; tagCls: string } {
  if (c.queue_type === 'internal_request') return { dot: '🔵', tag: 'INTERNAL REQUEST', tagCls: 'text-blue-700' }
  if (c.urgency === 'urgent') return { dot: '🔴', tag: 'URGENT', tagCls: 'text-red-700' }
  if (c.queue_type === 'returned') return { dot: '🟢', tag: 'RETURNED', tagCls: 'text-green-700' }
  return { dot: '🟡', tag: 'NEEDS ACTION', tagCls: 'text-amber-700' }
}

export default function MyQueue({
  userId,
  readOnly = false,
  onBack,
}: {
  userId?: string
  readOnly?: boolean
  onBack?: () => void
}) {
  const navigate = useNavigate()
  const { user: me } = useAuth()
  const [data, setData] = useState<MyQueueResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openPending, setOpenPending] = useState(false)
  const [openDecided, setOpenDecided] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const act = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetchMyQueue(userId)
      .then((d) => alive && setData(d))
      .catch(() => alive && setError('Could not load your queue.'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [userId])

  if (loading) return <div className="p-12 text-center text-slate-400">Loading queue…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!data) return null

  const canAct = !readOnly && me?.role !== 'viewer'

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      {/* Header */}
      <div className="mb-5 flex items-start justify-between">
        <div>
          {onBack && (
            <button onClick={onBack} className="mb-1 text-sm font-medium text-brand hover:underline">
              ← Back to team
            </button>
          )}
          <h1 className="text-2xl font-semibold text-slate-900">
            {readOnly ? `${data.user.name}'s queue` : `${greeting()}, ${firstName(data.user.name)}`}
          </h1>
          <p className="text-sm capitalize text-slate-500">{data.user.role.replace(/_/g, ' ')}</p>
        </div>
        <div className="flex items-center gap-1 text-sm text-slate-500">
          🔔 <span>{data.counts.active} need action</span>
        </div>
      </div>

      {/* Count cards */}
      <div className="mb-6 grid grid-cols-3 gap-3">
        {[
          { label: 'Need my action', n: data.counts.active, accent: 'text-red-600' },
          { label: 'Pending response', n: data.counts.pending, accent: 'text-amber-600' },
          { label: 'Decided this week', n: data.counts.decided, accent: 'text-green-600' },
        ].map((c) => (
          <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{c.label}</div>
            <div className={`mt-1 text-3xl font-semibold ${c.accent}`}>{c.n}</div>
          </div>
        ))}
      </div>

      {/* NEED MY ACTION */}
      <SectionHeader label="Need my action" n={data.active.length} />
      {data.active.length === 0 ? (
        <p className="mb-6 text-sm text-slate-400">Nothing needs your action right now. 🎉</p>
      ) : (
        <div className="mb-8 space-y-3">
          {data.active.map((c) => (
            <ActionCard key={c.application_id} c={c} canAct={canAct} onReview={() => navigate(`/pipeline/${c.application_id}`)} onAct={act} />
          ))}
        </div>
      )}

      {/* PENDING RESPONSE (collapsible) */}
      <CollapsibleHeader label="Pending response" n={data.pending.length} open={openPending} onToggle={() => setOpenPending((v) => !v)} />
      {openPending && (
        <div className="mb-8 mt-3 space-y-2">
          {data.pending.map((c) => (
            <PendingCard key={c.application_id} c={c} canAct={canAct} onAct={act} />
          ))}
          {data.pending.length === 0 && <p className="text-sm text-slate-400">No pending borrower requests.</p>}
        </div>
      )}

      {/* DECIDED THIS WEEK (collapsible) */}
      <CollapsibleHeader label="Decided this week" n={data.decided.length} open={openDecided} onToggle={() => setOpenDecided((v) => !v)} />
      {openDecided && (
        <div className="mt-3 space-y-1.5">
          {data.decided.map((c) => (
            <button
              key={c.application_id}
              onClick={() => navigate(`/pipeline/${c.application_id}`)}
              className="flex w-full items-center gap-3 rounded-lg border border-slate-100 bg-white px-4 py-2 text-left text-sm hover:bg-slate-50"
            >
              <span>{c.status === 'funded' ? '✅' : '✅'}</span>
              <span className="font-medium text-slate-800">{c.borrower_name}</span>
              <span className="text-slate-400">·</span>
              <span className="text-slate-600">{money(c.loan_amount)}</span>
              <span className="ml-auto capitalize text-slate-400">{c.status}</span>
            </button>
          ))}
          {data.decided.length === 0 && <p className="text-sm text-slate-400">Nothing decided this week.</p>}
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}

function SectionHeader({ label, n }: { label: string; n: number }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label} ({n})
      </h2>
      <div className="h-px flex-1 bg-slate-200" />
    </div>
  )
}
function CollapsibleHeader({ label, n, open, onToggle }: { label: string; n: number; open: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} className="flex w-full items-center gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label} ({n})
      </h2>
      <span className="text-[10px] text-slate-400">{open ? '▲ click to collapse' : '▼ click to expand'}</span>
      <div className="h-px flex-1 bg-slate-200" />
    </button>
  )
}

function ActionCard({
  c, canAct, onReview, onAct,
}: {
  c: QueueCard
  canAct: boolean
  onReview: () => void
  onAct: (m: string) => void
}) {
  const { dot, tag, tagCls } = cardTag(c)
  const internal = c.queue_type === 'internal_request' && c.attention_request
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-x-2 text-sm">
        <span>{dot}</span>
        <span className="font-semibold text-slate-900">{c.borrower_name}</span>
        <span className="text-slate-400">·</span>
        <span className="text-slate-700">{money(c.loan_amount)}</span>
        <span className="text-slate-400">·</span>
        <span className="capitalize text-slate-500">{prettyType(c.loan_type)}</span>
        <span className={`ml-1 text-xs font-bold ${tagCls}`}>{tag}</span>
      </div>

      {internal ? (
        <div className="mt-2 rounded-lg bg-blue-50 px-3 py-2 text-sm">
          <div className="text-xs font-medium text-blue-700">From: {c.attention_request!.from}</div>
          <div className="text-slate-700">"{c.attention_request!.message}"</div>
          <div className="mt-0.5 text-xs capitalize text-slate-500">Priority: {c.attention_request!.priority}</div>
        </div>
      ) : (
        <div className="mt-2 space-y-1 text-sm">
          <div className="text-slate-800"><span className="font-medium text-slate-500">AI found:</span> {c.ai_finding}</div>
          <div className="text-slate-700"><span className="font-medium text-slate-500">Recommendation:</span> "{c.ai_recommendation}"</div>
          <div className="text-slate-500"><span className="font-medium">What AI saw:</span> {c.ai_data_sources}</div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
        <span>In queue: {c.days_in_queue === 0 ? 'today' : `${c.days_in_queue} days`}</span>
        {c.rate_lock_days != null && (
          <span className={c.rate_lock_days <= 5 ? 'font-medium text-amber-600' : ''}>
            Rate lock: {c.rate_lock_days} days remaining {c.rate_lock_days <= 5 ? '⚠' : ''}
          </span>
        )}
      </div>

      {canAct && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={onReview} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">
            {internal ? 'Review request' : 'Review'}
          </button>
          {!internal && (
            <>
              <button onClick={() => onAct('Quick approved (demo)')} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Quick approve</button>
              <button onClick={() => onAct('Info requested from borrower (demo)')} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Request info</button>
              <button onClick={() => onAct('Loan denied (demo)')} className="rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50">Deny</button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function PendingCard({ c, canAct, onAct }: { c: QueueCard; canAct: boolean; onAct: (m: string) => void }) {
  const due = c.due_date ? new Date(c.due_date) : null
  const daysLeft = due ? Math.ceil((due.getTime() - Date.now()) / 86400000) : null
  const overdue = daysLeft != null && daysLeft <= 1
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-2">
        <span>📧</span>
        <span className="font-semibold text-slate-900">{c.borrower_name}</span>
        <span className="text-slate-400">·</span>
        <span className="text-slate-700">{money(c.loan_amount)}</span>
        {c.requesting && c.requesting.length > 0 && (
          <span className="text-slate-500">· Requesting: {c.requesting.join(', ')}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
        {c.due_date && <span>Due: {new Date(c.due_date).toLocaleDateString()}</span>}
        {daysLeft != null && (
          <span className={overdue ? 'font-semibold text-red-600' : ''}>
            · {daysLeft <= 0 ? 'OVERDUE' : `${daysLeft} day${daysLeft === 1 ? '' : 's'} remaining`} {overdue ? '⚠' : ''}
          </span>
        )}
      </div>
      {canAct && (
        <div className="mt-2 flex gap-2">
          <button onClick={() => onAct('Simulated borrower response (demo)')} className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Simulate response</button>
          <button onClick={() => onAct('Reminder sent (demo)')} className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Send reminder</button>
        </div>
      )}
    </div>
  )
}
