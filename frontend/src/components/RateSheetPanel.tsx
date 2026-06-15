import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchRateSheetStatus, uploadRateSheet, type RateSheetStatus, type RateSheetUploadResult } from '../api/client'

const COLS = ['product_id', 'credit_band', 'ltv_max', 'base_rate', 'llpa_adjustment', 'effective_date']
const SAMPLE = `product_id,credit_band,ltv_max,base_rate,llpa_adjustment,effective_date
PRD-FNMA-30FX,super_prime,80,6.750,0.000,2026-07-01
PRD-FNMA-30FX,prime,80,6.750,0.125,2026-07-01
PRD-FHA-30FX,near_prime,96.5,6.750,0.250,2026-07-01`

// Credit-band chips (matches the seeded banding scheme).
const bandColor: Record<string, { bg: string; color: string; label: string }> = {
  super_prime: { bg: '#d1e8d8', color: '#0F4D37', label: 'Super prime 760+' },
  prime: { bg: '#e6f1fb', color: '#185fa5', label: 'Prime 700–759' },
  near_prime: { bg: '#faeeda', color: '#633806', label: 'Near prime 660–699' },
  subprime: { bg: '#fcebeb', color: '#791f1f', label: 'Subprime 620–659' },
}

// Friendly product names for known product_ids; unknown ids fall back to the raw id.
const productLabel: Record<string, string> = {
  'PRD-FNMA-30FX': 'Conv 30yr Fixed',
  'PRD-FHLMC-30FX': 'Conv 30yr Fixed (Freddie)',
  'PRD-FNMA-20FX': 'Conv 20yr Fixed',
  'PRD-FNMA-15FX': 'Conv 15yr Fixed',
  'PRD-FHA-30FX': 'FHA 30yr',
  'PRD-VA-30FX': 'VA 30yr',
  'PRD-NONQM-30FX': 'Non-QM 30yr',
}
const prodName = (id: string) => productLabel[id] ?? id

const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—')

function BandChip({ band }: { band: string }) {
  const c = bandColor[band]
  if (!c) return <span className="rounded px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200">{band}</span>
  return (
    <span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ background: c.bg, color: c.color }}>
      {c.label}
    </span>
  )
}

