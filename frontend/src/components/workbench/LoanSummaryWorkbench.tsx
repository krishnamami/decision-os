import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import {
  fetchLoan, fetchConditions, fetchConditionsSummary,
  fetchSimilarCases, fetchLoanActions,
  type LoanAction, type SimilarCase,
} from '../../api/client'
import type { LoanDetail } from '../../types/accord'
import ActionModal from './ActionModal'

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

function Pill({ cls, children }: { cls: string; children: ReactNode }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>
}

export default function LoanSummaryWorkbench({ applicationId }: { applicationId: string }) {
  const navigate = useNavigate()
  const { effectiveUser } = useAuth()
  const role = effectiveUser?.role ?? 'viewer'

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
  const [toast, setToast] = useState<string | null>(null)

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
  const aiDecision = useMemo(() => (loan?.decisions ?? []).find((d) => d.explanation), [loan])
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
          {loanType && <><span className="text-white/30">·</span><span>{pretty(loanType)}</span></>}
        </div>
        <div className="flex items-center gap-2">
          <div className="mr-1 flex items-center gap-2 text-xs text-white/70">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-700 text-[10px] font-bold text-white">{initials(effectiveUser?.name)}</span>
            <span>{effectiveUser?.name ?? 'You'}</span>
          </div>
          <NavBtn onClick={() => setModalAction('add_note')}>Add note</NavBtn>
          <NavBtn onClick={() => setModalAction('request_documents')}>Request docs</NavBtn>
          <NavBtn onClick={() => setModalAction('escalate')}>Escalate</NavBtn>
          <button
            onClick={() => navigate(`/loans/${encodeURIComponent(applicationId)}?view=full`)}
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
          <Field label="Loan Purpose" value={DASH} />
          <Field label="Loan Amount" value={money(loan.metrics?.loan_amount)} />
          <Field label="LTV / CLTV" value={pct(loan.metrics?.ltv)} className={loan.metrics?.ltv != null && loan.metrics.ltv > 80 ? 'text-amber-600' : ''} />
          <Field label="DTI" value={pct(loan.metrics?.dti)} />
          <Field label="FICO" value={loan.metrics?.credit_score ?? DASH} />
          <Field label="Loan Program" value={loanType ? pretty(loanType) : DASH} />
          <Field label="AUS Result" value={DASH} />
          <Field
            label="Rate Lock Expires"
            value={lockDays == null ? DASH : `${lockDays} days`}
            className={lockDays != null && lockDays < 3 ? 'text-red-600' : lockDays != null && lockDays < 7 ? 'text-amber-600' : ''}
          />
          <Field label="Assigned To" value={DASH} />
        </div>
      </div>

      {/* ── SECTION 3 — STATUS ROW ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 divide-y divide-slate-200 border-b border-slate-200 bg-white md:grid-cols-4 md:divide-x md:divide-y-0">
        <StatusCell status={loan.status} blockingPersona={loan.blocking_persona} />
        <RecommendedCell cond={firstBlocking} />
        <ReadinessCell summary={summary} />
        <AtAGlanceCell summary={summary} conditions={conditions} lockDays={lockDays} />
      </div>

      {/* ── SECTION 4 — REVIEW AREA STRIP ───────────────────────────────── */}
      <ReviewStrip conditions={conditions} />

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
                      onAction={(t) => setModalAction(t)}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* RIGHT — sticky panel */}
        <div className="w-full lg:w-64">
          <div className="space-y-4 lg:sticky lg:top-4">
            <ActionPanel
              cond={firstBlocking}
              blockingCount={summary?.blocking_conditions ?? 0}
              role={role}
              onAction={(t) => setModalAction(t)}
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
          onClose={() => setModalAction(null)}
          onDone={onActionDone}
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

function Field({ label, value, className = '' }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-sm font-semibold text-slate-800 ${className}`}>{value}</div>
    </div>
  )
}

function StatusCell({ status, blockingPersona }: { status?: string | null; blockingPersona?: string | null }) {
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

function RecommendedCell({ cond }: { cond: Cond | null }) {
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">Recommended Action</div>
      {cond ? (
        <>
          <div className="mt-1 text-sm font-bold text-slate-900">{ACTION_LABEL[cond.recommended_action] ?? pretty(cond.recommended_action)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{cond.condition_text}</div>
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

function ActionPanel({ cond, blockingCount, role, onAction }: {
  cond: Cond | null; blockingCount: number; role: string; onAction: (t: string) => void
}) {
  const rec = cond?.recommended_action
  const primary = rec ? ACTION_PRIMARY[rec] : null
  const SECONDARY: Array<[string, string]> = [
    ['request_documents', '📄 Request documents'],
    ['escalate', '↑ Escalate'],
    ['senior_review', '👤 Senior review'],
    ['add_note', '📝 Add a note'],
  ]
  const approveDisabled = blockingCount > 0
  const denyDisabled = role === 'underwriter' || role === 'viewer'
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Recommended</div>
      {cond ? (
        <>
          <div className="mt-0.5 text-sm font-bold text-slate-900">{ACTION_LABEL[rec!] ?? pretty(rec)}</div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{cond.condition_text}</div>
        </>
      ) : (
        <div className="mt-0.5 text-sm font-bold text-green-700">No blocking issues</div>
      )}

      {primary && (
        <button onClick={() => onAction(rec!)} className={`mt-3 w-full rounded-lg px-3 py-2 text-xs font-semibold ${primary.cls}`}>{primary.label}</button>
      )}

      <div className="mt-2 space-y-1.5">
        {SECONDARY.map(([t, label]) => (
          <button key={t} onClick={() => onAction(t)} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-700 hover:bg-slate-50">{label}</button>
        ))}
      </div>

      <div className="mt-2 space-y-1.5">
        <button disabled={approveDisabled} title={approveDisabled ? 'Resolve blocking conditions first' : undefined}
          className="w-full cursor-not-allowed rounded-lg border border-slate-100 bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-300">
          Approve{approveDisabled ? ' — resolve block first' : ''}
        </button>
        <button disabled={denyDisabled} title={denyDisabled ? 'Requires senior underwriter' : undefined}
          className="w-full cursor-not-allowed rounded-lg border border-slate-100 bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-300">
          Deny — requires senior underwriter
        </button>
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
                    {cse.fraud_score != null && <>Fraud {cse.fraud_score} · </>}{pretty(cse.loan_type)}
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
