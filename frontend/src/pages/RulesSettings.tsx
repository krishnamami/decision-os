import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  approveRules, fetchRuleAlerts, fetchRules, updateRules,
  type AgencyGuideline, type RegulatoryRule, type RuleAlert, type RulesResponse,
} from '../api/client'
import DataFreshness from '../components/DataFreshness'
import RuleHistory from '../components/RuleHistory'

// Editable customer fields per category → path into the overlay rules JSON.
type Field = { path: [string, string]; label: string }
const CATEGORIES: Array<{ key: string; label: string; fields: Field[] }> = [
  { key: 'credit', label: 'Credit Assessment', fields: [
    { path: ['credit', 'min_score'], label: 'Your credit floor' },
    { path: ['credit', 'prime_threshold'], label: 'Your prime threshold' },
  ] },
  { key: 'dti', label: 'Debt-to-Income', fields: [
    { path: ['dti', 'back_max'], label: 'Your max DTI (back-end)' },
    { path: ['dti', 'front_max'], label: 'Your max DTI (front-end)' },
  ] },
  { key: 'ltv', label: 'Loan-to-Value', fields: [
    { path: ['ltv', 'max'], label: 'Your max LTV' },
    { path: ['ltv', 'no_mi_threshold'], label: 'No-MI threshold (LTV)' },
  ] },
  { key: 'fraud', label: 'Fraud Screening', fields: [
    { path: ['fraud', 'watchlist_threshold'], label: 'Watchlist block threshold' },
    { path: ['fraud', 'identity_min'], label: 'Identity match minimum' },
  ] },
  { key: 'income', label: 'Income Verification', fields: [
    { path: ['income', 'max_discrepancy_pct'], label: 'Max income discrepancy' },
  ] },
  { key: 'reserves', label: 'Reserves', fields: [
    { path: ['reserves', 'primary'], label: 'Primary residence reserves' },
    { path: ['reserves', 'investment'], label: 'Investment reserves' },
  ] },
]

const get = (obj: any, path: [string, string]) => obj?.[path[0]]?.[path[1]]
function setIn(obj: any, path: [string, string], value: number): any {
  const next = { ...obj, [path[0]]: { ...(obj[path[0]] || {}) } }
  next[path[0]][path[1]] = value
  return next
}

// Client mirror of the server's overlay validation (the PUT is authoritative).
function fieldIssue(key: string, path: [string, string], value: number, programs: string[]): { level: 'error' | 'warn'; msg: string } | null {
  if (Number.isNaN(value)) return { level: 'error', msg: 'Enter a number' }
  if (key === 'credit' && path[1] === 'min_score') {
    if (programs.includes('fha') && value < 580) return { level: 'error', msg: 'Cannot go below FHA minimum of 580' }
    if (value < 500) return { level: 'error', msg: 'Cannot go below FHA absolute minimum of 500' }
    if (value < 620) return { level: 'warn', msg: 'Below Fannie guideline of 620. Proceed?' }
  }
  if (key === 'dti' && path[1] === 'back_max' && value > 43) return { level: 'warn', msg: 'Exceeds QM safe harbor (43%)' }
  if (key === 'ltv' && path[1] === 'max' && value > 97) return { level: 'warn', msg: 'Exceeds Fannie conventional maximum (97%)' }
  return null
}

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'
}

