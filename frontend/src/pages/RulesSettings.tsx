import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  actOnProposal, approveRules, fetchFieldImpacts, fetchPipelineProtection, fetchPolicyProposals,
  fetchProducts, fetchRuleAlerts, fetchRules, fetchRulesHistory, fetchValidationReport,
  previewOverlayImpact, ratifyEmergency,
  type FieldImpact, type PipelineProtection, type PolicyProposal, type PreviewImpactResult,
  type Product, type RuleAlert, type RulesResponse, type TenantVersion,
} from '../api/client'
import RateSheetPanel from '../components/RateSheetPanel'
import RuleValidation from '../components/RuleValidation'
import DataFreshness from '../components/DataFreshness'
import RuleHistory from '../components/RuleHistory'
import {
  EmergencyModal, ExaminationToggle, ExpiringSection, planAllows,
  ReconstructPanel, RetrospectivePanel, ScheduledSection, ShadowSection, SubmitModal, LockedBadge,
} from '../components/RuleVersioning'

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
  // Fix 2: a field the overlay doesn't define (missing/unset → NaN) is not an
  // error — only validate fields that actually carry a value.
  if (Number.isNaN(value)) return null
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

// ── Plain-English helpers for the expandable policy rows ──
const EXPLAIN: Record<string, (v: number) => string> = {
  'credit.min_score': (v) => `Borrowers need a credit score of at least ${v} to qualify at your institution.`,
  'dti.back_max': (v) => `Total monthly debt payments (including the proposed mortgage) cannot exceed ${v}% of the borrower's gross monthly income.`,
  'ltv.max': (v) => `The loan amount cannot exceed ${v}% of the property's appraised value. Above 80% typically requires mortgage insurance.`,
  'fraud.watchlist_threshold': (v) => `Applications with a fraud score above ${v} are automatically blocked and referred to BSA/AML review.`,
  'fraud.identity_min': (v) => `Identity documents must match with at least ${Math.round(v * 100)}% confidence or the file is escalated for manual review.`,
  'income.max_discrepancy_pct': (v) => `If verified income differs from stated income by more than ${v}%, the file is blocked for income reconciliation.`,
  'reserves.primary': (v) => `Borrowers must have at least ${v} months of mortgage payments in liquid reserves after closing.`,
}
const explainFor = (key: string, v: number) => (EXPLAIN[key] ? EXPLAIN[key](v) : 'Your institution-specific overlay rule, applied on top of agency standards.')

