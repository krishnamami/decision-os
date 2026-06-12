import { useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

// ---------------------------------------------------------------------------
// Demo mode — a thin presentation layer for recording the product video.
//
// It does NOT fork the app or fake data: every demo URL routes to the REAL
// page against REAL seeded data, and just turns on a subtle "DEMO" watermark
// so the recording reads as a guided walkthrough. The /demo index is the
// control panel (admin only); the /demo/* deep links are bookmarkable moments
// the presenter can jump straight to.
// ---------------------------------------------------------------------------

const KEY = 'accord_demo'
const EVT = 'accord-demo-change'

export function isDemoOn(): boolean {
  try {
    return sessionStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setDemo(on: boolean) {
  try {
    if (on) sessionStorage.setItem(KEY, '1')
    else sessionStorage.removeItem(KEY)
  } catch {
    /* private mode — ignore */
  }
  window.dispatchEvent(new Event(EVT))
}

// React doesn't re-render on sessionStorage writes, so we bridge through a
// window event that setDemo() fires (plus the cross-tab `storage` event).
export function useDemoMode(): boolean {
  const [on, setOn] = useState(isDemoOn())
  useEffect(() => {
    const sync = () => setOn(isDemoOn())
    // Re-read on mount: a sibling's effect may have flipped the flag in the
    // same commit, firing EVT before this listener was attached.
    sync()
    window.addEventListener(EVT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(EVT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])
  return on
}

// Faint diagonal "DEMO" wash + a control pill. Rendered globally by AppShell
// whenever demo mode is on, so it persists as the presenter walks the app.
export function DemoWatermark() {
  const on = useDemoMode()
  if (!on) return null
  return (
    <>
      <div className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center overflow-hidden">
        <span className="-rotate-[20deg] select-none text-[18vw] font-black uppercase tracking-[0.15em] text-slate-900/[0.035]">
          DEMO
        </span>
      </div>
      <div className="fixed bottom-4 right-4 z-[70] flex items-center gap-2 rounded-full bg-slate-900/90 px-3 py-1.5 text-xs font-semibold text-white shadow-lg backdrop-blur">
        <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
        DEMO MODE
        <Link to="/demo" className="text-white/60 hover:text-white">menu</Link>
        <button
          onClick={() => setDemo(false)}
          className="rounded bg-white/15 px-1.5 py-0.5 hover:bg-white/25"
        >
          exit
        </button>
      </div>
    </>
  )
}

// Bookmarkable deep link → turns demo mode on, then redirects to the real
// route. `to` may contain :params (e.g. /pipeline/:appId), filled from the URL.
export function DemoRedirect({ to }: { to: string }) {
  const params = useParams()
  useEffect(() => setDemo(true), [])
  let target = to
  for (const [k, v] of Object.entries(params)) {
    if (v) target = target.replace(`:${k}`, v)
  }
  return <Navigate to={target} replace />
}

type Moment = {
  n: number
  path: string
  icon: string
  label: string
  show: string
  say: string
}

const MOMENTS: Moment[] = [
  {
    n: 1,
    path: '/demo/queue',
    icon: '📥',
    label: "Mike's Queue",
    show: 'My Queue loads with a greeting + the loans that need attention now.',
    say: '"When Mike logs in, he sees his queue — just the loans that need HIS attention right now."',
  },
  {
    n: 2,
    path: '/demo/loan/APP-SC02-004',
    icon: '🚩',
    label: 'Fraud-Blocked Loan',
    show: 'Summary card → "Why it\'s blocked" → "Everything else passed."',
    say: '"The AI found a watchlist match at 78% confidence. It tells Mike exactly what\'s wrong AND what\'s fine — the credit and income are clean. It\'s an identity question."',
  },
  {
    n: 3,
    path: '/demo/debate',
    icon: '💬',
    label: 'MiroFish Debate',
    show: 'Consensus card, vote bar, insights, full debate rounds.',
    say: '"MiroFish: 12 AI agents debate a loan in 3 rounds. They share findings, change positions, reach consensus — insights no single review would catch."',
  },
  {
    n: 4,
    path: '/demo/simulate',
    icon: '📋',
    label: 'Policy Simulator',
    show: 'DTI → 36% → "3 loans affected, $1.5M impact" + affected loan detail.',
    say: '"What if we tighten DTI? The simulator shows exactly who\'s affected, why, and what alternatives exist — BEFORE you change the policy."',
  },
  {
    n: 5,
    path: '/demo/swarm',
    icon: '🔍',
    label: 'Portfolio Health Check',
    show: 'Severity-grouped findings across the whole portfolio.',
    say: '"The health check scans all 8,896 loans. It found 46% have income gaps — a systematic problem no individual file review would catch."',
  },
  {
    n: 6,
    path: '/demo/audit',
    icon: '🧾',
    label: 'Audit Trail',
    show: 'The decision trail for a loan — every step, documented.',
    say: '"Every decision documented. Every action traced. Accord — every decision, in accord."',
  },
]

const CHECKLIST = [
  'Chrome, full screen, 1920×1080',
  'Close all other tabs; hide the bookmarks bar',
  'Login as processor1@summit.com / accord2026',
  'Run scripts/demo_data_check.py first — confirm "Demo data ready"',
  'Loom or OBS; quiet room; do 2–3 takes',
]

export default function DemoMode() {
  const on = useDemoMode()

  // The control panel itself shows under the watermark so the presenter can
  // see exactly how it'll look on camera.
  useEffect(() => {
    setDemo(true)
  }, [])

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Demo control room</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            Bookmarkable moments for recording the product video. Each opens the real page with the{' '}
            <span className="font-semibold">DEMO</span> watermark on. Follow{' '}
            <span className="font-mono text-sm">docs/DEMO_SCRIPT.md</span> for the full narration.
          </p>
        </div>
        <button
          onClick={() => setDemo(!on)}
          className={`shrink-0 rounded-lg px-3 py-2 text-sm font-semibold ${
            on ? 'bg-slate-900 text-white hover:bg-slate-700' : 'border border-slate-300 text-slate-700 hover:bg-slate-50'
          }`}
        >
          Watermark: {on ? 'ON' : 'OFF'}
        </button>
      </div>

      <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <h2 className="text-xs font-bold uppercase tracking-widest text-brand">Before you record</h2>
        <ul className="mt-2 space-y-1.5 text-sm text-slate-600">
          {CHECKLIST.map((c) => (
            <li key={c} className="flex gap-2">
              <span className="mt-0.5 text-brand">✓</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </div>

      <ol className="mt-6 space-y-3">
        {MOMENTS.map((m) => (
          <li key={m.path} className="rounded-xl border border-slate-200 p-4 transition hover:border-brand/40 hover:shadow-sm">
            <div className="flex items-start gap-4">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-light text-lg">{m.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="font-semibold text-slate-900">
                    <span className="mr-2 text-slate-400">{m.n}.</span>
                    {m.label}
                  </h3>
                  <Link
                    to={m.path}
                    className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark"
                  >
                    Open →
                  </Link>
                </div>
                <p className="mt-0.5 font-mono text-xs text-slate-400">{m.path}</p>
                <p className="mt-2 text-[15px] text-slate-700">
                  <span className="font-semibold text-slate-500">Show:</span> {m.show}
                </p>
                <p className="mt-1 text-[15px] italic text-slate-500">
                  <span className="not-italic font-semibold">Say:</span> {m.say}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-6 text-center text-sm text-slate-400">
        End on the landing page — <span className="font-medium text-slate-600">"Accord. Every decision, in accord."</span>
      </p>
    </div>
  )
}
