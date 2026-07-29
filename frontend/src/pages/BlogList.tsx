import { Link } from 'react-router-dom'
import LandingNav from '../components/landing/LandingNav'
import { BRAND } from '../components/landing/brand'

const POSTS = [
  {
    slug: 'arm-loans-2026',
    series: 'UW Practitioner',
    title: 'ARM Loans in 2026: Why the Fully Indexed Rate Matters More Than Ever',
    excerpt: 'Fannie Mae B2-1.3-02 requires qualifying at the fully indexed rate — not the teaser. Here is what happens when the documentation does not match.',
    readTime: '5 min',
    published: 'July 27, 2026',
    live: true,
  },
  { slug: 'dti-trap-200-basis-points', series: 'UW Practitioner', title: 'The DTI Trap: What Happens When Rates Rise 200 Basis Points', excerpt: 'Rate sensitivity analysis across a real 63-loan portfolio. 33 loans, $9.4M volume — how to stress-test before rate lock.', readTime: '4 min', published: 'July 28, 2026', live: true },
  { slug: 'seven-reasons-loans-get-blocked', series: 'UW Practitioner', title: 'The 7 Most Common Reasons Loans Get Blocked', excerpt: 'DTI, LTV, fraud, employment gap, income discrepancy, product mismatch, missing conditions — ranked by frequency.', readTime: '5 min', published: 'July 28, 2026', live: true },
  { slug: 'self-employed-income', series: 'UW Practitioner', title: 'Self-Employed Borrowers: The Income Calculation Nobody Gets Right', excerpt: 'Schedule C 2-year average, declining income, what Fannie B3-3.4 actually allows.', readTime: '5 min', published: 'July 28, 2026', live: true },
  { slug: 'adverse-action-clock', series: 'UW Practitioner', title: 'The 30-Day Adverse Action Clock: How Lenders Stay Compliant', excerpt: 'ECOA 12 CFR 1002.9 — what triggers the clock, what the notice must say, how to track 26 declined files.', readTime: '4 min', published: 'July 28, 2026', live: true },
  { slug: 'hmda-2026', series: 'Compliance', title: 'HMDA 2026: What Changes and How Lenders Should Prepare', excerpt: 'LAR field requirements, FFIEC pipe-delimited format, edit checks, Feb 28 deadline.', readTime: '5 min', published: 'July 28, 2026', live: true },
  { slug: 'fair-lending-ai', series: 'Compliance', title: 'Fair Lending Monitoring with AI: Disparate Impact Detection', excerpt: 'ECOA 12 CFR 202.15. Approval rate by segment — FHA 70% vs Conv 54.8%. The 80% rule explained.', readTime: '5 min', published: 'July 28, 2026', live: true },
  { slug: 'bsa-aml-sar', series: 'Compliance', title: 'BSA/AML in Mortgage: What Triggers a SAR Filing', excerpt: 'Fraud score thresholds, identity match 0.0%, watchlist hits. When to file vs escalate.', readTime: '4 min', published: 'July 28, 2026', live: true },
  { slug: 'sr-11-7-ai-underwriting', series: 'Compliance', title: 'OCC SR 11-7 and AI Underwriting: What Model Risk Management Requires', excerpt: 'SR 11-7 validation — per-agent confidence rates, override documentation, audit trail requirements.', readTime: '6 min', published: 'July 28, 2026', live: true },
  { slug: 'decision-layer-not-los', series: 'Product', title: 'Why Mortgage Lenders Need an AI Decision Layer, Not a Bigger LOS', excerpt: 'The LOS stores data. The decision OS makes decisions. The gap that costs lenders SLA days and exam findings.', readTime: '5 min', published: 'July 28, 2026', live: true },
  { slug: 'why-claude', series: 'Product', title: 'Why We Built Mortgage AI on Claude', excerpt: 'Structured output, audit trails, model safety — why Claude fits regulated financial services.', readTime: '4 min', published: 'July 28, 2026', live: true },
  { slug: 'policy-simulation', series: 'Product', title: 'Policy Simulation: How Lenders Test Rule Changes Before They Cost Them Loans', excerpt: 'What if DTI tightens to 36%? See 25 affected loans, $9M impact, approval rate delta — in seconds.', readTime: '4 min', published: 'July 28, 2026', live: true },
  { slug: 'w2-vs-paystub', series: 'Scenario Deep Dive', title: 'W2 vs Paystub Income Gap: Which Number Wins and Why', excerpt: 'W2 $96K, paystub annualizes $84K — 12% gap. Fannie says use the lower. When to order IRS 4506-C.', readTime: '3 min', published: 'July 28, 2026', live: true },
  { slug: 'ssn-mismatch', series: 'Scenario Deep Dive', title: 'SSN Mismatch on a Mortgage File: Fraud or Typo?', excerpt: 'Credit report SSN ends 4421, URLA shows 4412. Identity block triggered. How to resolve vs escalate.', readTime: '3 min', published: 'July 28, 2026', live: true },
  { slug: 'employment-start-date-conflict', series: 'Scenario Deep Dive', title: 'Employment Start Date Conflict: URLA Says March, VOE Says June', excerpt: 'Two documents, two dates. Which controls? How to document the discrepancy. LOE requirements.', readTime: '3 min', published: 'July 28, 2026', live: true },
  { slug: 'appraisal-scan-unreadable', series: 'Scenario Deep Dive', title: 'When the Appraisal Scan Is Unreadable: Document Quality and Loan Timing', excerpt: 'Rotated scans, faded paystubs, handwritten VOEs — when to reject a doc vs attempt extraction.', readTime: '3 min', published: 'July 28, 2026', live: true },
  { slug: 'arm-dti-trap', series: 'Scenario Deep Dive', title: 'The ARM DTI Trap: Passes at Teaser Rate, Blocked at Fully Indexed', excerpt: '7/1 ARM teaser 5.5% passes DTI. FIR 7.875% blocks it. The Fannie qualify-at-FIR rule explained.', readTime: '3 min', published: 'July 28, 2026', live: true },
  { slug: 'charm-booklet-missing', series: 'Scenario Deep Dive', title: 'Missing CHARM Booklet: The ARM Disclosure That Stops a Jumbo Closing', excerpt: '$1.25M jumbo ARM. CHARM booklet never delivered. TILA 12 CFR 1026.19(b) — what it requires and when.', readTime: '3 min', published: 'July 28, 2026', live: true },
]

