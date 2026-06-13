import { useEffect, useState } from 'react'
import { fetchDocuments, fetchSourceMatch, type DocItem, type SourceMatchResponse } from '../api/client'
import ExtractionDetail from './ExtractionDetail'

const CAT_LABEL: Record<string, string> = {
  income: 'Income', credit: 'Credit', property: 'Property', loan_terms: 'Loan Terms', identity: 'Identity', employment: 'Employment',
}

export default function SourceMatch({ applicationId }: { applicationId: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<SourceMatchResponse | null>(null)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    if (open && !data) {
      fetchSourceMatch(applicationId).then(setData).catch(() => undefined)
      fetchDocuments(applicationId).then((d) => setDocs(d.documents)).catch(() => undefined)
    }
  }, [open, data, applicationId])

  const anyDiscrepancy = data?.verifications.some((v) => v.discrepancy.exists)
  const openDoc = docs.find((d) => d.document_id === openId) || null

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span className="font-semibold text-slate-900">📊 Verify data sources</span>
        <span className="text-sm text-slate-400">{open ? '▼' : '▶ click to expand'}</span>
      </button>

      {open && (
        <div className="border-t border-slate-100 p-5">
          {!data ? <p className="text-sm text-slate-400">Tracing data points to source documents…</p> : (
            <div className="space-y-5">
              <p className="text-sm text-slate-500">Every data point traced to its source document.</p>
              {data.verifications.map((v) => (
                <div key={v.category}>
                  <div className="mb-1 border-b border-slate-100 pb-1 text-xs font-bold uppercase tracking-widest text-slate-400">{CAT_LABEL[v.category] || v.category}</div>
                  <div className="overflow-hidden rounded-lg">
                    {v.fields.map((f, i) => (
                      <div key={f.field_name} className={`flex items-center gap-3 px-2 py-2 text-sm ${i % 2 ? 'bg-slate-50/60' : ''}`}>
                        <span className="w-40 text-slate-600">{f.field_name}</span>
                        <span className="w-36 text-xs text-slate-400">{f.source_document}</span>
                        <span className="flex-1 font-mono font-semibold text-slate-900">{f.display_value}</span>
                        {f.status === 'computed'
                          ? <span className="text-xs text-slate-400">(computed)</span>
                          : f.document_id
                            ? <button onClick={() => setOpenId(f.document_id)} className="rounded px-1.5 text-xs font-medium text-slate-500 hover:text-brand">📄 View</button>
                            : <span className="text-xs text-red-500">❌ missing</span>}
                      </div>
                    ))}
                  </div>
                  {v.discrepancy.exists
                    ? <div className="mt-1 rounded-lg bg-amber-50 px-3 py-2 text-sm">
                        <span className="font-semibold text-amber-700">⚠ Discrepancy:</span> <span className="text-slate-700">{v.discrepancy.description}</span>
                        {v.discrepancy.ai_used && <div className="mt-0.5 text-xs font-semibold text-slate-700">AI used: {v.discrepancy.ai_used}</div>}
                      </div>
                    : <div className="mt-1 text-sm text-green-700">✅ {v.discrepancy.description || 'No discrepancies'}</div>}
                </div>
              ))}
              <div className={`rounded-lg p-3 text-sm font-medium ${anyDiscrepancy ? 'bg-amber-50 text-amber-700' : 'bg-green-50 text-green-700'}`}>
                {anyDiscrepancy ? '⚠ Some data points have discrepancies — review the flagged sections above.' : '✅ All data sources verified — no discrepancies.'}
              </div>
            </div>
          )}
        </div>
      )}

      {openDoc && <ExtractionDetail doc={openDoc} allDocs={docs} onClose={() => setOpenId(null)} onOpenDoc={(id) => setOpenId(id)} />}
    </section>
  )
}
