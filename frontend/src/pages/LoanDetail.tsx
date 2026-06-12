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

// AI outcome → recommendation headline + tone.
const REC: Record<string, { label: string; cls: string; ring: string }> = {
  block: { label: 'DO NOT APPROVE — resolve the block before proceeding', cls: 'text-red-700', ring: 'border-red-200 bg-red-50' },
  escalate: { label: 'ESCALATE — investigate further before deciding', cls: 'text-orange-700', ring: 'border-orange-200 bg-orange-50' },
  recommend: { label: 'REVIEW — needs your judgment before it advances', cls: 'text-amber-700', ring: 'border-amber-200 bg-amber-50' },
  allow: { label: 'APPROVE — all checks passed', cls: 'text-green-700', ring: 'border-green-200 bg-green-50' },
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

  const recKind = primary ? primary.outcome : 'allow'
  const rec = REC[recKind] ?? REC.allow
  const m = loan.metrics
  const gapPct =
    m.income_stated && m.income_verified
      ? Math.round((Math.abs(m.income_stated - m.income_verified) / m.income_stated) * 100)
      : null

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

        {/* 2 — AI recommendation (the key element) */}
        <section className={`rounded-xl border p-5 ${rec.ring}`}>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">🧠 What the AI recommends</div>
          <div className={`text-lg font-bold ${rec.cls}`}>{rec.label}</div>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-700">
            {primary ? primary.explanation : 'All 12 agent checks passed with no blocks or escalations — this loan is ready to advance.'}
          </p>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
            {primary?.confidence != null && (
              <span>Confidence: <span className="font-semibold text-slate-700">{Math.round(primary.confidence * 100)}%</span></span>
            )}
            <span>Based on: <span className="font-semibold text-slate-700">{loan.decisions.length} agent analyses</span></span>
            {primary && <span>Driving check: <span className="font-semibold text-slate-700">{primary.persona_name}</span></span>}
          </div>
        </section>

        {/* 3 — Evidence the AI reviewed */}
        <EvidenceSection loan={loan} gapPct={gapPct} />

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

// ── Evidence: documents on file + key data points ────────────────────
const EXPECTED_DOCS = ['W2', 'Pay stubs', 'IRS Transcript', 'URLA 1003', 'Credit Report', 'Purchase Agreement', 'Employer Verification']

function EvidenceSection({ loan, gapPct }: { loan: LoanDetailT; gapPct: number | null }) {
  const m = loan.metrics
  const present = loan.documents.map((d) => String((d as Record<string, unknown>).document ?? '').toLowerCase())
  const onFile = loan.documents.map((d) => String((d as Record<string, unknown>).document ?? '')).filter(Boolean)
  const missing = EXPECTED_DOCS.filter((e) => !present.some((p) => p.includes(e.toLowerCase().split(' ')[0])))

  const dataPoints: Array<[string, string]> = []
  if (m.income_stated && m.income_verified) {
    dataPoints.push([
      'Income',
      `stated ${moneyK(m.income_stated)} vs verified ${moneyK(m.income_verified)}${gapPct ? ` (${gapPct}% gap)` : ''}`,
    ])
  }
  if (m.credit_score != null) dataPoints.push(['Credit', `${m.credit_score} (${creditBand(m.credit_score)} band)`])
  if (m.ltv != null) dataPoints.push(['LTV', `${pct(m.ltv)}${m.ltv < 80 ? ' (below 80%, no MI needed)' : ''}`])
  if (m.dti != null) dataPoints.push(['DTI', `${pct(m.dti)}${m.dti > 43 ? ' (review band)' : ''}`])
  if (m.interest_rate != null)
    dataPoints.push(['Rate', `${pct(m.interest_rate)}${m.lock_days_remaining != null ? `, lock expires in ${m.lock_days_remaining} days` : ''}`])

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">📄 Evidence the AI reviewed</div>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-semibold text-slate-700">Documents on file</div>
          <ul className="space-y-1 text-sm">
            {onFile.length === 0 && <li className="text-slate-400">No documents indexed for this loan.</li>}
            {onFile.map((d, i) => (
              <li key={i} className="text-slate-700">✅ {d}</li>
            ))}
            {missing.map((d) => (
              <li key={d} className="text-slate-400">❌ {d} — not on file</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-2 text-sm font-semibold text-slate-700">Key data points</div>
          <ul className="space-y-1 text-sm">
            {dataPoints.length === 0 && <li className="text-slate-400">No metrics available.</li>}
            {dataPoints.map(([k, v]) => (
              <li key={k} className="text-slate-700">
                <span className="text-slate-500">{k}:</span> {v}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
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
