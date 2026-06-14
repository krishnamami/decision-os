import { useMemo, useState } from 'react'
import type { DocItem } from '../../api/client'
import { EvidenceDocumentPanel } from '../EvidenceDocumentPanel'
import { SOURCE_BY_TYPE, TYPE_BADGE, extractedValueText, panelPropsFromDoc } from '../evidenceDoc'

const confBar = (c: number | null) => (c == null ? 'bg-slate-300' : c >= 0.9 ? 'bg-green-500' : c >= 0.75 ? 'bg-amber-500' : 'bg-red-500')
const prettyCat = (c: string) => c.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase())

export default function EvidenceTab({ docs }: { docs: DocItem[] }) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const [sort, setSort] = useState<'confidence' | 'date' | 'type'>('confidence')
  const [openDoc, setOpenDoc] = useState<DocItem | null>(null)

  const cats = useMemo(() => [...new Set(docs.map((d) => d.document_category).filter((c): c is string => !!c))].sort(), [docs])
  const grouped = useMemo(() => {
    let list = docs.filter((d) =>
      (cat === 'all' || d.document_category === cat) &&
      (!q || `${d.display_name} ${d.document_type}`.toLowerCase().includes(q.toLowerCase())))
    if (sort === 'confidence') list = [...list].sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    else if (sort === 'type') list = [...list].sort((a, b) => (a.document_type || '').localeCompare(b.document_type || ''))
    else list = [...list].sort((a, b) => (b.indexed_at || '').localeCompare(a.indexed_at || ''))
    const g: Record<string, DocItem[]> = {}
    for (const d of list) (g[d.document_category || 'other'] ??= []).push(d)
    return g
  }, [docs, q, cat, sort])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search documents…" className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-brand" />
        <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand">
          <option value="all">All areas</option>
          {cats.map((c) => <option key={c} value={c}>{prettyCat(c)}</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-brand">
          <option value="confidence">Confidence</option>
          <option value="date">Date</option>
          <option value="type">Type</option>
        </select>
      </div>

      {Object.keys(grouped).length === 0 && <p className="text-sm text-slate-400">No documents match.</p>}
      {Object.entries(grouped).map(([category, list]) => (
        <div key={category} className="mb-5">
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">{prettyCat(category)}</div>
          <div className="space-y-2">
            {list.map((d) => {
              const pct = d.confidence != null ? Math.round(d.confidence * 100) : null
              return (
                <div key={d.document_id} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-800">{d.display_name} <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">{TYPE_BADGE[d.document_type] ?? d.document_type}</span></div>
                    <button onClick={() => setOpenDoc(d)} className="shrink-0 text-sm font-medium text-brand hover:underline">View extracted data →</button>
                  </div>
                  {extractedValueText(d) && <div className="mt-1 text-sm text-slate-700">{extractedValueText(d)}</div>}
                  <div className="mt-2 flex items-center gap-3 text-xs text-slate-500">
                    <div className="flex items-center gap-1.5">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${confBar(d.confidence)}`} style={{ width: `${pct ?? 0}%` }} /></div>
                      <span>{pct != null ? `${pct}%` : '—'}</span>
                    </div>
                    <span>· {SOURCE_BY_TYPE[d.document_type] ?? 'Lender upload'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {openDoc && <EvidenceDocumentPanel {...panelPropsFromDoc(openDoc)} onClose={() => setOpenDoc(null)} />}
    </div>
  )
}
