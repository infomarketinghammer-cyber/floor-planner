import { useState } from 'react'
import { api } from '../../api/client.ts'
import type { Layout, MaterialField, Price, ProjectMaterial, ReviewRoom, TileRef } from '../../api/types.ts'
import { formatArea, formatPrice, plural, useAreaUnit } from '../../lib/format.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { Button, ErrorText } from '../ui.tsx'
import {
  ExclusionsDialog,
  LAYOUT_LABELS,
  LayoutToggle,
  MaterialDialog,
  PriceInput,
  type ExclusionRow,
  type MaterialChange,
} from './MaterialDialogs.tsx'
import { ExtrasSettingsCard, SuggestionsPanel, WallsDialog, wallsSummary, type WallsPreset } from './ExtrasDialogs.tsx'
import { TilePicker } from './TilePicker.tsx'

const MM2_PER_SQFT = 92_903.04

/** Material assignment (PRD 4.6). Shares room state and undo history with the review section. */
export function MaterialsSection({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const { state, mutate, busy } = review
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<ReviewRoom[] | null>(null)
  const [excluding, setExcluding] = useState<ReviewRoom | null>(null)
  // Walls & doors: one room, or a queue of rooms from a suggestion (opened one after another).
  const [walling, setWalling] = useState<{ ids: string[]; preset?: WallsPreset } | null>(null)
  const [copyFrom, setCopyFrom] = useState('')
  const [areaUnit] = useAreaUnit()

  if (!state || state.rooms.length === 0) return null
  const { rooms, materials } = state
  const version = state.version
  const chosen = rooms.filter((r) => selected.has(r.id))
  const allSelected = chosen.length === rooms.length

  const area = (mm2: number) => formatArea(areaUnit === 'sqm' ? mm2 / 1_000_000 : mm2 / MM2_PER_SQFT, areaUnit)

  type RoomsChange = Partial<MaterialChange> & { skipped?: boolean }
  const save = (ids: string[], change: RoomsChange) => () =>
    api.materials.setRooms(projectId, { room_ids: ids, ...change }, version)
  // Quick actions: errors show in this section. Dialogs use `rethrow` to show them in the dialog.
  const applyToRooms = (label: string, ids: string[], change: RoomsChange) => mutate(label, save(ids, change))

  async function copySettings(sourceId: string) {
    const source = rooms.find((r) => r.id === sourceId)
    const targets = chosen.filter((r) => r.id !== sourceId)
    if (!source || targets.length === 0) return
    // Copy exactly what the source room overrides; everything else follows the project default.
    const own = source.material
    const change: MaterialChange = { set: {}, inherit: [] }
    const fields: MaterialField[] = ['tile', 'layout', 'breakage_pct', 'price']
    for (const f of fields) {
      if (own[f] === null) change.inherit.push(f)
    }
    if (own.tile) change.set.tile_id = own.tile.id
    if (own.layout) change.set.layout = own.layout
    if (own.breakage_pct) change.set.breakage_pct = own.breakage_pct
    if (own.price) change.set.price = own.price
    await mutate(`Copy ${source.name}'s settings to ${plural(targets.length, 'room')}`, () =>
      api.materials.setRooms(projectId, { room_ids: targets.map((r) => r.id), ...change }, version),
    )
    setCopyFrom('')
  }

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Tiles &amp; materials</h2>
          <p className="text-sm text-slate-500">
            Set a default for the whole project, then change any room that's different.
          </p>
        </div>
        <MaterialsStatus state={state} />
      </div>

      <DefaultsCard
        key={JSON.stringify(state.default_material)}
        defaults={state.default_material}
        busy={busy}
        onSave={(data) =>
          mutate('Change project tile defaults', () => api.materials.setDefault(projectId, data, version), {
            rethrow: true,
          })
        }
      />

      <ExtrasSettingsCard key={JSON.stringify(state.extras_settings)} projectId={projectId} review={review} />
      <SuggestionsPanel projectId={projectId} review={review} onTileWalls={(ids, preset) => setWalling({ ids, preset })} />

      {chosen.length > 0 && (
        <div className="sticky top-2 z-20 flex flex-wrap items-center gap-2 rounded-xl border border-brand-600/30 bg-brand-50 px-4 py-3 text-sm shadow-sm">
          <span className="font-medium">{plural(chosen.length, 'room')} selected</span>
          <Button onClick={() => setEditing(chosen)} disabled={busy}>
            Edit settings
          </Button>
          <select
            value={copyFrom}
            onChange={(e) => {
              setCopyFrom(e.target.value)
              if (e.target.value) void copySettings(e.target.value)
            }}
            aria-label="Copy settings from room"
            disabled={busy}
            className="rounded-md border border-slate-300 bg-white px-3 py-2"
          >
            <option value="">Copy settings from…</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <SmallButton
            onClick={() =>
              applyToRooms(`Reset ${plural(chosen.length, 'room')} to project default`, [...selected], {
                inherit: ['tile', 'layout', 'breakage_pct', 'price'],
              })
            }
          >
            Use project default
          </SmallButton>
          <SmallButton
            onClick={() =>
              applyToRooms(`Mark ${plural(chosen.length, 'room')} as not tiled`, [...selected], { skipped: true })
            }
          >
            No tiling
          </SmallButton>
          <SmallButton
            onClick={() =>
              applyToRooms(`Tile ${plural(chosen.length, 'room')}`, [...selected], { skipped: false })
            }
          >
            Tile them
          </SmallButton>
          <button onClick={() => setSelected(new Set())} className="ml-auto text-slate-600 hover:underline">
            Clear selection
          </button>
        </div>
      )}

      <ErrorText>{review.error}</ErrorText>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="hidden grid-cols-[2rem_minmax(0,1.3fr)_minmax(0,1.6fr)_6rem_5rem_7rem_minmax(0,1fr)_8.5rem] gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3 text-xs font-medium uppercase text-slate-500 md:grid">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={() => setSelected(allSelected ? new Set() : new Set(rooms.map((r) => r.id)))}
            aria-label="Select all rooms"
            className="accent-brand-600"
          />
          <span>Room</span>
          <span>Tile</span>
          <span>Layout</span>
          <span>Buffer</span>
          <span>Price</span>
          <span>Untiled areas</span>
          <span className="sr-only">Actions</span>
        </div>
        <ul className="divide-y divide-slate-100">
          {rooms.map((room) => (
            <MaterialRow
              key={room.id}
              room={room}
              area={area}
              selected={selected.has(room.id)}
              onToggle={() => toggle(room.id)}
              onEdit={() => setEditing([room])}
              onExclusions={() => setExcluding(room)}
              onWalls={() => setWalling({ ids: [room.id] })}
              onSkip={(skipped) =>
                applyToRooms(`${skipped ? 'Skip' : 'Tile'} ${room.name}`, [room.id], { skipped })
              }
              busy={busy}
            />
          ))}
        </ul>
      </div>
      {materials.skipped > 0 && (
        <p className="text-xs text-slate-500">
          {plural(materials.skipped, 'room')} marked "No tiling" {materials.skipped === 1 ? 'is' : 'are'} left out of the
          review and the estimate.
        </p>
      )}

      {editing && (
        <MaterialDialog
          rooms={editing}
          defaults={state.default_material}
          onClose={() => setEditing(null)}
          onApply={async (change) => {
            await mutate(
              editing.length === 1 ? `Change tile settings of ${editing[0].name}` : `Change ${plural(editing.length, 'room')}`,
              save(
                editing.map((r) => r.id),
                change,
              ),
              { rethrow: true },
            )
            setEditing(null)
          }}
        />
      )}
      {walling && rooms.some((r) => r.id === walling.ids[0]) && (
        <WallsDialog
          key={walling.ids[0]}
          room={rooms.find((r) => r.id === walling.ids[0])!}
          settings={state.extras_settings}
          preset={walling.preset}
          onClose={() => setWalling(null)}
          onSave={async (data) => {
            const room = rooms.find((r) => r.id === walling.ids[0])!
            await mutate(
              `Change walls & doors of ${room.name}`,
              () => api.materials.setRoomWalls(projectId, room.id, data, version),
              { rethrow: true },
            )
            const rest = walling.ids.slice(1)
            setWalling(rest.length ? { ids: rest, preset: walling.preset } : null)
          }}
        />
      )}
      {excluding && (
        <ExclusionsDialog
          room={excluding}
          onClose={() => setExcluding(null)}
          onSave={async (rows: ExclusionRow[]) => {
            await mutate(
              `Change untiled areas of ${excluding.name}`,
              () => api.materials.setExclusions(projectId, excluding.id, rows, version),
              { rethrow: true },
            )
            setExcluding(null)
          }}
        />
      )}
    </section>
  )
}

