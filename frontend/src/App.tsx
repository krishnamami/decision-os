import { Navigate, Route, Routes } from 'react-router-dom'
import Header from './components/Header'
import Pipeline from './pages/Pipeline'
import LoanDetail from './pages/LoanDetail'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Simulation from './pages/Simulation'
import Login from './pages/Login'

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/pipeline" replace />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/pipeline/:appId" element={<LoanDetail />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/simulation" element={<Simulation />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/pipeline" replace />} />
        </Routes>
      </main>
    </div>
  )
}
