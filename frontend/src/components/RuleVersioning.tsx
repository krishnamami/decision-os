import { useEffect, useState } from 'react'
import Modal from './Modal'
import {
  emergencyChange, examinationMode, fetchRuleImpact, fetchShadowReport, reconstructDecision,
  runRetrospective, scheduleRules, startShadow, updateRules, type TenantVersion,
} from '../api/client'

// ── Pricing-tier gating ─────────────────────────────────────────────
const PLAN_RANK: Record<string, number> = { starter: 0, growth: 1, business: 2, enterprise: 3 }
const PLAN_LABEL: Record<string, string> = { business: 'Business', enterprise: 'Enterprise' }
export function planAllows(plan: string | undefined, min: string): boolean {
  return (PLAN_RANK[plan || 'starter'] ?? 0) >= (PLAN_RANK[min] ?? 0)
}
export function LockedBadge({ feature, min }: { feature: string; min: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
      🔒 {feature} — available on {PLAN_LABEL[min]} plan
      <a href="mailto:demo@useaccord.com?subject=Accord%20upgrade" className="font-semibold text-brand hover:underline">Upgrade</a>
    </div>
  )
}

const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—')
const daysUntil = (iso?: string | null) => (iso ? Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000) : 0)

// Field-level diff between two overlay rule objects (for the submit summary).
function diffRules(orig: any, draft: any): string[] {
  const out: string[] = []
  const labels: Record<string, string> = {
    'credit.min_score': 'Credit floor', 'dti.back_max': 'DTI max', 'ltv.max': 'LTV max',
    'credit.prime_threshold': 'Prime threshold', 'dti.front_max': 'Front DTI',
  }
  for (const path of Object.keys(labels)) {
    const [a, b] = path.split('.')
    const o = orig?.[a]?.[b]; const d = draft?.[a]?.[b]
    if (o !== d && d !== undefined) out.push(`${labels[path]}: ${o} → ${d}`)
  }
  return out
}