export default function RateSheetPanel({ canEdit }: { canEdit: boolean }) {
  const [status, setStatus] = useState<RateSheetStatus | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<RateSheetUploadResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [productFilter, setProductFilter] = useState('all')
  const [bandFilter, setBandFilter] = useState('all')
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

  const rows = status?.recent ?? []
  // Product options come from whatever is actually on file (labelled).
  const products = useMemo(() => Array.from(new Set(rows.map((r) => r.product_id))).sort(), [rows])
  const filtered = rows.filter(
    (r) => (productFilter === 'all' || r.product_id === productFilter) && (bandFilter === 'all' || r.credit_band === bandFilter),
  )

  // Upload "versions" — group entries by upload timestamp (minute precision).
  // Exact per-upload snapshots aren't tracked, so the older versions show the
  // pipeline size at the time approximated by today's row count.
  const uploads = useMemo(() => {
    const byTime = new Map<string, { at: string; by: string | null; count: number }>()
    for (const r of rows) {
      const k = (r.uploaded_at || '').slice(0, 16)
      const cur = byTime.get(k)
      if (cur) cur.count += 1
      else byTime.set(k, { at: r.uploaded_at, by: r.uploaded_by ?? null, count: 1 })
    }
    return Array.from(byTime.values()).sort((a, b) => (b.at || '').localeCompare(a.at || '')).slice(0, 3)
  }, [rows])

  function downloadTemplate() {
    const blob = new Blob([SAMPLE + '\n'], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'accord_rate_sheet_template.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wide text-slate-700">Rate Sheets</h3>
          <p className="text-xs text-slate-500">Base rates and LLPA adjustments by product, credit band, and LTV.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={downloadTemplate} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">Download template</button>
          <span className="text-xs text-slate-400">{status?.total_entries ?? 0} entries</span>
        </div>
      </div>

      {/* 3. Last uploaded — prominent */}
      <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200">
        {status?.last_upload ? (
          <>
            <span className="font-semibold text-slate-700">Last uploaded:</span> {fmt(status.last_upload)}
            {status.last_uploaded_by && <> · by <span className="font-medium text-slate-700">{status.last_uploaded_by}</span></>}
          </>
        ) : (
          <span className="text-amber-700">Never uploaded — pricing uses placeholder rates</span>
        )}
      </div>

      {/* 1. Current rates — filterable table */}
      <div className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current rates</h4>
          <div className="flex items-center gap-2">
            <select
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"
            >
              <option value="all">All products</option>
              {products.map((p) => <option key={p} value={p}>{prodName(p)}</option>)}
            </select>
            <select
              value={bandFilter}
              onChange={(e) => setBandFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"
            >
              <option value="all">All bands</option>
              <option value="super_prime">Super prime</option>
              <option value="prime">Prime</option>
              <option value="near_prime">Near prime</option>
              <option value="subprime">Subprime</option>
            </select>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            ⚠️ No rate sheet on file — pricing falls back to placeholder rates. Upload a CSV below to activate real pricing.
          </div>
        ) : (
          <div className="mt-2 overflow-hidden rounded-lg border border-slate-200">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50 uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-1.5 text-left">Product</th>
                  <th className="px-3 py-1.5 text-left">Credit band</th>
                  <th className="px-3 py-1.5 text-right">Max LTV</th>
                  <th className="px-3 py-1.5 text-right">Base rate</th>
                  <th className="px-3 py-1.5 text-right">LLPA adj</th>
                  <th className="px-3 py-1.5 text-right">Effective rate</th>
                  <th className="px-3 py-1.5 text-left">Effective date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((r, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5 font-medium text-slate-700">{prodName(r.product_id)}</td>
                    <td className="px-3 py-1.5"><BandChip band={r.credit_band} /></td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{r.ltv_max}%</td>
                    <td className="px-3 py-1.5 text-right text-slate-800">{r.base_rate.toFixed(3)}%</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{r.llpa_adjustment >= 0 ? '+' : ''}{r.llpa_adjustment.toFixed(3)}</td>
                    <td className="px-3 py-1.5 text-right font-semibold text-slate-900">{(r.base_rate + r.llpa_adjustment).toFixed(3)}%</td>
                    <td className="px-3 py-1.5 text-slate-500">{r.effective_date}</td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-3 text-center text-slate-400">No rates match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
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

      {/* 2. Snapshot disclaimer + Upload */}
      {canEdit ? (
        <div className="mt-4">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">
            <span className="font-semibold">Before you upload:</span> Uploading a new rate sheet activates it immediately for all
            new loan evaluations. Loans currently open in the pipeline will be snapshotted at today's rates
            {status?.last_upload && <> ({fmt(status.last_upload)})</>} and their pricing will not change automatically.
            Re-evaluate manually from the workbench if needed. This action is logged. Previous rate sheets are archived for audit.
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
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

      {/* Recent uploads / version history */}
      {uploads.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent uploads</h4>
          <div className="mt-2 space-y-1.5">
            {uploads.map((u, i) => (
              <div key={u.at} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs">
                <span className="text-slate-700">{fmt(u.at)}</span>
                {u.by && <span className="text-slate-400">· by {u.by}</span>}
                <span className="text-slate-400">· {u.count} row{u.count === 1 ? '' : 's'}</span>
                {i === 0 ? (
                  <span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ background: '#d1e8d8', color: '#0F4D37' }}>Current</span>
                ) : (
                  <span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ background: '#e6f1fb', color: '#185fa5' }}>
                    Snapshotted · {(status?.total_entries ?? 0).toLocaleString()} loans
                  </span>
                )}
                <button className="ml-auto rounded-md border border-slate-300 px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50">View</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
