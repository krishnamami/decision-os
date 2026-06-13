import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Header from './components/Header'
import Pipeline from './pages/Pipeline'
import LoanDetail from './pages/LoanDetail'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Simulation from './pages/Simulation'
import Login from './pages/Login'
import Settings from './pages/Settings'
import Landing from './pages/Landing'
import Security from './pages/Security'
import ComplianceDocs from './pages/ComplianceDocs'
import DemoMode, { DemoRedirect, DemoWatermark } from './pages/DemoMode'
import RulesSettings from './pages/RulesSettings'
import ComparisonMode from './pages/ComparisonMode'
import { StaleDataBanner } from './components/DataFreshness'
import { AuthProvider, useAuth } from './context/AuthContext'

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}

// Gate the product on auth: a token check runs on load, then either the login
// page or the full app renders. `hasProduct`/role gating happens in Header +
// the route guard below.
function AppShell() {
  const { isAuthenticated, loading, hasProduct, effectiveUser, user, viewAs, stopImpersonating } = useAuth()
  const location = useLocation()

  // Public marketing pages — no auth, no app chrome, any auth state.
  if (location.pathname === '/security') return <Security />
  if (location.pathname === '/compliance') return <ComplianceDocs />

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">Loading…</div>
  }
  // Logged out: marketing landing at /, login at /login, everything else → /.
  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/pricing" element={<Landing scrollTo="pricing" />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    )
  }

  // Role → which products this role may open at all.
  const ROLE_PRODUCTS: Record<string, string[]> = {
    admin: ['pipeline', 'analytics', 'simulation', 'audit'],
    manager: ['pipeline', 'analytics', 'simulation', 'audit'],
    senior_uw: ['pipeline', 'analytics', 'simulation', 'audit'],
    underwriter: ['pipeline', 'simulation'],
    processor: ['pipeline'],
    closer: ['pipeline'],
    compliance: ['pipeline', 'audit'],
    viewer: ['pipeline'],
  }
  // Gating follows the EFFECTIVE user (so impersonation shows their access).
  const role = effectiveUser?.role ?? 'viewer'
  const allowed = (product: string) =>
    (ROLE_PRODUCTS[role] ?? ['pipeline']).includes(product) && (product === 'pipeline' || hasProduct(product))

  // A product the user can't reach (role or plan) redirects to Pipeline.
  const guard = (product: string, el: JSX.Element) => (allowed(product) ? el : <Navigate to="/pipeline" replace />)

  // Compliance lands on Audit; everyone else on Pipeline (which itself picks
  // My Queue / Team Overview / All Applications by role).
  const defaultPath = role === 'compliance' ? '/audit' : '/pipeline'

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <StaleDataBanner />
      {viewAs && (
        <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-1.5 text-sm font-medium text-white">
          👁 Viewing as {viewAs.name} ({viewAs.role.replace(/_/g, ' ')})
          <button onClick={stopImpersonating} className="rounded-md bg-white/20 px-2 py-0.5 text-xs font-semibold hover:bg-white/30">Exit</button>
        </div>
      )}
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to={defaultPath} replace />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/pipeline/:appId" element={<LoanDetail />} />
          <Route path="/analytics" element={guard('analytics', <Analytics />)} />
          <Route path="/simulation" element={guard('simulation', <Simulation />)} />
          <Route path="/audit" element={guard('audit', <Audit />)} />
          {user?.role === 'admin' && <Route path="/settings" element={<Settings />} />}
          {(user?.role === 'admin' || user?.role === 'manager') && <Route path="/settings/rules" element={<div className="mx-auto max-w-4xl px-6 py-6"><RulesSettings /></div>} />}
          {(user?.role === 'admin' || user?.role === 'manager') && <Route path="/comparison" element={<ComparisonMode />} />}
          {/* Demo walkthrough — admin-only deep links into the real pages, with
              the DEMO watermark on. See pages/DemoMode.tsx + docs/DEMO_SCRIPT.md. */}
          {user?.role === 'admin' && <Route path="/demo" element={<DemoMode />} />}
          {user?.role === 'admin' && <Route path="/demo/queue" element={<DemoRedirect to="/pipeline" />} />}
          {user?.role === 'admin' && <Route path="/demo/loan/:appId" element={<DemoRedirect to="/pipeline/:appId" />} />}
          {user?.role === 'admin' && <Route path="/demo/debate" element={<DemoRedirect to="/simulation#debate" />} />}
          {user?.role === 'admin' && <Route path="/demo/simulate" element={<DemoRedirect to="/simulation#simulate" />} />}
          {user?.role === 'admin' && <Route path="/demo/swarm" element={<DemoRedirect to="/simulation#swarm" />} />}
          {user?.role === 'admin' && <Route path="/demo/audit" element={<DemoRedirect to="/audit" />} />}
          <Route path="*" element={<Navigate to={defaultPath} replace />} />
        </Routes>
      </main>
      <DemoWatermark />
    </div>
  )
}
