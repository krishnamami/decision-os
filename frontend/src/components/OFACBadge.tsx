import { useState } from 'react'
import type { DecisionDetail } from '../types/accord'

type OFACStatus = 'clear' | 'review' | 'match' | 'pending'

const CONFIG: Record<OFACStatus, { label: string; bg: string; text: string; border: string; icon: string }> = {
  clear: { label: 'OFAC Clear', bg: 'bg-green-50', text: 'text-green-800', border: 'border-green-200', icon: '✓' },
  review: { label: 'OFAC Review', bg: 'bg-amber-50', text: 'text-amber-800', border: 'border-amber-200', icon: '⚠' },
  match: { label: 'OFAC Match', bg: 'bg-red-50', text: 'text-red-800', border: 'border-red-200', icon: '✕' },
  pending: { label: 'OFAC Pending', bg: 'bg-slate-50', text: 'text-slate-600', border: 'border-slate-200', icon: '…' },
}

// Derive status from the fraud_screening decision's "Watchlist match" signal.
// Note: signals is an ARRAY of {key,value,...} (not an object), and the value is
// a "Yes"/"No" string. A fraud BLOCK is usually fraud-score driven, not a
// watchlist hit, so we trust the explicit watchlist signal when present.
export function deriveOFACStatus(decisions: DecisionDetail[]): OFACStatus {
  const fraud = decisions.find((d) => d.decision_id === 'fraud_screening')
  if (!fraud) return 'pending'
  const sig = (fraud.signals ?? []).find((s) => /watchlist/i.test(s.key))
  const v = (typeof sig?.value === 'string' ? sig.value : '').trim().toLowerCase()
  if (v === 'yes' || v === 'true') return 'match'
  if (v === 'no' || v === 'false') return 'clear'
  if (fraud.outcome === 'escalate') return 'review'
  return 'clear'
}

export function OFACBadge({ status, checkedAt, listDate }: { status: OFACStatus; checkedAt?: string; listDate?: string }) {
  const [open, setOpen] = useState(false)
  const cfg = CONFIG[status]
  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cfg.bg} ${cfg.text} ${cfg.border}`}
      >
        <span>{cfg.icon}</span>
        {cfg.label}
      </button>
      {open && (
        <div className="absolute left-0 top-8 z-50 w-72 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-lg">
          <button onClick={() => setOpen(false)} className="absolute right-3 top-3 text-slate-400 hover:text-slate-600">✕</button>
          <p className="mb-2 font-semibold text-slate-800">OFAC &amp; Watchlist Screening</p>
          <div className="space-y-1.5 text-slate-600">
            <div className="flex justify-between">
              <span>Lists checked</span>
              <span className="font-medium text-slate-800">SDN / Consolidated Sanctions</span>
            </div>
            {checkedAt && (
              <div className="flex justify-between">
                <span>Checked</span>
                <span className="font-medium text-slate-800">
                  {new Date(checkedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                </span>
              </div>
            )}
            {listDate && (
              <div className="flex justify-between">
                <span>List date</span>
                <span className="font-medium text-slate-800">{listDate}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span>Refresh schedule</span>
              <span className="font-medium text-slate-800">Daily at 02:00 UTC</span>
            </div>
          </div>
          <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-400">
            31 CFR §1010.520 — BSA/OFAC screening requirements
          </p>
        </div>
      )}
    </div>
  )
}
