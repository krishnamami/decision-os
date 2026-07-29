import { Link } from 'react-router-dom'
import LandingNav from '../components/landing/LandingNav'
import { BRAND } from '../components/landing/brand'

const DOCS = [
  {
    slug: 'getting-started',
    pillar: 'Start Here',
    color: '#166534',
    icon: '',
    title: 'Getting Started with Accord',
    excerpt: 'Everything a lender administrator needs to configure Accord — from company setup and credit policy through loan products, pricing, and your first loan evaluation.',
    readTime: '7 min',
  },
  {
    slug: 'data-model',
    pillar: 'Data Model',
    color: '#0F4C75',
    icon: '',
    title: 'The Accord Data Model',
    excerpt: 'Eight core entities — Loan File, Entity State, Evidence Bundle, Decision, Rule, Condition, Exception, and Audit Trail — and how they connect from document ingestion to final underwriting disposition.',
    readTime: '6 min',
  },
  {
    slug: 'enterprise-security',
    pillar: 'Enterprise Security',
    color: '#1A3A5C',
    icon: '🔒',
    title: 'Enterprise Security Architecture',
    excerpt: 'bcrypt authentication, PII access logging, AES-256 encryption at rest, tenant-isolated storage, and JWT-enforced RBAC across every API surface.',
    readTime: '6 min',
  },
  {
    slug: 'soc2-ready',
    pillar: 'SOC 2-Ready',
    color: '#7C2D12',
    icon: '📋',
    title: 'Audit Trail and SOC 2 Posture',
    excerpt: 'Append-only decision traces, frozen persona bundle snapshots, human override tracking, Multi-AZ RDS, and point-in-time recovery — every decision reconstructable.',
    readTime: '6 min',
  },
  {
    slug: 'hmda-fair-lending',
    pillar: 'HMDA & Fair Lending',
    color: '#4A1A5C',
    icon: '⚖️',
    title: 'HMDA and Fair Lending Built In',
    excerpt: 'HMDA LAR auto-generated on every decision. EEOC four-fifths disparate impact monitoring across race, sex, and ethnicity. Demographic data never used in underwriting.',
    readTime: '7 min',
  },
  {
    slug: 'compliant-by-design',
    pillar: 'Compliant by Design',
    color: '#1B4332',
    icon: '🛡️',
    title: 'Compliant by Design: Model Risk and Regulatory Architecture',
    excerpt: 'SR 11-7 model inventory across 14 agents, three-layer rule hierarchy with zero hardcoded lending values, ATR/QM checklist, and exam-ready export package.',
    readTime: '8 min',
  },
]

export default function DocList() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <LandingNav />

      {/* Hero */}
      <div className="border-b border-slate-100 py-14" style={{ backgroundColor: '#F5F7FA' }}>
        <div className="mx-auto max-w-[1200px] px-6">
          <div className="mb-3 text-xs font-bold uppercase tracking-[0.14em]" style={{ color: BRAND.dark }}>Trust & Architecture</div>
          <h1 className="text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>
            Built for regulated<br />financial services.
          </h1>
          <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-slate-500">
            Architecture documentation for compliance officers, CTOs, and procurement teams evaluating Accord — grounded in real implementation details, not marketing claims.
          </p>
        </div>
      </div>

      {/* Docs grid */}
      <div className="mx-auto max-w-[1200px] px-6 py-14">
        <div className="grid gap-6 md:grid-cols-2">
          {DOCS.map((doc) => (
            <Link
              key={doc.slug}
              to={`/docs/${doc.slug}`}
              className="flex flex-col rounded-2xl border p-8 transition hover:border-slate-300 hover:shadow-md no-underline"
              style={{ borderColor: '#E5E7EB' }}
            >
              <div className="mb-4 flex items-center gap-3">
                <span
                  className="rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white"
                  style={{ backgroundColor: doc.color }}
                >
                  {doc.pillar}
                </span>
              </div>
              <div className="mb-3 text-[20px] font-bold leading-snug" style={{ color: BRAND.nearblack }}>
                {doc.title}
              </div>
              <p className="mb-6 flex-1 text-[14px] leading-relaxed text-slate-500">{doc.excerpt}</p>
              <div className="flex items-center justify-between text-[12px] text-slate-400">
                <span style={{ color: doc.color }} className="font-medium">Read documentation →</span>
                <span>{doc.readTime} read</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      <footer className="border-t border-slate-100 py-8 text-center text-sm text-slate-400">
        <Link to="/" className="hover:text-slate-600">← Back to Accord</Link>
      </footer>
    </div>
  )
}