function exportPdf(data: RulesResponse, tenantName: string) {
  const w = window.open('', '_blank')
  if (!w || !data.tenant) return
  const layer = (rows: string) => rows
  const regRows = data.regulatory.map((r) => `<tr><td>🔒 ${r.authority}${r.state_code ? ' (' + r.state_code + ')' : ''}</td><td>${r.rule_name}</td><td>${r.display_value || ''}</td><td>${r.citation || ''}</td></tr>`).join('')
  const agcRows = data.agency.map((a) => `<tr><td>📋 ${a.agency}</td><td>${a.guideline_name}</td><td>${a.display_value || ''}</td><td>${a.citation || ''}</td></tr>`).join('')
  const ovr = data.tenant.rules
  const ovrRows = CATEGORIES.flatMap((c) => c.fields.map((f) => `<tr><td>🔧 ${c.label}</td><td>${f.label}</td><td>${get(ovr, f.path) ?? ''}</td><td>You (v${data.tenant!.version})</td></tr>`)).join('')
  w.document.write(
    `<html><head><title>${tenantName} Decision Rules v${data.tenant.version}</title>
     <style>body{font-family:system-ui,sans-serif;padding:34px;color:#0f172a}
     h1{font-size:20px;margin:0 0 2px}h2{font-size:14px;margin:22px 0 6px;color:#0f6e56}
     .meta{color:#64748b;font-size:13px;margin-bottom:8px}
     table{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:8px}
     th,td{border:1px solid #e2e8f0;padding:5px 9px;text-align:left}th{background:#f8fafc}</style></head>
     <body><h1>${tenantName} — Decision Rules</h1>
     <div class="meta">Version ${data.tenant.version} · Effective ${fmtDate(data.tenant.effective_from)}` +
      `${data.tenant.approved_by ? ' · Approved by ' + data.tenant.approved_by : ''} · Generated ${new Date().toLocaleDateString()}</div>` +
      `<h2>🔒 Regulatory (federal & state law)</h2><table><tr><th>Layer</th><th>Rule</th><th>Value</th><th>Source</th></tr>${layer(regRows)}</table>` +
      `<h2>📋 Agency guidelines</h2><table><tr><th>Layer</th><th>Rule</th><th>Value</th><th>Source</th></tr>${layer(agcRows)}</table>` +
      `<h2>🔧 Your overlay (v${data.tenant.version})</h2><table><tr><th>Layer</th><th>Rule</th><th>Value</th><th>Source</th></tr>${layer(ovrRows)}</table>` +
      `</body></html>`,
  )
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 350)
}

