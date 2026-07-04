import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import {
  fetchLoan, fetchConditions, fetchConditionsSummary,
  fetchSimilarCases, fetchLoanActions, decideLoan, resolveAttentionRequest, createLoanAction,
  type LoanAction, type SimilarCase,
} from '../../api/client'

// Role identifiers — never hardcode role strings inline.
const ROLES = { SENIOR_UW: 'senior_uw', ADMIN: 'admin', UW: 'underwriter', PROCESSOR: 'processor', COMPLIANCE: 'compliance' } as const
const DENIAL_CODES = ['credit', 'income', 'collateral', 'fraud', 'other']
// Override outcomes — value, label, one-line effect. Drives the override modal
// radios and maps to the backend override_outcome.
const OVERRIDE_OUTCOMES = [
  ['clear_block', 'Clear this block', 'allow pipeline to continue'],
  ['approve', 'Approve loan', 'final approval'],
  ['waive_condition', 'Waive condition', 'mark condition as waived'],
  ['deny', 'Deny loan', 'final denial'],
] as const
import type { LoanDetail, InternalRequest, PendingDocRequest } from '../../types/accord'
import ActionModal from './ActionModal'
import EscalationThread from './EscalationThread'
import ActivityFeed from '../ActivityFeed'
import RequestDocsModal from '../modals/RequestDocsModal'

// ── Presentation maps (keyed by API enum values — never business logic) ──────
// Every label/colour below is a lookup on a value the API returns; the component
// branches on data, not on hardcoded condition codes or categories.
const ACTION_LABEL: Record<string, string> = {
  refer_bsa: 'Refer to BSA/AML',
  request_documents: 'Request Documents',
  escalate: 'Escalate to Senior UW',
  senior_review: 'Senior Review Required',
  view_details: 'Review Details',
  add_note: 'Add Note',
}
const ACTION_BTN: Record<string, { label: string; cls: string }> = {
  refer_bsa: { label: 'Refer to BSA', cls: 'bg-[#14532d] text-white' },
  request_documents: { label: 'Request Docs', cls: 'bg-blue-600 text-white' },
  escalate: { label: 'Escalate', cls: 'bg-amber-500 text-white' },
  senior_review: { label: 'Senior Review', cls: 'bg-slate-600 text-white' },
  view_details: { label: 'View Details', cls: 'border border-slate-300 text-slate-700 bg-white' },
}
const ACTION_PRIMARY: Record<string, { label: string; cls: string }> = {
  refer_bsa: { label: '⚠ Refer to BSA/AML', cls: 'bg-red-600 text-white' },
  request_documents: { label: '📄 Request Documents', cls: 'bg-blue-600 text-white' },
  escalate: { label: '↑ Escalate', cls: 'bg-amber-500 text-white' },
  senior_review: { label: '👤 Senior Review', cls: 'bg-slate-600 text-white' },
  view_details: { label: 'Review Details', cls: 'bg-slate-600 text-white' },
}
const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  open: { label: 'Open', cls: 'bg-orange-50 text-orange-700' },
  submitted: { label: 'Submitted', cls: 'bg-amber-50 text-amber-700' },
  in_review: { label: 'In Review', cls: 'bg-blue-50 text-blue-700' },
  approved: { label: 'Approved', cls: 'bg-green-50 text-green-700' },
  waived: { label: 'Waived', cls: 'bg-slate-100 text-slate-600' },
}
const GOV_BADGE: Record<string, { label: string; cls: string }> = {
  federal: { label: '🔒 Federal', cls: 'bg-red-50 text-red-700' },
  agency: { label: '🏦 Agency', cls: 'bg-amber-50 text-amber-700' },
  tenant: { label: '⚙️ Your policy', cls: 'bg-green-50 text-green-700' },
}
const OUTCOME_TAG: Record<string, { label: string; cls: string }> = {
  approve: { label: 'Approved', cls: 'bg-green-50 text-green-700' },
  refer_bsa: { label: 'BSA Referral', cls: 'bg-amber-50 text-amber-700' },
  deny: { label: 'Denied', cls: 'bg-red-50 text-red-700' },
  escalate: { label: 'Escalated', cls: 'bg-amber-50 text-amber-700' },
  request_documents: { label: 'Docs Requested', cls: 'bg-blue-50 text-blue-700' },
  senior_review: { label: 'Senior Review', cls: 'bg-slate-100 text-slate-600' },
}

// ── helpers (all null-safe — never crash on a missing field) ─────────────────
const DASH = '—'
type Cond = Record<string, any>

