// Typeahead search for loans. Types 2+ chars → debounced API call → dropdown
// of matches. Click a match → open that loan. Enter → filter the table.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchPipeline } from '../api/client'
import type { PipelineRow } from '../types/accord'

const STATUS_DOT: Record<string, string> = {
  halted: 'bg-red-800', blocked: 'bg-red-500', in_review: 'bg-amber-500',
  clear_to_close: 'bg-green-500', in_progress: 'bg-slate-400',
}
const STATUS_LABEL: Record<string, string> = {
  halted: 'Halted', blocked: 'Blocked', in_review: 'In Review',
  clear_to_close: 'Clear to Close', in_progress: 'In Progress',
}
function money(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}

export default function LoanSearch({
  value,
  onSubmit,
  className = '',
}: {
  value: string
  onSubmit: (q: string) => void
  className?: string
}) {
  const navigate = useNavigate()
  const [q, setQ] = useState(value)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<PipelineRow[]>([])
  const [searched, setSearched] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Keep in sync when the parent resets the applied filter.
  useEffect(() => setQ(value), [value])

  // Debounced lookup (300ms) once 2+ characters are typed.
  useEffect(() => {
    const term = q.trim()
    if (term.length < 2) {
      setResults([])
      setSearched(false)
      setLoading(false)
      setOpen(false)
      return
    }
    setLoading(true)
    setOpen(true)
    const t = setTimeout(async () => {
      try {
        const res = await fetchPipeline({ search: term, limit: 8 })
        setResults(res.applications)
      } catch {
        setResults([])
      } finally {
        setSearched(true)
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  function submit() {
    onSubmit(q.trim())
    setOpen(false)
  }

  return (
    <div ref={ref} className={`relative ${className}`}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => q.trim().length >= 2 && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
          else if (e.key === 'Escape') setOpen(false)
        }}
        placeholder="🔍  Search borrower or application ID…"
        className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand"
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          {loading && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-200 border-t-brand" />
              Searching…
            </div>
          )}
          {!loading && searched && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-slate-400">No results found</div>
          )}
          {!loading &&
            results.map((r) => (
              <button
                key={r.application_id}
                type="button"
                onClick={() => navigate(`/pipeline/${r.application_id}`)}
                className="flex w-full flex-col gap-0.5 border-b border-slate-50 px-4 py-2.5 text-left last:border-b-0 hover:bg-slate-50"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-800">{r.borrower_name}</span>
                  <span className="font-mono text-xs text-slate-400">{r.application_id}</span>
                </div>
                <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span className="capitalize">
                    {(r.loan_type ?? '—').replace('_', '-')} · {money(r.loan_amount)}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${STATUS_DOT[r.status] ?? 'bg-slate-400'}`} />
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
