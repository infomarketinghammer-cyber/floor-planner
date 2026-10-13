import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client.ts'
import type { ActivityItem, Approval, Comment, People, ProjectRole, ShareLink, Team } from '../../api/types.ts'
import { Button, ErrorText } from '../ui.tsx'

const ROLE_NAMES: Record<string, string> = {
  owner: 'Owner',
  contractor: 'Contractor',
  designer: 'Designer',
  homeowner: 'Client',
}
const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'

function when(iso: string): string {
  const d = new Date(iso)
  const s = (Date.now() - d.getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return d.toLocaleDateString()
}

/**
 * Working together on a project (PRD 4.18): approval of the estimate, comments, people and
 * sharing, and who did what. What each person can do follows their role.
 */
export function CollabPanel({
  projectId,
  role,
  rooms,
  version,
}: {
  projectId: string
  role: ProjectRole
  rooms: { id: string; name: string }[]
  version: number
}) {
  return (
    <section className="space-y-4" aria-labelledby="collab-heading">
      <div>
        <h2 id="collab-heading" className="text-lg font-semibold">
          {role === 'homeowner' ? 'Review and approve' : 'Team and client'}
        </h2>
        <p className="text-sm text-slate-500">
          {role === 'homeowner'
            ? 'Ask questions about the estimate, then approve it or ask for changes.'
            : 'Comments, approval of the estimate, who can see this project, and what changed.'}
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ApprovalCard projectId={projectId} role={role} version={version} />
        <Comments projectId={projectId} role={role} rooms={rooms} />
      </div>
      {role !== 'homeowner' && <PeopleAndSharing projectId={projectId} role={role} />}
      <Activity projectId={projectId} version={version} />
    </section>
  )
}

function ApprovalCard({ projectId, role, version }: { projectId: string; role: ProjectRole; version: number }) {
  const [data, setData] = useState<Approval | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.collab
      .approval(projectId)
      .then((a) => !cancelled && setData(a))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [projectId, version])

  async function run(change: () => Promise<Approval>) {
    setBusy(true)
    setError('')
    try {
      setData(await change())
      setNote('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const latest = data?.decisions[0]
  const status = !data
    ? null
    : data.approved_current
      ? { text: `Approved by ${latest?.user_name}, ${when(latest!.at)}`, tone: 'bg-green-50 text-green-800' }
      : latest?.current && latest.decision === 'changes_requested'
        ? { text: `${latest.user_name} asked for changes, ${when(latest.at)}`, tone: 'bg-amber-50 text-amber-800' }
        : data.pending
          ? { text: `Waiting for approval (asked ${when(data.requested_at!)})`, tone: 'bg-brand-50 text-brand-700' }
          : latest && !latest.current
            ? { text: 'The estimate changed since it was last reviewed', tone: 'bg-slate-50 text-slate-700' }
            : { text: 'Not reviewed yet', tone: 'bg-slate-50 text-slate-600' }
  const canRequest = role === 'owner' || role === 'contractor'

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <h3 className="font-semibold">Approval of the estimate</h3>
      <ErrorText>{error}</ErrorText>
      {status && <p className={`rounded-md px-3 py-2 ${status.tone}`}>{status.text}</p>}
      {latest?.current && latest.note && <p className="text-slate-600">“{latest.note}”</p>}
      {!data?.approved_current && (
        <div className="space-y-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={1000}
            placeholder={role === 'homeowner' ? 'A note (optional), e.g. what to change' : 'A note (optional)'}
            className={`${inputClass} w-full`}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={busy} onClick={() => run(() => api.collab.decide(projectId, 'approved', note))}>
              Approve this estimate
            </Button>
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => api.collab.decide(projectId, 'changes_requested', note))}
              className="rounded-md border border-slate-300 px-3 py-2 hover:bg-slate-50"
            >
              Ask for changes
            </button>
            {canRequest && !data?.pending && (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => api.collab.requestApproval(projectId))}
                className="rounded-md border border-brand-600 px-3 py-2 font-medium text-brand-700 hover:bg-brand-50"
              >
                Ask the client to approve
              </button>
            )}
          </div>
        </div>
      )}
      {data && data.decisions.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">Earlier reviews ({data.decisions.length})</summary>
          <ul className="mt-1 space-y-1">
            {data.decisions.map((d, i) => (
              <li key={i}>
                {d.decision === 'approved' ? 'Approved' : 'Changes asked'} by {d.user_name} ({ROLE_NAMES[d.role] ?? d.role}),{' '}
                {when(d.at)}
                {!d.current && ' · earlier version'}
                {d.note && ` · “${d.note}”`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function Comments({ projectId, role, rooms }: { projectId: string; role: ProjectRole; rooms: { id: string; name: string }[] }) {
  const [items, setItems] = useState<Comment[] | null>(null)
  const [text, setText] = useState('')
  const [roomId, setRoomId] = useState('')
  const [showResolved, setShowResolved] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api.collab
      .comments(projectId)
      .then(setItems)
      .catch((err: Error) => setError(err.message))
  }, [projectId])
  useEffect(load, [load])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    try {
      const c = await api.collab.addComment(projectId, text.trim(), roomId || null)
      setItems((list) => [...(list ?? []), c])
      setText('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const visible = (items ?? []).filter((c) => showResolved || !c.resolved)
  const resolvedCount = (items ?? []).filter((c) => c.resolved).length
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Comments</h3>
        {resolvedCount > 0 && (
          <button type="button" onClick={() => setShowResolved((s) => !s)} className="text-xs text-slate-500 hover:underline">
            {showResolved ? 'Hide resolved' : `Show resolved (${resolvedCount})`}
          </button>
        )}
      </div>
      <ErrorText>{error}</ErrorText>
      {items !== null && visible.length === 0 && <p className="text-slate-500">No comments yet.</p>}
      <ul className="max-h-80 space-y-2 overflow-y-auto">
        {visible.map((c) => (
          <li key={c.id} className={`rounded-lg border border-slate-100 p-2.5 ${c.resolved ? 'opacity-60' : ''}`}>
            <p className="text-xs text-slate-500">
              <span className="font-medium text-slate-700">{c.user_name}</span> · {ROLE_NAMES[c.role] ?? c.role} · {when(c.at)}
              {c.room_name && ` · about ${c.room_name}`}
            </p>
            <p className="mt-0.5 whitespace-pre-line">{c.text}</p>
            <div className="mt-1 flex gap-3 text-xs">
              {(c.mine || role !== 'homeowner') && (
                <button
                  type="button"
                  onClick={async () => {
                    const updated = await api.collab.resolveComment(projectId, c.id, !c.resolved)
                    setItems((list) => list?.map((x) => (x.id === c.id ? updated : x)) ?? null)
                  }}
                  className="text-slate-500 hover:underline"
                >
                  {c.resolved ? 'Reopen' : 'Resolve'}
                </button>
              )}
              {(c.mine || role === 'owner') && (
                <button
                  type="button"
                  onClick={async () => {
                    await api.collab.deleteComment(projectId, c.id)
                    setItems((list) => list?.filter((x) => x.id !== c.id) ?? null)
                  }}
                  className="text-red-700 hover:underline"
                >
                  Delete
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="space-y-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Write a comment…"
          aria-label="Comment"
          className={`${inputClass} w-full`}
        />
        <div className="flex flex-wrap items-center gap-2">
          <select value={roomId} onChange={(e) => setRoomId(e.target.value)} aria-label="About" className={inputClass}>
            <option value="">About the whole estimate</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                About {r.name}
              </option>
            ))}
          </select>
          <Button type="submit" disabled={!text.trim()}>
            Comment
          </Button>
        </div>
      </form>
    </div>
  )
}

function PeopleAndSharing({ projectId, role }: { projectId: string; role: ProjectRole }) {
  const [people, setPeople] = useState<People | null>(null)
  const [teams, setTeams] = useState<Team[]>([])
  const [share, setShare] = useState<ShareLink | null>(null)
  const [email, setEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('homeowner')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const manage = role === 'owner'

  const fetchAll = useCallback(
    () =>
      Promise.all([
        api.collab.people(projectId),
        manage ? api.teams.list() : Promise.resolve([] as Team[]),
        manage ? api.collab.share(projectId) : Promise.resolve(null),
      ]),
    [projectId, manage],
  )
  const load = useCallback(async () => {
    try {
      const [p, t, sh] = await fetchAll()
      setPeople(p)
      setTeams(t)
      setShare(sh)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [fetchAll])
  useEffect(() => {
    let cancelled = false
    fetchAll()
      .then(([p, t, sh]) => {
        if (cancelled) return
        setPeople(p)
        setTeams(t)
        setShare(sh)
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [fetchAll])

  async function run(change: () => Promise<unknown>) {
    setError('')
    try {
      await change()
      await load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const link = share ? `${window.location.origin}/share/${share.token}` : ''
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <h3 className="font-semibold">Who can see this project</h3>
        <ErrorText>{error}</ErrorText>
        <ul className="divide-y divide-slate-100">
          {people?.people.map((p, i) => (
            <li key={`${p.email}-${i}`} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span>
                <span className="font-medium">{p.name}</span> <span className="text-slate-500">{p.email}</span>
              </span>
              <span className="flex items-center gap-3 text-xs">
                <span className="rounded-full bg-slate-100 px-2 py-0.5">
                  {ROLE_NAMES[p.role] ?? p.role}
                  {p.via === 'team' && ' · team'}
                  {p.via === 'invite' && ' · invited'}
                </span>
                {manage && p.via === 'project' && p.user_id && (
                  <button type="button" onClick={() => run(() => api.collab.removeMember(projectId, p.user_id!))} className="text-red-700 hover:underline">
                    Remove
                  </button>
                )}
                {manage && p.via === 'invite' && (
                  <button type="button" onClick={() => run(() => api.collab.cancelInvite(projectId, p.email))} className="text-red-700 hover:underline">
                    Cancel
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
        {manage && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (email.trim()) void run(() => api.collab.invite(projectId, email.trim(), inviteRole)).then(() => setEmail(''))
            }}
            className="flex flex-wrap gap-2"
          >
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              placeholder="Email to invite"
              aria-label="Email to invite"
              className={`${inputClass} min-w-48 flex-1`}
            />
            <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} aria-label="Role" className={inputClass}>
              <option value="homeowner">Client (view, comment, approve)</option>
              <option value="designer">Designer (edit, no costs)</option>
              <option value="contractor">Contractor (edit, costs, quotes)</option>
            </select>
            <Button type="submit">Invite</Button>
          </form>
        )}
        {manage && (
          <label className="flex flex-wrap items-center gap-2">
            <span className="text-slate-600">Team</span>
            <select
              value={people?.team?.id ?? ''}
              onChange={(e) => run(() => api.collab.setTeam(projectId, e.target.value || null))}
              className={inputClass}
            >
              <option value="">Not shared with a team</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            {teams.length === 0 && <span className="text-xs text-slate-500">Create a team on the Team page.</span>}
          </label>
        )}
      </div>

      {manage && (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
          <h3 className="font-semibold">Read-only link</h3>
          <p className="text-slate-600">
            Anyone with the link can see the results and shopping list, without signing in. Plan files, notes and people are
            never shown.
          </p>
          {share ? (
            <>
              <div className="flex gap-2">
                <input readOnly value={link} aria-label="Share link" className={`${inputClass} flex-1 bg-slate-50`} onFocus={(e) => e.target.select()} />
                <button
                  type="button"
                  onClick={async () => {
                    await navigator.clipboard.writeText(link).catch(() => undefined)
                    setCopied(true)
                    setTimeout(() => setCopied(false), 2000)
                  }}
                  className="rounded-md border border-slate-300 px-3 py-2 hover:bg-slate-50"
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={share.show_costs}
                  onChange={(e) => run(() => api.collab.updateShare(projectId, e.target.checked))}
                  className="accent-brand-600"
                />
                Include costs
              </label>
              <div className="flex gap-4">
                <button type="button" onClick={() => run(() => api.collab.createShare(projectId, share.show_costs))} className="text-slate-600 hover:underline">
                  New link (the old one stops working)
                </button>
                <button type="button" onClick={() => run(() => api.collab.deleteShare(projectId))} className="text-red-700 hover:underline">
                  Turn off
                </button>
              </div>
            </>
          ) : (
            <Button type="button" onClick={() => run(() => api.collab.createShare(projectId, false))}>
              Make a link
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function Activity({ projectId, version }: { projectId: string; version: number }) {
  const [items, setItems] = useState<ActivityItem[] | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    let cancelled = false
    api.collab
      .activity(projectId)
      .then((a) => !cancelled && setItems(a))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [projectId, open, version])
  return (
    <details className="rounded-xl border border-slate-200 bg-white" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer list-none px-4 py-3 text-sm">
        <span className="font-semibold">Activity</span> <span className="text-slate-500">who did what</span>
      </summary>
      <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto px-4 pb-3 text-sm">
        {items?.map((a, i) => (
          <li key={i} className="py-1.5">
            <span className="font-medium">{a.user_name ?? 'Someone'}</span> {a.label.charAt(0).toLowerCase() + a.label.slice(1)}{' '}
            <span className="text-slate-500">· {when(a.at)}</span>
            {a.detail && <span className="block text-xs text-slate-500">“{a.detail}”</span>}
          </li>
        ))}
        {items?.length === 0 && <li className="py-2 text-slate-500">Nothing yet.</li>}
      </ul>
    </details>
  )
}
