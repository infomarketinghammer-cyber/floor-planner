import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client.ts'
import type { User } from '../api/types.ts'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  register: (data: { name: string; email: string; password: string; company?: string }) => Promise<User>
  logout: () => Promise<void>
  updatePreferences: (preferences: User['preferences']) => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.auth
      .me()
      .then(({ user }) => setUser(user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const { user } = await api.auth.login(email, password)
    setUser(user)
    return user
  }, [])

  const register = useCallback(async (data: Parameters<AuthState['register']>[0]) => {
    const { user } = await api.auth.register(data)
    setUser(user)
    return user
  }, [])

  const logout = useCallback(async () => {
    await api.auth.logout()
    setUser(null)
  }, [])

  const updatePreferences = useCallback(async (preferences: User['preferences']) => {
    // Optimistic: the display switches at once; roll back if saving fails.
    let previous: User | null = null
    setUser((u) => {
      previous = u
      return u ? { ...u, preferences } : u
    })
    try {
      setUser(await api.users.updatePreferences(preferences))
    } catch {
      setUser(previous)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout, updatePreferences }),
    [user, loading, login, register, logout, updatePreferences],
  )
  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthState {
  const ctx = use(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export function homePathFor(user: User): string {
  return user.role === 'admin' ? '/admin' : '/'
}