function initials(name?: string | null): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?'
}
function money(n: number | null | undefined): string {
  return n == null ? DASH : `$${Math.round(n).toLocaleString()}`
}
function pct(n: number | null | undefined): string {
  return n == null ? DASH : `${Math.round(n * 10) / 10}%`
}
function pretty(s?: string | null): string {
  if (!s) return DASH
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
// Relative "time ago" for the internal-request banner. The backend sends a naive
// UTC timestamp (isoformat, no offset), so treat a tz-less string as UTC.
function timeAgo(iso?: string | null): string {
  if (!iso) return ''
  const ms = new Date(/[Z+]/.test(iso) ? iso : `${iso}Z`).getTime()
  if (isNaN(ms)) return ''
  const secs = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}
function shortDate(iso?: string | null): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (isNaN(d.getTime())) return DASH
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
function isBlocking(c: Cond): boolean {
  return c.blocks_closing === true && !['approved', 'waived'].includes(c.status)
}
function isCleared(c: Cond): boolean {
  return ['approved', 'waived'].includes(c.status)
}

// 0 is a "not computed" sentinel for DTI / FICO (no real loan has a 0% DTI or a
// 0 credit score), so treat it as missing rather than displaying "0%".
function nonZero(n: number | null | undefined): number | null {
  return n == null || n === 0 ? null : n
}

// Fallback: pull a number out of a persona decision's signals when the flat
// metric is null (e.g. metrics.dti missing -> read the DTI signal value).
function signalNumber(loan: any, decisionId: string, keywords: string[]): number | null {
  const d = (loan?.decisions ?? []).find((x: any) => x.decision_id === decisionId)
  for (const s of d?.signals ?? []) {
    const key = String(s?.key ?? '').toLowerCase()
    if (keywords.some((k) => key.includes(k))) {
      const m = String(s?.value ?? '').match(/-?\d+(\.\d+)?/)
      if (m) return parseFloat(m[0])
    }
  }
  return null
}

// FHFA 2026 baseline conforming limit — display heuristic only (real limits are
// county/year-specific; ideally catalogue-driven). Used to label 'other' loans.
const CONFORMING_LIMIT = 766550
const LOAN_TYPE_MAP: Record<string, string> = {
  non_qm: 'Non-QM', nonqm: 'Non-QM', 'non qm': 'Non-QM',
  conforming: 'Conforming', jumbo: 'Jumbo', fha: 'FHA', va: 'VA',
  usda: 'USDA', conventional: 'Conventional',
}
function loanProgram(raw: string | null | undefined, amount: number | null | undefined): string {
  const v = String(raw ?? '').trim().toLowerCase()
  if (!v || v === 'other' || v === 'unknown') {
    if (amount != null) return amount <= CONFORMING_LIMIT ? 'Conforming' : 'Jumbo'
    return DASH
  }
  return LOAN_TYPE_MAP[v] ?? pretty(v)
}

// When a loan is blocked but no formal condition exists yet, derive the
// recommended action from the blocking persona (real decision outcome).
const PERSONA_ACTION: Record<string, string> = {
  fraud_screening: 'refer_bsa',
  compliance_check: 'escalate',
  product_eligibility: 'escalate',
}
function blockingActionType(loan: any): string | null {
  const bp = loan?.blocking_persona
  if (!bp) return null
  return PERSONA_ACTION[bp] ?? 'senior_review'
}

function Pill({ cls, children }: { cls: string; children: ReactNode }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>
}

export default function LoanSummaryWorkbench({ applicationId }: { applicationId: string }) {
  const navigate = useNavigate()
  const { effectiveUser, permissions } = useAuth()
  const role = effectiveUser?.role ?? ''
  const isSeniorUW = role === ROLES.SENIOR_UW
  // Decision authority needs BOTH the role's override_decision permission AND an
  // effective role that actually decides (senior_uw / admin). This keeps an
  // impersonated underwriter from ever seeing Approve/Deny/Override even when the
  // real session carries the permission.
  const canOverride = permissions?.override_decision === true && (role === ROLES.SENIOR_UW || role === ROLES.ADMIN)
  // senior_uw / admin ARE the escalation target — they can't escalate further.
  const canEscalate = role !== ROLES.SENIOR_UW && role !== ROLES.ADMIN
  const [decideModal, setDecideModal] = useState<null | 'approve' | 'deny' | 'override'>(null)

  const [loan, setLoan] = useState<LoanDetail | null>(null)
  const [conditions, setConditions] = useState<Cond[]>([])
  const [summary, setSummary] = useState<Record<string, any> | null>(null)
  const [similar, setSimilar] = useState<{ cases: SimilarCase[]; based_on?: { loan_type: string | null } } | null>(null)
  const [actions, setActions] = useState<LoanAction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  const [filter, setFilter] = useState<'all' | 'blocking' | 'review' | 'cleared'>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [modalAction, setModalAction] = useState<string | null>(null)
  const [threadOpen, setThreadOpen] = useState(false)
  // Request-docs gets its OWN modal — it is a document request to the borrower
  // (POST /communications), NOT an escalation/note recorded via ActionModal.
  // The two never share a modal component.
  const [showRequestDocsModal, setShowRequestDocsModal] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [searchParams] = useSearchParams()
  const focusRequestId = searchParams.get('request_id')
  const [resolvedReqs, setResolvedReqs] = useState<Set<string>>(new Set())
  const [replyReq, setReplyReq] = useState<InternalRequest | null>(null)
  const [docsDismissed, setDocsDismissed] = useState<Set<string>>(new Set())
  const [returnOpen, setReturnOpen] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [recommendOpen, setRecommendOpen] = useState(false)
  const [recommended, setRecommended] = useState(false)
  const [newDoc, setNewDoc] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    // Only fetchLoan can fail the page. Conditions / summary / similar-cases /
    // actions each degrade to an empty result so a loan with no conditions yet
    // (the common case — most loans have none) renders a clean empty state
    // instead of an error.
    const EMPTY_SUMMARY = {
      total_conditions: 0, open_conditions: 0, blocking_conditions: 0,
      cleared_conditions: 0, overdue_conditions: 0,
    }
    Promise.all([
      fetchLoan(applicationId),
      fetchConditions(applicationId).catch(() => [] as Cond[]),
      fetchConditionsSummary(applicationId).catch(() => EMPTY_SUMMARY),
      fetchSimilarCases(applicationId).catch(() => ({ cases: [] as SimilarCase[] })),
      fetchLoanActions(applicationId).catch(() => ({ actions: [] as LoanAction[] })),
    ])
      .then(([l, c, s, sim, act]) => {
        if (!alive) return
        setLoan(l)
        setConditions(Array.isArray(c) ? c : [])
        setSummary(s ?? null)
        setSimilar(sim as any)
        setActions(act.actions ?? [])
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Failed to load loan'))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [applicationId, reload])

  function refetchActions() {
    fetchLoanActions(applicationId).then((d) => setActions(d.actions ?? [])).catch(() => undefined)
  }
  function onActionDone() {
    setModalAction(null)
    refetchActions()
    setToast('Recorded — added to the file.')
    setTimeout(() => setToast(null), 2500)
  }
  // Route every "Request documents" trigger (top nav, action panel, condition
  // rows) to the dedicated doc-request modal; everything else uses ActionModal.
  function openAction(t: string) {
    if (t === 'request_documents') { setShowRequestDocsModal(true); return }
    setModalAction(t)
  }
  // Resolve an internal review request (optionally with a reply). Hides the
  // banner locally on success and shows the green confirmation toast.
  async function resolveRequest(r: InternalRequest, reply?: string) {
    try {
      await resolveAttentionRequest(applicationId, r.request_id, reply)
      setResolvedReqs((prev) => new Set(prev).add(r.request_id))
      setReplyReq(null)
      setToast('Request marked as resolved')
    } catch {
      setToast('Could not resolve the request — please try again.')
    }
    setTimeout(() => setToast(null), 2500)
  }
  // ── Concurrent doc-request + escalation (Pattern A) ────────────────────────
  async function waitForDocs() {
    try {
      await decideLoan(applicationId, { action: 'snooze_pending_docs' })
      setToast("Loan moved to Pending Response — you'll be notified when documents arrive")
      setTimeout(() => setToast(null), 3000)
      navigate('/pipeline')
    } catch {
      setToast('Could not move the loan — please try again.')
      setTimeout(() => setToast(null), 2500)
    }
  }
  function actNow(reqs: PendingDocRequest[]) {
    // Proceed with available info: dismiss the banner + log the decision in the audit trail.
    setDocsDismissed((prev) => { const n = new Set(prev); reqs.forEach((r) => n.add(r.comm_id)); return n })
    createLoanAction(applicationId, {
      action_type: 'add_note',
      reason_text: 'Decision made with doc request outstanding',
    }).catch(() => undefined)
    setToast('Proceeding — noted in the audit trail')
    setTimeout(() => setToast(null), 2500)
  }
  async function returnToUw(message: string) {
    try {
      await decideLoan(applicationId, { action: 'return_to_uw', note: message })
      setReturnOpen(false)
      setToast('Returned to the underwriter')
      setTimeout(() => setToast(null), 2500)
      navigate('/pipeline')
    } catch {
      setToast('Could not return the loan — please try again.')
      setTimeout(() => setToast(null), 2500)
    }
  }
  // Senior UW returns an escalated loan to the underwriter with structured feedback.
  async function sendFeedback(category: string, message: string) {
    try {
      await decideLoan(applicationId, { action: 'request_more_info', feedback_message: message, feedback_category: category })
      setFeedbackOpen(false)
      setToast(`Feedback sent to ${loan?.escalated_by_name ?? 'the underwriter'}`)
      setTimeout(() => setToast(null), 2500)
      navigate('/pipeline')
    } catch {
      setToast('Could not send feedback — please try again.')
      setTimeout(() => setToast(null), 2500)
    }
  }
  // James addresses senior feedback then re-escalates (resolves the feedback request).
  async function reEscalate(r: InternalRequest) {
    try {
      await resolveAttentionRequest(applicationId, r.request_id)
      await decideLoan(applicationId, { action: 'escalate' })
      setToast('Re-escalated to senior UW')
      setTimeout(() => setToast(null), 2500)
      navigate('/pipeline')
    } catch {
      setToast('Could not re-escalate — please try again.')
      setTimeout(() => setToast(null), 2500)
    }
  }
  // UW recommends a clean file for approval → senior UW decides.
  async function sendRecommendation(notes: string) {
    try {
      await decideLoan(applicationId, { action: 'recommend_approval', note: notes })
      setRecommendOpen(false)
      setRecommended(true)
      setToast('Recommendation sent to Senior UW')
      setTimeout(() => setToast(null), 2500)
    } catch {
      setToast('Could not send recommendation — please try again.')
      setTimeout(() => setToast(null), 2500)
    }
  }

  // Auto-refresh documents: poll every 30s; if a new doc arrives, refresh + badge.
  const docCountRef = useRef(0)
  useEffect(() => { docCountRef.current = loan?.documents?.length ?? 0 }, [loan])
  const loaded = !!loan
  useEffect(() => {
    if (!loaded) return
    const id = setInterval(() => {
      fetchLoan(applicationId)
        .then((fresh) => {
          if ((fresh.documents?.length ?? 0) > docCountRef.current) {
            setNewDoc(true)
            setLoan(fresh)
          }
        })
        .catch(() => undefined)
    }, 30000)
    return () => clearInterval(id)
  }, [applicationId, loaded])
  function toggle(id: string) {
    setExpanded((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  // ── derived (all from API data) ────────────────────────────────────────────
  const blockingConds = useMemo(() => conditions.filter(isBlocking), [conditions])
  const firstBlocking = useMemo(
    () => conditions.find((c) => isBlocking(c) && c.status === 'open') ?? blockingConds[0] ?? null,
    [conditions, blockingConds],
  )
  const loanType = similar?.based_on?.loan_type ?? null
  const lockDays = loan?.metrics?.lock_days_remaining ?? null
  const docCount = loan?.documents?.length ?? null
  // Prefer the decision that actually drove the outcome — fraud first — so a
  // fraud-blocked loan shows the fraud rationale, not e.g. compliance_check.
  const aiDecision = useMemo(() => {
    const withText = (loan?.decisions ?? []).filter((d) => d.explanation)
    const PRIORITY = ['fraud_screening', 'underwriting_decision', 'closing_readiness']
    for (const id of PRIORITY) {
      const hit = withText.find((d) => d.decision_id === id && (d.outcome === 'block' || d.outcome === 'escalate'))
      if (hit) return hit
    }
    return withText.find((d) => d.outcome === 'block') ?? withText[0]
  }, [loan])
  const ruleVersion = useMemo(() => {
    for (const d of loan?.decisions ?? []) if (d.rule_version_number != null) return d.rule_version_number
    return null
  }, [loan])
  const citations = useMemo(() => {
    const set = new Set<string>()
    conditions.forEach((c) => { if (c.agency_citation) set.add(c.agency_citation) })
    return [...set]
  }, [conditions])

  if (loading) return <Skeleton appId={applicationId} />
  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <p className="text-red-600">{error}</p>
        <button onClick={() => setReload((r) => r + 1)} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white">Retry</button>
      </div>
    )
  }
  if (!loan) return null

  const filtered = conditions.filter((c) => {
    if (filter === 'blocking') return isBlocking(c)
    if (filter === 'cleared') return isCleared(c)
    if (filter === 'review') return !isBlocking(c) && !isCleared(c)
    return true
  })

  return (
    <div className="min-h-screen bg-slate-50 pb-16">
      {/* ── SECTION 1 — TOP NAV ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-[#0c1710] px-5 py-2.5 text-white">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold tracking-tight">accord</span>
          <span className="text-white/30">·</span>
          <Link to="/pipeline" className="text-white/70 hover:text-white">← Pipeline</Link>
          <span className="text-white/30">·</span>
          <span className="font-mono text-white/90">{loan.application_id}</span>
          <span className="text-white/30">·</span>
          <span>{loan.borrower?.name ?? DASH}</span>
          <span className="text-white/30">·</span>
          <span>{money(loan.metrics?.loan_amount)}</span>
          {loanProgram(loanType, loan.metrics?.loan_amount) !== DASH && (
            <><span className="text-white/30">·</span><span>{loanProgram(loanType, loan.metrics?.loan_amount)}</span></>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="mr-1 flex items-center gap-2 text-xs text-white/70">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-700 text-[10px] font-bold text-white">{initials(effectiveUser?.name)}</span>
            <span>{effectiveUser?.name ?? 'You'}</span>
          </div>
          <NavBtn onClick={() => setModalAction('add_note')}>Add note</NavBtn>
          <NavBtn onClick={() => setShowRequestDocsModal(true)}>Request docs</NavBtn>
          {canEscalate && <NavBtn onClick={() => setModalAction('escalate')}>Escalate</NavBtn>}
          {canOverride && (
            <>
              <button onClick={() => setDecideModal('override')} className="rounded-md bg-white/15 px-3 py-1 text-xs font-semibold hover:bg-white/25">Override</button>
              <button onClick={() => setDecideModal('approve')} className="rounded-md bg-green-600 px-3 py-1 text-xs font-semibold text-white hover:bg-green-500">Approve</button>
              <button onClick={() => setDecideModal('deny')} className="rounded-md bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-500">Deny</button>
            </>
          )}
          <button
            onClick={() => navigate(`/pipeline/${encodeURIComponent(applicationId)}?view=full`)}
            className="rounded-md bg-white/15 px-3 py-1 text-xs font-semibold hover:bg-white/25"
          >View full decision →</button>
        </div>
      </div>

      {/* ── SECTION 2 — LOAN HEADER ─────────────────────────────────────── */}
      <div className="border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-blue-900 text-sm font-bold text-white">{initials(loan.borrower?.name)}</span>
          <div>
            <div className="text-base font-bold text-slate-900">{loan.borrower?.name ?? DASH}</div>
            <div className="text-xs text-slate-400">Primary Borrower</div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
          <Field label="Loan Purpose" value={pretty((loan as any).loan_purpose ?? (loan as any).metrics?.loan_purpose)} />
          <Field label="Loan Amount" value={money(loan.metrics?.loan_amount)} />
          <Field label="LTV / CLTV" value={pct(loan.metrics?.ltv)} className={loan.metrics?.ltv != null && loan.metrics.ltv > 80 ? 'text-amber-600' : ''} />
          <Field label="DTI" value={pct(nonZero(loan.metrics?.dti) ?? signalNumber(loan, 'dti_calculation', ['dti']))} />
          <Field label="FICO" value={nonZero(loan.metrics?.credit_score) ?? signalNumber(loan, 'credit_assessment', ['credit', 'fico', 'score']) ?? DASH} />
          <Field label="Loan Program" value={loanProgram(loanType, loan.metrics?.loan_amount)} />
          <Field label="AUS Result" value={(loan as any).aus_result ?? (loan as any).metrics?.aus_result ?? DASH} />
          <Field
            label="Rate Lock Expires"
            value={lockDays == null ? DASH : `${lockDays} days`}
            className={lockDays != null && lockDays < 3 ? 'text-red-600' : lockDays != null && lockDays < 7 ? 'text-amber-600' : ''}
          />
          <Field
            label="Assigned To"
            value={loan.assigned_to
              ? (loan.assigned_to === effectiveUser?.user_id
                  ? `${loan.assigned_to_name ?? effectiveUser?.name ?? ''} (You)`
                  : (loan.assigned_to_name ?? DASH))
              : DASH}
          />
        </div>
      </div>

      {/* ── SECTION 3 — STATUS ROW ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 divide-y divide-slate-200 border-b border-slate-200 bg-white md:grid-cols-4 md:divide-x md:divide-y-0">
        <StatusCell
          status={loan.status}
          blockingPersona={loan.blocking_persona}
          escalatedByName={loan.escalated_by ? loan.escalated_by_name : null}
          escalatedAt={loan.escalated_by ? loan.escalated_at : null}
        />
        <RecommendedCell
          cond={firstBlocking}
          fallbackAction={firstBlocking ? null : blockingActionType(loan)}
          blockingPersona={loan.blocking_persona}
        />
        <ReadinessCell summary={summary} />
        <AtAGlanceCell summary={summary} conditions={conditions} lockDays={lockDays} />
      </div>

      {/* ── SECTION 4 — REVIEW AREA STRIP ───────────────────────────────── */}
      <ReviewStrip conditions={conditions} />

      {/* ── ESCALATION BANNER (senior UW, escalated to me) ──────────────── */}
      {isSeniorUW && loan.escalated_by && loan.assigned_to === effectiveUser?.user_id && (
        <div className="mx-5 mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4">
          <div className="text-sm font-bold text-amber-800">⚠ Escalated to you by {loan.escalated_by_name ?? DASH}</div>
          <div className="mt-1 grid gap-0.5 text-[12px] text-amber-900">
            {loan.escalation_category && <div><span className="font-semibold">Category:</span> {pretty(loan.escalation_category)}</div>}
            {loan.escalation_reason && <div><span className="font-semibold">Reason:</span> {loan.escalation_reason}</div>}
            {loan.escalated_at && <div><span className="font-semibold">Escalated:</span> {new Date(loan.escalated_at).toLocaleString()}</div>}
          </div>
          <div className="mt-1.5 text-[11px] text-amber-700">{loan.escalated_by_name ?? 'The underwriter'} is waiting for your review.</div>
          {(loan.escalation_thread?.length ?? 0) > 0 && (
            <div className="mt-2 border-t border-amber-200 pt-2">
              <button
                onClick={() => setThreadOpen((v) => !v)}
                className="text-[11px] font-semibold text-amber-800 hover:underline"
              >
                {threadOpen ? 'Hide full thread ▲' : 'Show full thread ▼'}
              </button>
              {threadOpen && (
                <div className="mt-2 rounded-lg border border-amber-200 bg-white/60 p-3">
                  <EscalationThread items={loan.escalation_thread!} />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── DIRECT ASSIGNMENT BANNER (rule-routed straight to me — not escalated) ── */}
      {isSeniorUW && loan.direct_assignment && !loan.escalated_by && loan.assigned_to === effectiveUser?.user_id && (
        <div className="mx-5 mt-4 rounded-lg border border-blue-300 bg-blue-50 p-4">
          <div className="text-sm font-bold text-blue-800">🔵 Direct assignment</div>
          <div className="mt-1 text-[12px] text-blue-900">This loan was routed directly to you at intake by an assignment rule (loan characteristics) — no underwriter review preceded it.</div>
        </div>
      )}

      {/* ── NEW DOCUMENT BADGE (borrower uploaded; auto-refreshed) ────────── */}
      {newDoc && (
        <div className="mx-5 mt-4 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm">
          <span className="font-semibold text-blue-800">📄 New document uploaded</span>
          <span className="text-blue-700">The document list has been refreshed.</span>
          <button onClick={() => setNewDoc(false)} className="ml-auto rounded px-1.5 text-blue-600 hover:text-blue-800" title="Dismiss">✕</button>
        </div>
      )}

      {/* ── DOCS PENDING BANNER (open doc requests on this loan) ──────────── */}
      {(() => {
        const pd = (loan.pending_doc_requests ?? []).filter((r) => !docsDismissed.has(r.comm_id))
        if (pd.length === 0) return null
        return (
          <div className="mx-5 mt-4 rounded-lg border border-amber-300 border-l-4 border-l-amber-500 bg-amber-50 p-4">
            {pd.map((r) => (
              <div key={r.comm_id} className="mb-2 last:mb-0">
                <div className="text-sm font-bold text-amber-800">📎 Document request pending</div>
                <div className="mt-1 text-[13px] text-amber-900">
                  {r.requested_by_name ?? 'A teammate'} requested the following from {loan.borrower?.name ?? 'the borrower'}
                  {r.requested_at ? ` on ${shortDate(r.requested_at)}` : ''}:
                </div>
                <ul className="mt-1 list-disc pl-5 text-[13px] text-amber-900">
                  {(r.document_types ?? []).map((d) => <li key={d}>{d}</li>)}
                </ul>
                {r.message && <p className="mt-1 text-[12px] text-amber-800">{r.message}</p>}
                <div className="mt-1 text-[11px] text-amber-700">
                  {r.due_date ? `Due: ${shortDate(r.due_date)} · ` : ''}Status: Awaiting borrower
                </div>
              </div>
            ))}
            <div className="mt-2 flex flex-wrap gap-2">
              <button onClick={waitForDocs} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-500">Wait for docs</button>
              <button onClick={() => actNow(pd)} className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100">Act now</button>
              <button onClick={() => setReturnOpen(true)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">Return to UW</button>
            </div>
          </div>
        )
      })()}

      {/* ── INTERNAL REQUEST BANNER (pending request directed at me) ──────── */}
      {(loan.internal_requests ?? [])
        .filter((r) => !resolvedReqs.has(r.request_id))
        .sort((a, b) => Number(b.request_id === focusRequestId) - Number(a.request_id === focusRequestId))
        .map((r) => r.source === 'senior_uw_feedback' ? (
          <div key={r.request_id} className="mx-5 mt-4 rounded-lg border border-amber-300 border-l-4 border-l-amber-500 bg-amber-50 p-4">
            <div className="text-sm font-bold text-amber-800">⚠ Feedback from {r.from}</div>
            {r.category && <div className="mt-0.5 text-[12px] capitalize text-amber-900"><span className="font-semibold">Category:</span> {r.category}</div>}
            <p className="mt-1 text-sm text-slate-700">"{r.message}"</p>
            <div className="mt-1 text-[11px] text-amber-700">Received: {timeAgo(r.created_at)}</div>
            <div className="mt-3 flex gap-2">
              <button onClick={() => reEscalate(r)} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-500">Re-escalate after addressing</button>
              <button onClick={() => resolveRequest(r)} className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100">Mark resolved</button>
            </div>
          </div>
        ) : (
          <div key={r.request_id} className="mx-5 mt-4 rounded-lg border border-blue-200 border-l-4 border-l-blue-500 bg-blue-50 p-4">
            <div className="text-sm font-bold text-blue-800">📋 Internal request from {r.from}</div>
            <p className="mt-1 text-sm text-slate-700">"{r.message}"</p>
            <div className="mt-1 text-[11px] text-slate-500">
              Priority: <span className="capitalize">{r.priority}</span> · Received: {timeAgo(r.created_at)}
            </div>
            <div className="mt-3 flex gap-2">
              <button onClick={() => resolveRequest(r)} className="rounded-lg bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-500">Mark resolved</button>
              <button onClick={() => setReplyReq(r)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">Reply</button>
            </div>
          </div>
        ))}

      {/* ── SECTION 5 — AI SUMMARY BANNER ───────────────────────────────── */}
      {aiDecision && (
        <div className="mx-5 mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">
            AI Summary
            {aiDecision.confidence != null && <> · {Math.round(aiDecision.confidence * 100)}% confidence</>}
            {docCount != null && <> · {docCount} documents indexed</>}
            {ruleVersion != null && <> · Rule v{ruleVersion}</>}
          </div>
          <p className="mt-1.5 text-sm text-slate-700">{aiDecision.explanation}</p>
          {citations.length > 0 && (
            <p className="mt-2 text-[11px] text-slate-400">{citations.join(' · ')}</p>
          )}
        </div>
      )}

      {/* ── SECTION 6 — MAIN GRID ───────────────────────────────────────── */}
      <div className="mx-5 mt-4 flex flex-col gap-5 lg:flex-row">
        {/* LEFT — conditions table */}
        <div className="flex-1">
          <div className="rounded-xl border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
              <span className="text-sm font-bold text-slate-900">Needs Your Attention</span>
              <Pill cls="bg-red-50 text-red-700">{summary?.blocking_conditions ?? 0} blocking</Pill>
              <Pill cls="bg-amber-50 text-amber-700">{summary?.open_conditions ?? 0} open</Pill>
              <div className="ml-auto flex items-center gap-2">
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value as any)}
                  className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600"
                >
                  <option value="all">All</option>
                  <option value="blocking">Blocking</option>
                  <option value="review">Needs Review</option>
                  <option value="cleared">Cleared</option>
                </select>
              </div>
            </div>

            {conditions.length === 0 ? (
              <div className="px-4 py-12 text-center">
                <div className="text-sm font-medium text-slate-500">No conditions found for this loan</div>
                <div className="mt-1 text-xs text-slate-400">Conditions will appear here as the loan is processed by the decision engine.</div>
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-slate-400">No conditions in this view.</div>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-100 text-[10px] uppercase tracking-wide text-slate-400">
                    <th className="px-3 py-2 font-semibold">Condition</th>
                    <th className="px-2 py-2 font-semibold">Category</th>
                    <th className="px-2 py-2 font-semibold">Severity</th>
                    <th className="px-2 py-2 font-semibold">Status</th>
                    <th className="px-2 py-2 font-semibold">Owner</th>
                    <th className="px-2 py-2 font-semibold">Due</th>
                    <th className="px-2 py-2 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => (
                    <ConditionRow
                      key={c.id}
                      c={c}
                      actions={actions}
                      expanded={expanded.has(c.id)}
                      onToggle={() => toggle(c.id)}
                      onAction={openAction}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Audit trail — override entries render as the exam-ready record. */}
          <ActivityFeed activity={loan.activity ?? []} />
        </div>

        {/* RIGHT — sticky panel */}
        <div className="w-full lg:w-64">
          <div className="space-y-4 lg:sticky lg:top-4">
            <ActionPanel
              cond={firstBlocking}
              fallbackAction={firstBlocking ? null : blockingActionType(loan)}
              blockingPersona={loan.blocking_persona}
              canOverride={canOverride}
              canEscalate={canEscalate}
              showFeedback={isSeniorUW && !!loan.escalated_by}
              showRecommend={role === ROLES.UW && (summary?.blocking_conditions ?? 0) === 0 && loan.assigned_to === effectiveUser?.user_id && !recommended}
              recommendedPending={recommended}
              onAction={openAction}
              onDecide={(m) => setDecideModal(m)}
              onSendFeedback={() => setFeedbackOpen(true)}
              onRecommend={() => setRecommendOpen(true)}
            />
            <SimilarFiles similar={similar} />
          </div>
        </div>
      </div>

      {/* ── SECTION 8 — FOOTER ──────────────────────────────────────────── */}
      <div className="fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-200 bg-white px-5 py-2 text-[11px] text-slate-500">
        <span className="font-semibold text-green-700">✓ Audit ready</span>
        {docCount != null && <><span className="text-slate-300">·</span><span>{docCount} documents indexed</span></>}
        {aiDecision?.confidence != null && <><span className="text-slate-300">·</span><span>{Math.round(aiDecision.confidence * 100)}% confidence</span></>}
        {ruleVersion != null && <><span className="text-slate-300">·</span><span>Rule v{ruleVersion}</span></>}
        <span className="ml-auto">
          <button onClick={() => window.open(`/loans/${encodeURIComponent(applicationId)}/examiner-report`, '_blank')} className="font-semibold text-blue-600 hover:underline">Exam-ready export →</button>
        </span>
      </div>

      {modalAction && (
        <ActionModal
          appId={applicationId}
          actionType={modalAction}
          relatedDecisionId={null}
          escalationThread={loan.escalation_thread}
          youName={effectiveUser?.name}
          onClose={() => setModalAction(null)}
          onDone={onActionDone}
        />
      )}
      {decideModal && (
        <DecideModal
          mode={decideModal}
          loan={loan}
          onClose={() => setDecideModal(null)}
          onDone={(msg) => {
            setDecideModal(null)
            setToast(msg)
            setTimeout(() => setToast(null), 2500)
            setReload((r) => r + 1)
          }}
        />
      )}
      {showRequestDocsModal && (
        <RequestDocsModal
          applicationId={loan.application_id}
          borrowerName={loan.borrower?.name}
          borrowerEmail={loan.borrower_email}
          coBorrowerEmail={(loan as any).co_borrower_email}
          onClose={() => setShowRequestDocsModal(false)}
          onDone={(msg) => {
            setShowRequestDocsModal(false)
            setToast(msg)
            setTimeout(() => setToast(null), 2500)
            setReload((r) => r + 1)
          }}
        />
      )}
      {replyReq && (
        <RequestReplyModal
          request={replyReq}
          onClose={() => setReplyReq(null)}
          onSend={(reply) => resolveRequest(replyReq, reply)}
        />
      )}
      {returnOpen && (
        <ReturnToUwModal onClose={() => setReturnOpen(false)} onSend={(msg) => returnToUw(msg)} />
      )}
      {feedbackOpen && (
        <FeedbackModal toName={loan.escalated_by_name ?? 'the underwriter'} onClose={() => setFeedbackOpen(false)} onSend={(cat, msg) => sendFeedback(cat, msg)} />
      )}
      {recommendOpen && (
        <RecommendModal
          borrowerName={loan.borrower?.name ?? DASH}
          creditScore={nonZero(loan.metrics?.credit_score) ?? DASH}
          ltv={pct(loan.metrics?.ltv)}
          dti={pct(nonZero(loan.metrics?.dti) ?? signalNumber(loan, 'dti_calculation', ['dti']))}
          ausResult={(loan as any).aus_result ?? DASH}
          onClose={() => setRecommendOpen(false)}
          onSend={(notes) => sendRecommendation(notes)}
        />
      )}
      {toast && (
        <div className="fixed bottom-16 left-1/2 z-40 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}

// ── small components ─────────────────────────────────────────────────────────
function NavBtn({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} className="rounded-md border border-white/20 px-2.5 py-1 text-xs font-medium text-white/90 hover:bg-white/10">{children}</button>
}

function DecideModal({ mode, loan, onClose, onDone }: {
  mode: 'approve' | 'deny' | 'override'; loan: LoanDetail; onClose: () => void; onDone: (msg: string) => void
}) {
  const [reasoning, setReasoning] = useState('')
  const [conditions, setConditions] = useState('')
  const [denialReason, setDenialReason] = useState('')
  const [denialCode, setDenialCode] = useState(DENIAL_CODES[0])
  const [decisionId, setDecisionId] = useState((loan.decisions?.[0] as any)?.decision_id ?? '')
  const [overrideOutcome, setOverrideOutcome] = useState<'clear_block' | 'approve' | 'waive_condition' | 'deny'>('clear_block')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const selDec = (loan.decisions ?? []).find((d: any) => d.decision_id === decisionId) as any
  const title = mode === 'approve' ? 'Approve Loan' : mode === 'deny' ? 'Deny Loan' : 'Override decision'
  const amount = money(loan.metrics?.loan_amount)
  const name = loan.borrower?.name ?? 'this borrower'
  const ready = mode === 'deny' ? denialReason.trim().length >= 50
    : mode === 'override' ? (!!decisionId && !!overrideOutcome && reasoning.trim().length >= 50)
    : reasoning.trim().length >= 25

  async function submit() {
    if (!ready || busy) return
    setBusy(true); setErr(null)
    try {
      const body = mode === 'approve' ? { action: 'approve' as const, reasoning: reasoning.trim(), conditions: conditions.trim() || undefined }
        : mode === 'deny' ? { action: 'deny' as const, denial_reason: denialReason.trim(), denial_code: denialCode }
        : { action: 'override' as const, decision_id: decisionId, override_outcome: overrideOutcome, override_reason: reasoning.trim() }
      const res = await decideLoan(loan.application_id, body)
      onDone(res?.title || 'Done')
    } catch {
      setErr('Could not complete the action — please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-base font-bold text-slate-900">{title}</div>
        {(mode === 'approve' || mode === 'deny') && (
          <div className={`mt-2 rounded-lg p-2.5 text-[12px] ${mode === 'approve' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
            This will {mode} {name}'s application for {amount}.
          </div>
        )}
        <div className="mt-3 space-y-3 text-sm">
          {mode === 'override' && (
            <>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600">Decision to override</span>
                <select value={decisionId} onChange={(e) => setDecisionId(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                  {(loan.decisions ?? []).map((d: any) => <option key={d.decision_id} value={d.decision_id}>{(d.persona_name ?? d.decision_id)} — {d.outcome}</option>)}
                </select>
              </label>
              {selDec && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-[12px] leading-relaxed">
                  <div><span className="text-slate-500">Decision:</span> <span className="font-semibold text-slate-800">{selDec.persona_name ?? selDec.decision_id}</span></div>
                  <div><span className="text-slate-500">Original outcome:</span> <span className="font-bold uppercase text-slate-800">{selDec.outcome}</span></div>
                  {selDec.rule && <div><span className="text-slate-500">Rule citation:</span> <span className="font-mono text-slate-700">{selDec.rule}</span></div>}
                </div>
              )}
              <div>
                <span className="mb-1 block text-xs font-medium text-slate-600">Override outcome <span className="text-red-500">*</span></span>
                <div className="space-y-1.5">
                  {OVERRIDE_OUTCOMES.map(([val, label, desc]) => (
                    <label key={val} className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-1.5 ${overrideOutcome === val ? 'border-[#14532d] bg-green-50' : 'border-slate-200 hover:border-slate-300'}`}>
                      <input type="radio" name="ovout" checked={overrideOutcome === val} onChange={() => setOverrideOutcome(val)} className="mt-0.5 accent-[#14532d]" />
                      <span className="text-[12px]"><span className="font-medium text-slate-800">{label}</span> <span className="text-slate-500">— {desc}</span></span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] font-medium text-amber-800">
                <span>⚠</span><span>Override decisions are permanent and appear in the regulatory audit trail.</span>
              </div>
            </>
          )}
          {mode === 'approve' && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-600">Conditions (optional)</span>
              <textarea value={conditions} onChange={(e) => setConditions(e.target.value)} rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]" />
            </label>
          )}
          {mode === 'deny' && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-600">Denial code</span>
              <select value={denialCode} onChange={(e) => setDenialCode(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                {DENIAL_CODES.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}
              </select>
            </label>
          )}
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-xs font-medium text-slate-600">
              <span>{mode === 'deny' ? 'Denial reason' : mode === 'override' ? 'Override reason' : 'Reasoning'} <span className="text-red-500">*</span></span>
              <span className="text-slate-400">{(mode === 'deny' ? denialReason : reasoning).trim().length}/{mode === 'deny' || mode === 'override' ? 50 : 25} min</span>
            </span>
            <textarea
              value={mode === 'deny' ? denialReason : reasoning}
              onChange={(e) => (mode === 'deny' ? setDenialReason(e.target.value) : setReasoning(e.target.value))}
              rows={4}
              placeholder={mode === 'override' ? 'Document the specific reason for overriding this decision. This will appear in the exam-ready audit trail.' : undefined}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]"
            />
          </label>
          {err && <p className="text-sm font-medium text-red-600">{err}</p>}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={!ready || busy} className={`rounded-lg px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40 ${mode === 'deny' ? 'bg-red-600' : mode === 'approve' ? 'bg-green-600' : 'bg-[#14532d]'}`}>
            {busy ? 'Working…' : mode === 'override' ? 'Confirm override' : title}
          </button>
        </div>
      </div>
    </div>
  )
}

// RequestDocsModal + its helpers now live in ../modals/RequestDocsModal.tsx
// (shared with the UW queue cards in pages/MyQueue.tsx).

// UW recommend-for-approval modal — read-only summary + optional notes.
function RecommendModal({ borrowerName, creditScore, ltv, dti, ausResult, onClose, onSend }: {
  borrowerName: string; creditScore: ReactNode; ltv: ReactNode; dti: ReactNode; ausResult: ReactNode
  onClose: () => void; onSend: (notes: string) => void
}) {
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-base font-bold text-slate-900">Recommend for approval</div>
        <div className="mt-1 text-[12px] text-slate-500">Send your recommendation to the senior underwriter for final decision.</div>
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
          <div className="font-semibold text-slate-800">{borrowerName}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-slate-600">
            <span>FICO: <span className="font-medium text-slate-800">{creditScore}</span></span>
            <span>LTV: <span className="font-medium text-slate-800">{ltv}</span></span>
            <span>DTI: <span className="font-medium text-slate-800">{dti}</span></span>
            <span>AUS: <span className="font-medium text-slate-800">{ausResult}</span></span>
          </div>
        </div>
        <div className="mt-4">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-slate-600">Notes (optional)</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} autoFocus placeholder="Any notes for the senior underwriter…" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]" />
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={() => { setBusy(true); onSend(notes.trim()) }} disabled={busy} className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-green-500 disabled:opacity-40">
            {busy ? 'Sending…' : 'Send recommendation'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Senior-UW feedback modal — category radios + message (min 25) → return to UW.
const FEEDBACK_CATEGORIES: Array<[string, string]> = [
  ['documentation', 'Documentation needed'],
  ['income', 'Income clarification'],
  ['employment', 'Employment verification'],
  ['property', 'Property concern'],
  ['compliance', 'Compliance issue'],
  ['other', 'Other'],
]

function FeedbackModal({ toName, onClose, onSend }: {
  toName: string; onClose: () => void; onSend: (category: string, message: string) => void
}) {
  const [category, setCategory] = useState('documentation')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const len = message.trim().length
  const ready = len >= 25 && !busy
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-base font-bold text-slate-900">Send feedback to underwriter</div>
        <div className="mt-1 text-[12px] text-slate-500">Return this loan to {toName} with your feedback.</div>

        <div className="mt-4">
          <div className="mb-1.5 text-xs font-semibold text-slate-600">Feedback category</div>
          <div className="space-y-1.5">
            {FEEDBACK_CATEGORIES.map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                <input type="radio" name="fbcat" checked={category === k} onChange={() => setCategory(k)} className="accent-[#14532d]" />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-600">
              <span>Feedback message <span className="text-red-500">*</span></span>
              <span className={len < 25 ? 'text-slate-400' : 'text-green-600'}>{len}/25 min</span>
            </span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              autoFocus
              placeholder={`Explain what you need ${toName} to address before you can make a decision…`}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]"
            />
          </label>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={() => { setBusy(true); onSend(category, message.trim()) }} disabled={!ready}
            className="rounded-lg bg-amber-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-amber-500 disabled:opacity-40">
            {busy ? 'Sending…' : 'Send feedback & return to UW'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Return-to-UW modal — prefilled message; reassigns the loan to the original UW.
function ReturnToUwModal({ onClose, onSend }: { onClose: () => void; onSend: (msg: string) => void }) {
  const [text, setText] = useState('Please wait for borrower documents before escalating.')
  const [busy, setBusy] = useState(false)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-base font-bold text-slate-900">Return to underwriter</div>
        <div className="mt-1 text-[12px] text-slate-500">Hands the loan back to the underwriter who escalated it, with a note.</div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} autoFocus className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]" />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={() => { setBusy(true); onSend(text.trim()) }} disabled={busy || text.trim().length === 0} className="rounded-lg bg-[#14532d] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-40">
            {busy ? 'Returning…' : 'Return to UW'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Simple reply modal — textarea → send reply and resolve the request.
function RequestReplyModal({ request, onClose, onSend }: {
  request: InternalRequest; onClose: () => void; onSend: (reply: string) => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-base font-bold text-slate-900">Reply to {request.from}</div>
        <div className="mt-1 text-[12px] italic text-slate-500">"{request.message}"</div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          autoFocus
          placeholder="Write your reply…"
          className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button
            onClick={() => { setBusy(true); onSend(text.trim()) }}
            disabled={busy || text.trim().length === 0}
            className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-green-500 disabled:opacity-40"
          >
            {busy ? 'Sending…' : 'Send reply & resolve'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, className = '' }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-sm font-semibold text-slate-800 ${className}`}>{value}</div>
    </div>
  )
}

function StatusCell({ status, blockingPersona, escalatedByName, escalatedAt }: {
  status?: string | null; blockingPersona?: string | null
  escalatedByName?: string | null; escalatedAt?: string | null
}) {
  // When the loan is escalated, the UW status reflects the pending senior review.
  if (escalatedByName != null || escalatedAt != null) {
    return (
      <div className="px-4 py-3">
        <div className="text-[10px] uppercase tracking-wide text-slate-400">Current UW Status</div>
        <div className="mt-1 flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-500" />
          <span className="text-sm font-bold text-amber-700">Escalated — Awaiting Senior Review</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          {escalatedByName ? `Escalated by ${escalatedByName}` : 'Escalated'}{escalatedAt ? ` · ${new Date(escalatedAt).toLocaleDateString()}` : ''}
        </div>
      </div>
    )
  }
  const s = (status ?? '').toLowerCase()
  let dot = 'bg-blue-500', text = 'text-blue-700'
  if (/suspend|block/.test(s)) { dot = 'bg-red-500'; text = 'text-red-700' }
  else if (/escalat|review/.test(s)) { dot = 'bg-amber-500'; text = 'text-amber-700' }
  else if (/approv/.test(s)) { dot = 'bg-green-500'; text = 'text-green-700' }
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">Current UW Status</div>
      <div className="mt-1 flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        <span className={`text-sm font-bold ${text}`}>{pretty(status) || DASH}</span>
      </div>
      {blockingPersona && <div className="mt-1 text-[11px] text-slate-400">Blocked on {pretty(blockingPersona)}</div>}
    </div>
  )
}

function RecommendedCell({ cond, fallbackAction, blockingPersona }: {
  cond: Cond | null; fallbackAction: string | null; blockingPersona?: string | null
}) {
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">Recommended Action</div>
      {cond ? (
        <>
          <div className="mt-1 text-sm font-bold text-slate-900">{ACTION_LABEL[cond.recommended_action] ?? pretty(cond.recommended_action)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{cond.condition_text}</div>
        </>
      ) : fallbackAction ? (
        // No formal condition yet, but the engine blocked the loan — show the
        // action implied by the blocking decision (keeps this consistent with
        // the "Blocked on …" UW status instead of contradicting it).
        <>
          <div className="mt-1 text-sm font-bold text-slate-900">{ACTION_LABEL[fallbackAction] ?? pretty(fallbackAction)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">
            Blocked on {pretty(blockingPersona)} — no formal condition recorded yet.
          </div>
        </>
      ) : (
        <div className="mt-1 text-sm font-bold text-green-700">No blocking issues</div>
      )}
    </div>
  )
}

function ReadinessCell({ summary }: { summary: Record<string, any> | null }) {
  const total = summary?.total_conditions ?? 0
  const blocking = summary?.blocking_conditions ?? 0
  const cleared = summary?.cleared_conditions ?? 0
  const open = summary?.open_conditions ?? 0
  const needsReview = Math.max(0, open - blocking)
  const notStarted = Math.max(0, total - cleared - open)
  const ringPct = total > 0 ? Math.round((cleared / total) * 100) : 0
  const ring = blocking > 0 ? '#dc2626' : open > 0 ? '#d97706' : '#16a34a'

  // SVG donut — pure, no chart library
  const R = 26, C = 2 * Math.PI * R
  const segs = total > 0
    ? [{ n: blocking, c: '#dc2626' }, { n: needsReview, c: '#d97706' }, { n: cleared, c: '#16a34a' }, { n: notStarted, c: '#e2e8f0' }]
    : [{ n: 1, c: '#e2e8f0' }]
  const denom = segs.reduce((a, s) => a + s.n, 0) || 1
  let offset = 0
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">Decision Readiness</div>
      <div className="mt-1 flex items-center gap-3">
        <svg width="64" height="64" viewBox="0 0 64 64" className="-rotate-90">
          {segs.map((s, i) => {
            const len = (s.n / denom) * C
            const el = <circle key={i} cx="32" cy="32" r={R} fill="none" stroke={s.c} strokeWidth="8" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset} />
            offset += len
            return el
          })}
        </svg>
        <div>
          <div className="text-lg font-bold" style={{ color: ring }}>{ringPct}%</div>
          <div className="text-[10px] text-slate-400">cleared</div>
        </div>
      </div>
      <div className="mt-1 text-[10px] text-slate-500">
        {blocking} Blocking · {needsReview} Needs Review · {cleared} Cleared · {notStarted} Not Started
      </div>
    </div>
  )
}

function AtAGlanceCell({ summary, conditions, lockDays }: { summary: Record<string, any> | null; conditions: Cond[]; lockDays: number | null }) {
  const total = summary?.total_conditions ?? 0
  const cleared = summary?.cleared_conditions ?? 0
  const blocking = summary?.blocking_conditions ?? 0
  const overdue = summary?.overdue_conditions ?? 0
  const anyEscalate = conditions.some((c) => c.recommended_action === 'escalate')
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">At a Glance</div>
      <ul className="mt-1 space-y-0.5 text-[11px] text-slate-600">
        <li>✅ {cleared} of {total} areas complete</li>
        {blocking > 0 && <li>🔴 {blocking} blocking issue{blocking === 1 ? '' : 's'}</li>}
        {overdue > 0 && <li>🟡 {overdue} condition{overdue === 1 ? '' : 's'} overdue</li>}
        {anyEscalate && <li>⚠️ Escalation needed</li>}
        {lockDays != null && lockDays < 7 && <li>🔒 Rate lock expires in {lockDays} day{lockDays === 1 ? '' : 's'}</li>}
      </ul>
    </div>
  )
}

function ReviewStrip({ conditions }: { conditions: Cond[] }) {
  const areas = useMemo(() => {
    const byArea = new Map<string, Cond[]>()
    conditions.forEach((c) => {
      const a = c.review_area || 'Other'
      if (!byArea.has(a)) byArea.set(a, [])
      byArea.get(a)!.push(c)
    })
    const RANK: Record<string, number> = { blocked: 0, needs_review: 1, cleared: 2, not_started: 3 }
    const out = [...byArea.entries()].map(([area, conds]) => {
      let st: keyof typeof RANK = 'not_started'
      if (conds.some((c) => c.blocks_closing === true && ['open', 'submitted', 'in_review'].includes(c.status))) st = 'blocked'
      else if (conds.some((c) => ['submitted', 'in_review'].includes(c.status))) st = 'needs_review'
      else if (conds.length > 0 && conds.every((c) => ['approved', 'waived'].includes(c.status))) st = 'cleared'
      else if (conds.some((c) => c.status === 'open')) st = 'needs_review'
      return { area, st, first: conds[0] }
    })
    out.sort((a, b) => RANK[a.st] - RANK[b.st])
    return out
  }, [conditions])

  if (areas.length === 0) return null
  const TOP: Record<string, string> = {
    blocked: 'border-t-red-500', needs_review: 'border-t-amber-500', cleared: 'border-t-green-500', not_started: 'border-t-slate-300',
  }
  const LABEL: Record<string, string> = { blocked: 'Blocked', needs_review: 'Needs Review', cleared: 'Cleared', not_started: 'Not Started' }
  return (
    <div className="mx-5 mt-4 flex flex-wrap gap-2">
      {areas.map(({ area, st, first }) => (
        <button
          key={area}
          onClick={() => first && document.getElementById(first.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          className={`flex-1 min-w-[110px] rounded-lg border border-t-2 border-slate-200 bg-white px-3 py-2 text-left ${TOP[st]}`}
        >
          <div className="text-xs font-semibold text-slate-800">{area}</div>
          <div className="text-[10px] text-slate-400">{LABEL[st]}</div>
        </button>
      ))}
    </div>
  )
}

function ConditionRow({ c, actions, expanded, onToggle, onAction }: {
  c: Cond; actions: LoanAction[]; expanded: boolean; onToggle: () => void; onAction: (t: string) => void
}) {
  const blocking = isBlocking(c)
  const cleared = isCleared(c)
  const border = blocking ? 'border-l-red-500' : cleared ? 'border-l-green-500' : 'border-l-amber-500'
  const sev = blocking
    ? <Pill cls="bg-red-50 text-red-700">⊘ Blocking</Pill>
    : cleared
      ? <Pill cls="bg-green-50 text-green-700">✓ Cleared</Pill>
      : <Pill cls="bg-amber-50 text-amber-700">⚠ Needs Review</Pill>
  const statusPill = STATUS_PILL[c.status] ?? { label: pretty(c.status), cls: 'bg-slate-100 text-slate-600' }
  const btn = ACTION_BTN[c.recommended_action]
  const dueCls = c.is_overdue ? 'text-red-600' : c.days_until_due != null && c.days_until_due < 3 ? 'text-amber-600' : 'text-slate-500'
  const dueSub = c.is_overdue
    ? `${Math.abs(Math.round(c.days_until_due ?? 0))} days overdue`
    : c.days_until_due != null ? `${Math.round(c.days_until_due)} days left` : ''

  return (
    <>
      <tr id={c.id} className={`border-l-[3px] ${border} border-b border-slate-50 align-top`}>
        <td className="px-3 py-2.5">
          <div className="text-[11px] font-semibold text-slate-800">{c.condition_text}</div>
          <div className="text-[9px] text-slate-400">{c.condition_code}</div>
          <button onClick={onToggle} className="mt-0.5 text-[10px] font-medium text-blue-600 hover:underline">▸ View rules + trace</button>
        </td>
        <td className="px-2 py-2.5"><Pill cls="bg-slate-100 text-slate-600">{pretty(c.category)}</Pill></td>
        <td className="px-2 py-2.5">{sev}</td>
        <td className="px-2 py-2.5"><Pill cls={statusPill.cls}>{statusPill.label}</Pill></td>
        <td className="px-2 py-2.5">
          <div className="flex items-center gap-1.5">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[9px] font-bold text-slate-600">{initials(pretty(c.assignee))}</span>
            <span className="text-[11px] text-slate-600">{pretty(c.assignee)}</span>
          </div>
        </td>
        <td className="px-2 py-2.5">
          <div className={`text-[11px] font-medium ${dueCls}`}>{shortDate(c.due_date)}</div>
          {dueSub && <div className={`text-[9px] ${dueCls}`}>{dueSub}</div>}
        </td>
        <td className="px-2 py-2.5">
          <div className="flex items-center gap-1">
            {btn && (
              <button onClick={() => onAction(c.recommended_action)} className={`rounded-md px-2 py-1 text-[10px] font-semibold ${btn.cls}`}>{btn.label}</button>
            )}
            <button onClick={onToggle} className="rounded-md border border-slate-200 px-1.5 py-1 text-[10px] text-slate-500">···</button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-slate-50">
          <td colSpan={7} className="px-4 py-3">
            <RulePanel c={c} actions={actions} />
          </td>
        </tr>
      )}
    </>
  )
}

function RulePanel({ c, actions }: { c: Cond; actions: LoanAction[] }) {
  const gov = GOV_BADGE[c.governed_by] ?? { label: pretty(c.governed_by), cls: 'bg-slate-100 text-slate-600' }
  // Best-effort trace: the conditions view exposes no decision_id, so match
  // actions whose reasoning references this condition's code.
  const trace = actions.filter((a) => (a.reason_text ?? '').includes(c.condition_code))
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Three-layer rules</div>
        <div className="space-y-1.5">
          <RuleCard badge={gov} title={c.condition_text} citation={c.agency_citation} />
          {c.library_citation && c.library_citation !== c.agency_citation && (
            <RuleCard badge={GOV_BADGE.agency} title="Library template" citation={c.library_citation} />
          )}
        </div>
      </div>
      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Decision trace</div>
        {trace.length === 0 ? (
          <div className="text-[11px] text-slate-400">No actions recorded yet for this condition</div>
        ) : (
          <ul className="space-y-1.5">
            {trace.map((a) => (
              <li key={a.id} className="text-[11px] text-slate-600">
                <span className="text-slate-400">{shortDate(a.performed_at)} · {pretty(a.action_type)} · {a.performed_by}</span>
                <div>{a.reason_text}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function RuleCard({ badge, title, citation }: { badge: { label: string; cls: string }; title?: string | null; citation?: string | null }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5">
      <Pill cls={badge.cls}>{badge.label}</Pill>
      <div className="mt-1 text-[11px] font-medium text-slate-700">{title || DASH}</div>
      {citation && <div className="mt-0.5 text-[10px] text-slate-400">{citation}</div>}
    </div>
  )
}

function ActionPanel({ cond, fallbackAction, blockingPersona, canOverride, canEscalate, showFeedback, showRecommend, recommendedPending, onAction, onDecide, onSendFeedback, onRecommend }: {
  cond: Cond | null; fallbackAction?: string | null; blockingPersona?: string | null
  canOverride: boolean; canEscalate: boolean; showFeedback?: boolean; showRecommend?: boolean; recommendedPending?: boolean
  onAction: (t: string) => void; onDecide: (mode: 'approve' | 'deny' | 'override') => void; onSendFeedback?: () => void; onRecommend?: () => void
}) {
  const rec = cond?.recommended_action ?? fallbackAction ?? null
  const primary = rec ? ACTION_PRIMARY[rec] : null
  // Secondary actions are role-driven. Routing work upward (escalate / senior
  // review) is shown only to roles that can escalate — never to senior_uw / admin,
  // who ARE the escalation target. Override / approve / deny render separately
  // below, gated on canOverride. Request-docs + add-a-note are always available.
  const escalation: Array<[string, string]> = canEscalate
    ? [['escalate', '↑ Escalate'], ['senior_review', '👤 Senior review']]
    : []
  const SECONDARY: Array<[string, string]> = [
    ['request_documents', '📄 Request documents'],
    ...escalation,
    ['add_note', '📝 Add a note'],
  ]
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Recommended</div>
      {cond ? (
        <>
          <div className="mt-0.5 text-sm font-bold text-slate-900">{ACTION_LABEL[rec!] ?? pretty(rec)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{cond.condition_text}</div>
        </>
      ) : rec ? (
        <>
          <div className="mt-0.5 text-sm font-bold text-slate-900">{ACTION_LABEL[rec] ?? pretty(rec)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">Blocked on {pretty(blockingPersona)} — no formal condition recorded yet.</div>
        </>
      ) : (
        <div className="mt-0.5 text-sm font-bold text-green-700">No blocking issues</div>
      )}

      {primary && rec && (
        <button onClick={() => onAction(rec)} className={`mt-3 w-full rounded-lg px-3 py-2 text-xs font-semibold ${primary.cls}`}>{primary.label}</button>
      )}

      {/* Decision authority — only rendered for roles with override_decision.
          Roles that can't decide never see Approve/Deny at all (not grayed). */}
      {canOverride && (
        <div className="mt-3 space-y-1.5">
          <button onClick={() => onDecide('override')} className="w-full rounded-lg bg-[#14532d] px-3 py-1.5 text-left text-xs font-semibold text-white hover:bg-[#0f3d22]">⤺ Override</button>
          <button onClick={() => onDecide('approve')} className="w-full rounded-lg bg-green-600 px-3 py-1.5 text-left text-xs font-semibold text-white hover:bg-green-500">✓ Approve</button>
          <button onClick={() => onDecide('deny')} className="w-full rounded-lg bg-red-600 px-3 py-1.5 text-left text-xs font-semibold text-white hover:bg-red-500">✕ Deny</button>
        </div>
      )}

      {showFeedback && (
        <button onClick={onSendFeedback} className="mt-2 w-full rounded-lg border border-amber-400 bg-amber-50 px-3 py-1.5 text-left text-xs font-semibold text-amber-800 hover:bg-amber-100">📨 Send feedback to UW</button>
      )}
      {showRecommend && (
        <button onClick={onRecommend} className="mt-2 w-full rounded-lg border border-green-500 bg-white px-3 py-1.5 text-left text-xs font-semibold text-green-700 hover:bg-green-50">✅ Recommend approval</button>
      )}
      {recommendedPending && (
        <div className="mt-2 rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-semibold text-green-700">⏳ Pending Senior UW decision</div>
      )}

      <div className="mt-2 space-y-1.5">
        {SECONDARY.map(([t, label]) => (
          <button key={t} onClick={() => onAction(t)} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-700 hover:bg-slate-50">{label}</button>
        ))}
      </div>
    </div>
  )
}

function SimilarFiles({ similar }: { similar: { cases: SimilarCase[] } | null }) {
  const cases = (similar?.cases ?? []).slice(0, 3)
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Similar Files</div>
      {cases.length === 0 ? (
        <div className="mt-2 text-[11px] text-slate-400">No similar files found for this loan profile</div>
      ) : (
        <ul className="mt-2 space-y-2.5">
          {cases.map((cse) => {
            const tag = OUTCOME_TAG[cse.action_type] ?? OUTCOME_TAG[cse.outcome] ?? { label: pretty(cse.action_type), cls: 'bg-slate-100 text-slate-600' }
            return (
              <li key={cse.application_id} className="border-b border-slate-50 pb-2 last:border-0">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] text-slate-500">{cse.application_id.slice(0, 14)}</span>
                  <span className="text-[10px] font-medium text-slate-600">{money(cse.loan_amount)}</span>
                </div>
                <div className="mt-0.5 flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">
                    {cse.fraud_score != null && <>Fraud {cse.fraud_score.toFixed(2)} · </>}{pretty(cse.loan_type)}
                  </span>
                  <Pill cls={tag.cls}>{tag.label}</Pill>
                </div>
                {cse.reason_text && <div className="mt-1 text-[10px] italic text-slate-500">"{cse.reason_text.slice(0, 120)}{cse.reason_text.length > 120 ? '…' : ''}"</div>}
                {cse.resolved_days != null && <div className="mt-0.5 text-[9px] text-slate-400">Resolved in {cse.resolved_days} days</div>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function Skeleton({ appId }: { appId: string }) {
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-[#0c1710] px-5 py-2.5 text-sm text-white/70">Loading {appId}…</div>
      <div className="space-y-3 p-5">
        <div className="h-20 animate-pulse rounded-xl bg-slate-200" />
        <div className="h-24 animate-pulse rounded-xl bg-slate-200" />
        <div className="h-64 animate-pulse rounded-xl bg-slate-200" />
      </div>
    </div>
  )
}
