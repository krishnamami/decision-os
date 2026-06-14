// Shared mapping from an indexed document (DocItem) to EvidenceDocumentPanel
// props — type badge, verifying source service, friendly field label, and the
// single headline extracted value. Reconciled against all 53 live document
// types. Used by PersonaAccordion (evidence rows) and LoanDetail (clickable
// summary metrics) so there is one source of truth.
import type { DocItem } from '../api/client'
import type { Evidence } from '../types/accord'
import type { EvidenceDocumentPanelProps } from './EvidenceDocumentPanel'

// Short type badge per document_type.
export const TYPE_BADGE: Record<string, string> = {
  // income
  W2_CURRENT: 'W-2', W2_PRIOR: 'W-2', PAYSTUB_CURRENT: 'Pay Stub', IRS_TRANSCRIPT: 'IRS Transcript',
  TAX_RETURN_1040: '1040', '1099_NEC': '1099-NEC', SCHEDULE_C: 'Schedule C', SCHEDULE_E: 'Schedule E',
  COMMISSION_HISTORY: 'Commission', OFFER_LETTER: 'Offer Letter', EMPLOYMENT_GAP_LETTER: 'Gap Letter',
  PENSION_LETTER: 'Pension', SSA_AWARD_LETTER: 'SSA Award', RENTAL_LEASE: 'Lease',
  FOREIGN_INCOME_DOCS: 'Foreign Income', FLOOD_INSURANCE: 'Flood Insurance',
  // employment
  VOE_TWN: 'VOE (TWN)', VOE: 'VOE',
  // credit
  CREDIT_REPORT: 'Credit Report',
  // asset
  BANK_STATEMENT_M1: 'Bank Statement', BANK_STATEMENT_M2: 'Bank Statement', BANK_STATEMENT_M3: 'Bank Statement',
  GIFT_LETTER: 'Gift Letter', GIFT_DONOR_BANK_STATEMENT: 'Gift Donor Stmt',
  // property
  APPRAISAL_URAR: 'Appraisal', PURCHASE_AGREEMENT: 'Purchase Agreement', BUILDER_CONTRACT: 'Builder Contract',
  CONDO_QUESTIONNAIRE: 'Condo Q', PROPERTY_TAX_BILL: 'Property Tax', FLOOD_CERT: 'Flood Cert',
  TITLE_COMMITMENT: 'Title Commitment', TITLE_INSURANCE: 'Title Insurance', HOI_BINDER: 'HOI Binder',
  // identity
  DRIVERS_LICENSE: "Driver's License", PASSPORT: 'Passport', SSN_VALIDATION: 'SSN', OFAC_CHECK: 'OFAC',
  EAD_CARD: 'EAD', I94: 'I-94', VISA_H1B: 'H-1B',
  // legal
  DIVORCE_DECREE: 'Divorce Decree', ALIMONY_RECEIPT_HISTORY: 'Alimony',
  // loan / loan_terms
  URLA_1003: 'URLA', CLOSING_DISCLOSURE: 'Closing Disclosure', LOAN_ESTIMATE: 'Loan Estimate',
  RATE_LOCK: 'Rate Lock', ESCROW_ANALYSIS: 'Escrow', MORTGAGE_PAYOFF: 'Payoff', PAYMENT_HISTORY_24MO: 'Pay History',
  // vendor
  AUS_DU_FINDINGS: 'AUS', MI_CERTIFICATE: 'MI Cert', USDA_ELIGIBILITY: 'USDA', VA_COE: 'VA COE',
}
// Which service typically verifies each document type.
const TWN = 'The Work Number (TWN)', IRS = 'IRS (4506-C)', UPLOAD = 'Lender upload', BUREAU = 'Credit Bureau (tri-merge)'
export const SOURCE_BY_TYPE: Record<string, string> = {
  // payroll / employment → TWN
  W2_CURRENT: TWN, W2_PRIOR: TWN, PAYSTUB_CURRENT: TWN, VOE_TWN: TWN, VOE: TWN, COMMISSION_HISTORY: TWN,
  // tax authority
  IRS_TRANSCRIPT: IRS, TAX_RETURN_1040: IRS, '1099_NEC': IRS, SCHEDULE_C: IRS, SCHEDULE_E: IRS,
  // credit bureau
  CREDIT_REPORT: BUREAU,
  // asset verification
  BANK_STATEMENT_M1: 'AccountChek (FormFree)', BANK_STATEMENT_M2: 'AccountChek (FormFree)', BANK_STATEMENT_M3: 'AccountChek (FormFree)',
  // appraisal / property vendors
  APPRAISAL_URAR: 'AMC (appraisal)', FLOOD_CERT: 'Flood Determination (CoreLogic)', PROPERTY_TAX_BILL: 'County Assessor',
  TITLE_COMMITMENT: 'Title Company', TITLE_INSURANCE: 'Title Company',
  // insurance
  HOI_BINDER: 'Insurance Carrier', FLOOD_INSURANCE: 'Insurance Carrier', MI_CERTIFICATE: 'MI Provider',
  // government / identity
  OFAC_CHECK: 'OFAC / Treasury', SSN_VALIDATION: 'Social Security Administration', SSA_AWARD_LETTER: 'Social Security Administration',
  EAD_CARD: 'USCIS / DHS', I94: 'USCIS / DHS', VISA_H1B: 'USCIS / DHS',
  USDA_ELIGIBILITY: 'USDA', VA_COE: 'U.S. Dept. of Veterans Affairs',
  // automated underwriting
  AUS_DU_FINDINGS: 'Desktop Underwriter (Fannie Mae)',
  // lender / servicer
  CLOSING_DISCLOSURE: 'Lender (TRID)', LOAN_ESTIMATE: 'Lender (TRID)', RATE_LOCK: 'Lender (rate desk)',
  ESCROW_ANALYSIS: 'Lender / Servicer', MORTGAGE_PAYOFF: 'Servicer', PAYMENT_HISTORY_24MO: 'Servicer',
  // court
  DIVORCE_DECREE: 'Court / Lender upload',
  // borrower-provided uploads
  URLA_1003: UPLOAD, PURCHASE_AGREEMENT: UPLOAD, BUILDER_CONTRACT: UPLOAD, CONDO_QUESTIONNAIRE: UPLOAD,
  GIFT_LETTER: UPLOAD, GIFT_DONOR_BANK_STATEMENT: UPLOAD, OFFER_LETTER: UPLOAD, EMPLOYMENT_GAP_LETTER: UPLOAD,
  PENSION_LETTER: UPLOAD, RENTAL_LEASE: UPLOAD, FOREIGN_INCOME_DOCS: UPLOAD, ALIMONY_RECEIPT_HISTORY: UPLOAD,
  DRIVERS_LICENSE: UPLOAD, PASSPORT: UPLOAD,
}
// Friendly label for the document's key extracted field (DOC_META `key` values).
export const FIELD_LABEL: Record<string, string> = {
  box1_wages: 'Gross annual income', gross_pay: 'Gross pay', agi: 'Adjusted gross income', total_income: 'Total income',
  net_profit: 'Net profit', net_rental_income: 'Net rental income', nonemployee_compensation: 'Nonemployee compensation',
  two_year_average: '2-yr average', salary: 'Offered salary', current_salary: 'Current salary', income_amount: 'Verified income',
  monthly_benefit: 'Monthly benefit', monthly_rent: 'Monthly rent', monthly_amount: 'Alimony received', alimony_monthly: 'Alimony',
  annual_income: 'Annual income', mid_score: 'Credit score (mid)', ending_balance: 'Ending balance',
  gift_amount: 'Gift amount', withdrawal_amount: 'Gift withdrawal', appraised_value: 'Appraised value',
  purchase_price: 'Purchase price', contract_price: 'Contract price', fannie_approved: 'Fannie approved',
  annual_tax: 'Annual property tax', flood_zone: 'Flood zone', coverage_amount: 'Coverage amount',
  coverage_dwelling: 'Dwelling coverage', mi_monthly: 'Monthly MI premium', loan_amount: 'Loan amount',
  trid_compliant: 'TRID compliant', section_a_total: 'Loan costs (Section A)', monthly_escrow: 'Monthly escrow',
  current_balance: 'Current balance', late_payments: 'Late payments (24mo)', recommendation: 'AUS recommendation',
  income_eligible: 'Income eligible', entitlement_amount: 'VA entitlement', alimony_amount: 'Alimony',
  monthly_premium: 'Monthly MI premium', policy_amount: 'Title coverage',
}
const humanizeField = (k: string) => k.replace(/_/g, ' ').replace(/\bbox(\d)\b/i, 'Box $1').replace(/\b\w/g, (c) => c.toUpperCase())
const fmtVal = (v: unknown) => (typeof v === 'boolean' ? (v ? 'Yes' : 'No') : Array.isArray(v) ? `${v.length} item(s)` : String(v))

