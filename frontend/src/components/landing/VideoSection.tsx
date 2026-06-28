import { useEffect, useRef, useState } from 'react'
import { BRAND } from './brand'
import { SecLabel, H2, Sub } from './primitives'

const VIDEO_SRC = '/accord_demo.mp4'
const POSTER = '/accord_demo_poster.jpg'

// ── Animated fraud-review card ─────────────────────────────────────────────
function FraudCard({ animate }: { animate: boolean }) {
  const cls = (base: string) => `${base}${animate ? ' ac-go' : ''}`

  return (
    <>
      <style>{`
        .ac-l, .ac-r, .ac-bp, .ac-bs1, .ac-bs2, .ac-foot {
          opacity: 0;
          transform: translateY(8px);
          transition: none;
        }
        .ac-l.ac-go  { animation: acUp 0.38s ease forwards 0.15s; }
        .ac-r.ac-go  { animation: acUp 0.38s ease forwards 0.65s; }
        .ac-bp.ac-go  { animation: acUp 0.28s ease forwards 0.82s; }
        .ac-bs1.ac-go { animation: acUp 0.28s ease forwards 0.94s; }
        .ac-bs2.ac-go { animation: acUp 0.28s ease forwards 1.06s; }
        .ac-foot.ac-go{ animation: acUp 0.28s ease forwards 1.22s; }
        @keyframes acUp { to { opacity: 1; transform: translateY(0); } }
      `}</style>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm text-left">

        {/* top bar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100 bg-slate-50">
          <span className="w-2.5 h-2.5 rounded-full bg-red-400" />
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
          <span className="w-2.5 h-2.5 rounded-full bg-green-400" />
          <span className="ml-1 text-[11px] font-medium text-slate-500">
            Daniel Reyes · $418K · Conforming
          </span>
          <span className="ml-auto text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-50 text-red-600">
            Fraud review
          </span>
        </div>

        {/* two columns */}
        <div className="grid grid-cols-2 divide-x divide-slate-100">

          {/* LEFT */}
          <div className={`ac-l p-4`}>
            <p className="text-[9px] font-semibold tracking-widest uppercase text-slate-400 mb-2">
              Briefing
            </p>
            <p className="text-[11px] text-slate-500 leading-relaxed mb-3">
              W2 salaried, $418K conforming purchase. Credit clean, collateral clear.
              Identity fraud score <span className="font-semibold text-slate-800">0.79</span> — BSA referral mandatory above 0.75.
            </p>

            <hr className="border-slate-100 mb-3" />

            <p className="text-[9px] font-semibold tracking-widest uppercase text-slate-400 mb-2">
              What needs attention
            </p>
            <div className="flex flex-col gap-2">
              <div>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                  Identity — fraud score 0.79
                </div>
                <p className="text-[10px] text-slate-400 ml-3">ID verification · watchlist · device signals</p>
              </div>
              <div>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                  Employment — 290 day gap
                </div>
                <p className="text-[10px] text-slate-400 ml-3">Prior employer unconfirmed</p>
              </div>
              <div>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                  Income — W2 vs stated delta 6%
                </div>
                <p className="text-[10px] text-slate-400 ml-3">Reconciliation pending</p>
              </div>
              <div>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
                  5 checks passed
                </div>
                <p className="text-[10px] text-slate-400 ml-3">Credit · collateral · AUS · title · compliance</p>
              </div>
            </div>
          </div>

          {/* RIGHT */}
          <div className={`ac-r p-4`}>
            <p className="text-[9px] font-semibold tracking-widest uppercase text-slate-400 mb-2">
              Your call
            </p>
            <p className="text-[11px] text-slate-500 leading-relaxed mb-2">
              Fraud score exceeds threshold.{' '}
              <span className="font-semibold text-slate-800">BSA referral mandatory above 0.75.</span>
            </p>
            <p className="text-[10px] text-slate-400 bg-slate-50 border-l-2 border-red-400 px-2 py-1 rounded-r mb-3">
              BSA/AML 31 CFR §1010 · Rule v3 · active 5/1/2026
            </p>

            <button
              className={`ac-bp w-full py-2 rounded-lg text-[11px] font-semibold text-white mb-1.5`}
              style={{ backgroundColor: BRAND.dark }}
            >
              ⚠ Refer to BSA/AML
            </button>
            <button className={`ac-bs1 w-full py-1.5 rounded-lg text-[11px] text-slate-600 border border-slate-200 mb-1.5 bg-white`}>
              Request identity documents
            </button>
            <button className={`ac-bs2 w-full py-1.5 rounded-lg text-[11px] text-slate-600 border border-slate-200 bg-white`}>
              Needs senior review
            </button>

            <p className="text-[9px] font-semibold tracking-widest uppercase text-slate-400 mt-3 mb-2">
              Similar files
            </p>
            <div className="flex flex-col gap-1.5">
              {[
                { label: 'Fraud 0.81 · Conforming', tag: 'BSA referral', cls: 'bg-amber-50 text-amber-700' },
                { label: 'Fraud 0.83 · Conforming', tag: 'Denied',       cls: 'bg-red-50 text-red-600'    },
                { label: 'Fraud 0.76 · FHA',        tag: 'More docs',    cls: 'bg-blue-50 text-blue-600'  },
              ].map(({ label, tag, cls: tc }) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">{label}</span>
                  <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${tc}`}>{tag}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* footer */}
        <div className={`ac-foot flex items-center gap-1.5 px-3 py-2 border-t border-slate-100 bg-slate-50`}>
          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="text-[10px] text-slate-400">Audit ready</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[10px] text-slate-400">8 decisions</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[10px] text-slate-400">14 documents</span>
          <span className="text-slate-200 mx-1">·</span>
          <span className="text-[10px] text-slate-400">92% confidence</span>
          <span className="ml-auto text-[10px] text-blue-500 cursor-pointer">Preview →</span>
        </div>
      </div>
    </>
  )
}

// ── Main section ───────────────────────────────────────────────────────────
export default function VideoSection() {
  const [hasVideo, setHasVideo] = useState(false)
  const [cardVisible, setCardVisible] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)

  // Check if video file is actually deployed
  useEffect(() => {
    let alive = true
    fetch(VIDEO_SRC, { method: 'HEAD' })
      .then((r) => {
        const ct = r.headers.get('content-type') || ''
        if (alive && r.ok && ct.startsWith('video')) setHasVideo(true)
      })
      .catch(() => undefined)
    return () => { alive = false }
  }, [])

  // Fire card animation when section scrolls into view
  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setCardVisible(true); obs.disconnect() } },
      { threshold: 0.25 }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  return (
    <section id="video" className="mx-auto max-w-[1100px] scroll-mt-24 px-6 py-16">
      {/* header — centred */}
      <div className="text-center mb-10">
        <SecLabel>See it in action</SecLabel>
        <H2 className="mx-auto">Watch Accord review a loan</H2>
        <Sub className="mx-auto mt-3 max-w-xl">
          From file landing in the queue to an audited, documented decision — in under two minutes.
        </Sub>
      </div>

      {/* two-column: video left, card right */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[55fr_45fr] lg:items-center">

        {/* LEFT — video or placeholder */}
        <div>
          {hasVideo ? (
            <video
              src={VIDEO_SRC}
              controls
              poster={POSTER}
              className="w-full rounded-2xl bg-black shadow-lg aspect-video"
            />
          ) : (
            <div
              className="w-full aspect-video rounded-2xl flex flex-col items-center justify-center gap-4"
              style={{ backgroundColor: BRAND.offwhite }}
            >
              <span
                className="flex h-20 w-20 items-center justify-center rounded-full shadow-lg"
                style={{ backgroundColor: BRAND.dark }}
              >
                <span
                  style={{
                    width: 0,
                    height: 0,
                    borderTop: '10px solid transparent',
                    borderBottom: '10px solid transparent',
                    borderLeft: '16px solid white',
                    marginLeft: '3px',
                  }}
                />
              </span>
              <div className="text-center">
                <div className="text-base font-semibold" style={{ color: BRAND.nearblack }}>
                  Accord demo — underwriter walkthrough
                </div>
                <div className="mt-1 text-sm text-slate-500">60 seconds · Real product</div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT — animated fraud card */}
        <div ref={cardRef}>
          <FraudCard animate={cardVisible} />
          {/* replay — only visible after first animation */}
          {cardVisible && (
            <button
              onClick={() => { setCardVisible(false); setTimeout(() => setCardVisible(true), 50) }}
              className="mt-3 mx-auto flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
            >
              ↺ Replay
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
