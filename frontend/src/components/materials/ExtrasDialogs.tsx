import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../../api/client.ts'
import type {
  ExtrasSettings,
  LengthUnit,
  OpeningKind,
  Price,
  ReviewRoom,
  SkirtingSettings,
  Suggestion,
  SundriesSettings,
  TileRef,
} from '../../api/types.ts'
import { plural } from '../../lib/format.ts'
import { editableLength, formatLength, lengthUnitLabels } from '../../lib/units.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { Button, ErrorText } from '../ui.tsx'
import { Modal, PriceInput } from './MaterialDialogs.tsx'
import { TilePicker } from './TilePicker.tsx'

const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'
const OPENING_LABELS: Record<OpeningKind, string> = { door: 'Door', window: 'Window', other: 'Other' }

// --- Walls & doors for one room -----------------------------------------------------------------

interface OpeningRow {
  kind: OpeningKind
  label: string
  width: string
  height: string
  quantity: number
  unit: LengthUnit
}

export interface WallsPreset {
  height_mm: string
  tile: TileRef | null
  needs_length: boolean
}

export type RoomWallsData = Parameters<typeof api.materials.setRoomWalls>[2]

/** Doors and windows, wall tiling and skirting for one room (PRD 4.15). */
export function WallsDialog({
  room,
  settings,
  preset,
  onSave,
  onClose,
}: {
  room: ReviewRoom
  settings: ExtrasSettings
  preset?: WallsPreset // from a suggestion: open with wall tiling switched on
  onSave: (data: RoomWallsData) => Promise<void>
  onClose: () => void
}) {
  const unit = room.unit
  const [openings, setOpenings] = useState<OpeningRow[]>(() =>
    room.openings.map((o) => ({
      kind: o.kind,
      label: o.label,
      width: editableLength(o.width_mm, o.unit),
      height: editableLength(o.height_mm, o.unit),
      quantity: o.quantity,
      unit: o.unit,
    })),
  )
  const walls = room.walls
  const [tiled, setTiled] = useState(walls !== null || preset !== undefined)
  const [height, setHeight] = useState(
    walls ? editableLength(walls.height_mm, unit) : preset ? editableLength(preset.height_mm, unit) : '',
  )
  const [tile, setTile] = useState<TileRef | null>(walls?.tile ?? preset?.tile ?? null)
  const [partial, setPartial] = useState(walls?.length_mm != null || (preset?.needs_length ?? false))
  const [length, setLength] = useState(walls?.length_mm ? editableLength(walls.length_mm, unit) : '')
  const [breakage, setBreakage] = useState(walls?.breakage_pct ?? '')
  const [price, setPrice] = useState<Price | null>(walls?.price ?? null)
  const [skirting, setSkirting] = useState<'auto' | 'yes' | 'no'>(
    room.skirting === null ? 'auto' : room.skirting ? 'yes' : 'no',
  )
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const areaOnly = room.length_mm === null || room.width_mm === null

  const update = (i: number, patch: Partial<OpeningRow>) =>
    setOpenings((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (tiled && !height.trim()) return setError('Enter how high the walls are tiled.')
    if (tiled && (partial || areaOnly) && !length.trim()) return setError('Enter the length of wall to tile.')
    setError('')
    setSaving(true)
    try {
      await onSave({
        openings: openings
          .filter((o) => o.width.trim() || o.height.trim())
          .map((o) => ({ ...o, label: o.label.trim() })),
        walls: tiled
          ? {
              height: height.trim(),
              unit,
              tile_id: tile?.id ?? null,
              breakage_pct: breakage.trim() || null,
              length: partial || areaOnly ? length.trim() : null,
              price,
            }
          : null,
        skirting: skirting === 'auto' ? null : skirting === 'yes',
      })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const unitName = lengthUnitLabels[unit].toLowerCase()
  return (
    <Modal title={`Walls & doors: ${room.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <ErrorText>{error}</ErrorText>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Doors and windows</h3>
          <p className="text-xs text-slate-500">
            Taken off the wall tiles. Door widths are also left out of the skirting.
          </p>
          {openings.length === 0 && <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-500">None added.</p>}
          <ul className="space-y-2">
            {openings.map((o, i) => (
              <li key={i} className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-2 sm:grid-cols-[6rem_1fr_5rem_5rem_4rem_auto]">
                <select
                  value={o.kind}
                  onChange={(e) => update(i, { kind: e.target.value as OpeningKind })}
                  aria-label={`Opening ${i + 1} type`}
                  className={inputClass}
                >
                  {(Object.keys(OPENING_LABELS) as OpeningKind[]).map((k) => (
                    <option key={k} value={k}>
                      {OPENING_LABELS[k]}
                    </option>
                  ))}
                </select>
                <input
                  value={o.label}
                  onChange={(e) => update(i, { label: e.target.value })}
                  maxLength={60}
                  placeholder="Label (optional)"
                  aria-label={`Opening ${i + 1} label`}
                  className={inputClass}
                />
                <input
                  value={o.width}
                  onChange={(e) => update(i, { width: e.target.value })}
                  required
                  placeholder="Width"
                  aria-label={`Opening ${i + 1} width`}
                  className={inputClass}
                />
                <input
                  value={o.height}
                  onChange={(e) => update(i, { height: e.target.value })}
                  required
                  placeholder="Height"
                  aria-label={`Opening ${i + 1} height`}
                  className={inputClass}
                />
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={o.quantity}
                  onChange={(e) => update(i, { quantity: Math.max(1, Number(e.target.value) || 1) })}
                  title="How many"
                  aria-label={`Opening ${i + 1} quantity`}
                  className={inputClass}
                />
                <button
                  type="button"
                  onClick={() => setOpenings((rs) => rs.filter((_, j) => j !== i))}
                  className="text-sm text-red-600 hover:underline"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-3 text-sm">
            <button
              type="button"
              onClick={() =>
                setOpenings((rs) => [...rs, { kind: 'door', label: '', width: '', height: '', quantity: 1, unit }])
              }
              className="font-medium text-brand-700 hover:underline"
            >
              + Door
            </button>
            <button
              type="button"
              onClick={() =>
                setOpenings((rs) => [...rs, { kind: 'window', label: '', width: '', height: '', quantity: 1, unit }])
              }
              className="font-medium text-brand-700 hover:underline"
            >
              + Window
            </button>
            <span className="text-xs text-slate-500">Sizes in {unitName}, like the room.</span>
          </div>
        </section>

        <section className="space-y-3">
          <label className="flex items-center gap-2 text-sm font-semibold">
            <input type="checkbox" checked={tiled} onChange={(e) => setTiled(e.target.checked)} className="accent-brand-600" />
            Tile the walls
          </label>
          {tiled && (
            <div className="space-y-3 rounded-lg border border-slate-200 p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Tiled up to (height, {unitName})</span>
                  <input value={height} onChange={(e) => setHeight(e.target.value)} className={`${inputClass} w-full`} />
                  <span className="text-xs text-slate-500">Full height in bathrooms is usually 2.1 m / 7 ft.</span>
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Wall tile</span>
                  <TilePicker
                    label="Wall tile"
                    value={tile}
                    onChange={(t) => setTile({ ...t })}
                    placeholder={settings.wall_tile ? `Project default: ${settings.wall_tile.size_label}` : 'Choose a wall tile'}
                  />
                </label>
              </div>
              {areaOnly ? (
                <p className="text-xs text-amber-700">This room is known only by area, so enter the wall length to tile.</p>
              ) : (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} className="accent-brand-600" />
                  Only some walls (e.g. a backsplash above the counter)
                </label>
              )}
              {(partial || areaOnly) && (
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Length of wall to tile ({unitName})</span>
                  <input value={length} onChange={(e) => setLength(e.target.value)} className={`${inputClass} w-40`} />
                </label>
              )}
              <div className="flex flex-wrap gap-4">
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Breakage buffer</span>
                  <span className="flex items-center gap-1.5">
                    <input
                      value={breakage}
                      onChange={(e) => setBreakage(e.target.value)}
                      inputMode="decimal"
                      placeholder={String(Number(settings.wall_breakage_pct))}
                      className={`${inputClass} w-20`}
                    />
                    %
                  </span>
                </label>
                <div className="text-sm">
                  <span className="mb-1 block text-slate-600">Wall tile price (optional)</span>
                  <PriceInput value={price} onChange={setPrice} />
                </div>
              </div>
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Skirting</h3>
          <select
            value={skirting}
            onChange={(e) => setSkirting(e.target.value as 'auto' | 'yes' | 'no')}
            aria-label="Skirting in this room"
            className={inputClass}
          >
            <option value="auto">Follow the project setting{tiled ? ' (none: walls are tiled)' : ''}</option>
            <option value="yes">Skirting in this room</option>
            <option value="no">No skirting in this room</option>
          </select>
        </section>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

/** "Walls 2.1 m · 1 door" under a room's name. */
export function wallsSummary(room: ReviewRoom): string | null {
  const parts = []
  if (room.walls) parts.push(`walls tiled to ${formatLength(room.walls.height_mm, room.unit)}`)
  const doors = room.openings.filter((o) => o.kind === 'door').reduce((n, o) => n + o.quantity, 0)
  const windows = room.openings.filter((o) => o.kind === 'window').reduce((n, o) => n + o.quantity, 0)
  if (doors) parts.push(plural(doors, 'door'))
  if (windows) parts.push(plural(windows, 'window'))
  if (room.skirting === false) parts.push('no skirting')
  return parts.length ? parts.join(' · ') : null
}

// --- Project settings: wall tile, skirting, sundries --------------------------------------------

function Num({
  label,
  value,
  onChange,
  suffix,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  suffix?: string
  placeholder?: string
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <span className="flex items-center gap-1.5">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          inputMode="decimal"
          placeholder={placeholder}
          className={`${inputClass} w-24`}
        />
        {suffix && <span className="text-slate-500">{suffix}</span>}
      </span>
    </label>
  )
}

function Group({ title, enabled, onToggle, children }: { title: string; enabled?: boolean; onToggle?: (v: boolean) => void; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
      <legend className="px-1 text-sm font-semibold">
        {onToggle ? (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} className="accent-brand-600" />
            {title}
          </label>
        ) : (
          title
        )}
      </legend>
      {(enabled ?? true) && children}
    </fieldset>
  )
}

const optional = (v: string) => (v.trim() ? v.trim() : null)

/** Default wall tile, skirting and sundries for the project (PRD 4.15). Not an undo step. */
export function ExtrasSettingsCard({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const saved = review.state!.extras_settings
  const [open, setOpen] = useState(false)
  const [wallTile, setWallTile] = useState<TileRef | null>(saved.wall_tile)
  const [wallBreakage, setWallBreakage] = useState(String(Number(saved.wall_breakage_pct)))
  const [wallPrice, setWallPrice] = useState<Price | null>(saved.wall_price)
  const [sk, setSk] = useState<SkirtingSettings>(saved.skirting)
  const [su, setSu] = useState<SundriesSettings>(saved.sundries)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const patchSk = (p: Partial<SkirtingSettings>) => setSk((s) => ({ ...s, ...p }))
  const patchSu = (p: Partial<SundriesSettings>) => setSu((s) => ({ ...s, ...p }))

  async function save() {
    setError('')
    setSaving(true)
    try {
      review.replaceState(
        await api.materials.setExtras(projectId, {
          wall_tile_id: wallTile?.id ?? null,
          wall_breakage_pct: wallBreakage.trim() || '0',
          wall_price: wallPrice,
          skirting: { ...sk, pieces_per_box: sk.pieces_per_box || null },
          sundries: su,
        }),
      )
      setOpen(false)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const summary = [
    saved.wall_tile ? `wall tile ${saved.wall_tile.size_label}` : null,
    saved.skirting.enabled ? 'skirting on' : null,
    saved.sundries.enabled ? 'adhesive, grout & spacers on' : null,
  ].filter(Boolean)

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span>
          <span className="text-sm font-semibold">Walls, skirting &amp; sundries</span>{' '}
          <span className="text-sm text-slate-500">{summary.length ? summary.join(' · ') : 'not included yet'}</span>
        </span>
        <span aria-hidden="true" className="text-slate-400">
          {open ? '▴' : '▾'}
        </span>
      </button>
      {open && (
        <div className="space-y-4 border-t border-slate-100 p-4">
          <ErrorText>{error}</ErrorText>
          <Group title="Wall tiles">
            <p className="text-xs text-slate-500">
              Turn on wall tiling per room with "Walls &amp; doors" in the list below. Rooms without their own wall tile use this
              one.
            </p>
            <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_auto_auto] sm:items-end">
              <label className="block text-sm">
                <span className="mb-1 block text-slate-600">Default wall tile</span>
                <TilePicker label="Default wall tile" value={wallTile} onChange={(t) => setWallTile({ ...t })} placeholder="Choose a wall tile" />
              </label>
              <Num label="Breakage buffer" value={wallBreakage} onChange={setWallBreakage} suffix="%" />
              <div className="text-sm">
                <span className="mb-1 block text-slate-600">Price (optional)</span>
                <PriceInput value={wallPrice} onChange={setWallPrice} />
              </div>
            </div>
          </Group>

          <Group title="Skirting" enabled={sk.enabled} onToggle={(v) => patchSk({ enabled: v })}>
            <p className="text-xs text-slate-500">Room perimeter minus door widths. Rooms with tiled walls are left out unless you choose otherwise.</p>
            <div className="flex flex-wrap items-end gap-4">
              <Num label="Height" value={String(sk.height_mm)} onChange={(v) => patchSk({ height_mm: v })} suffix="mm" />
              <label className="block text-sm">
                <span className="mb-1 block text-slate-600">Made from</span>
                <select
                  value={sk.source}
                  onChange={(e) => patchSk({ source: e.target.value as SkirtingSettings['source'] })}
                  className={inputClass}
                >
                  <option value="floor_tile">Strips cut from the floor tile</option>
                  <option value="pieces">Ready-made skirting pieces</option>
                </select>
              </label>
              <Num label="Breakage" value={String(sk.breakage_pct)} onChange={(v) => patchSk({ breakage_pct: v })} suffix="%" />
            </div>
            {sk.source === 'pieces' && (
              <div className="flex flex-wrap items-end gap-4">
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Name</span>
                  <input
                    value={sk.piece_name}
                    onChange={(e) => patchSk({ piece_name: e.target.value })}
                    maxLength={60}
                    className={`${inputClass} w-48`}
                  />
                </label>
                <Num label="Piece length" value={String(sk.piece_length_mm)} onChange={(v) => patchSk({ piece_length_mm: v })} suffix="mm" />
                <Num
                  label="Pieces per box"
                  value={sk.pieces_per_box ? String(sk.pieces_per_box) : ''}
                  onChange={(v) => patchSk({ pieces_per_box: v.trim() ? Number(v) : null })}
                  placeholder="loose"
                />
                <div className="text-sm">
                  <span className="mb-1 block text-slate-600">Price (optional)</span>
                  <PriceInput value={sk.price} onChange={(p) => patchSk({ price: p })} />
                </div>
              </div>
            )}
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={sk.skip_tiled_walls}
                onChange={(e) => patchSk({ skip_tiled_walls: e.target.checked })}
                className="accent-brand-600"
              />
              No skirting in rooms with tiled walls
            </label>
          </Group>

          <Group title="Adhesive, grout & spacers" enabled={su.enabled} onToggle={(v) => patchSu({ enabled: v })}>
            <p className="text-xs text-slate-500">
              From coverage rates, for floor and wall tiles (not planks or rolls). Leave a rate empty to use the typical value.
            </p>
            <div className="flex flex-wrap items-end gap-4">
              <Num
                label="Adhesive"
                value={su.adhesive_rate_kg_m2 ?? ''}
                onChange={(v) => patchSu({ adhesive_rate_kg_m2: optional(v) })}
                suffix="kg/m²"
                placeholder="4–6"
              />
              <Num label="Bag size" value={String(su.adhesive_bag_kg)} onChange={(v) => patchSu({ adhesive_bag_kg: v })} suffix="kg" />
              <Num
                label="Bag price"
                value={su.adhesive_bag_price ?? ''}
                onChange={(v) => patchSu({ adhesive_bag_price: optional(v) })}
                placeholder="optional"
              />
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <Num label="Grout joint" value={String(su.grout_joint_mm)} onChange={(v) => patchSu({ grout_joint_mm: v })} suffix="mm" />
              <Num
                label="Joint depth"
                value={su.grout_depth_mm ?? ''}
                onChange={(v) => patchSu({ grout_depth_mm: optional(v) })}
                suffix="mm"
                placeholder="tile"
              />
              <Num label="Grout pack" value={String(su.grout_pack_kg)} onChange={(v) => patchSu({ grout_pack_kg: v })} suffix="kg" />
              <Num
                label="Pack price"
                value={su.grout_pack_price ?? ''}
                onChange={(v) => patchSu({ grout_pack_price: optional(v) })}
                placeholder="optional"
              />
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <Num label="Spacers per tile" value={String(su.spacers_per_tile)} onChange={(v) => patchSu({ spacers_per_tile: v })} />
              <Num
                label="Spacers per pack"
                value={String(su.spacer_pack)}
                onChange={(v) => patchSu({ spacer_pack: Math.max(1, Number(v) || 1) })}
              />
              <Num
                label="Pack price"
                value={su.spacer_pack_price ?? ''}
                onChange={(v) => patchSu({ spacer_pack_price: optional(v) })}
                placeholder="optional"
              />
              <Num label="Waste" value={String(su.waste_pct)} onChange={(v) => patchSu({ waste_pct: v })} suffix="%" />
            </div>
          </Group>

          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving || review.busy}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
            <button type="button" onClick={() => setOpen(false)} className="text-sm text-slate-600 hover:underline">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// --- Suggestions by room type -------------------------------------------------------------------

/**
 * Suggested defaults by room type (PRD 4.15): anti-skid floors in wet rooms and balconies, tiled
 * bathroom walls, a kitchen backsplash. Nothing changes until the user applies one.
 */
export function SuggestionsPanel({
  projectId,
  review,
  onTileWalls,
}: {
  projectId: string
  review: RoomsReview
  onTileWalls: (roomIds: string[], preset: WallsPreset) => void
}) {
  const state = review.state!
  const [items, setItems] = useState<Suggestion[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    api.materials
      .suggestions(projectId)
      .then((s) => !cancelled && setItems(s))
      .catch(() => undefined) // suggestions are optional
    return () => {
      cancelled = true
    }
  }, [projectId, state.version, state.extras_settings])

  async function apply(s: Suggestion) {
    const action = s.action
    if (!action) return
    if (action.type === 'set_tile' && action.tile_id) {
      await review.mutate(`Use ${action.tile_name} in ${plural(s.room_ids.length, 'room')}`, () =>
        api.materials.setRooms(projectId, { room_ids: s.room_ids, set: { tile_id: action.tile_id! } }, state.version),
      )
    } else if (action.type === 'tile_walls' && action.height_mm) {
      const tile = action.tile_id
        ? ({ id: action.tile_id, name: action.tile_name ?? '', size_label: action.tile_name ?? '' } as TileRef)
        : null
      onTileWalls(s.room_ids, { height_mm: action.height_mm, tile, needs_length: action.needs_length })
    }
  }

  const visible = items.filter((s) => !dismissed.has(`${s.key}:${s.room_ids.join(',')}`))
  if (visible.length === 0) return null
  return (
    <div className="space-y-2">
      {visible.map((s) => (
        <div
          key={s.key}
          className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${
            s.severity === 'warn' ? 'border-amber-300 bg-amber-50' : 'border-brand-100 bg-brand-50'
          }`}
        >
          <div className="min-w-0">
            <p className="font-medium">
              {s.severity === 'warn' ? '⚠ ' : '💡 '}
              {s.title}: {s.room_names.join(', ')}
            </p>
            <p className="text-slate-600">{s.detail}</p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {s.action && (s.action.type === 'tile_walls' || s.action.tile_id) && (
              <Button type="button" onClick={() => apply(s)} disabled={review.busy}>
                {s.action.type === 'set_tile' ? `Use ${s.action.tile_name}` : 'Set up walls'}
              </Button>
            )}
            <button
              type="button"
              onClick={() => setDismissed((d) => new Set(d).add(`${s.key}:${s.room_ids.join(',')}`))}
              className="text-slate-500 hover:underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
