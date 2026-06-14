import { useEffect, useRef, useState } from 'react'
import { BRAND } from './brand'
import { SecLabel, H2, Sub, Container } from './primitives'

type Q = { q: string; sub: string; label: string; val: string; text: string }

const QUESTIONS: Q[] = [
  {
    q: 'What if we tighten DTI to 36%?',
    sub: '3 loans affected · $1.5M volume impact',
    label: 'Policy simulator — DTI limit',
    val: 'Tighten to 36%',
    text: '3 loans affected · $1.5M volume impact. Sarah Johnson $528K DTI 36.7% — misses the new limit by just 0.7%. Approve with compensating factors or reduce loan by $1K.',
  },
  {
    q: 'What if rates rise 200 basis points?',
    sub: '47 loans exceed DTI at new payment amounts',
    label: 'Rate sensitivity analysis',
    val: '+200 basis points',
    text: '47 loans would exceed DTI threshold at new payment amounts. Highest risk: 12 loans in the 40–43% DTI band. Recommend stress-testing those files before rate lock.',
  },
  {
    q: 'Should this blocked loan be approved?',
    sub: 'AI agents debate from every angle',
    label: 'AI agent debate — loan review',
    val: 'Recommendation: Approve',
    text: '9 of 12 agents recommend approval. Compensating factors: credit score 748, 24 months reserves, LTV 65%. DTI is borderline at 44.2% but within agency exception range.',
  },
  {
    q: 'Where are our hidden portfolio risks?',
    sub: '46% income gaps · 97% one-product type',
    label: 'Portfolio risk scan',
    val: 'Risk concentration found',
    text: '46% of income is from self-employment with insufficient documentation. 97% of loans are single-product type — conforming conventional. Diversification risk flagged for management review.',
  },
]

const KEYFRAMES = `@keyframes simIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}.sim-in{animation:simIn .35s ease both}`
const CYCLE = 4000

export default function SimulationSection() {
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)
  const [typed, setTyped] = useState('')
  const resumeRef = useRef<number | null>(null)

  // Auto-cycle through questions every 4s unless paused.
  useEffect(() => {
    if (paused) return
    const id = window.setTimeout(() => setActive((a) => (a + 1) % QUESTIONS.length), CYCLE)
    return () => window.clearTimeout(id)
  }, [active, paused])

  // Typewriter for the active question's result text.
  useEffect(() => {
    setTyped('')
    const full = QUESTIONS[active].text
    let i = 0
    const id = window.setInterval(() => {
      i += 1
      setTyped(full.slice(0, i))
      if (i >= full.length) window.clearInterval(id)
    }, 20)
    return () => window.clearInterval(id)
  }, [active])

  useEffect(() => () => { if (resumeRef.current) window.clearTimeout(resumeRef.current) }, [])

  const onPick = (i: number) => {
    setActive(i)
    setPaused(true)
    if (resumeRef.current) window.clearTimeout(resumeRef.current)
    resumeRef.current = window.setTimeout(() => setPaused(false), CYCLE)
  }

  const cur = QUESTIONS[active]

  return (
    <section className="py-20">
      <style>{KEYFRAMES}</style>
      <Container>
        <div className="text-center">
          <SecLabel>Simulation</SecLabel>
          <H2 className="mx-auto">What would happen if…?</H2>
          <Sub className="mx-auto mt-3 max-w-2xl">
            Ask any question about your portfolio. See the answer — with AI reasoning — in seconds.
          </Sub>
        </div>

        <div className="mt-12 grid gap-6 rounded-2xl p-6 md:grid-cols-2 md:p-8" style={{ backgroundColor: BRAND.offwhite }}>
          {/* LEFT — question cards */}
          <div className="space-y-3">
            {QUESTIONS.map((item, i) => {
              const on = i === active
              return (
                <button
                  key={item.q}
                  type="button"
                  onClick={() => onPick(i)}
                  className="w-full rounded-xl border p-4 text-left transition"
                  style={
                    on
                      ? { borderColor: BRAND.dark, backgroundColor: BRAND.light, color: BRAND.dark }
                      : { borderColor: '#E5E7EB', backgroundColor: '#fff', color: '#0f172a' }
                  }
                >
                  <div className="text-sm font-bold">{item.q}</div>
                  <div className="mt-1 text-xs font-medium" style={{ color: on ? BRAND.dark : '#6B7280' }}>{item.sub}</div>
                </button>
              )
            })}
          </div>

          {/* RIGHT — animated result */}
          <div key={active} className="sim-in flex min-h-[220px] flex-col rounded-xl border border-slate-200 bg-white p-5">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">{cur.label}</div>
            <div className="mt-1 text-xl font-bold" style={{ color: BRAND.dark }}>{cur.val}</div>
            <p className="mt-4 text-sm leading-relaxed text-slate-600">
              {typed}
              <span className="animate-pulse text-slate-400">▌</span>
            </p>
          </div>
        </div>
      </Container>
    </section>
  )
}
