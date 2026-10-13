import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type {
  LengthUnit,
  Layout,
  MaterialField,
  Price,
  PriceBasis,
  ProjectMaterial,
  ReviewRoom,
  TileRef,
} from '../../api/types.ts'
import { formatPrice, plural } from '../../lib/format.ts'
import { editableLength, lengthUnitLabels } from '../../lib/units.ts'
import { Button, ErrorText } from '../ui.tsx'
import { TilePicker } from './TilePicker.tsx'

export const LAYOUT_LABELS: Record<Layout, string> = { straight: 'Straight', diagonal: 'Diagonal' }
export const BASIS_LABELS: Record<PriceBasis, string> = { box: 'per box', tile: 'per tile', sqft: 'per sq ft', sqm: 'per m²' }
const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-full max-w-xl rounded-xl border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="max-h-[90vh] space-y-4 overflow-y-auto p-6">
        <h2 className="text-lg font-semibold">{title}</h2>
        {children}
      </div>
    </dialog>
  )
}

export function LayoutToggle({ value, onChange }: { value: Layout; onChange: (l: Layout) => void }) {
  return (
    <div role="group" aria-label="Layout" className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
      {(Object.keys(LAYOUT_LABELS) as Layout[]).map((l) => (
        <button
          key={l}
          type="button"
          aria-pressed={value === l}
          onClick={() => onChange(l)}
          className={`rounded px-3 py-1 ${value === l ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
        >
          {LAYOUT_LABELS[l]}
        </button>
      ))}
    </div>
  )
}

export function PriceInput({ value, onChange }: { value: Price | null; onChange: (p: Price | null) => void }) {
  const [amount, setAmount] = useState(value?.amount ?? '')
  const [basis, setBasis] = useState<PriceBasis>(value?.basis ?? 'box')
  const emit = (a: string, b: PriceBasis) => onChange(Number(a) > 0 ? { amount: a.trim(), basis: b } : null)
  return (
    <div className="flex gap-2">
      <input
        value={amount}
        onChange={(e) => {
          setAmount(e.target.value)
          emit(e.target.value, basis)
        }}
        inputMode="decimal"
        placeholder="Optional"
        aria-label="Price"
        className={`${inputClass} w-28`}
      />
      <select
        value={basis}
        onChange={(e) => {
          setBasis(e.target.value as PriceBasis)
          emit(amount, e.target.value as PriceBasis)
        }}
        aria-label="Price basis"
        className={inputClass}
      >
        {(Object.keys(BASIS_LABELS) as PriceBasis[]).map((b) => (
          <option key={b} value={b}>
            {BASIS_LABELS[b]}
          </option>
        ))}
      </select>
    </div>
  )
}

// --- Edit settings for one or more rooms --------------------------------------------------------

type Mode = 'keep' | 'default' | 'own'
interface FieldState<T> {
  mode: Mode
  value: T
}

export interface MaterialChange {
  set: { tile_id?: string; layout?: Layout; breakage_pct?: string; price?: Price }
  inherit: MaterialField[]
}

export function MaterialDialog({
  rooms,
  defaults,
  onApply,
  onClose,
}: {
  rooms: ReviewRoom[]
  defaults: ProjectMaterial
  onApply: (change: MaterialChange) => Promise<void>
  onClose: () => void
}) {
  const single = rooms.length === 1 ? rooms[0] : null
  const initialMode = (field: MaterialField): Mode =>
    single ? (single.effective.overridden.includes(field) ? 'own' : 'default') : 'keep'
  const own = single?.material
  const [tile, setTile] = useState<FieldState<TileRef | null>>({ mode: initialMode('tile'), value: own?.tile ?? null })
  const [layout, setLayout] = useState<FieldState<Layout>>({ mode: initialMode('layout'), value: own?.layout ?? defaults.layout })
  const [buffer, setBuffer] = useState<FieldState<string>>({
    mode: initialMode('breakage_pct'),
    value: own?.breakage_pct ?? defaults.breakage_pct,
  })
  const [price, setPrice] = useState<FieldState<Price | null>>({ mode: initialMode('price'), value: own?.price ?? null })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const change: MaterialChange = { set: {}, inherit: [] }
    const add = <T,>(field: MaterialField, state: FieldState<T>, put: () => void) => {
      if (state.mode === 'default') change.inherit.push(field)
      if (state.mode === 'own') put()
    }
    add('tile', tile, () => {
      if (tile.value) change.set.tile_id = tile.value.id
    })
    add('layout', layout, () => (change.set.layout = layout.value))
    add('breakage_pct', buffer, () => (change.set.breakage_pct = buffer.value.trim()))
    add('price', price, () => {
      if (price.value) change.set.price = price.value
    })
    if (tile.mode === 'own' && !tile.value) return setError('Choose a tile, or use the project default.')
    if (price.mode === 'own' && !price.value) return setError('Enter a price, or use the project default.')
    setError('')
    setSaving(true)
    try {
      await onApply(change)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const title = single ? `Tile settings: ${single.name}` : `Tile settings for ${plural(rooms.length, 'room')}`
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorText>{error}</ErrorText>
        <Setting
          label="Tile"
          bulk={!single}
          state={tile}
          onMode={(mode) => setTile((s) => ({ ...s, mode }))}
          defaultText={defaults.tile ? `${defaults.tile.size_label} · ${defaults.tile.name}` : 'none set'}
        >
          <TilePicker label="Room tile" value={tile.value} onChange={(t) => setTile({ mode: 'own', value: { ...t } })} />
        </Setting>
        <Setting
          label="Layout"
          bulk={!single}
          state={layout}
          onMode={(mode) => setLayout((s) => ({ ...s, mode }))}
          defaultText={LAYOUT_LABELS[defaults.layout]}
        >
          <LayoutToggle value={layout.value} onChange={(value) => setLayout({ mode: 'own', value })} />
        </Setting>
        <Setting
          label="Breakage buffer"
          bulk={!single}
          state={buffer}
          onMode={(mode) => setBuffer((s) => ({ ...s, mode }))}
          defaultText={`${Number(defaults.breakage_pct)}%`}
        >
          <span className="flex items-center gap-2">
            <input
              value={buffer.value}
              onChange={(e) => setBuffer({ mode: 'own', value: e.target.value })}
              inputMode="decimal"
              aria-label="Breakage buffer percent"
              className={`${inputClass} w-24`}
            />
            %
          </span>
        </Setting>
        <Setting
          label="Price"
          bulk={!single}
          state={price}
          onMode={(mode) => setPrice((s) => ({ ...s, mode }))}
          defaultText={formatPrice(defaults.price)}
        >
          <PriceInput value={price.value} onChange={(value) => setPrice({ mode: 'own', value })} />
        </Setting>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Apply'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function Setting<T>({
  label,
  bulk,
  state,
  onMode,
  defaultText,
  children,
}: {
  label: string
  bulk: boolean
  state: FieldState<T>
  onMode: (mode: Mode) => void
  defaultText: string
  children: ReactNode
}) {
  const name = `mode-${label}`
  return (
    <fieldset className="space-y-2 rounded-lg border border-slate-200 p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {bulk && (
          <label className="flex items-center gap-1.5">
            <input type="radio" name={name} checked={state.mode === 'keep'} onChange={() => onMode('keep')} className="accent-brand-600" />
            Leave as is
          </label>
        )}
        <label className="flex items-center gap-1.5">
          <input type="radio" name={name} checked={state.mode === 'default'} onChange={() => onMode('default')} className="accent-brand-600" />
          Project default <span className="text-slate-500">({defaultText})</span>
        </label>
        <label className="flex items-center gap-1.5">
          <input type="radio" name={name} checked={state.mode === 'own'} onChange={() => onMode('own')} className="accent-brand-600" />
          {bulk ? 'Set to' : 'Own setting'}
        </label>
      </div>
      {state.mode === 'own' && <div>{children}</div>}
    </fieldset>
  )
}

// --- Exclusions ---------------------------------------------------------------------------------

export interface ExclusionRow {
  label: string
  length: string
  width: string
  quantity: number
  unit: LengthUnit
}

const COMMON = ['Kitchen cabinet', 'Column', 'Bathtub', 'Built-in wardrobe', 'Shower tray', 'Fixed furniture']

export function ExclusionsDialog({
  room,
  onSave,
  onClose,
}: {
  room: ReviewRoom
  onSave: (rows: ExclusionRow[]) => Promise<void>
  onClose: () => void
}) {
  const [rows, setRows] = useState<ExclusionRow[]>(() =>
    room.exclusions.map((e) => ({
      label: e.label,
      length: editableLength(e.length_mm, e.unit),
      width: editableLength(e.width_mm, e.unit),
      quantity: e.quantity,
      unit: e.unit,
    })),
  )
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const update = (i: number, patch: Partial<ExclusionRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      await onSave(rows.filter((r) => r.label.trim() || r.length.trim() || r.width.trim()))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Untiled areas: ${room.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-500">
          Areas inside the room that won't be tiled, like a kitchen cabinet base or a column. They're taken off the
          room area.
        </p>
        <ErrorText>{error}</ErrorText>
        {rows.length === 0 && <p className="rounded-md bg-slate-50 px-3 py-3 text-sm text-slate-500">No untiled areas.</p>}
        <ul className="space-y-3">
          {rows.map((row, i) => (
            <li key={i} className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-[1fr_5rem_5rem_4rem_6rem_auto]">
              <input
                value={row.label}
                onChange={(e) => update(i, { label: e.target.value })}
                list="exclusion-labels"
                required
                maxLength={60}
                placeholder="What is it?"
                aria-label={`Exclusion ${i + 1} name`}
                className={`${inputClass} col-span-2 sm:col-span-1`}
              />
              <input
                value={row.length}
                onChange={(e) => update(i, { length: e.target.value })}
                required
                aria-label={`Exclusion ${i + 1} length`}
                placeholder="Length"
                className={inputClass}
              />
              <input
                value={row.width}
                onChange={(e) => update(i, { width: e.target.value })}
                required
                aria-label={`Exclusion ${i + 1} width`}
                placeholder="Width"
                className={inputClass}
              />
              <input
                type="number"
                min={1}
                max={100}
                value={row.quantity}
                onChange={(e) => update(i, { quantity: Math.max(1, Number(e.target.value) || 1) })}
                aria-label={`Exclusion ${i + 1} quantity`}
                title="How many"
                className={inputClass}
              />
              <select
                value={row.unit}
                onChange={(e) => update(i, { unit: e.target.value as LengthUnit })}
                aria-label={`Exclusion ${i + 1} unit`}
                className={inputClass}
              >
                {(Object.keys(lengthUnitLabels) as LengthUnit[]).map((u) => (
                  <option key={u} value={u}>
                    {lengthUnitLabels[u]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                aria-label={`Remove exclusion ${i + 1}`}
                className="text-sm text-red-600 hover:underline"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <datalist id="exclusion-labels">
          {COMMON.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <button
          type="button"
          onClick={() => setRows((rs) => [...rs, { label: '', length: '', width: '', quantity: 1, unit: room.unit }])}
          className="text-sm font-medium text-brand-700 hover:underline"
        >
          + Add an untiled area
        </button>
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
