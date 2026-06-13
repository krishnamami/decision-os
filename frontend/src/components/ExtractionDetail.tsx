import type { DocItem } from '../api/client'

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—')
const money = (v: any) => { const n = Number(v); return Number.isFinite(n) ? `$${n.toLocaleString()}` : String(v) }

// Fields that feed the AI evaluation via entity_states.
const USED = new Set(['box1_wages', 'employer_name', 'employee_name', 'tax_year', 'mid_score', 'appraised_value', 'purchase_price', 'stated_income_monthly', 'loan_amount', 'adjusted_gross_income', 'match_score', 'watchlist_match', 'dl_state', 'gross_monthly_income', 'total_balance'])
const MONEY_KEYS = new Set(['box1_wages', 'box2_fed_tax', 'box3_ss_wages', 'box5_medicare_wages', 'appraised_value', 'purchase_price', 'loan_amount', 'adjusted_gross_income', 'total_balance', 'gross_monthly_income', 'stated_income_monthly'])

function prettyKey(k: string) {
  return k.replace(/_/g, ' ').replace(/\bbox(\d)\b/i, 'Box $1').replace(/\b\w/g, (c) => c.toUpperCase())
}
function renderVal(k: string, v: any) {
  if (/ssn/i.test(k)) { const s = String(v); return `***-**-${s.slice(-4)}` }
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (MONEY_KEYS.has(k)) return money(v)
  if (Array.isArray(v)) return `${v.length} item(s)`
  if (v && typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// Plain-English "what the AI did" + cross-references, derived from the real docs.
function aiNarrative(doc: DocItem, all: DocItem[]): { text: JSX.Element; discrepancy: boolean } {
  const f = doc.extracted_data || {}
  const find = (t: string) => all.find((d) => d.document_type === t)
  if (doc.document_type.startsWith('W2')) {
    const w2 = Number(f.box1_wages)
    const urla = find('URLA_1003')
    const stated = urla ? Number(urla.extracted_data?.stated_income_monthly) * 12 : null
    const gap = stated && w2 ? Math.abs(stated - w2) / stated : 0
    const disc = gap > 0.25
    return {
      discrepancy: disc,
      text: (
        <div className="space-y-2 text-sm text-slate-700">
          <div><b>Income verification:</b> This W2 shows {money(w2)} annual income.{stated ? ` Borrower stated ${money(stated)} on the URLA.` : ''}{stated ? ` Discrepancy: ${(gap * 100).toFixed(0)}% (${disc ? 'above' : 'within'} 25% threshold). AI decision: ${disc ? 'BLOCK income verification' : 'income verified'}.` : ''}</div>
          {f.employer_name && <div><b>Employment verification:</b> Employer {f.employer_name}{f.employer_ein ? ` (EIN ${f.employer_ein})` : ''}.</div>}
        </div>
      ),
    }
  }
  if (doc.document_type === 'APPRAISAL_URAR') {
    const apr = Number(f.appraised_value)
    const pa = find('PURCHASE_AGREEMENT')
    const price = pa ? Number(pa.extracted_data?.purchase_price) : null
    const short = price != null && apr < price
    return { discrepancy: !!short, text: <div className="text-sm text-slate-700"><b>Collateral analysis:</b> Appraised at {money(apr)}{price != null ? `; purchase price ${money(price)}. ${short ? 'Value shortfall — collateral does not support the price.' : 'Appraised ≥ purchase price; adequate equity.'}` : '.'}</div> }
  }
  if (doc.document_type === 'CREDIT_REPORT') {
    return { discrepancy: false, text: <div className="text-sm text-slate-700"><b>Credit assessment:</b> Mid score {f.mid_score}. {f.active_bankruptcy ? 'Active bankruptcy on file.' : 'No active bankruptcy.'} {f.no_derogatory_last_24_months ? 'No derogatory marks in 24 months.' : ''}</div> }
  }
  if (doc.document_type === 'OFAC_CHECK') {
    return { discrepancy: !!f.watchlist_match, text: <div className="text-sm text-slate-700"><b>Fraud screening:</b> {f.watchlist_match ? `Watchlist match "${f.match_name}" at ${(Number(f.match_score) * 100).toFixed(0)}% — mandatory BSA review.` : 'No watchlist match.'}</div> }
  }
  if (doc.document_type === 'DRIVERS_LICENSE') {
    return { discrepancy: !!f.expired || f.photo_match === false, text: <div className="text-sm text-slate-700"><b>Identity:</b> {f.expired ? 'License is EXPIRED. ' : ''}{f.photo_match === false ? 'Photo did not match. ' : ''}Issuing state {f.dl_state}.</div> }
  }
  return { discrepancy: false, text: <div className="text-sm text-slate-700">This document’s fields feed the AI evaluation via <span className="font-mono text-xs">entity_states</span>.</div> }
}

function crossRefs(doc: DocItem, all: DocItem[]) {
  if (!doc.document_type.startsWith('W2')) return []
  const w2 = Number(doc.extracted_data?.box1_wages)
  const out: Array<{ doc: DocItem; ok: boolean; note: string }> = []
  const irs = all.find((d) => d.document_type === 'IRS_TRANSCRIPT')
  if (irs) { const v = Number(irs.extracted_data?.adjusted_gross_income); out.push({ doc: irs, ok: Math.abs(v - w2) / w2 < 0.1, note: `income ${Math.abs(v - w2) / w2 < 0.1 ? 'matches' : 'differs'} (${money(v)})` }) }
  const urla = all.find((d) => d.document_type === 'URLA_1003')
  if (urla) { const v = Number(urla.extracted_data?.stated_income_monthly) * 12; out.push({ doc: urla, ok: Math.abs(v - w2) / w2 < 0.25, note: `income ${Math.abs(v - w2) / w2 < 0.25 ? 'matches' : 'CONFLICTS'} (${money(v)})` }) }
  return out
}

export default function ExtractionDetail({ doc, allDocs, onClose, onOpenDoc }: {
  doc: DocItem; allDocs: DocItem[]; onClose: () => void; onOpenDoc: (id: string) => void
}) {
  const narr = aiNarrative(doc, allDocs)
  const xrefs = crossRefs(doc, allDocs)
  const entries = Object.entries(doc.extracted_data || {})

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="flex-1 bg-black/30" />
      <div className="w-[480px] max-w-full animate-[slideIn_.2s_ease] overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <style>{`@keyframes slideIn{from{transform:translateX(40px);opacity:.6}to{transform:none;opacity:1}}`}</style>
        <div className="border-b border-slate-100 p-5">
          <button onClick={onClose} className="mb-3 text-sm font-medium text-brand hover:underline">← Back</button>
          <h2 className="text-lg font-bold text-slate-900">📄 {doc.display_name}</h2>
          <p className="text-sm text-slate-500">
            Indexed {fmtDate(doc.indexed_at)}{doc.confidence != null ? ` · ${Math.round(doc.confidence * 100)}% confidence` : ''}{doc.extraction_method ? ` · ${doc.extraction_method.replace('_', ' ')}` : ''}
          </p>
        </div>

        <div className="p-5">
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Extracted fields</div>
          <div className="divide-y divide-slate-100">
            {entries.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="text-slate-600">{prettyKey(k)}{/ssn/i.test(k) && <span className="ml-1 text-xs text-slate-400">(masked)</span>}</span>
                <span className="flex items-center gap-2">
                  <span className="font-mono font-semibold text-slate-900">{renderVal(k, v)}</span>
                  {USED.has(k) && <span className="rounded-full bg-green-50 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">→ used</span>}
                </span>
              </div>
            ))}
            {entries.length === 0 && <p className="py-2 text-sm text-slate-400">No structured fields extracted.</p>}
          </div>
          <p className="mt-2 text-xs text-slate-400">“→ used” means this field feeds the AI evaluation via entity_states.</p>
        </div>

        <div className="px-5 pb-5">
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">What AI did with this data</div>
          <div className={`rounded-lg p-3 ${narr.discrepancy ? 'bg-amber-50' : 'bg-green-50'}`}>{narr.text}</div>
        </div>

        {xrefs.length > 0 && (
          <div className="px-5 pb-5">
            <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Cross-references</div>
            <p className="mb-2 text-xs text-slate-500">This document was compared against:</p>
            <div className="space-y-1.5">
              {xrefs.map((x) => (
                <button key={x.doc.document_id} onClick={() => onOpenDoc(x.doc.document_id)} className="flex w-full items-center gap-2 rounded-lg border border-slate-200 p-2 text-left text-sm hover:border-brand/40">
                  <span>{x.ok ? '✅' : '⚠'}</span>
                  <span className="font-medium text-slate-800">📄 {x.doc.display_name}</span>
                  <span className="text-slate-500">→ {x.note}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="border-t border-slate-100 p-5">
          {doc.file_path
            ? <a href="#" onClick={(e) => { e.preventDefault(); alert('PDF viewer (pdf.js) is a production feature.\nSource: ' + doc.file_path) }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">View original PDF</a>
            : <span className="text-sm text-slate-400">Original document not available</span>}
        </div>
      </div>
    </div>
  )
}
