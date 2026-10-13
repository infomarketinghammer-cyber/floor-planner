import { useState } from 'react'
import type { Estimate, RoomEstimate } from '../../api/types.ts'

/**
 * Waste analysis (PRD 4.8): where the tile area you buy goes, per project and per room.
 * Colours: reference categorical slots 1–4 (validated: CVD ΔE ≥ 9.1, normal ≥ 22.9). Aqua and
 * yellow are under 3:1 on white, so every value is also given in text (legend + table).
 */
const PARTS = [
  { key: 'usable', label: 'Area to tile', color: '#2a78d6' },
  { key: 'cut', label: 'Cut waste', color: '#eb6834' },
  { key: 'buffer', label: 'Breakage buffer', color: '#1baf7a' },
  { key: 'rounding', label: 'Box rounding', color: '#eda100' },
] as const
type PartKey = (typeof PARTS)[number]['key']

export function WastePanel({ estimate, area }: { estimate: Estimate; area: (mm2: string | number) => string }) {
  const t = estimate.totals!
  const usable = Number(t.usable_area_mm2)
  const values: Record<PartKey, number> = {
    usable,
    cut: Number(t.cut_waste_mm2),
    buffer: Number(t.buffer_area_mm2),
    rounding: Number(t.rounding_area_mm2),
  }
  const bought = Number(t.bought_area_mm2)
  const pctOfUsable = (v: number) => (usable ? (v / usable) * 100 : 0)

  return (
    <section aria-labelledby="waste-heading" className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="waste-heading" className="font-semibold">
          Waste
        </h3>
        <p className="text-sm text-slate-600">
          You buy <strong className="text-slate-900">{area(bought)}</strong> of tiles to cover{' '}
          <strong className="text-slate-900">{area(usable)}</strong>:{' '}
          <strong className="text-slate-900">{Number(t.extra_pct).toFixed(1)}%</strong> extra.
        </p>
      </div>

      <StackedBar values={values} total={bought} area={area} />

      <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
        {PARTS.map((p) => (
          <li key={p.key} className="flex items-start gap-2">
            <span aria-hidden="true" className="mt-1 inline-block h-3 w-3 shrink-0 rounded-sm" style={{ background: p.color }} />
            <span>
              <span className="text-slate-600">{p.label}</span>
              <span className="block font-medium tabular-nums text-slate-900">
                {area(values[p.key])}
                {p.key !== 'usable' && (
                  <span className="ml-1 font-normal text-slate-500">({pctOfUsable(values[p.key]).toFixed(1)}%)</span>
                )}
              </span>
            </span>
          </li>
        ))}
      </ul>

      {t.high_waste_rooms > 0 && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          ⚠ {t.high_waste_rooms === 1 ? '1 room has' : `${t.high_waste_rooms} rooms have`} more than 20% cut waste. See
          the rooms marked below.
        </p>
      )}

      <RoomWasteTable rooms={estimate.rooms} area={area} />

      <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">💡 {estimate.offcut_note}</p>

      <details className="rounded-lg border border-slate-200" open>
        <summary className="cursor-pointer px-3 py-2 text-sm font-semibold">How these numbers were worked out</summary>
        <dl className="space-y-2 border-t border-slate-100 px-3 py-3 text-sm">
          {estimate.assumptions.map((a) => (
            <div key={a.key} className="grid gap-1 sm:grid-cols-[10rem_1fr]">
              <dt className="font-medium text-slate-700">{a.title}</dt>
              <dd className="text-slate-600">{a.text}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  )
}

/** One 100% bar of the tile area bought. 2px surface gaps between segments; hover for detail. */
function StackedBar({
  values,
  total,
  area,
}: {
  values: Record<PartKey, number>
  total: number
  area: (mm2: number) => string
}) {
  const [hover, setHover] = useState<PartKey | null>(null)
  const parts = PARTS.filter((p) => values[p.key] > 0)
  const active = PARTS.find((p) => p.key === hover)
  return (
    <div className="relative">
      <div
        role="img"
        aria-label={`Tile area bought: ${parts.map((p) => `${p.label} ${area(values[p.key])}`).join(', ')}`}
        className="flex h-6 gap-[2px] overflow-hidden rounded bg-white"
      >
        {parts.map((p, i) => (
          <div
            key={p.key}
            onMouseEnter={() => setHover(p.key)}
            onMouseLeave={() => setHover(null)}
            style={{ width: `${(values[p.key] / total) * 100}%`, background: p.color, minWidth: 3 }}
            className={`${i === 0 ? 'rounded-l' : ''} ${i === parts.length - 1 ? 'rounded-r' : ''} ${
              hover && hover !== p.key ? 'opacity-60' : ''
            } transition-opacity`}
          />
        ))}
      </div>
      {active && (
        <div className="pointer-events-none absolute -top-11 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow">
          {active.label}: {area(values[active.key])} · {((values[active.key] / total) * 100).toFixed(1)}% of tiles bought
        </div>
      )}
    </div>
  )
}

function RoomWasteTable({ rooms, area }: { rooms: RoomEstimate[]; area: (mm2: string | number) => string }) {
  const maxExtra = Math.max(...rooms.map((r) => Number(r.extra_pct)), 1)
  const pct = (part: string, r: RoomEstimate) =>
    Number(r.usable_area_mm2) ? (Number(part) / Number(r.usable_area_mm2)) * 100 : 0
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th className="py-2 pr-3 font-medium">Room</th>
            <th className="px-3 py-2 text-right font-medium">Area to tile</th>
            <th className="px-3 py-2 text-right font-medium">Cut waste</th>
            <th className="px-3 py-2 text-right font-medium">Buffer</th>
            <th className="px-3 py-2 text-right font-medium">Box rounding</th>
            <th className="px-3 py-2 text-right font-medium">Total extra</th>
            <th className="w-40 py-2 pl-3 font-medium">
              <span className="sr-only">Extra as a bar</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rooms.map((r) => {
            const cut = pct(r.cut_waste_mm2, r)
            const buf = pct(r.buffer_area_mm2, r)
            const rnd = pct(r.rounding_area_mm2, r)
            return (
              <tr key={r.room_id} className={r.high_waste ? 'bg-amber-50/60' : undefined}>
                <td className="py-2 pr-3">
                  <span className="font-medium">{r.name}</span>
                  {r.high_waste && (
                    <span className="block text-xs text-amber-800" title={r.waste_hint ?? undefined}>
                      ⚠ High cut waste
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{area(r.usable_area_mm2)}</td>
                <Cell area={area(r.cut_waste_mm2)} pct={cut} />
                <Cell area={area(r.buffer_area_mm2)} pct={buf} note={`${r.buffer_tiles} tiles`} />
                <Cell area={area(r.rounding_area_mm2)} pct={rnd} note={`${r.rounding_tiles} spare`} />
                <Cell area={area(r.extra_area_mm2)} pct={Number(r.extra_pct)} strong />
                <td className="py-2 pl-3" aria-hidden="true">
                  <div className="flex h-2.5 gap-[2px]" style={{ width: `${(Number(r.extra_pct) / maxExtra) * 100}%` }}>
                    {[
                      [cut, PARTS[1].color],
                      [buf, PARTS[2].color],
                      [rnd, PARTS[3].color],
                    ]
                      .filter(([v]) => (v as number) > 0)
                      .map(([v, color], i, arr) => (
                        <div
                          key={color as string}
                          className={`${i === 0 ? 'rounded-l-sm' : ''} ${i === arr.length - 1 ? 'rounded-r-sm' : ''}`}
                          style={{ flexGrow: v as number, background: color as string, minWidth: 2 }}
                        />
                      ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Cell({ area, pct, note, strong }: { area: string; pct: number; note?: string; strong?: boolean }) {
  return (
    <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${strong ? "font-semibold" : ""}`}>
      {area}
      <span className="block text-xs font-normal text-slate-500">
        {pct.toFixed(1)}%{note ? ` · ${note}` : ''}
      </span>
    </td>
  )
}
