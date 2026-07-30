import { BRAND } from './brand'
import { SecLabel, H2, Sub, Container } from './primitives'

type Plan = { name: string; price: string; unit: string; min: string; features: string[]; popular?: boolean }

const PLANS: Plan[] = [
  { name: 'Starter', price: '$15', unit: '/loan', min: '$500/mo min', features: ['Pipeline', 'CSV export', 'Self-serve setup', 'Email support'] },
  { name: 'Growth', price: '$35', unit: '/loan', min: '$1,500/mo min', features: ['Pipeline + Analytics', 'CSV + PDF export', 'API access', 'Guided setup call'] },
  { name: 'Business', price: '$60', unit: '/loan', min: '$3,000/mo min', popular: true, features: ['Pipeline + Analytics + Simulation', 'All exports', 'API + webhooks', 'Dedicated onboarding'] },
  { name: 'Enterprise', price: 'Custom', unit: '', min: 'Full platform + support', features: ['All 4 products', 'Dedicated DB replica', 'VPC deployment', '24/7 phone support'] },
]

export default function PricingSection({ onDemo }: { onDemo?: () => void }) {
  return (
    <section id="pricing" className="py-20">
      <Container>
        <div className="text-center">
          <SecLabel>Pricing</SecLabel>
          <H2 className="mx-auto">Simple per-loan pricing. No hidden fees.</H2>
          <Sub className="mx-auto mt-3">Start with Pipeline. Add more as you grow.</Sub>
        </div>
        <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {PLANS.map((p) => (
            <div
              key={p.name}
              className="relative flex flex-col rounded-2xl bg-white p-6"
              style={p.popular ? { border: `2px solid ${BRAND.dark}` } : { border: '1px solid #E5E7EB' }}
            >
              {p.popular && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-0.5 text-xs font-bold text-white" style={{ backgroundColor: BRAND.dark }}>
                  MOST POPULAR
                </span>
              )}
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">{p.name}</div>
              <div className="mt-2 text-3xl font-bold leading-none text-slate-900">
                {p.price}<span className="text-[13px] font-medium text-slate-400">{p.unit}</span>
              </div>
              <div className="mt-1 text-xs text-slate-400">{p.min}</div>
              <ul className="mt-4 flex-1 space-y-1.5 text-[13px] text-slate-600">
                {p.features.map((f) => (
                  <li key={f} className="flex gap-1.5"><span style={{ color: BRAND.dark }}>✓</span>{f}</li>
                ))}
              </ul>
              <button
                onClick={onDemo}
                className="mt-5 rounded-lg px-3 py-2 text-center text-sm font-semibold transition"
                style={p.popular ? { backgroundColor: BRAND.dark, color: '#fff' } : { border: `1px solid ${BRAND.dark}`, color: BRAND.dark }}
              >
                {p.name === 'Enterprise' ? 'Contact sales' : 'Start free trial'}
              </button>
            </div>
          ))}
        </div>
        <p className="mt-8 text-center text-[13px] text-slate-400">All plans include a 14-day free trial. No credit card required.</p>
      </Container>
    </section>
  )
}
