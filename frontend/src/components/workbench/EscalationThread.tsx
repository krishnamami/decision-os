import type { EscalationThreadItem } from '../../types/accord'

// Icon + phrasing per thread action. Keeps the modal panel and Karen's banner
// visually identical.
const ACTION_META: Record<
  string,
  { icon: string; verb: string; tone: string }
> = {
  escalated: { icon: '📤', verb: 'escalated', tone: 'text-slate-700' },
  re_escalated: { icon: '📤', verb: 're-escalated', tone: 'text-slate-700' },
  returned_feedback: { icon: '↩', verb: 'returned with feedback', tone: 'text-amber-700' },
  approved: { icon: '✅', verb: 'approved', tone: 'text-green-700' },
  denied: { icon: '⛔', verb: 'denied', tone: 'text-red-700' },
}

function fmtTs(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

// Renders the escalate → feedback → re-escalate → decide history, oldest first.
// `youName`, when it matches an item's actor, renders "You …" instead of the
// name (used in the underwriter's own re-escalation modal).
export default function EscalationThread({
  items, youName,
}: { items: EscalationThreadItem[]; youName?: string | null }) {
  if (!items.length) return null
  return (
    <ol className="space-y-2.5">
      {items.map((it, i) => {
        const meta = ACTION_META[it.action] ?? { icon: '•', verb: it.action, tone: 'text-slate-700' }
        const who = youName && it.actor === youName ? 'You' : it.actor
        return (
          <li key={i} className="text-xs">
            <div className={`flex flex-wrap items-center gap-1.5 font-medium ${meta.tone}`}>
              <span>{meta.icon}</span>
              <span>{who} {meta.verb}</span>
              {it.timestamp && <span className="text-slate-400">· {fmtTs(it.timestamp)}</span>}
            </div>
            {it.message && <p className="ml-5 mt-0.5 italic text-slate-600">“{it.message}”</p>}
          </li>
        )
      })}
    </ol>
  )
}
