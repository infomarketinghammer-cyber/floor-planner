import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type {
  ProductKind,
  Tile,
  TileFinish,
  TileInput,
  TileMaterial,
  TileRegion,
  TileSizeUnit,
  TileType,
} from '../../api/types.ts'
import { formatArea, type AreaUnit } from '../../lib/format.ts'
import { Button, ErrorText } from '../ui.tsx'

export const TYPE_LABELS: Record<TileType, string> = {
  floor: 'Floor',
  wall: 'Wall',
  floor_wall: 'Floor & wall',
  anti_skid: 'Anti-skid',
  outdoor: 'Outdoor',
}
export const FINISH_LABELS: Record<TileFinish, string> = {
  matt: 'Matt',
  glossy: 'Glossy',
  satin: 'Satin',
  polished: 'Polished',
  textured: 'Textured',
  other: 'Other',
}
export const MATERIAL_LABELS: Record<TileMaterial, string> = {
  vitrified: 'Vitrified',
  ceramic: 'Ceramic',
  porcelain: 'Porcelain',
  natural_stone: 'Natural stone',
  mosaic: 'Mosaic',
  wood: 'Wood',
  laminate: 'Laminate',
  vinyl: 'Vinyl',
  carpet: 'Carpet',
  other: 'Other',
}
/** How the product is sold and laid (PRD 4.15). */
export const KIND_LABELS: Record<ProductKind, string> = {
  tile: 'Tiles',
  plank: 'Planks (wood, laminate, vinyl)',
  roll: 'Roll (carpet, sheet vinyl)',
}
export const REGION_LABELS: Record<TileRegion, string> = { india: 'India (metric)', imperial: 'Imperial (in/ft)' }

const MM_PER: Record<TileSizeUnit, number> = { mm: 1, cm: 10, m: 1000, in: 25.4, ft: 304.8 }
const UNIT_LABELS: Record<TileSizeUnit, string> = { mm: 'mm', cm: 'cm', m: 'm', in: 'inches', ft: 'feet' }
const SQFT_PER_SQM = 10.763910416709722
const inputClass = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'

function trim(n: number, places = 3): string {
  return String(Number(n.toFixed(places)))
}

/** Bare numbers only, for the live preview. The server parses marks like 24" or 2' too. */
function previewMm(text: string, unit: TileSizeUnit): number | null {
  const n = Number(text.trim())
  return text.trim() && Number.isFinite(n) && n > 0 ? n * MM_PER[unit] : null
}

function emptyInput(defaultUnit: TileSizeUnit): TileInput {
  return {
    name: '',
    kind: 'tile',
    length: '',
    width: '',
    size_unit: defaultUnit,
    thickness_mm: null,
    tiles_per_box: null,
    coverage_per_box_sqm: null,
    type: 'floor',
    finish: 'matt',
    material: 'vitrified',
    brand: null,
    code: null,
    regions: [],
    notes: null,
  }
}

function fromTile(tile: Tile): TileInput {
  const per = MM_PER[tile.size_unit]
  return {
    name: tile.name,
    kind: tile.kind,
    length: trim(Number(tile.length_mm) / per),
    width: trim(Number(tile.width_mm) / per),
    size_unit: tile.size_unit,
    thickness_mm: tile.thickness_mm,
    tiles_per_box: tile.tiles_per_box,
    coverage_per_box_sqm: null,
    type: tile.type,
    finish: tile.finish,
    material: tile.material,
    brand: tile.brand,
    code: tile.code,
    regions: tile.regions,
    notes: tile.notes,
  }
}