function MaterialsStatus({ state }: { state: NonNullable<RoomsReview['state']> }) {
  const m = state.materials
  if (m.ready_for_calculation) {
    return (
      <span role="status" className="rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800">
        ✓ Ready to calculate
      </span>
    )
  }
  const reasons = []
  if (m.rooms_needing_tile) reasons.push(`${plural(m.rooms_needing_tile, 'room')} without a tile`)
  if (m.rooms_over_excluded) reasons.push(`${plural(m.rooms_over_excluded, 'room')} fully excluded`)
  if (!state.review.ready) reasons.push('review not finished')
  return (
    <span role="status" className="rounded-full bg-amber-100 px-3 py-1 text-sm text-amber-800">
      {reasons.join(' · ')}
    </span>
  )
}

function SmallButton({ children, onClick }: { children: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-slate-300 bg-white px-3 py-2 font-medium hover:bg-slate-50">
      {children}
    </button>
  )
}

function DefaultsCard({
  defaults,
  busy,
  onSave,
}: {
  defaults: ProjectMaterial
  busy: boolean
  onSave: (data: { tile_id: string | null; layout: Layout; breakage_pct: string; price: Price | null }) => Promise<boolean>
}) {
  const [tile, setTile] = useState<TileRef | null>(defaults.tile)
  const [layout, setLayout] = useState<Layout>(defaults.layout)
  const [buffer, setBuffer] = useState(String(Number(defaults.breakage_pct)))
  const [price, setPrice] = useState<Price | null>(defaults.price)
  const [error, setError] = useState('')

  const dirty =
    tile?.id !== defaults.tile?.id ||
    layout !== defaults.layout ||
    Number(buffer) !== Number(defaults.breakage_pct) ||
    JSON.stringify(price) !== JSON.stringify(defaults.price)

  async function save() {
    setError('')
    try {
      await onSave({ tile_id: tile?.id ?? null, layout, breakage_pct: buffer.trim() || '0', price })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold">Project defaults</h3>
      <ErrorText>{error}</ErrorText>
      <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_auto_auto_auto] md:items-end">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Tile</span>
          <TilePicker label="Project default tile" value={tile} onChange={(t) => setTile({ ...t })} placeholder="Choose the main tile" />
        </label>
        <div className="text-sm">
          <span className="mb-1 block text-slate-600">Layout</span>
          <LayoutToggle value={layout} onChange={setLayout} />
        </div>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Breakage buffer</span>
          <span className="flex items-center gap-1.5">
            <input
              value={buffer}
              onChange={(e) => setBuffer(e.target.value)}
              inputMode="decimal"
              aria-label="Default breakage buffer percent"
              className="w-20 rounded-md border border-slate-300 px-3 py-2"
            />
            %
          </span>
        </label>
        <div className="text-sm">
          <span className="mb-1 block text-slate-600">Price (optional)</span>
          <PriceInput value={price} onChange={setPrice} />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={!dirty || busy}>
          Save defaults
        </Button>
        {dirty && <span className="text-xs text-amber-700">Unsaved changes</span>}
      </div>
    </div>
  )
}

