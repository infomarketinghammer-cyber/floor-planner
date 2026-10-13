import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { api } from '../api/client.ts'
import type { Project } from '../api/types.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { NewProjectDialog, StatusBadge } from '../components/projects.tsx'
import { Button, ErrorText } from '../components/ui.tsx'
import {
  attentionReasons,
  formatArea,
  formatRelative,
  plural,
  projectArea,
  useAreaUnit,
  type AreaUnit,
} from '../lib/format.ts'

type SortKey = 'updated' | 'name' | 'area'

const sortOptions: { value: SortKey; label: string }[] = [
  { value: 'updated', label: 'Last updated' },
  { value: 'name', label: 'Name (A–Z)' },
  { value: 'area', label: 'Total area (largest)' },
]

function sortProjects(projects: Project[], key: SortKey, unit: AreaUnit): Project[] {
  const sorted = [...projects]
  if (key === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
  else if (key === 'area') sorted.sort((a, b) => projectArea(b, unit) - projectArea(a, unit))
  else sorted.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  return sorted
}

function latestBy(projects: Project[], field: 'updated_at' | 'last_exported_at'): Project | undefined {
  return projects.reduce<Project | undefined>((latest, p) => {
    const value = p[field]
    if (!value) return latest
    return !latest || value > (latest[field] ?? '') ? p : latest
  }, undefined)
}

export function HomePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('updated')
  const [areaUnit] = useAreaUnit()
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    api.projects
      .list()
      .then(setProjects)
      .catch((err: Error) => setError(err.message))
  }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = (projects ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q) || p.notes?.toLowerCase().includes(q),
    )
    return sortProjects(filtered, sortKey, areaUnit)
  }, [projects, query, sortKey, areaUnit])

  const attention = useMemo(() => (projects ?? []).filter((p) => p.needs_attention), [projects])
  const totalArea = useMemo(
    () => (projects ?? []).reduce((sum, p) => sum + projectArea(p, areaUnit), 0),
    [projects, areaUnit],
  )
  const lastEdited = useMemo(() => latestBy(projects ?? [], 'updated_at'), [projects])
  const lastExported = useMemo(() => latestBy(projects ?? [], 'last_exported_at'), [projects])

  async function handleCreate(data: { name: string; notes?: string }) {
    const created = await api.projects.create(data)
    setDialogOpen(false)
    navigate(`/projects/${created.id}`)
    return created
  }

  async function handleDuplicate(project: Project) {
    setBusyId(project.id)
    try {
      const copy = await api.projects.duplicate(project.id)
      setProjects((prev) => [copy, ...(prev ?? [])])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(project: Project) {
    if (!confirm(`Delete "${project.name}" and all its rooms? This cannot be undone.`)) return
    setBusyId(project.id)
    try {
      await api.projects.remove(project.id)
      setProjects((prev) => prev?.filter((p) => p.id !== project.id) ?? null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  const firstName = user?.name.split(' ')[0]
  const loading = projects === null && !error
  const isEmpty = projects?.length === 0

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Welcome back, {firstName}</h1>
          <p className="text-sm text-slate-500">Your floor plans and material estimates.</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Import a backup
            <input
              type="file"
              accept=".json,application/json"
              className="sr-only"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                setError('')
                try {
                  const project = await api.history.importBackup(file)
                  navigate(`/projects/${project.id}`)
                } catch (err) {
                  setError((err as Error).message)
                }
              }}
            />
          </label>
          <Button onClick={() => setDialogOpen(true)}>+ New project</Button>
        </div>
      </div>

      <ErrorText>{error}</ErrorText>

      {loading && <p className="text-sm text-slate-500">Loading projects…</p>}

      {isEmpty && <EmptyState onCreate={() => setDialogOpen(true)} />}

      {projects && projects.length > 0 && (
        <>
          <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Projects" value={projects.length} />
            <StatCard
              label="Needs attention"
              value={attention.length}
              tone={attention.length ? 'warning' : 'default'}
            />
            <StatCard label="Total area" value={formatArea(totalArea, areaUnit)} />
            <StatCard label="Recent activity">
              <ActivityLine label="Last edited" project={lastEdited} at={lastEdited?.updated_at} />
              <ActivityLine label="Last export" project={lastExported} at={lastExported?.last_exported_at} />
            </StatCard>
          </section>

          {attention.length > 0 && (
            <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
              <h2 className="font-semibold text-amber-900">Needs attention</h2>
              <p className="mb-3 text-sm text-amber-800">
                These projects can’t be calculated until every room is confirmed, sized and has a tile.
              </p>
              <ul className="divide-y divide-amber-200">
                {attention.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                    <Link to={`/projects/${p.id}`} className="font-medium text-amber-950 hover:underline">
                      {p.name}
                    </Link>
                    <span className="text-sm text-amber-800">{attentionReasons(p).join(' · ')}</span>
                    <Link
                      to={`/projects/${p.id}`}
                      className="ml-auto text-sm font-medium text-amber-900 hover:underline"
                    >
                      Review →
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">All projects</h2>
              <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search projects"
                  aria-label="Search projects"
                  className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm sm:w-56 sm:flex-none"
                />
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  aria-label="Sort projects"
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  {sortOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      Sort: {o.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {visible.length === 0 && (
              <p className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                No projects match “{query}”.
              </p>
            )}

            {/* Phones get cards instead of the table. */}
            <ul className="space-y-3 md:hidden">
              {visible.map((p) => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  areaUnit={areaUnit}
                  busy={busyId === p.id}
                  onDuplicate={() => handleDuplicate(p)}
                  onDelete={() => handleDelete(p)}
                />
              ))}
            </ul>

            {/* `relative` keeps the absolutely positioned sr-only header inside the scroll box. */}
            <div
              className={`relative hidden overflow-x-auto rounded-xl border border-slate-200 bg-white ${
                visible.length ? 'md:block' : ''
              }`}
            >
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Project</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 text-right font-medium">Rooms</th>
                    <th className="px-4 py-3 text-right font-medium">Total area</th>
                    <th className="px-4 py-3 font-medium">Updated</th>
                    <th className="px-4 py-3">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visible.map((p) => (
                    <tr key={p.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <Link to={`/projects/${p.id}`} className="font-medium hover:text-brand-700 hover:underline">
                          {p.name}
                        </Link>
                        {p.needs_attention && (
                          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                            needs attention
                          </span>
                        )}
                        {p.notes && <p className="max-w-xs truncate text-xs text-slate-500">{p.notes}</p>}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={p.status} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">{p.room_count}</td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {p.room_count ? formatArea(projectArea(p, areaUnit), areaUnit) : '–'}
                      </td>
                      <td className="px-4 py-3 text-slate-500" title={new Date(p.updated_at).toLocaleString()}>
                        {formatRelative(p.updated_at)}
                      </td>
                      <td className="px-4 py-3">
                        <ProjectActions
                          projectId={p.id}
                          busy={busyId === p.id}
                          onDuplicate={() => handleDuplicate(p)}
                          onDelete={() => handleDelete(p)}
                          className="justify-end"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <NewProjectDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onCreate={handleCreate} />
    </div>
  )
}

function StatCard({
  label,
  value,
  tone = 'default',
  children,
}: {
  label: string
  value?: ReactNode
  tone?: 'default' | 'warning'
  children?: ReactNode
}) {
  return (
    <div
      className={`rounded-xl border bg-white p-5 ${tone === 'warning' ? 'border-amber-300' : 'border-slate-200'}`}
    >
      <p className="text-sm text-slate-500">{label}</p>
      {value !== undefined && (
        <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone === 'warning' ? 'text-amber-700' : ''}`}>
          {value}
        </p>
      )}
      {children && <div className="mt-2 space-y-1 text-sm">{children}</div>}
    </div>
  )
}

function ActivityLine({ label, project, at }: { label: string; project?: Project; at?: string | null }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      {project && at ? (
        <p className="flex min-w-0 items-baseline gap-2">
          <Link to={`/projects/${project.id}`} className="truncate font-medium hover:underline" title={project.name}>
            {project.name}
          </Link>
          <span className="shrink-0 text-xs text-slate-400">{formatRelative(at)}</span>
        </p>
      ) : (
        <p className="text-slate-400">None yet</p>
      )}
    </div>
  )
}

function ProjectActions({
  projectId,
  busy,
  onDuplicate,
  onDelete,
  className = '',
}: {
  projectId: string
  busy: boolean
  onDuplicate: () => void
  onDelete: () => void
  className?: string
}) {
  return (
    <div className={`flex gap-4 text-sm ${className}`}>
      <Link to={`/projects/${projectId}`} className="font-medium text-brand-600 hover:underline">
        Open
      </Link>
      <button onClick={onDuplicate} disabled={busy} className="text-slate-600 hover:underline disabled:opacity-50">
        Duplicate
      </button>
      <button onClick={onDelete} disabled={busy} className="text-red-600 hover:underline disabled:opacity-50">
        Delete
      </button>
    </div>
  )
}

function ProjectCard({
  project: p,
  areaUnit,
  busy,
  onDuplicate,
  onDelete,
}: {
  project: Project
  areaUnit: AreaUnit
  busy: boolean
  onDuplicate: () => void
  onDelete: () => void
}) {
  const details = [plural(p.room_count, 'room')]
  if (p.room_count > 0) details.push(formatArea(projectArea(p, areaUnit), areaUnit))
  details.push(formatRelative(p.updated_at))

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <Link to={`/projects/${p.id}`} className="min-w-0 font-medium hover:underline">
          {p.name}
        </Link>
        <StatusBadge status={p.status} />
      </div>
      {p.needs_attention && <p className="mt-1 text-xs text-amber-700">{attentionReasons(p).join(' · ')}</p>}
      <p className="mt-2 text-sm text-slate-500">{details.join(' · ')}</p>
      <ProjectActions projectId={p.id} busy={busy} onDuplicate={onDuplicate} onDelete={onDelete} className="mt-3" />
    </li>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  const steps = [
    ['Upload', 'a blueprint (PDF, image, DXF or DWG) or a room list'],
    ['Review', 'the rooms and sizes we extract'],
    ['Assign', 'tiles to each room'],
    ['Export', 'quantities, waste and cost'],
  ]
  return (
    <section className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <h2 className="text-lg font-semibold">Create your first project</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
        Go from blueprint to a tile shopping list in minutes.
      </p>
      <ol className="mx-auto mt-6 grid max-w-3xl gap-3 text-left sm:grid-cols-4">
        {steps.map(([title, text], i) => (
          <li key={title} className="rounded-lg bg-slate-50 p-3 text-sm">
            <span className="font-semibold text-brand-700">
              {i + 1}. {title}
            </span>{' '}
            <span className="text-slate-600">{text}</span>
          </li>
        ))}
      </ol>
      <Button onClick={onCreate} className="mt-6">
        + New project
      </Button>
    </section>
  )
}