export function TileFormDialog({
  open,
  tile,
  isAdmin,
  areaUnit,
  onClose,
  onSave,
}: {
  open: boolean
  tile: Tile | null // null = new tile
  isAdmin: boolean
  areaUnit: AreaUnit
  onClose: () => void
  onSave: (data: TileInput, catalog: boolean) => Promise<void>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const defaultUnit: TileSizeUnit = areaUnit === 'sqm' ? 'mm' : 'in'
  const [form, setForm] = useState<TileInput>(() => (tile ? fromTile(tile) : emptyInput(defaultUnit)))
  const [packBy, setPackBy] = useState<'count' | 'coverage'>('count')
  const [coverage, setCoverage] = useState('')
  const [catalog, setCatalog] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  const set = <K extends keyof TileInput>(key: K, value: TileInput[K]) => setForm((f) => ({ ...f, [key]: value }))

  // Live preview of what a box covers.
  const l = previewMm(form.length, form.size_unit)
  const w = previewMm(form.width, form.size_unit)
  const tileSqm = l && w ? (l * w) / 1_000_000 : null
  const coverageSqm =
    packBy === 'count'
      ? tileSqm && form.tiles_per_box
        ? tileSqm * form.tiles_per_box
        : null
      : Number(coverage) > 0
        ? areaUnit === 'sqm'
          ? Number(coverage)
          : Number(coverage) / SQFT_PER_SQM
        : null
  const impliedCount = packBy === 'coverage' && tileSqm && coverageSqm ? coverageSqm / tileSqm : null
  const display = (sqm: number) => formatArea(areaUnit === 'sqm' ? sqm : sqm * SQFT_PER_SQM, areaUnit)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSaving(true)
    const data: TileInput =
      form.kind === 'roll'
        ? { ...form, tiles_per_box: null, coverage_per_box_sqm: null } // a roll has no pack size
        : {
            ...form,
            tiles_per_box: packBy === 'count' ? form.tiles_per_box : null,
            coverage_per_box_sqm: packBy === 'coverage' && coverageSqm ? trim(coverageSqm, 4) : null,
          }
    try {
      await onSave(data, !tile && isAdmin && catalog)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <form onSubmit={handleSubmit} className="max-h-[90vh] space-y-5 overflow-y-auto p-6">
        <div>
          <h2 className="text-lg font-semibold">{tile ? 'Edit tile' : 'Add a tile'}</h2>
          <p className="text-sm text-slate-500">
            {tile?.scope === 'catalog'
              ? 'You are editing the shared catalogue: every contractor sees this change.'
              : 'Saved to your tiles so you can reuse it on any project.'}
          </p>
        </div>
        <ErrorText>{error}</ErrorText>

        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            required
            maxLength={120}
            placeholder="e.g. Kajaria Eternity 600×1200 polished"
            className={inputClass}
            autoFocus
          />
        </Field>

        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">Product</legend>
          <div role="group" aria-label="Product" className="inline-flex flex-wrap rounded-md border border-slate-300 bg-white p-0.5 text-sm">
            {(Object.keys(KIND_LABELS) as ProductKind[]).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={form.kind === k}
                onClick={() => set('kind', k)}
                className={`rounded px-3 py-1 ${form.kind === k ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
              >
                {KIND_LABELS[k]}
              </button>
            ))}
          </div>
          {form.kind !== 'tile' && (
            <p className="mt-1 text-xs text-slate-500">
              {form.kind === 'plank'
                ? 'Planks are worked out by area plus an allowance for cuts at the row ends, then boxes.'
                : 'Rolls are worked out as strips across the room, bought by the running metre.'}
            </p>
          )}
        </fieldset>

        <fieldset className="grid gap-3 sm:grid-cols-[1fr_auto_1fr_8rem_8rem]">
          <legend className="mb-1 text-sm font-medium text-slate-700">
            {form.kind === 'roll' ? 'Roll length × roll width' : 'Size'}
          </legend>
          <input
            value={form.length}
            onChange={(e) => set('length', e.target.value)}
            required
            maxLength={20}
            aria-label={form.kind === 'roll' ? 'Roll length' : 'Tile length'}
            placeholder={form.kind === 'roll' ? 'Roll length' : 'Length'}
            className={inputClass}
          />
          <span className="self-center text-center text-slate-400">×</span>
          <input
            value={form.width}
            onChange={(e) => set('width', e.target.value)}
            required
            maxLength={20}
            aria-label={form.kind === 'roll' ? 'Roll width' : 'Tile width'}
            placeholder={form.kind === 'roll' ? 'Roll width' : 'Width'}
            className={inputClass}
          />
          <select
            value={form.size_unit}
            onChange={(e) => set('size_unit', e.target.value as TileSizeUnit)}
            aria-label="Size unit"
            className={inputClass}
          >
            {(Object.keys(UNIT_LABELS) as TileSizeUnit[]).map((u) => (
              <option key={u} value={u}>
                {UNIT_LABELS[u]}
              </option>
            ))}
          </select>
          <input
            value={form.thickness_mm ?? ''}
            onChange={(e) => set('thickness_mm', e.target.value.trim() || null)}
            inputMode="decimal"
            aria-label="Thickness in mm"
            placeholder="Thickness mm"
            className={inputClass}
          />
        </fieldset>

        {form.kind !== 'roll' && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-slate-700">Pack size</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={packBy === 'count'} onChange={() => setPackBy('count')} className="accent-brand-600" />
              {form.kind === 'plank' ? 'Planks per box' : 'Tiles per box'}
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={packBy === 'coverage'}
                onChange={() => setPackBy('coverage')}
                className="accent-brand-600"
              />
              Coverage per box (from the box label)
            </label>
          </div>
          {packBy === 'count' ? (
            <input
              type="number"
              min={1}
              max={500}
              value={form.tiles_per_box ?? ''}
              onChange={(e) => set('tiles_per_box', e.target.value ? Number(e.target.value) : null)}
              required
              aria-label="Tiles per box"
              className={`${inputClass} max-w-40`}
            />
          ) : (
            <div className="flex max-w-60 items-center gap-2">
              <input
                value={coverage}
                onChange={(e) => setCoverage(e.target.value)}
                required
                inputMode="decimal"
                aria-label="Coverage per box"
                className={inputClass}
              />
              <span className="text-sm text-slate-500">{areaUnit === 'sqm' ? 'm²' : 'sq ft'}</span>
            </div>
          )}
          <p className="text-xs text-slate-500" aria-live="polite">
            {tileSqm && coverageSqm
              ? packBy === 'count'
                ? `${form.tiles_per_box} tiles × ${display(tileSqm)} = ${display(coverageSqm)} per box`
                : `${display(coverageSqm)} ÷ ${display(tileSqm)} ≈ ${trim(impliedCount ?? 0, 2)} tiles per box`
              : 'Enter a size and pack to see the coverage.'}
          </p>
        </fieldset>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Type">
            <Select value={form.type} onChange={(v) => set('type', v)} options={TYPE_LABELS} />
          </Field>
          <Field label="Finish">
            <Select value={form.finish} onChange={(v) => set('finish', v)} options={FINISH_LABELS} />
          </Field>
          <Field label="Material">
            <Select value={form.material} onChange={(v) => set('material', v)} options={MATERIAL_LABELS} />
          </Field>
          <Field label="Brand (optional)">
            <input
              value={form.brand ?? ''}
              onChange={(e) => set('brand', e.target.value || null)}
              maxLength={80}
              className={inputClass}
            />
          </Field>
          <Field label="Code / SKU (optional)">
            <input
              value={form.code ?? ''}
              onChange={(e) => set('code', e.target.value || null)}
              maxLength={60}
              className={inputClass}
            />
          </Field>
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-slate-700">Region</legend>
            {(Object.keys(REGION_LABELS) as TileRegion[]).map((r) => (
              <label key={r} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={form.regions.includes(r)}
                  onChange={(e) =>
                    set('regions', e.target.checked ? [...form.regions, r] : form.regions.filter((x) => x !== r))
                  }
                  className="accent-brand-600"
                />
                {REGION_LABELS[r]}
              </label>
            ))}
          </fieldset>
        </div>

        <Field label="Notes (optional)">
          <textarea
            value={form.notes ?? ''}
            onChange={(e) => set('notes', e.target.value || null)}
            rows={2}
            maxLength={500}
            className={inputClass}
          />
        </Field>

        {!tile && isAdmin && (
          <label className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-sm">
            <input type="checkbox" checked={catalog} onChange={(e) => setCatalog(e.target.checked)} className="accent-brand-600" />
            Add to the shared catalogue (visible to every contractor)
          </label>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : tile ? 'Save changes' : 'Add tile'}
          </Button>
        </div>
      </form>
    </dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}

function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (value: T) => void
  options: Record<T, string>
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value as T)} className={inputClass}>
      {(Object.keys(options) as T[]).map((k) => (
        <option key={k} value={k}>
          {options[k]}
        </option>
      ))}
    </select>
  )
}
