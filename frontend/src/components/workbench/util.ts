import type { DecisionDetail } from '../../types/accord'

export const money = (v: number | null | undefined) =>
  v == null ? '—' : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${v}`
export const pct = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}%`)
export const fmtTs = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—')

const FRIENDLY: Record<string, string> = {
  credit_assessment: 'Credit', fraud_screening: 'Identity', compliance_check: 'Compliance',
  employment_reconciliation: 'Employment', income_verification: 'Income', ltv_assessment: 'Collateral',
  dti_calculation: 'DTI', product_eligibility: 'Product', rate_pricing: 'Rate',
  underwriting_decision: 'Underwriting', approval_routing: 'Routing', closing_readiness: 'Closing',
}
export const friendly = (id: string) => FRIENDLY[id] ?? id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const BLOCK = ['block', 'escalate']
export function bucketDecisions(decisions: DecisionDetail[]) {
  const blocked = decisions.filter((d) => d.outcome === 'block')
  const escalated = decisions.filter((d) => d.outcome === 'escalate')
  const passed = decisions.filter((d) => !BLOCK.includes(d.outcome))
  return { blocked, escalated, passed }
}

// The decision that drives the recommendation: a hard block at the lowest wave,
// else the lowest-wave open escalate.
export function primaryDecision(decisions: DecisionDetail[]): DecisionDetail | null {
  const byWave = [...decisions].sort((a, b) => a.wave - b.wave)
  return byWave.find((d) => d.outcome === 'block') || byWave.find((d) => d.outcome === 'escalate') || null
}
