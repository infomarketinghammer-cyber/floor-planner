import { useState, type ReactNode } from 'react'
import type { Cost, Estimate, ReviewRoom, RoomCost, RoomEstimate } from '../../api/types.ts'
import { plural } from '../../lib/format.ts'
import { formatMoney, type MoneyFormat } from '../../lib/money.ts'
import { formatLength } from '../../lib/units.ts'

type View = 'basic' | 'detailed'
type Grouping = 'none' | 'floor' | 'type'

const VIEW_KEY = 'fp.results.view'
const GROUP_KEY = 'fp.results.group'

// Per-viewer conveniences only; the page works the same if storage is unavailable.
function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}
function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // not persisted
  }
}

interface Totals {
  area: number
  needed: number
  cut: number
  buffer: number
  boxes: number
  bought: number
  extra: number
  cost: number // priced rooms only
}

function totalsOf(rows: RoomEstimate[], costs: Map<string, RoomCost>): Totals {
  return rows.reduce<Totals>(
    (t, r) => ({
      cost: t.cost + Number(costs.get(r.room_id)?.cost ?? 0),
      area: t.area + Number(r.usable_area_mm2),
      needed: t.needed + r.tiles_needed,
      cut: t.cut + Number(r.cut_waste_mm2),
      buffer: t.buffer + r.buffer_tiles,
      boxes: t.boxes + r.boxes,
      bought: t.bought + r.tiles_bought,
      extra: t.extra + Number(r.extra_area_mm2),
    }),
    { area: 0, needed: 0, cut: 0, buffer: 0, boxes: 0, bought: 0, extra: 0, cost: 0 },
  )
}

/**
 * Master results table (PRD 4.9): one row per room, a project total that equals the sum of the
 * rooms, Basic/Detailed views, and optional grouping by floor or room type with subtotals.
 * Cost columns (PRD 4.10) appear only once at least one room has a price.
 */
export function ResultsTable({
  estimate,
  rooms,
  area,
  colors,
  cost,
  money,
  selectedId,
  onSelect,
}: {
  estimate: Estimate
  rooms: ReviewRoom[]
  area: (mm2: number | string) => string
  colors: Map<string, string>
  cost: Cost | null
  money: MoneyFormat
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [view, setView] = useState<View>(() => readPref(VIEW_KEY, ['basic', 'detailed'] as const, 'basic'))
  const [grouping, setGrouping] = useState<Grouping>(() =>
    readPref(GROUP_KEY, ['none', 'floor', 'type'] as const, 'none'),
  )
  const detailed = view === 'detailed'
  const byId = new Map(rooms.map((r) => [r.id, r]))
  const priced = cost?.has_prices ?? false
  const costs = new Map((cost?.rooms ?? []).map((c) => [c.room_id, c]))
  const m = (v: string | number | null) => formatMoney(v, money)

  const groups: [string | null, RoomEstimate[]][] = []
  if (grouping === 'none') {
    groups.push([null, estimate.rooms])
  } else {
    const map = new Map<string, RoomEstimate[]>()
    for (const r of estimate.rooms) {
      const key = grouping === 'floor' ? (r.floor ?? 'No floor set') : r.room_type
      map.set(key, [...(map.get(key) ?? []), r])
    }
    groups.push(...map.entries())
  }
  const columns = (detailed ? 10 : 6) + (priced ? (detailed ? 2 : 1) : 0)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Results</h3>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Segmented
            label="Detail"
            value={view}
            options={[
              ['basic', 'Basic'],
              ['detailed', 'Detailed'],
            ]}
            onChange={(v) => {
              setView(v)
              writePref(VIEW_KEY, v)
            }}
          />
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">Group by</span>
            <select
              value={grouping}
              onChange={(e) => {
                setGrouping(e.target.value as Grouping)
                writePref(GROUP_KEY, e.target.value)
              }}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5"
            >
              <option value="none">Nothing</option>
              <option value="floor">Floor</option>
              <option value="type">Room type</option>
            </select>
          </label>
        </div>
      </div>

      <div className="relative overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table
          className={`w-full text-left text-sm ${detailed ? (priced ? 'min-w-[1200px]' : 'min-w-[1000px]') : priced ? 'min-w-[760px]' : 'min-w-[640px]'}`}
        >
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <Th>Room</Th>
              <Th>Size</Th>
              <Th right>{detailed ? 'Area to tile' : 'Area'}</Th>
              <Th>Tile</Th>
              {detailed && <Th right>Tiles in grid</Th>}
              {detailed && <Th right>Cut waste</Th>}
              {detailed && <Th right>Buffer</Th>}
              <Th right>Boxes</Th>
              <Th right>Tiles bought</Th>
              {detailed && <Th right>Extra area</Th>}
              {priced && detailed && <Th right>Price / box</Th>}
              {priced && <Th right>Cost</Th>}
            </tr>
          </thead>
          {groups.map(([label, rows]) => (
            <tbody key={label ?? 'all'} className="divide-y divide-slate-100 border-b border-slate-200">
              {label !== null && (
                <tr className="bg-slate-50/70">
                  <td colSpan={columns} className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    {label}
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <ResultRow
                  key={r.room_id}
                  r={r}
                  room={byId.get(r.room_id)}
                  detailed={detailed}
                  area={area}
                  cost={priced ? (costs.get(r.room_id) ?? null) : undefined}
                  money={m}
                  color={colors.get(r.tile.id)}
                  selected={r.room_id === selectedId}
                  onSelect={() => onSelect(r.room_id)}
                />
              ))}
              {label !== null && groups.length > 1 && (
                <TotalRow
                  label={`Subtotal: ${label}`}
                  t={totalsOf(rows, costs)}
                  detailed={detailed}
                  area={area}
                  money={priced ? m : undefined}
                  subtle
                />
              )}
            </tbody>
          ))}
          <tfoot>
            <TotalRow
              label="Project total"
              t={totalsOf(estimate.rooms, costs)}
              detailed={detailed}
              area={area}
              money={priced ? m : undefined}
            />
          </tfoot>
        </table>
      </div>
    </div>
  )
}

