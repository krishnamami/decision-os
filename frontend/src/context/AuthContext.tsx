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

interface AuthState {
  isAuthenticated: boolean
  loading: boolean
  user: AuthUser | null
  tenant: AuthTenant | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  hasProduct: (product: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tenant, setTenant] = useState<AuthTenant | null>(null)
  const [loading, setLoading] = useState(true)

  // On load: if a token exists, verify it via /me; drop it if invalid/expired.
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

  // Any API 401 (expired/invalid token) clears the session → back to login.
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
  }

  function logout() {
    clearToken()
    setUser(null)
    setTenant(null)
  }

  const hasProduct = (product: string) => !!tenant?.products?.includes(product)

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!user, loading, user, tenant, login, logout, hasProduct }}>
      {children}
    </AuthContext.Provider>
  )
}
