import { BRAND } from './brand'
import { Container } from './primitives'

const STATS: Array<[string, string]> = [
  ['100%', 'Decisions with documented reasoning'],
  ['1-click', 'Examiner package — full audit trail'],
  ['3 layers', 'Federal · Agency · Your policy'],
  ['Zero', 'Blind spots — every data point sourced'],
]

export default function ImpactSection() {
  return (
    <section className="px-6 py-16">
      <div className="mx-auto max-w-[1200px] rounded-3xl px-8 py-12 md:px-12 md:py-14" style={{ backgroundColor: BRAND.dark }}>
        <Container className="!px-0">
          <div className="grid gap-10 md:grid-cols-2">
            {/* LEFT */}
            <div>
              <h2 className="text-[28px] font-bold leading-[1.2] tracking-[-0.02em] text-white md:text-[32px]">
                Make faster, fairer, and fully auditable decisions.
              </h2>
              <div className="mt-8 grid grid-cols-2 gap-6">
                {STATS.map(([big, label]) => (
                  <div key={label}>
                    <div className="text-3xl font-extrabold text-white">{big}</div>
                    <div className="mt-1 text-sm text-white/70">{label}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* RIGHT — quote */}
            <div className="relative rounded-2xl p-7" style={{ backgroundColor: 'rgba(255,255,255,0.10)' }}>
              <span className="absolute right-5 top-2 text-6xl leading-none text-white/15">”</span>
              <p className="relative text-lg font-medium leading-relaxed text-white">
                Accord cut our average decision time from 5 days to 4 hours. The audit trail saved us 3 weeks during
                our last exam. I can't imagine going back to doing this manually.
              </p>
              <p className="mt-5 text-sm font-semibold text-white">VP of Underwriting</p>
              <p className="text-sm text-white/60">Design Partner · Mid-size Retail Lender</p>
            </div>
          </div>
        </Container>
      </div>
    </section>
  )
}
