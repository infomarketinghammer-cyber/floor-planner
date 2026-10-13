import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../../api/client.ts'
import type { Comparison, Layout, Price, ScenarioBadge, ScenarioResult, TileRef } from '../../api/types.ts'
import { formatArea, useAreaUnit } from '../../lib/format.ts'
import { formatMoney, type MoneyFormat } from '../../lib/money.ts'
import { LAYOUT_LABELS, PriceInput } from '../materials/MaterialDialogs.tsx'
import { TilePicker } from '../materials/TilePicker.tsx'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { Button, ErrorText } from '../ui.tsx'
import { useProjectRole } from '../../lib/projectRole.ts'

const MM2_PER_SQFT = 92_903.04
const BADGES: Record<ScenarioBadge, [string, string]> = {
  lowest_cost: ['Lowest cost', 'bg-green-100 text-green-800'],
  lowest_waste: ['Least waste', 'bg-brand-100 text-brand-700'],
  fewest_boxes: ['Fewest boxes', 'bg-slate-100 text-slate-700'],
  within_budget: ['Within budget', 'bg-green-50 text-green-700'],
  over_budget: ['Over budget', 'bg-red-50 text-red-700'],
}

/**
 * Compare options (PRD 4.17): the project as it is against saved scenarios with other tiles or
 * layouts, side by side, with the best one highlighted and why.
 */
