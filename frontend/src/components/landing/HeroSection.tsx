import { BRAND, DEMO } from './brand'
import { Icon } from './Icon'
import { PrimaryButton, GreenGhostButton } from './primitives'

const TRUST: Array<['shield-check' | 'certificate' | 'circle-check', string]> = [
  ['shield-check', 'Enterprise security'],
  ['certificate', 'SOC 2 ready'],
  ['circle-check', 'Compliant by design'],
]

// Right-hand product mockup — built in code (not an image), styled as a
// Mac-style app window showing a fraud-review loan.
function ProductMockup() {
  return (
    <div className="w-full max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      {/* window chrome */}
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3" style={{ backgroundColor: BRAND.offwhite }}>
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#FF5F57' }} />
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#FEBC2E' }} />
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#28C840' }} />
        <span className="ml-3 text-xs font-semibold text-slate-600">Matthew Johnson · $505K · Fraud review</span>
      </div>

      {/* body */}
      <div className="grid grid-cols-2 gap-3 p-3">
        {/* left pane */}
        <div className="space-y-3">
          <div className="rounded-xl border border-slate-200 p-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Briefing</div>
            <p className="mt-1 text-[12px] leading-snug text-slate-700">
              Self-employed, $505K conforming. Credit and collateral clean. Identity fraud score 0.82 — needs attention.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 p-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">What needs attention</div>
            <ul className="mt-1.5 space-y-1 text-[12px] text-slate-700">
              <li>🔴 Identity — fraud 0.82</li>
              <li>🟡 Employment — 365 day gap</li>
              <li>🟡 Income — reconciliation missing</li>
              <li>🟢 5 checks passed</li>
            </ul>
          </div>
        </div>

        {/* right pane */}
        <div className="space-y-3">
          <div className="rounded-xl border border-slate-200 p-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Your call</div>
            <p className="mt-1 text-[12px] leading-snug text-slate-700">
              Fraud score exceeds threshold. BSA referral mandatory above 0.75.
            </p>
            <div className="mt-2 space-y-1.5">
              <div className="rounded-lg px-2.5 py-1.5 text-center text-[11px] font-semibold text-white" style={{ backgroundColor: BRAND.dark }}>
                Refer to BSA/AML
              </div>
              <div className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-center text-[11px] font-medium text-slate-600">
                Request identity documents
              </div>
              <div className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-center text-[11px] font-medium text-slate-600">
                Needs senior review
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 p-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Similar files</div>
            <ul className="mt-1.5 space-y-1.5 text-[11px] text-slate-600">
              <li className="flex items-center justify-between gap-1">
                <span>Fraud 0.79 · Conforming</span>
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-700">BSA referral</span>
              </li>
              <li className="flex items-center justify-between gap-1">
                <span>Fraud 0.84 · Conforming</span>
                <span className="rounded-full bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">Denied</span>
              </li>
              <li className="flex items-center justify-between gap-1">
                <span>Fraud 0.76 · FHA</span>
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-700">More docs</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* audit strip */}
      <div className="px-3 py-2 text-[12px] font-semibold" style={{ backgroundColor: BRAND.light, color: BRAND.dark }}>
        ✓ Audit ready · 7 decisions · 17 documents · 92% · Preview →
      </div>
    </div>
  )
}

export default function HeroSection() {
  return (
    <section className="mx-auto grid max-w-[1200px] items-center gap-12 px-6 pb-12 pt-16 lg:grid-cols-[52fr_48fr]">
      <div>
        <h1 className="text-[44px] font-bold leading-[1.12] tracking-[-0.03em]" style={{ color: BRAND.nearblack }}>
          AI-powered lending decisions with <span style={{ color: BRAND.dark }}>complete audit trail</span>
        </h1>
        <p className="mt-5 max-w-[500px] text-[17px] leading-[1.7] text-slate-600">
          Accord gives underwriters the best tool to review every file the same way, every time. Every decision
          explained. Every judgment documented. Every file exam-ready.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <PrimaryButton href={DEMO}>Request a demo</PrimaryButton>
          <GreenGhostButton href="#video"><span aria-hidden="true">▶</span> See it in action</GreenGhostButton>
        </div>
        <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-[13px] font-medium text-slate-600">
          {TRUST.map(([icon, label]) => (
            <span key={label} className="flex items-center gap-1.5">
              <span style={{ color: BRAND.dark }}><Icon name={icon} size={16} /></span>
              {label}
            </span>
          ))}
        </div>
      </div>
      <div className="flex justify-center lg:justify-end"><ProductMockup /></div>
    </section>
  )
}
