import { Link } from 'react-router-dom'

export function PublicPage({ title, intro, sections }: {
  title: string
  intro: string
  sections: Array<[string, string] | [string, string, string]>
}) {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-100">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6" style={{ height: 56 }}>
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight">accord</span>
          </Link>
          <Link to="/" className="text-sm font-medium text-brand hover:underline">← Back to home</Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-14">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-3 text-[17px] leading-relaxed text-slate-600">{intro}</p>
        <div className="mt-10 space-y-8">
          {sections.map(([h, body, id]) => (
            <section key={h} id={id} className="scroll-mt-20">
              <h2 className="text-lg font-semibold text-slate-900">{h}</h2>
              <p className="mt-1.5 text-[15px] leading-relaxed text-slate-600">{body}</p>
            </section>
          ))}
        </div>
        <div className="mt-12 rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600">
          Questions about security or compliance? Reach our team at{' '}
          <a href="mailto:security@useaccord.com" className="font-medium text-brand hover:underline">security@useaccord.com</a>.
        </div>
      </main>
    </div>
  )
}

export default function Security() {
  return (
    <PublicPage
      title="Security at Accord"
      intro="Accord is built to handle sensitive lending data with bank-grade controls. Here's how we protect it."
      sections={[
        ['Encryption everywhere', 'Data is encrypted with AES-256 at rest and TLS 1.3 in transit. Credentials and secrets are never stored in plain text.'],
        ['Tenant isolation', 'Every customer\'s data is isolated at the database level. A user in one organization can never see another organization\'s loans — enforced on every request, not just in the UI.'],
        ['Access control', 'Role-based access (processor, underwriter, senior UW, manager, compliance) governs what each user can see and do. Authentication uses short-lived signed tokens.'],
        ['You own your data', 'We never share or sell customer data, and we never use it to train AI for other customers. Export anytime via CSV, API, or a full database dump. When you leave, your data is deleted within 90 days and the deletion is confirmed in writing.'],
        ['SOC 2 ready', 'Our architecture and controls are designed toward SOC 2 compliance. Certification is in progress — we are not yet certified, and we will say so plainly until we are.', 'soc2'],
        ['Deploy your way', 'Run Accord as a fully managed SaaS, or deploy it in your own AWS VPC so your data never leaves your environment. Same product, your infrastructure.'],
        ['Reliability', 'We target 99.9% uptime, with monitoring and audit logging across the platform. Every action is recorded.'],
      ]}
    />
  )
}
