// Pagination controls + page-size selector. Drives server-side limit/offset.

const SIZES = [25, 50, 100]

// Page numbers with ellipses: always 1, last, current and its neighbours.
function pageList(current: number, total: number): (number | 'gap')[] {
  const want = new Set<number>([1, total, current, current - 1, current + 1])
  const sorted = [...want].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b)
  const out: (number | 'gap')[] = []
  let prev = 0
  for (const p of sorted) {
    if (p - prev > 1) out.push('gap')
    out.push(p)
    prev = p
  }
  return out
}

export default function Pagination({
  total,
  limit,
  offset,
  onOffset,
  onLimit,
}: {
  total: number
  limit: number
  offset: number
  onOffset: (o: number) => void
  onLimit: (l: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / limit))
  const current = Math.floor(offset / limit) + 1
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)
  const goto = (p: number) => onOffset((Math.min(Math.max(p, 1), pages) - 1) * limit)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-sm">
      <span className="text-slate-500">
        Showing {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>

      <div className="flex items-center gap-1">
        <button
          onClick={() => goto(current - 1)}
          disabled={current <= 1}
          className="rounded-lg border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          ← Prev
        </button>
        {pageList(current, pages).map((p, i) =>
          p === 'gap' ? (
            <span key={`gap-${i}`} className="px-1.5 text-slate-400">…</span>
          ) : (
            <button
              key={p}
              onClick={() => goto(p)}
              className={`min-w-[32px] rounded-lg border px-2 py-1 ${
                p === current ? 'border-brand bg-brand text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {p}
            </button>
          ),
        )}
        <button
          onClick={() => goto(current + 1)}
          disabled={current >= pages}
          className="rounded-lg border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          Next →
        </button>
      </div>

      <div className="flex items-center gap-1.5 text-slate-500">
        Show:
        {SIZES.map((s) => (
          <button
            key={s}
            onClick={() => onLimit(s)}
            className={`rounded px-2 py-1 ${s === limit ? 'bg-slate-200 font-semibold text-slate-800' : 'hover:bg-slate-100'}`}
          >
            {s}
          </button>
        ))}
        <span className="text-slate-400">per page</span>
      </div>
    </div>
  )
}
