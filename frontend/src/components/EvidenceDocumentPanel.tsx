// Slide-over that shows what Accord extracted from a single evidence document,
// how confident it was, who verified it, and a link into EDMS. Purely
// presentational — callers (PersonaAccordion) derive the props from a DocItem.

const EDMS_BASE = 'http://accord-alb-588286075.us-east-1.elb.amazonaws.com'

export interface EvidenceDocumentPanelProps {
  documentName: string
  documentType: string // short badge text, e.g. "W-2", "Bank Statement"
  category?: string | null // document_category, e.g. "income", "property"
  extractedValue?: string | null // e.g. "Gross annual income: $95,000"
  confidence?: number | null // 0..1 fraction
  source?: string | null // verifying service, e.g. "Experian", "TWN", "AMC"
  page?: number | string | null // page reference, if known
  edmsId?: string | null
  onClose: () => void
}

const prettyCategory = (c: string) => c.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase())

export function EvidenceDocumentPanel({
  documentName, documentType, category, extractedValue, confidence, source, page, edmsId, onClose,
}: EvidenceDocumentPanelProps) {
  const pct = confidence != null ? Math.round(confidence * 100) : null
  const bar = pct == null ? 'bg-slate-300' : pct >= 90 ? 'bg-green-500' : pct >= 75 ? 'bg-amber-500' : 'bg-red-500'
  const txt = pct == null ? 'text-slate-400' : pct >= 90 ? 'text-green-700' : pct >= 75 ? 'text-amber-700' : 'text-red-700'
  const edmsUrl = edmsId ? `${EDMS_BASE}/documents/${edmsId}` : `${EDMS_BASE}/documents`

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="flex-1 bg-black/30" />
      <div className="w-[460px] max-w-full animate-[slideIn_.2s_ease] overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <style>{`@keyframes slideIn{from{transform:translateX(40px);opacity:.6}to{transform:none;opacity:1}}`}</style>

        {/* Header: name + type badge */}
        <div className="border-b border-slate-100 p-5">
          <button onClick={onClose} className="mb-3 text-sm font-medium text-brand hover:underline">← Back</button>
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-xl font-bold text-slate-900">📄 {documentName}</h2>
            <div className="mt-1 flex shrink-0 flex-col items-end gap-1">
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">{documentType}</span>
              {category && <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">{prettyCategory(category)}</span>}
            </div>
          </div>
        </div>

        <div className="space-y-5 p-5">
          {/* Extracted value */}
          <div>
            <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Extracted value</div>
            {extractedValue
              ? <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800">{extractedValue}</div>
              : <div className="text-sm text-slate-400">No single extracted value for this document.</div>}
          </div>

          {/* Confidence bar */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Confidence</span>
              <span className={`text-sm font-semibold ${txt}`}>{pct != null ? `${pct}%` : '—'}</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct ?? 0}%` }} />
            </div>
          </div>

          {/* Source + page */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <div className="mb-0.5 text-xs font-bold uppercase tracking-wide text-slate-500">Source</div>
              <div className="font-medium text-slate-800">{source || 'Lender upload'}</div>
            </div>
            {page != null && page !== '' && (
              <div>
                <div className="mb-0.5 text-xs font-bold uppercase tracking-wide text-slate-500">Page</div>
                <div className="font-medium text-slate-800">Page {page}</div>
              </div>
            )}
          </div>
        </div>

        {/* View in EDMS */}
        <div className="border-t border-slate-100 p-5">
          <a
            href={edmsUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
          >
            View in EDMS ↗
          </a>
          {!edmsId && <p className="mt-2 text-xs text-slate-400">Opens the EDMS document simulator.</p>}
        </div>
      </div>
    </div>
  )
}
