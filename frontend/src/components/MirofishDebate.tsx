import { useState } from 'react'
import { runDebate } from '../api/client'
import type { DebateResult, DebateRound } from '../types/accord'
import { outcomeMeta } from './DecisionPill'

const POSITION_ORDER = ['allow', 'recommend', 'escalate', 'block']
const ROUND_TITLE: Record<number, string> = {
  1: 'Round 1 · Independent Analysis',
  2: 'Round 2 · Cross-Agent Response',
  3: 'Round 3 · Final Consensus',
}

function VoteBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  return (
    <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
      {POSITION_ORDER.map((p) =>
        counts[p] ? (
          <div
            key={p}
            className={outcomeMeta(p).dot}
            style={{ width: `${(counts[p] / total) * 100}%` }}
            title={`${counts[p]} ${p}`}
          />
        ) : null,
      )}
    </div>
  )
}

function RoundView({ round }: { round: DebateRound }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
        {ROUND_TITLE[round.round_number] ?? `Round ${round.round_number}`}
      </div>
      <ul className="space-y-2">
        {round.positions.map((p) => {
          const m = outcomeMeta(p.position)
          const changed = !!p.changed_from
          return (
            <li key={p.agent_id} className="flex items-start gap-2 text-sm">
              <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${m.pill}`}>
                {m.icon}
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-800">{p.agent_name}</span>
                  {changed && (
                    <span className="text-amber-600" title={`Changed from ${p.changed_from}`}>
                      ⚡ {p.changed_from} → {p.position}
                    </span>
                  )}
                  <span className="text-xs text-slate-400">({p.confidence.toFixed(2)})</span>
                </div>
                <div className="text-xs leading-snug text-slate-500">{p.reasoning}</div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default function MirofishDebate({ appId }: { appId: string }) {
  const [result, setResult] = useState<DebateResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showFull, setShowFull] = useState(false)

  async function run() {
    setLoading(true)
    setError(null)
    setShowFull(false)
    try {
      setResult(await runDebate(appId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Debate failed')
    } finally {
      setLoading(false)
    }
  }

  const total = result
    ? Object.values(result.consensus_count).reduce((a, b) => a + b, 0)
    : 0
  const consensusN = result ? result.consensus_count[result.final_consensus] ?? 0 : 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-900">🐟 MiroFish Debate</div>
          <div className="text-xs text-slate-500">12 agents argue this loan across 3 rounds.</div>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : result ? 'Re-run' : 'Run MiroFish Debate'}
        </button>
      </div>

      {loading && (
        <div className="mt-4 flex items-center gap-3 rounded-lg bg-brand-light/60 px-4 py-3 text-sm text-brand">
          <span className="h-2 w-2 animate-pulse rounded-full bg-brand" />
          MiroFish is analyzing this loan… 12 agents evaluating…
        </div>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {result && !loading && (
        <div className="mt-4 space-y-4">
          {/* Consensus card */}
          <div className="rounded-lg border border-slate-200 p-4">
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`rounded-full px-3 py-1 text-sm font-bold uppercase ${outcomeMeta(result.final_consensus).pill}`}
              >
                {result.final_consensus}
              </span>
              <span className="text-sm font-medium text-slate-500">
                {consensusN}/{total} agents
              </span>
            </div>
            <VoteBar counts={result.consensus_count} total={total} />
            <div className="mt-2 flex flex-wrap gap-x-3 text-xs text-slate-500">
              {POSITION_ORDER.filter((p) => result.consensus_count[p]).map((p) => (
                <span key={p} className="flex items-center gap-1">
                  <span className={`h-2 w-2 rounded-full ${outcomeMeta(p).dot}`} />
                  {result.consensus_count[p]} {p}
                </span>
              ))}
            </div>
          </div>

          {/* Recommendation */}
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Recommendation
            </div>
            <p className="text-sm leading-relaxed text-slate-700">{result.recommendation}</p>
          </div>

          {/* Emergent insights */}
          {result.emergent_insights.length > 0 && (
            <div className="rounded-lg bg-amber-50 p-4">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700">
                What you might have missed
              </div>
              <ul className="list-disc space-y-1 pl-5 text-sm text-amber-900">
                {result.emergent_insights.map((ins, i) => (
                  <li key={i}>{ins}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Full transcript */}
          <div>
            <button
              onClick={() => setShowFull((v) => !v)}
              className="text-sm font-medium text-brand hover:underline"
            >
              {showFull ? 'Hide full debate' : 'View full debate'} ({result.rounds.length} rounds)
            </button>
            {showFull && (
              <div className="mt-3 space-y-4 border-l-2 border-slate-100 pl-4">
                {result.rounds.map((r) => (
                  <RoundView key={r.round_number} round={r} />
                ))}
              </div>
            )}
          </div>

          <div className="text-[11px] text-slate-400">
            debate {result.debate_id.slice(0, 8)} · {result.total_duration_seconds}s
          </div>
        </div>
      )}
    </div>
  )
}
