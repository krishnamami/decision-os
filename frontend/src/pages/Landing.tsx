import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

const DEMO = 'mailto:demo@useaccord.com?subject=Accord%20demo%20request'

// ⬇️ ONE-LINE CHANGE: paste your recorded demo here to swap the placeholder for
// the real video. Accepts a Loom/YouTube *embed* URL (an <iframe> is rendered)
// or a direct .mp4/.webm URL (a <video controls> is rendered). Leave '' for the
// placeholder. See docs/DEMO_SCRIPT.md for recording the video.
//   Loom:    https://www.loom.com/embed/<id>
//   YouTube: https://www.youtube.com/embed/<id>
const DEMO_VIDEO_URL = '/accord_demo.mp4'

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
]
const STEPS4 = [
  ['01', 'READ', 'AI reads every document in the loan file'],
  ['02', 'CHECK', 'Matches every data point to regulations and policy'],
  ['03', 'RECOMMEND', 'Delivers a recommendation backed by evidence'],
  ['04', 'DECIDE', 'Your team reviews and makes the final call'],
]
const STAKEHOLDERS: Array<[string, string, string, string]> = [
  ['🏦', 'Lenders', 'Faster decisions. Fewer manual reviews.', 'AI handles the analysis — credit, fraud, income, collateral, compliance — your team reviews the findings and makes the call. Every decision documented with evidence and regulation citations.'],
  ['🏠', 'Borrowers', 'Faster answers on the biggest purchase of their life.', "No more waiting days for an underwriting decision. Accord evaluates in seconds so your team can respond in hours, not weeks. Transparent process — borrowers know exactly what's needed and why."],
  ['⚖️', 'Examiners & Compliance', 'Every decision documented. Every action traced.', 'When an examiner asks "why?" — pull the answer in one click. Full audit trail: which rules applied, which data was analyzed, who decided, and why. HMDA, fair lending, adverse action — one place.'],
]
const COMPLIANCE: Array<[string, string, string]> = [
  ['🔒', 'Three Layers of Rules', "Federal law, agency guidelines, and your overlays — all visible. OFAC screening is automatic. QM safe harbor is enforced. State rules apply by property location. You can't accidentally violate a regulation."],
  ['📋', 'Every Decision Traceable', 'Click any data point — see the source document. Click any rule — see the regulation citation. Click any decision — see who decided, when, and why. Examiners get the full package in one click.'],
  ['📊', 'Continuous Monitoring', 'OFAC watchlists updated daily. Agency guidelines monitored for changes. Rule validation tests run automatically. Data freshness dashboard shows every source and when it was last updated.'],
]
const PRODUCTS = [
  ['📋', 'Pipeline', 'See what AI found on every loan', "Review findings, take action, move on. AI tells you what's wrong, what's fine, and what to do next — for every loan in your pipeline."],
  ['🔮', 'Simulation', "Ask 'what if' about anything", 'What if we tighten DTI? What if rates rise? Should this loan be approved? Where are our hidden risks? Get answers with AI reasoning, not just numbers.'],
  ['📊', 'Analytics', 'Know your pipeline inside and out', "Who's blocked, what's aging, where risk is concentrating. Team performance, override trends, and portfolio intelligence."],
  ['📑', 'Audit', 'Pull the examiner package in one click', 'Every AI finding, every human action, every override — documented with reasoning. HMDA, fair lending, adverse action. Complete trail.'],
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

function FlowBox({ title }: { title: string }) {
  return (
    <div className="min-w-[150px] flex-1 rounded-lg border border-[#E5E7EB] bg-white p-4 text-center text-sm font-bold text-slate-900">
      {title}
    </div>
  )
}

// "See Accord in action" — renders the recorded demo (DEMO_VIDEO_URL). For a
// self-hosted file it shows a poster + a big click-to-play overlay (no autoplay);
// once started it hands off to the native controls.
function DemoVideo() {
  const url = DEMO_VIDEO_URL.trim()
  const isFile = /\.(mp4|webm)(\?.*)?$/i.test(url)
  const [started, setStarted] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)

  const play = () => {
    videoRef.current?.play()
    setStarted(true)
  }

  let frame: React.ReactNode
  if (!url) {
    frame = (
      <a href={DEMO} className="group flex h-full w-full flex-col items-center justify-center gap-3 bg-slate-900 text-white">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-white/15 text-2xl transition group-hover:scale-110 group-hover:bg-white/25">▶</span>
        <span className="text-sm font-semibold">Product demo</span>
        <span className="text-xs text-white/50">Coming soon — request a live walkthrough</span>
      </a>
    )
  } else if (isFile) {
    frame = (
      <div className="relative h-full w-full">
        <video
          ref={videoRef}
          controls={started}
          playsInline
          preload="metadata"
          poster="/accord_demo_poster.jpg"
          src={url}
          className="h-full w-full bg-black"
          onPlay={() => setStarted(true)}
        />
        {!started && (
          <button
            type="button"
            onClick={play}
            aria-label="Play the demo"
            className="group absolute inset-0 flex flex-col items-center justify-center gap-4 bg-slate-900/45 transition hover:bg-slate-900/30"
          >
            <span className="flex h-20 w-20 items-center justify-center rounded-full bg-white text-3xl text-brand shadow-2xl transition group-hover:scale-110">▶</span>
            <span className="rounded-full bg-black/65 px-5 py-2 text-sm font-semibold text-white">Watch the 90-second demo</span>
          </button>
        )}
      </div>
    )
  } else {
    frame = (
      <iframe
        title="Accord product demo"
        src={url}
        className="h-full w-full"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
        allowFullScreen
      />
    )
  }

  return (
    <section id="demo-video" className="mx-auto max-w-[1200px] scroll-mt-24 px-6 py-16 text-center">
      <Eyebrow>See it in action</Eyebrow>
      <h2 className="text-3xl font-bold tracking-tight text-slate-900">Watch Accord make a decision</h2>
      <p className="mx-auto mt-2 max-w-xl text-[17px] leading-relaxed text-slate-600">
        Ninety seconds, end to end — from a loan landing in the queue to an audited decision.
      </p>
      <div
        id="demo-player"
        className="mx-auto mt-8 aspect-video w-full max-w-4xl scroll-mt-24 overflow-hidden rounded-2xl border border-slate-200 bg-slate-900 shadow-xl"
      >
        {frame}
      </div>
    </section>
  )
}

