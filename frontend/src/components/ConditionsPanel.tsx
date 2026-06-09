const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  open: { label: 'Outstanding', cls: 'bg-amber-100 text-amber-800' },
  in_progress: { label: 'In progress', cls: 'bg-blue-100 text-blue-700' },
  cleared: { label: 'Satisfied', cls: 'bg-green-100 text-green-800' },
  satisfied: { label: 'Satisfied', cls: 'bg-green-100 text-green-800' },
  waived: { label: 'Waived', cls: 'bg-slate-100 text-slate-500' },
}

export default function ConditionsPanel({ conditions }: { conditions: Array<Record<string, unknown>> }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-3 text-sm font-semibold text-slate-900">
        Conditions ({conditions.length})
      </div>
      {conditions.length === 0 ? (
        <p className="text-sm text-slate-400">No open conditions.</p>
      ) : (
        <ul className="space-y-2.5">
          {conditions.map((c, i) => {
            const status = String(c.status ?? 'open')
            const pill = STATUS_PILL[status] ?? STATUS_PILL.open
            return (
              <li key={i} className="flex items-start justify-between gap-3 text-sm">
                <div>
                  <div className="text-slate-700">{String(c.description ?? '')}</div>
                  <div className="text-xs text-slate-400">{String(c.category ?? '')}</div>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${pill.cls}`}>
                  {pill.label}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
