import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  completeComparison, fetchComparisonReport, startComparison,
  type ComparisonDetail, type ComparisonReport,
} from '../api/client'
import { downloadCsv } from '../utils/export'

const fmt = (iso?: string) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—')

const MATCH: Record<string, { label: string; cls: string }> = {
  agree: { label: '✅ agree', cls: 'text-green-700' },
  accord_stricter: { label: '⚠ Accord stricter', cls: 'text-amber-600' },
  accord_looser: { label: '⚠ Accord looser', cls: 'text-amber-600' },
  disagree: { label: '❌ disagree', cls: 'text-red-600' },
}

function printReport(r: ComparisonReport, tenantName: string) {
  const w = window.open('', '_blank')
  if (!w || !r.summary || !r.period) return
  const rows = (r.all_comparisons || []).map((c) => `<tr><td>${c.application_id}</td><td>${c.borrower}</td><td>${c.accord_outcome}</td><td>${c.manual_outcome}</td><td>${MATCH[c.agreement]?.label || c.agreement}</td></tr>`).join('')
  const caught = (r.accord_caught || []).map((d) => `<li><b>${d.borrower}</b> (${d.application_id}): ${d.description || ''} — <i>${d.resolution || ''}</i></li>`).join('')
  const dis = (r.disagreements || []).map((d) => `<li><b>${d.borrower}</b> (${d.application_id}): ${d.description || ''} — <i>${d.resolution || ''}</i></li>`).join('')
  w.document.write(
    `<html><head><title>${tenantName} — Comparison Report</title>
     <style>body{font-family:system-ui,sans-serif;padding:34px;color:#0f172a}h1{font-size:20px;margin:0}
     .meta{color:#64748b;font-size:13px;margin:4px 0 14px}h2{font-size:14px;color:#0f6e56;margin:18px 0 6px}
     .big{font-size:34px;font-weight:800;color:#0f6e56}table{border-collapse:collapse;width:100%;font-size:11px}
     th,td{border:1px solid #e2e8f0;padding:4px 8px;text-align:left}th{background:#f8fafc}li{font-size:12px;margin:4px 0}</style></head>
     <body><h1>${tenantName} — Comparison Mode Report</h1>
     <div class="meta">${fmt(r.period.started)} – ${fmt(r.period.ends)} · Day ${r.period.day} of ${r.period.duration} · ${r.summary.total_loans} loans compared</div>
     <div class="big">${r.summary.agreement_rate}% agreement</div>
     <div class="meta">${r.summary.agree} agree · ${r.summary.accord_stricter} Accord stricter · ${r.summary.accord_looser} Accord looser · ${r.summary.disagree} disagree</div>
     <h2>What Accord caught</h2><ul>${caught || '<li>None</li>'}</ul>
     <h2>Disagreements reviewed</h2><ul>${dis || '<li>None</li>'}</ul>
     <h2>All comparisons</h2><table><tr><th>App</th><th>Borrower</th><th>Accord</th><th>Manual</th><th>Match</th></tr>${rows}</table>
     </body></html>`,
  )
  w.document.close(); w.focus()
  setTimeout(() => w.print(), 350)
}