// ── Interactive (marketing) Simulation section ──────────────────────────────
// Fully static / pre-built data — NO API calls. Multi-select scenarios on the
// left drive dynamic single-scenario simulators or combined-impact summaries on
// the right, each with a code-driven animated preview.
type SimKey = 'dti' | 'rates' | 'debate' | 'health'
type Vote = { n: number; cls: string; label: string }

const SIM_ORDER: SimKey[] = ['dti', 'rates', 'debate', 'health']
const SHORT: Record<SimKey, string> = { dti: 'Policy', rates: 'Stress', debate: 'Debate', health: 'Portfolio' }

const SCENARIOS: Array<{ key: SimKey; title: string; subtitle: string; detail: string; color: string; tint: string }> = [
  { key: 'dti', title: 'What if we tighten DTI to 36%?', subtitle: '3 loans affected · $1.5M volume impact', detail: 'Each borrower: why they’d fail, how to restructure', color: '#0F6E56', tint: 'bg-emerald-50' },
  { key: 'rates', title: 'What if rates rise 200 basis points?', subtitle: '47 loans exceed DTI at new payment amounts', detail: 'Higher monthly payments push borderline borrowers over the limit', color: '#F59E0B', tint: 'bg-amber-50' },
  { key: 'debate', title: 'Should this blocked loan be approved?', subtitle: 'AI agents debate it from every angle', detail: 'Consensus: investigate further, don’t deny yet', color: '#8B5CF6', tint: 'bg-violet-50' },
  { key: 'health', title: 'Where are our hidden portfolio risks?', subtitle: '46% income gaps · 97% one product type', detail: 'Risks no individual file review would catch', color: '#EF4444', tint: 'bg-red-50' },
]

