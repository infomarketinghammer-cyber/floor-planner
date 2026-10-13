import { useState } from 'react'
import { api } from '../../api/client.ts'
import { formatMoney, type MoneyFormat } from '../../lib/money.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { ErrorText } from '../ui.tsx'
import { useProjectRole } from '../../lib/projectRole.ts'

type Version = Awaited<ReturnType<typeof api.history.versions>>[number]

function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

function save({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement('a'), { href: url, download: filename }).click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Project history (PRD 4.12): every change with who made it and the totals at that point;
 * any version can be restored. Also the project backup, since browser data can be cleared.
 */
export function HistoryPanel({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const state = review.state
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [error, setError] = useState('')
  const money: MoneyFormat | null = state ? state.cost_settings : null
  const { canSeeCosts } = useProjectRole()

  async function load() {
    setError('')
    try {
      setVersions(await api.history.versions(projectId))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function restore(v: Version) {
    if (!state || !confirm(`Go back to how the project was ${timeAgo(v.at)} (${v.label})? This can be undone the same way.`)) return
    const ok = await review.mutate(`Restore version from ${timeAgo(v.at)}`, () => api.history.restore(projectId, v.id, state.version))
    if (ok) await load()
  }

  return (
    <details
      className="rounded-xl border border-slate-200 bg-white"
      onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && versions === null && void load()}
    >
      <summary className="cursor-pointer list-none px-5 py-4">
        <span className="font-semibold">History and backup</span>{' '}
        <span className="text-sm text-slate-500">every change, with restore; download a copy of the project</span>
      </summary>
      <div className="space-y-4 px-5 pb-5 text-sm">
        <ErrorText>{error}</ErrorText>
        {canSeeCosts && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={async () => {
              try {
                save(await api.history.backup(projectId))
              } catch (err) {
                setError((err as Error).message)
              }
            }}
            className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-50"
          >
            Download backup
          </button>
          <span className="text-xs text-slate-500">
            One file with the rooms, settings and plan files. Import it from the home page to restore it, here or in
            another browser.
          </span>
        </div>
        )}
        {versions === null ? (
          <p className="text-slate-500">Loading…</p>
        ) : versions.length === 0 ? (
          <p className="text-slate-500">No changes recorded yet.</p>
        ) : (
          <ol className="divide-y divide-slate-100">
            {versions.map((v, i) => (
              <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="min-w-0">
                  <span className="font-medium">{v.label}</span>{' '}
                  <span className="text-slate-500">
                    · {timeAgo(v.at)}
                    {v.user_name && ` · ${v.user_name}`}
                    {typeof v.metrics.boxes === 'number' && ` · ${v.metrics.boxes} boxes`}
                    {typeof v.metrics.cost === 'string' && money && ` · ${formatMoney(v.metrics.cost, money)}`}
                  </span>
                </span>
                {i === 0 ? (
                  <span className="text-xs text-slate-400">current</span>
                ) : (
                  <button type="button" onClick={() => restore(v)} disabled={review.busy} className="text-brand-700 hover:underline">
                    Restore
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </details>
  )
}
