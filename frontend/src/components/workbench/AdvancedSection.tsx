import { useState } from 'react'
import type { LoanDetail } from '../../types/accord'

export default function AdvancedSection({ loan }: { loan: LoanDetail }) {
  const [open, setOpen] = useState(false)
  const conditions = (loan as unknown as { conditions?: Array<{ condition_id: string; description: string; status: string; category?: string }> }).conditions ?? []
  const edges = (loan as unknown as { graph_edges?: unknown[] }).graph_edges ?? []
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-5 py-3 text-left">
        <span className="text-sm font-semibold text-slate-700">Advanced</span>
        <span className="text-xs text-slate-400">{open ? '▼ collapse' : '▶ conditions, document graph'}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 p-5 text-sm">
          <div>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Conditions ({conditions.length})</div>
            {conditions.length === 0 ? (
              <p className="mt-1 text-slate-400">No conditions on file.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {conditions.map((c) => (
                  <li key={c.condition_id} className="flex items-center gap-2 text-slate-700">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] capitalize text-slate-500">{c.status}</span>
                    {c.description}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="text-xs text-slate-500">Document graph: {edges.length} cross-reference{edges.length === 1 ? '' : 's'} between source documents.</div>
        </div>
      )}
    </section>
  )
}
