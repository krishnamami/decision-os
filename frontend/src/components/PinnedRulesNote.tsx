import { useEffect, useState } from 'react'
import { fetchLoanRulesNote } from '../api/client'

const fmt = (iso?: string) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—')

// Shows below the loan summary ONLY when the loan was applied under an older
// rule version than the one currently active (application-date pinning policy).
export default function PinnedRulesNote({ applicationId, borrowerName }: { applicationId: string; borrowerName?: string }) {
  const [note, setNote] = useState<Awaited<ReturnType<typeof fetchLoanRulesNote>> | null>(null)

  useEffect(() => {
    fetchLoanRulesNote(applicationId).then((n) => { if (n.show) setNote(n) }).catch(() => undefined)
  }, [applicationId])

  if (!note) return null
  const who = borrowerName?.split(' ')[0] || 'This loan'

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="text-sm font-bold text-slate-900">ℹ️ Rules Note</div>
      <div className="mt-1 text-sm text-slate-700">
        Applied: {fmt(note.application_date)} under rules <b>v{note.applied_version}</b>
        {' · '}Current rules: <b>v{note.current_version}</b> (effective {fmt(note.current_effective)})
      </div>
      <div className="text-sm text-slate-600">Evaluated under: <b>v{note.applied_version}</b> (application-date policy)</div>
      {note.differences && note.differences.length > 0 && (
        <div className="mt-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Key differences</div>
          <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
            {note.differences.map((d) => (
              <li key={d.field}>
                {d.field}: {d.pinned} (v{note.applied_version}) → {d.current} (v{note.current_version})
                {d.field === 'DTI max' && <span className="ml-1 text-xs text-slate-500">— {who} passes v{note.applied_version} ✅, may fail v{note.current_version} ❌</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
