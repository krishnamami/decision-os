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
          <h2 className="text-[28px] font-bold leading-[1.2] tracking-[-0.02em] text-white md:text-[32px]">
            Make faster, fairer, and fully auditable decisions.
          </h2>
          <div className="mt-8 grid grid-cols-2 gap-6 md:grid-cols-4">
            {STATS.map(([big, label]) => (
              <div key={label}>
                <div className="text-3xl font-extrabold text-white">{big}</div>
                <div className="mt-1 text-sm text-white/70">{label}</div>
              </div>
            ))}
          </div>
        </Container>
      </div>
    </section>
  )
}
