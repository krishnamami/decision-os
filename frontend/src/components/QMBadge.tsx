import { useState } from 'react'

export type QMStatus = 'safe_harbor' | 'rebuttable_presumption' | 'non_qm' | 'pending'
export interface QMTest { test: string; value: string; limit: string; pass: boolean | null }
export interface QMInfo { status: QMStatus; determination: string; citation: string; tests: QMTest[] }

const QM_CONFIG: Record<QMStatus, { label: string; color: string; description: string }> = {
  safe_harbor: {
    label: 'Safe Harbor QM',
    color: 'text-green-700 bg-green-50 border-green-200',
    description: 'Loan meets all QM requirements. Lender has full safe harbor protection.',
  },
  rebuttable_presumption: {
    label: 'Rebuttable Presumption QM',
    color: 'text-amber-700 bg-amber-50 border-amber-200',
    description: 'QM presumption applies but can be rebutted if the borrower shows inability to repay.',
  },
  non_qm: {
    label: 'Non-QM',
    color: 'text-red-700 bg-red-50 border-red-200',
    description: 'Does not meet QM standards. Higher liability — requires additional review.',
  },
  pending: {
    label: 'QM Pending',
    color: 'text-slate-600 bg-slate-50 border-slate-200',
    description: 'QM determination not yet complete (DTI not calculated).',
  },
}

const result = (p: boolean | null) => (p === true ? '✅ Pass' : p === false ? '❌ Fail' : '— n/a')
const resultClass = (p: boolean | null) => (p === true ? 'text-green-700' : p === false ? 'text-red-700' : 'text-slate-400')

export function QMBadge({ qm }: { qm: QMInfo }) {
  const [open, setOpen] = useState(false)
  const cfg = QM_CONFIG[qm.status] ?? QM_CONFIG.pending
  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        title="QM / Ability-to-Repay status"
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cfg.color}`}
      >
        <span>🛡</span>
        {cfg.label}
      </button>
      {open && (
        <div className="absolute left-0 top-8 z-50 w-[23rem] rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-lg">
          <button onClick={() => setOpen(false)} className="absolute right-3 top-3 text-slate-400 hover:text-slate-600">✕</button>
          <p className="font-semibold text-slate-800">Qualified Mortgage determination</p>
          <p className="mt-0.5 text-xs text-slate-500">{cfg.description}</p>

          <table className="mt-3 w-full text-xs">
            <thead>
              <tr className="text-slate-400">
                <th className="pb-1 text-left font-medium">Test</th>
                <th className="pb-1 text-left font-medium">Value</th>
                <th className="pb-1 text-left font-medium">Limit</th>
                <th className="pb-1 text-right font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {qm.tests.map((t, i) => (
                <tr key={i}>
                  <td className="py-1.5 text-slate-600">{t.test}</td>
                  <td className="py-1.5 font-medium text-slate-800">{t.value}</td>
                  <td className="py-1.5 text-slate-500">{t.limit}</td>
                  <td className={`py-1.5 text-right font-medium ${resultClass(t.pass)}`}>{result(t.pass)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2">
            <span className="text-xs text-slate-500">Final determination</span>
            <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cfg.color}`}>{qm.determination}</span>
          </div>
          <p className="mt-2 text-xs text-slate-400">{qm.citation}</p>
        </div>
      )}
    </div>
  )
}
