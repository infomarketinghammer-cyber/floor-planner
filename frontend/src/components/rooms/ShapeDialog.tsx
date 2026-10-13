import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { LengthUnit, ReviewRoom } from '../../api/types.ts'
import { editableLength, lengthUnitLabels } from '../../lib/units.ts'
import { Button, ErrorText } from '../ui.tsx'

const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'

interface PartRow {
  label: string
  length: string
  width: string
  x: string
  y: string
}

export interface ShapeData {
  parts: PartRow[]
  perimeter: string | null
  unit: LengthUnit
}

/**
 * Split a non-rectangular room into rectangles (PRD 4.16): an L-shaped living room is a main
 * area plus a nook. Positions are optional (parts are placed side by side) and only affect the
 * drawing; each rectangle is counted on its own.
 */
export function ShapeDialog({
  room,
  onSave,
  onClose,
}: {
  room: ReviewRoom
  onSave: (data: ShapeData) => Promise<void>
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  const unit = room.unit
  const [rows, setRows] = useState<PartRow[]>(() =>
    room.parts.length
      ? room.parts.map((p) => ({
          label: p.label,
          length: editableLength(p.length_mm, unit),
          width: editableLength(p.width_mm, unit),
          x: editableLength(p.x_mm, unit),
          y: editableLength(p.y_mm, unit),
        }))
      : [
          {
            label: 'Main',
            length: editableLength(room.length_mm, unit),
            width: editableLength(room.width_mm, unit),
            x: '',
            y: '',
          },
          { label: '', length: '', width: '', x: '', y: '' },
        ],
  )
  const [perimeter, setPerimeter] = useState(room.perimeter_mm ? editableLength(room.perimeter_mm, unit) : '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const update = (i: number, patch: Partial<PartRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  async function save(parts: PartRow[]) {
    setError('')
    setSaving(true)
    try {
      await onSave({ parts, perimeter: perimeter.trim() || null, unit })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const parts = rows.filter((r) => r.length.trim() || r.width.trim())
    if (parts.length < 2) return setError('Add at least two rectangles, or use "Back to one rectangle".')
    void save(parts.map((p) => ({ ...p, x: p.x.trim(), y: p.y.trim() })))
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.stopPropagation()}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <form onSubmit={submit} className="max-h-[90vh] space-y-4 overflow-y-auto p-6">
        <div>
          <h2 className="text-lg font-semibold">Room shape: {room.name}</h2>
          <p className="text-sm text-slate-500">
            For a room that isn't a simple rectangle, split it into rectangles, like a main area and a nook. Sizes in{' '}
            {lengthUnitLabels[unit].toLowerCase()}.
          </p>
        </div>
        <ErrorText>{error}</ErrorText>
        <ul className="space-y-2">
          {rows.map((r, i) => (
            <li key={i} className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-2 sm:grid-cols-[1fr_5.5rem_5.5rem_5rem_5rem_auto]">
              <input
                value={r.label}
                onChange={(e) => update(i, { label: e.target.value })}
                maxLength={40}
                placeholder={`Part ${i + 1}`}
                aria-label={`Part ${i + 1} name`}
                className={`${inputClass} col-span-2 sm:col-span-1`}
              />
              <input value={r.length} onChange={(e) => update(i, { length: e.target.value })} placeholder="Length" aria-label={`Part ${i + 1} length`} className={inputClass} />
              <input value={r.width} onChange={(e) => update(i, { width: e.target.value })} placeholder="Width" aria-label={`Part ${i + 1} width`} className={inputClass} />
              <input
                value={r.x}
                onChange={(e) => update(i, { x: e.target.value })}
                placeholder="From left"
                title="Optional: distance from the room's left edge, for the drawing"
                aria-label={`Part ${i + 1} distance from the left`}
                className={inputClass}
              />
              <input
                value={r.y}
                onChange={(e) => update(i, { y: e.target.value })}
                placeholder="From top"
                title="Optional: distance from the room's top edge, for the drawing"
                aria-label={`Part ${i + 1} distance from the top`}
                className={inputClass}
              />
              <button type="button" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} className="text-sm text-red-600 hover:underline">
                Remove
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setRows((rs) => [...rs, { label: '', length: '', width: '', x: '', y: '' }])}
          disabled={rows.length >= 12}
          className="text-sm font-medium text-brand-700 hover:underline"
        >
          + Add a rectangle
        </button>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Perimeter (optional, for skirting and wall tiles)</span>
          <input value={perimeter} onChange={(e) => setPerimeter(e.target.value)} className={`${inputClass} w-40`} />
        </label>
        <p className="text-xs text-slate-500">
          Positions are only used to draw the room. Leave them empty to place the rectangles side by side. Changing the
          shape un-confirms the room.
        </p>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {room.parts.length > 0 ? (
            <button type="button" onClick={() => save([])} className="text-sm text-slate-600 hover:underline" disabled={saving}>
              Back to one rectangle (keeps the first)
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
              Cancel
            </button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save shape'}
            </Button>
          </div>
        </div>
      </form>
    </dialog>
  )
}
