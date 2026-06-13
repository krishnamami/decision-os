import { useEffect, useState } from 'react'
import { fetchValidationReport, runValidation, type ValidationReport, type ValidationTest } from '../api/client'

const CAT_LABEL: Record<string, string> = {
  credit: 'Credit Assessment', dti: 'DTI Calculation', ltv: 'Loan-to-Value', fraud: 'Fraud Screening',
  income: 'Income Verification', reserves: 'Reserves', conditional: 'Conditional Rules',
  regulatory_floor: 'Regulatory Floors', state_rules: 'State Rules', interactions: 'Interactions',
}
const fmtTs = (iso: string) => new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
const inputStr = (i: Record<string, any>) => Object.entries(i).map(([k, v]) => `${k}=${v}`).join(', ')

function printReport(r: ValidationReport, tenantName: string) {
  const w = window.open('', '_blank')
  if (!w) return
  const cats = Object.entries(r.categories).map(([k, c]) => `<tr><td>${CAT_LABEL[k] || k}</td><td>${c.passed}/${c.total}</td><td>${c.failed ? '❌' : '✅'}</td></tr>`).join('')
  const tests = r.tests.map((t) => `<tr class="${t.passed ? '' : 'f'}"><td>${t.id}</td><td>${t.description}</td><td>${inputStr(t.input)}</td><td>${t.expected}</td><td>${t.actual}</td><td>${t.passed ? '✅' : '❌'}</td></tr>`).join('')
  w.document.write(
    `<html><head><title>${tenantName} Rule Validation — v${r.rule_version}</title>
     <style>body{font-family:system-ui,sans-serif;padding:32px;color:#0f172a}h1{font-size:18px;margin:0}
     .meta{color:#64748b;font-size:13px;margin:4px 0 16px}h2{font-size:14px;margin:18px 0 6px;color:#0f6e56}
     table{border-collapse:collapse;width:100%;font-size:11px;margin-bottom:10px}th,td{border:1px solid #e2e8f0;padding:4px 8px;text-align:left}
     th{background:#f8fafc}.f{background:#fef2f2}</style></head>
     <body><h1>${tenantName} — Rule Validation Report</h1>
     <div class="meta">Rules v${r.rule_version} · ${r.passed}/${r.total_tests} tests passing · run ${fmtTs(r.run_at)} · ${r.duration_ms}ms</div>
     <h2>By category</h2><table><tr><th>Category</th><th>Passed</th><th>Status</th></tr>${cats}</table>
     <h2>All tests</h2><table><tr><th>ID</th><th>Test</th><th>Input</th><th>Expected</th><th>Actual</th><th></th></tr>${tests}</table>
     </body></html>`,
  )
  w.document.close(); w.focus()
  setTimeout(() => w.print(), 350)
}

function CategoryRow({ cat, label, tests }: { cat: { total: number; passed: number; failed: number }; label: string; tests: ValidationTest[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-slate-100 last:border-0">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50">
        <span className="font-medium text-slate-800">{label}</span>
        <span className="flex items-center gap-3">
          <span className={`font-mono ${cat.failed ? 'text-red-600' : 'text-slate-600'}`}>{cat.passed}/{cat.total}</span>
          <span>{cat.failed ? '❌' : '✅'}</span>
          <span className="text-xs text-brand">{open ? 'Collapse' : 'Expand'}</span>
        </span>
      </button>
      {open && (
        <div className="overflow-x-auto px-3 pb-3">
          <table className="min-w-full text-xs">
            <thead className="text-slate-400"><tr><th className="px-2 py-1 text-left">Test</th><th className="px-2 py-1 text-left">Input</th><th className="px-2 py-1 text-left">Expected</th><th className="px-2 py-1 text-left">Actual</th><th /></tr></thead>
            <tbody className="divide-y divide-slate-50">
              {tests.map((t) => (
                <tr key={t.id} className={t.passed ? '' : 'bg-red-50'}>
                  <td className="px-2 py-1 text-slate-700">{t.description}</td>
                  <td className="px-2 py-1 font-mono text-[11px] text-slate-500">{inputStr(t.input)}</td>
                  <td className="px-2 py-1 font-mono">{t.expected}</td>
                  <td className={`px-2 py-1 font-mono ${t.passed ? '' : 'font-bold text-red-600'}`}>{t.actual}</td>
                  <td className="px-2 py-1">{t.passed ? '✅' : '❌'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function RuleValidation({ tenantName }: { tenantName: string }) {
  const [report, setReport] = useState<ValidationReport | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { fetchValidationReport().then(setReport).catch(() => undefined) }, [])

  async function run() {
    setBusy(true)
    try { setReport(await runValidation()) } finally { setBusy(false) }
  }

  if (!report) return <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-400">Loading validation results…</div>

  const pct = report.total_tests ? Math.round((report.passed / report.total_tests) * 100) : 0
  const failed = report.tests.filter((t) => !t.passed)

  return (
    <div className="space-y-4">
      {report.failed > 0 && (
        <div className="rounded-xl border border-red-300 bg-red-50 p-4">
          <div className="text-sm font-bold text-red-800">🔴 {report.failed} rule validation test(s) failed. Review immediately.</div>
          <ul className="mt-2 space-y-0.5 text-xs text-red-700">
            {failed.slice(0, 5).map((t) => (
              <li key={t.id}>❌ {t.id}: {t.description} — expected <b>{t.expected}</b>, got <b>{t.actual}</b></li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900">✅ Rule Validation</h3>
            <p className="text-xs text-slate-500">Last run: {fmtTs(report.run_at)} · Duration: {(report.duration_ms / 1000).toFixed(report.duration_ms < 100 ? 3 : 1)}s · Rules v{report.rule_version}</p>
          </div>
          <div className="flex gap-2">
            <button onClick={run} disabled={busy} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">🔄 {busy ? 'Running…' : 'Run tests now'}</button>
            <button onClick={() => printReport(report, tenantName)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">📥 Download PDF report</button>
          </div>
        </div>

        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-sm">
            <span className={`font-semibold ${report.failed ? 'text-red-700' : 'text-green-700'}`}>{report.passed} of {report.total_tests} tests passing</span>
            <span className="text-slate-400">{pct}%</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full rounded-full ${report.failed ? 'bg-red-500' : 'bg-green-500'}`} style={{ width: `${pct}%` }} />
          </div>
        </div>

        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
          <div className="bg-slate-50 px-3 py-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">By category</div>
          {Object.entries(report.categories).map(([cat, c]) => (
            <CategoryRow key={cat} cat={c} label={CAT_LABEL[cat] || cat} tests={report.tests.filter((t) => t.category === cat)} />
          ))}
        </div>

        {report.warnings.length > 0 && (
          <div className="mt-4">
            <div className="text-sm font-semibold text-amber-700">⚠ {report.warnings.length} warning(s):</div>
            <ul className="mt-1 space-y-0.5 text-sm text-slate-600">
              {report.warnings.map((w) => <li key={w.id}>• {w.description}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