const DTI: Record<string, { affected: string; who: string; reason: string }> = {
  '36%': { affected: '3 loans affected · -$1.5M volume', who: 'Sarah Johnson · $520K · DTI 36.1%', reason: 'Misses the new limit by just 0.1%. Approve with compensating factors or reduce loan by $1K.' },
  '38%': { affected: '2 loans affected · -$950K volume', who: 'Michael Lee · $380K · DTI 38.7%', reason: 'Would need income increase of $862/mo or loan reduction of $27K to qualify.' },
  '40%': { affected: '1 loan affected · -$380K volume', who: 'Emily Davis · $610K · DTI 41.9%', reason: 'Significantly over. Would need major restructure.' },
  '50%': { affected: '0 loans affected — all qualify under relaxed limit', who: '', reason: 'No borrowers affected. All current loans qualify under the relaxed 50% DTI limit.' },
}
const RATE: Record<string, { affected: string; detail: string }> = {
  '+100bps': { affected: '12 loans affected · -$4.8M', detail: 'DTI increases push 12 over limit' },
  '+200bps': { affected: '47 loans affected · -$16.7M', detail: 'Monthly payments up ~$280 avg' },
  '+300bps': { affected: '89 loans affected · -$32.1M', detail: 'Severe stress, 10% of book' },
}
const DEBATE: Record<string, { label: string; consensus: string; votes: Vote[]; insight: string }> = {
  david: {
    label: 'David Park · $400K · Blocked (income)', consensus: 'ESCALATE (7/12)',
    votes: [{ n: 7, cls: 'bg-[#0F6E56]', label: 'escalate' }, { n: 3, cls: 'bg-red-500', label: 'block' }, { n: 1, cls: 'bg-amber-500', label: 'review' }, { n: 1, cls: 'bg-slate-400', label: 'approve' }],
    insight: '3 agents independently flagged income. Credit score masks ability-to-repay risk.',
  },
  mark: {
    label: 'Mark Singh · $490K · Halted (fraud)', consensus: 'BLOCK (9/12)',
    votes: [{ n: 9, cls: 'bg-red-500', label: 'block' }, { n: 2, cls: 'bg-amber-500', label: 'escalate' }, { n: 1, cls: 'bg-slate-400', label: 'review' }],
    insight: 'Federal watchlist match 78%. Mandatory BSA referral.',
  },
  sam: {
    label: 'Sam Patel · $450K · In Review (self-employed)', consensus: 'RECOMMEND (8/12)',
    votes: [{ n: 8, cls: 'bg-amber-500', label: 'recommend' }, { n: 2, cls: 'bg-[#0F6E56]', label: 'approve' }, { n: 2, cls: 'bg-slate-400', label: 'escalate' }],
    insight: 'Self-employed income needs additional verification. Business tax returns support the stated income.',
  },
}
const HEALTH_CRIT = ['5 loans flagged for possible fraud', '5 loans with compound risk (high LTV + high DTI)']
const HEALTH_WARN = ['46% have income documentation gaps', '97% concentration in one product type', 'All rate locks expire the same week', '61% decline rate — policy may be too tight']

const SIM_KEYFRAMES = `
@keyframes accFade{from{opacity:0}to{opacity:1}}
@keyframes accUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes accRight{from{opacity:0;transform:translateX(22px)}to{opacity:1;transform:none}}
@keyframes accPop{0%{opacity:0;transform:scale(.8)}60%{transform:scale(1.06)}100%{opacity:1;transform:scale(1)}}
@keyframes accFill{from{width:0}to{width:100%}}
.acc-fade2{animation:accFade .22s ease both}
.acc-up{animation:accUp .4s ease both}
.acc-right{animation:accRight .45s ease both}
.acc-pop{animation:accPop .4s ease both}
.acc-bar{animation:accFill 1.6s ease-out both}
`

function VoteBar({ votes }: { votes: Vote[] }) {
  const total = votes.reduce((s, v) => s + v.n, 0) || 12
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
        {votes.map((v, i) => <div key={i} className={v.cls} style={{ width: `${(v.n / total) * 100}%` }} />)}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
        {votes.map((v, i) => (
          <span key={i} className="flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${v.cls}`} />{v.n} {v.label}</span>
        ))}
      </div>
    </div>
  )
}

