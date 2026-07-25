import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { fetchComparisonStatus } from '../api/client'
import NotificationBell from './NotificationBell'

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
  { to: '/pipeline', product: 'pipeline', label: 'Pipeline' },
  { to: '/analytics', product: 'analytics', label: 'Analytics' },
  { to: '/simulation', product: 'simulation', label: 'Simulation' },
  { to: '/audit', product: 'audit', label: 'Audit' },
  { to: '/platform-studio', product: 'platform_studio', label: 'Platform Studio' },
  { to: '/data-health', product: 'data_health', label: 'Data Health' },
  { to: '/settings/rules', product: 'data_health', label: 'Policy Rules' },
]

// Which nav tabs each role sees (by label). Roles not listed fall back to
// Pipeline only. Tabs are also plan-gated below (pipeline + data_health are
// always plan-available).
const ROLE_NAV: Record<string, string[]> = {
  underwriter: ['Pipeline'],
  processor: ['Pipeline'],
  closer: ['Pipeline'],
  viewer: ['Pipeline'],
  senior_uw: ['Pipeline', 'Analytics'],
  manager: ['Pipeline', 'Analytics', 'Simulation'],
  compliance: ['Pipeline', 'Audit', 'Policy Rules'],
  admin: ['Pipeline', 'Analytics', 'Simulation', 'Audit', 'Data Health', 'Policy Rules', 'Platform Studio'],
  super_admin: ['Pipeline', 'Analytics', 'Simulation', 'Audit', 'Data Health', 'Policy Rules', 'Platform Studio'],
}
// Upgrade prompt when the tenant's plan lacks a product.
const UPGRADE: Record<string, string> = {
  analytics: 'Upgrade to Growth plan',
  simulation: 'Upgrade to Business plan',
  audit: 'Upgrade to Enterprise plan',
}

