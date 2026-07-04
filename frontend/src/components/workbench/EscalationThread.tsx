import type { EscalationThreadItem } from '../../types/accord'

// Icon + phrasing per thread action. Shared by the modal panel, Karen's banner,
// and the audit feed so they read identically.
const ACTION_META: Record<
  string,
  { icon: string; verb: string; tone: string }
> = {
  escalated: { icon: '📤', verb: 'escalated', tone: 'text-slate-700' },
  re_escalated: { icon: '📤', verb: 're-escalated', tone: 'text-slate-700' },
  returned_feedback: { icon: '↩', verb: 'returned feedback', tone: 'text-amber-700' },
  recommend_approval: { icon: '✅', verb: 'recommended approval', tone: 'text-green-700' },
  approved: { icon: '✅', verb: 'approved', tone: 'text-green-700' },
  denied: { icon: '❌', verb: 'denied', tone: 'text-red-700' },
  overridden: { icon: '🔄', verb: 'overrode the decision', tone: 'text-amber-800' },
}

const prettyCat = (c: string) => c.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase())

function fmtTs(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

// Renders the escalate → feedback → re-escalate → decide history, oldest first.
// `youName`, when it matches an item's actor, renders "You …" (used in the
// underwriter's own re-escalation modal).
export default function EscalationThread({
  items, youName,
}: { items: EscalationThreadItem[]; youName?: string | null }) {
  if (!items.length) return null
  return (
    <ol className="space-y-3">
      {items.map((it, i) => {
        const meta = ACTION_META[it.action] ?? { icon: '•', verb: it.action, tone: 'text-slate-700' }
        const who = youName && it.actor_name === youName ? 'You' : it.actor_name
        return (
          <li key={it.event_id ?? i} className="text-xs">
            <div className="flex flex-wrap items-baseline gap-x-1.5 text-slate-400">
              <span>{meta.icon}</span>
              <span>{fmtTs(it.timestamp)}</span>
              {it.time_ago && <span className="text-slate-300">· {it.time_ago}</span>}
            </div>
            <div className={`ml-5 font-medium ${meta.tone}`}>{who} {meta.verb}</div>
            {it.category && (
              <div className="ml-5 text-slate-500">Category: <span className="capitalize">{prettyCat(it.category)}</span></div>
            )}
            {it.message && <p className="ml-5 mt-0.5 italic text-slate-600">“{it.message}”</p>}
          </li>
        )
      })}
    </ol>
  )
}