// ════ Submit modal — timing + pipeline handling + impact + reason ════
export function SubmitModal({ original, draft, programs, onClose, onDone }: {
  original: any; draft: any; programs: string[]; onClose: () => void; onDone: (msg: string) => void
}) {
  const [timing, setTiming] = useState<'immediate' | 'schedule' | 'shadow'>('immediate')
  const [scheduleDate, setScheduleDate] = useState('2026-07-01')
  const [shadowDays, setShadowDays] = useState(14)
  const [pipeline, setPipeline] = useState<'grandfather' | 'immediate' | 'cutoff_date'>('grandfather')
  const [cutoff, setCutoff] = useState('2026-02-01')
  const [reason, setReason] = useState('')
  const [impact, setImpact] = useState<{ count: number; examples: Array<{ name: string; reason: string }> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const changes = diffRules(original, draft)

  useEffect(() => {
    fetchRuleImpact(draft).then(setImpact).catch(() => undefined)
  }, [])

  async function submit() {
    if (!reason.trim()) { setErr('A reason is required.'); return }
    setBusy(true); setErr(null)
    try {
      if (timing === 'schedule') {
        const r = await scheduleRules(draft, new Date(scheduleDate).toISOString(), reason.trim())
        onDone(`Scheduled as v${r.version} — activates ${r.activates}.`)
      } else if (timing === 'shadow') {
        const r = await startShadow(draft, shadowDays, reason.trim())
        onDone(`Shadow v${r.shadow_version} started (${shadowDays} days) — ${r.differences} of ${r.loans_evaluated} loans would change.`)
      } else {
        const r = await updateRules({ rules: draft, change_reason: reason.trim(), changes_summary: changes.join('; ') || 'Overlay update', programs })
        onDone(`Submitted as v${r.version} — pending admin approval.`)
      }
    } catch (e: any) {
      setErr(e?.message || 'Submit failed')
    } finally {
      setBusy(false)
    }
  }

  const Radio = ({ v, cur, set, children }: any) => (
    <label className="flex items-start gap-2 text-sm text-slate-700">
      <input type="radio" checked={cur === v} onChange={() => set(v)} className="mt-1 accent-brand" />
      <span>{children}</span>
    </label>
  )

  return (
    <Modal title="Submit Rule Change" onClose={onClose} width="max-w-lg">
      <div className="space-y-4 text-sm">
        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Changes</div>
          {changes.length ? changes.map((c) => <div key={c} className="font-medium text-slate-800">{c}</div>) : <div className="text-slate-400">No threshold changes detected.</div>}
        </div>

        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">When should this take effect?</div>
          <div className="space-y-1.5">
            <Radio v="immediate" cur={timing} set={setTiming}>Immediately (after admin approval)</Radio>
            <Radio v="schedule" cur={timing} set={setTiming}>
              Schedule for <input type="date" value={scheduleDate} onChange={(e) => setScheduleDate(e.target.value)} disabled={timing !== 'schedule'} className="rounded border border-slate-300 px-1.5 py-0.5 text-xs" />
            </Radio>
            <Radio v="shadow" cur={timing} set={setTiming}>
              Shadow mode first: test for <input type="number" value={shadowDays} onChange={(e) => setShadowDays(Number(e.target.value))} disabled={timing !== 'shadow'} className="w-14 rounded border border-slate-300 px-1.5 py-0.5 text-xs" /> days
            </Radio>
          </div>
        </div>

        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">How should pipeline loans be handled?</div>
          <div className="space-y-1.5">
            <Radio v="grandfather" cur={pipeline} set={setPipeline}>Grandfather: existing loans keep old rules</Radio>
            <Radio v="immediate" cur={pipeline} set={setPipeline}>Apply to all: re-evaluate pipeline under new rules</Radio>
            <Radio v="cutoff_date" cur={pipeline} set={setPipeline}>
              Cutoff date: loans before <input type="date" value={cutoff} onChange={(e) => setCutoff(e.target.value)} disabled={pipeline !== 'cutoff_date'} className="rounded border border-slate-300 px-1.5 py-0.5 text-xs" /> keep old rules
            </Radio>
          </div>
        </div>

        <div className="rounded-lg bg-slate-50 p-3">
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Pipeline impact</div>
          {impact == null ? <div className="text-slate-400">Calculating…</div> : (
            <>
              <div className="font-medium text-slate-800">{impact.count} loan{impact.count === 1 ? '' : 's'} would be affected by this change:</div>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                {impact.examples.map((e) => <li key={e.name}>• {e.name} — {e.reason}</li>)}
                {impact.count === 0 && <li className="text-slate-400">No active pipeline loans fail the new thresholds.</li>}
              </ul>
            </>
          )}
        </div>

        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Reason for change (required)</div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand" />
        </div>

        {err && <p className="text-sm font-medium text-red-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
            {timing === 'shadow' ? 'Start shadow test' : timing === 'schedule' ? 'Schedule change' : 'Submit for approval'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ════ Emergency override modal ════
export function EmergencyModal({ draft, onClose, onDone }: { draft: any; onClose: () => void; onDone: (msg: string) => void }) {
  const [reason, setReason] = useState('')
  const [type, setType] = useState('market_event')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function activate() {
    if (!reason.trim()) { setErr('An emergency reason is required.'); return }
    setBusy(true); setErr(null)
    try {
      const r = await emergencyChange(draft, reason.trim(), type)
      onDone(`🔴 Emergency v${r.version} active immediately — ratify within 24 hours (${r.affected_pipeline_loans} loans rescreened).`)
    } catch (e: any) { setErr(e?.message || 'Failed') } finally { setBusy(false) }
  }
  return (
    <Modal title="⚠ Emergency Rule Change" onClose={onClose} width="max-w-lg">
      <div className="space-y-3 text-sm">
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-800">
          This bypasses the normal approval workflow. Changes take effect <b>immediately</b>. An admin must ratify within 24 hours or changes auto-revert.
        </div>
        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Emergency reason (required)</div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Major employer layoff — 5,000 jobs affected…" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand" />
        </div>
        <div>
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-500">Emergency type</div>
          <select value={type} onChange={(e) => setType(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand">
            <option value="market_event">Market event (employer, housing market)</option>
            <option value="fraud_detection">Fraud detection (new pattern discovered)</option>
            <option value="regulatory">Regulatory (new law with immediate effect)</option>
            <option value="other">Other</option>
          </select>
        </div>
        {err && <p className="text-sm font-medium text-red-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={activate} disabled={busy} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">⚠ Activate emergency change</button>
        </div>
      </div>
    </Modal>
  )
}

// ════ Scheduled changes section ════
export function ScheduledSection({ scheduled }: { scheduled: TenantVersion[] }) {
  if (!scheduled.length) return null
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-bold text-slate-900">📅 Scheduled Changes</h3>
      <div className="mt-2 space-y-2">
        {scheduled.map((v) => (
          <div key={v.rule_version_id} className="rounded-lg border border-slate-200 p-3">
            <div className="font-semibold text-slate-900">v{v.version} · {v.changes_summary}</div>
            <div className="text-sm text-slate-600">Activates: {fmt(v.scheduled_for)} ({daysUntil(v.scheduled_for)} days)</div>
            <div className="text-xs text-slate-400">Approved by: {v.approved_by || 'Admin'}{v.change_reason ? ` · ${v.change_reason}` : ''}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ════ Expiring waivers section ════
export function ExpiringSection({ expiring }: { expiring: Array<{ name: string; field: string; value: number; normal: number; expires: string; days_remaining: number; severity: string }> }) {
  if (!expiring?.length) return null
  const sev = (s: string) => (s === 'red' ? 'border-red-300 bg-red-50' : s === 'amber' ? 'border-amber-300 bg-amber-50' : 'border-slate-200 bg-white')
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-bold text-slate-900">⏰ Expiring Rules</h3>
      <div className="mt-2 space-y-2">
        {expiring.map((w) => (
          <div key={w.name} className={`rounded-lg border p-3 ${sev(w.severity)}`}>
            <div className="font-semibold text-slate-900">⚠ {w.name}</div>
            <div className="text-sm text-slate-600">{w.field} exception: {w.value} (vs normal {w.normal})</div>
            <div className="text-sm text-slate-700">Expires: {fmt(w.expires)} ({w.days_remaining} days remaining)</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ════ Shadow mode section (live report) ════
export function ShadowSection() {
  const [r, setR] = useState<any>(null)
  useEffect(() => { fetchShadowReport().then(setR).catch(() => undefined) }, [])
  if (!r || !r.active) return null
  return (
    <div className="rounded-xl border border-violet-300 bg-violet-50 p-5">
      <h3 className="text-sm font-bold text-slate-900">🔍 Shadow Mode Active</h3>
      <div className="mt-1 text-sm text-slate-700">Testing: {r.changes_summary} (shadow v{r.shadow_version})</div>
      <div className="text-sm text-slate-600">Day {r.day} of {r.duration_days} · Loans evaluated: {r.loans_evaluated}</div>
      <div className="mt-2 rounded-lg bg-white p-3 text-sm">
        <div>Under current rules: <b>{r.active_approved}</b> approved, <b>{r.active_denied}</b> denied</div>
        <div>Under shadow rules: <b>{r.shadow_approved}</b> approved, <b>{r.shadow_denied}</b> denied</div>
        <div className="mt-1 font-semibold text-violet-700">{r.additional_denials} additional denials if shadow goes live</div>
      </div>
    </div>
  )
}

// ════ Examination mode toggle (enterprise) ════
export function ExaminationToggle({ exam, onChange }: { exam: { active: boolean; examiner?: string }; onChange: () => void }) {
  const [examiner, setExaminer] = useState('FDIC')
  const [reason, setReason] = useState('Annual safety & soundness examination')
  const [busy, setBusy] = useState(false)
  async function toggle(action: 'start' | 'end') {
    setBusy(true)
    try { await examinationMode(action, examiner, reason); onChange() } finally { setBusy(false) }
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-bold text-slate-900">🏛 Examination Mode</h3>
      <p className="mt-1 text-sm text-slate-500">
        Current status: {exam.active ? <span className="font-semibold text-amber-700">● Active ({exam.examiner})</span> : <span className="text-slate-500">○ Inactive</span>}
      </p>
      <p className="mt-2 text-xs text-slate-500">Activate during regulatory examinations to freeze all rule changes. Emergency overrides still allowed with additional documentation.</p>
      {!exam.active ? (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div><label className="block text-xs text-slate-500">Examiner</label>
            <select value={examiner} onChange={(e) => setExaminer(e.target.value)} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm">
              <option>FDIC</option><option>OCC</option><option>CFPB</option><option>State examiner</option>
            </select></div>
          <div className="flex-1"><label className="block text-xs text-slate-500">Reason</label>
            <input value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></div>
          <button onClick={() => toggle('start')} disabled={busy} className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50">Activate examination mode</button>
        </div>
      ) : (
        <button onClick={() => toggle('end')} disabled={busy} className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">End examination mode</button>
      )}
    </div>
  )
}

// ════ Retrospective analysis panel ════
export function RetrospectivePanel({ versions }: { versions: TenantVersion[] }) {
  const [start, setStart] = useState('2026-01-01')
  const [end, setEnd] = useState('2026-03-31')
  const [ver, setVer] = useState(versions.find((v) => v.status === 'active')?.version ?? 1)
  const [r, setR] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try { setR(await runRetrospective(start, end, ver)) } finally { setBusy(false) }
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-bold text-slate-900">📊 Retrospective Analysis</h3>
      <p className="text-xs text-slate-500">"What if we had used different rules in the past?"</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div><label className="block text-xs text-slate-500">From</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></div>
        <div><label className="block text-xs text-slate-500">To</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></div>
        <div><label className="block text-xs text-slate-500">Simulate under</label>
          <select value={ver} onChange={(e) => setVer(Number(e.target.value))} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm">
            {versions.map((v) => <option key={v.version} value={v.version}>v{v.version} {v.status === 'active' ? '(current)' : ''}</option>)}
          </select></div>
        <button onClick={run} disabled={busy} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">{busy ? 'Running…' : 'Run analysis'}</button>
      </div>
      {r && (
        <div className="mt-4 space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <div className="font-semibold text-slate-900">{r.total_loans} loans in range</div>
          <div>Under original rules: ✅ {r.original.approved} approved · ❌ {r.original.denied} denied</div>
          <div>Under simulated rules: ✅ {r.simulated.approved} approved · ❌ {r.simulated.denied} denied</div>
          <div className="font-semibold text-slate-900">Delta: {r.additional_denials} additional denials, {r.additional_approvals} additional approvals</div>
          <div className="text-slate-600">Of the additional denials: {r.performing_analysis.of_additional_denials.currently_performing} currently performing · {r.performing_analysis.of_additional_denials.currently_delinquent} delinquent</div>
          <p className="italic text-slate-600">"{r.performing_analysis.conclusion}"</p>
        </div>
      )}
    </div>
  )
}

// ════ Audit reconstruction panel ════
export function ReconstructPanel() {
  const [app, setApp] = useState('APP-SC02-004')
  const [when, setWhen] = useState('2026-06-10T14:14')
  const [r, setR] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function go() {
    setBusy(true); setErr(null)
    try { setR(await reconstructDecision(new Date(when).toISOString(), app)) } catch (e: any) { setErr(e?.message || 'Failed'); setR(null) } finally { setBusy(false) }
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-bold text-slate-900">🔍 Reconstruct a Decision</h3>
      <p className="text-xs text-slate-500">"See exactly what Accord looked like at any moment."</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div><label className="block text-xs text-slate-500">Application</label><input value={app} onChange={(e) => setApp(e.target.value)} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></div>
        <div><label className="block text-xs text-slate-500">Date/time</label><input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></div>
        <button onClick={go} disabled={busy} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50">{busy ? 'Reconstructing…' : 'Reconstruct'}</button>
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      {r && (
        <div className="mt-4 space-y-3 rounded-lg bg-slate-50 p-3 text-sm">
          <div><span className="font-bold text-slate-700">RULES ACTIVE:</span> v{r.rules_active.version} (effective {fmt(r.rules_active.effective_from)}) — DTI max {r.rules_active.dti_max}%, credit floor {r.rules_active.credit_floor}, LTV max {r.rules_active.ltv_max}%</div>
          <div><span className="font-bold text-slate-700">DATA SOURCES:</span> OFAC SDN {String(r.ofac_version).slice(0, 10)} ({r.ofac_entries?.toLocaleString()} entries) · Fannie Guide {r.agency_guidelines_version} · Conforming {r.conforming_limit}</div>
          <div><span className="font-bold text-slate-700">BORROWER:</span> {r.entity_state_at_time.borrower || app} — credit {r.entity_state_at_time.credit_score}, DTI {r.entity_state_at_time.dti}%, LTV {r.entity_state_at_time.ltv}%</div>
          <div>
            <span className="font-bold text-slate-700">AI EVALUATION:</span>
            {r.ai_evaluation.length ? <ul className="mt-1 space-y-0.5 text-xs">{r.ai_evaluation.map((d: any, i: number) => <li key={i}>{d.decision_id}: {String(d.outcome).toUpperCase()} {d.confidence != null ? `(${Math.round(d.confidence * 100)}%)` : ''}</li>)}</ul> : <span className="text-slate-400"> none recorded at/before this moment</span>}
          </div>
          {r.human_action && <div><span className="font-bold text-slate-700">HUMAN ACTION:</span> {r.human_action.by} {r.human_action.action} at {fmt(r.human_action.at)}</div>}
        </div>
      )}
    </div>
  )
}