function SimDropdown({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: Array<[string, string]> }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    >
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

function SimHead({ title, subtitle }: { title: string; subtitle: string }) {
  return <div className="mb-3"><div className="text-sm font-bold text-slate-900">{title}</div><div className="text-xs text-slate-500">{subtitle}</div></div>
}

// Code-driven animated walkthrough (replaces video clips). Play → timed reveal.
function AnimatedPreview(props: {
  kind: 'policy' | 'debate' | 'health'
  result?: string
  reason?: string
  votes?: Vote[]
  consensus?: string
  insight?: string
  findings?: Array<{ icon: string; text: string }>
}) {
  const { kind } = props
  const [phase, setPhase] = useState<'idle' | 'playing' | 'done'>('idle')
  const [run, setRun] = useState(0)
  const [typed, setTyped] = useState('')
  const [scan, setScan] = useState('')
  const timers = useRef<number[]>([])
  const clear = () => { timers.current.forEach((t) => { clearTimeout(t); clearInterval(t) }); timers.current = [] }
  useEffect(() => () => clear(), [])

  const start = () => {
    clear()
    setTyped('')
    setRun((r) => r + 1)
    setPhase('playing')
    setScan(kind === 'policy' ? 'Evaluating 8,896 loans…' : kind === 'debate' ? 'AI agents evaluating…' : 'Scanning portfolio…')
    if (kind === 'policy') {
      timers.current.push(window.setTimeout(() => setScan('3,558 evaluated…'), 800))
      timers.current.push(window.setTimeout(() => setScan('Analysis complete ✓'), 1600))
      if (props.reason) {
        timers.current.push(window.setTimeout(() => {
          let i = 0
          const iv = window.setInterval(() => {
            i += 1
            setTyped(props.reason!.slice(0, i))
            if (i >= props.reason!.length) clearInterval(iv)
          }, 20)
          timers.current.push(iv)
        }, 2400))
      }
    }
    const total = kind === 'policy' ? 5200 : kind === 'health' ? 4200 : 3600
    timers.current.push(window.setTimeout(() => setPhase('done'), total))
  }

  if (phase === 'idle') {
    return (
      <div className="mt-4 flex min-h-[110px] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white">
        <button type="button" onClick={start} className="group flex flex-col items-center gap-2 py-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand text-lg text-white shadow-md transition group-hover:scale-110">▶</span>
          <span className="text-sm font-semibold text-slate-600">See how this looks in Accord</span>
        </button>
      </div>
    )
  }

  return (
    <div key={run} className="acc-fade2 mt-4 min-h-[200px] rounded-xl border border-slate-200 bg-white p-4">
      {kind === 'policy' && (
        <div className="space-y-3">
          <div className="acc-fade2">
            <div className="text-xs text-slate-500">{scan}</div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100"><div className="acc-bar h-full rounded-full bg-brand" /></div>
          </div>
          <div className="acc-up rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-slate-900" style={{ animationDelay: '1.9s' }}>{props.result}</div>
          <div className="acc-right rounded-lg border border-slate-200 p-3 text-xs text-slate-600" style={{ animationDelay: '2.4s' }}>
            {typed}<span className="animate-pulse text-slate-400">▌</span>
          </div>
        </div>
      )}
      {kind === 'debate' && (
        <div className="space-y-3">
          <div className="acc-fade2 text-xs text-slate-500">{scan}</div>
          <div className="flex gap-1">
            {Array.from({ length: 12 }).map((_, i) => (
              <span key={i} className="acc-pop h-3 w-3 rounded-full bg-slate-300" style={{ animationDelay: `${i * 0.07}s` }} />
            ))}
          </div>
          <div className="acc-up" style={{ animationDelay: '1.5s' }}><VoteBar votes={props.votes!} /></div>
          <div className="acc-up rounded-lg bg-slate-50 p-2 text-sm font-bold text-slate-900" style={{ animationDelay: '2.2s' }}>Consensus: {props.consensus}</div>
          <div className="acc-up text-xs italic text-slate-500" style={{ animationDelay: '2.8s' }}>{props.insight}</div>
        </div>
      )}
      {kind === 'health' && (
        <div className="space-y-2">
          <div className="acc-fade2">
            <div className="text-xs text-slate-500">{scan}</div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100"><div className="acc-bar h-full rounded-full bg-red-400" /></div>
          </div>
          {props.findings!.map((f, i) => (
            <div key={i} className="acc-up flex items-center gap-2 rounded-lg border border-slate-200 p-2 text-xs text-slate-700" style={{ animationDelay: `${1.8 + i * 0.45}s` }}>
              <span>{f.icon}</span><span>{f.text}</span>
            </div>
          ))}
        </div>
      )}
      {phase === 'done' && (
        <button type="button" onClick={start} className="mt-3 text-xs font-semibold text-brand hover:underline">↻ Replay</button>
      )}
    </div>
  )
}

function DtiSim() {
  const [pct, setPct] = useState('36%')
  const r = DTI[pct]
  return (
    <div>
      <SimHead title="Policy Simulator — DTI Limit" subtitle="Current threshold: 43%" />
      <SimDropdown value={pct} onChange={setPct} options={[['36%', '36% (tighten)'], ['38%', '38%'], ['40%', '40%'], ['50%', '50% (relax)']]} />
      <div key={pct} className="acc-fade2 mt-3 rounded-lg bg-emerald-50 p-3 text-sm">
        <div className="font-semibold text-slate-900">{r.affected}</div>
        <div className="mt-1 text-xs leading-relaxed text-slate-600">{r.who && <span className="font-medium text-slate-700">{r.who} — </span>}{r.reason}</div>
      </div>
      <AnimatedPreview key={pct} kind="policy" result={r.affected} reason={r.reason} />
    </div>
  )
}

function RateSim() {
  const [bps, setBps] = useState('+200bps')
  const r = RATE[bps]
  return (
    <div>
      <SimHead title="Stress Test — Interest Rate Increase" subtitle="Current average rate: 6.5%" />
      <SimDropdown value={bps} onChange={setBps} options={[['+100bps', '+100bps (+1.0%)'], ['+200bps', '+200bps (+2.0%)'], ['+300bps', '+300bps (+3.0%)']]} />
      <div key={bps} className="acc-fade2 mt-3 rounded-lg bg-amber-50 p-3 text-sm">
        <div className="font-semibold text-slate-900">{r.affected}</div>
        <div className="mt-1 text-xs text-slate-600">{r.detail}</div>
      </div>
      <AnimatedPreview key={bps} kind="policy" result={r.affected} reason={r.detail} />
    </div>
  )
}

function DebateSim() {
  const [who, setWho] = useState('david')
  const d = DEBATE[who]
  return (
    <div>
      <SimHead title="AI Loan Debate" subtitle="Pick a loan. Watch AI agents deliberate." />
      <SimDropdown value={who} onChange={setWho} options={[['david', DEBATE.david.label], ['mark', DEBATE.mark.label], ['sam', DEBATE.sam.label]]} />
      <div key={who} className="acc-fade2 mt-3 space-y-3 rounded-lg bg-violet-50 p-3">
        <div className="text-sm font-bold text-slate-900">{d.consensus}</div>
        <VoteBar votes={d.votes} />
        <div className="text-xs italic text-slate-600">{d.insight}</div>
      </div>
      <AnimatedPreview key={who} kind="debate" votes={d.votes} consensus={d.consensus} insight={d.insight} />
    </div>
  )
}

function HealthSim() {
  return (
    <div>
      <SimHead title="Portfolio Health Check" subtitle="AI scans every loan for hidden risks" />
      <div className="space-y-3 rounded-lg bg-red-50 p-3">
        <div>
          <div className="text-sm font-bold text-red-700">🔴 2 critical findings</div>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">{HEALTH_CRIT.map((f) => <li key={f}>• {f}</li>)}</ul>
        </div>
        <div>
          <div className="text-sm font-bold text-amber-600">🟡 4 warnings</div>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">{HEALTH_WARN.map((f) => <li key={f}>• {f}</li>)}</ul>
        </div>
        <div className="text-xs text-slate-400">ℹ️ + 5 more informational findings</div>
      </div>
      <AnimatedPreview
        kind="health"
        findings={[
          { icon: '🔴', text: HEALTH_CRIT[0] }, { icon: '🔴', text: HEALTH_CRIT[1] },
          { icon: '🟡', text: HEALTH_WARN[0] }, { icon: '🟡', text: HEALTH_WARN[1] },
        ]}
      />
    </div>
  )
}

function SingleSim({ k }: { k: SimKey }) {
  if (k === 'dti') return <DtiSim />
  if (k === 'rates') return <RateSim />
  if (k === 'debate') return <DebateSim />
  return <HealthSim />
}

function CombinedResults({ checked }: { checked: Set<SimKey> }) {
  const has = (k: SimKey) => checked.has(k)
  const all4 = checked.size === 4

  let body: React.ReactNode
  if (all4) {
    body = (
      <div className="space-y-3">
        <div className="text-sm font-bold text-slate-900">Full Analysis: Policy + Stress + Portfolio + Loan Debate</div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {[['47', 'loans affected by policy + stress'], ['11', 'portfolio risks identified'], ['AI', 'debate provides loan-level reasoning'], ['$18.2M', 'total volume impact']].map(([a, b]) => (
            <div key={b} className="rounded-lg border border-slate-200 bg-white p-3"><div className="text-base font-bold text-brand">{a}</div><div className="text-slate-500">{b}</div></div>
          ))}
        </div>
        <p className="text-xs leading-relaxed text-slate-600">This is the power of Accord — not just one test, but cascading, multi-dimensional analysis across your entire book. No spreadsheet can do this.</p>
      </div>
    )
  } else if (has('debate')) {
    body = (
      <div className="space-y-2">
        <div className="text-sm font-bold text-slate-900">Loan debate + portfolio analysis</div>
        <p className="text-xs leading-relaxed text-slate-600">AI Debate analyzes individual loans while Policy and Stress tests analyze the portfolio. Run both to get the complete picture — loan-level reasoning plus portfolio-level impact.</p>
      </div>
    )
  } else if (has('dti') && has('rates') && has('health')) {
    body = (
      <div className="space-y-2">
        <div className="text-sm font-bold text-slate-900">Comprehensive stress analysis</div>
        <p className="text-xs leading-relaxed text-slate-600">47 loans fail from policy + rate changes. 11 portfolio risks compound the picture. Total exposure: <span className="font-semibold text-slate-800">$18.2M</span> in direct impact plus systemic concentration risks.</p>
      </div>
    )
  } else if (has('dti') && has('rates')) {
    body = (
      <div className="space-y-3">
        <div className="text-sm font-bold text-slate-900">DTI 36% + Rate shock +200bps</div>
        <div className="overflow-hidden rounded-lg border border-slate-200 text-xs">
          <div className="bg-slate-50 px-3 py-1.5 font-semibold text-slate-500">Individual impact</div>
          <div className="flex justify-between px-3 py-1.5"><span className="text-slate-600">DTI alone</span><span className="font-medium text-slate-800">3 loans · -$1.5M</span></div>
          <div className="flex justify-between px-3 py-1.5"><span className="text-slate-600">Rates alone</span><span className="font-medium text-slate-800">44 loans · -$16.7M</span></div>
          <div className="bg-emerald-50 px-3 py-1.5 font-semibold text-brand-dark">Combined impact</div>
          <div className="flex justify-between px-3 py-1.5"><span className="text-slate-600">Together</span><span className="font-bold text-slate-900">47 loans · -$18.2M</span></div>
          <div className="flex justify-between px-3 py-1.5"><span className="text-slate-600">Approval rate</span><span className="font-medium text-slate-800">31% → 26%</span></div>
        </div>
        <p className="text-xs leading-relaxed text-slate-600">When multiple changes combine, the impact compounds. Higher rates push monthly payments up, which pushes DTI ratios up, which means more borrowers fail the tighter 36% limit.</p>
      </div>
    )
  } else if (has('dti') && has('health')) {
    body = (
      <div className="space-y-2">
        <div className="text-sm font-bold text-slate-900">Policy change + Portfolio scan</div>
        <p className="text-xs leading-relaxed text-slate-600">3 loans fail under new DTI rule. Separately, portfolio has 11 systemic risks. Combined view: tightening DTI while 46% have income gaps may trigger additional fallout.</p>
      </div>
    )
  } else {
    body = (
      <div className="space-y-2">
        <div className="text-sm font-bold text-slate-900">Rate stress + Portfolio risks</div>
        <p className="text-xs leading-relaxed text-slate-600">47 loans fail under rate shock. Portfolio already has concentration risks. Combined: rate-sensitive sectors (real estate, construction) are also the highest LTV borrowers.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-1 text-sm font-bold text-slate-900">Combined Scenario Analysis</div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-[11px] font-medium text-slate-500">
        {SIM_ORDER.filter((k) => has(k)).map((k) => {
          const sc = SCENARIOS.find((s) => s.key === k)!
          return <span key={k} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: sc.color }} />{SHORT[k]}</span>
        })}
      </div>
      {body}
    </div>
  )
}

