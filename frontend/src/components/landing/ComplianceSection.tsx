import { BRAND } from './brand'
import { SecLabel, H2, Container, IconBox } from './primitives'
import { Icon, type IconName } from './Icon'

const CARDS: Array<{ icon: IconName; title: string; intro: string; items: string[] }> = [
  {
    icon: 'building-bank',
    title: 'Three layers of rules',
    intro: 'Federal law, agency guidelines, and your overlays — all visible.',
    items: [
      'OFAC results surfaced from your existing compliance workflow',
      'QM safe harbor enforced',
      'State rules apply by property location',
      "Can't accidentally violate a regulation",
    ],
  },
  {
    icon: 'eye',
    title: 'Every decision traceable',
    intro: 'Click any data point — see the source document.',
    items: [
      'Click any rule — see the regulation citation',
      'Click any decision — see who, when, and why',
      'Examiner package in one click',
      'Every action requires written reasoning',
    ],
  },
  {
    icon: 'refresh',
    title: 'Continuous monitoring',
    intro: 'Your lending operation stays healthy automatically.',
    items: [
      'Rule boundary tests run on every change',
      'Agent performance tracked by persona',
      'Data freshness dashboard — every source',
      'Fair lending signals monitored across portfolio',
    ],
  },
]

export default function ComplianceSection() {
  return (
    <section className="py-20">
      <Container>
        <div className="text-center">
          <SecLabel>Compliance</SecLabel>
          <H2 className="mx-auto max-w-2xl">Regulatory compliance isn't a feature. It's the foundation.</H2>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {CARDS.map((c) => (
            <div key={c.title} className="rounded-2xl border border-slate-200 bg-white p-6">
              <IconBox><Icon name={c.icon} size={20} /></IconBox>
              <div className="mt-4 text-lg font-bold text-slate-900">{c.title}</div>
              <p className="mt-1.5 text-sm text-slate-500">{c.intro}</p>
              <ul className="mt-4 space-y-2 text-sm text-slate-600">
                {c.items.map((it) => (
                  <li key={it} className="flex gap-2">
                    <span style={{ color: BRAND.dark }}>✓</span>
                    <span>{it}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-10 text-center text-sm text-slate-400">Built for HMDA · ECOA · TRID · Fair Lending · BSA/AML</p>
      </Container>
    </section>
  )
}
