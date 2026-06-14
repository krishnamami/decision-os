// Clickable summary metric chips — carried over UNCHANGED from the old LoanDetail
// (credit score / DTI / LTV / income → source document via EvidenceDocumentPanel).
import type { DecisionDetail } from '../../types/accord'
import type { DocItem } from '../../api/client'

export type Metric = 'credit_score' | 'dti' | 'ltv' | 'income'
const METRIC_DECISIONS: Record<Metric, string[]> = {
  credit_score: ['credit_assessment'],
  dti: ['dti_calculation', 'income_verification'],
  ltv: ['ltv_assessment'],
  income: ['income_verification', 'employment_reconciliation'],
}
const METRIC_DOC_TYPES: Record<Metric, string[]> = {
  credit_score: ['CREDIT_REPORT'],
  dti: ['PAYSTUB_CURRENT', 'W2_CURRENT', 'CREDIT_REPORT'],
  ltv: ['APPRAISAL_URAR', 'PURCHASE_AGREEMENT'],
  income: ['W2_CURRENT', 'PAYSTUB_CURRENT', 'VOE_TWN', 'VOE', 'IRS_TRANSCRIPT'],
}
export function findDocForMetric(metric: Metric, decisions: DecisionDetail[], documents: DocItem[]): DocItem | null {
  const dec = decisions.find((d) => METRIC_DECISIONS[metric].includes(d.decision_id) && d.evidence?.length)
  if (dec) {
    const first = dec.evidence[0].document?.toLowerCase().split(' ')[0]
    const m = first ? documents.find((doc) => doc.document_type?.toLowerCase().includes(first)) : undefined
    if (m) return m
  }
  for (const t of METRIC_DOC_TYPES[metric]) {
    const m = documents.find((doc) => doc.document_type === t)
    if (m) return m
  }
  return null
}

export function MetricChip({ label, value, doc, onOpen }: { label: string; value: string; doc: DocItem | null; onOpen: (d: DocItem) => void }) {
  if (!doc) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
        <div className="text-sm font-semibold text-slate-800">{value}</div>
      </div>
    )
  }
  return (
    <button
      onClick={() => onOpen(doc)}
      title="Click to see source document"
      className="group rounded-lg border border-slate-200 bg-white px-3 py-2 text-left transition hover:border-brand/40 hover:bg-slate-50"
    >
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="flex items-center gap-1">
        <span className="text-sm font-semibold text-slate-800 underline decoration-dotted decoration-slate-300 group-hover:decoration-brand">{value}</span>
        <span className="text-xs text-slate-400 group-hover:text-brand">↗</span>
      </div>
    </button>
  )
}
