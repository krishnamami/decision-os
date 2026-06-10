import type { LoanDetail } from '../types/accord'

function dotColor(action: string): string {
  const a = action.toLowerCase()
  if (a.includes('block') || a.includes('halt') || a.includes('revert') || a.includes('deny')) return 'bg-red-500'
  if (a.includes('approv')) return 'bg-green-500'
  if (a.includes('override')) return 'bg-amber-500'
  return 'bg-slate-300'
}

export default function ActivityFeed({ activity }: { activity: LoanDetail['activity'] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-3 text-sm font-semibold text-slate-900">Activity</div>
      {activity.length === 0 ? (
        <p className="text-sm text-slate-400">No data available.</p>
      ) : (
        <ul className="space-y-3">
          {activity.map((a, i) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="relative flex flex-col items-center">
                <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotColor(a.action)}`} />
                {i < activity.length - 1 && <span className="mt-1 w-px flex-1 bg-slate-200" />}
              </span>
              <div className="pb-1">
                <div className="text-slate-700">
                  <span className="font-medium">{a.actor}</span> {a.action.replace(/_/g, ' ')}
                  {a.target ? <span className="text-slate-400"> · {a.target}</span> : ''}
                </div>
                {a.at && <div className="text-xs text-slate-400">{new Date(a.at).toLocaleString()}</div>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