function MaterialRow({
  room,
  area,
  selected,
  onToggle,
  onEdit,
  onExclusions,
  onWalls,
  onSkip,
  busy,
}: {
  room: ReviewRoom
  area: (mm2: number) => string
  selected: boolean
  onToggle: () => void
  onEdit: () => void
  onExclusions: () => void
  onWalls: () => void
  onSkip: (skipped: boolean) => Promise<boolean>
  busy: boolean
}) {
  const eff = room.effective
  const own = (f: MaterialField) => eff.overridden.includes(f)
  const tag = (f: MaterialField) =>
    own(f) ? (
      <span className="ml-1 rounded bg-brand-50 px-1 text-[10px] font-semibold uppercase text-brand-700">own</span>
    ) : null
  const fullArea =
    room.length_mm && room.width_mm
      ? Number(room.length_mm) * Number(room.width_mm)
      : room.area_mm2
        ? Number(room.area_mm2) // odd-shaped room known only by area
        : null
  const excluded = Number(room.exclusion_area_mm2)
  const usable = room.usable_area_mm2 !== null ? Number(room.usable_area_mm2) : null

  return (
    <li
      className={`grid grid-cols-[2rem_1fr] gap-x-3 gap-y-2 px-4 py-3 text-sm md:grid-cols-[2rem_minmax(0,1.3fr)_minmax(0,1.6fr)_6rem_5rem_7rem_minmax(0,1fr)_8.5rem] md:items-center ${
        room.skipped ? 'bg-slate-50 text-slate-400' : selected ? 'bg-brand-50/50' : ''
      }`}
    >
      <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${room.name}`} className="accent-brand-600" />
      <div className="min-w-0">
        <p className={`truncate font-medium ${room.skipped ? '' : 'text-slate-900'}`}>{room.name}</p>
        <p className="text-xs text-slate-500">
          {fullArea === null ? 'Size missing' : area(fullArea)}
          {excluded > 0 && usable !== null && <> · {area(usable)} to tile</>}
        </p>
        {!room.skipped && wallsSummary(room) && <p className="text-xs text-brand-700">{wallsSummary(room)}</p>}
      </div>
      {room.skipped ? (
        <p className="col-start-2 md:col-span-5">No tiling</p>
      ) : (
        <>
          <div className="col-start-2 min-w-0 md:col-start-auto">
            {eff.tile ? (
              <p className="truncate" title={eff.tile.name}>
                {eff.tile.size_label}
                {tag('tile')}
                <span className="block truncate text-xs text-slate-500">{eff.tile.name}</span>
              </p>
            ) : (
              <p className="font-medium text-amber-700">No tile yet</p>
            )}
          </div>
          <p className="col-start-2 md:col-start-auto">
            <span className="text-slate-500 md:hidden">Layout: </span>
            {LAYOUT_LABELS[eff.layout]}
            {tag('layout')}
          </p>
          <p className="col-start-2 tabular-nums md:col-start-auto">
            <span className="text-slate-500 md:hidden">Buffer: </span>
            {Number(eff.breakage_pct)}%{tag('breakage_pct')}
          </p>
          <p className="col-start-2 tabular-nums md:col-start-auto">
            <span className="text-slate-500 md:hidden">Price: </span>
            {formatPrice(eff.price)}
            {tag('price')}
          </p>
          <button onClick={onExclusions} className="col-start-2 text-left text-brand-700 hover:underline md:col-start-auto">
            {room.exclusions.length
              ? `${plural(room.exclusions.reduce((n, e) => n + e.quantity, 0), 'item')} · ${area(excluded)}`
              : 'Add'}
          </button>
        </>
      )}
      <div className="col-start-2 flex gap-3 md:col-start-auto md:justify-end">
        {!room.skipped && (
          <>
            <button onClick={onEdit} className="text-slate-700 hover:underline">
              Edit
            </button>
            <button onClick={onWalls} className="whitespace-nowrap text-slate-700 hover:underline" title="Doors, windows, wall tiles and skirting">
              Walls
            </button>
          </>
        )}
        {/* Remounts when the saved value changes, which clears the optimistic state. */}
        <SkipToggle key={String(room.skipped)} skipped={room.skipped} busy={busy} onSkip={onSkip} />
      </div>
    </li>
  )
}

/** Shows the new state at once; the server's answer (or a rollback on failure) remounts it. */
function SkipToggle({
  skipped,
  busy,
  onSkip,
}: {
  skipped: boolean
  busy: boolean
  onSkip: (skipped: boolean) => Promise<boolean>
}) {
  const [pending, setPending] = useState<boolean | null>(null)
  return (
    <label className="flex items-center gap-1 text-xs text-slate-500" title="This room needs no tiles">
      <input
        type="checkbox"
        checked={pending ?? skipped}
        disabled={busy && pending === null}
        onChange={async (e) => {
          setPending(e.target.checked)
          if (!(await onSkip(e.target.checked))) setPending(null) // save failed: show the saved value
        }}
        className="accent-slate-600"
      />
      Skip
    </label>
  )
}
