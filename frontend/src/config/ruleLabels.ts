// Plain-English labels + regulatory layer for the boundary rules the engine
// emits. The backend stores `boundary_rule` as an EXPRESSION STRING (e.g.
// "credit_score >= 680 AND no_derogatory_last_24_months == true"), not a
// snake_case identifier — so resolveRule() matches on the real expressions,
// then falls back to keyword classification, then to an operator-aware
// humanizer. ID-style keys are kept too, in case the backend ever emits them.

export type RuleLayer = 'federal' | 'agency' | 'lender' | 'system'

export interface RuleDefinition {
  label: string // plain English
  layer: RuleLayer
  citation?: string // e.g. "CFPB QM Rule 12 CFR §1026.43"
}

export const RULE_LABELS: Record<string, RuleDefinition> = {
  // ───────────────────────── ID-style keys (future-proof) ─────────────────────────
  // Federal — CFPB / Dodd-Frank
  dti_threshold_exceeded: { label: 'Debt-to-income ratio exceeds qualified mortgage limit', layer: 'federal', citation: 'CFPB QM Rule 12 CFR §1026.43(e)' },
  dti_above_43: { label: 'DTI exceeds 43% qualified mortgage ceiling', layer: 'federal', citation: 'CFPB QM Rule 12 CFR §1026.43(e)' },
  points_fees_exceeded: { label: 'Points and fees exceed qualified mortgage cap', layer: 'federal', citation: 'CFPB QM Rule 12 CFR §1026.43(e)(3)' },
  hmda_incomplete: { label: 'Required HMDA fields are missing or incomplete', layer: 'federal', citation: 'HMDA Regulation C 12 CFR §1003' },
  fair_lending_flag: { label: 'Fair lending review required — potential disparate impact', layer: 'federal', citation: 'Equal Credit Opportunity Act / Fair Housing Act' },
  // Agency — Fannie / Freddie / FHA / VA
  credit_score_below_minimum: { label: 'Credit score is below the minimum agency guideline', layer: 'agency', citation: 'Fannie Mae SEL 2022-07 / FHA 4000.1' },
  credit_score_below_620: { label: 'Credit score below 620 — ineligible for conventional financing', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-5.1' },
  ltv_too_high: { label: 'Loan-to-value ratio exceeds maximum allowed', layer: 'agency', citation: 'Fannie Mae Selling Guide B2-1.3 / FHA 4000.1 II.A.8' },
  ltv_above_97: { label: 'LTV exceeds 97% — exceeds agency maximum', layer: 'agency', citation: 'Fannie Mae HomeReady / FHA 4000.1' },
  employment_gap: { label: 'Employment gap of more than 30 days requires explanation', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1-09' },
  employment_less_than_2_years: { label: 'Employment history less than two years requires documentation', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1-01' },
  income_unverified: { label: 'Income could not be independently verified', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1 / FHA 4000.1 II.A.4' },
  self_employment_income_unverified: { label: 'Self-employment income requires two years of tax returns', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.2-01' },
  appraisal_condition_flag: { label: 'Appraisal condition rating requires repair or escrow', layer: 'agency', citation: 'Fannie Mae Selling Guide B4-1.3-06' },
  property_not_warrantable: { label: 'Property does not meet agency warrantability requirements', layer: 'agency', citation: 'Fannie Mae Selling Guide B4-2.1' },
  // Lender — internal policies / overlays
  reserves_insufficient: { label: 'Reserves below lender minimum — 3 months PITI required', layer: 'lender' },
  dti_overlay_exceeded: { label: 'DTI exceeds lender overlay threshold (40% cap)', layer: 'lender' },
  credit_score_overlay: { label: 'Credit score below lender overlay minimum (640)', layer: 'lender' },
  missing_required_disclosures: { label: 'One or more required borrower disclosures are missing', layer: 'lender' },
  cd_timing_non_compliant: { label: 'Closing Disclosure was not delivered within required timeframe', layer: 'lender' },
  loan_amount_below_minimum: { label: 'Loan amount is below the minimum lender threshold', layer: 'lender' },

  // ───────────────── Real expression-string keys (what the DB stores today) ─────────────────
  // Federal — fraud / BSA-AML + HMDA / fair lending
  'fraud_score < 0.2 AND identity_match_confidence >= 0.95': { label: 'Fraud and identity screening cleared', layer: 'federal', citation: 'BSA/AML 31 CFR §1010' },
  'fraud_score >= 0.5': { label: 'High fraud risk — mandatory BSA/SAR review', layer: 'federal', citation: 'BSA/AML 31 CFR §1010' },
  'fraud_score >= 0.2 AND fraud_score < 0.5': { label: 'Elevated fraud risk — manual identity review', layer: 'federal', citation: 'BSA/AML 31 CFR §1010' },
  'hmda_complete=True, fair_lending_violation=False, missing_disclosures=False': { label: 'HMDA data complete, no fair lending violations, all disclosures present', layer: 'federal', citation: 'HMDA Reg C 12 CFR §1003 / ECOA Reg B' },
  'hmda_complete=False, fair_lending_violation=False, missing_disclosures=False': { label: 'HMDA data incomplete — fields must be completed', layer: 'federal', citation: 'HMDA Reg C 12 CFR §1003' },

  // Agency — credit / LTV / income / product
  'credit_score >= 680 AND no_derogatory_last_24_months == true': { label: 'Credit score 680+ with no derogatory marks in 24 months', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-5.1' },
  'credit_score >= 600 AND credit_score < 680': { label: 'Credit score between 600 and 680 — closer review required', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-5.1' },
  'ltv <= 80%': { label: 'Loan-to-value within 80% — no mortgage insurance required', layer: 'agency', citation: 'Fannie Mae Selling Guide B2-1.3' },
  'ltv > 80% AND ltv <= 95%': { label: 'LTV between 80% and 95% — mortgage insurance required', layer: 'agency', citation: 'Fannie Mae Selling Guide B2-1.3' },
  'ltv > 95%': { label: 'LTV above 95% — limited program eligibility', layer: 'agency', citation: 'Fannie Mae Selling Guide B2-1.3 / FHA 4000.1' },
  'ltv > 97%': { label: 'LTV exceeds 97% — exceeds agency maximum', layer: 'agency', citation: 'Fannie Mae HomeReady / FHA 4000.1' },
  'income_discrepancy_pct > 0.25': { label: 'Stated vs verified income differs by more than 25%', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1' },
  'income_verification.confidence < 0.85': { label: 'Income verification confidence below threshold', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1' },

  // Lender — overlays / employment / pricing / title
  'continuity_coverage_pct < 0.80': { label: 'Employment continuity coverage is below 80%', layer: 'lender' },
  'reconciliation_status == conflict': { label: 'Income reconciliation found conflicting data', layer: 'lender' },
  'reconciliation_status == missing': { label: 'Income reconciliation data is missing', layer: 'lender' },
  'reconciliation_status == partial AND coverage >= 0.80': { label: 'Partial income reconciliation with adequate coverage', layer: 'lender' },
  'confidence >= 0.9 AND salaried AND payroll_verified': { label: 'Salaried income verified via payroll', layer: 'lender' },
  'auto_verified AND coverage >= 0.95 AND gap <= 30 AND name_match >= 0.90 AND drift <= 0.10': { label: 'Employment auto-verified within policy thresholds', layer: 'lender' },
  'rate_within_normal_band AND no_manual_adjustments': { label: 'Rate within normal band, no manual adjustments', layer: 'lender' },
  'pricing exception possible': { label: 'Pricing exception may apply', layer: 'lender' },
  cd_timing_violation: { label: 'Closing Disclosure was not delivered within required timeframe', layer: 'lender' },
  title_defect: { label: 'Title defect found — must be cleared before closing', layer: 'lender' },
  insurance_gap: { label: 'Hazard insurance gap — coverage required', layer: 'lender' },
  'minor conditions': { label: 'Minor conditions to clear (PTD/PTC)', layer: 'lender' },

  // System — routing / aggregation / fallbacks
  'default escalate': { label: 'No specific rule matched — escalated for human review', layer: 'system' },
  'minor_data_gap == true': { label: 'Minor data gap — routed for review', layer: 'system' },
  'underwriting_decision.outcome == block': { label: 'Upstream underwriting decision: blocked', layer: 'system' },
  'underwriting_decision.outcome == recommend': { label: 'Upstream underwriting decision: conditional approval', layer: 'system' },
  'upstream block propagated': { label: 'Blocked by an upstream check', layer: 'system' },
  'not all upstream cleared': { label: 'Waiting on upstream checks to clear', layer: 'system' },
}

// Keyword classifiers for parameterized variants the engine emits at runtime
// (e.g. "score=745, band='prime' → allow", "dti=escalate ltv=allow band=near-prime").
// Checked in order; first match wins.
const KEYWORD_RULES: Array<{ test: RegExp; def: (rule: string) => RuleDefinition }> = [
  { test: /eligible=/i, def: () => ({ label: 'Product eligibility evaluation', layer: 'agency', citation: 'Fannie Mae / FHA / VA product matrices' }) },
  { test: /fraud_score|watchlist|synthetic|\bofac\b/i, def: () => ({ label: 'Fraud and identity screening', layer: 'federal', citation: 'BSA/AML 31 CFR §1010' }) },
  { test: /hmda|fair_lending|missing_disclosures/i, def: () => ({ label: 'HMDA / fair lending and disclosure check', layer: 'federal', citation: 'HMDA Reg C 12 CFR §1003 / ECOA Reg B' }) },
  { test: /cd_timing/i, def: () => ({ label: 'Closing Disclosure timing check', layer: 'lender' }) },
  { test: /(dti=.*ltv=.*band=)|all_clean|all_conditions|upstream|underwriting_decision|risk_score|not all upstream/i, def: () => ({ label: 'Combined underwriting routing decision', layer: 'system' }) },
  { test: /underwriting_outcome|channel=|target=|_notice|counter_offer/i, def: () => ({ label: 'Decision notification routing', layer: 'system' }) },
  { test: /reconciliation_status|continuity_coverage|coverage=|verified \$|employer_match|payroll_verified/i, def: () => ({ label: 'Income / employment reconciliation', layer: 'lender' }) },
  { test: /income_discrepancy|income_verification|income_confidence/i, def: () => ({ label: 'Income verification', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-3.1' }) },
  { test: /eligible|credit_band|credit_score|\bband=|thin_file|bankruptcy|\bscore=/i, def: () => ({ label: 'Credit score / band evaluation', layer: 'agency', citation: 'Fannie Mae Selling Guide B3-5.1' }) },
  { test: /\bltv\b|ltv=/i, def: () => ({ label: 'Loan-to-value evaluation', layer: 'agency', citation: 'Fannie Mae Selling Guide B2-1.3 / FHA 4000.1' }) },
  { test: /title/i, def: () => ({ label: 'Title review', layer: 'lender' }) },
  { test: /\brate\b|rate=|llpa|pricing/i, def: () => ({ label: 'Pricing / rate evaluation', layer: 'lender' }) },
  { test: /insurance/i, def: () => ({ label: 'Insurance coverage check', layer: 'lender' }) },
  { test: /minor_data_gap|minor/i, def: () => ({ label: 'Minor data gap — routed for review', layer: 'system' }) },
]

// Strip a trailing "→ allow" / "-> escalate" outcome suffix.
const stripOutcome = (rule: string) => rule.replace(/\s*(?:->|→).*$/, '').trim()

// Operator-aware humanizer for anything we don't recognize.
function humanize(rule: string): string {
  const s = stripOutcome(rule)
    .replace(/\s*&&\s*|\s+AND\s+/gi, ' and ')
    .replace(/\s*\|\|\s*|\s+OR\s+/gi, ' or ')
    .replace(/>=/g, 'at least')
    .replace(/<=/g, 'at most')
    .replace(/==/g, 'equals')
    .replace(/!=/g, 'does not equal')
    .replace(/>/g, 'exceeds')
    .replace(/</g, 'is below')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Resolve a boundary-rule expression (or ID) to a plain-English definition. */
export function resolveRule(ruleId: string): RuleDefinition {
  const raw = (ruleId || '').trim()
  if (RULE_LABELS[raw]) return RULE_LABELS[raw]
  const stripped = stripOutcome(raw)
  if (RULE_LABELS[stripped]) return RULE_LABELS[stripped]
  for (const { test, def } of KEYWORD_RULES) {
    if (test.test(raw)) return def(raw)
  }
  // Unknown — humanize and default to a lender (internal) classification.
  return { label: humanize(raw), layer: 'lender' }
}