function ScenarioCard({ sc, checked, onToggle }: { sc: (typeof SCENARIOS)[number]; checked: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={checked}
      className={`flex w-full items-start gap-3 rounded-xl border border-l-4 p-4 text-left transition-all duration-200 ${checked ? sc.tint : 'bg-white opacity-80 hover:opacity-100'}`}
      style={{ borderLeftColor: checked ? sc.color : '#E5E7EB' }}
    >
      <span
        className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded border-2 text-xs leading-none text-white transition"
        style={checked ? { backgroundColor: sc.color, borderColor: sc.color } : { borderColor: '#CBD5E1' }}
      >
        {checked ? '✓' : ''}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-bold text-slate-900">{sc.title}</span>
        <span className="mt-0.5 block text-xs font-semibold" style={{ color: checked ? sc.color : '#6B7280' }}>{sc.subtitle}</span>
        <span className="mt-1 block text-[11px] italic text-slate-400">{sc.detail}</span>
      </span>
    </button>
  )
}

function SimulationSection() {
  const [checked, setChecked] = useState<Set<SimKey>>(new Set<SimKey>(['dti']))
  const toggle = (k: SimKey) =>
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })
  const sig = SIM_ORDER.filter((k) => checked.has(k)).join('+')
  const only = SIM_ORDER.filter((k) => checked.has(k))

  return (
    <div>
      <style>{SIM_KEYFRAMES}</style>
      <div className="grid gap-6 md:grid-cols-[2fr_3fr]">
        {/* LEFT — multi-select scenarios */}
        <div className="space-y-3">
          {SCENARIOS.map((sc) => (
            <ScenarioCard key={sc.key} sc={sc} checked={checked.has(sc.key)} onToggle={() => toggle(sc.key)} />
          ))}
        </div>

        {/* RIGHT — dynamic results */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 md:p-6">
          <div key={sig} className="acc-fade2">
            {checked.size === 0 && (
              <div className="flex min-h-[200px] items-center justify-center text-center text-sm text-slate-400">
                Select one or more scenarios to see the analysis.
              </div>
            )}
            {checked.size === 1 && <SingleSim k={only[0]} />}
            {checked.size >= 2 && <CombinedResults checked={checked} />}
          </div>
        </div>
      </div>

      {/* BOTTOM CTA */}
      <div className="mt-10 text-center">
        <p className="text-sm text-slate-500">✦ These results are from a real portfolio of 8,896 loans.</p>
        <div className="mt-4 flex flex-wrap justify-center gap-3">
          <a href={DEMO} className="rounded-lg bg-brand px-6 py-3 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo →</a>
          <a href="mailto:demo@useaccord.com?subject=Accord%20free%20trial" className="rounded-lg border border-brand px-6 py-3 text-sm font-semibold text-brand hover:bg-brand-light/40">Start free trial →</a>
        </div>
        <p className="mt-2 text-xs text-slate-400">14-day free trial. No credit card required.</p>
      </div>
    </div>
  )
}

