import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

const DEMO = 'mailto:demo@useaccord.com?subject=Accord%20demo%20request'

// ── Hero: animated loan-evaluation card ──────────────────────────────
const AGENTS = ['Credit', 'Fraud', 'Income', 'Collateral', 'Compliance', 'Employment', 'DTI', 'Pricing']

function EvaluationCard() {
  const PAUSE = 3
  const END = AGENTS.length + PAUSE
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => (t + 1) % (END + 1)), 800)
    return () => clearInterval(id)
  }, [END])

  const revealed = Math.min(tick, AGENTS.length)
  const done = tick >= AGENTS.length
  const status = tick === 0 ? 'New' : done ? 'Decision: Approve' : 'Evaluating…'
  const statusCls = tick === 0 ? 'bg-slate-100 text-slate-600' : done ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
  const confidence = done ? 97 : Math.min(revealed * 11, 88)

  return (
    <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold text-slate-900">David Park</div>
          <div className="text-xs text-slate-400">$400K · Conventional · APP-2026-0042</div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusCls}`}>{status}</span>
      </div>

      <div className="mt-4 space-y-1.5">
        {AGENTS.map((a, i) => {
          const show = i < revealed
          const loading = i === revealed - 1 && !done
          return (
            <div
              key={a}
              className={`flex items-center justify-between rounded-lg border border-slate-100 px-3 py-1.5 text-sm transition-all duration-500 ${
                show ? 'translate-x-0 opacity-100' : 'translate-x-3 opacity-0'
              }`}
            >
              <span className="text-slate-700">{a} Agent</span>
              {loading ? (
                <span className="animate-pulse text-xs text-slate-400">● ● ●</span>
              ) : show ? (
                <span className="text-xs font-semibold text-green-600">✓ Pass</span>
              ) : (
                <span className="text-xs text-transparent">—</span>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-4">
        <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
          <span>AI confidence</span>
          <span className="font-semibold text-slate-700">{confidence}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-brand transition-all duration-700" style={{ width: `${confidence}%` }} />
        </div>
      </div>

      <div className="mt-3 text-center text-xs text-slate-400">{revealed} of 12 agents · 0.8s</div>
    </div>
  )
}

// ── Section data ─────────────────────────────────────────────────────
const STATS = [
  ['80% faster underwriting', 'Reduce cycle times from days to hours'],
  ['60% fewer manual reviews', 'AI agents handle complex analysis'],
  ['100% audit traceability', 'Full decision trail for every loan'],
  ['15 min integration', 'Connect your LOS and go live same day'],
]
const STEPS = [
  ['01', '🔌', 'Connect your loan system', 'Upload a CSV or connect Encompass. Your loan data flows into Accord automatically. Setup takes 15 minutes.'],
  ['02', '🧠', '12 AI agents evaluate every loan', 'Credit, fraud, income, collateral, compliance, employment, DTI, product eligibility, pricing, underwriting, routing, and closing readiness — all checked simultaneously.'],
  ['03', '✅', 'Review findings, make your decision', 'See what the AI found, what data it analyzed, and what it recommends — in plain English. Approve with one click. Every action fully documented.'],
]
const CASES = [
  ['4.2 → 1.7 hours', 'Average review time per loan', 'Across 8,896 loans, AI agents handle initial analysis in under 1 second. Underwriters review AI findings instead of starting from scratch.', 'I used to spend 20 minutes pulling the credit report and comparing numbers. Now the AI does that and tells me what to focus on.'],
  ['5 fraud cases caught', 'that manual review missed', 'The Fraud Agent identified 5 watchlist matches and synthetic identity patterns. The Portfolio Health Check found that 46% of loans had income discrepancies — a systematic intake problem.', 'The health check found a pattern across 4,000 loans that no individual file review would have caught.'],
  ['3 loans, $1.5M impact', 'predicted before policy change', 'Before tightening DTI from 43% to 36%, the Policy Simulator showed exactly which 3 borrowers would be affected, why, and what alternatives existed.', 'We could see the impact of a rule change across our entire book before committing. No other tool does that.'],
]
const PERSONAS = [
  ['Processors & Underwriters', 'Review AI findings, not raw documents', 'See exactly what the AI found, what data it analyzed, and what it recommends. Approve clean files in one click. Request docs with a checklist. Focus on the exceptions, not the routine.'],
  ['Senior Underwriters', 'Make final decisions with full context', '12 agents already evaluated the loan. See the consensus, the dissent, and the evidence. Run a MiroFish debate for complex cases. Override with documented justification.'],
  ['Managers & VPs', "See your team's pipeline and performance", "Who's overloaded? What's aging? Which policies create the most blocks? Run simulations before changing rules. Reassign loans between team members."],
  ['Compliance & Audit', 'Answer any examiner question in seconds', 'Every AI decision, every human action, every override — documented with reasoning. Export the full examiner package. HMDA, fair lending, adverse action — all in one place.'],
]
const PRICING = [
  { name: 'Starter', price: '$15', unit: '/loan', min: '$500/mo min', includes: 'Pipeline', popular: false },
  { name: 'Growth', price: '$35', unit: '/loan', min: '$1,500/mo min', includes: 'Pipeline + Analytics', popular: false },
  { name: 'Business', price: '$60', unit: '/loan', min: '$3,000/mo min', includes: 'Pipeline + Analytics + Simulation', popular: true },
  { name: 'Enterprise', price: 'Custom', unit: '', min: 'Volume pricing', includes: 'All 4 + support + VPC deployment', popular: false },
]
const FAQS = [
  ['How long does setup take?', 'Most lenders are live in under an hour. Upload a CSV of your loans, and 12 AI agents start evaluating immediately. For Encompass integration, setup takes about 15 minutes.'],
  ['Does Accord replace my LOS?', 'No. Accord works alongside your LOS (Encompass, ICE, etc.). Your LOS manages the loan. Accord provides the AI evaluation and audit trail. Think of it as the brain that reads what your LOS stores.'],
  ['How does the AI make decisions?', "It doesn't. AI evaluates and recommends. Humans decide. 12 specialized agents each check one aspect — credit checks credit, fraud checks fraud, income checks income. Each explains what it found, what data it reviewed, and why it recommends what it recommends. You make the final call."],
  ['What if the AI is wrong?', 'You can override any AI recommendation with a written justification. The override is documented in the audit trail. Over time, the system learns from overrides to improve.'],
  ['Is my data secure?', 'Yes. AES-256 encryption at rest and TLS 1.3 in transit. Your data is isolated from other customers. We never share or sell customer data. Our architecture is designed for SOC 2 Type II compliance.'],
  ['Can I run Accord in my own cloud?', 'Enterprise customers can deploy Accord in their own AWS VPC. Your data never leaves your environment. Same product, your infrastructure.'],
]
const PRODUCTS = [
  ['📋 Pipeline', 'See what 12 AI agents found on every loan'],
  ['📊 Analytics', 'Portfolio performance, risk, and intelligence'],
  ['🐟 Simulation', 'Run the future before it happens'],
  ['📑 Audit', 'Full decision trail for every examiner question'],
]
const PLATFORM = [
  ['Decision Engine', 'Boundary rules with confidence scoring'],
  ['AI Agents', '12 agents trained on lending regulations'],
  ['Integrations', 'Encompass, Experian, Fannie DU — 15 min setup'],
  ['Docs & API', 'Get started in under an hour'],
]

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-xs font-bold uppercase tracking-widest text-brand">{children}</div>
}

export default function Landing() {
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  return (
    <div className="min-h-screen scroll-smooth bg-white text-slate-900">
      {/* 1 — Announcement banner */}
      <div
        className="flex items-center justify-center gap-2 px-4 text-sm text-white"
        style={{ height: 36, background: 'linear-gradient(90deg, #0F6E56, #1D9E75, #5DCAA5)' }}
      >
        <span>Introducing AI-powered lending decisions with complete audit trail.</span>
        <a href="#how" className="font-medium underline">See how →</a>
      </div>

      {/* 2 — Marketing nav */}
      <header className="sticky top-0 z-30 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center px-6" style={{ height: 56 }}>
          <a href="#top" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight">accord</span>
          </a>
          <nav className="ml-8 hidden items-center gap-6 text-sm font-medium text-slate-600 md:flex">
            <a href="#products" className="hover:text-slate-900">Products ▾</a>
            <a href="#pricing" className="hover:text-slate-900">Pricing</a>
            <a href="#faq" className="hover:text-slate-900">Docs</a>
            <a href="#who" className="hover:text-slate-900">Company ▾</a>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <Link to="/login" className="text-sm font-medium text-slate-600 hover:text-slate-900">Log in</Link>
            <a href={DEMO} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo</a>
          </div>
        </div>
      </header>

      <main id="top">
        {/* 3 — Hero */}
        <section className="mx-auto grid max-w-7xl items-center gap-12 px-6 py-16 lg:grid-cols-2">
          <div>
            <h1 className="text-4xl font-bold leading-tight tracking-tight text-slate-900 md:text-5xl">
              AI-powered lending decisions with complete audit trail
            </h1>
            <p className="mt-5 text-lg leading-relaxed text-slate-600">
              12 specialized AI agents evaluate every loan — credit, fraud, income, collateral, compliance, and more.
              Decisions in hours, not days. Every step documented for examiners.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-500">
              <span>🔒 Enterprise security</span>
              <span>🏛️ SOC 2 ready</span>
              <span>⚖️ Compliant by design</span>
            </div>
            <div className="mt-7 grid grid-cols-2 gap-3">
              {STATS.map(([h, d]) => (
                <div key={h} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="font-semibold text-slate-900">{h}</div>
                  <div className="text-xs text-slate-500">{d}</div>
                </div>
              ))}
            </div>
            <div className="mt-7 flex flex-wrap gap-3">
              <a href={DEMO} className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo →</a>
              <a href="#how" className="rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">See it in action ▷</a>
            </div>
          </div>
          <div className="flex justify-center lg:justify-end">
            <EvaluationCard />
          </div>
        </section>

        {/* 4 — Logo bar */}
        <section className="border-y border-slate-100 bg-slate-50 py-8">
          <div className="mx-auto max-w-7xl px-6 text-center">
            <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">Built to integrate with</div>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-lg font-semibold text-slate-400">
              <span>Encompass</span><span>Fannie Mae</span><span>Freddie Mac</span><span>Experian</span><span>Equifax</span>
            </div>
          </div>
        </section>

        {/* 5 — How it works */}
        <section id="how" className="mx-auto max-w-7xl px-6 py-20">
          <div className="text-center">
            <Eyebrow>How it works</Eyebrow>
            <h2 className="text-3xl font-bold tracking-tight">From loan submission to AI decision in 3 steps</h2>
          </div>
          <div className="relative mt-12 grid gap-6 md:grid-cols-3">
            {STEPS.map(([num, icon, title, desc]) => (
              <div key={num} className="relative rounded-2xl border border-slate-200 bg-white p-6">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{icon}</span>
                  <span className="text-2xl font-bold text-slate-200">{num}</span>
                </div>
                <h3 className="mt-3 text-lg font-semibold text-slate-900">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{desc}</p>
              </div>
            ))}
            <div className="pointer-events-none absolute left-[33%] right-[33%] top-12 hidden border-t-2 border-dashed border-slate-200 md:block" />
          </div>
        </section>

        {/* 6 — Case studies */}
        <section className="bg-slate-50 py-20">
          <div className="mx-auto max-w-7xl px-6">
            <div className="text-center">
              <Eyebrow>Real results</Eyebrow>
              <h2 className="text-3xl font-bold tracking-tight">What happens when AI reviews every loan</h2>
            </div>
            <div className="mt-12 grid gap-6 md:grid-cols-3">
              {CASES.map(([stat, sub, body, quote]) => (
                <div key={stat} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-6">
                  <div className="text-2xl font-bold text-brand">{stat}</div>
                  <div className="text-sm font-medium text-slate-500">{sub}</div>
                  <p className="mt-3 text-sm leading-relaxed text-slate-600">{body}</p>
                  <p className="mt-4 border-l-2 border-brand pl-3 text-sm italic text-slate-700">“{quote}”</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 7 — Who it's for */}
        <section id="who" className="mx-auto max-w-7xl px-6 py-20">
          <div className="text-center">
            <Eyebrow>Who it's for</Eyebrow>
            <h2 className="text-3xl font-bold tracking-tight">Built for every role in the lending workflow</h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {PERSONAS.map(([who, head, body]) => (
              <div key={who} className="rounded-2xl border border-slate-200 bg-white p-6">
                <div className="text-xs font-semibold uppercase tracking-wide text-brand">{who}</div>
                <h3 className="mt-1 text-lg font-semibold text-slate-900">{head}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 8 — Products + platform */}
        <section id="products" className="bg-slate-50 py-20">
          <div className="mx-auto max-w-7xl px-6">
            <div className="grid gap-10 md:grid-cols-2">
              <div>
                <Eyebrow>Products</Eyebrow>
                <div className="space-y-3">
                  {PRODUCTS.map(([name, desc]) => (
                    <div key={name} className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="font-semibold text-slate-900">{name}</div>
                      <div className="text-sm text-slate-500">{desc}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <Eyebrow>Platform</Eyebrow>
                <div className="space-y-3">
                  {PLATFORM.map(([name, desc]) => (
                    <div key={name} className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="font-semibold text-slate-900">{name}</div>
                      <div className="text-sm text-slate-500">{desc}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 rounded-xl border border-brand/30 bg-brand-light/40 p-4">
                  <div className="font-semibold text-brand-dark">Deploy your way</div>
                  <div className="text-sm text-slate-600">Fully managed SaaS, or a private deployment in your own AWS VPC.</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* 9 — Pricing */}
        <section id="pricing" className="mx-auto max-w-7xl px-6 py-20">
          <div className="text-center">
            <Eyebrow>Pricing</Eyebrow>
            <h2 className="text-3xl font-bold tracking-tight">Simple per-loan pricing. No hidden fees.</h2>
            <p className="mt-2 text-slate-500">Start with Pipeline. Add products as you grow.</p>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {PRICING.map((p) => (
              <div key={p.name} className={`relative flex flex-col rounded-2xl border bg-white p-6 ${p.popular ? 'border-brand ring-2 ring-brand/20' : 'border-slate-200'}`}>
                {p.popular && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-brand px-3 py-0.5 text-xs font-bold text-white">MOST POPULAR</span>
                )}
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">{p.name}</div>
                <div className="mt-2 text-3xl font-bold text-slate-900">{p.price}<span className="text-base font-medium text-slate-400">{p.unit}</span></div>
                <div className="text-xs text-slate-400">{p.min}</div>
                <div className="mt-4 flex-1 text-sm text-slate-600">{p.includes}</div>
                <a href={DEMO} className={`mt-5 rounded-lg px-3 py-2 text-center text-sm font-semibold ${p.popular ? 'bg-brand text-white hover:bg-brand-dark' : 'border border-slate-300 text-slate-700 hover:bg-slate-50'}`}>
                  {p.name === 'Enterprise' ? 'Contact sales' : 'Request a demo'}
                </a>
              </div>
            ))}
          </div>
        </section>

        {/* 10 — FAQ */}
        <section id="faq" className="bg-slate-50 py-20">
          <div className="mx-auto max-w-3xl px-6">
            <div className="text-center">
              <Eyebrow>Frequently asked questions</Eyebrow>
            </div>
            <div className="mt-8 space-y-3">
              {FAQS.map(([q, a], i) => (
                <div key={q} className="rounded-xl border border-slate-200 bg-white">
                  <button onClick={() => setOpenFaq(openFaq === i ? null : i)} className="flex w-full items-center justify-between px-5 py-4 text-left">
                    <span className="font-semibold text-slate-900">{q}</span>
                    <span className="text-slate-400">{openFaq === i ? '−' : '+'}</span>
                  </button>
                  {openFaq === i && <p className="px-5 pb-4 text-sm leading-relaxed text-slate-600">{a}</p>}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 11 — Testimonial */}
        <section className="mx-auto max-w-4xl px-6 py-20 text-center">
          <p className="text-2xl font-medium italic leading-relaxed text-slate-700">
            “Accord cut our average decision time from 5 days to 4 hours. The audit trail saved us 3 weeks during our last exam.”
          </p>
          <p className="mt-4 text-sm font-semibold text-slate-500">VP of Underwriting · Design Partner</p>
        </section>

        {/* 12 — CTA banner */}
        <section className="px-6 py-16" style={{ background: '#0F6E56' }}>
          <div className="mx-auto max-w-3xl text-center text-white">
            <h2 className="text-3xl font-bold">Ready to see Accord in action?</h2>
            <p className="mt-2 text-white/85">Request a demo and see how 12 AI agents evaluate your loans.</p>
            <div className="mt-6 flex flex-col items-center gap-3">
              <a href={DEMO} className="rounded-lg bg-white px-6 py-2.5 text-sm font-semibold text-brand-dark hover:bg-white/90">Request a demo →</a>
              <Link to="/login" className="text-sm text-white/80 underline hover:text-white">Or log in to your account →</Link>
            </div>
          </div>
        </section>
      </main>

      {/* 13 — Footer */}
      <footer className="border-t border-slate-200 bg-white py-12">
        <div className="mx-auto max-w-7xl px-6">
          <div className="grid gap-8 md:grid-cols-5">
            <div className="md:col-span-1">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
                <span className="text-lg font-bold tracking-tight">accord</span>
              </div>
              <p className="mt-2 text-sm text-slate-500">Every decision. In accord.</p>
              <p className="mt-4 text-xs text-slate-400">© 2026 Accord. All rights reserved.</p>
            </div>
            {[
              ['Product', ['Pipeline', 'Analytics', 'Simulation', 'Audit']],
              ['Platform', ['Decision Engine', 'AI Agents', 'Integrations', 'Docs & API']],
              ['Company', ['About', 'Careers', 'Blog', 'Contact']],
              ['Legal', ['Privacy', 'Terms', 'Security', 'DPA']],
            ].map(([title, links]) => (
              <div key={title as string}>
                <div className="text-sm font-semibold text-slate-900">{title}</div>
                <ul className="mt-2 space-y-1.5 text-sm text-slate-500">
                  {(links as string[]).map((l) => <li key={l}><a href="#top" className="hover:text-slate-900">{l}</a></li>)}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-slate-100 pt-6 text-xs text-slate-400">
            <span>🔒 AES-256 at rest · TLS 1.3 in transit</span>
            <span>🏛️ SOC 2 ready</span>
            <span>⚖️ Compliant by design</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
