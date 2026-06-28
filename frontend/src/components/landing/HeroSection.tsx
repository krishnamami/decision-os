import { useEffect, useState } from 'react'
import { BRAND, DEMO } from './brand'
import { Icon } from './Icon'
import { PrimaryButton, GreenGhostButton } from './primitives'

const TRUST: Array<['shield-check' | 'certificate' | 'circle-check', string]> = [
  ['shield-check', 'Enterprise security'],
  ['certificate', 'SOC 2 ready'],
  ['circle-check', 'Compliant by design'],
]

// Staggered reveal that replays on a loop, so the hero card feels alive (the
// old hero animated its findings in one by one — this restores that motion).
const MOCKUP_KEYFRAMES = `
@keyframes heroRise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.hero-rise{animation:heroRise .5s ease both}
`
const CYCLE_MS = 7000

// Right-hand product mockup — built in code (not an image), styled as a
// Mac-style app window showing a fraud-review loan. Reveals progressively.
function ProductMockup() {
  const [cycle, setCycle] = useState(0)
  const [pct, setPct] = useState(0)

  // Replay the whole reveal every few seconds.
  useEffect(() => {
    const id = window.setInterval(() => setCycle((c) => c + 1), CYCLE_MS)
    return () => window.clearInterval(id)
  }, [])

  // Count the audit-ready % up (0 → 92) once the strip has appeared, each cycle.
  useEffect(() => {
    setPct(0)
    let iv: number | undefined
    const start = window.setTimeout(() => {
      let v = 0
      iv = window.setInterval(() => {
        v += 4
        setPct(v >= 92 ? 92 : v)
        if (v >= 92 && iv) window.clearInterval(iv)
      }, 30)
    }, 1500)
    return () => { window.clearTimeout(start); if (iv) window.clearInterval(iv) }
  }, [cycle])

  return (
    <div className="w-full max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      <style>{MOCKUP_KEYFRAMES}</style>
      {/* window chrome */}
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3" style={{ backgroundColor: BRAND.offwhite }}>
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#FF5F57' }} />
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#FEBC2E' }} />
        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#28C840' }} />
        <span className="ml-3 text-xs font-semibold text-slate-600">Daniel Reyes · $418K · Fraud review</span>
      </div>

      {/* body — keyed so the staggered animation restarts each cycle */}
      <div key={cycle} className="grid grid-cols-2 gap-3 p-3">
        {/* left pane */}
        <div className="space-y-3">
          <div className="hero-rise rounded-xl border border-slate-200 p-3" style={{ animationDelay: '0.1s' }}>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Briefing</div>
            <p className="mt-1 text-[12px] leading-snug text-slate-700">
              W2 salaried, $418K conforming purchase. Credit clean, collateral clear. Identity fraud score 0.79 — BSA referral mandatory above 0.75.
            </p>
          </div>
          <div className="hero-rise rounded-xl border border-slate-200 p-3" style={{ animationDelay: '0.3s' }}>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">What needs attention</div>
            <ul className="mt-1.5 space-y-1 text-[12px] text-slate-700">
              <li className="hero-rise" style={{ animationDelay: '0.5s' }}>🔴 Identity — fraud 0.82</li>
              <li className="hero-rise" style={{ animationDelay: '0.65s' }}>🟡 Employment — 365 day gap</li>
              <li className="hero-rise" style={{ animationDelay: '0.8s' }}>🟡 Income — reconciliation missing</li>
              <li className="hero-rise" style={{ animationDelay: '0.95s' }}>🟢 5 checks passed</li>
            </ul>
          </div>
        </div>

        {/* right pane */}
        <div className="space-y-3">
          <div className="hero-rise rounded-xl border border-slate-200 p-3" style={{ animationDelay: '0.3s' }}>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Your call</div>
            <p className="mt-1 text-[12px] leading-snug text-slate-700">
              Fraud score exceeds threshold. BSA referral mandatory above 0.75.
            </p>
            <div className="mt-2 space-y-1.5">
              <div className="hero-rise rounded-lg px-2.5 py-1.5 text-center text-[11px] font-semibold text-white" style={{ backgroundColor: BRAND.dark, animationDelay: '0.6s' }}>
                Refer to BSA/AML
              </div>
              <div className="hero-rise rounded-lg border border-slate-200 px-2.5 py-1.5 text-center text-[11px] font-medium text-slate-600" style={{ animationDelay: '0.75s' }}>
                Request identity documents
              </div>
              <div className="hero-rise rounded-lg border border-slate-200 px-2.5 py-1.5 text-center text-[11px] font-medium text-slate-600" style={{ animationDelay: '0.9s' }}>
                Needs senior review
              </div>
            </div>
          </div>
          <div className="hero-rise rounded-xl border border-slate-200 p-3" style={{ animationDelay: '1s' }}>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Similar files</div>
            <ul className="mt-1.5 space-y-1.5 text-[11px] text-slate-600">
              <li className="hero-rise flex items-center justify-between gap-1" style={{ animationDelay: '1.15s' }}>
                <span>Fraud 0.79 · Conforming</span>
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-700">BSA referral</span>
              </li>
              <li className="hero-rise flex items-center justify-between gap-1" style={{ animationDelay: '1.3s' }}>
                <span>Fraud 0.84 · Conforming</span>
                <span className="rounded-full bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">Denied</span>
              </li>
              <li className="hero-rise flex items-center justify-between gap-1" style={{ animationDelay: '1.45s' }}>
                <span>Fraud 0.76 · FHA</span>
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-700">More docs</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* audit strip — slides in, % counts up */}
      <div key={`strip-${cycle}`} className="hero-rise px-3 py-2 text-[12px] font-semibold" style={{ backgroundColor: BRAND.light, color: BRAND.dark, animationDelay: '1.5s' }}>
        ✓ Audit ready · 7 decisions · 17 documents · {pct}% · Preview →
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
