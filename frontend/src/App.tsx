import { Navigate, Route, Routes } from 'react-router-dom'
import Header from './components/Header'
import Pipeline from './pages/Pipeline'
import LoanDetail from './pages/LoanDetail'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Simulation from './pages/Simulation'
import Login from './pages/Login'
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
  const { isAuthenticated, loading, hasProduct, user } = useAuth()

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">Loading…</div>
  }
  if (!isAuthenticated) {
    return <Login />
  }

  // Role → which products this role may open at all.
  const ROLE_PRODUCTS: Record<string, string[]> = {
    admin: ['pipeline', 'analytics', 'simulation', 'audit'],
    manager: ['pipeline', 'analytics', 'simulation', 'audit'],
    underwriter: ['pipeline', 'simulation'],
    compliance: ['pipeline', 'audit'],
    viewer: ['pipeline'],
  }
  const allowed = (product: string) =>
    (ROLE_PRODUCTS[user?.role ?? 'viewer'] ?? ['pipeline']).includes(product) && (product === 'pipeline' || hasProduct(product))

  // A product the user can't reach (role or plan) redirects to Pipeline.
  const guard = (product: string, el: JSX.Element) => (allowed(product) ? el : <Navigate to="/pipeline" replace />)

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/pipeline" replace />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/pipeline/:appId" element={<LoanDetail />} />
          <Route path="/analytics" element={guard('analytics', <Analytics />)} />
          <Route path="/simulation" element={guard('simulation', <Simulation />)} />
          <Route path="/audit" element={guard('audit', <Audit />)} />
          <Route path="*" element={<Navigate to="/pipeline" replace />} />
        </Routes>
      </main>
    </div>
  )
}