export default function Landing({ scrollTo }: { scrollTo?: string }) {
  const [bannerOpen, setBannerOpen] = useState(true)
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [productsOpen, setProductsOpen] = useState(false)
  const navRef = useRef<HTMLDivElement>(null)

  // /pricing (and similar) lands on the section instead of the top.
  useEffect(() => {
    if (scrollTo) {
      const id = setTimeout(() => document.getElementById(scrollTo)?.scrollIntoView({ behavior: 'smooth' }), 100)
      return () => clearTimeout(id)
    }
  }, [scrollTo])

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
          <a href="#top" onClick={() => setProductsOpen(false)} className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight">accord</span>
          </a>
          <nav className="ml-8 hidden items-center gap-6 text-sm font-medium text-slate-600 md:flex">
            <button onClick={() => setProductsOpen((v) => !v)} className={`flex items-center gap-1 hover:text-slate-900 ${productsOpen ? 'text-slate-900' : ''}`}>Products ▾</button>
            <a href="#pricing" onClick={() => setProductsOpen(false)} className="hover:text-slate-900">Pricing</a>
            <a href="#faq" onClick={() => setProductsOpen(false)} className="hover:text-slate-900">Docs</a>
            <a href="#who" onClick={() => setProductsOpen(false)} className="hover:text-slate-900">Company ▾</a>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <Link to="/login" onClick={() => setProductsOpen(false)} className="text-sm font-medium text-slate-600 hover:text-slate-900">Log in</Link>
            <a href={DEMO} onClick={() => setProductsOpen(false)} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo</a>
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
              Accord works like your best underwriter — reviewing every file the same way, every time.
              Your team reviews the findings and makes the call.
            </p>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-[#6B7280]">
              <Link to="/security" className="hover:text-slate-900">🔒 Enterprise security</Link>
              <Link to="/security#soc2" className="hover:text-slate-900">🏛️ SOC 2 ready</Link>
              <Link to="/compliance" className="hover:text-slate-900">⚖️ Compliant by design</Link>
            </div>
            <div className="mt-9 flex flex-wrap gap-3">
              <a href={DEMO} className="rounded-lg bg-brand px-7 py-3 text-sm font-semibold text-white hover:bg-brand-dark">Request a demo →</a>
              <button
                type="button"
                onClick={() => document.getElementById('demo-player')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                className="rounded-lg border border-[#D1D5DB] px-7 py-3 text-sm font-semibold text-[#374151] hover:bg-slate-50"
              >See it in action ▷</button>
            </div>
          </div>
          <div className="flex justify-center lg:justify-end"><EvaluationCard /></div>
        </section>

        {/* 3b — Stats */}
        <section className="py-12" style={{ background: '#F9FAFB' }}>
          <div className="mx-auto grid max-w-[1000px] gap-8 px-6 text-center sm:grid-cols-3">
            {STATS.map(([big, label, sub]) => (
              <div key={label}>
                <div className="text-[56px] font-extrabold leading-none text-brand">{big}</div>
                <div className="mt-2 text-base font-bold text-[#111]">{label}</div>
                <div className="mt-1 text-[13px] text-[#6B7280]">{sub}</div>
              </div>
            ))}
          </div>
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

        {/* 4b — Demo video */}
        <DemoVideo />

        {/* 5 — How it works (4 one-word steps) */}
        <section id="how-it-works" className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>How it works</Eyebrow>
            <h2 className="text-[28px] font-bold tracking-tight">From file to decision in four steps</h2>
          </div>
          <div className="mt-12 flex flex-col items-stretch gap-2 md:flex-row md:items-start">
            {STEPS4.map(([num, title, desc], i) => (
              <Fragment key={num}>
                <div className="flex flex-1 flex-col items-center text-center">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full border border-slate-300 text-xs font-semibold text-slate-400">{num}</div>
                  <div className="mt-3 text-[28px] font-extrabold tracking-tight text-brand">{title}</div>
                  <p className="mx-auto mt-2 max-w-[200px] text-sm leading-relaxed text-[#6B7280]">{desc}</p>
                </div>
                {i < STEPS4.length - 1 && (
                  <div className="flex shrink-0 items-center justify-center self-center text-2xl text-[#D1D5DB] md:self-start md:pt-9">
                    <span className="hidden md:inline">→</span><span className="md:hidden">↓</span>
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        </section>

        {/* 5b — Flow diagram (U-shape) */}
        <section className="mx-auto max-w-[840px] px-6 pb-6">
          <div className="space-y-2">
            <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
              <FlowBox title="Borrower applies" />
              <span className="self-center text-xl text-brand"><span className="hidden md:inline">→</span><span className="md:hidden">↓</span></span>
              <FlowBox title="Documents uploaded" />
              <span className="self-center text-xl text-brand"><span className="hidden md:inline">→</span><span className="md:hidden">↓</span></span>
              <FlowBox title="AI evaluates every aspect" />
            </div>
            <div className="flex justify-center text-xl text-brand md:justify-end md:pr-[12%]">↓</div>
            <div className="flex flex-col items-stretch gap-2 md:flex-row-reverse md:items-center">
              <FlowBox title="Recommendation with evidence" />
              <span className="self-center text-xl text-brand"><span className="hidden md:inline">←</span><span className="md:hidden">↓</span></span>
              <FlowBox title="Underwriter decides" />
              <span className="self-center text-xl text-brand"><span className="hidden md:inline">←</span><span className="md:hidden">↓</span></span>
              <FlowBox title="Audit trail documented" />
            </div>
          </div>
          <p className="mt-6 text-center text-sm italic text-[#6B7280]">
            Every step creates an immutable record. What the AI found. What the human decided. Why.
          </p>
        </section>

        {/* 5c — No new systems callout */}
        <div className="mx-auto my-8 max-w-[600px] border-y border-[#E5E7EB] px-6 py-8 text-center">
          <div className="text-[20px] font-semibold tracking-wide text-[#374151]">No new apps.&nbsp;&nbsp;No new portals.&nbsp;&nbsp;No new logins.</div>
          <div className="mt-2 text-base text-[#6B7280]">Accord works alongside your LOS. Your team keeps using Encompass.</div>
        </div>

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
          <div className="mt-12">
            <SimulationSection />
          </div>
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
            <h2 className="text-[28px] font-bold tracking-tight">Built for everyone the loan touches</h2>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {STAKEHOLDERS.map(([icon, who, head, body]) => (
              <div key={who} className="rounded-xl border border-slate-200 bg-slate-50 p-6">
                <div className="text-[28px]">{icon}</div>
                <div className="mt-2 text-lg font-bold text-slate-900">{who}</div>
                <h3 className="mt-1 font-semibold text-brand-dark">{head}</h3>
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

        {/* 10b — Compliance built in */}
        <section className="mx-auto max-w-[1200px] px-6 py-20">
          <div className="text-center">
            <Eyebrow>Compliance</Eyebrow>
            <h2 className="mx-auto max-w-2xl text-[28px] font-bold tracking-tight">Regulatory compliance isn’t a feature. It’s the foundation.</h2>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {COMPLIANCE.map(([icon, title, body]) => (
              <div key={title} className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-light text-xl">{icon}</span>
                  <div className="text-lg font-semibold text-slate-900">{title}</div>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-[#6B7280]">{body}</p>
              </div>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-[#9CA3AF]">Built for HMDA · ECOA · TRID · Fair Lending · BSA/AML</p>
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
