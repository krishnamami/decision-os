import type { Outcome } from '../types/accord'

// Exact Accord outcome palette:
//   allow     green-100/800  (#DCFCE7 / #166534)
//   recommend amber-100/800  (#FEF3C7 / #92400E)
//   escalate  orange-100/800 (#FFEDD5 / #9A3412)
//   block     red-100/800    (#FEE2E2 / #991B1B)
export const OUTCOME_META: Record<
  string,
  { label: string; icon: string; pill: string; dot: string }
> = {
  allow: { label: 'Approved', icon: '✓', pill: 'bg-green-100 text-green-800', dot: 'bg-green-600' },
  recommend: { label: 'Review', icon: '◆', pill: 'bg-amber-100 text-amber-800', dot: 'bg-amber-500' },
  escalate: { label: 'Escalated', icon: '▲', pill: 'bg-orange-100 text-orange-800', dot: 'bg-orange-500' },
  block: { label: 'Blocked', icon: '✕', pill: 'bg-red-100 text-red-800', dot: 'bg-red-600' },
}

const EMPTY = { label: '—', icon: '·', pill: 'bg-slate-100 text-slate-400', dot: 'bg-slate-300' }

export function outcomeMeta(outcome: string | null | undefined) {
  return (outcome && OUTCOME_META[outcome]) || EMPTY
}

export default function DecisionPill({
  outcome,
  reviewed,
  compact,
}: {
  outcome: Outcome | string | null | undefined
  reviewed?: boolean
  compact?: boolean
}) {
  const m = outcomeMeta(outcome)
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ${m.pill} ${
        compact ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'
      }`}
      title={reviewed ? 'Reviewed by a human' : 'Awaiting review'}
    >
      {m.label}
      {reviewed && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />}
    </span>
  )
}
