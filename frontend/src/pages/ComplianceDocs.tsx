import { PublicShell, Section } from './Security'

const REGS: Array<[string, string, string]> = [
  ['HMDA', 'Home Mortgage Disclosure Act', 'Accord tracks all HMDA-required fields automatically. Export LAR data in CFPB-compliant format. Current completeness is visible on the Audit dashboard.'],
  ['ECOA', 'Equal Credit Opportunity Act', 'Every denial triggers adverse-action tracking. Specific denial reasons are recorded (not generic). The 30-day notice countdown is monitored.'],
  ['TRID', 'TILA-RESPA Integrated Disclosure', 'Closing-disclosure timing is tracked. 3-day-rule compliance is monitored. Tolerance buckets are verified.'],
  ['Fair Lending', 'Disparate-impact monitoring', 'AI decisions are monitored for disparate impact. Approval rates are analyzable by geography and demographics. Override patterns are tracked for bias detection.'],
]

const FLOW = [
  'Loan arrives', 'AI evaluates', 'Human reviews', 'Decision made', 'Override (if any)', 'Stored', 'Examiner package',
]

const RECORD = [
  'What the AI proposed',
  'What data it analyzed',
  'What the human decided',
  'Why they agreed or disagreed',
  'Their authority level',
  'Timestamp and digital signature',
]

const REPORTS: Array<[string, string]> = [
  ['HMDA LAR Export', 'Quarterly · CFPB format'],
  ['Fair Lending Analysis', 'Monthly'],
  ['AI Decision Audit Trail', 'On demand'],
  ['Override Justification Report', 'Monthly'],
  ['AI Model Validation Report', 'Quarterly'],
  ['Complete Examiner Package', 'On demand · ZIP'],
]

export default function ComplianceDocs() {
  return (
    <PublicShell title="Compliant by Design" subtitle="How Accord supports lending compliance requirements.">
      <Section eyebrow="Regulatory framework">
        <div className="space-y-3">
          {REGS.map(([abbr, full, body]) => (
            <div key={abbr} className="rounded-xl border border-slate-200 p-4">
              <div className="flex items-baseline gap-2">
                <span className="font-bold text-slate-900">{abbr}</span>
                <span className="text-xs text-slate-400">{full}</span>
              </div>
              <p className="mt-1.5 text-[15px] leading-relaxed text-slate-600">{body}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section eyebrow="Audit architecture">
        <div className="flex flex-wrap items-center gap-2">
          {FLOW.map((step, i) => (
            <span key={step} className="flex items-center gap-2">
              <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700">{step}</span>
              {i < FLOW.length - 1 && <span className="text-slate-300">→</span>}
            </span>
          ))}
        </div>
        <p className="mt-5 text-[15px] text-slate-700">
          Each step is logged to <span className="font-mono text-sm text-slate-600">decision_outputs</span> +{' '}
          <span className="font-mono text-sm text-slate-600">decision_timeline</span> and exportable as an examiner package.
          Every step creates an immutable record:
        </p>
        <ul className="mt-3 space-y-2 text-[15px] text-slate-600">
          {RECORD.map((r) => <li key={r} className="flex gap-2"><span className="mt-0.5 text-brand">•</span><span>{r}</span></li>)}
        </ul>
      </Section>

      <Section eyebrow="Examiner-ready exports">
        <div className="overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {REPORTS.map(([name, cadence]) => (
                <tr key={name}>
                  <td className="px-4 py-2.5 font-medium text-slate-800">📑 {name}</td>
                  <td className="px-4 py-2.5 text-right text-slate-500">{cadence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-slate-600">
          Questions for your compliance team? Reach us at{' '}
          <a href="mailto:compliance@useaccord.com" className="font-medium text-brand hover:underline">compliance@useaccord.com</a>.
        </p>
      </Section>
    </PublicShell>
  )
}