export default function RulesSettings() {
  const { user, tenant } = useAuth()
  const [data, setData] = useState<RulesResponse | null>(null)
  const [draft, setDraft] = useState<any>(null)
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [showFreshness, setShowFreshness] = useState(false)
  const [showAlerts, setShowAlerts] = useState(false)
  const [alerts, setAlerts] = useState<RuleAlert[]>([])
  const [pendingVersion, setPendingVersion] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const canEdit = user?.role === 'admin' || user?.role === 'manager'
  const isAdmin = user?.role === 'admin'

  function load() {
    fetchRules().then((d) => { setData(d); setDraft(d.tenant?.rules || {}) }).catch(() => undefined)
    fetchRuleAlerts().then((d) => setAlerts(d.alerts)).catch(() => undefined)
    import('../api/client').then(({ fetchRulesHistory }) =>
      fetchRulesHistory().then((h) => {
        const pend = h.versions.find((v) => v.status === 'pending_approval')
        setPendingVersion(pend ? pend.version : null)
      }).catch(() => undefined))
  }
  useEffect(load, [])

  const programs: string[] = data?.tenant?.programs || ['conventional', 'fha']
  const dirty = useMemo(() => data && JSON.stringify(draft) !== JSON.stringify(data.tenant?.rules), [draft, data])

  const issues = useMemo(() => {
    const errs: string[] = []; const warns: string[] = []
    if (!draft) return { errs, warns }
    for (const c of CATEGORIES) for (const f of c.fields) {
      const v = Number(get(draft, f.path))
      const iss = fieldIssue(c.key, f.path, v, programs)
      if (iss?.level === 'error') errs.push(`${f.label}: ${iss.msg}`)
      if (iss?.level === 'warn') warns.push(`${f.label}: ${iss.msg}`)
    }
    return { errs, warns }
  }, [draft, programs])

  function update(path: [string, string], raw: string) {
    setDraft((d: any) => setIn(d, path, raw === '' ? NaN : Number(raw)))
    setMsg(null)
  }

  async function submit() {
    if (!dirty) { setMsg({ kind: 'err', text: 'No changes to submit.' }); return }
    if (issues.errs.length) { setMsg({ kind: 'err', text: issues.errs[0] }); return }
    if (!reason.trim()) { setMsg({ kind: 'err', text: 'A reason for the change is required.' }); return }
    setBusy(true)
    try {
      const r = await updateRules({ rules: draft, change_reason: reason.trim(), changes_summary: 'Overlay rule update' })
      setMsg({ kind: 'ok', text: `Submitted as v${r.version} — pending admin approval.` })
      setReason('')
      load()
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || 'Submit failed' })
    } finally {
      setBusy(false)
    }
  }

  async function approve() {
    setBusy(true)
    try {
      const r = await approveRules()
      setMsg({ kind: 'ok', text: `Approved — v${r.version} is now active.` })
      load()
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || 'Approve failed' })
    } finally {
      setBusy(false)
    }
  }

  if (!data || !draft) return <div className="p-10 text-center text-sm text-slate-400">Loading decision rules…</div>

  const newAlerts = alerts.filter((a) => a.status === 'new').length

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Decision Rules · {tenant?.name}</h2>
            <p className="text-sm text-slate-500">Three layers protect every AI decision.</p>
            {data.tenant && (
              <p className="mt-1 text-xs text-slate-500">
                Version <span className="font-semibold text-slate-700">v{data.tenant.version}</span> · Active since {fmtDate(data.tenant.effective_from)}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setShowHistory(true)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">View history</button>
            <button onClick={() => exportPdf(data, tenant?.name || 'Tenant')} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">📥 Export PDF</button>
            <button onClick={() => setShowFreshness((v) => !v)} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${showFreshness ? 'border-brand bg-brand-light/40 text-brand-dark' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>Data Freshness</button>
            <button onClick={() => setShowAlerts((v) => !v)} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${showAlerts ? 'border-brand bg-brand-light/40 text-brand-dark' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>
              Rule Alerts{newAlerts ? ` (${newAlerts} new)` : ''}
            </button>
          </div>
        </div>
      </div>

      {/* Pending-approval banner (admin) */}
      {pendingVersion && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-300 bg-amber-50 p-4">
          <span className="text-sm font-medium text-amber-800">⏳ v{pendingVersion} is pending approval.</span>
          {isAdmin && <button onClick={approve} disabled={busy} className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50">Approve change</button>}
        </div>
      )}

      {showAlerts && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-bold text-slate-900">🔔 Rule Alerts</h3>
          <p className="text-xs text-slate-500">New agency / regulatory announcements to review.</p>
          <div className="mt-3 space-y-2">
            {alerts.length === 0 && <p className="text-sm text-slate-400">No alerts.</p>}
            {alerts.map((a) => (
              <div key={a.alert_id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center gap-2">
                  {a.status === 'new' && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">NEW</span>}
                  <span className="text-sm font-semibold text-slate-900">{a.title}</span>
                  <span className="text-xs text-slate-400">· {fmtDate(a.published_date)}</span>
                </div>
                {a.description && <p className="mt-1 text-xs text-slate-600">{a.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {showFreshness && (
        <div className="rounded-xl border border-slate-200 bg-white p-5"><DataFreshness /></div>
      )}

      {/* Category tables */}
      {CATEGORIES.map((cat) => {
        const reg = data.regulatory.filter((r) => r.category === cat.key)
        const agc = data.agency.filter((a) => a.category === cat.key)
        return (
          <div key={cat.key} className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-700">{cat.label}</h3>
            <div className="overflow-hidden rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="w-16 px-3 py-2 text-left">Layer</th><th className="px-3 py-2 text-left">Rule</th><th className="w-40 px-3 py-2 text-left">Value</th><th className="px-3 py-2 text-left">Source</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {reg.map((r: RegulatoryRule) => (
                    <tr key={r.rule_id} className="bg-slate-50/70">
                      <td className="px-3 py-2" title="Regulatory — locked">🔒</td>
                      <td className="px-3 py-2 text-slate-700">{r.rule_name}{r.state_code ? <span className="ml-1 text-xs text-slate-400">({r.state_code})</span> : ''}</td>
                      <td className="px-3 py-2 font-semibold text-slate-800">{r.display_value}</td>
                      <td className="px-3 py-2 text-xs text-slate-500">{r.citation}</td>
                    </tr>
                  ))}
                  {agc.map((a: AgencyGuideline) => (
                    <tr key={a.guideline_id} className="bg-blue-50/50">
                      <td className="px-3 py-2" title="Agency guideline — read-only">📋</td>
                      <td className="px-3 py-2 text-slate-700">{a.guideline_name}<span className="ml-1 text-xs uppercase text-slate-400">{a.agency}</span></td>
                      <td className="px-3 py-2 font-semibold text-slate-800">{a.display_value}</td>
                      <td className="px-3 py-2 text-xs text-slate-500">{a.citation}</td>
                    </tr>
                  ))}
                  {cat.fields.map((f) => {
                    const val = get(draft, f.path)
                    const iss = fieldIssue(cat.key, f.path, Number(val), programs)
                    const border = iss?.level === 'error' ? 'border-red-400 focus:border-red-500' : iss?.level === 'warn' ? 'border-amber-400 focus:border-amber-500' : 'border-slate-300 focus:border-brand'
                    return (
                      <tr key={f.path.join('.')} className="bg-white">
                        <td className="px-3 py-2" title="Your overlay — editable">🔧</td>
                        <td className="px-3 py-2 text-slate-700">{f.label}</td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            step="any"
                            value={Number.isNaN(Number(val)) ? '' : val}
                            disabled={!canEdit}
                            onChange={(e) => update(f.path, e.target.value)}
                            className={`w-24 rounded-md border px-2 py-1 text-sm outline-none disabled:bg-slate-50 ${border}`}
                          />
                          {iss && <span className={`ml-2 text-xs ${iss.level === 'error' ? 'text-red-600' : 'text-amber-600'}`}>✏️ {iss.msg}</span>}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-500">You (v{data.tenant?.version})</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}

      {/* Validation summary + actions */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        {issues.errs.length === 0
          ? <p className="text-sm font-medium text-green-700">✅ All your rules are at or above regulatory minimums.</p>
          : <p className="text-sm font-medium text-red-600">❌ {issues.errs.length} value(s) below a hard minimum — fix before submitting.</p>}
        {issues.warns.map((w) => <p key={w} className="mt-1 text-sm text-amber-600">⚠ {w}</p>)}

        {canEdit && dirty && (
          <div className="mt-4">
            <label className="mb-1 block text-xs font-medium text-slate-500">Reason for change (required)</label>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Why are you changing these rules?" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand" />
          </div>
        )}

        {msg && <p className={`mt-3 text-sm font-medium ${msg.kind === 'ok' ? 'text-green-700' : 'text-red-600'}`}>{msg.text}</p>}

        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={() => { setMsg({ kind: 'ok', text: 'Draft kept locally — submit when ready.' }) }} disabled={!canEdit || !dirty} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40">Save draft</button>
          <button onClick={submit} disabled={!canEdit || !dirty || busy || issues.errs.length > 0} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40">Submit for approval</button>
          <button onClick={() => exportPdf(data, tenant?.name || 'Tenant')} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">📥 Export PDF</button>
        </div>
        <p className="mt-2 text-xs text-slate-400">Changes require admin approval before taking effect.</p>
      </div>

      {showHistory && <RuleHistory tenantName={tenant?.name || 'Tenant'} onClose={() => setShowHistory(false)} />}
    </div>
  )
}
