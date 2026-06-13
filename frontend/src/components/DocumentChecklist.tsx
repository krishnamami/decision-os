import { useEffect, useState } from 'react'
import { fetchDocuments, requestInfo, type DocItem, type DocsResponse } from '../api/client'
import ExtractionDetail from './ExtractionDetail'

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '')

export default function DocumentChecklist({ applicationId }: { applicationId: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<DocsResponse | null>(null)
  const [openDoc, setOpenDoc] = useState<DocItem | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    if (open && !data) fetchDocuments(applicationId).then(setData).catch(() => undefined)
  }, [open, data, applicationId])

  async function requestMissing() {
    if (!data) return
    try {
      await requestInfo({ application_id: applicationId, items: data.missing_documents.map((m) => m.display_name), note: 'Please provide the missing documents listed.' })
      setMsg(`Requested ${data.missing_documents.length} document(s).`)
    } catch {
      setMsg('Could not send the request.')
    }
  }

  const count = data ? `${data.summary.total_on_file} of ${data.summary.total_on_file + data.summary.total_missing}` : ''

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span className="font-semibold text-slate-900">📄 Documents on file{count ? ` (${count})` : ''}</span>
        <span className="text-sm text-slate-400">{open ? '▼' : '▶ click to expand'}</span>
      </button>

      {open && (
        <div className="border-t border-slate-100 p-5">
          {!data ? <p className="text-sm text-slate-400">Loading documents…</p> : (
            <div className="space-y-4">
              {/* ON FILE */}
              <div className="overflow-hidden rounded-lg border border-l-4 border-slate-200 border-l-green-500 bg-white">
                <div className="bg-green-50/60 px-4 py-2 text-xs font-bold uppercase tracking-wide text-green-700">On file</div>
                {data.documents.map((d) => (
                  <div key={d.document_id} className="flex items-center gap-3 border-b border-slate-50 px-4 py-2.5 last:border-0">
                    <span>✅</span>
                    <span className="flex-1 font-medium text-slate-800">{d.display_name}</span>
                    <span className="w-16 text-xs text-slate-400">{fmtDate(d.indexed_at)}</span>
                    <span className="w-28 text-right font-mono text-sm font-semibold text-slate-700">{d.key_value || ''}</span>
                    <button onClick={() => setOpenDoc(d)} title="View extraction detail" className="rounded px-1.5 text-slate-400 hover:text-brand">↗</button>
                  </div>
                ))}
                {data.documents.length === 0 && <div className="px-4 py-3 text-sm text-slate-400">No documents indexed.</div>}
              </div>

              {/* MISSING */}
              {data.missing_documents.length > 0 && (
                <div className="overflow-hidden rounded-lg border border-l-4 border-rose-200 border-l-red-500 bg-rose-50/40">
                  <div className="px-4 py-2 text-xs font-bold uppercase tracking-wide text-red-700">Missing</div>
                  {data.missing_documents.map((m) => (
                    <div key={m.document_type} className="flex items-center gap-3 border-b border-rose-100 px-4 py-2.5 last:border-0">
                      <span>❌</span>
                      <span className="flex-1 font-medium text-slate-700">{m.display_name}</span>
                      <span className="text-xs text-slate-500">{m.reason}</span>
                    </div>
                  ))}
                </div>
              )}

              {data.missing_documents.length > 0 && (
                <div className="flex items-center gap-3">
                  <button onClick={requestMissing} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">📧 Request missing documents</button>
                  {msg && <span className="text-sm font-medium text-green-700">{msg}</span>}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {openDoc && data && <ExtractionDetail doc={openDoc} allDocs={data.documents} onClose={() => setOpenDoc(null)} onOpenDoc={(id) => setOpenDoc(data.documents.find((d) => d.document_id === id) || null)} />}
    </section>
  )
}
