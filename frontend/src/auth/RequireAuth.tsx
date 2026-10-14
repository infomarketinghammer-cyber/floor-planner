import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import type { Role } from '../api/types.ts'
import { homePathFor, useAuth } from './AuthContext.tsx'

/** Route guard. Visual only: FastAPI enforces roles on every API call. */
export function RequireAuth({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) return <Navigate to={homePathFor(user)} replace />
  return <Outlet />
}

export function RedirectHome() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? homePathFor(user) : '/'} replace />
}

/** "/" shows the public home page to visitors and the app (dashboard) to signed-in users. */
export function PublicOrApp({ publicPage, app }: { publicPage: ReactNode; app: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>
  return user ? app : publicPage
}
