import { Link, NavLink, Outlet, useNavigate } from 'react-router'
import { useAuth } from '../auth/AuthContext.tsx'
import { UnitSystemToggle } from './UnitSystemToggle.tsx'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100'
  }`

export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:gap-x-6">
          <span className="whitespace-nowrap text-lg font-semibold">Floor Planner</span>
          <nav className="flex gap-1">
            <NavLink to="/" end className={navClass}>
              Home
            </NavLink>
            <NavLink to="/tiles" className={navClass}>
              Tiles
            </NavLink>
            {user?.role === 'admin' && (
              <NavLink to="/admin" className={navClass}>
                Admin
              </NavLink>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <UnitSystemToggle />
            <Link to="/account" className="hidden text-slate-600 hover:text-slate-900 sm:inline" title="Account">
              {user?.name} <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{user?.role}</span>
            </Link>
            <button onClick={handleLogout} className="whitespace-nowrap text-slate-600 hover:text-slate-900">
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="mx-auto flex max-w-6xl flex-wrap gap-4 px-4 pb-8 text-xs text-slate-500">
        <Link to="/privacy" className="hover:underline">
          Your plans and data
        </Link>
        <Link to="/account" className="hover:underline sm:hidden">
          Account
        </Link>
      </footer>
    </div>
  )
}
