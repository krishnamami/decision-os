import { SecLabel, H2, Sub, Container, IconBox } from './primitives'
import { Icon, type IconName } from './Icon'

const FEATURES: Array<[IconName, string, string]> = [
  ['brain', 'Intelligent automation', 'AI handles the analysis — credit, fraud, income, collateral, compliance — your team reviews findings and makes the call.'],
  ['shield-check', 'Policy-driven decisions', 'Build, manage, and version lending policies with simulations and what-if analysis. See impact before any rule goes live.'],
  ['file-check', 'Evidence you can trust', 'Every data point sourced, validated, and linked to verifiable evidence. Click any number — see the source document.'],
  ['clipboard-list', 'Complete audit trail', 'A real-time record of every decision, note, and action — ready for exams. Every action requires written reasoning.'],
  ['users', 'Human-in-the-loop', 'Empowers underwriters with context, recommendations, and the right information. AI recommends — humans decide.'],
  ['chart-line', 'Insights that drive performance', 'Portfolio volume, approval rates, and fallout by wave — in one view. Know exactly where your pipeline is winning and leaking.'],
]

export default function FeaturesGrid() {
  return (
    <section className="py-20">
      <Container>
        <div className="text-center">
          <SecLabel>The Decision Intelligence Platform</SecLabel>
          <H2 className="mx-auto max-w-2xl">Everything you need to make better lending decisions</H2>
          <Sub className="mx-auto mt-3 max-w-2xl">
            Accord brings together policy, data, AI, and human judgment in one workspace so your team can decide
            with speed and confidence.
          </Sub>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(([icon, title, body]) => (
            <div key={title} className="rounded-2xl border border-slate-200 bg-white p-6">
              <IconBox><Icon name={icon} size={20} /></IconBox>
              <div className="mt-4 text-lg font-bold text-slate-900">{title}</div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{body}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  )
}
