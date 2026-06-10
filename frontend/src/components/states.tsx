// Shared loading / error / empty UI states that match the real content layout.

export function Shimmer({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-gray-200 ${className}`} />
}

// Amber error card with a retry action. Never shows raw error text.
export function ErrorState({
  message = 'Could not load this data.',
  onRetry,
  className = '',
}: {
  message?: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div className={`rounded-xl border border-amber-300 bg-amber-50 p-6 text-center ${className}`}>
      <div className="text-2xl text-amber-500">⚠</div>
      <div className="mt-1 font-semibold text-gray-800">Something went wrong</div>
      <p className="mt-1 text-sm text-gray-700">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-lg border border-amber-400 bg-white px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100"
        >
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({
  icon = '📋',
  title,
  hint,
  actionLabel,
  onAction,
  className = '',
}: {
  icon?: string
  title: string
  hint?: string
  actionLabel?: string
  onAction?: () => void
  className?: string
}) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-10 text-center ${className}`}>
      <div className="text-3xl">{icon}</div>
      <div className="mt-2 font-semibold text-slate-800">{title}</div>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}

// Skeleton <tr> rows that match a table's column count — drop inside <tbody>.
export function SkeletonRows({ rows = 6, cols }: { rows?: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c} className="px-4 py-3">
              <div className="h-4 animate-pulse rounded bg-gray-200" style={{ width: c === 0 ? '75%' : '55%' }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

// A single KPI-card-sized skeleton.
export function CardSkeleton() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="h-3 w-20 animate-pulse rounded bg-gray-200" />
      <div className="mt-2 h-7 w-24 animate-pulse rounded bg-gray-200" />
    </div>
  )
}
