import { useState, type FormEvent } from 'react'
import { api } from '../../api/client.ts'
import type { LengthUnit, RoomImportResult } from '../../api/types.ts'
import { plural } from '../../lib/format.ts'
import { formatLength, lengthUnitLabels } from '../../lib/units.ts'
import { Button, ErrorText } from '../ui.tsx'

export const UNITS = Object.keys(lengthUnitLabels) as LengthUnit[]

const PLACEHOLDERS: Record<LengthUnit, [string, string]> = {
  ft_in: [`12'6"`, `10'0"`],
  ft: ['12.5', '10'],
  in: ['150', '120'],
  m: ['3.6', '3.0'],
  cm: ['360', '300'],
  mm: ['3600', '3000'],
}
const TEMPLATE_CSV =
  'Room,Length,Width,Unit,Floor\r\n' +
  'Bedroom 1,"12\'0""","10\'0""",ft-in,Ground Floor\r\n' +
  'Kitchen,3.6,3.0,m,Ground Floor\r\n' +
  'Toilet,2400,1500,mm,First Floor\r\n'

export const inputClass = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'


export function UnitSelect({ value, onChange, id }: { value: LengthUnit; onChange: (u: LengthUnit) => void; id?: string }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value as LengthUnit)} className={inputClass}>
      {UNITS.map((u) => (
        <option key={u} value={u}>
          {lengthUnitLabels[u]}
        </option>
      ))}
    </select>
  )
}

export interface NewRoom {
  name: string
  floor?: string
  length?: string
  width?: string
  unit: LengthUnit
  area?: string // odd-shaped rooms known only by floor area
  area_unit?: 'sqft' | 'sqm'
}

