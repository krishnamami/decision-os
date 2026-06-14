import { useState } from 'react'
import type { LoanDetail, DecisionDetail } from '../../types/accord'
import { bucketDecisions, friendly } from './util'

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const simplify = (e: string) =>
  e.replace(/^(Blocked|Escalated for senior review|Declined|Recommended[^—]*)\s*—\s*driven by\s*/i, '').replace(/\.$/, '') + '.'

function Item({ d }: { d: DecisionDetail }) {
  const block = d.outcome === 'block'
  const fails = (d.signals || []).filter((s) => s.status === 'fail' || s.status === 'warn').slice(0, 2)
  return (
    <div className={`rounded-xl border bg-white p-4 ${block ? 'border-l-4 border-l-red-500 border-red-100' : 'border-l-4 border-l-amber-500 border-amber-100'}`}>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <span>{block ? '🔴' : '⚠'}</span>
        {friendly(d.decision_id)} — <span className={block ? 'text-red-700' : 'text-amber-700'}>{cap(d.outcome)}</span>
        {d.confidence != null && <span className="text-xs font-normal text-slate-400">({Math.round(d.confidence * 100)}% confidence)</span>}
      </div>
      <p className="mt-1 text-sm leading-snug text-slate-600">{cap(simplify(d.explanation || 'Needs review.'))}</p>
      {fails.length > 0 && (
        <div className="mt-1 text-xs text-slate-500">{fails.map((s, i) => <span key={i}>{i > 0 ? ' · ' : ''}✕ {s.key}: <span className="font-medium">{s.value}</span></span>)}</div>
      )}
      {!block && <div className="mt-2 text-xs font-medium text-brand">→ What do you want to do?</div>}
    </div>
  )
}

export default function AttentionItems({ loan }: { loan: LoanDetail }) {
  const decisions = loan.decisions ?? []
  const { blocked, escalated, passed } = bucketDecisions(decisions)
  const items = [
    ...blocked.sort((a, b) => a.wave - b.wave),
    ...escalated.sort((a, b) => a.wave - b.wave),
  ].slice(0, 5)
  const [showPassed, setShowPassed] = useState(false)

  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Needs your attention</h2>
      {items.length === 0 ? (
        <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-sm font-medium text-green-800">✅ Nothing is blocking this file — every check passed.</div>
      ) : (
        <div className="space-y-3">{items.map((d) => <Item key={d.decision_id} d={d} />)}</div>
      )}

      {passed.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setShowPassed((v) => !v)} className="text-xs font-medium text-slate-500 hover:text-slate-800">
            {showPassed ? '▲ Hide' : `▼ Everything else passed (${passed.length})`}
          </button>
          {showPassed && (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {passed.map((d) => (
                <li key={d.decision_id} className="rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">✅ {friendly(d.decision_id)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
