import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchLoan } from '../api/client'
import type { LoanDetail as LoanDetailT } from '../types/accord'
import BorrowerCard from '../components/BorrowerCard'
import PersonaAccordion from '../components/PersonaAccordion'
import MirofishDebate from '../components/MirofishDebate'
import ConditionsPanel from '../components/ConditionsPanel'
import ActivityFeed from '../components/ActivityFeed'

function ActionButton({ label, kind = 'ghost', onClick }: {
  label: string
  kind?: 'ghost' | 'danger' | 'brand'
  onClick: () => void
}) {
  const cls =
    kind === 'danger'
      ? 'bg-white text-red-700 border-red-200 hover:bg-red-50'
      : kind === 'brand'
        ? 'bg-brand text-white border-brand hover:bg-brand-dark'
        : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
  return (
    <button onClick={onClick} className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${cls}`}>
      {label}
    </button>
  )
}

export default function LoanDetail() {
  const { appId = '' } = useParams()
  const [loan, setLoan] = useState<LoanDetailT | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

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

  // Demo action — these workflow shortcuts have no dedicated endpoint yet.
  const act = (msg: string) => {
    setNote(msg)
    setTimeout(() => setNote(null), 2500)
  }

  if (loading) return <div className="p-12 text-center text-slate-400">Loading {appId}…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!loan) return null

  const persona = loan.blocking_persona?.replace(/_/g, ' ')

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <Link to="/pipeline" className="text-sm font-medium text-brand hover:underline">
        ← Back to Pipeline
      </Link>

      <div className="mt-4 space-y-5">
        <BorrowerCard loan={loan} />

        {/* Block / halt action bar */}
        {loan.status === 'halted' && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-red-700 px-5 py-4 text-white">
            <span className="text-lg">⛔</span>
            <span className="font-semibold tracking-wide">PIPELINE HALTED — Fraud block</span>
            <div className="ml-auto flex gap-2">
              <button onClick={() => act('Referred to SAR (demo)')} className="rounded-lg bg-white/15 px-3 py-1.5 text-sm font-medium hover:bg-white/25">
                Refer to SAR
              </button>
              <button onClick={() => act('Fraud flag cleared (demo)')} className="rounded-lg bg-white/15 px-3 py-1.5 text-sm font-medium hover:bg-white/25">
                Clear fraud flag
              </button>
            </div>
          </div>
        )}
        {loan.status === 'blocked' && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-5 py-4">
            <span className="font-semibold text-red-800">
              Blocked{persona ? ` at ${persona}` : ''}
            </span>
            <div className="ml-auto flex gap-2">
              <ActionButton label="Request docs" onClick={() => act('Document request sent (demo)')} />
              <ActionButton label="Request override" onClick={() => act('Override requested (demo)')} />
              <ActionButton label="Deny + adverse action" kind="danger" onClick={() => act('Adverse-action notice queued (demo)')} />
            </div>
          </div>
        )}

        {note && (
          <div className="rounded-lg border border-brand/30 bg-brand-light/60 px-4 py-2 text-sm text-brand">
            {note}
          </div>
        )}

        {/* MiroFish debate — the headline interactive feature */}
        <MirofishDebate appId={loan.application_id} />

        {/* Decisions + side rail */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <PersonaAccordion decisions={loan.decisions} />
          </div>
          <div className="space-y-5">
            <ConditionsPanel conditions={loan.conditions} />
            <ActivityFeed activity={loan.activity} />
          </div>
        </div>
      </div>
    </div>
  )
}
