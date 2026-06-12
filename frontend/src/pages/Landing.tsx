import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

const DEMO = 'mailto:demo@useaccord.com?subject=Accord%20demo%20request'

// ── Hero: animated loan-evaluation card (no agent counts shown) ──────
const AGENTS: Array<[string, string, string]> = [
  ['🏦', 'Credit Assessment', 'Credit score and history'],
  ['🛡️', 'Fraud Screening', 'Identity and watchlist check'],
  ['💰', 'Income Verification', 'Income documents review'],
  ['🏠', 'Collateral Analysis', 'Property value and LTV'],
  ['📊', 'DTI Analysis', 'Debt-to-income assessment'],
  ['⚖️', 'Compliance Check', 'Regulatory requirements'],
  ['👔', 'Employment Check', 'Job stability verification'],
  ['📋', 'Product Eligibility', 'Loan program matching'],
]

function EvaluationCard() {
  const STATES = AGENTS.length + 5 // reveal + decision + hold
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => (t + 1) % STATES), 750)
    return () => clearInterval(id)
  }, [STATES])

  const allIn = tick > AGENTS.length
  const status = tick === 0 ? 'New' : allIn ? 'Decision: Approve' : 'Evaluating…'
  const statusCls = tick === 0 ? 'bg-slate-100 text-slate-600' : allIn ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
  const RING = 2 * Math.PI * 24
  const conf = allIn ? 97 : 0

  return (
    <div className="w-full max-w-xl rounded-2xl border border-slate-200 bg-slate-50 p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-400">Pipeline / Loan #1234567</span>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusCls}`}>{status}</span>
      </div>

      <div className="grid grid-cols-[110px_1fr_120px] gap-0 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {/* Loan summary */}
        <div className="space-y-1.5 border-r border-slate-100 p-3 text-[11px]">
          {[['Borrower', 'John D. Smith'], ['Type', 'Conventional'], ['Amount', '$425,000'], ['DTI', '36.2%'], ['Score', '742'], ['LTV', '68%']].map(([k, v]) => (
            <div key={k}><div className="text-slate-400">{k}</div><div className="font-medium text-slate-700">{v}</div></div>
          ))}
        </div>

        {/* AI findings */}
        <div className="p-3">
          <div className="mb-1.5 text-[11px] font-semibold text-slate-700">AI Findings</div>
          <div className="space-y-1">
            {AGENTS.map(([icon, name, desc], i) => {
              const show = i < tick
              const passed = allIn || i < tick - 1
              return (
                <div key={name} className={`flex items-center gap-1.5 transition-all duration-500 ${show ? 'translate-x-0 opacity-100' : 'translate-x-3 opacity-0'}`}>
                  <span className="text-xs">{icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11px] font-medium text-slate-700">{name}</span>
                    <span className="block truncate text-[9px] text-slate-400">{desc}</span>
                  </span>
                  {passed ? (
                    <span className="rounded-full bg-green-100 px-1.5 text-[9px] font-semibold text-green-700">Pass</span>
                  ) : show ? (
                    <span className="animate-pulse text-[10px] text-amber-500">●●●</span>
                  ) : null}
                </div>
              )
            })}
          </div>
          <div className={`mt-2 text-[10px] font-medium ${allIn ? 'text-green-600' : 'text-slate-400'}`}>
            {allIn ? '✓ All checks complete' : '+ more checks running…'}
          </div>
        </div>

        {/* Decision */}
        <div className="flex flex-col items-center justify-center border-l border-slate-100 p-3 text-center">
          {!allIn ? (
            <div className="text-[10px] text-slate-400">Awaiting analysis…</div>
          ) : (
            <>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Decision</div>
              <svg width="60" height="60" viewBox="0 0 60 60">
                <circle cx="30" cy="30" r="24" fill="none" stroke="#e2e8f0" strokeWidth="5" />
                <circle cx="30" cy="30" r="24" fill="none" stroke="#0F6E56" strokeWidth="5" strokeLinecap="round"
                  strokeDasharray={RING} strokeDashoffset={RING * (1 - conf / 100)} transform="rotate(-90 30 30)"
                  style={{ transition: 'stroke-dashoffset 1s ease' }} />
                <text x="30" y="30" textAnchor="middle" className="fill-slate-900 text-base font-bold">{conf}</text>
                <text x="30" y="42" textAnchor="middle" className="fill-slate-400 text-[7px]">Confidence</text>
              </svg>
              <div className="mt-1.5 text-[9px] leading-tight text-slate-500">Approved based on comprehensive AI analysis</div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Section data ─────────────────────────────────────────────────────
const NAV_PRODUCTS: Array<[string, string, string]> = [
  ['📋', 'Pipeline', 'See what AI found on every loan'],
  ['📊', 'Analytics', 'Know your pipeline inside and out'],
  ['🔮', 'Simulation', "Ask 'what if' about anything"],
  ['📑', 'Audit', 'Pull the examiner package in one click'],
]
const NAV_PLATFORM: Array<[string, string]> = [
  ['Decision Engine', 'Policy-aware reasoning with confidence scoring'],
  ['AI Agents', 'Specialized agents for every lending decision'],
  ['Integrations', 'Encompass, Experian, Fannie Mae & more'],
  ['Docs & API', 'Get started in under an hour'],
]
const STATS = [
  ['80%', 'faster underwriting', 'Reduce cycle times from days to hours'],
  ['60%', 'fewer manual reviews', 'AI handles the analysis, you make the call'],
  ['100%', 'audit traceability', 'Full decision trail for every loan'],
  ['Same-day', 'setup', 'Connect your LOS and go live today'],
]
const STEPS = [
  ['01', '🔌', 'Connect your loan system', 'Upload a CSV or connect your LOS. Your loan data flows into Accord automatically. Go live the same day.'],
  ['02', '🧠', 'AI checks every aspect', 'Credit, fraud, income, collateral, compliance, employment, debt ratios, product eligibility, pricing, and closing readiness — all checked in seconds.'],
  ['03', '✅', 'Review findings, make your call', 'See what AI found, what data it analyzed, and what it recommends — in plain English. Approve clean files with one click. Every action documented.'],
]
const PRODUCTS = [
  ['📋', 'Pipeline', 'See what AI found on every loan', "Review findings, take action, move on. AI tells you what's wrong, what's fine, and what to do next — for every loan in your pipeline."],
  ['🔮', 'Simulation', "Ask 'what if' about anything", 'What if we tighten DTI? What if rates rise? Should this loan be approved? Where are our hidden risks? Get answers with AI reasoning, not just numbers.'],
  ['📊', 'Analytics', 'Know your pipeline inside and out', "Who's blocked, what's aging, where risk is concentrating. Team performance, override trends, and portfolio intelligence."],
  ['📑', 'Audit', 'Pull the examiner package in one click', 'Every AI finding, every human action, every override — documented with reasoning. HMDA, fair lending, adverse action. Complete trail.'],
]
const SIM_QS: Array<[string, string, string, string]> = [
  ['What if we tighten DTI to 36%?', '3 loans affected · $1.5M volume impact', "Each borrower: why they'd fail, how to restructure. 'Sarah Johnson misses by 0.1% — approve with compensating factors or reduce loan by $1K.'", 'border-l-[#0F6E56]'],
  ['Should this blocked loan be approved?', 'AI agents debate it from every angle', "Consensus: investigate further, don't deny yet. 3 insights that no single review would catch.", 'border-l-[#F59E0B]'],
  ['Where are our hidden portfolio risks?', '46% have income documentation gaps', '97% concentration in one product type. All rate locks expire the same week.', 'border-l-[#EF4444]'],
]
const CASES = [
  ['4.2 → 1.7 hrs', 'Average review time per loan', 'AI handles initial analysis in seconds. Underwriters review AI findings instead of starting from scratch.', 'I used to spend 20 minutes pulling the credit report. Now the AI does that and tells me what to focus on.'],
  ['5 fraud cases', 'caught that manual review missed', 'AI identified watchlist matches and synthetic identity patterns. The portfolio health check found 46% of loans had income discrepancies — a systematic problem invisible to file-by-file review.', 'The health check found a pattern across thousands of loans that no individual review would have caught.'],
  ['3 loans, $1.5M', 'impact predicted before policy change', 'Before tightening DTI from 43% to 36%, the simulator showed exactly which borrowers would be affected, why, and what alternatives existed.', 'We could see the impact across the entire book before committing.'],
]
const PERSONAS = [
  ['👤', 'Processors & Underwriters', 'Review AI findings, not raw documents', 'See what AI found, what data it analyzed, what it recommends. Approve clean files in one click. Request docs with a checklist. Focus on exceptions, not routine.'],
  ['👔', 'Senior Underwriters', 'Decide with full context', 'AI already analyzed the loan from every angle. See the consensus, dissent, and evidence. Run a debate for complex cases. Override with documented justification.'],
  ['📊', 'Managers & VPs', 'See your team and your risk', "Who's overloaded? What's aging? Which policies cause blocks? Test rule changes before committing. Reassign work across your team."],
  ['⚖️', 'Compliance & Audit', 'Answer any examiner question in seconds', 'Every AI finding, every human action, every override — documented. Export the full examiner package. HMDA, fair lending, adverse action — one place.'],
]
const PLATFORM = [
  ['Decision Engine', 'Policy-aware reasoning with confidence scoring'],
  ['AI Agents', 'Specialized agents for every lending decision'],
  ['Integrations', 'Encompass, Experian, Fannie Mae & 50+ more'],
  ['Docs & API', 'Get started in under an hour with comprehensive docs'],
]
const PRICING = [
  { name: 'Starter', price: '$15', unit: '/loan', min: '$500/mo minimum', desc: 'See what AI finds on every loan', cta: 'Start free trial', solid: false, popular: false, features: ['Pipeline', 'CSV export', 'Self-serve setup', 'Email support'] },
  { name: 'Growth', price: '$35', unit: '/loan', min: '$1,500/mo minimum', desc: 'Add portfolio intelligence', cta: 'Start free trial', solid: false, popular: false, features: ['Pipeline + Analytics', 'CSV + PDF export', 'API access (1,000 calls/hr)', 'Guided setup call'] },
  { name: 'Business', price: '$60', unit: '/loan', min: '$3,000/mo minimum', desc: 'Test any decision before you make it', cta: 'Start free trial', solid: true, popular: true, features: ['Pipeline + Analytics + Simulation', 'All exports', 'API + webhooks (5,000 calls/hr)', 'Dedicated onboarding ($5K setup)'] },
  { name: 'Enterprise', price: 'Custom', unit: '', min: '', desc: 'Full platform with dedicated support', cta: 'Contact sales', solid: false, popular: false, features: ['All 4 products', 'Dedicated read-only database replica', 'VPC deployment option', 'Dedicated success manager', '24/7 phone support', 'Custom integrations', 'Implementation: $15–25K'] },
]
const FAQS = [
  ['How long does setup take?', 'Most lenders go live the same day. Upload a CSV of your loans and AI starts evaluating immediately. For Encompass integration, setup takes about 15 minutes. Enterprise implementations with custom data mapping typically take 2–3 weeks.'],
  ['Does Accord replace my LOS?', 'No. Accord works alongside your LOS — Encompass, ICE, or whatever you use. Your LOS manages the loan lifecycle. Accord provides AI evaluation and audit trail. Think of it as the brain that reads what your LOS stores.'],
  ['How does the AI make decisions?', "It doesn't. AI evaluates and recommends. Humans decide. Specialized agents each check one aspect — credit checks credit, fraud checks fraud, income checks income. Each explains what it found and why in plain English. You make the final call."],
  ['What if the AI is wrong?', 'Override any recommendation with a written justification. The override is documented in the audit trail so examiners can see the reasoning. Over time, the system learns from overrides.'],
  ['Is my data secure?', "Your data is stored in our AWS infrastructure with AES-256 encryption at rest and TLS 1.3 in transit. Each customer's data is isolated at the database level — no other customer can access your loans. We never sell, share, or use your data to train AI for other customers. You can export all your data anytime. Enterprise customers can deploy in their own AWS VPC."],
  ['Who owns the data?', 'You do. Always. Accord stores and processes your data on your behalf but never claims ownership. Export anytime via CSV, API, or full database dump. When you leave, data is deleted within 90 days and deletion is confirmed in writing.'],
  ['Can I connect my BI tools?', 'Enterprise customers get a dedicated read-only database replica. Connect Tableau, Power BI, Looker, or run your own SQL queries against your loan data. Updated every 15 minutes.'],
  ['Can I run Accord in my own cloud?', 'Enterprise customers can deploy Accord in their own AWS VPC. Your data never leaves your environment. Same product, your infrastructure.'],
]

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-xs font-bold uppercase tracking-widest text-brand">{children}</div>
}

export default function Landing() {
  const [bannerOpen, setBannerOpen] = useState(true)
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [productsOpen, setProductsOpen] = useState(false)
  const navRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (productsOpen && navRef.current && !navRef.current.contains(e.target as Node)) setProductsOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [productsOpen])

  return (
    <div className="min-h-screen scroll-smooth bg-white text-slate-900">
      {/* 1 — Announcement banner */}
      {bannerOpen && (
        <div className="relative flex items-center justify-center gap-2 px-4 text-[13px] text-white" style={{ height: 40, background: '#0F6E56' }}>
          <span>✦ Introducing AI-powered lending decisions with complete audit trail.</span>
          <a href="#how-it-works" className="font-medium underline">See how →</a>
          <button onClick={() => setBannerOpen(false)} aria-label="Dismiss" className="absolute right-3 text-white/80 hover:text-white">✕</button>
        </div>
      )}

      {/* 2 — Marketing nav */}
      <header ref={navRef} className="sticky top-0 z-30 border-b border-slate-100 bg-white">
        <div className="mx-auto flex max-w-[1200px] items-center px-6" style={{ height: 56 }}>
          <a href="#top" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight">accord</span>
          </a>
          <nav className="ml-8 hidden items-center gap-6 text-sm font-medium text-slate-600 md:flex">
            <button onClick={() => setProductsOpen((v) => !v)} className={`flex items-center gap-1 hover:text-slate-900 ${productsOpen ? 'text-slate-900' : ''}`}>Products ▾</button>
            <a href="#pricing" className="hover:text-slate-900">Pricing</a>
            <a href="#faq" className="hover:text-slate-900">Docs</a>
            <a href="#who" className="hover:text-slate-900">Company ▾</a>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <Link to="/login" className="text-sm font-medium text-slate-600 hover:text-slate-900">Log in</Link>
            <a href={DEMO} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo</a>
          </div>
        </div>
        {productsOpen && (
          <div className="absolute left-0 right-0 border-b border-slate-200 bg-white shadow-lg">
            <div className="mx-auto grid max-w-[1200px] gap-10 px-6 py-7 md:grid-cols-2">
              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Products</div>
                <div className="space-y-1">
                  {NAV_PRODUCTS.map(([icon, name, desc]) => (
                    <a key={name} href="#products" onClick={() => setProductsOpen(false)} className="flex items-start gap-3 rounded-lg p-2.5 hover:bg-slate-50">
                      <span className="text-lg">{icon}</span>
                      <span><span className="block font-semibold text-slate-900">{name}</span><span className="block text-sm text-slate-500">{desc}</span></span>
                    </a>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Platform</div>
                <div className="space-y-1">
                  {NAV_PLATFORM.map(([name, desc]) => (
                    <a key={name} href="#platform" onClick={() => setProductsOpen(false)} className="block rounded-lg p-2.5 hover:bg-slate-50">
                      <span className="block font-semibold text-slate-900">{name}</span><span className="block text-sm text-slate-500">{desc}</span>
                    </a>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </header>

      <main id="top">
        {/* 3 — Hero */}
        <section className="mx-auto grid max-w-[1200px] items-center gap-10 px-6 pb-10 pt-14 lg:grid-cols-[55fr_45fr]">
          <div>
            <h1 className="text-[42px] font-bold leading-[1.15] tracking-[-0.03em] text-[#111]">
              AI-powered lending decisions with <span className="text-brand">complete audit trail</span>
            </h1>
            <p className="mt-5 max-w-[480px] text-[17px] leading-[1.7] text-[#4B5563]">
              Specialized AI checks every aspect of every loan — credit, fraud, income, collateral, compliance,
              and more. Decisions in hours, not days. Every step documented for examiners.
            </p>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-[#6B7280]">
              <Link to="/security" className="hover:text-slate-900">🔒 Enterprise security</Link>
              <Link to="/security#soc2" className="hover:text-slate-900">🏛️ SOC 2 ready</Link>
              <Link to="/compliance" className="hover:text-slate-900">⚖️ Compliant by design</Link>
            </div>
            <div className="mt-9 grid grid-cols-2 gap-4">
              {STATS.map(([big, label, sub]) => (
                <div key={label} className="rounded-lg border border-slate-200 p-4">
                  <div className="text-[28px] font-bold text-brand">{big}</div>
                  <div className="text-[13px] font-bold text-slate-800">{label}</div>
                  <div className="text-[11px] text-slate-500">{sub}</div>
                </div>
              ))}
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href={DEMO} className="rounded-lg bg-brand px-7 py-3 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo →</a>
              <a href="#how-it-works" className="rounded-lg border border-[#D1D5DB] px-7 py-3 text-sm font-semibold text-[#374151] hover:bg-slate-50">See it in action ▷</a>
            </div>
          </div>
          <div className="flex justify-center lg:justify-end"><EvaluationCard /></div>
        </section>

        {/* 4 — Logo bar */}
        <section className="border-y border-slate-100 bg-slate-50 py-8">
          <div className="mx-auto max-w-[1200px] px-6 text-center">
            <div className="text-[13px] text-[#9CA3AF]">Built to integrate with</div>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-base font-bold text-[#9CA3AF]">
              <span>Encompass</span><span>Fannie Mae</span><span>Freddie Mac</span><span>Experian</span><span>Equifax</span>
            </div>
          </div>
        </section>

        {/* 5 — How it works */}
        <section id="how-it-works" className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>How it works</Eyebrow>
            <h2 className="text-[28px] font-bold tracking-tight">From loan submission to decision in 3 steps</h2>
          </div>
          <div className="relative mt-12 grid gap-6 md:grid-cols-3">
            {STEPS.map(([num, icon, title, desc]) => (
              <div key={num} className="relative z-10 rounded-xl border border-slate-200 bg-white p-7">
                <div className="text-[48px] font-extrabold leading-none text-[#D1FAE5]">{num}</div>
                <div className="mt-2 text-3xl">{icon}</div>
                <h3 className="mt-3 text-base font-bold text-slate-900">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{desc}</p>
              </div>
            ))}
            <div className="pointer-events-none absolute left-[33%] right-[33%] top-20 hidden border-t-2 border-dotted border-slate-300 md:block" />
          </div>
        </section>

        {/* 6 — Products */}
        <section id="products" className="bg-slate-50 py-20">
          <div className="mx-auto max-w-[1200px] px-6">
            <div className="text-center">
              <Eyebrow>Products</Eyebrow>
              <h2 className="text-[28px] font-bold tracking-tight">Four products. One platform.</h2>
              <p className="mt-2 text-slate-500">Start with Pipeline. Add more as you grow.</p>
            </div>
            <div className="mt-10 grid gap-5 md:grid-cols-2">
              {PRODUCTS.map(([icon, name, head, body]) => (
                <div key={name} className="flex flex-col rounded-xl border border-slate-200 bg-white p-6">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-light text-xl">{icon}</span>
                    <div className="text-lg font-semibold text-slate-900">{name}</div>
                  </div>
                  <div className="mt-2 font-medium text-slate-700">{head}</div>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-slate-600">{body}</p>
                  <a href={DEMO} className="mt-3 text-sm font-medium text-brand hover:underline">Learn more →</a>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 7 — Simulation deep dive */}
        <section className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>Simulation</Eyebrow>
            <h2 className="text-[32px] font-bold tracking-tight">What would happen if…?</h2>
            <p className="mx-auto mt-2 max-w-2xl text-base text-[#6B7280]">Ask any question about your portfolio. See the answer — with AI reasoning — in seconds.</p>
          </div>
          <div className="mt-12 grid gap-8 lg:grid-cols-2">
            <div className="space-y-4">
              {SIM_QS.map(([q, ans, detail, bar]) => (
                <div key={q} className={`rounded-xl border border-slate-200 border-l-4 bg-white p-5 ${bar}`}>
                  <div className="font-bold text-slate-900">{q}</div>
                  <div className="mt-1 text-sm text-[#6B7280]">{ans}</div>
                  <div className="mt-1 text-[13px] italic text-[#9CA3AF]">{detail}</div>
                </div>
              ))}
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
              <div className="mb-3 text-sm font-semibold text-slate-700">Policy Simulator — DTI limit</div>
              <div className="space-y-2">
                {['36% (tighten)', '38%', '40%', '50% (relax)', 'Custom…'].map((o, i) => (
                  <div key={o} className={`rounded-lg border px-3 py-2 text-sm ${i === 0 ? 'border-brand bg-brand-light/40 font-semibold text-brand-dark' : 'border-slate-200 bg-white text-slate-600'}`}>{o}</div>
                ))}
              </div>
              <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3 text-sm">
                <div className="font-semibold text-slate-900">3 loans affected · $1.5M impact</div>
                <div className="text-xs text-slate-500">Each with restructure options</div>
              </div>
              <button className="mt-4 w-full rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white">Run simulation</button>
            </div>
          </div>
          <p className="mx-auto mt-8 max-w-2xl text-center text-[15px] italic text-[#374151]">
            No spreadsheets. No guesswork. AI reasoning for every scenario, every borrower, every decision.
          </p>
        </section>

        {/* 8 — Case studies */}
        <section className="bg-slate-50 py-20">
          <div className="mx-auto max-w-[1200px] px-6">
            <div className="text-center">
              <Eyebrow>Real results</Eyebrow>
              <h2 className="text-[28px] font-bold tracking-tight">What happens when AI reviews every loan</h2>
            </div>
            <div className="mt-12 grid gap-5 md:grid-cols-3">
              {CASES.map(([stat, sub, body, quote]) => (
                <div key={stat} className="flex flex-col rounded-xl border border-slate-200 bg-white p-6">
                  <div className="text-[36px] font-bold leading-none text-brand">{stat}</div>
                  <div className="mt-2 text-sm font-bold text-slate-700">{sub}</div>
                  <p className="mt-3 text-[13px] leading-relaxed text-[#6B7280]">{body}</p>
                  <p className="mt-4 text-xs italic text-[#9CA3AF]">“{quote}”</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 9 — Who it's for */}
        <section id="who" className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>Who it's for</Eyebrow>
            <h2 className="text-[28px] font-bold tracking-tight">Built for every role in the lending workflow</h2>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            {PERSONAS.map(([icon, who, head, body]) => (
              <div key={who} className="rounded-xl border border-slate-200 bg-slate-50 p-6">
                <div className="text-[28px]">{icon}</div>
                <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-brand">{who}</div>
                <h3 className="mt-1 font-semibold text-slate-900">{head}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-[#6B7280]">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 10 — Platform */}
        <section id="platform" className="bg-slate-50 py-20">
          <div className="mx-auto grid max-w-[1200px] gap-10 px-6 md:grid-cols-2">
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
            </div>
            <div className="flex flex-col justify-center rounded-2xl border border-brand bg-white p-6">
              <div className="text-2xl">☁️</div>
              <div className="mt-2 text-lg font-bold text-slate-900">Deploy your way</div>
              <div className="text-sm font-semibold text-brand">SaaS or Private Deployment</div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                Run Accord in our cloud or deploy in your own AWS VPC. You own your data either way. Enterprise customers get a
                dedicated read-only database replica for their own analytics and BI tools — Tableau, Power BI, Looker, whatever you use.
              </p>
              <a href={DEMO} className="mt-3 text-sm font-medium text-brand hover:underline">Learn more →</a>
            </div>
          </div>
        </section>

        {/* 11 — Pricing */}
        <section id="pricing" className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>Pricing</Eyebrow>
            <h2 className="text-[28px] font-bold tracking-tight">Simple per-loan pricing. No hidden fees.</h2>
            <p className="mt-2 text-[15px] text-[#6B7280]">Start with Pipeline. Add products as you grow.</p>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {PRICING.map((p) => (
              <div key={p.name} className={`relative flex flex-col rounded-xl bg-white p-6 ${p.popular ? 'border-2 border-brand' : 'border border-slate-200'}`}>
                {p.popular && <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-brand px-3 py-0.5 text-xs font-bold text-white">MOST POPULAR</span>}
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">{p.name}</div>
                <div className="mt-2 text-[32px] font-bold leading-none text-slate-900">{p.price}<span className="text-[13px] font-medium text-slate-400">{p.unit}</span></div>
                <div className="text-xs text-[#9CA3AF]">{p.min || ' '}</div>
                <div className="mt-2 text-[13px] text-[#6B7280]">{p.desc}</div>
                <ul className="mt-4 flex-1 space-y-1.5 text-[13px] text-slate-600">
                  {p.features.map((f) => <li key={f}>✓ {f}</li>)}
                </ul>
                <a href={DEMO} className={`mt-5 rounded-lg px-3 py-2 text-center text-sm font-semibold ${p.solid ? 'bg-brand text-white hover:bg-brand-dark' : 'border border-brand text-brand hover:bg-brand-light/40'}`}>{p.cta}</a>
              </div>
            ))}
          </div>
          <p className="mt-8 text-center text-[13px] text-[#9CA3AF]">All plans include a 14-day free trial. No credit card required.</p>
          <div className="mx-auto mt-6 max-w-3xl rounded-lg border border-slate-200 p-4 text-[13px] text-slate-600">
            📊 <span className="font-semibold text-slate-800">Enterprise data access:</span> Get a dedicated read-only database replica with your loan data.
            Connect Tableau, Power BI, Looker, or any BI tool directly. Run your own queries. Build your own reports. Your data, your analytics.
          </div>
        </section>

        {/* 12 — FAQ */}
        <section id="faq" className="bg-slate-50 py-20">
          <div className="mx-auto max-w-[800px] px-6">
            <div className="text-center"><Eyebrow>Frequently asked questions</Eyebrow></div>
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

        {/* 13 — Testimonial */}
        <section className="mx-auto max-w-[700px] px-6 py-20 text-center">
          <p className="text-2xl font-medium italic leading-[1.6] text-[#374151]">
            “Accord cut our average decision time from 5 days to 4 hours. The audit trail saved us 3 weeks during our last exam. I can't imagine going back to doing this manually.”
          </p>
          <p className="mt-5 text-sm font-bold text-slate-700">VP of Underwriting</p>
          <p className="text-[13px] text-[#9CA3AF]">Design Partner · Mid-size Retail Lender</p>
        </section>

        {/* 14 — CTA banner */}
        <section className="px-6 py-12" style={{ background: '#0F6E56' }}>
          <div className="mx-auto max-w-3xl text-center text-white">
            <h2 className="text-[28px] font-bold">Ready to see Accord in action?</h2>
            <p className="mt-2 text-base text-white/80">See how AI evaluates your loans — with full audit trail.</p>
            <div className="mt-6 flex flex-col items-center gap-3">
              <a href={DEMO} className="rounded-lg bg-white px-6 py-2.5 text-sm font-bold text-brand-dark hover:bg-white/90">Request a demo →</a>
              <Link to="/login" className="text-sm text-white underline hover:text-white/80">Or log in to your account →</Link>
            </div>
          </div>
        </section>
      </main>

      {/* 15 — Footer */}
      <footer className="py-10" style={{ background: '#111827' }}>
        <div className="mx-auto max-w-[1200px] px-12">
          <div className="grid gap-8 md:grid-cols-5">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
                <span className="text-lg font-bold tracking-tight text-white">accord</span>
              </div>
              <p className="mt-2 text-[13px] text-[#9CA3AF]">Every decision. In accord.</p>
              <p className="mt-4 text-xs text-[#6B7280]">© 2026 Accord Technologies. All rights reserved.</p>
            </div>
            {[
              ['Product', ['Pipeline', 'Analytics', 'Simulation', 'Audit', 'Pricing']],
              ['Platform', ['Decision Engine', 'AI Agents', 'Integrations', 'Docs & API']],
              ['Company', ['About', 'Blog', 'Careers', 'Contact', 'Security']],
              ['Legal', ['Privacy Policy', 'Terms of Service', 'Cookie Policy']],
            ].map(([title, links]) => (
              <div key={title as string}>
                <div className="text-xs font-bold uppercase tracking-wide text-[#9CA3AF]">{title}</div>
                <ul className="mt-2 space-y-1.5 text-[13px] text-[#D1D5DB]">
                  {(links as string[]).map((l) => (
                    <li key={l}>
                      {l === 'Security' ? <Link to="/security" className="hover:text-white">{l}</Link>
                        : l === 'Pricing' ? <a href="#pricing" className="hover:text-white">{l}</a>
                          : <a href="#top" className="cursor-pointer hover:text-white">{l}</a>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-[#374151] pt-5 text-xs text-[#6B7280]">
            <span>🔒 Bank-grade security (AES-256)</span><span>🛡️ You own your data. Always.</span><span>⬆ 99.9% uptime SLA</span><span>📞 Real humans, always</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
