import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  clearToken,
  fetchMe,
  getToken,
  loginRequest,
  setToken,
  type AuthTenant,
  type AuthUser,
} from '../api/client'

export interface ImpersonatedUser {
  user_id: string
  name: string
  role: string
}

interface AuthState {
  isAuthenticated: boolean
  loading: boolean
  user: AuthUser | null
  tenant: AuthTenant | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  hasProduct: (product: string) => boolean
  // Action-level RBAC flags from role_permissions (override_decision, etc.).
  permissions: Record<string, boolean>
  // Impersonation (super-admin): `effectiveUser` is who the app behaves as.
  effectiveUser: AuthUser | null
  viewAs: ImpersonatedUser | null
  impersonate: (u: ImpersonatedUser) => void
  stopImpersonating: () => void
}

const VIEWAS_KEY = 'accord_viewas'
const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tenant, setTenant] = useState<AuthTenant | null>(null)
  const [permissions, setPermissions] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [viewAs, setViewAs] = useState<ImpersonatedUser | null>(() => {
    try {
      const raw = localStorage.getItem(VIEWAS_KEY)
      return raw ? (JSON.parse(raw) as ImpersonatedUser) : null
    } catch {
      return null
    }
  })

  useEffect(() => {
    let alive = true
    if (!getToken()) {
      setLoading(false)
      return
    }
    fetchMe()
      .then((d) => {
        if (alive) {
          setUser(d.user)
          setTenant(d.tenant)
          setPermissions(d.action_permissions || {})
        }
      })
      .catch(() => {
        clearToken()
        if (alive) {
          setUser(null)
          setTenant(null)
        }
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const onUnauth = () => {
      setUser(null)
      setTenant(null)
    }
    window.addEventListener('accord:unauthorized', onUnauth)
    return () => window.removeEventListener('accord:unauthorized', onUnauth)
  }, [])

  async function login(email: string, password: string) {
    const s = await loginRequest(email, password)
    setToken(s.access_token)
    setUser(s.user)
    setTenant(s.tenant)
    // loginRequest doesn't return action_permissions — fetch them so RBAC flags
    // (override_decision, etc.) are available immediately after login.
    try { const me = await fetchMe(); setPermissions(me.action_permissions || {}) } catch { /* non-fatal */ }
  }

  function clearViewAs() {
    setViewAs(null)
    localStorage.removeItem(VIEWAS_KEY)
  }
  function logout() {
    clearToken()
    clearViewAs()
    setUser(null)
    setTenant(null)
    setPermissions({})
  }
  function impersonate(u: ImpersonatedUser) {
    setViewAs(u)
    localStorage.setItem(VIEWAS_KEY, JSON.stringify(u))
  }

  const hasProduct = (product: string) => !!tenant?.products?.includes(product)
  // When impersonating, identity stays real (token, email) but the experience
  // (role, queue, name) reflects the target user.
  const effectiveUser: AuthUser | null =
    viewAs && user ? { ...user, user_id: viewAs.user_id, name: viewAs.name, role: viewAs.role } : user

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!user,
        loading,
        user,
        tenant,
        login,
        logout,
        hasProduct,
        permissions,
        effectiveUser,
        viewAs,
        impersonate,
        stopImpersonating: clearViewAs,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
