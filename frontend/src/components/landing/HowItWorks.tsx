import { Fragment } from 'react'
import { BRAND } from './brand'
import { SecLabel, H2, Sub, Container } from './primitives'

const STEPS: Array<[string, string, string]> = [
  ['1', 'READ', 'AI reads every document in the loan file'],
  ['2', 'CHECK', 'Matches every data point to regulations and policy'],
  ['3', 'RECOMMEND', 'Delivers a recommendation backed by evidence'],
  ['4', 'DECIDE', 'Your team reviews and makes the final call'],
]
const ROW1 = ['Borrower applies', 'Documents uploaded', 'AI evaluates every aspect']
const ROW2 = ['Audit trail documented', 'Underwriter decides', 'Recommendation with evidence']

function FlowBox({ title }: { title: string }) {
  return (
    <div
      className="min-w-[150px] flex-1 rounded-lg bg-white p-4 text-center text-sm"
      style={{ border: `1px solid ${BRAND.dark}`, fontWeight: 500, color: BRAND.nearblack }}
    >
      {title}
    </div>
  )
}

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="py-20">
      <Container>
        <div className="text-center">
          <SecLabel>How it works</SecLabel>
          <H2 className="mx-auto">From file to decision in four steps</H2>
          <Sub className="mx-auto mt-3 max-w-2xl">
            Every step creates an immutable record. What the AI found. What the human decided. Why.
          </Sub>
        </div>

        {/* 4 steps */}
        <div className="mt-12 flex flex-col items-stretch gap-3 md:flex-row md:items-start">
          {STEPS.map(([num, title, desc], i) => (
            <Fragment key={num}>
              <div className="flex flex-1 flex-col items-center text-center">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold text-white"
                  style={{ backgroundColor: BRAND.dark }}
                >
                  {num}
                </div>
                <div className="mt-3 text-lg font-extrabold tracking-tight" style={{ color: BRAND.dark }}>{title}</div>
                <p className="mx-auto mt-2 max-w-[200px] text-sm leading-relaxed text-slate-500">{desc}</p>
              </div>
              {i < STEPS.length - 1 && (
                <div className="flex shrink-0 items-center justify-center self-center text-2xl md:self-start md:pt-3" style={{ color: BRAND.dark }}>
                  <span className="hidden md:inline">→</span><span className="md:hidden">↓</span>
                </div>
              )}
            </Fragment>
          ))}
        </div>

        {/* process flow — Row 1 → , Row 2 ← */}
        <div className="mx-auto mt-14 max-w-[860px] space-y-2">
          <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
            {ROW1.map((t, i) => (
              <Fragment key={t}>
                <FlowBox title={t} />
                {i < ROW1.length - 1 && (
                  <span className="self-center text-xl" style={{ color: BRAND.dark }}>
                    <span className="hidden md:inline">→</span><span className="md:hidden">↓</span>
                  </span>
                )}
              </Fragment>
            ))}
          </div>
          <div className="flex justify-center text-xl md:justify-end md:pr-[10%]" style={{ color: BRAND.dark }}>↓</div>
          {/* Row 2 reads left→right as [Audit trail] ← [Underwriter decides] ← [Recommendation]; arrows point LEFT */}
          <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
            {ROW2.map((t, i) => (
              <Fragment key={t}>
                <FlowBox title={t} />
                {i < ROW2.length - 1 && (
                  <span className="self-center text-xl" style={{ color: BRAND.dark }}>
                    <span className="hidden md:inline">←</span><span className="md:hidden">↓</span>
                  </span>
                )}
              </Fragment>
            ))}
          </div>
        </div>

        <div className="mx-auto mt-12 max-w-[600px] text-center">
          <div className="text-lg font-bold" style={{ color: BRAND.nearblack }}>No new apps. No new portals. No new logins.</div>
          <div className="mt-2 text-base text-slate-500">Accord works alongside your LOS. Your team keeps using Encompass.</div>
        </div>
      </Container>
    </section>
  )
}