function ResultRow({
  r,
  room,
  detailed,
  area,
  cost,
  money,
  color,
  selected,
  onSelect,
}: {
  r: RoomEstimate
  room: ReviewRoom | undefined
  detailed: boolean
  area: (mm2: number | string) => string
  /** undefined: cost columns hidden; null: shown, but this room has no price. */
  cost: RoomCost | null | undefined
  money: (v: string | null) => string
  color: string | undefined
  selected: boolean
  onSelect: () => void
}) {
  const size =
    room && room.length_mm !== null && room.width_mm !== null
      ? `${formatLength(room.length_mm, room.unit)} × ${formatLength(room.width_mm, room.unit)}`
      : 'by area'
  const usable = Number(r.usable_area_mm2)
  const roomArea = Number(r.room_area_mm2)
  return (
    <tr
      onClick={onSelect}
      aria-selected={selected}
      className={`cursor-pointer align-top ${selected ? 'bg-brand-50' : r.high_waste && detailed ? 'bg-amber-50/50 hover:bg-slate-50' : 'hover:bg-slate-50'}`}
    >
      <Td>
        <span className="font-medium">{r.name}</span>
        {detailed && r.high_waste && (
          <span className="block text-xs text-amber-800" title={r.waste_hint ?? undefined}>
            ⚠ High cut waste
          </span>
        )}
      </Td>
      <Td>
        <span className="whitespace-nowrap tabular-nums">{size}</span>
      </Td>
      <Td right>
        {area(usable)}
        {detailed && usable !== roomArea && <Sub>of {area(roomArea)}</Sub>}
      </Td>
      <Td>
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          {color && <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />}
          {r.tile.size_label}
        </span>
        {detailed && <Sub>{r.layout === 'diagonal' ? 'Diagonal' : 'Straight'}</Sub>}
      </Td>
      {detailed && (
        <Td right>
          {r.kind === 'roll' ? '–' : r.tiles_needed}
          <Sub>
            {r.method === 'roll'
              ? `${r.drops ? plural(r.drops, 'drop') : 'by area'}`
              : r.method === 'grid'
                ? `${r.columns} × ${r.rows}${r.excluded_tiles ? ` − ${r.excluded_tiles}` : ''}`
                : `by area +${Number(r.allowance_pct)}%`}
          </Sub>
        </Td>
      )}
      {detailed && (
        <Td right>
          {area(r.cut_waste_mm2)}
          <Sub>{Number(r.cut_waste_pct).toFixed(1)}%</Sub>
        </Td>
      )}
      {detailed && (
        <Td right>
          {r.buffer_tiles}
          <Sub>{Number(r.breakage_pct)}%</Sub>
        </Td>
      )}
      <Td right strong>
        {r.kind === 'roll' ? '–' : r.boxes}
      </Td>
      <Td right>
        {r.kind === 'roll' ? (
          <>
            {Number((Number(r.linear_mm) / 1000).toFixed(2))} m<Sub>of roll</Sub>
          </>
        ) : (
          r.tiles_bought
        )}
      </Td>
      {detailed && (
        <Td right>
          {area(r.extra_area_mm2)}
          <Sub>{Number(r.extra_pct).toFixed(1)}%</Sub>
        </Td>
      )}
      {cost !== undefined && detailed && <Td right>{cost?.price_per_box ? money(cost.price_per_box) : '–'}</Td>}
      {cost !== undefined && (
        <Td right>
          {cost?.cost ? money(cost.cost) : <span className="text-xs text-slate-500">No price</span>}
        </Td>
      )}
    </tr>
  )
}