function Kpi({ label, value, tone = 'slate' }: { label: string; value: string | number; tone?: string }) {
  const c = tone === 'green' ? 'text-green-700' : tone === 'amber' ? 'text-amber-600' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${c}`}>{value}</div>
    </div>
  )
}

function DetailCard({ d, kind }: { d: ComparisonDetail; kind: 'caught' | 'disagree' }) {
  const accent = kind === 'caught' ? 'border-l-blue-500 bg-blue-50/40' : 'border-l-amber-500 bg-amber-50/40'
  return (
    <div className={`rounded-xl border border-l-4 border-slate-200 p-4 ${accent}`}>
      <div className="font-semibold text-slate-900">{kind === 'caught' ? '🔍' : '⚠'} {d.application_id} · {d.borrower}</div>
      <div className="mt-1.5 text-sm text-slate-700">{d.description}</div>
      <div className="mt-1 text-sm"><span className="font-medium text-slate-600">Accord:</span> {String(d.accord_decision).toUpperCase()} · <span className="font-medium text-slate-600">Manual:</span> {String(d.manual_decision).toUpperCase()}</div>
      {d.resolution && <div className="mt-2 text-sm italic text-slate-600">Resolution: {d.resolution}</div>}
    </div>
  )
}

function WeeklyTrend({ trend }: { trend: Array<{ week: number; loans: number; agreement: number }> }) {
  return (
    <div className="flex items-end gap-4">
      {trend.map((w) => (
        <div key={w.week} className="flex flex-1 flex-col items-center gap-1">
          <div className="text-xs font-semibold text-slate-700">{w.agreement}%</div>
          <div className="flex h-28 w-full items-end">
            <div className="w-full rounded-t bg-brand" style={{ height: `${w.agreement}%` }} />
          </div>
          <div className="text-xs text-slate-400">Wk {w.week}</div>
          <div className="text-[10px] text-slate-400">{w.loans} loans</div>
        </div>
      ))}
    </div>
  )
}

export default function ComparisonMode() {
  const { tenant } = useAuth()
  const [report, setReport] = useState<ComparisonReport | null>(null)
  const [duration, setDuration] = useState(90)
  const [busy, setBusy] = useState(false)

  const load = () => fetchComparisonReport().then(setReport).catch(() => undefined)
  useEffect(() => { load() }, [])

  async function start() {
    setBusy(true)
    try { await startComparison(duration); await load() } finally { setBusy(false) }
  }
  async function complete() {
    setBusy(true)
    try { await completeComparison(); await load() } finally { setBusy(false) }
  }

  if (!report) return <div className="p-12 text-center text-sm text-slate-400">Loading comparison…</div>

  // SETUP — no period yet
  if (!report.active && !report.ended) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h1 className="text-xl font-bold text-slate-900">🔄 Comparison Mode</h1>
          <p className="mt-2 text-[15px] text-slate-600">Run Accord alongside your manual underwriting to build trust through evidence. See where Accord agrees with your team and where it differs.</p>
          <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
            <div className="font-semibold">How it works:</div>
            <ol className="mt-1 list-decimal space-y-0.5 pl-5">
              <li>Accord evaluates every loan (as normal)</li>
              <li>Your team makes their own independent decision</li>
              <li>The system compares both decisions</li>
              <li>After 90 days, review the agreement report</li>
            </ol>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <label className="text-sm text-slate-600">Duration</label>
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value={30}>30 days</option><option value={60}>60 days</option><option value={90}>90 days</option>
            </select>
            <button onClick={start} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">Start comparison period</button>
          </div>
        </div>
      </div>
    )
  }

  const s = report.summary!
  const p = report.period!
  const exportCsv = () => downloadCsv(
    ['Application', 'Borrower', 'Accord', 'Manual', 'Agreement'],
    (report.all_comparisons || []).map((c) => [c.application_id, c.borrower, c.accord_outcome, c.manual_outcome, c.agreement]),
    'accord_comparison',
  )

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-900">
          🔄 Comparison Mode — {report.ended ? `Complete · ${s.total_loans} loans` : `Day ${p.day} of ${p.duration}`}
        </h1>
        <div className="flex gap-2">
          <button onClick={() => printReport(report, tenant?.name || 'Tenant')} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">📥 Export report (PDF)</button>
          <button onClick={exportCsv} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">📥 Export data (CSV)</button>
          {!report.ended && <button onClick={complete} disabled={busy} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">End period</button>}
        </div>
      </div>

      {/* Big agreement banner */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 text-center">
        <div className="text-sm uppercase tracking-wide text-slate-400">Agreement rate</div>
        <div className="text-4xl font-extrabold text-brand">{s.agreement_rate}%</div>
        <div className="mx-auto mt-3 h-3 max-w-lg overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-brand" style={{ width: `${s.agreement_rate}%` }} />
        </div>
        <div className="mt-2 text-sm text-slate-500">{s.agree} agree · {s.accord_stricter} Accord stricter · {s.accord_looser} Accord looser · {s.disagree} disagree</div>
        {report.ended && (
          <p className="mx-auto mt-3 max-w-xl text-sm font-medium text-slate-700">
            {s.agreement_rate >= 95 ? 'Accord matches your team’s judgment. Ready for primary use.' : s.agreement_rate >= 90 ? 'Strong agreement. A few patterns left to calibrate.' : 'Review the disagreements and calibrate rules before primary use.'}
          </p>
        )}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi label="Loans compared" value={s.total_loans} />
        <Kpi label="Agreement rate" value={`${s.agreement_rate}%`} tone="green" />
        <Kpi label="Accord caught" value={report.accord_caught?.length || 0} tone="amber" />
        <Kpi label="Manual caught" value={report.manual_caught?.length || 0} />
      </div>

      {/* Weekly trend */}
      {report.weekly_trend && report.weekly_trend.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-bold text-slate-900">Agreement trend</h2>
          <WeeklyTrend trend={report.weekly_trend} />
          <p className="mt-3 text-sm text-slate-500">Agreement rate is improving as rules are calibrated.</p>
        </div>
      )}

      {/* Accord caught */}
      {(report.accord_caught?.length || 0) > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-bold text-slate-900">What Accord caught (that manual missed)</h2>
          <div className="space-y-3">{report.accord_caught!.map((d) => <DetailCard key={d.application_id} d={d} kind="caught" />)}</div>
        </div>
      )}

      {/* Disagreements */}
      {(report.disagreements?.length || 0) > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-bold text-slate-900">Disagreements (to review)</h2>
          <div className="space-y-3">{report.disagreements!.map((d) => <DetailCard key={d.application_id} d={d} kind="disagree" />)}</div>
        </div>
      )}

      {/* All comparisons */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-bold text-slate-900">All comparisons</h2>
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2 text-left">App ID</th><th className="px-3 py-2 text-left">Borrower</th><th className="px-3 py-2 text-left">Accord</th><th className="px-3 py-2 text-left">Manual</th><th className="px-3 py-2 text-left">Match</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(report.all_comparisons || []).map((c) => (
                <tr key={c.application_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs text-slate-500">{c.application_id}</td>
                  <td className="px-3 py-2 font-medium text-slate-800">{c.borrower}</td>
                  <td className="px-3 py-2">{c.accord_outcome}</td>
                  <td className="px-3 py-2">{c.manual_outcome}</td>
                  <td className={`px-3 py-2 font-medium ${MATCH[c.agreement]?.cls || ''}`}>{MATCH[c.agreement]?.label || c.agreement}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
