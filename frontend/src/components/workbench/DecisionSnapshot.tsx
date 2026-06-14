import type { LoanDetail } from '../../types/accord'
import { bucketDecisions } from './util'

export default function DecisionSnapshot({ loan }: { loan: LoanDetail }) {
  const decisions = loan.decisions ?? []
  const { blocked, escalated, passed } = bucketDecisions(decisions)
  const confs = decisions.map((d) => d.confidence).filter((c): c is number => c != null)
  const confidence = confs.length ? Math.round((confs.reduce((a, b) => a + b, 0) / confs.length) * 100) : 0
  const confCls = confidence >= 80 ? 'text-green-600' : confidence >= 60 ? 'text-amber-600' : 'text-red-600'
  const headline = loan.conversational_summary?.headline

  const Stat = ({ n, label, cls }: { n: number; label: string; cls: string }) => (
    <div className="text-center">
      <div className={`text-2xl font-bold ${cls}`}>{n}</div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  )

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center gap-6">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">AI confidence</div>
          <div className={`text-4xl font-bold ${confCls}`}>{confidence}%</div>
        </div>
        <div className="flex flex-1 items-center justify-around gap-4">
          <Stat n={blocked.length} label="Blocking" cls="text-red-600" />
          <Stat n={escalated.length} label="Escalations" cls="text-amber-600" />
          <Stat n={passed.length} label="Passed" cls="text-green-600" />
        </div>
      </div>
      {headline && <div className="mt-3 border-t border-slate-100 pt-3 text-sm font-semibold text-slate-800">{headline}</div>}
    </section>
  )
}