const SERIES_COLORS: Record<string, string> = {
  'UW Practitioner': '#1A3A5C',
  'Compliance': '#7C2D12',
  'Product': '#4A1A5C',
  'Scenario Deep Dive': '#1B4332',
}

export default function BlogList() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      {/* Nav */}
      <LandingNav />

      {/* Hero */}
      <div className="border-b border-slate-100 py-14" style={{ backgroundColor: '#F5F7FA' }}>
        <div className="mx-auto max-w-[1200px] px-6">
          <div className="mb-3 text-xs font-bold uppercase tracking-[0.14em]" style={{ color: BRAND.dark }}>Blog</div>
          <h1 className="text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>
            Mortgage underwriting.<br />Done right.
          </h1>
          <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-slate-500">
            Practical guides for underwriters, compliance officers, and mortgage lenders — grounded in real scenarios, real regulations, and real loan files.
          </p>
        </div>
      </div>

      {/* Posts grid */}
      <div className="mx-auto max-w-[1200px] px-6 py-14">
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {POSTS.map((post) => {
            const CardInner = () => (
              <>
                <div className="mb-3 flex items-center gap-2">
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white"
                    style={{ backgroundColor: SERIES_COLORS[post.series] ?? BRAND.dark }}
                  >
                    {post.series}
                  </span>
                  {!post.live && (
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-500">
                      Coming soon
                    </span>
                  )}
                </div>
                <div className="mb-2 text-[16px] font-bold leading-snug" style={{ color: BRAND.nearblack }}>
                  {post.title}
                </div>
                <p className="mb-4 flex-1 text-[14px] leading-relaxed text-slate-500">{post.excerpt}</p>
                <div className="flex items-center justify-between text-[12px] text-slate-400">
                  <span>{post.published}</span>
                  <span>{post.readTime} read</span>
                </div>
              </>
            )
            return post.live ? (
              <Link
                key={post.slug}
                to={`/blog/${post.slug}`}
                className="flex flex-col rounded-2xl border p-6 transition hover:border-slate-300 hover:shadow-md no-underline"
                style={{ borderColor: '#E5E7EB' }}
              >
                <CardInner />
              </Link>
            ) : (
              <div
                key={post.slug}
                className="flex flex-col rounded-2xl border p-6 opacity-60"
                style={{ borderColor: '#E5E7EB' }}
              >
                <CardInner />
              </div>
            )
          })}
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-slate-100 py-8 text-center text-sm text-slate-400">
        <Link to="/" className="hover:text-slate-600">← Back to Accord</Link>
      </footer>
    </div>
  )
}
