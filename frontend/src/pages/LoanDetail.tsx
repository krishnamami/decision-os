import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ExportMenu from '../components/ExportMenu'
import { downloadCsv, downloadJson, printPdf } from '../utils/export'
import { decideLoan, fetchLoan } from '../api/client'
import { useAuth } from '../context/AuthContext'
import type { DecisionDetail, LoanDetail as LoanDetailT } from '../types/accord'
import PersonaAccordion from '../components/PersonaAccordion'
import MirofishDebate from '../components/MirofishDebate'
import ConditionsPanel from '../components/ConditionsPanel'
import ActivityFeed from '../components/ActivityFeed'
import RequestInfoModal from '../components/RequestInfoModal'
import AttentionModal from '../components/AttentionModal'
import NotesSection from '../components/NotesSection'

function moneyK(v: number | null | undefined) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${Math.round(v / 1e3)}K`
  return `$${v}`
}
const pct = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}%`)
const creditBand = (s: number | null | undefined) =>
  s == null ? '' : s >= 760 ? 'super-prime' : s >= 700 ? 'prime' : s >= 640 ? 'near-prime' : 'sub-prime'

// Friendly check name per persona (drives the summary + grouped evidence).
const FRIENDLY: Record<string, string> = {
  credit_assessment: 'Credit', fraud_screening: 'Identity', compliance_check: 'Compliance',
  employment_reconciliation: 'Employment', income_verification: 'Income', ltv_assessment: 'Collateral',
  dti_calculation: 'DTI', product_eligibility: 'Product', rate_pricing: 'Rate',
  underwriting_decision: 'Underwriting', approval_routing: 'Routing', closing_readiness: 'Closing',
}
const BLOCK_OUTCOMES = ['block', 'escalate']
const TONE: Record<'red' | 'amber' | 'green', { ring: string; cls: string; bar: string }> = {
  red: { ring: 'border-red-200 bg-red-50', cls: 'text-red-700', bar: 'border-l-red-500' },
  amber: { ring: 'border-amber-200 bg-amber-50', cls: 'text-amber-700', bar: 'border-l-amber-500' },
  green: { ring: 'border-green-200 bg-green-50', cls: 'text-green-700', bar: 'border-l-green-500' },
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const sigVal = (d: DecisionDetail, key: string) => d.signals.find((s) => s.key === key)?.value ?? ''
const simplify = (e: string) =>
  e.replace(/^(Blocked|Escalated for senior review|Declined|Recommended[^—]*)\s*—\s*driven by\s*/i, '').replace(/\.$/, '') + '.'

function checkValue(did: string, m: LoanDetailT['metrics']): string {
  switch (did) {
    case 'credit_assessment': return m.credit_score != null ? `${m.credit_score} (${creditBand(m.credit_score)} band)` : 'passed'
    case 'income_verification': return m.income_verified ? `${moneyK(m.income_verified)} verified` : 'verified'
    case 'ltv_assessment': return m.ltv != null ? `${pct(m.ltv)}${m.ltv < 80 ? ' (no MI)' : ''}` : 'passed'
    case 'dti_calculation': return m.dti ? pct(m.dti) : 'within limits'
    case 'rate_pricing': return m.interest_rate != null ? `${pct(m.interest_rate)} in band` : 'in band'
    case 'compliance_check': return 'complete'
    case 'employment_reconciliation': return 'verified'
    case 'fraud_screening': return 'clear'
    case 'product_eligibility': return 'eligible'
    case 'closing_readiness': return 'ready'
    default: return 'passed'
  }
}

interface Narr {
  tone: 'red' | 'amber' | 'green'
  blocked: DecisionDetail[]
  passed: DecisionDetail[]
  headline: string
  convo: string
  summary: { story: string; issue: string; elseLine: string; nextStep: string }
}

// Build the whole narrative (summary + conversational rec + grouping) from the
// decisions the API already returns. Handles N blocking issues, not just one.
function buildNarrative(loan: LoanDetailT): Narr {
  const m = loan.metrics
  const name = loan.borrower.name.split(/\s+/)[0]
  const ds = loan.decisions
  const blocked = ds.filter((d) => BLOCK_OUTCOMES.includes(d.outcome)).sort((a, b) => a.wave - b.wave)
  const passed = ds.filter((d) => !BLOCK_OUTCOMES.includes(d.outcome))
  const hasBlock = ds.some((d) => d.outcome === 'block')
  const tone: Narr['tone'] = hasBlock ? 'red' : blocked.length ? 'amber' : 'green'
  const primary = blocked[0] ?? null
  const gap = m.income_stated && m.income_verified
    ? Math.round((Math.abs(m.income_stated - m.income_verified) / m.income_stated) * 100) : null
  const has = (id: string) => passed.some((d) => d.decision_id === id)

  const goods: string[] = []
  if (has('credit_assessment') && m.credit_score) goods.push(`credit (${m.credit_score})`)
  if (has('income_verification') && m.income_verified) goods.push(`income (${moneyK(m.income_verified)})`)
  if (has('ltv_assessment') && m.ltv != null) goods.push(`property (${pct(m.ltv)} LTV)`)

  let story = `${name} wants a ${moneyK(m.loan_amount)} loan.`
  if (goods.length) story += ` Their ${goods.join(', ')} all look fine.`

  const elseLine = `${passed.length} of ${ds.length} checks pass${goods.length ? ` (${goods.map((g) => g.split(' (')[0]).join(', ')}…)` : ''}`
  let headline: string, issue: string, nextStep: string, convo: string

  if (!primary) {
    headline = 'APPROVE — every check passed'
    issue = 'None — every AI check passed'
    nextStep = 'Approve and advance to the next stage'
    convo = `This is a clean file. All ${ds.length} AI checks passed — credit ${m.credit_score ?? '—'}, income verified${gap != null ? ` within ${gap}%` : ''}, LTV ${pct(m.ltv)} with good equity. Ready to advance to the next stage.`
    story += ' Every AI check passed.'
  } else {
    const did = primary.decision_id
    const f = FRIENDLY[did] ?? primary.persona_name
    headline = hasBlock ? 'DO NOT APPROVE — resolve the block before proceeding' : 'REVIEW — needs your judgment before it advances'
    if (blocked.length > 1) story += ` However, ${blocked.length} checks need attention — ${blocked.map((b) => FRIENDLY[b.decision_id] ?? b.persona_name).join(', ')}.`
    else story += ` However, ${simplify(primary.explanation).charAt(0).toLowerCase()}${simplify(primary.explanation).slice(1)}`

    if (did === 'fraud_screening') {
      const fs = sigVal(primary, 'Fraud score'); const wl = sigVal(primary, 'Watchlist match')
      issue = 'Possible identity fraud (watchlist + identity risk)'
      nextStep = 'Refer to the BSA officer for SAR review before proceeding'
      convo = `${name}'s identity raised red flags${fs ? ` — a fraud score of ${fs}` : ''}${wl === 'Yes' ? ' and a federal watchlist match' : ''}, with identity confidence and document authenticity both well below our bar. This is a mandatory BSA referral before anything else moves on this file. The good news: the rest of the loan looks clean — if the identity issue clears, this is a straightforward deal.`
    } else if (did === 'income_verification' || did === 'employment_reconciliation') {
      const restruct = m.loan_amount && m.income_stated && m.income_verified
        ? Math.round((m.loan_amount * m.income_verified) / m.income_stated / 1000) * 1000 : null
      issue = "Income / employment can't be fully verified"
      nextStep = 'Request a current pay stub + employer VOE, or restructure the loan'
      convo = `There's a gap between what ${name} states${m.income_stated ? ` (${moneyK(m.income_stated)}/yr)` : ''} and what the documents verify${m.income_verified ? ` (${moneyK(m.income_verified)}/yr)` : ''}${gap != null ? ` — about a ${gap}% difference` : ''}. Two options: ask for a current pay stub showing higher income (maybe a recent raise), or restructure to qualify at the verified figure${restruct ? ` (~${moneyK(restruct)} max)` : ''}.`
    } else if (did === 'compliance_check') {
      issue = 'Compliance / disclosure timing issue'
      nextStep = 'Re-issue disclosures and confirm TRID timing'
      convo = `Compliance flagged this file. We can't proceed until disclosures are re-issued and TRID timing checks out. The rest of the loan otherwise looks clean.`
    } else if (did === 'ltv_assessment') {
      issue = 'Collateral / LTV above guideline'
      nextStep = 'Order a review appraisal or increase the down payment'
      convo = `The collateral doesn't support the loan as structured. Either order a review appraisal or have the borrower bring more money in. The rest of the file is otherwise clean.`
    } else {
      issue = `${f} — ${primary.outcome === 'block' ? 'blocked' : 'needs senior review'}`
      nextStep = 'Review the flagged decision and clear it or request more information'
      convo = `${simplify(primary.explanation)} ${passed.length} of ${ds.length} checks passed — if this clears, it's a straightforward deal.`
    }
    if (blocked.length > 1) convo += ` Heads up: ${blocked.length} checks need attention here — ${blocked.map((b) => FRIENDLY[b.decision_id] ?? b.persona_name).join(', ')}.`
  }
  return { tone, blocked, passed, headline, convo, summary: { story, issue, elseLine, nextStep } }
}

export default function LoanDetail() {
  const { appId = '' } = useParams()
  const navigate = useNavigate()
  const { effectiveUser } = useAuth()
  // Viewers + compliance are read-only on decisions.
  const canAct = !['viewer', 'compliance'].includes(effectiveUser?.role ?? 'viewer')
  const [loan, setLoan] = useState<LoanDetailT | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [modal, setModal] = useState<'request_info' | 'internal' | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetchLoan(appId)
      .then((d) => alive && setLoan(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Failed to load loan'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [appId])

  // The decision that drives the AI's recommendation: the active block, else the
  // lowest-wave open escalate/recommend, else "all clear".
  const primary = useMemo<DecisionDetail | null>(() => {
    if (!loan) return null
    const byWave = [...loan.decisions].sort((a, b) => a.wave - b.wave)
    return (
      byWave.find((d) => d.outcome === 'block') ||
      byWave.find((d) => (d.outcome === 'escalate' || d.outcome === 'recommend') && !d.reviewed) ||
      null
    )
  }, [loan])

  if (loading) return <div className="p-12 text-center text-slate-400">Loading {appId}…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!loan) return null

  function fire(msg: string) {
    setToast(msg)
    setTimeout(() => {
      setToast(null)
      navigate('/pipeline') // back to My Queue
    }, 1400)
  }
  async function decide(action: 'approve' | 'deny' | 'escalate', note: string) {
    try {
      const r = await decideLoan(loan!.application_id, action, note)
      fire(`✓ ${r.title}`)
    } catch {
      fire('Could not complete the action')
    }
  }

  const m = loan.metrics
  const narr = buildNarrative(loan)
  const tone = TONE[narr.tone]

  const exportItems = [
    { label: 'Export as JSON', run: () => downloadJson(loan, `accord_loan_${loan.application_id}`) },
    {
      label: 'Export as CSV',
      run: () =>
        downloadCsv(
          ['Persona', 'Wave', 'Outcome', 'Confidence', 'Explanation'],
          loan.decisions.map((d) => [d.persona_name, d.wave, d.outcome, d.confidence ?? '', d.explanation]),
          `accord_loan_${loan.application_id}`,
        ),
    },
    { label: 'Export as PDF', run: printPdf },
  ]

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <div className="flex items-center justify-between">
        <Link to="/pipeline" className="text-sm font-medium text-brand hover:underline">← Back to queue</Link>
        <ExportMenu label="📄 Export this loan" items={exportItems} />
      </div>

      <div className="mt-4 space-y-5">
        {/* 1 — Borrower story */}
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h1 className="text-[22px] font-semibold text-slate-900">
            {loan.borrower.name}
            {loan.borrower.age ? <span className="text-slate-400"> · {loan.borrower.age}</span> : null}
            {loan.borrower.employer ? <span className="text-slate-400"> · {loan.borrower.employer}</span> : null}
          </h1>
          <p className="text-sm text-slate-500">
            {moneyK(m.loan_amount)} · {loan.application_id}
          </p>
          {loan.borrower.story && <p className="mt-3 text-[15px] leading-relaxed text-slate-700">{loan.borrower.story}</p>}
        </section>

        {/* 2 — Summary (leads with the full story) */}
        <section className={`rounded-xl border border-slate-200 bg-white p-5 border-l-4 ${tone.bar}`}>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">📋 Summary</div>
          <p className="text-[15px] leading-relaxed text-slate-700">{narr.summary.story}</p>
          <div className="mt-3 space-y-1 text-sm">
            <div><span className="font-semibold text-red-700">⚠ The issue:</span> {narr.summary.issue}</div>
            <div><span className="font-semibold text-green-700">✅ Everything else:</span> {narr.summary.elseLine}</div>
            <div><span className="font-semibold text-slate-700">👉 Next step:</span> {narr.summary.nextStep}</div>
          </div>
        </section>

        {/* 3 — AI recommendation, conversational */}
        <section className={`rounded-xl border p-5 ${tone.ring}`}>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">🧠 What the AI recommends</div>
          <div className={`text-lg font-bold ${tone.cls}`}>{narr.headline}</div>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-700">{narr.convo}</p>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
            <span>Based on: <span className="font-semibold text-slate-700">{loan.decisions.length} agent analyses</span></span>
            {primary && <span>Driving check: <span className="font-semibold text-slate-700">{primary.persona_name}</span></span>}
          </div>
        </section>

        {/* 4 — Evidence, grouped by issue */}
        <GroupedEvidence loan={loan} narr={narr} />

        {/* 4 — Your decision */}
        {canAct ? (
          <YourDecision onAct={fire} onOpenModal={setModal} onDecide={decide} />
        ) : (
          <section className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
            <span className="font-medium text-slate-700">View only</span> — your role has read-only access. You can review
            the AI’s recommendation and evidence but cannot take action on this loan.
          </section>
        )}

        {toast && (
          <div className="fixed bottom-6 left-1/2 z-20 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
            {toast}
          </div>
        )}

        {modal === 'request_info' && (
          <RequestInfoModal
            appId={loan.application_id}
            defaultEmail={`${loan.borrower.name.toLowerCase().split(/\s+/).slice(0, 2).join('.').replace(/[^a-z.]/g, '')}@email.com`}
            onClose={() => setModal(null)}
            onSent={() => { setModal(null); fire('✓ Request sent. Loan moved to Pending.') }}
          />
        )}
        {modal === 'internal' && (
          <AttentionModal
            appId={loan.application_id}
            onClose={() => setModal(null)}
            onSent={() => { setModal(null); fire('✓ Internal review requested.') }}
          />
        )}

        {/* MiroFish debate */}
        <div id="mirofish-debate">
          <MirofishDebate appId={loan.application_id} />
        </div>

        {/* 5 — AI evaluation details (the reframed persona accordion) */}
        <section>
          <h2 className="text-lg font-semibold text-slate-900">AI evaluation details</h2>
          <p className="mb-3 text-sm text-slate-500">Click any stage to see the full analysis the agents ran.</p>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <PersonaAccordion decisions={loan.decisions} />
            </div>
            <div className="space-y-5">
              <NotesSection appId={loan.application_id} />
              <ConditionsPanel conditions={loan.conditions} />
              <ActivityFeed activity={loan.activity} />
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

// ── Evidence grouped by issue: "Why it's blocked" + "Everything else passed" ──
const EXPECTED_DOCS = ['W2', 'Pay stubs', 'IRS Transcript', 'URLA 1003', 'Credit Report', 'Purchase Agreement', 'Employer Verification']

function GroupedEvidence({ loan, narr }: { loan: LoanDetailT; narr: Narr }) {
  const m = loan.metrics
  const [expanded, setExpanded] = useState(narr.passed.length < 5)
  const onFile = loan.documents.map((d) => String((d as Record<string, unknown>).document ?? '')).filter(Boolean)
  const present = onFile.map((s) => s.toLowerCase())
  const missing = EXPECTED_DOCS.filter((e) => !present.some((p) => p.includes(e.toLowerCase().split(' ')[0])))

  return (
    <>
      {narr.blocked.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-5 border-l-4 border-l-red-500">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">⚠ Why it's blocked</div>
          <div className="space-y-4">
            {narr.blocked.map((d) => {
              const fails = d.signals.filter((s) => s.status === 'fail' || s.status === 'warn')
              return (
                <div key={d.decision_id}>
                  <div className="font-semibold text-slate-900">
                    {FRIENDLY[d.decision_id] ?? d.persona_name} —{' '}
                    <span className={d.outcome === 'block' ? 'text-red-700' : 'text-amber-700'}>{cap(d.outcome)}</span>
                    {d.confidence != null ? ` (confidence ${Math.round(d.confidence * 100)}%)` : ''}
                  </div>
                  {fails.length > 0 && (
                    <>
                      <div className="mt-1 text-xs font-medium text-slate-500">The AI flagged this because:</div>
                      <ul className="mt-1 space-y-0.5 text-sm">
                        {fails.map((s, i) => (
                          <li key={i} className="text-slate-700">✕ {s.key}: <span className="font-medium">{s.value}</span></li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p className="mt-2 text-sm italic leading-relaxed text-slate-600">"{d.explanation}"</p>
                </div>
              )
            })}
          </div>
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5 border-l-4 border-l-green-500">
        <button onClick={() => setExpanded((v) => !v)} className="flex w-full items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">✅ Everything else passed</span>
          {narr.passed.length >= 5 && <span className="text-[10px] text-slate-400">{expanded ? '▲ collapse' : `▼ show ${narr.passed.length}`}</span>}
        </button>
        {expanded ? (
          <ul className="mt-2 space-y-1 text-sm">
            {narr.passed.length === 0 && <li className="text-slate-400">No checks passed.</li>}
            {narr.passed.map((d) => (
              <li key={d.decision_id} className="flex items-center gap-2 text-slate-700">
                <span>✅</span>
                <span className="font-medium">{FRIENDLY[d.decision_id] ?? d.persona_name}:</span>
                <span>{checkValue(d.decision_id, m)}</span>
                <span className="ml-auto text-xs font-medium text-green-700">Passed</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-2 text-sm text-slate-600">✅ {narr.passed.length} checks passed — click to expand.</div>
        )}
        <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">
          {onFile.length} document{onFile.length === 1 ? '' : 's'} on file{missing.length ? `. Missing: ${missing.join(', ')}.` : '.'}
        </div>
      </section>
    </>
  )
}

// ── Your decision: 6 actions, AI proposes / user decides ─────────────
type ActionKey = 'approve' | 'request_info' | 'override' | 'internal' | 'escalate' | 'deny'
const ACTIONS: Array<{
  key: ActionKey
  icon: string
  title: string
  blurb: string
  input?: 'note' | 'required'
  inputLabel?: string
  confirm: string
  cls: string
  done: string
}> = [
  { key: 'approve', icon: '✅', title: 'Approve & advance to next stage', blurb: "I've reviewed the AI findings and agree this can move forward.", input: 'note', inputLabel: 'Add a note (optional)', confirm: 'Approve & advance', cls: 'text-green-700', done: 'Approved — advancing to the next stage' },
  { key: 'request_info', icon: '📧', title: 'Request more information', blurb: 'I need more docs from the borrower before I can decide.', input: 'note', inputLabel: 'What do you need? (W2, pay stubs, gift letter…)', confirm: 'Send request', cls: 'text-blue-700', done: 'Information requested from the borrower' },
  { key: 'override', icon: '🔄', title: 'Override AI recommendation', blurb: 'I disagree with the AI — approve or deny despite its recommendation.', input: 'required', inputLabel: 'Written justification (required)', confirm: 'Submit override', cls: 'text-amber-700', done: 'AI recommendation overridden' },
  { key: 'internal', icon: '🔵', title: 'Request internal review', blurb: 'I need another team member to revisit a specific decision.', input: 'required', inputLabel: 'Message to your teammate (required)', confirm: 'Send to teammate', cls: 'text-indigo-700', done: 'Internal review requested' },
  { key: 'escalate', icon: '⬆', title: 'Escalate to Senior UW', blurb: 'This needs a higher authority to decide.', input: 'note', inputLabel: 'Note for the Senior UW (optional)', confirm: 'Escalate', cls: 'text-purple-700', done: 'Escalated to Senior UW queue' },
  { key: 'deny', icon: '❌', title: 'Deny', blurb: 'Deny this loan and trigger an adverse-action notice.', input: 'required', inputLabel: 'Specific denial reason (required)', confirm: 'Deny loan', cls: 'text-red-700', done: 'Loan denied — adverse-action notice queued' },
]

function YourDecision({ onAct, onOpenModal, onDecide }: {
  onAct: (msg: string) => void
  onOpenModal: (k: 'request_info' | 'internal') => void
  onDecide: (action: 'approve' | 'deny' | 'escalate', note: string) => void
}) {
  const [open, setOpen] = useState<ActionKey | null>(null)
  const [text, setText] = useState('')
  const MODAL_ACTIONS: ActionKey[] = ['request_info', 'internal']
  const DECIDE_ACTIONS: ActionKey[] = ['approve', 'deny', 'escalate']

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="mb-3 text-lg font-semibold text-slate-900">What would you like to do?</h2>
      <div className="space-y-2">
        {ACTIONS.map((a) => {
          const isOpen = open === a.key
          const needsText = a.input === 'required'
          return (
            <div key={a.key} className={`rounded-lg border ${isOpen ? 'border-brand ring-1 ring-brand/20' : 'border-slate-200'}`}>
              <button
                onClick={() => {
                  if (MODAL_ACTIONS.includes(a.key)) {
                    onOpenModal(a.key as 'request_info' | 'internal')
                    return
                  }
                  setOpen(isOpen ? null : a.key)
                  setText('')
                }}
                className="flex w-full items-start gap-3 p-3 text-left hover:bg-slate-50"
              >
                <span className="text-lg leading-none">{a.icon}</span>
                <span>
                  <span className={`block font-semibold ${a.cls}`}>{a.title}</span>
                  <span className="block text-sm text-slate-500">{a.blurb}</span>
                </span>
              </button>
              {isOpen && (
                <div className="border-t border-slate-100 px-3 pb-3 pt-2">
                  {a.input && (
                    <>
                      <label className="mb-1 block text-xs font-medium text-slate-500">{a.inputLabel}</label>
                      <textarea
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        rows={2}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
                        placeholder={needsText ? 'Required…' : 'Optional…'}
                      />
                    </>
                  )}
                  <div className="mt-2 flex justify-end">
                    <button
                      disabled={needsText && !text.trim()}
                      onClick={() => {
                        if (DECIDE_ACTIONS.includes(a.key)) onDecide(a.key as 'approve' | 'deny' | 'escalate', text)
                        else onAct(`${a.done} (demo)`)
                      }}
                      className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
                    >
                      {a.confirm}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
