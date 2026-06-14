const PERSONAS: Array<[string, string]> = [
  ['See what matters. Make confident calls.', 'Every file briefed. Every rule explained. Every decision backed by evidence you can click through.'],
  ['Every decision traced. Exam-ready in one click.', 'Full audit trail generated automatically. HMDA, fair lending, OFAC results — all documented as work happens.'],
  ['Portfolio volume, approval rates, fallout by wave.', 'See which personas are blocking, where risk is concentrating, and what your leadership team needs to act.'],
]
const LABELS = ['Underwriters', 'Compliance', 'Management']

export default function PersonaStrip() {
  return (
    <section className="mx-auto max-w-[1200px] px-6 py-10">
      <div className="grid gap-5 md:grid-cols-3">
        {PERSONAS.map(([title, text], i) => (
          <div key={LABELS[i]} className="rounded-2xl border border-slate-200 bg-white p-6">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">{LABELS[i]}</div>
            <div className="mt-2 text-lg font-bold text-slate-900">{title}</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">{text}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
