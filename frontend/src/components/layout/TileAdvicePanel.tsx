import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { Estimate, TileAdvice, TileOption } from '../../api/types.ts'
import { plural } from '../../lib/format.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { Button } from '../ui.tsx'

const pct = (v: string) => `${Number(v)}%`
const boxes = (o: TileOption) => `${o.boxes} ${o.boxes === 1 ? 'box' : 'boxes'}`

/**
 * Best tile size for the least waste (PRD 4.16): the engine recounts each room with the other
 * tiles in the library. Also points out what reusing offcuts would save.
 */
export function TileAdvicePanel({
  projectId,
  review,
  estimate,
}: {
  projectId: string
  review: RoomsReview
  estimate: Estimate
}) {
  const state = review.state!
  const [advice, setAdvice] = useState<TileAdvice | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.materials
      .tileAdvice(projectId)
      .then((a) => !cancelled && setAdvice(a))
      .catch(() => undefined) // advice is optional
    return () => {
      cancelled = true
    }
  }, [projectId, state.version])

  const reuseSaving = estimate.rooms.reduce(
    (n, r) => n + (r.tiles_if_reused !== null && !r.reuse_applied ? r.tiles_needed - r.tiles_if_reused : 0),
    0,
  )
  const better = advice?.rooms.filter((r) => r.best) ?? []
  const projectBest = advice?.project?.best ?? null
  if (!advice?.summary && reuseSaving <= 0) return null

  async function applyInRoom(roomId: string, name: string, tileId: string, label: string) {
    await review.mutate(`Use ${label} in ${name}`, () =>
      api.materials.setRooms(projectId, { room_ids: [roomId], set: { tile_id: tileId } }, state.version),
    )
  }

  async function applyToProject(tileId: string, label: string) {
    const d = state.default_material
    await review.mutate(`Use ${label} as the project tile`, () =>
      api.materials.setDefault(
        projectId,
        {
          tile_id: tileId,
          layout: d.layout,
          breakage_pct: d.breakage_pct,
          price: null, // the price was for the old tile
          brick_offset_pct: d.brick_offset_pct,
          reuse_offcuts: d.reuse_offcuts,
        },
        state.version,
      ),
    )
  }

  return (
    <div className="space-y-2 rounded-xl border border-brand-100 bg-brand-50 p-4 text-sm">
      {advice?.summary && (
        <p>
          <span className="font-semibold">Waste tip: </span>
          {advice.summary}
        </p>
      )}
      {reuseSaving > 0 && (
        <p className="text-slate-700">
          Reusing offcuts for narrow edge pieces would save {plural(reuseSaving, 'tile')}. It needs planned cutting; turn on
          "Count on reusing offcuts" in the project defaults to use it in the quantities.
        </p>
      )}
      {(better.length > 0 || projectBest) && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="font-medium text-brand-700 hover:underline">
          {open ? 'Hide tile size suggestions' : `See tile size suggestions (${better.length + (projectBest ? 1 : 0)})`}
        </button>
      )}
      {open && (
        <ul className="space-y-2">
          {projectBest && advice?.project && (
            <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
              <span>
                <span className="font-medium">Whole project ({plural(advice.project.rooms, 'room')} on the default tile):</span>{' '}
                {projectBest.tile.size_label} {projectBest.tile.name} wastes {pct(projectBest.extra_pct)} instead of{' '}
                {pct(advice.project.current.extra_pct)} ({boxes(projectBest)} instead of {boxes(advice.project.current)}).
              </span>
              <Button type="button" disabled={review.busy} onClick={() => applyToProject(projectBest.tile.id, projectBest.tile.size_label)}>
                Use for the project
              </Button>
            </li>
          )}
          {better.map((r) => (
            <li key={r.room_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
              <span>
                <span className="font-medium">{r.name}:</span> {r.best!.tile.size_label} {r.best!.tile.name} wastes{' '}
                {pct(r.best!.extra_pct)} instead of {pct(r.current.extra_pct)} ({boxes(r.best!)} instead of{' '}
                {boxes(r.current)}).
              </span>
              <button
                type="button"
                disabled={review.busy}
                onClick={() => applyInRoom(r.room_id, r.name, r.best!.tile.id, r.best!.tile.size_label)}
                className="rounded-md border border-brand-600 px-3 py-1.5 font-medium text-brand-700 hover:bg-brand-50 disabled:opacity-50"
              >
                Use in {r.name}
              </button>
            </li>
          ))}
          <li className="text-xs text-slate-500">
            Boxes hold different numbers of tiles, so compare the cost too. Box counts here exclude other rooms.
          </li>
        </ul>
      )}
    </div>
  )
}