function noteFor(key: string, v: number): { text: string; tone: 'up' | 'eq' | 'down' | 'neutral' } {
  if (key === 'credit.min_score') {
    if (v > 620) return { text: '↑ above Fannie min (620)', tone: 'up' }
    if (v === 620) return { text: '= Fannie min', tone: 'eq' }
    return { text: '⚠ below Fannie min', tone: 'down' }
  }
  if (key === 'dti.back_max') {
    if (v === 43) return { text: '= QM safe harbor', tone: 'eq' }
    if (v > 43) return { text: '↑ above QM safe harbor', tone: 'down' }
    return { text: '↓ below QM safe harbor', tone: 'up' }
  }
  if (key === 'ltv.max' && v === 97) return { text: '= Fannie conventional max', tone: 'eq' }
  if (key === 'reserves.primary' && v === 2) return { text: '= Fannie minimum', tone: 'eq' }
  return { text: 'Your overlay', tone: 'neutral' }
}
const FLOOR: Record<string, string> = {
  'credit.min_score': 'Cannot go below 620 (Fannie) · 580 (FHA)',
  'dti.back_max': 'Agency max 50% (Fannie DU) · QM safe harbor 43%',
  'ltv.max': 'Agency max 97% (Fannie conventional)',
}
const floorFor = (key: string) => FLOOR[key] || 'No regulatory floor — this is your overlay only.'

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
  const navigate = useNavigate()
  const [data, setData] = useState<RulesResponse | null>(null)
  const [draft, setDraft] = useState<any>(null)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [showFreshness, setShowFreshness] = useState(false)
  const [showAlerts, setShowAlerts] = useState(false)
  const [alerts, setAlerts] = useState<RuleAlert[]>([])
  const [pendingVersion, setPendingVersion] = useState<number | null>(null)
  const [versions, setVersions] = useState<TenantVersion[]>([])
  const [emergencyPending, setEmergencyPending] = useState<TenantVersion | null>(null)
  const [busy, setBusy] = useState(false)
  const [showSubmit, setShowSubmit] = useState(false)
  const [showEmergency, setShowEmergency] = useState(false)
  const [showRetro, setShowRetro] = useState(false)
  const [showReconstruct, setShowReconstruct] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  const [validationFailed, setValidationFailed] = useState(0)
  const [impact, setImpact] = useState<PreviewImpactResult | null>(null)
  const [impactBusy, setImpactBusy] = useState(false)
  // Redesign state
  const [expandedField, setExpandedField] = useState<string | null>(null)
  const [editingField, setEditingField] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [productCount, setProductCount] = useState(0)
  const [protection, setProtection] = useState<PipelineProtection | null>(null)
  const [fieldImpacts, setFieldImpacts] = useState<Record<string, FieldImpact>>({})
  const [proposals, setProposals] = useState<PolicyProposal[]>([])

  const plan = tenant?.plan
  const examFrozen = data?.examination?.active === true
  const canEdit = (user?.role === 'admin' || user?.role === 'manager') && planAllows(plan, 'business') && !examFrozen
  const isAdmin = user?.role === 'admin'

  function load() {
    fetchRules().then((d) => {
      // Option A: merge overlay_rules into tenant rules for display
      console.log('overlay_rules from API:', d.overlay_rules)
      console.log('tenant rules before merge:', d.tenant?.rules)
      if (d.overlay_rules && Object.keys(d.overlay_rules).length > 0) {
        const overlayMerged = JSON.parse(JSON.stringify(d.tenant?.rules || {}))
        const om = d.overlay_rules as Record<string, number>
        // Map overlay rule_keys to tenant_rules JSONB paths
        const KEY_MAP: Record<string, [string, string]> = {
          dti_back_max:              ['dti',      'back_max'],
          credit_min_score:          ['credit',   'min_score'],
          ltv_max_purchase:          ['ltv',      'max'],
          ltv_max_cashout:           ['ltv',      'cashout_max'],
          ltv_max_investment:        ['ltv',      'investment_max'],
          fraud_score_threshold:     ['fraud',    'block_threshold'],
          income_min_confidence:     ['income',   'confidence_min'],
          reserves_months_required:  ['reserves', 'primary_months'],
          reserves_months_jumbo:     ['reserves', 'jumbo_months'],
          high_dti_senior_review:    ['dti',      'senior_uw_threshold'],
          uw_auto_approve_risk_max:  ['fraud',    'auto_approve_max'],
          uw_escalate_risk_min:      ['fraud',    'escalate_min'],
        }
        Object.entries(om).forEach(([key, val]) => {
          const path = KEY_MAP[key]
          if (path) {
            if (!overlayMerged[path[0]]) overlayMerged[path[0]] = {}
            overlayMerged[path[0]][path[1]] = val
          }
        })
        const merged = { ...d, tenant: d.tenant ? { ...d.tenant, rules: overlayMerged } : d.tenant }
        console.log('overlayMerged result:', overlayMerged)
        setData(merged); setDraft(overlayMerged)
      } else {
        setData(d); setDraft(d.tenant?.rules || {})
      }
    }).catch(() => undefined)
    fetchRuleAlerts().then((d) => setAlerts(d.alerts)).catch(() => undefined)
    fetchRulesHistory().then((h) => {
      setVersions(h.versions)
      const pend = h.versions.find((v) => v.status === 'pending_approval')
      setPendingVersion(pend ? pend.version : null)
      setEmergencyPending(h.versions.find((v) => v.change_type === 'emergency' && v.status === 'active' && !v.ratified_by) || null)
    }).catch(() => undefined)
    fetchValidationReport().then((r) => setValidationFailed(r.failed)).catch(() => undefined)
    fetchProducts().then((r) => { setProducts(r.products); setProductCount(r.active_count) }).catch(() => undefined)
    fetchPipelineProtection().then(setProtection).catch(() => undefined)
    fetchFieldImpacts().then((r) => setFieldImpacts(r.impacts)).catch(() => undefined)
    fetchPolicyProposals().then((r) => setProposals(r.proposals)).catch(() => undefined) // admin-only; 403 for others
  }
  useEffect(load, [])

  async function handleProposalAction(proposalId: string, action: 'accept' | 'dismiss') {
    setProposals((prev) => prev.filter((p) => p.proposal_id !== proposalId))
    try {
      await actOnProposal(proposalId, action)
      if (action === 'accept') {
        setMsg({ kind: 'ok', text: 'Proposal accepted — edit the affected rule below to apply the change, then submit for approval.' })
        document.getElementById('your-policy')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || 'Action failed' })
      load()
    }
  }

  async function ratify(ok: boolean) {
    if (!emergencyPending) return
    setBusy(true)
    try {
      await ratifyEmergency(emergencyPending.version, ok)
      setMsg({ kind: 'ok', text: ok ? `Emergency v${emergencyPending.version} ratified.` : `Emergency reverted.` })
      load()
    } finally { setBusy(false) }
  }

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

  // Shadow impact preview — what the proposed overlay would do to active loans.
  async function runPreview() {
    setImpactBusy(true)
    setImpact(null)
    try {
      setImpact(await previewOverlayImpact(draft))
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || 'Preview failed' })
    } finally {
      setImpactBusy(false)
    }
  }

  if (!data || !draft) return <div className="p-10 text-center text-sm text-slate-400">Loading decision rules…</div>

  const newAlerts = alerts.filter((a) => a.status === 'new').length
  const active = data.tenant
  const waivers: any[] = (draft?.waivers as any[]) || []
  const scheduledVersion = (data.scheduled && data.scheduled[0]) || null

  // Your Policy card summary (dynamic from active overlay)
  // Use draft (overlay-merged) for summary card display
  const cv = get(draft ?? active?.rules, ['credit', 'min_score'])
  const dv = get(draft ?? active?.rules, ['dti', 'back_max'])
  const lv = get(draft ?? active?.rules, ['ltv', 'max'])
  const tightened = [Number(cv) > 620, Number(dv) < 50, Number(lv) < 97].filter(Boolean).length

  const Badge = ({ bg, color, children }: { bg: string; color: string; children: any }) => (
    <span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ background: bg, color }}>{children}</span>
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Policy Studio · {tenant?.name}</h2>
            <p className="text-sm text-slate-500">Three layers protect every AI decision — federal law, agency guidelines, and your policy.</p>
            {active && (
              <p className="mt-1 text-xs text-slate-500">
                Version <span className="font-semibold text-slate-700">v{active.version}</span> · Active since {fmtDate(active.effective_from)}
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
            <button onClick={() => setShowValidation((v) => !v)} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${validationFailed ? 'border-red-300 bg-red-50 text-red-700' : showValidation ? 'border-brand bg-brand-light/40 text-brand-dark' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>
              {validationFailed ? `🔴 Validation (${validationFailed} failed)` : '✅ Rule Validation'}
            </button>
            {planAllows(plan, 'enterprise') && (
              <button onClick={() => setShowRetro((v) => !v)} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${showRetro ? 'border-brand bg-brand-light/40 text-brand-dark' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>📊 Retrospective</button>
            )}
            {planAllows(plan, 'enterprise') && (
              <button onClick={() => setShowReconstruct((v) => !v)} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${showReconstruct ? 'border-brand bg-brand-light/40 text-brand-dark' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>🔍 Reconstruct</button>
            )}
            {planAllows(plan, 'enterprise') && (user?.role === 'admin' || user?.role === 'manager') && !examFrozen && (
              <button onClick={() => setShowEmergency(true)} className="rounded-lg border border-red-300 bg-red-50 px-3 py-1.5 text-sm font-semibold text-red-700 hover:bg-red-100">🔴 Emergency rule change</button>
            )}
          </div>
        </div>
      </div>

      {/* ════ SECTION 1 — Plain English summary (3 cards) ════ */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Federal */}
        <div className="rounded-lg bg-white p-5" style={{ border: '0.5px solid #E5E7EB' }}>
          <div className="flex items-center justify-between">
            <span className="text-2xl">🏛️</span>
            <Badge bg="#d1e8d8" color="#0F4D37">Read-only · Accord-maintained</Badge>
          </div>
          <h3 className="mt-3 text-base font-bold text-slate-900">Federal law</h3>
          <p className="mt-1 text-sm text-slate-600">8 rules apply to every loan you originate. You cannot change these. Accord enforces them automatically.</p>
          <ul className="mt-3 space-y-1 text-sm text-slate-700">
            <li>OFAC screening — required</li>
            <li>QM DTI cap — 43%</li>
            <li>HMDA collection — required</li>
            <li>Adverse action notice — 30 days</li>
          </ul>
          <button onClick={() => navigate('/regulation-transparency?layer=federal')} className="mt-3 text-sm font-semibold text-brand hover:underline">See all 8 federal rules →</button>
        </div>

        {/* Agency */}
        <div className="rounded-lg bg-white p-5" style={{ border: '0.5px solid #E5E7EB' }}>
          <div className="flex items-center justify-between">
            <span className="text-2xl">📜</span>
            <Badge bg="#d1e8d8" color="#0F4D37">Verified Jun 2026 · Accord compliance team</Badge>
          </div>
          <h3 className="mt-3 text-base font-bold text-slate-900">Agency guidelines</h3>
          <p className="mt-1 text-sm text-slate-600">Fannie Mae and FHA set baseline eligibility standards. These are the minimums your loans must meet to be saleable to investors.</p>
          <ul className="mt-3 space-y-1 text-sm text-slate-700">
            <li>Fannie: min credit 620 · max LTV 97% · max DTI 50%</li>
            <li>FHA: min credit 580 · max LTV 96.5%</li>
            <li>Conforming limit: $766,550 (FHFA 2026)</li>
          </ul>
          <button onClick={() => navigate('/regulation-transparency?layer=agency')} className="mt-3 text-sm font-semibold text-brand hover:underline">See all 15 guidelines →</button>
        </div>

        {/* Your Policy */}
        <div className="rounded-lg bg-white p-5" style={{ border: '0.5px solid #E5E7EB' }}>
          <div className="flex items-center justify-between">
            <span className="text-2xl">⚙️</span>
            <Badge bg="#e6f1fb" color="#185fa5">Editable by admin</Badge>
          </div>
          <h3 className="mt-3 text-base font-bold text-slate-900">Your policy</h3>
          <p className="mt-1 text-sm text-slate-600">
            You've tightened {tightened} agency standard{tightened === 1 ? '' : 's'}.
            {cv != null && <> Credit floor raised to {cv} (Fannie min: 620).</>}
            {dv != null && <> DTI capped at {dv}% (QM safe harbor).</>}
          </p>
          {active && (
            <div className="mt-3">
              <Badge bg="#e6f1fb" color="#185fa5">v{active.version} · active {fmtDate(active.effective_from)}</Badge>
            </div>
          )}
          {scheduledVersion && (
            <p className="mt-2 text-xs font-medium" style={{ color: '#633806' }}>
              v{scheduledVersion.version} scheduled: {scheduledVersion.changes_summary || 'overlay update'}
            </p>
          )}
          <button
            onClick={() => document.getElementById('your-policy')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="mt-3 text-sm font-semibold text-brand hover:underline"
          >
            Edit your policy ↓
          </button>
        </div>
      </div>

      {/* Full regulation reference (the old transparency view, still reachable) */}
      <div className="-mt-2 text-right">
        <button onClick={() => navigate('/regulation-transparency')} className="text-sm font-semibold text-brand hover:underline">
          Full regulation reference →
        </button>
      </div>

      {/* Dashboard-wide validation-failure banner */}
      {validationFailed > 0 && !showValidation && (
        <button onClick={() => setShowValidation(true)} className="w-full rounded-xl border border-red-300 bg-red-50 p-4 text-left text-sm font-bold text-red-800 hover:bg-red-100">
          🔴 {validationFailed} rule validation test{validationFailed === 1 ? '' : 's'} failed. Review immediately.
        </button>
      )}

      {showValidation && <RuleValidation tenantName={tenant?.name || 'Tenant'} />}

      {/* Examination-freeze banner */}
      {examFrozen && (
        <div className="rounded-xl border border-slate-300 bg-slate-100 p-4 text-sm font-medium text-slate-700">
          🔒 EXAMINATION MODE — Rule changes frozen{data.examination?.started_at ? ` since ${fmtDate(data.examination.started_at)}` : ''}. {data.examination?.examiner} examination. Contact Admin to end.
        </div>
      )}

      {/* Emergency ratification banner */}
      {emergencyPending && (
        <div className="rounded-xl border border-red-300 bg-red-50 p-4">
          <div className="text-sm font-semibold text-red-800">🔴 EMERGENCY RULE CHANGE requires ratification.</div>
          <div className="mt-0.5 text-xs text-red-700">v{emergencyPending.version} · {emergencyPending.change_reason} · changed by {emergencyPending.created_by || 'a manager'}</div>
          {isAdmin && (
            <div className="mt-2 flex gap-2">
              <button onClick={() => ratify(true)} disabled={busy} className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50">Review and ratify</button>
              <button onClick={() => ratify(false)} disabled={busy} className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100 disabled:opacity-50">Review and revert</button>
            </div>
          )}
        </div>
      )}

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

      {showRetro && (planAllows(plan, 'enterprise')
        ? <RetrospectivePanel versions={versions} />
        : <LockedBadge feature="Retrospective analysis" min="enterprise" />)}
      {showReconstruct && (planAllows(plan, 'enterprise')
        ? <ReconstructPanel />
        : <LockedBadge feature="Audit reconstruction" min="enterprise" />)}

      {/* ════ Learning insights — proposals from underwriter overrides ════ */}
      {proposals.length > 0 && (
        <div>
          <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Learning insights · {proposals.length} pattern{proposals.length !== 1 ? 's' : ''} detected
          </div>
          <div className="mb-2.5 rounded-lg px-3.5 py-2.5 text-xs leading-relaxed" style={{ background: '#d1e8d8', border: '0.5px solid #a8d5b5', color: '#0F4D37' }}>
            🧠 Accord detected patterns in your team's override decisions. These suggested policy changes are based on what your
            underwriters are consistently approving with compensating factors.
          </div>
          <div className="space-y-2">
            {proposals.map((p) => (
              <div key={p.proposal_id} className="rounded-lg bg-white p-4" style={{ border: '0.5px solid #E5E7EB', borderLeft: '3px solid #0F4D37' }}>
                <div className="mb-2 flex items-start justify-between gap-3">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    {p.decision_id.replace(/_/g, ' ')} · {p.override_count} overrides in 30 days
                  </span>
                  <div className="flex shrink-0 gap-1.5">
                    <button
                      onClick={() => handleProposalAction(p.proposal_id, 'dismiss')}
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
                    >
                      Dismiss
                    </button>
                    <button
                      onClick={() => handleProposalAction(p.proposal_id, 'accept')}
                      className="rounded-md px-2.5 py-1 text-[11px] font-semibold text-white hover:brightness-110"
                      style={{ background: '#0F4D37' }}
                    >
                      Review change →
                    </button>
                  </div>
                </div>
                <div className="mb-2 text-xs leading-relaxed text-slate-600">{p.pattern_summary}</div>
                <div className="text-xs font-medium leading-relaxed" style={{ color: '#0F4D37' }}>Suggested: {p.proposed_change}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ════ SECTION 2 — Your Policy (editable, expandable rows) ════ */}
      <div id="your-policy" className="scroll-mt-20 rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wide text-slate-700">Your Policy</h3>
            <p className="text-xs text-slate-500">Click any rule to see what it means, who it affects, and how low you can set it.</p>
          </div>
          {active && <Badge bg="#e6f1fb" color="#185fa5">v{active.version} · editable</Badge>}
        </div>

        {!planAllows(plan, 'business') && <div className="mt-3"><LockedBadge feature="Editing overlay rules" min="business" /></div>}

        <div className="mt-3 divide-y divide-slate-100">
          {CATEGORIES.map((cat) => (
            <div key={cat.key} className="py-1">
              <div className="px-1 py-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">{cat.label}</div>
              {cat.fields.map((f) => {
                const key = f.path.join('.')
                const val = get(draft, f.path)
                const numVal = Number(val)
                const expanded = expandedField === key
                const editing = editingField === key
                const note = noteFor(key, numVal)
                const iss = fieldIssue(cat.key, f.path, numVal, programs)
                const border = iss?.level === 'error' ? 'border-red-400 focus:border-red-500' : iss?.level === 'warn' ? 'border-amber-400 focus:border-amber-500' : 'border-slate-300 focus:border-brand'
                const noteColor = note.tone === 'down' ? 'text-red-600' : note.tone === 'up' ? 'text-green-700' : note.tone === 'eq' ? 'text-slate-500' : 'text-blue-700'
                const fi = fieldImpacts[key]
                return (
                  <div key={key} className="rounded-lg">
                    {/* Collapsed row */}
                    <div
                      onClick={() => setExpandedField(expanded ? null : key)}
                      className="flex cursor-pointer items-center gap-3 px-1 py-2.5 hover:bg-slate-50"
                    >
                      <span className="w-3 text-slate-400">{expanded ? '▾' : '▸'}</span>
                      <span className="flex-1 text-sm text-slate-700">{f.label}</span>
                      <span className="text-sm font-semibold text-slate-900">{Number.isNaN(numVal) ? '—' : val}</span>
                      <span className={`hidden text-xs sm:inline ${noteColor}`}>{note.text}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); setExpandedField(key); setEditingField(key) }}
                        disabled={!canEdit}
                        className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"
                      >
                        Edit
                      </button>
                    </div>

                    {/* Expanded detail panel */}
                    {expanded && (
                      <div className="ml-6 mb-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                        <div><span className="font-semibold text-slate-700">What this means:</span> {explainFor(key, numVal)}</div>
                        <div><span className="font-semibold text-slate-700">Pipeline impact:</span> {fi ? fi.label : 'Calculating…'}</div>
                        <div><span className="font-semibold text-slate-700">Floor:</span> {floorFor(key)}</div>
                        <div><span className="font-semibold text-slate-700">Last changed:</span> {active ? `${fmtDate(active.effective_from)} (v${active.version})` : '—'}</div>
                        {editing && (
                          <div className="flex items-center gap-2 pt-1">
                            <input
                              type="number"
                              step="any"
                              autoFocus
                              value={Number.isNaN(numVal) ? '' : val}
                              disabled={!canEdit}
                              onChange={(e) => update(f.path, e.target.value)}
                              className={`w-28 rounded-md border px-2 py-1 text-sm outline-none disabled:bg-slate-100 ${border}`}
                            />
                            {iss && <span className={`text-xs ${iss.level === 'error' ? 'text-red-600' : 'text-amber-600'}`}>{iss.msg}</span>}
                          </div>
                        )}
                        <div className="flex gap-2 pt-1">
                          {!editing && (
                            <button onClick={() => setEditingField(key)} disabled={!canEdit} className="rounded-md bg-brand px-3 py-1 text-xs font-semibold text-white hover:bg-brand-dark disabled:opacity-40">Change value</button>
                          )}
                          <button
                            onClick={() => setMsg({ kind: 'ok', text: 'To add a time-boxed waiver, contact your Accord compliance team — waivers appear here once approved.' })}
                            disabled={!canEdit}
                            className="rounded-md border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-40"
                          >
                            Add waiver
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Waivers — green chips */}
        {waivers.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {waivers.map((w, i) => (
              <div key={i} style={{ background: '#d1e8d8', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#0F4D37', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>⏱</span>
                Waiver: {w.name} · {w.field} {w.value} (normal: {w.normal}) · expires {w.expires}
              </div>
            ))}
          </div>
        )}

        {/* Scheduled version — amber chip */}
        {scheduledVersion && (
          <div className="mt-1.5" style={{ background: '#faeeda', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#633806', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📅</span>
            Scheduled: v{scheduledVersion.version} · {scheduledVersion.changes_summary || 'overlay update'}{scheduledVersion.change_reason ? ` · ${scheduledVersion.change_reason}` : ''}
            <button onClick={() => navigate('/regulation-transparency?layer=lender')} style={{ marginLeft: 'auto' }} className="font-semibold text-brand hover:underline">View impact</button>
          </div>
        )}

        {/* Validation summary + actions */}
        <div className="mt-4 border-t border-slate-100 pt-4">
          {issues.errs.length === 0
            ? <p className="text-sm font-medium text-green-700">✅ All your rules are at or above regulatory minimums.</p>
            : <p className="text-sm font-medium text-red-600">❌ {issues.errs.length} value(s) below a hard minimum — fix before submitting.</p>}
          {issues.warns.map((w) => <p key={w} className="mt-1 text-sm text-amber-600">⚠ {w}</p>)}

          {msg && <p className={`mt-3 text-sm font-medium ${msg.kind === 'ok' ? 'text-green-700' : 'text-red-600'}`}>{msg.text}</p>}

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={runPreview}
              disabled={!dirty || impactBusy}
              title="See which active loans this overlay change would affect, before submitting."
              className="rounded-lg border border-brand px-4 py-2 text-sm font-semibold text-brand hover:bg-brand-light/40 disabled:opacity-40"
            >
              {impactBusy ? 'Previewing…' : '🔍 Preview Impact'}
            </button>
            <button
              onClick={() => setShowSubmit(true)}
              disabled={!canEdit || !dirty || issues.errs.length > 0}
              title={examFrozen ? 'Rule changes frozen during active examination.' : undefined}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
            >
              Submit for approval
            </button>
            <button onClick={() => exportPdf(data, tenant?.name || 'Tenant')} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">📥 Export PDF</button>
          </div>

          {/* Shadow impact preview result */}
          {impact && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-slate-900">🔍 Impact preview</h4>
                <button onClick={() => setImpact(null)} className="text-xs text-slate-400 hover:text-slate-700">✕ Dismiss</button>
              </div>
              <p className="mt-1 text-sm text-slate-700">{impact.recommendation}</p>
              <p className="mt-0.5 text-xs text-slate-400">{impact.total_loans_affected} affected of {impact.active_loans_evaluated} active loan(s) evaluated.</p>
              {impact.impact_by_decision.length > 0 && (
                <div className="mt-3 space-y-2">
                  {impact.impact_by_decision.map((d) => (
                    <div key={d.decision_id} className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="text-sm font-semibold text-slate-800">
                        {d.decision_id.replace(/_/g, ' ')}
                        <span className="ml-2 text-xs font-normal text-slate-400">threshold {d.threshold}</span>
                      </div>
                      <div className="mt-0.5 text-xs">
                        {d.newly_blocked > 0 && <span className="mr-3 font-medium text-red-600">🔴 {d.newly_blocked} newly blocked</span>}
                        {d.newly_allowed > 0 && <span className="font-medium text-green-700">🟢 {d.newly_allowed} newly allowed</span>}
                      </div>
                      {d.samples.length > 0 && (
                        <ul className="mt-1 space-y-0.5 text-[11px] text-slate-500">
                          {d.samples.map((s, i) => <li key={i}>{s.name} · {s.value} · {s.change}</li>)}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <p className="mt-2 text-xs text-slate-400">
            {examFrozen ? 'Rule changes frozen during active examination.' : 'Submitting opens the timing + pipeline options. Changes require admin approval.'}
          </p>
        </div>
      </div>

      {/* Scheduled / shadow / expiring (Business+) */}
      <ScheduledSection scheduled={data.scheduled || []} />
      <ShadowSection />
      <ExpiringSection expiring={data.expiring || []} />

      {/* ════ SECTION 3 — Rate Sheets (visible, no toggle) ════ */}
      <RateSheetPanel canEdit={canEdit} />

      {/* ════ SECTION 4 — Products (read-only) ════ */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-sm font-bold uppercase tracking-wide text-slate-700">Products · {productCount} product{productCount === 1 ? '' : 's'} active</h3>
        <p className="text-xs text-slate-500">Loan products you originate and the agency that governs each.</p>
        <div className="mt-3">
          {products.length === 0 ? (
            <p className="text-sm text-slate-400">No products configured.</p>
          ) : products.map((p) => (
            <div key={p.product_id} className="flex items-center gap-2.5 border-b border-slate-100 py-2 last:border-0">
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: p.active_indicator ? '#0F4D37' : '#cbd5e1' }} />
              <span className="flex-1 text-[13px] text-slate-800">{p.product_name}</span>
              {p.rate_type && <span className="text-[11px] capitalize text-slate-400">{p.rate_type}</span>}
              <span className="text-[11px] text-slate-400">{p.governing_authority}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ════ SECTION 5 — Pipeline Protection ════ */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-sm font-bold uppercase tracking-wide text-slate-700">Pipeline Protection</h3>
        <p className="mt-1 text-sm text-slate-600">
          Loans rate-locked before a rule change are evaluated under the rules active at their lock date.
          This protects borrowers from mid-process policy changes.
        </p>
        {!protection || !protection.has_history ? (
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-500">
            Pipeline protection activates once you configure your first policy version.
          </p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-4">
                <div className="text-2xl font-bold text-slate-900">{protection.total_locked.toLocaleString()}</div>
                <div className="text-xs text-slate-500">Rate-locked loans</div>
              </div>
              <div className="rounded-lg border border-slate-200 p-4">
                <div className="text-2xl font-bold text-slate-900">{protection.pinned.toLocaleString()} <span className="text-sm font-medium text-slate-400">({protection.pinned_pct}%)</span></div>
                <div className="text-xs text-slate-500">Pinned to a rule version</div>
              </div>
              <div className="rounded-lg border border-slate-200 p-4">
                <div className="text-2xl font-bold text-slate-900">v{protection.current_version ?? '—'}</div>
                <div className="text-xs text-slate-500">Current version</div>
              </div>
            </div>
            {protection.protected.length > 0 && protection.current_version != null && (
              <div className="mt-3 space-y-1.5">
                {protection.protected.map((p) => (
                  <div key={p.pinned_version} className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
                    🛡 {p.count.toLocaleString()} loan{p.count === 1 ? ' is' : 's are'} protected under rule v{p.pinned_version} even though v{protection.current_version} is now active.
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Examination mode toggle (Enterprise admin) */}
      {isAdmin && planAllows(plan, 'enterprise') && <ExaminationToggle exam={data.examination || { active: false }} onChange={load} />}

      {showHistory && <RuleHistory tenantName={tenant?.name || 'Tenant'} versions={versions} canRollback={canEdit} onRolledBack={(m) => { setMsg({ kind: 'ok', text: m }); load() }} onClose={() => { setShowHistory(false); load() }} />}
      {showSubmit && (
        <SubmitModal
          original={data.tenant?.rules || {}}
          draft={draft}
          programs={programs}
          onClose={() => setShowSubmit(false)}
          onDone={(m) => { setShowSubmit(false); setMsg({ kind: 'ok', text: m }); load() }}
        />
      )}
      {showEmergency && (
        <EmergencyModal
          draft={draft}
          onClose={() => setShowEmergency(false)}
          onDone={(m) => { setShowEmergency(false); setMsg({ kind: 'ok', text: m }); load() }}
        />
      )}
    </div>
  )
}
