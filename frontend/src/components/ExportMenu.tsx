// Export button with a click-to-open dropdown of format actions.
import { useEffect, useRef, useState } from 'react'

export type ExportItem = { label: string; run: () => void; disabled?: boolean }

export default function ExportMenu({
  label = '📥 Export',
  items,
  className = '',
}: {
  label?: string
  items: ExportItem[]
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

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
        className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        {label} <span className="text-xs text-gray-400">▾</span>
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-48 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              disabled={it.disabled}
              onClick={() => {
                if (it.disabled) return
                it.run()
                setOpen(false)
              }}
              className="block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
