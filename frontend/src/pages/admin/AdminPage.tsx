import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { AdminStats, User } from '../../api/types.ts'
import { useAuth } from '../../auth/AuthContext.tsx'
import { ErrorText } from '../../components/ui.tsx'
import { AccuracyPanel } from './AccuracyPanel.tsx'
import { PlatformPanel } from './PlatformPanel.tsx'

export function AdminPage() {
  const { user: me } = useAuth()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.admin.stats(), api.admin.users()])
      .then(([s, u]) => {
        setStats(s)
        setUsers(u)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  async function update(target: User, changes: Partial<Pick<User, 'role' | 'is_active'>>) {
    try {
      const updated = await api.admin.updateUser(target.id, changes)
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Admin</h1>
      <ErrorText>{error}</ErrorText>

      <div className="grid gap-4 sm:grid-cols-3">
        {(
          [
            ['Contractors', stats?.contractors],
            ['Admins', stats?.admins],
            ['Projects', stats?.projects],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-5">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">{value ?? '–'}</p>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => {
              const isSelf = u.id === me?.id
              return (
                <tr key={u.id}>
                  <td className="px-4 py-3 font-medium">{u.name}</td>
                  <td className="px-4 py-3">{u.email}</td>
                  <td className="px-4 py-3 text-slate-500">{u.company ?? '–'}</td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      disabled={isSelf}
                      onChange={(e) => update(u, { role: e.target.value as User['role'] })}
                      className="rounded border border-slate-300 px-2 py-1"
                    >
                      <option value="contractor">contractor</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      disabled={isSelf}
                      onClick={() => update(u, { is_active: !u.is_active })}
                      className={`rounded-full px-2 py-0.5 text-xs disabled:opacity-50 ${
                        u.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {u.is_active ? 'active' : 'disabled'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <PlatformPanel />
      <AccuracyPanel />
    </div>
  )
}
