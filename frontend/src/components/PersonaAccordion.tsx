import { useEffect, useState } from 'react'
import type { DecisionDetail, Evidence } from '../types/accord'
import { fetchDocuments, type DocItem } from '../api/client'
import { resolveRule } from '../config/ruleLabels'
import { RuleLayerBadge } from './RuleLayerBadge'
import DecisionPill, { outcomeMeta } from './DecisionPill'
import { EvidenceDocumentPanel, type EvidenceDocumentPanelProps } from './EvidenceDocumentPanel'

const SIGNAL_DOT: Record<string, string> = {
  pass: 'bg-green-500',
  fail: 'bg-red-500',
  warn: 'bg-amber-500',
  no_data: 'bg-slate-300',
  info: 'bg-slate-400',
}

// "default escalate" is a system fallback, not a policy rule — detect it so we
// render an amber review notice (no layer badge) instead of a rule.
const isDefaultEscalate = (ruleId: string | null | undefined) =>
  ['default_escalate', 'default escalate', 'escalate_default'].includes((ruleId || '').trim().toLowerCase())

// Match a free-text evidence name to an indexed document.
function matchDoc(name: string, docs: DocItem[]): DocItem | undefined {
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')
  const n = norm(name)
  if (!n) return undefined
  return docs.find((d) => {
    const dn = norm(d.display_name)
    const dt = norm(d.document_type)
    return dn === n || dt === n || dn.includes(n) || n.includes(dn) || (!!dt && (dt.includes(n) || n.includes(dt)))
  })
}

// Short type badge per document_type — reconciled against all 53 live types.
const TYPE_BADGE: Record<string, string> = {
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
const SOURCE_BY_TYPE: Record<string, string> = {
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
const FIELD_LABEL: Record<string, string> = {
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

function extractedValueText(doc: DocItem | null): string | null {
  if (!doc) return null
  if (doc.key_value) {
    const label = FIELD_LABEL[doc.key_field ?? ''] ?? (doc.key_field ? humanizeField(doc.key_field) : 'Extracted value')
    return `${label}: ${doc.key_value}`
  }
  const entries = Object.entries(doc.extracted_data || {}).filter(([, v]) => v != null && typeof v !== 'object')
  if (entries.length) return entries.slice(0, 2).map(([k, v]) => `${humanizeField(k)}: ${fmtVal(v)}`).join(' · ')
  return null
}

// Derive the EvidenceDocumentPanel props from an evidence row + its matched doc.
function buildEvidenceProps(ev: Evidence, doc: DocItem | null): Omit<EvidenceDocumentPanelProps, 'onClose'> {
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

export default function PersonaAccordion({ decisions, applicationId }: { decisions: DecisionDetail[]; applicationId?: string }) {
  // One open decision per stage. Default: open the first blocking/escalating one.
  const [openByWave, setOpenByWave] = useState<Record<number, string | null>>(() => {
    const blocker = decisions.find((d) => d.outcome === 'block' || d.outcome === 'escalate')
    return blocker ? { [blocker.wave]: blocker.decision_id } : {}
  })
  // Indexed documents, so evidence rows can open the real extraction.
  const [docs, setDocs] = useState<DocItem[]>([])
  useEffect(() => {
    if (!applicationId) return
    let alive = true
    fetchDocuments(applicationId).then((d) => alive && setDocs(d.documents)).catch(() => undefined)
    return () => { alive = false }
  }, [applicationId])

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
                      docs={docs}
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

function DecisionRow({ d, docs, open, onToggle }: { d: DecisionDetail; docs: DocItem[]; open: boolean; onToggle: () => void }) {
  const m = outcomeMeta(d.outcome)
  const [openEv, setOpenEv] = useState<Omit<EvidenceDocumentPanelProps, 'onClose'> | null>(null)
  const ruleStr = (d.rule || '').trim()
  const defaultEscalate = isDefaultEscalate(ruleStr)

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

          {/* Rule applied */}
          {d.rule && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">Rule applied</div>
              {defaultEscalate ? (
                <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <span className="text-xl">⚠️</span>
                  <div>
                    <p className="font-semibold text-amber-800">Escalated for underwriter review</p>
                    <p className="mt-1 text-sm text-amber-700">
                      No automated rule triggered a clear approve or decline. This file requires underwriter judgment.
                      All conditions fall within acceptable ranges, but compensating factors or incomplete data prevent
                      an automated decision.
                    </p>
                  </div>
                </div>
              ) : (
                (() => {
                  const def = resolveRule(ruleStr)
                  // Many engine rules already carry their own "→ outcome" suffix;
                  // only append one when it's missing, to avoid "→ block → block".
                  const codeLine = /(?:->|→)/.test(ruleStr) ? ruleStr : `${ruleStr} → ${d.outcome}`
                  return (
                    <div className="rounded-lg border border-slate-200 bg-white p-4">
                      <div className="flex items-start">
                        <RuleLayerBadge layer={def.layer} />
                        <div>
                          <p className="text-[15px] font-medium text-[#374151]">{def.label}</p>
                          {def.citation && <p className="mt-0.5 text-xs text-slate-500">Citation: {def.citation}</p>}
                        </div>
                      </div>
                      <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 px-3 py-2 font-mono text-[12px] leading-relaxed text-slate-100">
                        {codeLine}
                      </pre>
                    </div>
                  )
                })()
              )}
            </div>
          )}

          {/* Evidence — each document is clickable */}
          {d.evidence.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Evidence</div>
              <ul className="space-y-1">
                {d.evidence.map((e, i) => {
                  const doc = matchDoc(e.document, docs)
                  return (
                    <li key={i}>
                      <button
                        onClick={() => setOpenEv(buildEvidenceProps(e, doc ?? null))}
                        title="View extracted data"
                        className="group flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-white hover:shadow-sm"
                      >
                        <span className="text-slate-400">📄</span>
                        <span className="font-medium text-slate-700 underline decoration-dotted decoration-slate-300 underline-offset-2 group-hover:decoration-brand">{e.document}</span>
                        <span className="text-slate-400">— {e.detail}</span>
                        <span className="ml-auto text-base text-slate-300 group-hover:text-brand">›</span>
                      </button>
                    </li>
                  )
                })}
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

          {/* Evidence document detail (slide-over) */}
          {openEv && <EvidenceDocumentPanel {...openEv} onClose={() => setOpenEv(null)} />}
        </div>
      )}
    </div>
  )
}
