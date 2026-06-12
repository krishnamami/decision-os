import { useEffect, useState } from 'react'
import { fetchMyQueue } from '../api/client'

export interface ActionConfirmationData {
  icon: string
  title: string
  tone: 'green' | 'blue' | 'purple' | 'red' | 'amber'
  points: string[]
  detailTitle?: string
  detailItems?: string[]
  detailText?: string
}

const BAR: Record<ActionConfirmationData['tone'], string> = {
  green: 'border-l-green-500', blue: 'border-l-blue-500', purple: 'border-l-purple-500',
  red: 'border-l-red-500', amber: 'border-l-amber-500',
}

export default function ActionConfirmation({
  data,
  onBack,
  autoBackMs = 8000,
}: {
  data: ActionConfirmationData
  onBack: () => void
  autoBackMs?: number
}) {
  const [remaining, setRemaining] = useState<number | null>(null)

  // How much work is left in the user's queue (motivating + informational).
  useEffect(() => {
    fetchMyQueue().then((d) => setRemaining(d.counts.active)).catch(() => undefined)
  }, [])

  // Optional auto-return to the queue.
  useEffect(() => {
    if (!autoBackMs) return
    const t = setTimeout(onBack, autoBackMs)
    return () => clearTimeout(t)
  }, [autoBackMs, onBack])

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm border-l-4 ${BAR[data.tone]}`}>
        <h1 className="text-xl font-semibold text-slate-900">{data.icon} {data.title}</h1>

        <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">What happens now</div>
        <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
          {data.points.map((p, i) => (
            <li key={i} className="flex gap-2"><span className="text-slate-400">•</span><span>{p}</span></li>
          ))}
        </ul>

        {(data.detailItems?.length || data.detailText) && (
          <div className="mt-4 rounded-lg bg-slate-50 p-3">
            {data.detailTitle && <div className="mb-1.5 text-xs font-semibold text-slate-500">{data.detailTitle}</div>}
            {data.detailItems?.map((it, i) => (
              <div key={i} className="text-sm text-slate-700">☑ {it}</div>
            ))}
            {data.detailText && <div className="text-sm italic leading-relaxed text-slate-700">"{data.detailText}"</div>}
          </div>
        )}

        <button onClick={onBack} className="mt-6 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark">
          ← Back to my queue{remaining != null ? ` (${remaining} remaining)` : ''}
        </button>
      </div>
    </div>
  )
}
