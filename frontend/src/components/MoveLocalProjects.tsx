import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'
import type { Project } from '../api/types.ts'
import { Button, ErrorText } from './ui.tsx'

const LATER_KEY = 'fp.move-local.later'

/**
 * After signing in: projects made in this browser without an account can move into the account
 * (PRD 4.18 "optional login with cross-device sync"). Each one is imported from its backup and
 * then removed from the browser.
 */
export function MoveLocalProjects({ onMoved }: { onMoved: (project: Project) => void }) {
  const [local, setLocal] = useState<{ id: string; name: string }[]>([])
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState('')
  const [later, setLater] = useState(() => {
    try {
      return sessionStorage.getItem(LATER_KEY) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    let cancelled = false
    import('../lib/localStore.ts')
      .then(({ localStore }) => localStore.listProjects())
      .then((ps) => !cancelled && setLocal(ps.map((p) => ({ id: p.id, name: String(p.summary?.name ?? p.doc.name ?? 'Project') }))))
      .catch(() => undefined) // no browser storage: nothing to move
    return () => {
      cancelled = true
    }
  }, [])

  if (later || local.length === 0) return null

  async function move() {
    setMoving(true)
    setError('')
    const { localBackupFile } = await import('../api/guest.ts')
    const { localStore } = await import('../lib/localStore.ts')
    for (const p of local) {
      try {
        const project = await api.history.importBackup(await localBackupFile(p.id))
        await localStore.deleteProject(p.id)
        setLocal((l) => l.filter((x) => x.id !== p.id))
        onMoved(project)
      } catch (err) {
        setError(`"${p.name}" couldn't be moved: ${(err as Error).message}. It's still in this browser.`)
        break
      }
    }
    setMoving(false)
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm">
      <div className="min-w-0">
        <p className="font-medium">
          {local.length === 1 ? '1 project is' : `${local.length} projects are`} saved in this browser from before you signed in
        </p>
        <p className="text-slate-600">{local.map((p) => p.name).join(', ')}. Move them to your account to use them on any device.</p>
        <ErrorText>{error}</ErrorText>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Button type="button" onClick={move} disabled={moving}>
          {moving ? 'Moving…' : 'Move to my account'}
        </Button>
        <button
          type="button"
          onClick={() => {
            setLater(true)
            try {
              sessionStorage.setItem(LATER_KEY, '1')
            } catch {
              // not remembered
            }
          }}
          className="text-slate-600 hover:underline"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
