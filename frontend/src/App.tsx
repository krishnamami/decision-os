import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import ProductSwitcher from './components/ProductSwitcher'
import Pipeline from './pages/Pipeline'
import LoanDetail from './pages/LoanDetail'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Login from './pages/Login'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `rounded-md px-3 py-1.5 text-sm font-medium transition ${
          isActive ? 'bg-brand-light text-brand' : 'text-slate-600 hover:text-slate-900'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-3">
          <NavLink to="/pipeline" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">
              A
            </span>
            <span className="text-lg font-bold tracking-tight text-brand">Accord</span>
          </NavLink>

          <div className="hidden md:block">
            <ProductSwitcher active="pipeline" />
          </div>

          <nav className="ml-2 flex items-center gap-1">
            <NavItem to="/pipeline" label="Pipeline" />
            <NavItem to="/analytics" label="Analytics" />
            <NavItem to="/audit" label="Audit" />
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <NavLink to="/login" className="text-sm font-medium text-slate-600 hover:text-slate-900">
              Sign in
            </NavLink>
            <button className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">
              Get a demo
            </button>
          </div>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/pipeline" replace />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/pipeline/:appId" element={<LoanDetail />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/pipeline" replace />} />
        </Routes>
      </main>
    </div>
  )
}
