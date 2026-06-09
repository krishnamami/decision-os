import { useState } from 'react'
import type { DecisionDetail } from '../types/accord'
import DecisionPill, { outcomeMeta } from './DecisionPill'

const SIGNAL_DOT: Record<string, string> = {
  pass: 'bg-green-500',
  fail: 'bg-red-500',
  warn: 'bg-amber-500',
  no_data: 'bg-slate-300',
  info: 'bg-slate-400',
}

function shortDesc(d: DecisionDetail): string {
  const first = (d.explanation || '').split('. ')[0]
  return first.length > 90 ? first.slice(0, 88) + '…' : first
}

export default function PersonaAccordion({ decisions }: { decisions: DecisionDetail[] }) {
  // Only one open at a time; default the first blocking/escalating decision.
  const initial =
    decisions.find((d) => d.outcome === 'block' || d.outcome === 'escalate')?.decision_id ??
    decisions[0]?.decision_id ??
    null
  const [open, setOpen] = useState<string | null>(initial)

  return (
    <div>
      <div className="mb-1 text-base font-semibold text-slate-900">
        What the AI found ({decisions.length} decisions)
      </div>
      <p className="mb-3 text-sm text-slate-500">Click any decision to see the AI's reasoning.</p>

      <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {decisions.map((d) => {
          const isOpen = open === d.decision_id
          const m = outcomeMeta(d.outcome)
          return (
            <div key={d.decision_id}>
              <button
                onClick={() => setOpen(isOpen ? null : d.decision_id)}
                className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-slate-50"
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${m.pill}`}
                >
                  {m.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-800">{d.persona_name}</span>
                    <span className="text-[10px] font-medium text-slate-400">WAVE {d.wave}</span>
                    {d.stale && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                        stale
                      </span>
                    )}
                  </div>
                  <div className="truncate text-xs text-slate-500">{shortDesc(d)}</div>
                </div>
                <span className="hidden shrink-0 text-xs text-slate-400 sm:block">
                  {d.reviewed ? `✓ Reviewed${d.reviewer ? ` by ${d.reviewer}` : ''}` : '⏳ Pending'}
                </span>
                <DecisionPill outcome={d.outcome} compact />
                <span className="shrink-0 text-slate-400">{isOpen ? '▲' : '▼'}</span>
              </button>

              {isOpen && (
                <div className="space-y-4 border-t border-slate-100 bg-slate-50/60 px-5 py-4">
                  {/* AI explanation */}
                  <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700">
                    {d.explanation}
                  </div>

                  {/* Signals checklist */}
                  {d.signals.length > 0 && (
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Signals
                      </div>
                      <ul className="grid gap-1.5 sm:grid-cols-2">
                        {d.signals.map((s, i) => (
                          <li key={i} className="flex items-center gap-2 text-sm">
                            <span className={`h-2 w-2 shrink-0 rounded-full ${SIGNAL_DOT[s.status] || 'bg-slate-400'}`} />
                            <span className="text-slate-600">{s.key}</span>
                            <span className="ml-auto font-medium text-slate-900">{s.value}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Rule matched */}
                  {d.rule && (
                    <div>
                      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Rule matched
                      </div>
                      <pre className="overflow-x-auto rounded-lg bg-slate-900 px-3 py-2 font-mono text-[11px] text-slate-100">
                        {d.rule}
                      </pre>
                    </div>
                  )}

                  {/* Evidence */}
                  {d.evidence.length > 0 && (
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Evidence
                      </div>
                      <ul className="space-y-1">
                        {d.evidence.map((e, i) => (
                          <li key={i} className="flex items-center gap-2 text-sm">
                            <span className="text-slate-400">📄</span>
                            <span className="font-medium text-slate-700">{e.document}</span>
                            <span className="text-slate-400">— {e.detail}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Metadata */}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 pt-3 text-xs text-slate-400">
                    <span>
                      Confidence:{' '}
                      <span className="font-medium text-slate-600">
                        {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'}
                      </span>
                    </span>
                    <span>Mode: <span className="font-medium text-slate-600">{d.mode}</span></span>
                    {d.reviewer && <span>Reviewer: <span className="font-medium text-slate-600">{d.reviewer}</span></span>}
                    {d.reviewed_at && (
                      <span>{new Date(d.reviewed_at).toLocaleString()}</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
