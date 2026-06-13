import { useEffect, useState } from 'react'
import { fetchDataFreshness, type DataSource } from '../api/client'

// "X ago" for recent timestamps; an absolute date for older ones.
export function freshnessLabel(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const diff = Date.now() - then
  const h = diff / 3_600_000
  if (h < 1) return `${Math.max(1, Math.round(diff / 60_000))} min ago`
  if (h < 36) return `${Math.round(h)} hours ago`
  const d = h / 24
  if (d < 14) return `${Math.round(d)} days ago`
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function nextLabel(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

// App-wide banner: shown only when a data source is stale/errored (Part 8).
export function StaleDataBanner() {
  const [stale, setStale] = useState<DataSource[]>([])
  useEffect(() => {
    fetchDataFreshness().then((d) => setStale(d.stale)).catch(() => undefined)
  }, [])
  if (!stale.length) return null
  const s = stale[0]
  return (
    <div className="flex items-center justify-center gap-2 bg-amber-500 px-4 py-1.5 text-sm font-medium text-white">
      ⚠ {s.source_name} is stale ({freshnessLabel(s.last_success)}). {s.source_id === 'ofac_sdn' ? 'Fraud screening may use outdated data.' : 'Eligibility checks may use outdated data.'}
    </div>
  )
}

const STATUS_META: Record<string, { icon: string; label: string; cls: string }> = {
  ok: { icon: '✅', label: 'OK', cls: 'text-green-700' },
  stale: { icon: '⚠️', label: 'STALE', cls: 'text-amber-600' },
  error: { icon: '🔴', label: 'ERROR', cls: 'text-red-600' },
}

export default function DataFreshness() {
  const [sources, setSources] = useState<DataSource[]>([])
  const [allOk, setAllOk] = useState(true)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDataFreshness()
      .then((d) => { setSources(d.sources); setAllOk(d.all_ok) })
      .catch(() => undefined)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-4 text-sm text-slate-400">Loading data sources…</div>

  return (
    <div>
      <div className="mb-3">
        <h3 className="text-sm font-bold text-slate-900">📡 Data Freshness</h3>
        <p className="text-xs text-slate-500">Every data source powering Accord's decisions.</p>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2 text-left">Last updated</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-left">Next</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sources.map((s) => {
              const meta = STATUS_META[s.status] ?? STATUS_META.ok
              return (
                <tr key={s.source_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium text-slate-800">
                    {s.source_url ? (
                      <a href={s.source_url} target="_blank" rel="noreferrer" className="hover:text-brand hover:underline">{s.source_name}</a>
                    ) : s.source_name}
                    {s.record_count != null && <span className="ml-2 text-xs text-slate-400">{s.record_count.toLocaleString()} records</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{freshnessLabel(s.last_success)}</td>
                  <td className={`px-3 py-2 font-semibold ${meta.cls}`}>{meta.icon} {meta.label}</td>
                  <td className="px-3 py-2 text-slate-500">{nextLabel(s.next_scheduled)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className={`mt-3 text-sm ${allOk ? 'text-green-700' : 'text-amber-600'}`}>
        {allOk ? 'All sources current. No action needed.' : 'Some sources are stale — fraud and eligibility checks may use outdated data.'}
      </p>
    </div>
  )
}
