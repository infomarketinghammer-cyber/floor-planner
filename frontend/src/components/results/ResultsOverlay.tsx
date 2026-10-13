import { ApiImage } from '../../lib/apiImage.tsx'
import { useState } from 'react'
import { api } from '../../api/client.ts'
import type { Estimate, ReviewRoom, RoomEstimate } from '../../api/types.ts'

interface Page {
  key: string
  fileId: string
  page: number
  floors: string[]
  items: { room: ReviewRoom; result: RoomEstimate; bbox: number[] }[]
}

const PAD = 0.006

/**
 * Results on the plan (PRD 4.9): every extracted room outlined in its tile's colour and labelled
 * with its boxes. Rooms added by hand or imported have no plan location and are listed below.
 */
export function ResultsOverlay({
  projectId,
  estimate,
  rooms,
  colors,
  selectedId,
  onSelect,
}: {
  projectId: string
  estimate: Estimate
  rooms: ReviewRoom[]
  colors: Map<string, string>
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const results = new Map(estimate.rooms.map((r) => [r.room_id, r]))
  const pages = new Map<string, Page>()
  const unplaced: RoomEstimate[] = []
  for (const room of rooms) {
    const result = results.get(room.id)
    if (!result) continue // skipped rooms
    const src = room.source
    if (!src?.bbox) {
      unplaced.push(result)
      continue
    }
    const key = `${src.file_id}:${src.page}`
    const page = pages.get(key) ?? { key, fileId: src.file_id, page: src.page, floors: [], items: [] }
    page.items.push({ room, result, bbox: src.bbox })
    if (room.floor && !page.floors.includes(room.floor)) page.floors.push(room.floor)
    pages.set(key, page)
  }
  const list = [...pages.values()]
  const selectedPage = list.find((p) => p.items.some((i) => i.room.id === selectedId))?.key
  const [chosen, setChosen] = useState<string | null>(selectedPage ?? null)
  // Selecting a room in the table jumps to its page; page tabs still work afterwards.
  const [lastSelected, setLastSelected] = useState(selectedId)
  if (selectedId !== lastSelected) {
    setLastSelected(selectedId)
    if (selectedPage) setChosen(selectedPage)
  }
  const current = list.find((p) => p.key === chosen) ?? list[0]

  if (!current) {
    return (
      <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
        No rooms were read from a plan, so there's nothing to show on one.
      </p>
    )
  }

  return (
    <section aria-label="Results on the plan" className="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">On the plan</h3>
        {list.length > 1 && (
          <div role="tablist" aria-label="Plan pages" className="flex flex-wrap gap-1 text-sm">
            {list.map((p, i) => (
              <button
                key={p.key}
                role="tab"
                aria-selected={p.key === current.key}
                onClick={() => setChosen(p.key)}
                className={`rounded-full px-3 py-1 ${
                  p.key === current.key ? 'bg-brand-600 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'
                }`}
              >
                {p.floors.join(', ') || `Plan ${i + 1}`}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-lg bg-slate-100">
        <div className="relative mx-auto w-fit">
          <ApiImage
            src={api.files.previewUrl(projectId, current.fileId, current.page)}
            alt="Plan with results"
            className="block max-h-[70vh] w-auto max-w-full"
          />
          {current.items.map(({ room, result, bbox }) => {
            const [x0, y0, x1, y1] = bbox
            const color = colors.get(result.tile.id) ?? '#8a8984'
            const active = room.id === selectedId
            return (
              <button
                key={room.id}
                type="button"
                onClick={() => onSelect(room.id)}
                aria-label={`${room.name}: ${result.boxes} boxes of ${result.tile.size_label}`}
                className={`absolute rounded-sm ${active ? 'z-10 ring-4 ring-brand-600/30' : ''}`}
                style={{
                  left: `${(x0 - PAD) * 100}%`,
                  top: `${(y0 - PAD) * 100}%`,
                  width: `${(x1 - x0 + 2 * PAD) * 100}%`,
                  height: `${(y1 - y0 + 2 * PAD) * 100}%`,
                  border: `${active ? 3 : 2}px solid ${color}`,
                  background: `${color}${active ? '33' : '14'}`,
                }}
              >
                <span
                  className="absolute left-0 top-full mt-0.5 whitespace-nowrap rounded bg-white/95 px-1.5 py-0.5 text-[11px] font-medium text-slate-900 shadow-sm ring-1 ring-slate-200"
                >
                  {room.name} · {result.boxes} {result.boxes === 1 ? 'box' : 'boxes'}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        {estimate.tiles.map((t) => (
          <li key={t.tile.id} className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colors.get(t.tile.id) }} />
            {t.tile.size_label} · {t.tile.name}
          </li>
        ))}
      </ul>
      {unplaced.length > 0 && (
        <p className="text-xs text-slate-500">
          Not on a plan (added by hand or imported): {unplaced.map((r) => `${r.name} (${r.boxes})`).join(', ')}.
        </p>
      )}
    </section>
  )
}
