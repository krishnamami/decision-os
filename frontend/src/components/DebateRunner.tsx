import { useEffect, useRef, useState } from 'react'
import { fetchLoan, fetchPipeline, runDebate } from '../api/client'
import type { DebateResult, DebateRound, LoanDetail, PipelineRow } from '../types/accord'
import { outcomeMeta } from './DecisionPill'

const POSITIONS = ['allow', 'recommend', 'escalate', 'block']
const STATUS_LABEL: Record<string, string> = {
  halted: 'Halted', blocked: 'Blocked', in_review: 'In Review',
  clear_to_close: 'Clear to Close', in_progress: 'In Progress',
}
const ROUND_TITLE: Record<number, string> = {
  1: 'Round 1: Independent Analysis',
  2: 'Round 2: Cross-Agent Response',
  3: 'Round 3: Final Consensus',
}
const LOADING_STAGES = [
  '🐟 Round 1: 12 agents evaluating independently…',
  '🐟 Round 2: Agents sharing findings…',
  '🐟 Round 3: Building consensus…',
]
// Plain-English verdict (not the raw outcome word).
const VERDICT_LABEL: Record<string, string> = {
  allow: 'Approve', recommend: 'Send for review', escalate: 'Investigate further', block: 'Decline',
}
const VERDICT_SUB: Record<string, string> = {
  allow: 'The agents agree this loan clears the bar.',
  recommend: 'Strong overall, but at least one agent wants a human to take a look.',
  escalate: 'There are open questions a senior reviewer should resolve before deciding.',
  block: 'The agents found a hard stop that disqualifies this loan as it stands.',
}
const POS_SHORT: Record<string, string> = { allow: 'approve', recommend: 'review', escalate: 'investigate', block: 'decline' }

function VoteBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  return (
    <div className="flex h-4 w-full overflow-hidden rounded-full bg-slate-100">
      {POSITIONS.map((p) =>
        counts[p] ? (
          <div key={p} className={outcomeMeta(p).dot} style={{ width: `${(counts[p] / total) * 100}%` }} title={`${counts[p]} ${p}`} />
        ) : null,
      )}
    </div>
  )
}

