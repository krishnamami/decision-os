import type { LoanDetail } from '../../types/accord'
import type { DocItem, LoanAction } from '../../api/client'
import { resolveRule } from '../../config/ruleLabels'
import { RuleLayerBadge } from '../RuleLayerBadge'
import { fmtTs, friendly } from './util'

const LAYER: Record<string, 'federal' | 'agency' | 'lender' | 'system'> = {
  federal: 'federal', agency: 'agency', lender: 'lender', system: 'system',
}

export default function AuditTab({ loan, docs, actions }: { loan: LoanDetail; docs: DocItem[]; actions: LoanAction[] }) {
  const readiness = loan.examiner_readiness ?? { score: 0, missing: [] }
  const cls = readiness.score >= 90 ? 'text-green-600' : readiness.score >= 70 ? 'text-amber-600' : 'text-red-600'
  const bar = readiness.score >= 90 ? 'bg-green-500' : readiness.score >= 70 ? 'bg-amber-500' : 'bg-red-500'
  const decisions = loan.decisions ?? []
  const openReport = () => window.open(`/loans/${loan.application_id}/examiner-report`, '_blank')

  return (
    <div className="space-y-6">
      {/* Readiness */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Examiner readiness</div>
            <div className={`text-4xl font-bold ${cls}`}>{readiness.score}%</div>
          </div>
          <div className="flex gap-2">
            <button onClick={openReport} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Preview examiner package →</button>
            <button onClick={openReport} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Export PDF</button>
          </div>
        </div>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${bar}`} style={{ width: `${readiness.score}%` }} /></div>
        {readiness.missing.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm text-amber-700">{readiness.missing.map((m, i) => <li key={i}>⚠ {m}</li>)}</ul>
        )}
      </div>

      {/* Rules applied */}
      <div>
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">Rules applied</h3>
        <div className="space-y-1.5">
          {decisions.filter((d) => d.rule).map((d) => {
            const info = resolveRule(d.rule || '')
            return (
              <div key={d.decision_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-white px-3 py-2 text-sm">
                <RuleLayerBadge layer={LAYER[info.layer] ?? 'system'} />
                <span className="text-slate-700">{info.label}</span>
                {info.citation && <span className="text-xs text-slate-400">· {info.citation}</span>}
                <span className="ml-auto text-xs text-slate-400">{friendly(d.decision_id)}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Evidence reviewed */}
      <div>
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">Evidence reviewed ({docs.length})</h3>
        <ul className="space-y-1 text-sm">
          {docs.map((d) => (
            <li key={d.document_id} className="flex items-center gap-2 text-slate-700">
              <span className="text-slate-400">📄</span>{d.display_name}
              <span className="ml-auto text-xs text-slate-400">{d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Decision timeline */}
      <div>
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">Decision timeline</h3>
        <ul className="space-y-1.5 text-sm">
          {decisions.filter((d) => d.reviewed_at).map((d) => (
            <li key={d.decision_id} className="flex items-start gap-2 border-l-2 border-slate-200 pl-3">
              <span className="text-xs text-slate-400">{fmtTs(d.reviewed_at)}</span>
              <span className="text-slate-700">{friendly(d.decision_id)} — <span className="uppercase">{d.outcome}</span>{d.reviewer ? ` · ${d.reviewer}` : ''}</span>
            </li>
          ))}
          {actions.map((a) => (
            <li key={a.id} className="flex items-start gap-2 border-l-2 border-brand/40 pl-3">
              <span className="text-xs text-slate-400">{fmtTs(a.performed_at)}</span>
              <span className="text-slate-700"><span className="font-medium">{a.performed_by}</span> — {a.action_type} · “{a.reason_text.slice(0, 60)}…”</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
