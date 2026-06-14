import { useState } from 'react'
import { SecLabel, Container } from './primitives'
import { Icon } from './Icon'

const FAQS: Array<[string, string]> = [
  ['How long does setup take?', 'Most lenders go live the same day. Upload a CSV and AI starts evaluating immediately. Encompass integration takes about 15 minutes.'],
  ['Does Accord replace my LOS?', 'No. Accord works alongside your LOS. Your team keeps using Encompass. No new apps, portals, or logins.'],
  ['How does the AI make decisions?', 'Every decision maps to a specific rule with a regulation citation. Nothing is a black box. Click any rule — see the exact regulation.'],
  ['What if the AI is wrong?', 'Humans make the final call. AI recommends — your underwriter decides. Every override is documented with written reasoning.'],
  ['Is my data secure?', 'Enterprise customers get a dedicated VPC deployment. You own your data. SOC 2 compliance in progress.'],
  ['Who owns the data?', 'You do. Always. Enterprise customers get a read-only database replica for their own analytics.'],
  ['Can I connect my BI tools?', 'Yes. Enterprise plans include a dedicated read-only database replica. Connect Tableau, Power BI, Looker, or any BI tool directly.'],
  ['Can I run Accord in my own cloud?', 'Yes. Enterprise customers can deploy in their own AWS VPC. You own your data either way.'],
]

export default function FAQSection() {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <section id="faq" className="py-20">
      <Container className="max-w-[800px]">
        <div className="text-center"><SecLabel>Frequently asked questions</SecLabel></div>
        <div className="mt-8 space-y-3">
          {FAQS.map(([q, a], i) => {
            const isOpen = open === i
            return (
              <div key={q} className="rounded-xl border border-slate-200 bg-white">
                <button
                  onClick={() => setOpen(isOpen ? null : i)}
                  className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
                  aria-expanded={isOpen}
                >
                  <span className="font-semibold text-slate-900">{q}</span>
                  <span
                    className="shrink-0 text-slate-400 transition-transform"
                    style={{ transform: isOpen ? 'rotate(180deg)' : 'none' }}
                  >
                    <Icon name="chevron-down" size={18} />
                  </span>
                </button>
                {isOpen && <p className="px-5 pb-4 text-sm leading-relaxed text-slate-600">{a}</p>}
              </div>
            )
          })}
        </div>
      </Container>
    </section>
  )
}
