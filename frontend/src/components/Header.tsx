import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

const PRODUCTS = [
  { to: '/pipeline', icon: '📋', name: 'Pipeline', desc: 'See what 12 AI agents found on every loan' },
  { to: '/analytics', icon: '📊', name: 'Analytics', desc: 'Portfolio performance, risk, and intelligence' },
  { to: '/simulation', icon: '🐟', name: 'Simulation', desc: 'Run the future before it happens' },
  { to: '/audit', icon: '📑', name: 'Audit', desc: 'Full decision trail for every examiner question' },
]

const PLATFORM = [
  { name: 'Decision AI', desc: 'Boundary rules engine with confidence scoring' },
  { name: 'AI Personas', desc: '12 agents trained on lending regulations' },
  { name: 'Integrations', desc: 'Encompass, Experian, Fannie DU — 15 min setup' },
  { name: 'Docs', desc: 'Get started in under an hour' },
]

const TABS = [
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/simulation', label: 'Simulation' },
  { to: '/audit', label: 'Audit' },
]

export default function Header() {
  const [bannerOpen, setBannerOpen] = useState(true)
  const [productsOpen, setProductsOpen] = useState(false)
  const navRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()

  // Close the dropdown when clicking outside the nav region.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (productsOpen && navRef.current && !navRef.current.contains(e.target as Node)) {
        setProductsOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [productsOpen])

  // Close the dropdown on navigation.
  useEffect(() => {
    setProductsOpen(false)
  }, [location.pathname])

  function go(to: string) {
    setProductsOpen(false)
    navigate(to)
  }

  const isActiveProduct = (to: string) =>
    location.pathname === to || location.pathname.startsWith(to + '/')

  return (
    <header className="sticky top-0 z-30">
      {/* 1. Announcement banner */}
      {bannerOpen && (
        <div
          className="relative flex items-center justify-center gap-2 px-4 text-sm text-white"
          style={{ height: 36, background: 'linear-gradient(90deg, #0F6E56, #1D9E75, #5DCAA5)' }}
        >
          <span>Introducing AI-powered lending decisions with complete audit trail.</span>
          <a href="#" className="font-medium underline">See how →</a>
          <button
            onClick={() => setBannerOpen(false)}
            aria-label="Dismiss"
            className="absolute right-3 text-white/80 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

      {/* 2. Main nav bar (+ dropdown anchored to it) */}
      <div ref={navRef} className="relative border-b border-[#E5E7EB] bg-white">
        <div className="mx-auto flex max-w-7xl items-center px-6" style={{ height: 52 }}>
          {/* Logo */}
          <button onClick={() => go('/pipeline')} className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">
              A
            </span>
            <span className="text-lg font-bold tracking-tight text-slate-900">accord</span>
          </button>

          {/* Nav links */}
          <nav className="ml-8 flex items-center gap-6 text-sm font-medium text-slate-600">
            <button
              onClick={() => setProductsOpen((v) => !v)}
              className={`flex items-center gap-1 hover:text-slate-900 ${productsOpen ? 'text-slate-900' : ''}`}
            >
              Products <span className="text-[10px]">▾</span>
            </button>
            <a href="#" className="hover:text-slate-900">Pricing</a>
            <a href="#" className="hover:text-slate-900">Docs</a>
            <a href="#" className="hover:text-slate-900">Blog</a>
          </nav>

          {/* Right side */}
          <div className="ml-auto flex items-center gap-4">
            <a href="#" className="text-sm font-medium text-slate-600 hover:text-slate-900">Sign in</a>
            <button className="rounded-full bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-dark">
              Get a demo
            </button>
          </div>
        </div>

        {/* 3. Products dropdown */}
        {productsOpen && (
          <div className="absolute left-0 right-0 top-full border-b border-[#E5E7EB] bg-white shadow-lg">
            <div className="mx-auto grid max-w-7xl grid-cols-1 gap-10 px-6 py-7 md:grid-cols-2">
              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Products</div>
                <div className="space-y-1">
                  {PRODUCTS.map((p) => (
                    <button
                      key={p.to}
                      onClick={() => go(p.to)}
                      className="flex w-full items-start gap-3 rounded-lg p-2.5 text-left hover:bg-slate-50"
                    >
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-light text-lg">
                        {p.icon}
                      </span>
                      <span>
                        <span className="block font-semibold text-slate-900">{p.name}</span>
                        <span className="block text-sm text-slate-500">{p.desc}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Platform</div>
                <div className="space-y-1">
                  {PLATFORM.map((p) => (
                    <a key={p.name} href="#" className="block rounded-lg p-2.5 hover:bg-slate-50">
                      <span className="block font-semibold text-slate-900">{p.name}</span>
                      <span className="block text-sm text-slate-500">{p.desc}</span>
                    </a>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 4. Active product bar */}
      <div className="border-b border-[#E5E7EB] bg-white">
        <nav className="mx-auto flex max-w-7xl items-center gap-6 px-6">
          {TABS.map((t) => {
            const active = isActiveProduct(t.to)
            return (
              <NavLink
                key={t.to}
                to={t.to}
                className={`-mb-px border-b-2 py-3 text-sm font-medium transition ${
                  active ? 'border-brand text-brand' : 'border-transparent text-[#6B7280] hover:text-slate-800'
                }`}
              >
                {t.label}
              </NavLink>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
