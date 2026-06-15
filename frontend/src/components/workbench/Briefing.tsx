import type { LoanDetail } from '../../types/accord'
import type { DocItem, LoanAction } from '../../api/client'
import { OFACBadge, deriveOFACStatus } from '../OFACBadge'
import { QMBadge } from '../QMBadge'
import { MetricChip, findDocForMetric } from './metricChips'
import { money, pct } from './util'

export default function Briefing({ loan, ofac, docs, onOpenDoc, actions = [] }: {
  loan: LoanDetail
  ofac: { checkedAt?: string; listDate?: string }
  docs: DocItem[]
  onOpenDoc: (d: DocItem) => void
  actions?: LoanAction[]
}) {
  const m = loan.metrics
  const cs = loan.conversational_summary
  const summary = cs?.summary
    ?? `${loan.borrower.name} — ${money(m.loan_amount)} loan. ${loan.status}.`
  const rc = loan.rain_check
  const seniorReview = actions.find((a) => a.action_type === 'senior_review')

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      {/* Senior review requested — loan handed off to a senior underwriter */}
      {seniorReview && (
        <div
          className="mb-3 flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[11px]"
          style={{ background: '#faeeda', border: '0.5px solid #ef9f27', color: '#633806' }}
        >
          <span aria-hidden="true">👤</span>
          <span>
            <strong>Senior review requested</strong>
            {seniorReview.performed_by && <> by {seniorReview.performed_by}</>}
            {seniorReview.performed_at && <> · {new Date(seniorReview.performed_at).toLocaleDateString()}</>}
          </span>
        </div>
      )}
      {/* Rain check — loan pinned to a rule version (rate-lock / pipeline protection) */}
      {rc?.pinned_rule_version && (
        <div
          className="mb-3 flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[11px]"
          style={{ background: '#d1e8d8', border: '0.5px solid #a8d5b5', color: '#0F4D37' }}
        >
          <span aria-hidden="true">🔒</span>
          <span>
            <strong>{rc.rate_locked ? 'Rate lock active' : 'Pipeline protection'}</strong> — evaluated under Rule v{rc.pinned_version_number}
            {rc.pinned_at ? ` (pinned ${new Date(rc.pinned_at).toLocaleDateString()})` : ''}.
            {rc.current_version_number != null && <> Current rule version is v{rc.current_version_number}.</>}
            {rc.protected && (
              <span style={{ color: '#854f0b' }}> Rules updated since lock — this loan is protected.</span>
            )}
          </span>
        </div>
      )}
      {/* Name + compliance badges */}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold text-slate-900">
          {loan.borrower.name}
          {loan.borrower.age ? <span className="text-slate-400"> · {loan.borrower.age}</span> : null}
          {loan.borrower.employer ? <span className="text-slate-400"> · {loan.borrower.employer}</span> : null}
        </h1>
        <OFACBadge status={deriveOFACStatus(loan.decisions ?? [])} checkedAt={ofac.checkedAt} listDate={ofac.listDate} />
        {loan.qm && <QMBadge qm={loan.qm} />}
      </div>

      {/* Slim info bar */}
      <p className="mt-1 text-sm text-slate-500">{money(m.loan_amount)} · {loan.application_id}</p>

      {/* Plain-English briefing */}
      <p className="mt-3 text-[15px] leading-relaxed text-slate-700">{summary}</p>
      {cs && (
        <div className="mt-3 space-y-1 text-sm">
          {cs.issue && <div><span className="font-semibold text-red-700">⚠ The issue:</span> {cs.issue}</div>}
          <div><span className="font-semibold text-green-700">✅ What&apos;s good:</span> {cs.whats_good}</div>
          <div><span className="font-semibold text-slate-700">👉 Next step:</span> {cs.next_step}</div>
        </div>
      )}

      {/* Clickable metric chips — every number sourced */}
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricChip label="Credit Score" value={m.credit_score != null ? String(m.credit_score) : '—'} doc={findDocForMetric('credit_score', loan.decisions, docs)} onOpen={onOpenDoc} />
        <MetricChip label="DTI" value={pct(m.dti)} doc={findDocForMetric('dti', loan.decisions, docs)} onOpen={onOpenDoc} />
        <MetricChip label="LTV" value={pct(m.ltv)} doc={findDocForMetric('ltv', loan.decisions, docs)} onOpen={onOpenDoc} />
        <MetricChip label="Income (verified)" value={money(m.income_verified)} doc={findDocForMetric('income', loan.decisions, docs)} onOpen={onOpenDoc} />
      </div>
    </section>
  )
}
