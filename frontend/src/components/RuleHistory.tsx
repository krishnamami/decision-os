import { useEffect, useState } from 'react'
import Modal from './Modal'
import { fetchRulesHistory, lookupRules, rollbackRules, type TenantVersion } from '../api/client'

const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

const STATUS_PILL: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  superseded: 'bg-slate-100 text-slate-500',
  pending_approval: 'bg-amber-100 text-amber-800',
  scheduled: 'bg-blue-100 text-blue-800',
  shadow: 'bg-violet-100 text-violet-800',
  draft: 'bg-slate-100 text-slate-400',
}
const TYPE_PILL: Record<string, string> = {
  standard: 'bg-slate-100 text-slate-600',
  rollback: 'bg-indigo-100 text-indigo-700',
  emergency: 'bg-red-100 text-red-700',
  scheduled: 'bg-blue-100 text-blue-700',
  shadow: 'bg-violet-100 text-violet-700',
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
     <style>body{font-family:system-ui,sans-serif;padding:32px;color:#0f172a}h1{font-size:18px;margin:0 0 4px}
     .meta{color:#64748b;font-size:13px;margin-bottom:16px}table{border-collapse:collapse;width:100%;font-size:13px}td{border:1px solid #e2e8f0;padding:6px 10px}</style></head>
     <body><h1>${tenantName} — Decision Rules v${v.version}</h1>
     <div class="meta">Status: ${v.status} · ${v.change_type || 'standard'} · Effective ${fmtDate(v.effective_from)}` +
      `${v.approved_by ? ' · Approved by ' + v.approved_by : ''}</div><table>${rows}</table></body></html>`,
  )
  w.document.close(); w.focus()
  setTimeout(() => w.print(), 350)
}

export default function RuleHistory({ tenantName, versions: passed, canRollback, onRolledBack, onClose }: {
  tenantName: string
  versions?: TenantVersion[]
  canRollback?: boolean
  onRolledBack?: (msg: string) => void
  onClose: () => void
}) {
  const [versions, setVersions] = useState<TenantVersion[]>(passed || [])
  const [lookupDate, setLookupDate] = useState('2026-06-03')
  const [lookupResult, setLookupResult] = useState<string | null>(null)
  const [rollTarget, setRollTarget] = useState<TenantVersion | null>(null)
  const [rollReason, setRollReason] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!passed) fetchRulesHistory().then((d) => setVersions(d.versions)).catch(() => undefined)
  }, [passed])

  async function doLookup() {
    try {
      const r = await lookupRules(lookupDate)
      setLookupResult(r.found ? `Version ${r.version} was active on ${fmtDate(lookupDate)}` : r.message || 'No version found for that date')
    } catch { setLookupResult('Lookup failed — check the date format.') }
  }

  async function doRollback() {
    if (!rollTarget || !rollReason.trim()) return
    setBusy(true)
    try {
      const r = await rollbackRules(rollTarget.version, rollReason.trim())
      onRolledBack?.(`${r.message} ${r.affected_pipeline_loans} pipeline loan(s) affected.`)
      setRollTarget(null); setRollReason('')
      onClose()
    } finally { setBusy(false) }
  }

  return (
    <Modal title="Rules Version History" onClose={onClose} width="max-w-2xl">
      <div className="space-y-3">
        {versions.map((v) => (
          <div key={v.rule_version_id} className="rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-bold text-slate-900">v{v.version}</span>
              <span className="text-xs text-slate-400">· {fmtDate(v.effective_from || v.scheduled_for || v.created_at)}</span>
              <span className="text-xs text-slate-400">· {v.created_by || 'System'}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${STATUS_PILL[v.status] || 'bg-slate-100 text-slate-500'}`}>{v.status.replace('_', ' ')}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${TYPE_PILL[v.change_type || 'standard'] || 'bg-slate-100 text-slate-600'}`}>{v.change_type || 'standard'}</span>
              {v.rolled_back_from && <span className="text-xs italic text-indigo-600">↩ rolled back from v{v.rolled_back_from}</span>}
              {v.pipeline_policy && <span className="text-xs text-slate-400">· pipeline: {v.pipeline_policy}</span>}
            </div>
            <p className="mt-1.5 text-sm text-slate-700">{v.changes_summary || 'Rule version'}</p>
            {v.change_reason && <p className="mt-0.5 text-xs italic text-slate-500">“{v.change_reason}”</p>}
            <div className="mt-1 text-xs text-slate-400">
              {v.ratified_by ? `Ratified by ${v.ratified_by}` : v.approved_by ? `Approved by ${v.approved_by} · ${fmtDate(v.approved_at)}` : v.status === 'pending_approval' ? 'Awaiting approval' : ''}
            </div>
            <div className="mt-2 flex gap-3">
              <button onClick={() => printVersion(v, tenantName)} className="text-xs font-medium text-brand hover:underline">📥 Download PDF</button>
              {canRollback && v.status === 'superseded' && (
                <button onClick={() => setRollTarget(v)} className="text-xs font-medium text-indigo-600 hover:underline">↩ Rollback to this version</button>
              )}
            </div>
          </div>
        ))}

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">For examiners</div>
          <p className="mt-1 text-sm text-slate-700">Which rules were active on a given date?</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input type="date" value={lookupDate} onChange={(e) => setLookupDate(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-brand" />
            <button onClick={doLookup} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Look up</button>
            {lookupResult && <span className="text-sm font-medium text-slate-800">→ {lookupResult}</span>}
          </div>
        </div>
      </div>

      {rollTarget && (
        <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
          <p className="text-sm text-slate-700">Create a new version with the same rules as v{rollTarget.version}? This will NOT delete the current version. The audit trail is preserved.</p>
          <textarea value={rollReason} onChange={(e) => setRollReason(e.target.value)} rows={2} placeholder="Reason for rollback (required)" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand" />
          <div className="mt-2 flex gap-2">
            <button onClick={() => setRollTarget(null)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-white">Cancel</button>
            <button onClick={doRollback} disabled={busy || !rollReason.trim()} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">Create rollback version</button>
          </div>
        </div>
      )}
    </Modal>
  )
}