export default function Header() {
  const [bannerOpen, setBannerOpen] = useState(true)
  const [productsOpen, setProductsOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const [comparisonActive, setComparisonActive] = useState(false)
  const navRef = useRef<HTMLDivElement>(null)
  const userRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, tenant, logout, hasProduct, effectiveUser } = useAuth()

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (productsOpen && navRef.current && !navRef.current.contains(e.target as Node)) setProductsOpen(false)
      if (userOpen && userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [productsOpen, userOpen])

  useEffect(() => {
    setProductsOpen(false)
    setUserOpen(false)
  }, [location.pathname])

  function go(to: string) {
    setProductsOpen(false)
    navigate(to)
  }

  const isActiveProduct = (to: string) => location.pathname === to || location.pathname.startsWith(to + '/')
  const role = user?.role ?? 'viewer' // identity (avatar/menu) = real user
  const effRole = effectiveUser?.role ?? 'viewer' // tabs follow the impersonated role
  const roleAllows = (label: string) => (ROLE_NAV[effRole] ?? ['Pipeline']).includes(label)
  // Admin/manager use the Dashboard as their Pipeline landing (effective role,
  // so impersonating a non-manager keeps the real /pipeline link).
  const isMgr = ['admin', 'manager', 'super_admin'].includes(effRole)
  const planAllows = (product: string) => role === 'super_admin' || product === 'pipeline' || product === 'data_health' || hasProduct(product)
  const initials = (user?.name || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  const canCompare = role === 'admin' || role === 'manager'

  useEffect(() => {
    if (canCompare) fetchComparisonStatus().then((s) => setComparisonActive(s.active)).catch(() => undefined)
  }, [canCompare])

  return (
    <header className="sticky top-0 z-30">
      {!user && bannerOpen && (
        <div
          className="relative flex items-center justify-center gap-2 px-4 text-sm text-white"
          style={{ height: 36, background: 'linear-gradient(90deg, #0F6E56, #1D9E75, #5DCAA5)' }}
        >
          <span>Introducing AI-powered lending decisions with complete audit trail.</span>
          <a href="#" className="font-medium underline">See how →</a>
          <button onClick={() => setBannerOpen(false)} aria-label="Dismiss" className="absolute right-3 text-white/80 hover:text-white">✕</button>
        </div>
      )}

      <div ref={navRef} className="relative border-b border-white/[0.08] bg-[#0B1220]">
        <div className="mx-auto flex max-w-7xl items-center px-6" style={{ height: 52 }}>
          <button onClick={() => go('/pipeline')} className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">A</span>
            <span className="text-lg font-bold tracking-tight text-white">accord</span>
          </button>

          {!user && (
            <nav className="ml-8 flex items-center gap-6 text-sm font-medium text-white">
              <button onClick={() => setProductsOpen((v) => !v)} className={`flex items-center gap-1 hover:text-white ${productsOpen ? 'text-white' : ''}`}>
                Products <span className="text-[10px]">▾</span>
              </button>
              <a href="#" className="hover:text-white">Pricing</a>
              <a href="#" className="hover:text-white">Docs</a>
              <a href="#" className="hover:text-white">Blog</a>
            </nav>
          )}

          {/* Notifications + user menu */}
          <div className="ml-auto flex items-center gap-2">
            <NotificationBell />
            <div ref={userRef} className="relative">
            <button
              onClick={() => setUserOpen((v) => !v)}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-xs font-bold text-white"
              title={user?.name}
            >
              {initials}
            </button>
            {userOpen && (
              <div className="absolute right-0 top-full mt-2 w-60 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
                <div className="px-4 py-2.5">
                  <div className="font-semibold text-slate-900">{user?.name}</div>
                  <div className="mt-0.5 text-xs capitalize text-slate-500">{role} · {tenant?.name}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-400">{tenant?.plan} plan</div>
                </div>
                <div className="border-t border-slate-100" />
                {role === 'admin' && (
                  <button onClick={() => { setUserOpen(false); navigate('/settings') }} className="block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">Settings</button>
                )}
                <button onClick={logout} className="block w-full px-4 py-2 text-left text-sm font-medium text-red-600 hover:bg-slate-50">
                  Sign out
                </button>
              </div>
            )}
            </div>
          </div>
        </div>

        {!user && productsOpen && (
          <div className="absolute left-0 right-0 top-full border-b border-[#E5E7EB] bg-white shadow-lg">
            <div className="mx-auto grid max-w-7xl grid-cols-1 gap-10 px-6 py-7 md:grid-cols-2">
              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Products</div>
                <div className="space-y-1">
                  {PRODUCTS.map((p) => (
                    <button key={p.to} onClick={() => go(p.to)} className="flex w-full items-start gap-3 rounded-lg p-2.5 text-left hover:bg-slate-50">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-light text-lg">{p.icon}</span>
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

      {/* Active product bar — role-hidden / plan-locked */}
      <div className="border-b border-white/[0.08] bg-[#0B1220]">
        <nav className="mx-auto flex max-w-7xl items-center gap-6 px-6">
          {TABS.map((t) => {
            if (!roleAllows(t.label)) return null // role can't access — hide
            if (!planAllows(t.product)) {
              return (
                <span
                  key={t.to}
                  title={UPGRADE[t.product] ?? 'Not included in your plan'}
                  className="flex cursor-not-allowed items-center gap-1 py-3 text-sm font-medium text-white/30"
                >
                  🔒 {t.label}
                </span>
              )
            }
            const to = t.label === 'Pipeline' && isMgr ? '/dashboard' : t.to
            const active = isActiveProduct(to)
            return (
              <NavLink
                key={t.to}
                to={to}
                className={`-mb-px border-b-2 py-3 text-sm font-medium transition ${
                  active ? 'border-[#34D399] text-white' : 'border-transparent text-white/60 hover:text-white'
                }`}
              >
                {t.label}
              </NavLink>
            )
          })}
          {comparisonActive && canCompare && (
            <NavLink
              to="/comparison"
              className={({ isActive }) => `-mb-px border-b-2 py-3 text-sm font-medium transition ${isActive ? 'border-[#34D399] text-white' : 'border-transparent text-white/60 hover:text-white'}`}
            >
              🔄 Comparison
            </NavLink>
          )}
        </nav>
      </div>
    </header>
  )
}
