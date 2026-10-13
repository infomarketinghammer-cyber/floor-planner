import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api/client.ts'
import type { Team } from '../api/types.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { Button, ErrorText } from '../components/ui.tsx'

const ROLE_NAMES: Record<string, string> = { owner: 'Owner', contractor: 'Contractor', designer: 'Designer' }
const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'

/**
 * Teams (PRD 4.18): your company's contractors and designers. Share a project with the team
 * from its page, and everyone in the team can work on it in their role.
 */
export function TeamPage() {
  const { user } = useAuth()
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api.teams
      .list()
      .then(setTeams)
      .catch((err: Error) => setError(err.message))
  }, [])

  async function run(change: () => Promise<unknown>) {
    setError('')
    try {
      await change()
      setTeams(await api.teams.list())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Team</h1>
        <p className="text-sm text-slate-500">
          Contractors can edit, see costs and make quotes. Designers edit rooms and tiles, without costs. Invite clients to a
          single project from the project's page.
        </p>
      </div>
      <ErrorText>{error}</ErrorText>
      {teams?.map((t) => (
        <TeamCard key={t.id} team={t} me={user?.id ?? ''} run={run} />
      ))}
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          if (name.trim()) void run(() => api.teams.create(name.trim())).then(() => setName(''))
        }}
        className="flex flex-wrap items-end gap-2 rounded-xl border border-dashed border-slate-300 bg-white p-4"
      >
        <label className="block flex-1 text-sm">
          <span className="mb-1 block text-slate-600">{teams?.length ? 'Another team' : 'Create your team'}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="e.g. Asha Tiling" className={`${inputClass} w-full`} />
        </label>
        <Button type="submit" disabled={!name.trim()}>
          Create team
        </Button>
      </form>
    </div>
  )
}

function TeamCard({ team, me, run }: { team: Team; me: string; run: (change: () => Promise<unknown>) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('contractor')
  const owner = team.my_role === 'owner'
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{team.name}</h2>
        <span className="text-slate-500">
          {team.projects} shared project{team.projects === 1 ? '' : 's'} · you are {ROLE_NAMES[team.my_role]?.toLowerCase() ?? team.my_role}
        </span>
      </div>
      <ul className="divide-y divide-slate-100">
        {team.members.map((m) => (
          <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              <span className="font-medium">{m.name}</span> <span className="text-slate-500">{m.email}</span>
            </span>
            <span className="flex items-center gap-3">
              {owner && m.role !== 'owner' ? (
                <select
                  value={m.role}
                  onChange={(e) => run(() => api.teams.setRole(team.id, m.user_id, e.target.value))}
                  aria-label={`Role of ${m.name}`}
                  className="rounded-md border border-slate-300 px-2 py-1"
                >
                  <option value="contractor">Contractor</option>
                  <option value="designer">Designer</option>
                </select>
              ) : (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{ROLE_NAMES[m.role] ?? m.role}</span>
              )}
              {m.role !== 'owner' && (owner || m.user_id === me) && (
                <button
                  type="button"
                  onClick={() =>
                    confirm(m.user_id === me ? `Leave ${team.name}?` : `Remove ${m.name} from ${team.name}?`) &&
                    run(() => api.teams.removeMember(team.id, m.user_id))
                  }
                  className="text-red-700 hover:underline"
                >
                  {m.user_id === me ? 'Leave' : 'Remove'}
                </button>
              )}
            </span>
          </li>
        ))}
        {team.invites.map((i) => (
          <li key={i.email} className="flex flex-wrap items-center justify-between gap-2 py-2 text-slate-500">
            <span>
              {i.email} · invited as {ROLE_NAMES[i.role]?.toLowerCase() ?? i.role}, joins when they sign up
            </span>
            {owner && (
              <button type="button" onClick={() => run(() => api.teams.cancelInvite(team.id, i.email))} className="text-red-700 hover:underline">
                Cancel
              </button>
            )}
          </li>
        ))}
      </ul>
      {owner && (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (email.trim()) void run(() => api.teams.addMember(team.id, email.trim(), role)).then(() => setEmail(''))
            }}
            className="flex flex-wrap gap-2"
          >
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="Email" aria-label="Email to add" className={`${inputClass} min-w-48 flex-1`} />
            <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role" className={inputClass}>
              <option value="contractor">Contractor</option>
              <option value="designer">Designer</option>
            </select>
            <Button type="submit">Add</Button>
          </form>
          <button
            type="button"
            onClick={() => confirm(`Delete ${team.name}? Projects stay with their owners.`) && run(() => api.teams.remove(team.id))}
            className="text-xs text-red-700 hover:underline"
          >
            Delete team
          </button>
        </>
      )}
    </section>
  )
}
