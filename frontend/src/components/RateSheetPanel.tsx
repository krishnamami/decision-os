import { useEffect, useRef, useState } from 'react'
import { fetchRateSheetStatus, uploadRateSheet, type RateSheetStatus, type RateSheetUploadResult } from '../api/client'

const COLS = ['product_id', 'credit_band', 'ltv_max', 'base_rate', 'llpa_adjustment', 'effective_date']
const SAMPLE = `product_id,credit_band,ltv_max,base_rate,llpa_adjustment,effective_date
CONF30,740-759,80,6.500,0.250,2026-07-01
CONF30,720-739,80,6.625,0.500,2026-07-01
FHA30,680-699,96.5,6.250,0.000,2026-07-01`

const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—')

export default function RateSheetPanel({ canEdit }: { canEdit: boolean }) {
  const [status, setStatus] = useState<RateSheetStatus | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<RateSheetUploadResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = () => fetchRateSheetStatus().then(setStatus).catch(() => undefined)
  useEffect(() => { load() }, [])

  async function upload() {
    if (!file) return
    setBusy(true); setErr(null); setResult(null)
    try {
      const r = await uploadRateSheet(file)
      setResult(r)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Upload failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-900">📄 Rate Sheet</h3>
          <p className="text-xs text-slate-500">Upload your lender rate sheet (CSV) — base rates and LLPA adjustments by product, credit band, and LTV.</p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Last upload: <span className="font-medium text-slate-700">{fmt(status?.last_upload)}</span></div>
          <div>{status?.total_entries ?? 0} entries on file</div>
        </div>
      </div>

      {/* Format guide */}
      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">CSV format</div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {COLS.map((c) => <span key={c} className="rounded bg-white px-2 py-0.5 font-mono text-[11px] text-slate-700 ring-1 ring-slate-200">{c}</span>)}
        </div>
        <pre className="mt-2 overflow-x-auto rounded bg-slate-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-100">{SAMPLE}</pre>
        <p className="mt-1 text-[11px] text-slate-400">Rows are upserted by (product, credit band, LTV, effective date). effective_date is ISO (YYYY-MM-DD).</p>
      </div>

      {/* Upload */}
      {canEdit ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setErr(null); setResult(null) }}
            className="text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-white hover:file:bg-brand-dark"
          />
          <button
            onClick={upload}
            disabled={!file || busy}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
          >
            {busy ? 'Uploading…' : 'Upload rate sheet'}
          </button>
        </div>
      ) : (
        <p className="mt-4 text-xs text-slate-400">🔒 Admin or manager access (Business plan) required to upload.</p>
      )}

      {err && <p className="mt-3 text-sm font-medium text-red-600">❌ {err}</p>}
      {result && (
        <div className="mt-3 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
          ✅ Uploaded <strong>{result.uploaded}</strong> of {result.rows_in_file} row(s)
          {result.effective_dates.length > 0 && <> · effective {result.effective_dates.join(', ')}</>}
          {result.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-amber-700">
              {result.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Recent entries */}
      {status && status.recent.length > 0 && (
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-1.5 text-left">Product</th><th className="px-3 py-1.5 text-left">Band</th><th className="px-3 py-1.5 text-left">LTV ≤</th><th className="px-3 py-1.5 text-left">Base rate</th><th className="px-3 py-1.5 text-left">LLPA</th><th className="px-3 py-1.5 text-left">Effective</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {status.recent.map((r, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5 font-medium text-slate-700">{r.product_id}</td>
                  <td className="px-3 py-1.5 text-slate-600">{r.credit_band}</td>
                  <td className="px-3 py-1.5 text-slate-600">{r.ltv_max}%</td>
                  <td className="px-3 py-1.5 text-slate-800">{r.base_rate.toFixed(3)}%</td>
                  <td className="px-3 py-1.5 text-slate-600">{r.llpa_adjustment >= 0 ? '+' : ''}{r.llpa_adjustment}</td>
                  <td className="px-3 py-1.5 text-slate-500">{r.effective_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
