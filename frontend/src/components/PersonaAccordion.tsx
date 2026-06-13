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

// Short type badge per document_type.
const TYPE_BADGE: Record<string, string> = {
  W2_CURRENT: 'W-2', W2_PRIOR: 'W-2', PAY_STUBS: 'Pay Stub', PAYSTUB: 'Pay Stub',
  BANK_STATEMENT: 'Bank Statement', BANK_STATEMENTS: 'Bank Statement', CREDIT_REPORT: 'Credit Report',
  IRS_TRANSCRIPT: 'IRS Transcript', URLA_1003: 'URLA 1003', DRIVERS_LICENSE: "Driver's License",
  PURCHASE_AGREEMENT: 'Purchase Agreement', APPRAISAL_URAR: 'Appraisal', OFAC_CHECK: 'OFAC Check',
  EMPLOYER_VERIFICATION: 'VOE', VOE: 'VOE',
}
// Which service typically verifies each document type.
const SOURCE_BY_TYPE: Record<string, string> = {
  CREDIT_REPORT: 'Experian', W2_CURRENT: 'The Work Number (TWN)', W2_PRIOR: 'The Work Number (TWN)',
  PAY_STUBS: 'The Work Number (TWN)', PAYSTUB: 'The Work Number (TWN)',
  EMPLOYER_VERIFICATION: 'The Work Number (TWN)', VOE: 'The Work Number (TWN)',
  BANK_STATEMENT: 'Argyle', BANK_STATEMENTS: 'Argyle', IRS_TRANSCRIPT: 'IRS (4506-C)',
  APPRAISAL_URAR: 'AMC', OFAC_CHECK: 'OFAC / Treasury',
  URLA_1003: 'Lender upload', PURCHASE_AGREEMENT: 'Lender upload', DRIVERS_LICENSE: 'Lender upload',
}
// Friendly label for the document's key extracted field.
const FIELD_LABEL: Record<string, string> = {
  box1_wages: 'Gross annual income', gross_monthly_income: 'Gross monthly income',
  stated_income_monthly: 'Stated annual income', adjusted_gross_income: 'Adjusted gross income',
  mid_score: 'Credit score (mid)', total_balance: 'Total balance', appraised_value: 'Appraised value',
  purchase_price: 'Purchase price', match_score: 'Watchlist match score',
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
  const isDefaultEscalate = ruleStr.toLowerCase() === 'default escalate'

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
              {isDefaultEscalate ? (
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-start">
                    <RuleLayerBadge layer="system" />
                    <div>
                      <p className="text-[15px] leading-relaxed text-slate-700">
                        No specific rule matched for this check. The system escalated to a human reviewer because the
                        data didn&apos;t clearly pass or fail any defined threshold.
                      </p>
                      <p className="mt-2 text-sm leading-relaxed text-slate-500">
                        This typically means: missing data, edge case values, or a scenario not covered by current rules.
                      </p>
                    </div>
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
