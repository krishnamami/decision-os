// Status filter dropdown with colored dots. Native <select> can't color
// per-option markers, so this is a small custom popover.
import { useEffect, useRef, useState } from 'react'

export const STATUS_OPTIONS: Array<{ value: string; label: string; dot: string }> = [
  { value: '', label: 'All Statuses', dot: '' },
  { value: 'clear_to_close', label: 'Clear to Close', dot: 'bg-green-500' },
  { value: 'in_review', label: 'In Review', dot: 'bg-amber-500' },
  { value: 'blocked', label: 'Blocked', dot: 'bg-red-500' },
  { value: 'halted', label: 'Halted', dot: 'bg-red-800' },
]

export default function StatusFilter({
  value,
  onChange,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = STATUS_OPTIONS.find((o) => o.value === value) ?? STATUS_OPTIONS[0]

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand"
      >
        <span className="flex items-center gap-2 truncate">
          {current.dot && <span className={`h-2 w-2 shrink-0 rounded-full ${current.dot}`} />}
          {current.label}
        </span>
        <span className="text-xs text-gray-400">▾</span>
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          {STATUS_OPTIONS.map((o) => (
            <button
              key={o.value || 'all'}
              type="button"
              onClick={() => {
                onChange(o.value)
                setOpen(false)
              }}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                o.value === value ? 'bg-slate-50 font-medium' : ''
              }`}
            >
              {o.dot ? <span className={`h-2 w-2 shrink-0 rounded-full ${o.dot}`} /> : <span className="h-2 w-2 shrink-0" />}
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
