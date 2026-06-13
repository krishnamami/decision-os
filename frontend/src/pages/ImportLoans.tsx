import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  downloadImportTemplate, importLoans, validateImport, IMPORT_FIELDS,
  type ImportResult, type ImportValidation,
} from '../api/client'

type Step = 'upload' | 'mapping' | 'preview' | 'importing' | 'complete'
const money = (n: number | null | undefined) => (n == null ? '—' : `$${Math.round(n / 1000)}K`)

export default function ImportLoans() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [val, setVal] = useState<ImportValidation | null>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [result, setResult] = useState<ImportResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showGuide, setShowGuide] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function onFile(f: File) {
    setFile(f); setErr(null); setBusy(true)
    try {
      const v = await validateImport(f)
      setVal(v)
      if (v.needs_mapping) { setMapping(v.auto_mapping || {}); setStep('mapping') }
      else setStep('preview')
    } catch (e: any) { setErr(e?.message || 'Validation failed') } finally { setBusy(false) }
  }

  async function revalidateWithMapping() {
    if (!file) return
    setBusy(true); setErr(null)
    try { setVal(await validateImport(file, mapping)); setStep('preview') }
    catch (e: any) { setErr(e?.message || 'Validation failed') } finally { setBusy(false) }
  }

  async function doImport() {
    if (!file) return
    setStep('importing'); setErr(null)
    try {
      const r = await importLoans(file, val?.needs_mapping ? mapping : undefined)
      setResult(r); setStep('complete')
    } catch (e: any) { setErr(e?.message || 'Import failed'); setStep('preview') }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      {/* STEP 1 — UPLOAD */}
      {step === 'upload' && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h1 className="text-xl font-bold text-slate-900">📥 Import Loans</h1>
          <p className="mt-1 text-[15px] text-slate-600">Upload your loan data to get started with Accord.</p>

          <div className="mt-5 text-sm">
            <div className="font-semibold text-slate-800">Step 1 · Download the template</div>
            <div className="mt-2 flex gap-2">
              <button onClick={() => downloadImportTemplate()} className="rounded-lg border border-slate-300 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50">📥 Download CSV template</button>
              <button onClick={() => setShowGuide((v) => !v)} className="rounded-lg border border-slate-300 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50">📖 {showGuide ? 'Hide' : 'View'} import guide</button>
            </div>
            {showGuide && (
              <div className="mt-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                <b>Encompass:</b> Pipeline → Select All → Export → Custom Fields → CSV.<br />
                <b>ICE:</b> Reports → Loan Export → Standard Fields → map to Accord columns.<br />
                <b>Generic:</b> fill the template (one row per loan), save as CSV. Different headers? We’ll show a mapping screen.
              </div>
            )}
          </div>

          <div className="mt-5 text-sm">
            <div className="font-semibold text-slate-800">Step 2 · Fill in your loan data</div>
            <p className="mt-1 text-slate-500">Open the template, fill in your loans, save as CSV.</p>
          </div>

          <div className="mt-5 text-sm font-semibold text-slate-800">Step 3 · Upload</div>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onFile(f) }}
            onClick={() => inputRef.current?.click()}
            className="mt-2 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 py-10 text-center hover:border-brand/50"
          >
            <div className="text-3xl">📁</div>
            <div className="text-sm font-medium text-slate-700">Drag and drop your CSV here</div>
            <div className="text-sm text-brand">or browse files</div>
            <div className="text-xs text-slate-400">Supported: .csv, .tsv (max 50MB)</div>
            <input ref={inputRef} type="file" accept=".csv,.tsv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
          </div>
          {busy && <p className="mt-3 text-sm text-slate-400">Validating…</p>}
          {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
        </div>
      )}

      {/* MAPPING (non-standard CSV) */}
      {step === 'mapping' && val && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h1 className="text-lg font-bold text-slate-900">🔄 Map your columns</h1>
          <p className="mt-1 text-sm text-slate-600">Your CSV has different column names. Map them to Accord:</p>
          {val.mapping_stats && <p className="mt-1 text-xs text-slate-500">Auto-mapped {val.mapping_stats.auto} of {val.mapping_stats.total} columns · {val.mapping_stats.skipped} skipped</p>}
          <div className="mt-3 max-h-80 overflow-y-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2 text-left">Your column</th><th className="px-3 py-2 text-left">Accord field</th><th className="px-3 py-2" /></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {val.headers.map((h) => {
                  const auto = !!val.auto_mapping?.[h]
                  return (
                    <tr key={h}>
                      <td className="px-3 py-2 font-mono text-xs text-slate-700">{h}</td>
                      <td className="px-3 py-2">
                        <select value={mapping[h] ?? '__skip__'} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value === '__skip__' ? null : e.target.value })} className="rounded-md border border-slate-300 px-2 py-1 text-xs">
                          <option value="__skip__">— skip —</option>
                          {IMPORT_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </td>
                      <td className="px-3 py-2 text-xs">{mapping[h] ? (auto ? '✅ auto' : '⚠ manual') : '❌ skip'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={() => setStep('upload')} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
            <button onClick={revalidateWithMapping} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">Continue with this mapping</button>
          </div>
        </div>
      )}

      {/* STEP 2 — PREVIEW */}
      {step === 'preview' && val && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h1 className="text-lg font-bold text-slate-900">{val.errors.length ? '⚠' : '✅'} File validated</h1>
          <p className="mt-1 text-sm text-slate-600">{val.row_count} loans found · {val.valid_count} valid · {val.errors.length} error{val.errors.length === 1 ? '' : 's'}</p>

          <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2 text-left">Loan #</th><th className="px-3 py-2 text-left">Borrower</th><th className="px-3 py-2 text-left">Amount</th><th className="px-3 py-2 text-left">Type</th><th className="px-3 py-2 text-left">Status</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {val.preview.map((p, i) => (
                  <tr key={i} className={p.status === 'error' ? 'bg-red-50' : ''}>
                    <td className="px-3 py-2 font-mono text-xs">{p.loan_number}</td>
                    <td className="px-3 py-2">{p.borrower}{p.error && <span className="block text-xs text-red-600">{p.error}</span>}</td>
                    <td className="px-3 py-2">{money(p.amount)}</td>
                    <td className="px-3 py-2 capitalize">{p.type || '—'}</td>
                    <td className="px-3 py-2">{p.status === 'ok' ? '✅ ok' : '❌ error'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {val.warnings.length > 0 && (
            <div className="mt-3">
              <div className="text-sm font-semibold text-amber-700">⚠ {val.warnings.length} warning(s):</div>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">{val.warnings.slice(0, 5).map((w) => <li key={w}>{w}</li>)}</ul>
            </div>
          )}

          {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
          <div className="mt-4 flex gap-2">
            <button onClick={() => { setStep('upload'); setVal(null); setFile(null) }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
            <button onClick={doImport} disabled={val.valid_count === 0} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40">
              Import {val.valid_count} loan{val.valid_count === 1 ? '' : 's'}{val.errors.length ? ` (skip ${val.errors.length})` : ''}
            </button>
          </div>
        </div>
      )}

      {/* STEP 3 — IMPORTING */}
      {step === 'importing' && (
        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center">
          <h1 className="text-lg font-bold text-slate-900">📥 Importing…</h1>
          <div className="mx-auto mt-4 h-3 max-w-md overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-2/3 animate-pulse rounded-full bg-brand" />
          </div>
          <p className="mt-3 text-sm text-slate-500">Creating entity states · assigning to team · starting AI evaluation…</p>
        </div>
      )}

      {/* STEP 4 — COMPLETE */}
      {step === 'complete' && result && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h1 className="text-lg font-bold text-green-700">✅ Import complete</h1>
          <p className="mt-1 text-[15px] text-slate-700">{result.imported} loans imported successfully{result.skipped ? ` (${result.skipped} skipped)` : ''}.</p>

          <div className="mt-4 text-sm">
            <div className="font-semibold text-slate-800">What happens next</div>
            <ul className="mt-1 space-y-0.5 text-slate-600">{result.next_steps.map((n) => <li key={n}>• {n}</li>)}</ul>
          </div>

          {result.evaluation && (
            <div className="mt-4 text-sm">
              <div className="font-semibold text-slate-800">AI evaluation</div>
              <p className="mt-1 text-slate-600">{result.evaluation.allow || 0} allow · {result.evaluation.review || 0} review · {result.evaluation.block || 0} block</p>
            </div>
          )}

          <div className="mt-4 text-sm">
            <div className="font-semibold text-slate-800">Assignments</div>
            <ul className="mt-1 space-y-0.5 text-slate-600">{Object.entries(result.summary.assignments).map(([e, n]) => <li key={e}>{e === 'unassigned' ? 'Unassigned' : e}: {n} loan{n === 1 ? '' : 's'}</li>)}</ul>
          </div>

          <div className="mt-5 flex gap-2">
            <button onClick={() => navigate('/pipeline')} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark">Go to Pipeline →</button>
            <button onClick={() => { setStep('upload'); setVal(null); setFile(null); setResult(null) }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Import more loans</button>
          </div>
        </div>
      )}
    </div>
  )
}
