import { useEffect, useRef, useState } from 'react'
import { BRAND } from './brand'

// ── Data ──────────────────────────────────────────────────────────────────
const LOANS = [
  {
    id: 0,
    name: 'Daniel Reyes',
    amount: '$418K',
    product: 'Conforming',
    dotColor: '#e24b4a',
    urgency: 'Urgent',
    urgencyCls: 'bg-red-50 text-red-700',
    finding: 'Fraud blocked',
    findingSub: '— score 0.79 · ID verification failed',
    sla: '9d over SLA',
    badge: 'Blocked',
    badgeCls: 'bg-red-50 text-red-700',
    decision: {
      waves: [
        { name: 'Identity',    color: '#e24b4a' },
        { name: 'Credit',      color: '#639922' },
        { name: 'Income',      color: '#639922' },
        { name: 'DTI',         color: '#ba7517' },
        { name: 'Property',    color: '#639922' },
        { name: 'Compliance',  color: '#639922' },
      ],
      aiText: 'Blocked — fraud score 0.79 exceeds the 0.75 threshold. BSA referral mandatory. Identity match 0.0%, watchlist hit detected, device signals inconsistent.',
      signals: [
        { key: 'Fraud score',    val: '0.79',  bad: true  },
        { key: 'Identity match', val: '0.0%',  bad: true  },
        { key: 'Watchlist',      val: 'Hit',   bad: true  },
        { key: 'Credit score',   val: '724',   bad: false },
        { key: 'LTV',            val: '84.2%', bad: false },
        { key: 'DTI back',       val: '38.4%', bad: false },
      ],
    },
    rules: [
      { layer: 'Federal',      title: 'High fraud risk — mandatory BSA/SAR review',         cite: 'BSA/AML 31 CFR §1010 · Rule v3 · active 5/1/2026' },
      { layer: 'Agency',       title: 'HMDA data complete — no fair-lending flags',          cite: 'HMDA Reg C 12 CFR §1003 / ECOA Reg B' },
      { layer: 'Your policy',  title: 'Min credit score 680 — Summit overlay applied',       cite: 'Summit Home Loans · overlay v4 · active 3/15/2026' },
    ],
    evidence: [
      { name: 'OFAC Check',          sub: 'List Date 2026-06-12 · Pep Match: No', conf: '99%' },
      { name: 'URLA 1003',           sub: 'Loan amount $418,000 · purchase',       conf: '94%' },
      { name: 'W2 2025',             sub: 'Box1 wages $87,400 · employer verified', conf: '97%' },
      { name: 'Purchase Agreement',  sub: '$496,000 · 1423 Elm St',                conf: '94%' },
    ],
    audit: [
      { time: '6/28 · 9:14 AM',  main: '14 documents received · auto-classified',       sub: '14 personas queued · Wave 1 started' },
      { time: '6/28 · 9:14 AM',  main: 'Identity blocked — fraud score 0.79',           sub: 'Mode: auto_execute · system · Rule v3 · conf 90%' },
      { time: '6/28 · 9:15 AM',  main: 'BSA/AML referral filed',                        sub: '31 CFR §1010 · mandatory above 0.75' },
      { time: '6/28 · 11:02 AM', main: 'James reviewed · escalated to senior UW',       sub: 'Mode: human_approval · Rule v3 pinned · model v2 pinned' },
    ],
  },
  {
    id: 1,
    name: 'Priya Sharma',
    amount: '$354K',
    product: 'FHA',
    dotColor: '#ba7517',
    urgency: 'Review',
    urgencyCls: 'bg-amber-50 text-amber-700',
    finding: 'DTI escalated',
    findingSub: '— 47.2% · compensating factors detected',
    sla: '3d over SLA',
    badge: 'Escalated',
    badgeCls: 'bg-amber-50 text-amber-700',
    decision: {
      waves: [
        { name: 'Identity',   color: '#639922' },
        { name: 'Credit',     color: '#639922' },
        { name: 'Income',     color: '#639922' },
        { name: 'DTI',        color: '#ba7517' },
        { name: 'Property',   color: '#639922' },
        { name: 'Compliance', color: '#639922' },
      ],
      aiText: 'Escalated — DTI 47.2% exceeds FHA guideline of 43%. Compensating factors detected: credit score 760 and 18% reserves may support exception. Senior UW review required.',
      signals: [
        { key: 'DTI back',       val: '47.2%', bad: true  },
        { key: 'FHA guideline',  val: '43%',   bad: true  },
        { key: 'Credit score',   val: '760',   bad: false },
        { key: 'Reserves',       val: '18%',   bad: false },
        { key: 'LTV',            val: '96.5%', bad: false },
        { key: 'Income conf',    val: '0.97',  bad: false },
      ],
    },
    rules: [
      { layer: 'Federal',     title: 'ATR — ability to repay documented',                  cite: '12 CFR 1026.43 · CFPB · Rule v3' },
      { layer: 'Agency',      title: 'FHA DTI guideline 43% — escalate above',             cite: 'FHA HUD 4000.1 · AUS approved with conditions' },
      { layer: 'Your policy', title: 'Exception requires senior UW approval above 45%',    cite: 'Summit Home Loans · overlay v4 · active 3/15/2026' },
    ],
    evidence: [
      { name: 'W2 2025',         sub: 'Box1 wages $62,400 · ADP payroll',          conf: '97%' },
      { name: 'Paystub Current', sub: 'Gross pay $5,200/mo · YTD $31,200',         conf: '95%' },
      { name: 'Bank Statement',  sub: 'Ending balance $18,400 · 60-day seasoned',  conf: '93%' },
      { name: 'DU Findings',     sub: 'Approve/Eligible · conditions attached',    conf: '99%' },
    ],
    audit: [
      { time: '6/27 · 2:11 PM',  main: '11 documents received · auto-classified',     sub: '14 personas queued · Wave 1 started' },
      { time: '6/27 · 2:12 PM',  main: 'DTI escalated — 47.2% exceeds guideline',     sub: 'Mode: auto_execute · Rule v3 · conf 60%' },
      { time: '6/27 · 2:12 PM',  main: 'Compensating factors detected',               sub: 'Credit 760 + reserves 18% — exception eligible' },
      { time: '6/28 · 9:30 AM',  main: 'James reviewed · awaiting senior UW',         sub: 'Mode: human_approval · Rule v3 pinned' },
    ],
  },
  {
    id: 2,
    name: 'Marcus Webb',
    amount: '$292K',
    product: 'VA',
    dotColor: '#ba7517',
    urgency: 'Review',
    urgencyCls: 'bg-amber-50 text-amber-700',
    finding: 'Employment gap',
    findingSub: '— 290 days · prior employer unconfirmed',
    sla: '1d over SLA',
    badge: 'Review',
    badgeCls: 'bg-amber-50 text-amber-700',
    decision: {
      waves: [
        { name: 'Identity',   color: '#639922' },
        { name: 'Credit',     color: '#639922' },
        { name: 'Income',     color: '#ba7517' },
        { name: 'DTI',        color: '#639922' },
        { name: 'Property',   color: '#639922' },
        { name: 'Compliance', color: '#639922' },
      ],
      aiText: 'Escalated — 290-day employment gap detected. Prior employer unconfirmed. VA guidelines require 2-year employment history or documented reason for gap. VOE from current employer needed.',
      signals: [
        { key: 'Employment gap', val: '290d',  bad: true  },
        { key: 'Prior employer', val: 'Unconf', bad: true },
        { key: 'Credit score',   val: '742',   bad: false },
        { key: 'VA entitlement', val: 'Full',  bad: false },
        { key: 'LTV',            val: '89.1%', bad: false },
        { key: 'DTI back',       val: '36.2%', bad: false },
      ],
    },
    rules: [
      { layer: 'Federal',     title: 'ATR — 2-year employment history required',         cite: '12 CFR 1026.43 · CFPB · Rule v3' },
      { layer: 'Agency',      title: 'VA — gap >30 days requires written explanation',   cite: 'VA Lenders Handbook Ch 4 · Fannie B3-3.1-09' },
      { layer: 'Your policy', title: 'Request VOE before underwriting decision',         cite: 'Summit Home Loans · overlay v4 · active 3/15/2026' },
    ],
    evidence: [
      { name: 'URLA 1003',       sub: 'Current employer: Vertex Corp · 8 months',   conf: '94%' },
      { name: 'W2 2024',         sub: 'Box1 wages $54,000 · prior employer',         conf: '97%' },
      { name: 'VA Certificate',  sub: 'Full entitlement · no prior use',             conf: '99%' },
      { name: 'Credit Report',   sub: 'Mid score 742 · 0 derogatory · 2 inquiries', conf: '96%' },
    ],
    audit: [
      { time: '6/26 · 4:05 PM',  main: '9 documents received · auto-classified',       sub: '14 personas queued · Wave 1 started' },
      { time: '6/26 · 4:06 PM',  main: 'Employment gap flagged — 290 days',            sub: 'Mode: auto_execute · system · Rule v3 · conf 85%' },
      { time: '6/26 · 4:06 PM',  main: 'VOE condition generated',                      sub: 'Request verification of employment — current employer' },
      { time: '6/28 · 8:45 AM',  main: 'James reviewed · VOE requested from borrower', sub: 'Mode: human_approval · Rule v3 pinned' },
    ],
  },
]

