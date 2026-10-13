import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, guestUser, setGuestMode } from '../api/client.ts'
import type { User } from '../api/types.ts'

interface AuthState {
  user: User | null // the signed-in user, or a stand-in while working as a guest
  loading: boolean
  isGuest: boolean // no account: projects are kept in this browser (PRD 4.12)
  startGuest: () => Promise<void>
  leaveGuest: () => void
  login: (email: string, password: string) => Promise<User>
  register: (data: { name: string; email: string; password: string; company?: string }) => Promise<User>
  logout: () => Promise<void>
  updatePreferences: (preferences: User['preferences']) => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [isGuest, setIsGuest] = useState(false)

  const enterGuest = useCallback(async () => {
    const { guestId, localStore } = await import('../lib/localStore.ts')
    const prefs = (await localStore.get<User['preferences']>('preferences')) ?? { unit_system: 'imperial' }
    setGuestMode(true)
    setIsGuest(true)
    setUser(guestUser(await guestId(), prefs))
  }, [])

  useEffect(() => {
    api.auth
      .me()
      .then(({ user }) => setUser(user))
      .catch(async () => {
        setUser(null)
        if (readGuestFlag()) await enterGuest().catch(() => undefined) // storage blocked: stay out
      })
      .finally(() => setLoading(false))
  }, [enterGuest])

  const startGuest = useCallback(async () => {
    writeGuestFlag(true)
    await enterGuest()
  }, [enterGuest])

  const leaveGuest = useCallback(() => {
    writeGuestFlag(false)
    setGuestMode(false)
    setIsGuest(false)
    setUser(null)
  }, [])

  const signedIn = useCallback((u: User) => {
    writeGuestFlag(false)
    setGuestMode(false)
    setIsGuest(false)
    setUser(u)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setGuestMode(false) // sign-in always goes to the real API
    const { user } = await api.auth.login(email, password)
    signedIn(user)
    return user
  }, [signedIn])

  const register = useCallback(async (data: Parameters<AuthState['register']>[0]) => {
    setGuestMode(false)
    const { user } = await api.auth.register(data)
    signedIn(user)
    return user
  }, [signedIn])

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
    () => ({ user, loading, isGuest, startGuest, leaveGuest, login, register, logout, updatePreferences }),
    [user, loading, isGuest, startGuest, leaveGuest, login, register, logout, updatePreferences],
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

// "Continue without an account" is remembered per browser. A convenience only.
const GUEST_KEY = 'fp.guest'
function readGuestFlag(): boolean {
  try {
    return localStorage.getItem(GUEST_KEY) === '1'
  } catch {
    return false
  }
}
function writeGuestFlag(on: boolean) {
  try {
    if (on) localStorage.setItem(GUEST_KEY, '1')
    else localStorage.removeItem(GUEST_KEY)
  } catch {
    // not remembered
  }
}