export function AddRoomForm({
  defaultUnit,
  onAdd,
  onClose,
}: {
  defaultUnit: LengthUnit
  onAdd: (room: NewRoom) => Promise<void>
  onClose: () => void
}) {
  const [unit, setUnit] = useState<LengthUnit>(defaultUnit)
  const [byArea, setByArea] = useState(false)
  const [areaUnit, setAreaUnit] = useState<'sqft' | 'sqm'>(defaultUnit === 'm' || defaultUnit === 'cm' || defaultUnit === 'mm' ? 'sqm' : 'sqft')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [lastAdded, setLastAdded] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formEl = event.currentTarget
    const form = new FormData(formEl)
    setError('')
    setSubmitting(true)
    try {
      const name = String(form.get('name')).trim()
      const floor = String(form.get('floor') ?? '').trim() || undefined
      await onAdd(
        byArea
          ? { name, floor, unit, area: String(form.get('area')).trim(), area_unit: areaUnit }
          : { name, floor, unit, length: String(form.get('length')).trim(), width: String(form.get('width')).trim() },
      )
      setLastAdded(name)
      // Keep floor and unit for fast entry of the next room.
      for (const field of byArea ? ['name', 'area'] : ['name', 'length', 'width'])
        (formEl.elements.namedItem(field) as HTMLInputElement).value = ''
      ;(formEl.elements.namedItem('name') as HTMLInputElement).focus()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const [lengthHint, widthHint] = PLACEHOLDERS[unit]
  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="font-medium">Add a room</h3>
      <ErrorText>{error}</ErrorText>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="block text-sm lg:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Room name</span>
          <input name="name" required maxLength={100} placeholder="Bedroom 1" className={inputClass} autoFocus />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Floor</span>
          <input name="floor" maxLength={50} list="floor-suggestions" placeholder="Optional" className={inputClass} />
        </label>
        <label className="block text-sm lg:col-span-2" htmlFor="add-room-unit">
          <span className="mb-1 block font-medium text-slate-700">Unit</span>
          <UnitSelect id="add-room-unit" value={unit} onChange={setUnit} />
        </label>
        {byArea ? (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">Floor area</span>
            <span className="flex gap-2">
              <input name="area" required inputMode="decimal" placeholder="e.g. 145" className={inputClass} />
              <select
                value={areaUnit}
                onChange={(e) => setAreaUnit(e.target.value as 'sqft' | 'sqm')}
                aria-label="Area unit"
                className={`${inputClass} w-28`}
              >
                <option value="sqft">sq ft</option>
                <option value="sqm">m²</option>
              </select>
            </span>
          </label>
        ) : (
          <>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Length</span>
              <input name="length" required maxLength={30} placeholder={lengthHint} className={inputClass} />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Width</span>
              <input name="width" required maxLength={30} placeholder={widthHint} className={inputClass} />
            </label>
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          {byArea
            ? 'Tiles will be worked out by area with a cutting allowance.'
            : "You can also type the unit, e.g. 3.6 m or 12'6\"."}
        </span>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={byArea} onChange={(e) => setByArea(e.target.checked)} className="accent-brand-600" />
          Odd shape: I only know the floor area
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? 'Adding…' : 'Add room'}
        </Button>
        <button type="button" onClick={onClose} className="text-sm text-slate-600 hover:underline">
          Done
        </button>
        {lastAdded && <span className="text-sm text-green-700">Added {lastAdded}</span>}
      </div>
    </form>
  )
}

export type ImportOptions = { defaultUnit: LengthUnit; mode: 'append' | 'replace' }

/** Preview runs here (nothing saved); the actual import goes through `onCommit` so it can be undone. */
export function ImportPanel({
  projectId,
  hasRooms,
  defaultUnit,
  onCommit,
  onClose,
}: {
  projectId: string
  hasRooms: boolean
  defaultUnit: LengthUnit
  onCommit: (file: File, options: ImportOptions) => Promise<void>
  onClose: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [unit, setUnit] = useState<LengthUnit>(defaultUnit)
  const [mode, setMode] = useState<'append' | 'replace'>('append')
  const [preview, setPreview] = useState<RoomImportResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run(dryRun: boolean) {
    if (!file) return
    if (!dryRun && mode === 'replace' && hasRooms && !confirm('Replace all existing rooms with this list?')) return
    setError('')
    setBusy(true)
    try {
      if (dryRun) setPreview(await api.rooms.import(projectId, file, { defaultUnit: unit, mode, dryRun: true }))
      else await onCommit(file, { defaultUnit: unit, mode })
    } catch (err) {
      setError((err as Error).message)
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([TEMPLATE_CSV], { type: 'text/csv' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: 'room-list-template.csv' })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-medium">Import a room list</h3>
          <p className="text-sm text-slate-500">
            .xlsx or .csv with columns Room, Length, Width, and optionally Unit and Floor (or one Size column like
            12'0" x 10'0").
          </p>
        </div>
        <button onClick={downloadTemplate} className="text-sm font-medium text-brand-600 hover:underline">
          Download template
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">File</span>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setPreview(null)
            }}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm"
          />
        </label>
        <label className="block text-sm" htmlFor="import-unit">
          <span className="mb-1 block font-medium text-slate-700">Unit when the file has none</span>
          <UnitSelect
            id="import-unit"
            value={unit}
            onChange={(u) => {
              setUnit(u)
              setPreview(null)
            }}
          />
        </label>
        <fieldset className="text-sm">
          <legend className="mb-1 font-medium text-slate-700">Existing rooms</legend>
          <div className="flex gap-4 py-2">
            {(['append', 'replace'] as const).map((m) => (
              <label key={m} className="flex items-center gap-1.5">
                <input type="radio" name="import-mode" checked={mode === m} onChange={() => setMode(m)} className="accent-brand-600" />
                {m === 'append' ? 'Keep and add' : 'Replace all'}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <ErrorText>{error}</ErrorText>

      {preview && (
        <div className="space-y-3">
          {preview.errors.length > 0 && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
              <p className="font-medium">{plural(preview.errors.length, 'row')} can't be imported:</p>
              <ul className="mt-1 list-disc pl-5">
                {preview.errors.map((e) => (
                  <li key={e.row}>
                    Row {e.row}: {e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {preview.rooms.length > 0 && (
            <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Room</th>
                    <th className="px-3 py-2 font-medium">Floor</th>
                    <th className="px-3 py-2 font-medium">Length × Width</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.rooms.map((r) => (
                    <tr key={r.id}>
                      <td className="px-3 py-2">{r.name}</td>
                      <td className="px-3 py-2 text-slate-600">{r.floor ?? '–'}</td>
                      <td className="px-3 py-2 tabular-nums">
                        {formatLength(r.length_mm, r.unit)} × {formatLength(r.width_mm, r.unit)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {preview && preview.rooms.length > 0 ? (
          <Button onClick={() => run(false)} disabled={busy}>
            {busy ? 'Importing…' : `Import ${plural(preview.rooms.length, 'room')}`}
          </Button>
        ) : (
          <Button onClick={() => run(true)} disabled={!file || busy}>
            {busy ? 'Reading…' : 'Preview'}
          </Button>
        )}
        <button type="button" onClick={onClose} className="text-sm text-slate-600 hover:underline">
          Cancel
        </button>
      </div>
    </div>
  )
}