const TABS = ['Decision', 'Rules', 'Evidence', 'Audit']

const LAYER_STYLES: Record<string, string> = {
  Federal:      'bg-red-50 text-red-700',
  Agency:       'bg-amber-50 text-amber-700',
  'Your policy':'bg-green-50 text-green-700',
}

// ── Component ─────────────────────────────────────────────────────────────
export default function HeroSection() {
  const [activeLoan, setActiveLoan] = useState(0)
  const [activeTab,  setActiveTab]  = useState(0)
  const [seeActive,  setSeeActive]  = useState(false)
  const tabTimer  = useRef<ReturnType<typeof setInterval> | null>(null)
  const loanTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  const loan = LOANS[activeLoan]

  function pickLoan(n: number) {
    setActiveLoan(n)
    setActiveTab(0)
    resetLoanTimer(n)
    resetTabTimer(0)
  }

  function pickTab(n: number) {
    setActiveTab(n)
    resetTabTimer(n)
  }

  function resetTabTimer(start: number) {
    if (tabTimer.current) clearInterval(tabTimer.current)
    let cur = start
    tabTimer.current = setInterval(() => {
      cur = (cur + 1) % 4
      setActiveTab(cur)
    }, 2800)
  }

  function resetLoanTimer(start: number) {
    if (loanTimer.current) clearInterval(loanTimer.current)
    let cur = start
    loanTimer.current = setInterval(() => {
      cur = (cur + 1) % 3
      setActiveLoan(cur)
      setActiveTab(0)
    }, 13000)
  }

  useEffect(() => {
    resetTabTimer(0)
    resetLoanTimer(0)
    return () => {
      if (tabTimer.current)  clearInterval(tabTimer.current)
      if (loanTimer.current) clearInterval(loanTimer.current)
    }
  }, [])

  return (
    <section className="mx-auto grid max-w-[1200px] items-center gap-12 px-6 pb-12 pt-16 lg:grid-cols-[52fr_48fr]">

      {/* ── Left: copy ── */}
      <div>
        <div
          className="mb-4 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
          style={{ backgroundColor: BRAND.offwhite, color: BRAND.dark }}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-green-600 inline-block" />
          Built for community banks and independent mortgage lenders
        </div>

        <h1
          className="text-[42px] font-bold leading-[1.1] tracking-[-0.03em] mb-4"
          style={{ color: BRAND.nearblack }}
        >
          Every underwriting decision —{' '}
          <span style={{ color: BRAND.dark }}>explained, cited, defensible.</span>
        </h1>

        <p className="text-lg text-slate-500 leading-relaxed mb-8 max-w-lg">
          Accord gives underwriters the best tool to review every file the same way,
          every time. Every decision explained. Every judgment documented. Every file
          exam-ready.
        </p>

        <div className="flex flex-wrap gap-3 mb-6">
          <button
            className="rounded-lg px-5 py-2.5 text-sm font-semibold text-white"
            style={{ backgroundColor: BRAND.dark }}
          >
            Request a demo
          </button>
          <button
            className="rounded-lg border px-5 py-2.5 text-sm font-semibold flex items-center gap-2 transition-colors duration-150"
            style={{
              borderColor: seeActive ? BRAND.dark : '#e2e8f0',
              backgroundColor: seeActive ? BRAND.dark : 'white',
              color: seeActive ? 'white' : '#334155',
            }}
            onClick={() => {
              setSeeActive(true)
              document.getElementById('video')?.scrollIntoView({ behavior: 'smooth' })
              setTimeout(() => setSeeActive(false), 1500)
            }}
          >
            <span style={{ width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: `8px solid ${seeActive ? 'white' : 'currentColor'}`, display: 'inline-block' }} />
            See it in action
          </button>
        </div>

        <div className="flex flex-wrap gap-4 text-xs text-slate-400">
          <span>🔒 Enterprise security</span>
          <span>📋 SOC 2-ready</span>
          <span>⚖️ HMDA & fair lending built in</span>
          <span>🛡️ Compliant by design</span>
        </div>
      </div>

      {/* ── Right: animated workbench ── */}
      <div
        className="rounded-xl overflow-hidden border text-left"
        style={{ borderColor: 'rgba(0,0,0,0.1)' }}
      >
        {/* nav bar */}
        <div className="flex items-center gap-1.5 px-3 py-2 border-b" style={{ backgroundColor: '#0c1710', borderColor: '#1e3020' }}>
          <span className="w-2.5 h-2.5 rounded-full bg-red-400" />
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
          <span className="w-2.5 h-2.5 rounded-full bg-green-400" />
          <span className="ml-1.5 text-[11px] font-semibold" style={{ color: '#5aa87a', letterSpacing: '0.04em' }}>
            accord · pipeline
          </span>
          <span className="ml-auto text-[10px]" style={{ color: '#3d6b4f' }}>Summit Home Loans</span>
        </div>

        {/* two-column body */}
        <div className="grid bg-white" style={{ gridTemplateColumns: '175px 1fr' }}>

          {/* ── Queue rail (left) ── */}
          <div className="border-r border-slate-100 flex flex-col">
            <div className="px-2.5 py-2 border-b border-slate-100">
              <p className="text-[11px] font-semibold text-slate-700 mb-0.5">Good morning, James</p>
              <p className="text-[9px] text-slate-400">Underwriter · 3 need action</p>
            </div>

            {/* stats */}
            <div className="flex border-b border-slate-100">
              {[['3','Action','#e24b4a'],['2','Pending','#ba7517'],['7','Done','#3b6d11']].map(([n,l,c]) => (
                <div key={l} className="flex-1 px-2 py-1.5 border-r border-slate-100 last:border-r-0">
                  <div className="text-sm font-semibold" style={{ color: c }}>{n}</div>
                  <div className="text-[8px] text-slate-400 uppercase tracking-wide">{l}</div>
                </div>
              ))}
            </div>

            <div className="px-2.5 pt-2 pb-1 text-[8px] font-semibold text-slate-400 uppercase tracking-widest">
              Need my action
            </div>

            {/* loan cards */}
            {LOANS.map((l, i) => (
              <div
                key={l.id}
                onClick={() => pickLoan(i)}
                className="px-2.5 py-2 border-b border-slate-100 cursor-pointer transition-colors"
                style={{
                  backgroundColor: activeLoan === i ? '#f0f7f2' : undefined,
                  borderLeft: activeLoan === i ? '2px solid #1B5E20' : '2px solid transparent',
                }}
              >
                <div className="flex items-center gap-1 mb-0.5">
                  <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: l.dotColor }} />
                  <span className="text-[11px] font-semibold text-slate-700">{l.name}</span>
                  <span className={`ml-auto text-[8px] font-bold px-1.5 py-0.5 rounded-full ${l.urgencyCls}`}>
                    {l.urgency}
                  </span>
                </div>
                <div className="text-[9px] text-slate-500">
                  <span className="font-medium text-slate-700">{l.finding}</span>{l.findingSub}
                </div>
                <div className="text-[9px] text-slate-400 mt-0.5">
                  {l.amount} · {l.product} · {l.sla}
                </div>
              </div>
            ))}

            {/* greyed-out 4th loan */}
            <div className="px-2.5 py-2 border-b border-slate-100 opacity-35 pointer-events-none">
              <div className="flex items-center gap-1 mb-0.5">
                <div className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" />
                <span className="text-[11px] font-semibold text-slate-700">Sofia Chen</span>
                <span className="ml-auto text-[8px] font-bold px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-400">Clear</span>
              </div>
              <div className="text-[9px] text-slate-500">All checks passed</div>
              <div className="text-[9px] text-slate-400 mt-0.5">$510K · Jumbo · on track</div>
            </div>
          </div>

          {/* ── Detail panel (right) ── */}
          <div className="flex flex-col min-h-[340px]">
            {/* loan header */}
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100">
              <div>
                <div className="text-[12px] font-semibold text-slate-800">{loan.name}</div>
                <div className="text-[10px] text-slate-500">{loan.amount} · {loan.product}</div>
              </div>
              <span className={`ml-auto text-[9px] font-semibold px-2 py-0.5 rounded-full ${loan.badgeCls}`}>
                {loan.badge}
              </span>
            </div>

            {/* tabs */}
            <div className="flex border-b border-slate-100 px-3">
              {TABS.map((t, i) => (
                <button
                  key={t}
                  onClick={() => pickTab(i)}
                  className="text-[10px] px-2 py-1.5 border-b-2 transition-colors mr-0.5"
                  style={{
                    borderBottomColor: activeTab === i ? '#1B5E20' : 'transparent',
                    color: activeTab === i ? '#1B5E20' : '#94a3b8',
                    fontWeight: activeTab === i ? 600 : 400,
                  }}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* panel content */}
            <div className="flex-1 px-3 py-2.5 overflow-hidden">

              {/* DECISION */}
              {activeTab === 0 && (
                <div className="animate-fade-in">
                  <div className="text-[8px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
                    Decision journey
                  </div>
                  <div className="flex gap-1 mb-2.5">
                    {loan.decision.waves.map((w) => (
                      <div key={w.name} className="flex-1 border border-slate-100 rounded p-1 text-center">
                        <div className="text-[8px] text-slate-500 mb-1">{w.name}</div>
                        <div className="w-1.5 h-1.5 rounded-full mx-auto" style={{ backgroundColor: w.color }} />
                      </div>
                    ))}
                  </div>
                  <div className="bg-slate-50 border border-slate-100 rounded-lg p-2 mb-2">
                    <div className="text-[9px] font-semibold text-blue-600 mb-1">AI explanation</div>
                    <div className="text-[10px] text-slate-700 leading-relaxed">{loan.decision.aiText}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3">
                    {loan.decision.signals.map((s) => (
                      <div key={s.key} className="flex justify-between border-b border-slate-100 py-1 text-[9px]">
                        <span className="text-slate-500">{s.key}</span>
                        <span className={`font-semibold ${s.bad ? 'text-red-600' : 'text-green-700'}`}>{s.val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* RULES */}
              {activeTab === 1 && (
                <div className="animate-fade-in">
                  <div className="text-[8px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
                    Rules applied
                  </div>
                  {loan.rules.map((r) => (
                    <div key={r.layer} className="border border-slate-100 rounded-lg p-2 mb-1.5">
                      <span className={`inline-block text-[8px] font-bold px-1.5 py-0.5 rounded mb-1 uppercase tracking-wide ${LAYER_STYLES[r.layer]}`}>
                        {r.layer}
                      </span>
                      <div className="text-[10px] font-semibold text-slate-800 mb-0.5">{r.title}</div>
                      <div className="text-[9px] text-slate-400">{r.cite}</div>
                    </div>
                  ))}
                  <div className="text-[9px] text-slate-400 mt-1">
                    184 rules total · every decision cites the exact rule that fired
                  </div>
                </div>
              )}

              {/* EVIDENCE */}
              {activeTab === 2 && (
                <div className="animate-fade-in">
                  <div className="text-[8px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
                    Source documents
                  </div>
                  {loan.evidence.map((e) => (
                    <div key={e.name} className="flex items-center gap-2 border border-slate-100 rounded-md px-2 py-1.5 mb-1">
                      <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <div className="flex-1 min-w-0">
                        <div className="text-[10px] font-semibold text-slate-700">{e.name}</div>
                        <div className="text-[9px] text-slate-400 truncate">{e.sub}</div>
                      </div>
                      <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-green-50 text-green-700 flex-shrink-0">
                        {e.conf}
                      </span>
                    </div>
                  ))}
                  <div className="text-[9px] text-slate-400 mt-1">
                    Click any document to see extracted value · source · confidence
                  </div>
                </div>
              )}

              {/* AUDIT */}
              {activeTab === 3 && (
                <div className="animate-fade-in">
                  <div className="text-[8px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
                    Audit trail — immutable
                  </div>
                  {loan.audit.map((a, i) => (
                    <div key={i} className="flex gap-2 border-b border-slate-100 py-1.5 last:border-b-0">
                      <div className="text-[9px] text-slate-400 min-w-[72px] pt-px flex-shrink-0">{a.time}</div>
                      <div>
                        <div className="text-[10px] text-slate-700">{a.main}</div>
                        <div className="text-[9px] text-slate-400">{a.sub}</div>
                      </div>
                    </div>
                  ))}
                  <div className="text-[9px] text-slate-400 mt-1.5">
                    Policy version pinned · model version pinned · examiner-ready
                  </div>
                </div>
              )}
            </div>

            {/* action bar */}
            <div className="flex gap-1.5 px-3 py-2 border-t border-slate-100 bg-slate-50">
              <button className="text-[10px] font-semibold px-3 py-1.5 rounded-md text-white" style={{ backgroundColor: BRAND.dark }}>
                Review file
              </button>
              <button className="text-[10px] px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600">
                Refer to BSA
              </button>
              <button className="text-[10px] px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600">
                Request docs
              </button>
              <button className="text-[10px] px-2.5 py-1.5 rounded-md border border-red-200 bg-white text-red-600">
                Escalate
              </button>
            </div>
          </div>
        </div>

        {/* footer */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 border-t border-slate-100 bg-slate-50">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="text-[9px] text-slate-400">Audit ready</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[9px] text-slate-400">14 documents</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[9px] text-slate-400">90% confidence</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[9px] text-slate-400">HMDA complete</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[9px] text-blue-500 cursor-pointer">Exam-ready export →</span>
        </div>
      </div>
    </section>
  )
}
