// Product switcher — Accord ships multiple products on one platform.
// Only "Pipeline" is live today; the rest preview as disabled.

const PRODUCTS = [
  { id: 'pipeline', label: 'Pipeline', live: true },
  { id: 'origination', label: 'Origination', live: false },
  { id: 'servicing', label: 'Servicing', live: false },
]

export default function ProductSwitcher({ active = 'pipeline' }: { active?: string }) {
  return (
    <div className="inline-flex items-center rounded-lg bg-slate-100 p-0.5 text-sm">
      {PRODUCTS.map((p) => (
        <button
          key={p.id}
          disabled={!p.live}
          className={`flex items-center gap-1 rounded-md px-3 py-1 font-medium transition ${
            p.id === active
              ? 'bg-white text-brand shadow-sm'
              : p.live
                ? 'text-slate-600 hover:text-slate-900'
                : 'cursor-not-allowed text-slate-400'
          }`}
          title={p.live ? p.label : `${p.label} — coming soon`}
        >
          {p.label}
          {!p.live && (
            <span className="rounded bg-slate-200 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-500">
              Soon
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
