import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

// Shared shell for the public security / compliance pages.
export function PublicShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-100">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6" style={{ height: 56 }}>
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight">accord</span>
          </Link>
          <Link to="/" className="text-sm font-medium text-brand hover:underline">← Back to home</Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-14">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-[17px] leading-relaxed text-slate-600">{subtitle}</p>
        <div className="mt-12 space-y-12">{children}</div>
      </main>
    </div>
  )
}

export function Section({ eyebrow, id, children }: { eyebrow: string; id?: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20">
      <h2 className="mb-4 text-xs font-bold uppercase tracking-widest text-brand">{eyebrow}</h2>
      {children}
    </section>
  )
}

export function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2 text-[15px] text-slate-700">
      {items.map((i) => (
        <li key={i} className="flex gap-2"><span className="mt-0.5 text-brand">✓</span><span className="text-slate-600">{i}</span></li>
      ))}
    </ul>
  )
}

const SOC2 = [
  ['✅', 'CC6.1', 'Logical access controls (RBAC + RLS)'],
  ['✅', 'CC6.2', 'User authentication (JWT + bcrypt)'],
  ['✅', 'CC6.3', 'Access provisioning (role-based, per-tenant)'],
  ['✅', 'CC7.1', 'System monitoring (CloudWatch)'],
  ['✅', 'CC7.2', 'Anomaly detection (AI fraud screening)'],
  ['✅', 'CC8.1', 'Change management (GitHub + CI/CD)'],
  ['⬜', 'CC6.6', 'Penetration testing (scheduled)'],
  ['⬜', 'CC9.1', 'Risk assessment (in progress)'],
]

export default function Security() {
  return (
    <PublicShell title="Enterprise-Grade Security" subtitle="Designed for regulated financial institutions.">
      <Section eyebrow="Data protection">
        <Bullets items={[
          'AES-256 encryption at rest (RDS encrypted storage)',
          'TLS 1.3 encryption in transit (ALB HTTPS)',
          'Database-level row isolation (PostgreSQL RLS)',
          'No cross-tenant data access',
          'Secrets stored in AWS Secrets Manager',
        ]} />
      </Section>

      <Section eyebrow="Infrastructure">
        <Bullets items={[
          'AWS US-East-1 (Virginia)',
          'ECS Fargate — serverless containers, no persistent servers',
          'RDS PostgreSQL with automated backups',
          'CloudWatch monitoring and alerting',
          'All infrastructure defined as code',
        ]} />
      </Section>

      <Section eyebrow="Access control">
        <Bullets items={[
          'JWT-based authentication',
          'Role-based access control (8 roles)',
          'Row-level security in PostgreSQL',
          'Per-tenant data isolation',
          'Session management with token expiry',
          'Audit log of every access and action',
        ]} />
      </Section>

      <Section eyebrow="SOC 2 readiness" id="soc2">
        <div className="mb-5 rounded-xl border border-brand/30 bg-brand-light/40 px-4 py-3 text-[15px] text-brand-dark">
          Our architecture is designed for SOC 2 Type II compliance. Certification is in progress.
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {SOC2.map(([mark, code, desc]) => (
                <tr key={code} className={mark === '✅' ? '' : 'opacity-60'}>
                  <td className="w-10 px-3 py-2 text-center">{mark}</td>
                  <td className="w-20 px-3 py-2 font-mono text-xs font-semibold text-slate-700">{code}</td>
                  <td className="px-3 py-2 text-slate-600">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-slate-600">
          We welcome security questionnaires from prospective customers. Contact{' '}
          <a href="mailto:security@useaccord.com" className="font-medium text-brand hover:underline">security@useaccord.com</a>.
        </p>
      </Section>

      <Section eyebrow="Compliance capabilities">
        <Bullets items={[
          'HMDA reporting built-in',
          'Adverse action notice tracking (ECOA)',
          'Fair lending analysis',
          'Full decision audit trail',
          'AI model documentation',
          'Override justification tracking',
        ]} />
      </Section>

      <Section eyebrow="Privacy">
        <p className="mb-3 text-lg font-semibold text-slate-900">Your data is your data. Always.</p>
        <Bullets items={[
          "We don't sell customer data",
          "We don't train AI on customer data",
          'Data deletion within 90 days of contract end',
          'Data export available at any time',
        ]} />
      </Section>

      <Section eyebrow="Responsible AI">
        <p className="mb-3 text-[15px] text-slate-700">AI recommends, humans decide. Every AI decision includes:</p>
        <Bullets items={[
          'What data the AI analyzed',
          'What rule was applied',
          'Why it reached its conclusion',
          'Confidence level',
          'Human override with documented justification',
          'No black-box decisions — bias monitored through fair lending analysis',
        ]} />
      </Section>
    </PublicShell>
  )
}
