import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { TileUpdate } from '../../api/types.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { Button } from '../ui.tsx'

/**
 * Tiles edited in the library after this project chose them (PRD 4.12). The project keeps its
 * copy until the user updates it, so an estimate never changes unnoticed.
 */
export function TileUpdatesBanner({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const state = review.state!
  const [updates, setUpdates] = useState<TileUpdate[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    api.materials
      .tileUpdates(projectId)
      .then((u) => !cancelled && setUpdates(u))
      .catch(() => undefined) // optional
    return () => {
      cancelled = true
    }
  }, [projectId, state.version, state.extras_settings])

  const visible = updates.filter((u) => !dismissed.has(u.tile_id))
  if (visible.length === 0) return null
  const changed = visible.filter((u) => u.available)
  const removed = visible.filter((u) => !u.available)

  return (
    <div className="space-y-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm">
      {changed.map((u) => (
        <div key={u.tile_id} className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-medium">
              {u.size_label} {u.name} changed in your tile library
            </p>
            <p className="text-slate-700">
              {u.changes.map((c) => `${c.field}: ${c.old ?? '–'} → ${c.new ?? '–'}`).join(' · ')}. Used in{' '}
              {u.used_in.join(', ')}. This project still uses the old details.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <Button
              type="button"
              disabled={review.busy}
              onClick={() =>
                review.mutate(`Update ${u.name} from the library`, () =>
                  api.materials.applyTileUpdates(projectId, [u.tile_id], state.version),
                )
              }
            >
              Update and recalculate
            </Button>
            <button type="button" onClick={() => setDismissed((d) => new Set(d).add(u.tile_id))} className="text-slate-600 hover:underline">
              Keep as it was
            </button>
          </div>
        </div>
      ))}
      {removed.map((u) => (
        <p key={u.tile_id} className="text-slate-700">
          <span className="font-medium">
            {u.size_label} {u.name}
          </span>{' '}
          is no longer in your library. The project keeps its copy ({u.used_in.join(', ')}), so nothing changes.
          <button type="button" onClick={() => setDismissed((d) => new Set(d).add(u.tile_id))} className="ml-2 text-slate-600 hover:underline">
            OK
          </button>
        </p>
      ))}
    </div>
  )
}
