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

// The 5 lifecycle stages, keyed by the `wave` each decision already carries.
const STAGES = [
  { wave: 1, label: 'VERIFY' },
  { wave: 2, label: 'UNDERWRITE' },
  { wave: 3, label: 'ELIGIBILITY' },
  { wave: 4, label: 'DECIDE' },
  { wave: 5, label: 'CLOSE' },
]

function overall(ds: DecisionDetail[]): { label: string; cls: string } {
  if (!ds.length) return { label: 'Pending', cls: 'bg-gray-100 text-gray-400' }
  if (ds.some((d) => d.outcome === 'block')) return { label: 'Blocked', cls: 'bg-red-100 text-red-800' }
  if (ds.some((d) => d.outcome === 'escalate' || d.outcome === 'recommend'))
    return { label: 'Review', cls: 'bg-amber-100 text-amber-800' }
  if (ds.every((d) => d.outcome === 'allow')) return { label: 'Passed', cls: 'bg-green-100 text-green-800' }
  return { label: 'Pending', cls: 'bg-gray-100 text-gray-400' }
}

export default function PersonaAccordion({ decisions }: { decisions: DecisionDetail[] }) {
  // One open decision per stage. Default: open the first blocking/escalating one.
  const [openByWave, setOpenByWave] = useState<Record<number, string | null>>(() => {
    const blocker = decisions.find((d) => d.outcome === 'block' || d.outcome === 'escalate')
    return blocker ? { [blocker.wave]: blocker.decision_id } : {}
  })

  return (
    <div>
      <div className="mb-1 text-base font-semibold text-slate-900">Decision Journey</div>
      <p className="mb-3 text-sm text-slate-500">Click any decision to see the AI's reasoning.</p>

      <div className="space-y-3">
        {STAGES.map((stage) => {
          const ds = decisions.filter((d) => d.wave === stage.wave)
          const ov = overall(ds)
          return (
            <div key={stage.wave} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-5 py-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-bold tracking-wide text-slate-800">{stage.label}</span>
                  <span className="text-xs text-slate-400">Wave {stage.wave}</span>
                </div>
                <span className="flex items-center gap-1.5 text-xs text-slate-500">
                  Overall:
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ov.cls}`}>{ov.label}</span>
                </span>
              </div>

              {ds.length === 0 ? (
                <div className="px-5 py-3 text-sm text-slate-400">No data available.</div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {ds.map((d) => (
                    <DecisionRow
                      key={d.decision_id}
                      d={d}
                      open={openByWave[stage.wave] === d.decision_id}
                      onToggle={() =>
                        setOpenByWave((s) => ({
                          ...s,
                          [stage.wave]: s[stage.wave] === d.decision_id ? null : d.decision_id,
                        }))
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DecisionRow({ d, open, onToggle }: { d: DecisionDetail; open: boolean; onToggle: () => void }) {
  const m = outcomeMeta(d.outcome)
  return (
    <div>
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-slate-50">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${m.pill}`}>
          {m.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-800">{d.persona_name}</span>
            {d.stale && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">stale</span>
            )}
          </div>
          <div className="truncate text-xs text-slate-500">{(d.explanation || '').split('. ')[0]}</div>
        </div>
        <span className="hidden shrink-0 text-xs text-slate-400 sm:block">
          {d.reviewed ? `✓ Reviewed${d.reviewer ? ` by ${d.reviewer}` : ''}` : '⏳ Pending'}
        </span>
        <DecisionPill outcome={d.outcome} compact />
        <span className="shrink-0 text-slate-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          {/* AI explanation */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">🧠 AI Explanation</div>
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700">
              {d.explanation || 'No explanation available.'}
            </div>
          </div>

          {/* Signals */}
          {d.signals.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Signals</div>
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
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Rule matched</div>
              <pre className="overflow-x-auto rounded-lg bg-slate-900 px-3 py-2 font-mono text-[11px] text-slate-100">
                {d.rule}
              </pre>
            </div>
          )}

          {/* Evidence */}
          {d.evidence.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Evidence</div>
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

          {/* Metadata: Confidence · Reviewer · Timestamp */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 pt-3 text-xs text-slate-400">
            <span>
              Confidence:{' '}
              <span className="font-medium text-slate-600">
                {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'}
              </span>
            </span>
            <span>Mode: <span className="font-medium text-slate-600">{d.mode}</span></span>
            <span>Reviewer: <span className="font-medium text-slate-600">{d.reviewer ?? 'System'}</span></span>
            {d.reviewed_at && <span>{new Date(d.reviewed_at).toLocaleString()}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
