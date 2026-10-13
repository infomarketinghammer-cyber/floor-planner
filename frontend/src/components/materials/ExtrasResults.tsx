import type { Estimate } from '../../api/types.ts'
import { plural } from '../../lib/format.ts'

const metres = (mm: string | number) => `${Number((Number(mm) / 1000).toFixed(2))} m`
const boxes = (n: number) => `${n} ${n === 1 ? 'box' : 'boxes'}`

/** Wall tiles, skirting and sundries (PRD 4.15), worked out with the floor quantities. */
export function ExtrasResults({ estimate, area }: { estimate: Estimate; area: (mm2: string | number) => string }) {
  const x = estimate.extras
  if (!x) return null
  return (
    <section className="space-y-3" aria-labelledby="extras-heading">
      <h3 id="extras-heading" className="font-semibold">
        Walls, skirting &amp; sundries
      </h3>
      {x.warnings.map((w) => (
        <p key={w} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {w}
        </p>
      ))}

      {x.walls.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="border-b border-slate-100 px-4 py-3 text-left text-sm font-semibold">Wall tiles</caption>
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Room</th>
                <th className="px-3 py-2 font-medium">Tile</th>
                <th className="px-3 py-2 text-right font-medium">Height</th>
                <th className="px-3 py-2 text-right font-medium">Wall length</th>
                <th className="px-3 py-2 text-right font-medium">Area to tile</th>
                <th className="px-3 py-2 text-right font-medium">Tiles</th>
                <th className="px-3 py-2 text-right font-medium">Boxes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {x.walls.map((w) => (
                <tr key={w.room_id}>
                  <td className="px-3 py-2 font-medium">{w.name}</td>
                  <td className="px-3 py-2">
                    {w.tile.size_label} <span className="text-slate-500">{w.tile.name}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{metres(w.height_mm)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{metres(w.length_mm)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {area(w.net_area_mm2)}
                    {Number(w.openings_area_mm2) > 0 && (
                      <span className="block text-xs text-slate-500">after {area(w.openings_area_mm2)} of openings</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {w.tiles_required}
                    <span className="block text-xs text-slate-500">incl. {w.buffer_tiles} buffer</span>
                  </td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">{w.boxes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {x.skirting && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
            <h4 className="font-semibold">Skirting ({Number(x.skirting.height_mm)} mm high)</h4>
            <p className="text-slate-500">
              {metres(x.skirting.run_mm)} across {plural(x.skirting.rooms.length, 'room')}, door widths left out
            </p>
            <ul className="mt-2 space-y-1.5">
              {x.skirting.products.map((p) => (
                <li key={p.label} className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    {p.label}
                    <span className="block text-xs text-slate-500">
                      {p.tile
                        ? `${p.tiles} tiles cut into ${p.pieces} strips of ${metres(p.piece_length_mm)} (${p.strips_per_tile} per tile)`
                        : `${p.pieces} pieces of ${metres(p.piece_length_mm)}`}
                    </span>
                  </span>
                  <span className="whitespace-nowrap font-semibold tabular-nums">
                    {p.boxes !== null ? boxes(p.boxes) : `${p.pieces} pieces`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {x.sundries.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
            <h4 className="font-semibold">Adhesive, grout &amp; spacers</h4>
            <p className="text-slate-500">For {area(x.sundries[0].area_mm2)} of tiled floor and wall</p>
            <ul className="mt-2 space-y-1.5">
              {x.sundries.map((s) => (
                <li key={s.key} className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    {s.label}
                    <span className="block text-xs text-slate-500">
                      {Number(s.quantity)} {s.unit} · {s.basis}
                    </span>
                  </span>
                  <span className="whitespace-nowrap font-semibold tabular-nums">
                    {s.packs} {s.key === 'adhesive' ? 'bags' : 'packs'}
                    <span className="block text-right text-xs font-normal text-slate-500">
                      of {Number(s.pack_size)} {s.unit}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
