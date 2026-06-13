import { useEffect, useState } from 'react'
import Modal from './Modal'
import { fetchRulesHistory, lookupRules, type TenantVersion } from '../api/client'

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

const STATUS_PILL: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  superseded: 'bg-slate-100 text-slate-500',
  pending_approval: 'bg-amber-100 text-amber-800',
  draft: 'bg-slate-100 text-slate-400',
}

function printVersion(v: TenantVersion, tenantName: string) {
  const w = window.open('', '_blank')
  if (!w) return
  const rows = Object.entries(v.rules || {})
    .filter(([, val]) => typeof val === 'object')
    .map(([cat, val]) => `<tr><td><b>${cat}</b></td><td>${JSON.stringify(val)}</td></tr>`)
    .join('')
  w.document.write(
    `<html><head><title>${tenantName} rules v${v.version}</title>
     <style>body{font-family:system-ui,sans-serif;padding:32px;color:#0f172a}
     h1{font-size:18px;margin:0 0 4px}.meta{color:#64748b;font-size:13px;margin-bottom:16px}
     table{border-collapse:collapse;width:100%;font-size:13px}td{border:1px solid #e2e8f0;padding:6px 10px}</style></head>
     <body><h1>${tenantName} — Decision Rules v${v.version}</h1>
     <div class="meta">Status: ${v.status} · Effective ${fmtDate(v.effective_from)}` +
      `${v.approved_by ? ' · Approved by ' + v.approved_by : ''}</div>` +
      `<table>${rows}</table></body></html>`,
  )
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 350)
}

export default function RuleHistory({ tenantName, onClose }: { tenantName: string; onClose: () => void }) {
  const [versions, setVersions] = useState<TenantVersion[]>([])
  const [lookupDate, setLookupDate] = useState('2026-06-03')
  const [lookupResult, setLookupResult] = useState<string | null>(null)

  useEffect(() => {
    fetchRulesHistory().then((d) => setVersions(d.versions)).catch(() => undefined)
  }, [])

  async function doLookup() {
    try {
      const r = await lookupRules(lookupDate)
      setLookupResult(
        r.found ? `Version ${r.version} was active on ${fmtDate(lookupDate)}` : r.message || 'No version found for that date',
      )
    } catch {
      setLookupResult('Lookup failed — check the date format.')
    }
  }

  return (
    <Modal title="Rules Version History" onClose={onClose} width="max-w-2xl">
      <div className="space-y-3">
        {versions.map((v) => (
          <div key={v.rule_version_id} className="rounded-xl border border-slate-200 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-900">v{v.version}</span>
                <span className="text-xs text-slate-400">· {fmtDate(v.effective_from || v.created_at)}</span>
                <span className="text-xs text-slate-400">· {v.created_by || 'System'}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${STATUS_PILL[v.status] || 'bg-slate-100 text-slate-500'}`}>
                  {v.status.replace('_', ' ')}
                </span>
              </div>
            </div>
            <p className="mt-1.5 text-sm text-slate-700">{v.changes_summary || 'Rule version'}</p>
            {v.change_reason && <p className="mt-0.5 text-xs italic text-slate-500">“{v.change_reason}”</p>}
            <div className="mt-1 text-xs text-slate-400">
              {v.approved_by ? `Approved by ${v.approved_by} · ${fmtDate(v.approved_at)}` : 'Awaiting approval'}
            </div>
            <button onClick={() => printVersion(v, tenantName)} className="mt-2 text-xs font-medium text-brand hover:underline">
              📥 Download PDF
            </button>
          </div>
        ))}

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">For examiners</div>
          <p className="mt-1 text-sm text-slate-700">Which rules were active on a given date?</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={lookupDate}
              onChange={(e) => setLookupDate(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-brand"
            />
            <button onClick={doLookup} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">
              Look up
            </button>
            {lookupResult && <span className="text-sm font-medium text-slate-800">→ {lookupResult}</span>}
          </div>
        </div>
      </div>
    </Modal>
  )
}
