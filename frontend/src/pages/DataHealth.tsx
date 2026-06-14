import { useEffect, useState } from 'react'
import { fetchDataHealth, type DataHealthResponse, type DataSourceHealth } from '../api/client'

const CATEGORY: Record<string, { icon: string; label: string }> = {
  federal: { icon: '🔒', label: 'Federal' },
  agency: { icon: '📋', label: 'Agency' },
  system: { icon: '⚙️', label: 'System' },
  external: { icon: '🌐', label: 'External' },
}

const fmtTs = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : null

function StatusCell({ s }: { s: DataSourceHealth }) {
  if (s.category === 'system' && s.tests_total != null) {
    const ok = (s.tests_failed ?? 0) === 0
    return <span className={`font-medium ${ok ? 'text-green-700' : 'text-red-700'}`}>{ok ? '✅' : '🔴'} {s.tests_passed ?? 0}/{s.tests_total} passed</span>
  }
  switch (s.status) {
    case 'current': return <span className="font-medium text-green-700">✅ Current</span>
    case 'stale': return <span className="font-medium text-amber-700" title="Overdue for refresh">⚠️ Stale</span>
    case 'failing': return <span className="font-medium text-red-700" title={s.error || undefined}>🔴 Failing</span>
    default: return <span className="text-slate-400">— Not recorded</span>
  }
}

function StatCard({ label, value, tone = 'slate' }: { label: string; value: React.ReactNode; tone?: 'slate' | 'green' | 'amber' }) {
  const cls = tone === 'green' ? 'text-green-700' : tone === 'amber' ? 'text-amber-700' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${cls}`}>{value}</div>
    </div>
  )
}

export default function DataHealth() {
  const [data, setData] = useState<DataHealthResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchDataHealth().then((d) => alive && setData(d)).catch((e) => alive && setErr(e instanceof Error ? e.message : 'Failed to load'))
    return () => { alive = false }
  }, [])

  if (err) return <div className="p-10 text-center text-sm text-red-600">{err}</div>
  if (!data) return <div className="p-10 text-center text-sm text-slate-400">Checking every data source…</div>

  const sources = data.sources
  const stale = sources.filter((s) => s.status === 'stale' || s.status === 'failing').length
  const tests = sources.find((s) => s.tests_total != null)
  const sortedTs = sources.map((s) => s.last_updated).filter((x): x is string => !!x).sort()
  const lastChecked = sortedTs.length ? sortedTs[sortedTs.length - 1] : null

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <h1 className="text-2xl font-semibold text-slate-900">Data freshness</h1>
      <p className="mt-1 text-sm text-slate-500">Every source Accord uses, and when it was last verified.</p>

      {/* Status summary strip */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Sources monitored" value={sources.length} />
        <StatCard label={stale ? 'Need attention' : 'All current'} value={stale ? `${stale} stale` : '✅ All'} tone={stale ? 'amber' : 'green'} />
        <StatCard label="Rule tests" value={tests?.tests_total != null ? `${tests.tests_passed}/${tests.tests_total}` : '—'} tone={tests && (tests.tests_failed ?? 0) === 0 ? 'green' : 'slate'} />
        <StatCard label="Last checked" value={<span className="text-sm font-semibold text-slate-700">{fmtTs(lastChecked ?? null) ?? '—'}</span>} />
      </div>

      {/* Source table */}
      <div className="mt-5 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2.5 text-left">Source</th>
              <th className="px-4 py-2.5 text-left">Category</th>
              <th className="px-4 py-2.5 text-left">Last updated</th>
              <th className="px-4 py-2.5 text-left">Next refresh</th>
              <th className="px-4 py-2.5 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sources.map((s, i) => {
              const cat = CATEGORY[s.category] || CATEGORY.external
              return (
                <tr key={i}>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-800">{s.source}</div>
                    {s.regulation && s.regulation !== s.source && <div className="text-xs text-slate-400">{s.regulation}</div>}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-slate-600">{cat.icon} {cat.label}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    {fmtTs(s.last_updated) ?? <span className="text-slate-400">Not recorded yet</span>}
                    {s.record_count != null && <span className="ml-1 text-xs text-slate-400">· {s.record_count.toLocaleString()} records</span>}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{s.next_refresh}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap"><StatusCell s={s} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-slate-400">
        As of {fmtTs(data.as_of)} · Timestamps come from each source's last successful sync. Sources with no recorded sync show “Not recorded”.
      </p>
    </div>
  )
}