function TotalRow({
  label,
  t,
  detailed,
  area,
  money,
  subtle,
}: {
  label: string
  t: Totals
  detailed: boolean
  area: (mm2: number | string) => string
  /** Formats the cost of the priced rooms; undefined when the cost columns are hidden. */
  money?: (v: number) => string
  subtle?: boolean
}) {
  const cls = subtle ? 'bg-white text-slate-600' : 'border-t-2 border-slate-300 bg-slate-50 font-semibold'
  return (
    <tr className={cls}>
      <Td colSpan={2}>{label}</Td>
      <Td right>{area(t.area)}</Td>
      <Td>{''}</Td>
      {detailed && <Td right>{t.needed}</Td>}
      {detailed && (
        <Td right>
          {area(t.cut)}
          <Sub>{t.area ? ((t.cut / t.area) * 100).toFixed(1) : '0.0'}%</Sub>
        </Td>
      )}
      {detailed && <Td right>{t.buffer}</Td>}
      <Td right strong={!subtle}>
        {t.boxes}
      </Td>
      <Td right>{t.bought}</Td>
      {detailed && (
        <Td right>
          {area(t.extra)}
          <Sub>{t.area ? ((t.extra / t.area) * 100).toFixed(1) : '0.0'}%</Sub>
        </Td>
      )}
      {money && detailed && <Td>{''}</Td>}
      {money && (
        <Td right strong={!subtle}>
          {money(t.cost)}
        </Td>
      )}
    </tr>
  )
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return <th className={`px-3 py-3 font-medium ${right ? 'text-right' : ''}`}>{children}</th>
}

function Td({
  children,
  right,
  strong,
  colSpan,
}: {
  children: ReactNode
  right?: boolean
  strong?: boolean
  colSpan?: number
}) {
  return (
    <td colSpan={colSpan} className={`px-3 py-2.5 tabular-nums ${right ? 'text-right' : ''} ${strong ? 'font-semibold' : ''}`}>
      {children}
    </td>
  )
}

function Sub({ children }: { children: ReactNode }) {
  return <span className="block text-xs font-normal text-slate-500">{children}</span>
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: [T, string][]
  onChange: (v: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex rounded-md border border-slate-300 bg-white p-0.5">
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`rounded px-2.5 py-1 ${value === v ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
        >
          {text}
        </button>
      ))}
    </div>
  )
}
