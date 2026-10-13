import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { Estimate, RoomLayout } from '../../api/types.ts'
import { plural } from '../../lib/format.ts'

const LAYOUT_NAMES: Record<RoomLayout['layout'], string> = {
  straight: 'Straight',
  diagonal: 'Diagonal',
  brick: 'Brick offset',
  herringbone: 'Herringbone',
  roll: 'Roll drops',
}

/**
 * A room drawn tile by tile, with the tiles that need cutting marked (PRD 4.16). The drawing
 * comes from the same engine as the quantities, so the counts match.
 */
export function TileLayoutView({
  projectId,
  estimate,
  roomId,
  version,
  onSelect,
}: {
  projectId: string
  estimate: Estimate
  roomId: string | null
  version: number
  onSelect: (id: string) => void
}) {
  // The selected room, else the first room laid with tiles or planks (a roll is just strips).
  const firstTiled = estimate.rooms.find((r) => r.kind !== 'roll') ?? estimate.rooms[0]
  const id = roomId && estimate.rooms.some((r) => r.room_id === roomId) ? roomId : (firstTiled?.room_id ?? null)
  const [layout, setLayout] = useState<RoomLayout | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    let cancelled = false
    api.materials
      .roomLayout(projectId, id)
      .then((l) => {
        if (cancelled) return
        setLayout(l)
        setError('')
      })
      .catch((err: Error) => {
        if (cancelled) return
        setLayout(null)
        setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, id, version])

  if (!id) return null
  const shown = layout && layout.room_id === id ? layout : null

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4" aria-labelledby="layout-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="layout-heading" className="font-semibold">
          Tile layout
        </h3>
        <select
          value={id}
          onChange={(e) => onSelect(e.target.value)}
          aria-label="Room to draw"
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
        >
          {estimate.rooms.map((r) => (
            <option key={r.room_id} value={r.room_id}>
              {r.name}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="mt-2 text-sm text-slate-500">{error}</p>}
      {shown && <Drawing layout={shown} />}
    </section>
  )
}

function Drawing({ layout }: { layout: RoomLayout }) {
  const xs = layout.parts.flatMap(([x, , l]) => [x, x + l])
  const ys = layout.parts.flatMap(([, y, , w]) => [y, y + w])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const pad = Math.max(x1 - x0, y1 - y0) * 0.04
  const clipId = `room-clip-${layout.room_id}`
  const whole = layout.total - layout.cut
  const piece = layout.layout === 'roll' ? 'drop' : 'tile'
  const cutWord = layout.layout === 'roll' ? 'trimmed' : 'cut'
  return (
    <div className="mt-3 space-y-3">
      <p className="text-sm text-slate-600">
        {LAYOUT_NAMES[layout.layout]} · {layout.tile.size_label} {layout.tile.name}
      </p>
      {layout.too_many ? (
        <p className="rounded-md bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
          {layout.total} tiles: too many to draw clearly.
        </p>
      ) : (
        <svg
          viewBox={`${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`}
          role="img"
          aria-label={`${layout.name}: ${plural(whole, `whole ${piece}`)} and ${plural(layout.cut, `${cutWord} ${piece}`)}`}
          className="max-h-[420px] w-full"
        >
          <defs>
            <clipPath id={clipId}>
              {layout.parts.map(([x, y, l, w], i) => (
                <rect key={i} x={x} y={y} width={l} height={w} />
              ))}
            </clipPath>
          </defs>
          <g clipPath={`url(#${clipId})`}>
            {layout.tiles.map((t, i) => (
              <polygon
                key={i}
                points={t.points.map(([x, y]) => `${x},${y}`).join(' ')}
                fill={t.cut ? '#fde68a' : '#e3f3f1'}
                stroke={t.cut ? '#d97706' : '#7cc6bd'}
                strokeWidth={Math.max(x1 - x0, y1 - y0) / 500}
              />
            ))}
          </g>
          {layout.parts.map(([x, y, l, w], i) => (
            <rect
              key={i}
              x={x}
              y={y}
              width={l}
              height={w}
              fill="none"
              stroke="#023b77"
              strokeWidth={Math.max(x1 - x0, y1 - y0) / 180}
            />
          ))}
        </svg>
      )}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-sm border border-[#7cc6bd] bg-[#e3f3f1]" />
          {plural(whole, `whole ${piece}`)}
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-sm border border-[#d97706] bg-[#fde68a]" />
          {plural(layout.cut, `${cutWord} ${piece}`)}
        </span>
        {layout.estimate_tiles !== null && (
          <span className="text-slate-500">Estimate: {plural(layout.estimate_tiles, 'tile')} before the breakage buffer</span>
        )}
      </div>
      {layout.note && <p className="text-xs text-slate-500">{layout.note}</p>}
    </div>
  )
}
