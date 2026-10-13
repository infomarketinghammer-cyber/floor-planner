import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api } from '../api/client.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { ErrorText } from '../components/ui.tsx'

type SharedPlan = Awaited<ReturnType<typeof api.users.sharedPlans>>[number]

/** Account and data management (PRD 4.14): shared evaluation copies, and deleting the account. */
export function AccountPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [shared, setShared] = useState<SharedPlan[] | null>(null)
  const [error, setError] = useState('')
  const [password, setPassword] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    api.users
      .sharedPlans()
      .then(setShared)
      .catch((err: Error) => setError(err.message))
  }, [])

  async function removeShared(plan: SharedPlan) {
    if (!confirm(`Remove the copy of "${plan.project_name ?? 'this plan'}" from the evaluation set?`)) return
    try {
      await api.users.removeSharedPlan(plan.id)
      setShared((list) => list?.filter((p) => p.id !== plan.id) ?? null)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function deleteAccount(event: FormEvent) {
    event.preventDefault()
    setDeleting(true)
    setDeleteError('')
    try {
      await api.users.deleteAccount(password)
      await logout().catch(() => undefined) // the session is gone either way
      navigate('/', { replace: true })
    } catch (err) {
      setDeleteError((err as Error).message)
      setDeleting(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Account</h1>
        <p className="text-sm text-slate-500">
          {user?.name} · {user?.email}
          {user?.company && ` · ${user.company}`}
        </p>
      </div>
      <ErrorText>{error}</ErrorText>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">Your data</h2>
        <p className="text-sm text-slate-600">
          Plans and projects are kept until you delete them. Delete a plan file inside its project, or a whole project
          from the home page.{' '}
          <Link to="/privacy" className="text-brand-600 hover:underline">
            How your plans are handled
          </Link>
        </p>
        <div>
          <h3 className="text-sm font-medium">Plans shared for the evaluation set</h3>
          {shared === null ? null : shared.length === 0 ? (
            <p className="text-sm text-slate-500">None.</p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100 text-sm">
              {shared.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    <span className="font-medium">{p.project_name ?? 'Untitled'}</span>{' '}
                    <span className="text-slate-500">
                      · {p.files.join(', ')} · shared {new Date(p.created_at).toLocaleDateString()}
                      {!p.project_exists && ' · project deleted'}
                    </span>
                  </span>
                  <button type="button" onClick={() => removeShared(p)} className="text-red-700 hover:underline">
                    Remove copy
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="space-y-3 rounded-xl border border-red-200 bg-white p-5">
        <h2 className="font-semibold text-red-800">Delete account</h2>
        <p className="text-sm text-slate-600">
          Permanently deletes your account, every project with its plan files, your saved tiles, your feedback and any
          plans you shared for the evaluation set. This can't be undone. Download any exports you need first.
        </p>
        <form onSubmit={deleteAccount} className="space-y-3">
          <ErrorText>{deleteError}</ErrorText>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Your password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full max-w-xs rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">
              Type <strong>DELETE</strong> to confirm
            </span>
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-full max-w-xs rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <button
            type="submit"
            disabled={deleting || !password || confirmText !== 'DELETE'}
            className="rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50"
          >
            {deleting ? 'Deleting…' : 'Delete my account and data'}
          </button>
        </form>
      </section>
    </div>
  )
}