function RoundView({ round }: { round: DebateRound }) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-700">{ROUND_TITLE[round.round_number] ?? `Round ${round.round_number}`}</div>
      <ul className="space-y-2">
        {round.positions.map((p) => {
          const m = outcomeMeta(p.position)
          const changed = !!p.changed_from
          return (
            <li key={p.agent_id} className={`rounded-lg px-3 py-2 ${changed ? 'bg-amber-50' : ''}`}>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${m.pill}`}>{m.icon}</span>
                <span className="font-medium text-slate-800">{p.agent_name}</span>
                {changed ? (
                  <span className="font-medium text-amber-700">⚡ {p.changed_from?.toUpperCase()} → {p.position.toUpperCase()}</span>
                ) : (
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${m.pill}`}>{p.position}</span>
                )}
                <span className="text-xs text-slate-400">({p.confidence.toFixed(2)})</span>
              </div>
              <div className="pl-5 text-xs leading-snug text-slate-500">{p.reasoning}</div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default function DebateRunner() {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<PipelineRow[]>([])
  const [showDrop, setShowDrop] = useState(false)
  const [selected, setSelected] = useState<PipelineRow | null>(null)
  const [loan, setLoan] = useState<LoanDetail | null>(null)
  const [running, setRunning] = useState(false)
  const [stage, setStage] = useState(0)
  const [result, setResult] = useState<DebateResult | null>(null)
  const [showFull, setShowFull] = useState(false)
  const [question, setQuestion] = useState('Should this loan be approved?')
  const dropRef = useRef<HTMLDivElement>(null)

  // Debounced search.
  useEffect(() => {
    if (!query) {
      setMatches([])
      return
    }
    const t = setTimeout(async () => {
      try {
        const res = await fetchPipeline({ search: query, limit: 8 })
        setMatches(res.applications)
        setShowDrop(true)
      } catch {
        setMatches([])
      }
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  // Cycle loading messages while running.
  useEffect(() => {
    if (!running) return
    setStage(0)
    const id = setInterval(() => setStage((s) => (s + 1) % LOADING_STAGES.length), 1200)
    return () => clearInterval(id)
  }, [running])

  async function select(row: PipelineRow) {
    setSelected(row)
    setShowDrop(false)
    setQuery('')
    setResult(null)
    setLoan(null)
    try {
      setLoan(await fetchLoan(row.application_id))
    } catch {
      setLoan(null)
    }
  }

  async function run() {
    if (!selected) return
    setRunning(true)
    setResult(null)
    setShowFull(false)
    try {
      setResult(await runDebate(selected.application_id, question.trim() || undefined))
    } finally {
      setRunning(false)
    }
  }

  const total = result ? Object.values(result.consensus_count).reduce((a, b) => a + b, 0) : 0
  const consensusN = result ? result.consensus_count[result.final_consensus] ?? 0 : 0

  return (
    <div className="space-y-5">
      {/* Search */}
      <div ref={dropRef} className="relative max-w-xl">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => matches.length && setShowDrop(true)}
          placeholder="Search by borrower name or application ID…"
          className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm outline-none focus:border-brand"
        />
        {showDrop && matches.length > 0 && (
          <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
            {matches.map((m) => (
              <button
                key={m.application_id}
                onClick={() => select(m)}
                className="flex w-full flex-col gap-0.5 border-b border-slate-50 px-4 py-2.5 text-left last:border-b-0 hover:bg-slate-50"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-800">{m.borrower_name}</span>
                  <span className="font-mono text-xs text-slate-400">{m.application_id}</span>
                </div>
                <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span>
                    {m.loan_amount ? `$${Math.round(m.loan_amount / 1000)}K` : '—'} · Score {m.credit_score ?? '—'} ·{' '}
                    {STATUS_LABEL[m.status] ?? m.status}
                  </span>
                  <span className="truncate capitalize text-slate-400">
                    {[m.loan_type, m.loan_purpose].filter(Boolean).join(' · ')}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Selected loan summary + question */}
      {selected && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="text-lg font-semibold text-slate-900">{selected.borrower_name}</div>
          <div className="text-sm text-slate-500">
            {loan?.borrower.employer || '—'} ·{' '}
            {selected.loan_amount ? `$${Math.round(selected.loan_amount / 1000)}K` : '—'} · Score{' '}
            {selected.credit_score ?? '—'} · LTV {selected.ltv ?? '—'}% ·{' '}
            {STATUS_LABEL[selected.status] ?? selected.status}
          </div>
          {loan && <p className="mt-3 text-sm leading-relaxed text-slate-600">{loan.borrower.story}</p>}

          <div className="mt-4">
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400">
              Question for the agents
            </label>
            <div className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Should this loan be approved?"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
              />
              <button
                onClick={run}
                disabled={running}
                className="shrink-0 rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
              >
                🐟 Run MiroFish Debate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading animation */}
      {running && (
        <div className="flex items-center gap-3 rounded-xl bg-brand-light/60 px-5 py-4 text-sm font-medium text-brand">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-brand" />
          {LOADING_STAGES[stage]}
        </div>
      )}

      {/* Result */}
      {result && !running && (
        <div className="space-y-5">
          {/* A. Plain-English verdict */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`rounded-full px-4 py-1.5 text-base font-bold ${outcomeMeta(result.final_consensus).pill}`}>
                {VERDICT_LABEL[result.final_consensus] ?? result.final_consensus}
              </span>
              <span className="font-medium text-slate-500">{consensusN} of {total} agents agree</span>
            </div>
            <p className="mt-2 text-sm text-slate-600">{VERDICT_SUB[result.final_consensus] ?? ''}</p>
            <div className="mt-3"><VoteBar counts={result.consensus_count} /></div>
            <div className="mt-2 flex flex-wrap gap-x-3 text-xs text-slate-500">
              {POSITIONS.filter((p) => result.consensus_count[p]).map((p) => (
                <span key={p} className="flex items-center gap-1">
                  <span className={`h-2 w-2 rounded-full ${outcomeMeta(p).dot}`} />
                  {result.consensus_count[p]} {POS_SHORT[p] ?? p}
                </span>
              ))}
            </div>
          </div>

          {/* B. What to do next */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">What to do next</div>
            <p className="text-sm leading-relaxed text-slate-800">{result.recommendation}</p>
          </div>

          {/* C. Emergent insights */}
          {result.emergent_insights.length > 0 && (
            <div>
              <div className="mb-2 text-base font-semibold text-slate-900">What you might have missed</div>
              <div className="space-y-2">
                {result.emergent_insights.map((ins, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <span className="text-lg">💡</span>
                    <p className="text-sm text-amber-900">{ins}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* D. Full debate */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <button onClick={() => setShowFull((v) => !v)} className="text-sm font-medium text-brand hover:underline">
              {showFull ? 'Hide full 3-round debate ▲' : 'View full 3-round debate ▼'}
            </button>
            {showFull && (
              <div className="mt-4 space-y-5 border-l-2 border-slate-100 pl-4">
                {result.rounds.map((r) => (
                  <RoundView key={r.round_number} round={r} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