export function extractedValueText(doc: DocItem | null): string | null {
  if (!doc) return null
  if (doc.key_value) {
    const label = FIELD_LABEL[doc.key_field ?? ''] ?? (doc.key_field ? humanizeField(doc.key_field) : 'Extracted value')
    return `${label}: ${doc.key_value}`
  }
  const entries = Object.entries(doc.extracted_data || {}).filter(([, v]) => v != null && typeof v !== 'object')
  if (entries.length) return entries.slice(0, 2).map(([k, v]) => `${humanizeField(k)}: ${fmtVal(v)}`).join(' · ')
  return null
}

// Build EvidenceDocumentPanel props from a DocItem alone (e.g. a summary metric).
export function panelPropsFromDoc(doc: DocItem): Omit<EvidenceDocumentPanelProps, 'onClose'> {
  const page = (doc.extracted_data?.page ?? doc.extracted_data?.page_number ?? null) as number | string | null
  return {
    documentName: doc.display_name || doc.document_type,
    documentType: TYPE_BADGE[doc.document_type] ?? doc.document_type,
    category: doc.document_category ?? null,
    extractedValue: extractedValueText(doc),
    confidence: doc.confidence,
    source: SOURCE_BY_TYPE[doc.document_type] ?? 'Lender upload',
    page,
    edmsId: doc.document_id ?? null,
  }
}

// Build EvidenceDocumentPanel props from an evidence row + its matched doc.
export function buildEvidenceProps(ev: Evidence, doc: DocItem | null): Omit<EvidenceDocumentPanelProps, 'onClose'> {
  const confMatch = /(\d+)\s*%/.exec(ev.detail || '')
  const confidence = doc?.confidence ?? (confMatch ? Number(confMatch[1]) / 100 : null)
  const page = (doc?.extracted_data?.page ?? doc?.extracted_data?.page_number ?? null) as number | string | null
  return {
    documentName: doc?.display_name || ev.document,
    documentType: doc ? TYPE_BADGE[doc.document_type] ?? ev.document : ev.document,
    category: doc?.document_category ?? null,
    extractedValue: extractedValueText(doc),
    confidence,
    source: doc ? SOURCE_BY_TYPE[doc.document_type] ?? 'Lender upload' : 'Lender upload',
    page,
    edmsId: doc?.document_id ?? null,
  }
}