export function ScenariosSection({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const state = review.state!
  const [data, setData] = useState<Comparison | null>(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [details, setDetails] = useState(false)
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)
  const [areaUnit] = useAreaUnit()
  const money: MoneyFormat = state.cost_settings
  const deps = JSON.stringify([state.version, state.default_material, state.cost_settings, state.extras_settings])

  useEffect(() => {
    let cancelled = false
    api.scenarios
      .compare(projectId)
      .then((c) => !cancelled && setData(c))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [projectId, deps])

  async function run(change: () => Promise<Comparison | void>) {
    setError('')
    try {
      const next = await change()
      setData(next ?? (await api.scenarios.compare(projectId)))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function applyOption(r: ScenarioResult) {
    if (!confirm(`Use "${r.name}" for the project? Its tiles and layouts replace the current ones. You can undo this.`)) return
    await review.mutate(`Use option "${r.name}"`, () => api.scenarios.apply(projectId, r.id, state.version))
  }

  if (!data) return error ? <ErrorText>{error}</ErrorText> : null
  const area = (mm2: string) =>
    formatArea(areaUnit === 'sqm' ? Number(mm2) / 1_000_000 : Number(mm2) / MM2_PER_SQFT, areaUnit)
  const cols = data.results
  const best = data.best?.scenario_id
  const bestResult = cols.find((r) => r.id === best)

  return (
    <section className="space-y-4" aria-labelledby="scenarios-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="scenarios-heading" className="text-lg font-semibold">
            Compare options
          </h2>
          <p className="text-sm text-slate-500">Try other tiles or layouts on the same rooms and compare boxes, waste and cost.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              const name = prompt('Name for the current setup', 'Current setup')
              if (name?.trim()) void run(() => api.scenarios.saveCurrent(projectId, name.trim()))
            }}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
          >
            Save current setup
          </button>
          <Button type="button" onClick={() => setAdding((a) => !a)}>
            {adding ? 'Close' : 'Add an option'}
          </Button>
        </div>
      </div>
      <ErrorText>{error}</ErrorText>

      {adding && (
        <AddOptionForm
          onAdd={async (input) => {
            await run(() => api.scenarios.add(projectId, input))
            setAdding(false)
          }}
        />
      )}

      {data.suggestions.map((s) => (
        <div key={s.key} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm">
          <span>
            <span className="font-medium">💡 {s.name}.</span> {s.reason}
          </span>
          <button
            type="button"
            onClick={() =>
              run(() =>
                api.scenarios.add(projectId, {
                  name: s.name,
                  tile_id: s.tile.id,
                  layout: s.layout,
                  breakage_pct: null,
                  price: null,
                  every_room: false,
                }),
              )
            }
            className="rounded-md border border-brand-600 px-3 py-1.5 font-medium text-brand-700 hover:bg-white"
          >
            Add as an option
          </button>
        </div>
      ))}

      {cols.length < 2 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">
          Add an option, such as a different tile size or a herringbone layout, to compare it with the current setup.
        </p>
      ) : (
        <>
          {bestResult && data.best && (
            <div className="rounded-xl border-2 border-brand-500 bg-white p-4 text-sm">
              <p className="font-semibold text-brand-700">Recommended: {bestResult.name}</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">
                {data.best.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left text-sm" style={{ minWidth: 220 + cols.length * 190 }}>
              <thead>
                <tr className="border-b border-slate-200 align-top">
                  <th className="w-44 px-3 py-3 text-xs font-medium uppercase text-slate-500">Option</th>
                  {cols.map((r) => (
                    <th key={r.id} className={`px-3 py-3 font-normal ${r.id === best ? 'bg-brand-50' : ''}`}>
                      {renaming?.id === r.id ? (
                        <form
                          onSubmit={(e: FormEvent) => {
                            e.preventDefault()
                            if (renaming.name.trim()) void run(() => api.scenarios.rename(projectId, r.id, renaming.name.trim()))
                            setRenaming(null)
                          }}
                        >
                          <input
                            autoFocus
                            value={renaming.name}
                            onChange={(e) => setRenaming({ id: r.id, name: e.target.value })}
                            onBlur={() => setRenaming(null)}
                            maxLength={60}
                            aria-label="Option name"
                            className="w-full rounded border border-slate-300 px-2 py-1"
                          />
                        </form>
                      ) : (
                        <p className="font-semibold">
                          {r.name}
                          {r.id === best && <span className="ml-1 text-brand-700">★</span>}
                        </p>
                      )}
                      {r.every_room && r.id !== 'current' && <p className="text-xs text-slate-500">every room</p>}
                      <div className="mt-1 flex flex-wrap gap-1">
                        {r.badges.map((b) => (
                          <span key={b} className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${BADGES[b][1]}`}>
                            {BADGES[b][0]}
                          </span>
                        ))}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <Row label="Tiles" cols={cols} best={best}>
                  {(r) =>
                    r.ready ? (
                      <ul className="space-y-0.5">
                        {r.tiles.map((t) => (
                          <li key={t.tile.id}>
                            {t.tile.size_label} <span className="text-slate-500">{t.tile.name}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-amber-700">{r.blockers[0]}</span>
                    )
                  }
                </Row>
                <Row label="Boxes" cols={cols} best={best} strong>
                  {(r) => (r.ready ? r.boxes : '–')}
                </Row>
                <Row label="Tiles bought" cols={cols} best={best}>
                  {(r) => (r.ready ? r.tiles_bought : '–')}
                </Row>
                <Row label="Extra over area" cols={cols} best={best}>
                  {(r) =>
                    r.ready ? (
                      <>
                        {area(r.extra_area_mm2)}
                        <span className="block text-xs text-slate-500">{Number(r.extra_pct)}% of {area(r.usable_area_mm2)}</span>
                      </>
                    ) : (
                      '–'
                    )
                  }
                </Row>
                <Row label="Cut waste" cols={cols} best={best}>
                  {(r) => (r.ready ? `${Number(r.cut_waste_pct)}%` : '–')}
                </Row>
                <Row label="Total cost" cols={cols} best={best} strong>
                  {(r) =>
                    r.cost === null ? (
                      <span className="text-xs text-slate-500">No price</span>
                    ) : (
                      <>
                        {formatMoney(r.cost, money)}
                        {!r.fully_priced && <span className="block text-xs text-amber-700">Some rooms unpriced</span>}
                      </>
                    )
                  }
                </Row>
                {state.cost_settings.budget && (
                  <Row label="Budget" cols={cols} best={best}>
                    {(r) =>
                      r.budget_remaining === null ? (
                        '–'
                      ) : Number(r.budget_remaining) >= 0 ? (
                        <span className="text-green-700">{formatMoney(r.budget_remaining, money)} left</span>
                      ) : (
                        <span className="text-red-700">{formatMoney(-Number(r.budget_remaining), money)} over</span>
                      )
                    }
                  </Row>
                )}
                <tr>
                  <td className="px-3 py-2.5 text-xs text-slate-500" />
                  {cols.map((r) => (
                    <td key={r.id} className={`px-3 py-2.5 ${r.id === best ? 'bg-brand-50' : ''}`}>
                      {r.id === 'current' ? (
                        <span className="text-xs text-slate-500">The project now</span>
                      ) : (
                        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                          <button type="button" onClick={() => applyOption(r)} disabled={review.busy} className="font-medium text-brand-700 hover:underline">
                            Use this
                          </button>
                          <button type="button" onClick={() => setRenaming({ id: r.id, name: r.name })} className="text-slate-600 hover:underline">
                            Rename
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              confirm(`Delete the option "${r.name}"?`) && run(() => api.scenarios.remove(projectId, r.id))
                            }
                            className="text-red-700 hover:underline"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <button type="button" onClick={() => setDetails((d) => !d)} className="text-sm font-medium text-brand-700 hover:underline">
            {details ? 'Hide room by room' : 'Compare room by room'}
          </button>
          {details && <RoomByRoom cols={cols} money={money} />}
        </>
      )}
    </section>
  )
}

function Row({
  label,
  cols,
  best,
  strong,
  children,
}: {
  label: string
  cols: ScenarioResult[]
  best: string | undefined
  strong?: boolean
  children: (r: ScenarioResult) => ReactNode
}) {
  return (
    <tr className="align-top">
      <th scope="row" className="px-3 py-2.5 text-xs font-medium uppercase text-slate-500">
        {label}
      </th>
      {cols.map((r) => (
        <td key={r.id} className={`px-3 py-2.5 tabular-nums ${strong ? 'font-semibold' : ''} ${r.id === best ? 'bg-brand-50' : ''}`}>
          {children(r)}
        </td>
      ))}
    </tr>
  )
}

function RoomByRoom({ cols, money }: { cols: ScenarioResult[]; money: MoneyFormat }) {
  const ready = cols.filter((c) => c.ready)
  const rooms = ready[0]?.rooms ?? []
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm" style={{ minWidth: 200 + ready.length * 170 }}>
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Room</th>
            {ready.map((c) => (
              <th key={c.id} className="px-3 py-2 font-medium">
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rooms.map((room) => (
            <tr key={room.room_id} className="align-top">
              <td className="px-3 py-2 font-medium">{room.name}</td>
              {ready.map((c) => {
                const r = c.rooms.find((x) => x.room_id === room.room_id)
                return (
                  <td key={c.id} className="px-3 py-2 tabular-nums">
                    {r ? (
                      <>
                        {r.boxes} {r.boxes === 1 ? 'box' : 'boxes'} · {Number(r.extra_pct)}% extra
                        <span className="block text-xs text-slate-500">
                          {r.tile.size_label} · {LAYOUT_LABELS[r.layout]}
                          {r.cost !== null && ` · ${formatMoney(r.cost, money)}`}
                        </span>
                      </>
                    ) : (
                      '–'
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AddOptionForm({
  onAdd,
}: {
  onAdd: (input: {
    name: string
    tile_id: string | null
    layout: Layout | null
    breakage_pct: string | null
    price: Price | null
    every_room: boolean
  }) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [tile, setTile] = useState<TileRef | null>(null)
  const [layout, setLayout] = useState<Layout | ''>('')
  const [breakage, setBreakage] = useState('')
  const [price, setPrice] = useState<Price | null>(null)
  const [everyRoom, setEveryRoom] = useState(false)
  const { canSeeCosts } = useProjectRole()
  const [saving, setSaving] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      await onAdd({
        name: name.trim() || (tile ? tile.size_label : layout ? LAYOUT_LABELS[layout] : 'Option'),
        tile_id: tile?.id ?? null,
        layout: layout || null,
        breakage_pct: breakage.trim() || null,
        price,
        every_room: everyRoom,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto]">
        <label className="block">
          <span className="mb-1 block text-slate-600">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder="e.g. 800×800 polished"
            className="w-full rounded-md border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Tile</span>
          <TilePicker label="Option tile" value={tile} onChange={(t) => setTile({ ...t })} placeholder="Keep the project tile" />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Layout</span>
          <select value={layout} onChange={(e) => setLayout(e.target.value as Layout | '')} className="rounded-md border border-slate-300 bg-white px-3 py-2">
            <option value="">Keep the project layout</option>
            {(Object.keys(LAYOUT_LABELS) as Layout[]).map((l) => (
              <option key={l} value={l}>
                {LAYOUT_LABELS[l]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="mb-1 block text-slate-600">Breakage buffer</span>
          <span className="flex items-center gap-1.5">
            <input
              value={breakage}
              onChange={(e) => setBreakage(e.target.value)}
              inputMode="decimal"
              placeholder="same"
              className="w-20 rounded-md border border-slate-300 px-3 py-2"
            />
            %
          </span>
        </label>
        {canSeeCosts && (
          <div>
            <span className="mb-1 block text-slate-600">Price of this tile (optional)</span>
            <PriceInput value={price} onChange={setPrice} />
          </div>
        )}
        <label className="flex items-center gap-2 pb-2">
          <input type="checkbox" checked={everyRoom} onChange={(e) => setEveryRoom(e.target.checked)} className="accent-brand-600" />
          Use in every room, even rooms with their own tile
        </label>
      </div>
      <p className="text-xs text-slate-500">
        Rooms with their own tile (like an anti-skid bathroom) keep it unless you tick the box. Without a price, this option
        is compared on boxes and waste only.
      </p>
      <Button type="submit" disabled={saving || (!tile && !layout)}>
        {saving ? 'Adding…' : 'Add option'}
      </Button>
    </form>
  )
}
