import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMyQueue, simulateResponse, type MyQueueResponse, type QueueCard } from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import RequestDocsModal from '../components/modals/RequestDocsModal'

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

const FILTER_LABEL: Record<'active' | 'pending' | 'decided', string> = {
  active: 'Need my action', pending: 'Pending response', decided: 'Decided this week',
}

// queue_type/urgency → dot + tag shown on each action card.
function cardTag(c: QueueCard): { dot: string; tag: string; tagCls: string } {
  if (c.queue_type === 'internal_request') return { dot: '🔵', tag: 'INTERNAL REQUEST', tagCls: 'text-blue-700' }
  // Returned (borrower responded) wins over urgency — it's the salient new state.
  if (c.queue_type === 'returned') return { dot: '🟢', tag: 'RETURNED', tagCls: 'text-green-700' }
  if (c.urgency === 'urgent') return { dot: '🔴', tag: 'URGENT', tagCls: 'text-red-700' }
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
  const { effectiveUser: me } = useAuth()
  const [data, setData] = useState<MyQueueResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openPending, setOpenPending] = useState(false)
  const [openDecided, setOpenDecided] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [simCard, setSimCard] = useState<QueueCard | null>(null)
  const [docsCard, setDocsCard] = useState<QueueCard | null>(null)
  const [activeFilter, setActiveFilter] = useState<'active' | 'pending' | 'decided' | null>(null)

  const act = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }
  function afterSimulate() {
    setSimCard(null)
    act('Borrower responded — loan is back in your queue 🟢')
    setReloadKey((k) => k + 1)
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
  }, [userId, reloadKey])

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
          🔔 <span>{data.active.length} need action</span>
        </div>
      </div>

      {/* Count cards — click to filter the queue to that bucket */}
      <div className="mb-6 grid grid-cols-3 gap-3">
        {([
          { key: 'active', label: 'Need my action', n: data.active.length, accent: 'text-red-600', ring: 'ring-red-500' },
          { key: 'pending', label: 'Pending response', n: data.pending.length, accent: 'text-amber-600', ring: 'ring-amber-500' },
          { key: 'decided', label: 'Decided this week', n: data.decided.length, accent: 'text-green-600', ring: 'ring-green-500' },
        ] as const).map((c) => (
          <button
            key={c.key}
            onClick={() => setActiveFilter((f) => (f === c.key ? null : c.key))}
            title="Click to filter the queue"
            className={`rounded-xl border bg-white p-4 text-left transition hover:border-brand/40 hover:bg-slate-50 ${activeFilter === c.key ? `border-transparent ring-2 ${c.ring}` : 'border-slate-200'}`}
          >
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{c.label}</div>
            <div className={`mt-1 text-3xl font-semibold ${c.accent}`}>{c.n}</div>
          </button>
        ))}
      </div>

      {/* Active-filter banner */}
      {activeFilter && (
        <div className="mb-4 flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm">
          <span className="font-medium text-slate-700">
            Filtered: {FILTER_LABEL[activeFilter]} ({data[activeFilter].length})
          </span>
          <button onClick={() => setActiveFilter(null)} className="ml-auto rounded px-1.5 font-medium text-slate-500 hover:text-slate-800" title="Clear filter">✕ Clear</button>
        </div>
      )}

      {/* When a filter is active, show ONLY that bucket; else the full layout. */}
      {activeFilter ? (
        data[activeFilter].length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
            <p className="text-sm text-slate-500">No loans in this category right now.</p>
            <button onClick={() => setActiveFilter(null)} className="mt-3 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Show all loans</button>
          </div>
        ) : activeFilter === 'active' ? (
          <div className="space-y-3">
            {data.active.map((c) => (
              <ActionCard key={c.application_id} c={c} canAct={canAct} onReview={() => navigate(`/pipeline/${c.application_id}${c.attention_request ? `?request_id=${c.attention_request.request_id}` : ''}`)} onAct={act} onRequestDocs={() => setDocsCard(c)} />
            ))}
          </div>
        ) : activeFilter === 'pending' ? (
          <div className="space-y-2">
            {data.pending.map((c) => (
              <PendingCard key={c.application_id} c={c} canAct={canAct} onAct={act} onSimulate={() => setSimCard(c)} />
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            {data.decided.map((c) => (
              <DecidedRow key={c.application_id} c={c} onClick={() => navigate(`/pipeline/${c.application_id}`)} />
            ))}
          </div>
        )
      ) : (
        <>
          {/* NEED MY ACTION */}
          <SectionHeader label="Need my action" n={data.active.length} />
          {data.active.length === 0 ? (
            <p className="mb-6 text-sm text-slate-400">Nothing needs your action right now. 🎉</p>
          ) : (
            <div className="mb-8 space-y-3">
              {data.active.map((c) => (
                <ActionCard key={c.application_id} c={c} canAct={canAct} onReview={() => navigate(`/pipeline/${c.application_id}${c.attention_request ? `?request_id=${c.attention_request.request_id}` : ''}`)} onAct={act} onRequestDocs={() => setDocsCard(c)} />
              ))}
            </div>
          )}

          {/* PENDING RESPONSE (collapsible) */}
          <CollapsibleHeader label="Pending response" n={data.pending.length} open={openPending} onToggle={() => setOpenPending((v) => !v)} />
          {openPending && (
            <div className="mb-8 mt-3 space-y-2">
              {data.pending.map((c) => (
                <PendingCard key={c.application_id} c={c} canAct={canAct} onAct={act} onSimulate={() => setSimCard(c)} />
              ))}
              {data.pending.length === 0 && <p className="text-sm text-slate-400">No pending borrower requests.</p>}
            </div>
          )}

          {/* DECIDED THIS WEEK (collapsible) */}
          <CollapsibleHeader label="Decided this week" n={data.decided.length} open={openDecided} onToggle={() => setOpenDecided((v) => !v)} />
          {openDecided && (
            <div className="mt-3 space-y-1.5">
              {data.decided.map((c) => (
                <DecidedRow key={c.application_id} c={c} onClick={() => navigate(`/pipeline/${c.application_id}`)} />
              ))}
              {data.decided.length === 0 && <p className="text-sm text-slate-400">Nothing decided this week.</p>}
            </div>
          )}
        </>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}

      {simCard && <SimulateResponseModal card={simCard} onClose={() => setSimCard(null)} onDone={afterSimulate} />}
      {docsCard && (
        <RequestDocsModal
          applicationId={docsCard.application_id}
          borrowerName={docsCard.borrower_name}
          onClose={() => setDocsCard(null)}
          onDone={(msg) => { setDocsCard(null); act(msg) }}
        />
      )}
    </div>
  )
}

function SimulateResponseModal({ card, onClose, onDone }: { card: QueueCard; onClose: () => void; onDone: () => void }) {
  const requested = card.requesting ?? []
  const [checked, setChecked] = useState<Set<string>>(new Set(requested))
  const [busy, setBusy] = useState(false)
  function toggle(d: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      next.has(d) ? next.delete(d) : next.add(d)
      return next
    })
  }
  async function submit() {
    setBusy(true)
    try {
      await simulateResponse(card.application_id, [...checked])
      onDone()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title="Simulate borrower response" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">
        Simulate that <span className="font-medium text-slate-800">{card.borrower_name}</span> uploaded documents — the loan
        returns to the assignee's queue.
      </p>
      {requested.length > 0 ? (
        <>
          <div className="mb-1 text-xs font-medium text-slate-500">Which documents?</div>
          <div className="mb-4 space-y-1">
            {requested.map((d) => (
              <label key={d} className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={checked.has(d)} onChange={() => toggle(d)} className="accent-brand" />
                {d}
              </label>
            ))}
          </div>
        </>
      ) : (
        <p className="mb-4 text-sm text-slate-400">No specific documents were requested — this marks the loan as responded.</p>
      )}
      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
        <button onClick={submit} disabled={busy} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40">
          {busy ? 'Simulating…' : 'Simulate response'}
        </button>
      </div>
    </Modal>
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
  c, canAct, onReview, onAct, onRequestDocs,
}: {
  c: QueueCard
  canAct: boolean
  onReview: () => void
  onAct: (m: string) => void
  onRequestDocs: () => void
}) {
  const { dot, tag, tagCls } = cardTag(c)
  const internal = c.queue_type === 'internal_request' && c.attention_request
  const returned = c.queue_type === 'returned'
  const sla = c.sla_days ?? 5
  const days = c.days_in_queue ?? 0
  const overSla = days > sla
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-4 ${returned ? 'border-l-4 border-l-green-500' : ''}`}>
      <div className="flex flex-wrap items-center gap-x-2 text-sm">
        <span>{dot}</span>
        <span className="font-semibold text-slate-900">{c.borrower_name}</span>
        <span className="text-slate-400">·</span>
        <span className="text-slate-700">{money(c.loan_amount)}</span>
        <span className="text-slate-400">·</span>
        <span className="capitalize text-slate-500">{prettyType(c.loan_type)}</span>
        <span className={`ml-1 text-xs font-bold ${tagCls}`}>{tag}</span>
        {c.senior_review && (
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium" style={{ background: '#faeeda', color: '#633806' }}>
            ⚑ Senior review
          </span>
        )}
      </div>

      {internal ? (
        <div className="mt-2 rounded-lg bg-blue-50 px-3 py-2 text-sm">
          <div className="text-xs font-medium text-blue-700">From: {c.attention_request!.from}</div>
          <div className="text-slate-700">"{c.attention_request!.message}"</div>
          <div className="mt-0.5 text-xs capitalize text-slate-500">Priority: {c.attention_request!.priority}</div>
        </div>
      ) : (
        <div className="mt-2 space-y-1 text-sm">
          <div className="text-slate-800"><span className="font-medium text-slate-500">Key finding:</span> {c.ai_finding}</div>
          <div className="text-slate-700"><span className="font-medium text-slate-500">AI suggests:</span> "{c.ai_recommendation}"</div>
          <div className="text-slate-500"><span className="font-medium">Based on:</span> {c.ai_data_sources}</div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
        <span className={overSla ? 'font-medium text-amber-600' : ''}>
          In queue: {days} of {sla} days{overSla ? ` ⚠ ${days - sla} ${days - sla === 1 ? 'day' : 'days'} over SLA` : ''}
        </span>
        {c.rate_lock_days != null && (
          <span className={c.rate_lock_days <= 5 ? 'font-medium text-amber-600' : ''}>
            Rate lock: {c.rate_lock_days} days remaining {c.rate_lock_days <= 5 ? '⚠' : ''}
          </span>
        )}
      </div>

      {canAct && (
        <div className="mt-3 flex flex-wrap gap-2">
          {internal ? (
            <button onClick={onReview} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Review request</button>
          ) : c.category === 'clean' ? (
            // Clean file: quick approve is the primary (green) action.
            <>
              <button onClick={() => onAct('Quick approved (demo)')} className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-green-700">✅ Quick approve</button>
              <button onClick={onReview} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Review</button>
            </>
          ) : (
            // Blocked file: review first; context action; NO quick approve.
            <>
              <button onClick={onReview} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Review</button>
              {c.category === 'fraud' ? (
                <button onClick={() => onAct('Referred to BSA officer (demo)')} className="rounded-lg border border-amber-200 px-3 py-1.5 text-sm font-medium text-amber-700 hover:bg-amber-50">⚠ Refer to BSA</button>
              ) : (
                <button onClick={onRequestDocs} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">📧 Request docs</button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function DecidedRow({ c, onClick }: { c: QueueCard; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg border border-slate-100 bg-white px-4 py-2 text-left text-sm hover:bg-slate-50"
    >
      <span>✅</span>
      <span className="font-medium text-slate-800">{c.borrower_name}</span>
      <span className="text-slate-400">·</span>
      <span className="text-slate-600">{money(c.loan_amount)}</span>
      <span className="ml-auto capitalize text-slate-400">{c.status}</span>
    </button>
  )
}

function PendingCard({ c, canAct, onAct, onSimulate }: { c: QueueCard; canAct: boolean; onAct: (m: string) => void; onSimulate: () => void }) {
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
          <button onClick={onSimulate} className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Simulate response</button>
          <button onClick={() => onAct('Reminder sent (demo)')} className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">Send reminder</button>
        </div>
      )}
    </div>
  )
}
