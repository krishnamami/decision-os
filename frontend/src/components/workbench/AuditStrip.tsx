import type { LoanDetail } from '../../types/accord'

export default function AuditStrip({ loan, docsCount, teamCount }: { loan: LoanDetail; docsCount: number; teamCount: number }) {
  const score = loan.examiner_readiness?.score ?? 0
  const border = score >= 90 ? 'border-green-400' : score >= 70 ? 'border-amber-400' : 'border-red-400'
  const cls = score >= 90 ? 'text-green-700' : score >= 70 ? 'text-amber-700' : 'text-red-700'
  return (
    <div className={`fixed bottom-0 left-0 right-0 z-30 border-t-2 ${border} bg-white px-6 py-2.5 shadow-[0_-4px_12px_rgba(0,0,0,0.05)]`}>
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 text-sm">
        <span className={`font-semibold ${cls}`}>📋 Audit ready: {score}%</span>
        <span className="text-slate-500">{(loan.decisions ?? []).length} decisions · {docsCount} documents · {teamCount} team member{teamCount === 1 ? '' : 's'}</span>
        <button onClick={() => window.open(`/loans/${loan.application_id}/examiner-report`, '_blank')} className="font-medium text-brand hover:underline">Preview examiner package →</button>
      </div>
    </div>
  )
}
