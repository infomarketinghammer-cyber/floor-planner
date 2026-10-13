import { useEffect, useMemo, useState, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'
import { api } from '../../api/client.ts'
import type { LengthUnit, PlanUnit, ReviewRoom, RoomsState, RoomUpdate } from '../../api/types.ts'
import { formatArea, plural, useAreaUnit } from '../../lib/format.ts'
import { bareNumber, editableLength, formatLength, lengthUnitLabels, roomArea } from '../../lib/units.ts'
import { Button, ErrorText } from '../ui.tsx'
import { PlanViewer } from './PlanViewer.tsx'
import { AddRoomForm, ImportPanel, UNITS, type ImportOptions, type NewRoom } from './RoomForms.tsx'
import type { RoomsReview } from './useRoomsReview.ts'

const UNIT_SHORT: Record<LengthUnit, string> = { ft_in: 'ft-in', ft: 'ft', in: 'in', m: 'm', cm: 'cm', mm: 'mm' }
const ORIGIN_LABELS: Record<ReviewRoom['origin'], string> = {
  auto: 'From plan',
  edited: 'From plan, edited',
  manual: 'Added by hand',
  imported: 'Imported',
}
const LEVEL_STYLES = {
  high: 'bg-green-100 text-green-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-red-100 text-red-800',
} as const

type Filter = 'all' | 'review' | 'issues' | 'confirmed'
type Panel = 'none' | 'add' | 'import'

interface RoomActions {
  update: (data: RoomUpdate, label: string) => Promise<boolean>
  setUnit: (unit: LengthUnit) => Promise<boolean>
  followPlanUnit: () => Promise<boolean>
  toggleConfirm: () => Promise<boolean>
  remove: () => Promise<boolean>
}

/** Room review (PRD 4.3/4.4). `review` is shared with the materials section (one undo history). */
export function RoomsSection({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const { state, busy, mutate } = review
  const [panel, setPanel] = useState<Panel>('none')
  const [filter, setFilter] = useState<Filter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [areaUnit] = useAreaUnit()

  const rooms = useMemo(() => state?.rooms ?? [], [state])
  const selected = rooms.find((r) => r.id === selectedId) ?? null
  const visible = rooms.filter((r) =>
    filter === 'review' ? !r.confirmed && !r.skipped : filter === 'issues' ? r.issues.length > 0 : filter === 'confirmed' ? r.confirmed : true,
  )
  const confirmable = rooms.filter((r) => !r.confirmed && !r.skipped && r.issues.length === 0)
  const planUnit = state?.plan_unit ?? null
  const defaultUnit: LengthUnit = planUnit?.unit ?? 'ft_in'

  // Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z, except while typing (inputs keep their own undo).
  const { undo, redo } = review
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      const target = e.target as HTMLElement
      if (!(e.ctrlKey || e.metaKey) || target.closest('input, textarea, select, [contenteditable]')) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        void undo()
      } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault()
        void redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo])

  function actionsFor(room: ReviewRoom): RoomActions {
    return {
      update: (data, label) => mutate(label, () => api.rooms.update(projectId, room.id, data)),
      setUnit: (unit) => {
        // "The unit was wrong": keep the digits, read them in the new unit.
        const data: RoomUpdate = { unit }
        if (room.length_mm !== null) data.length = bareNumber(room.length_mm, room.unit)
        if (room.width_mm !== null) data.width = bareNumber(room.width_mm, room.unit)
        return mutate(`Change unit of ${room.name}`, () => api.rooms.update(projectId, room.id, data))
      },
      followPlanUnit: () =>
        mutate(`Use plan unit for ${room.name}`, () =>
          api.rooms.update(projectId, room.id, { follow_plan_unit: true }),
        ),
      toggleConfirm: () =>
        mutate(`${room.confirmed ? 'Un-confirm' : 'Confirm'} ${room.name}`, () =>
          api.rooms.update(projectId, room.id, { confirmed: !room.confirmed }),
        ),
      remove: async () => {
        if (selectedId === room.id) setSelectedId(null)
        return mutate(`Delete ${room.name}`, () => api.rooms.remove(projectId, room.id))
      },
    }
  }

  async function addRoom(data: NewRoom) {
    // Errors (e.g. an unreadable length) are shown inside the form, so let them through.
    await mutate(`Add ${data.name}`, () => api.rooms.add(projectId, data), { rethrow: true })
  }

  async function importRooms(file: File, options: ImportOptions) {
    const ok = await mutate('Import room list', async () => {
      await api.rooms.import(projectId, file, { ...options, dryRun: false })
      return api.rooms.list(projectId)
    })
    if (ok) setPanel('none')
  }

  const togglePanel = (next: Panel) => setPanel((current) => (current === next ? 'none' : next))

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Rooms</h2>
          <p className="text-sm text-slate-500">
            Check each room against the plan, fix anything that's wrong, then confirm it.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => togglePanel('import')}
            aria-expanded={panel === 'import'}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Import Excel / CSV
          </button>
          <Button onClick={() => togglePanel('add')} aria-expanded={panel === 'add'}>
            + Add room
          </Button>
        </div>
      </div>

      {panel === 'add' && <AddRoomForm defaultUnit={defaultUnit} onAdd={addRoom} onClose={() => setPanel('none')} />}
      {panel === 'import' && (
        <ImportPanel
          projectId={projectId}
          hasRooms={rooms.length > 0}
          defaultUnit={defaultUnit}
          onCommit={importRooms}
          onClose={() => setPanel('none')}
        />
      )}

      {state && state.rooms.length > 0 && (
        <PlanUnitCard
          key={`${state.plan_unit.unit}-${state.plan_unit.confirmed}`}
          state={state}
          busy={busy}
          onSet={(unit) =>
            mutate(
              state.plan_unit.confirmed ? `Change plan unit to ${UNIT_SHORT[unit]}` : 'Confirm plan unit',
              () => api.rooms.setPlanUnit(projectId, unit, state.version),
            )
          }
        />
      )}

      {state && state.rooms.length > 0 && (
        <ReviewBar
          state={state}
          busy={busy}
          confirmableCount={confirmable.length}
          onConfirmAll={() =>
            mutate(`Confirm ${plural(confirmable.length, 'room')}`, () =>
              api.rooms.confirm(
                projectId,
                confirmable.map((r) => r.id),
              ),
            )
          }
          undoLabel={review.undoLabel}
          redoLabel={review.redoLabel}
          onUndo={review.undo}
          onRedo={review.redo}
        />
      )}

      <ErrorText>{review.error}</ErrorText>

      {selected && (
        <PlanViewer
          projectId={projectId}
          rooms={rooms}
          selected={selected}
          onSelect={setSelectedId}
          onClose={() => setSelectedId(null)}
        />
      )}

      {state && rooms.length === 0 && panel === 'none' && (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
          No rooms yet. Upload a blueprint above, add rooms by hand, or import a room list.
        </p>
      )}

      {rooms.length > 0 && (
        <>
          <FilterTabs filter={filter} onChange={setFilter} rooms={rooms} />

          {visible.length === 0 ? (
            <p className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
              No rooms in this view.
            </p>
          ) : (
            <>
              {/* Phones: one card per room */}
              <ul className="space-y-3 md:hidden">
                {visible.map((room) => (
                  <RoomCard
                    key={room.id}
                    room={room}
                    planUnit={planUnit}
                    areaUnit={areaUnit}
                    selected={room.id === selectedId}
                    onSelect={() => setSelectedId(room.id)}
                    actions={actionsFor(room)}
                  />
                ))}
              </ul>

              <div className="relative hidden overflow-x-auto rounded-xl border border-slate-200 bg-white md:block">
                <table className="w-full min-w-[980px] text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="w-32 px-3 py-3 font-medium">Status</th>
                      <th className="px-3 py-3 font-medium">Room</th>
                      <th className="w-36 px-3 py-3 font-medium">Floor</th>
                      <th className="w-28 px-3 py-3 font-medium">Length</th>
                      <th className="w-28 px-3 py-3 font-medium">Width</th>
                      <th className="w-32 px-3 py-3 font-medium">Unit</th>
                      <th className="w-24 px-3 py-3 text-right font-medium">Area</th>
                      <th className="px-3 py-3 font-medium">Check</th>
                      <th className="w-16 px-3 py-3">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visible.map((room) => (
                      <RoomRow
                        key={room.id}
                        room={room}
                        planUnit={planUnit}
                        areaUnit={areaUnit}
                        selected={room.id === selectedId}
                        onSelect={() => setSelectedId(room.id)}
                        actions={actionsFor(room)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="text-xs text-slate-500">
            Click a room to see where it was read on the plan. Edits save automatically; press Ctrl+Z to undo.
          </p>
        </>
      )}
    </section>
  )
}

// --- Review summary ---------------------------------------------------------------------

function ReviewBar({
  state,
  busy,
  confirmableCount,
  onConfirmAll,
  undoLabel,
  redoLabel,
  onUndo,
  onRedo,
}: {
  state: NonNullable<RoomsReview['state']>
  busy: boolean
  confirmableCount: number
  onConfirmAll: () => void
  undoLabel: string | null
  redoLabel: string | null
  onUndo: () => void
  onRedo: () => void
}) {
  const { review } = state
  const active = review.confirmed + review.to_review
  const pct = active ? Math.round((review.confirmed / active) * 100) : 0
  return (
    <div
      className={`space-y-3 rounded-xl border p-4 ${review.ready ? 'border-green-200 bg-green-50' : 'border-slate-200 bg-white'}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium" role="status">
            {review.ready
              ? 'All rooms confirmed. Ready for tile assignment.'
              : `${review.confirmed} of ${plural(active, 'room')} confirmed`}
          </p>
          {!review.ready && (
            <p className="text-sm text-slate-500">
              Confirm or delete every room before calculating.
              {review.unit_pending && ' Confirm the plan unit too.'}
              {review.blocking > 0 && ` ${plural(review.blocking, 'room')} must be fixed first.`}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <IconButton onClick={onUndo} disabled={!undoLabel || busy} title={undoLabel ? `Undo: ${undoLabel} (Ctrl+Z)` : 'Nothing to undo'}>
            ↶ Undo
          </IconButton>
          <IconButton onClick={onRedo} disabled={!redoLabel || busy} title={redoLabel ? `Redo: ${redoLabel} (Ctrl+Y)` : 'Nothing to redo'}>
            ↷ Redo
          </IconButton>
          {confirmableCount > 0 && (
            <Button onClick={onConfirmAll} disabled={busy}>
              Confirm {plural(confirmableCount, 'room')} without issues
            </Button>
          )}
        </div>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Rooms confirmed"
      >
        <div className="h-full rounded-full bg-green-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function IconButton({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button
      {...props}
      className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function FilterTabs({ filter, onChange, rooms }: { filter: Filter; onChange: (f: Filter) => void; rooms: ReviewRoom[] }) {
  const counts: Record<Filter, number> = {
    all: rooms.length,
    review: rooms.filter((r) => !r.confirmed && !r.skipped).length,
    issues: rooms.filter((r) => r.issues.length > 0).length,
    confirmed: rooms.filter((r) => r.confirmed).length,
  }
  const labels: Record<Filter, string> = { all: 'All', review: 'To review', issues: 'With issues', confirmed: 'Confirmed' }
  return (
    <div role="tablist" aria-label="Filter rooms" className="flex flex-wrap gap-1">
      {(Object.keys(labels) as Filter[]).map((f) => (
        <button
          key={f}
          role="tab"
          aria-selected={filter === f}
          onClick={() => onChange(f)}
          className={`rounded-full px-3 py-1 text-sm ${
            filter === f ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'
          }`}
        >
          {labels[f]} <span className="tabular-nums opacity-70">{counts[f]}</span>
        </button>
      ))}
    </div>
  )
}

// --- Editing ------------------------------------------------------------------------------

/** Text field that saves on blur or Enter; Esc cancels. Remount (key) to reset after saves. */
function EditableText({
  value,
  onCommit,
  label,
  placeholder,
  className = '',
  maxLength = 100,
  list,
}: {
  value: string
  onCommit: (value: string) => Promise<boolean>
  label: string
  placeholder?: string
  className?: string
  maxLength?: number
  list?: string
}) {
  const [draft, setDraft] = useState(value)

  async function commit() {
    const next = draft.trim()
    if (next === value.trim()) return setDraft(value)
    if (!(await onCommit(next))) setDraft(value)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') e.currentTarget.blur()
    if (e.key === 'Escape') {
      setDraft(value)
      requestAnimationFrame(() => (e.target as HTMLInputElement).blur())
    }
  }

  return (
    <input
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={onKeyDown}
      aria-label={label}
      placeholder={placeholder}
      maxLength={maxLength}
      list={list}
      className={`w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 hover:border-slate-300 focus:border-brand-600 focus:bg-white focus:outline-none focus:ring-1 focus:ring-brand-600 ${className}`}
    />
  )
}

/** "Plan" = follow the plan unit; a specific unit = this room's own unit (an override). */
function UnitPicker({
  room,
  planUnit,
  actions,
}: {
  room: ReviewRoom
  planUnit: PlanUnit | null
  actions: RoomActions
}) {
  const follows = !room.unit_explicit
  const unconfirmed = follows && planUnit?.required && !planUnit.confirmed
  return (
    <select
      value={follows ? 'plan' : room.unit}
      onChange={(e) =>
        void (e.target.value === 'plan' ? actions.followPlanUnit() : actions.setUnit(e.target.value as LengthUnit))
      }
      aria-label={`Unit for ${room.name}`}
      title={
        follows
          ? 'Uses the plan unit. Pick a unit to give this room its own (the same numbers are re-read in it).'
          : "This room has its own unit. If it's wrong, pick the right one: the same numbers are re-read in it."
      }
      className={`w-full rounded-md border px-1.5 py-1.5 text-sm ${
        unconfirmed ? 'border-amber-400 bg-amber-50' : 'border-transparent bg-transparent hover:border-slate-300'
      }`}
    >
      {planUnit?.unit && <option value="plan">Plan · {UNIT_SHORT[planUnit.unit]}</option>}
      {UNITS.map((u) => (
        <option key={u} value={u}>
          {UNIT_SHORT[u]}
        </option>
      ))}
    </select>
  )
}

/** Plan unit (PRD 4.4): auto-detected, explained, and confirmed by the user. */
function PlanUnitCard({
  state,
  busy,
  onSet,
}: {
  state: RoomsState
  busy: boolean
  onSet: (unit: LengthUnit) => Promise<boolean>
}) {
  const pu = state.plan_unit
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState<LengthUnit>(pu.unit ?? pu.detected ?? 'ft_in')
  const followers = state.rooms.filter((r) => !r.unit_explicit)
  const pending = pu.required && !pu.confirmed

  async function apply() {
    const moving = followers.filter((r) => r.unit !== choice && r.length_mm !== null)
    if (
      moving.length &&
      !confirm(
        `${plural(moving.length, 'room')} without their own unit will be re-read in ${lengthUnitLabels[choice].toLowerCase()} ` +
          '(the same numbers, new unit) and will need confirming again. Continue?',
      )
    )
      return
    if (await onSet(choice)) setEditing(false)
  }

  const picker = (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={choice}
        onChange={(e) => setChoice(e.target.value as LengthUnit)}
        aria-label="Plan unit"
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
      >
        {UNITS.map((u) => (
          <option key={u} value={u}>
            {lengthUnitLabels[u]}
            {u === pu.detected ? ' (detected)' : ''}
          </option>
        ))}
      </select>
      <Button onClick={apply} disabled={busy}>
        {pending ? 'Confirm unit' : 'Apply'}
      </Button>
      {!pending && (
        <button onClick={() => setEditing(false)} className="text-sm text-slate-600 hover:underline">
          Cancel
        </button>
      )}
    </div>
  )

  if (pending) {
    return (
      <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4">
        <div>
          <p className="font-medium text-amber-900">Confirm the plan's unit</p>
          <p className="text-sm text-amber-800">
            {pu.detected ? (
              <>
                We think this plan is in <strong>{lengthUnitLabels[pu.detected].toLowerCase()}</strong>. {pu.evidence}
              </>
            ) : (
              "We couldn't tell which unit this plan uses."
            )}
          </p>
          <p className="mt-1 text-xs text-amber-800">
            Rooms without a written unit use it. Sizes written with their own unit (like 3.6 m) keep theirs.
          </p>
        </div>
        {picker}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
      {editing ? (
        picker
      ) : (
        <>
          <span>
            <span className="text-slate-500">Plan unit: </span>
            <span className="font-medium">{pu.unit ? lengthUnitLabels[pu.unit] : 'Not set'}</span>
            {pu.confirmed && <span className="ml-1.5 text-green-700">✓ confirmed</span>}
            <span className="ml-2 text-xs text-slate-400">
              {plural(followers.length, 'room')} {followers.length === 1 ? 'uses' : 'use'} it
            </span>
          </span>
          <button
            onClick={() => {
              setChoice(pu.unit ?? 'ft_in')
              setEditing(true)
            }}
            className="font-medium text-brand-700 hover:underline"
          >
            Change
          </button>
        </>
      )}
    </div>
  )
}

function ConfirmButton({ room, onToggle }: { room: ReviewRoom; onToggle: () => void }) {
  if (room.skipped) {
    return (
      <span title="Marked as needing no tiles in Tiles & materials" className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">
        No tiling
      </span>
    )
  }
  const blocking = room.issues.find((i) => i.severity === 'block')
  if (room.confirmed) {
    return (
      <button
        onClick={onToggle}
        title="Click to un-confirm"
        className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-800 hover:bg-green-200"
      >
        ✓ Confirmed
      </button>
    )
  }
  return (
    <button
      onClick={onToggle}
      disabled={!!blocking}
      title={blocking ? blocking.message : 'Confirm this room is correct'}
      className="rounded-full border border-brand-600 px-2.5 py-1 text-xs font-semibold text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400"
    >
      Confirm
    </button>
  )
}

function Issues({ room }: { room: ReviewRoom }) {
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {room.confidence_level && room.origin === 'auto' && !room.confirmed && !room.skipped && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${LEVEL_STYLES[room.confidence_level]}`}
            title={room.confidence !== null ? `Confidence ${Math.round(room.confidence * 100)}%` : undefined}
          >
            {room.confidence_level} confidence
          </span>
        )}
        <span className="text-xs text-slate-400">{ORIGIN_LABELS[room.origin]}</span>
      </div>
      {room.origin === 'edited' && room.extracted && <PlanRead room={room} />}
      {room.issues.map((issue) => (
        <p key={issue.code} className={`text-xs ${issue.severity === 'block' ? 'text-red-700' : 'text-amber-700'}`}>
          {issue.severity === 'block' ? '✕' : '⚠'} {issue.message}
        </p>
      ))}
    </div>
  )
}

/** What the plan reader originally read, for a room the user has corrected (PRD 4.13). */
function PlanRead({ room }: { room: ReviewRoom }) {
  const read = room.extracted!
  const size =
    read.length_mm !== null && read.width_mm !== null
      ? `${formatLength(read.length_mm, read.unit)} × ${formatLength(read.width_mm, read.unit)}`
      : 'no size'
  return (
    <p className="text-xs text-slate-500" title="What was read from the plan before your changes">
      Plan read: {read.name} · {size}
    </p>
  )
}

function LengthField({
  room,
  side,
  actions,
}: {
  room: ReviewRoom
  side: 'length' | 'width'
  actions: RoomActions
}) {
  const mm = side === 'length' ? room.length_mm : room.width_mm
  const value = editableLength(mm, room.unit)
  return (
    <EditableText
      key={`${mm}-${room.unit}`}
      value={value}
      label={`${side === 'length' ? 'Length' : 'Width'} of ${room.name}`}
      placeholder={mm === null ? (room.area_mm2 ? 'by area' : 'Enter') : undefined}
      maxLength={30}
      className={`tabular-nums ${mm === null && !room.area_mm2 ? 'border-red-300 bg-red-50' : ''}`}
      onCommit={(text) => actions.update({ [side]: text, unit: room.unit }, `Change ${side} of ${room.name}`)}
    />
  )
}

function RoomRow({
  room,
  planUnit,
  areaUnit,
  selected,
  onSelect,
  actions,
}: {
  room: ReviewRoom
  planUnit: PlanUnit | null
  areaUnit: 'sqft' | 'sqm'
  selected: boolean
  onSelect: () => void
  actions: RoomActions
}) {
  const area = roomArea(room, areaUnit)
  const hasBlock = room.issues.some((i) => i.severity === 'block')
  return (
    <tr
      onClick={onSelect}
      onFocusCapture={onSelect}
      aria-selected={selected}
      className={`cursor-pointer align-top ${
        selected ? 'bg-brand-50' : hasBlock ? 'bg-red-50/40 hover:bg-slate-50' : 'hover:bg-slate-50'
      }`}
    >
      <td className="px-3 py-2.5">
        <ConfirmButton room={room} onToggle={actions.toggleConfirm} />
      </td>
      <td className="px-1 py-1.5 font-medium">
        <EditableText
          key={room.name}
          value={room.name}
          label="Room name"
          onCommit={(name) => (name ? actions.update({ name }, `Rename ${room.name}`) : Promise.resolve(false))}
        />
      </td>
      <td className="px-1 py-1.5">
        <EditableText
          key={room.floor ?? ''}
          value={room.floor ?? ''}
          label={`Floor of ${room.name}`}
          placeholder="–"
          maxLength={50}
          list="floor-suggestions"
          onCommit={(floor) => actions.update({ floor: floor || null }, `Change floor of ${room.name}`)}
        />
      </td>
      <td className="px-1 py-1.5">
        <LengthField room={room} side="length" actions={actions} />
      </td>
      <td className="px-1 py-1.5">
        <LengthField room={room} side="width" actions={actions} />
      </td>
      <td className="px-1 py-1.5">
        <UnitPicker room={room} planUnit={planUnit} actions={actions} />
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">{area === null ? '–' : formatArea(area, areaUnit)}</td>
      <td className="px-3 py-2.5">
        <Issues room={room} />
      </td>
      <td className="px-3 py-2.5 text-right">
        <button
          onClick={(e) => {
            e.stopPropagation()
            void actions.remove()
          }}
          aria-label={`Delete ${room.name}`}
          className="text-sm text-red-600 hover:underline"
        >
          Delete
        </button>
      </td>
    </tr>
  )
}

function RoomCard({
  room,
  planUnit,
  areaUnit,
  selected,
  onSelect,
  actions,
}: {
  room: ReviewRoom
  planUnit: PlanUnit | null
  areaUnit: 'sqft' | 'sqm'
  selected: boolean
  onSelect: () => void
  actions: RoomActions
}) {
  const area = roomArea(room, areaUnit)
  return (
    <li
      onClick={onSelect}
      onFocusCapture={onSelect}
      className={`space-y-2 rounded-xl border bg-white p-3 ${selected ? 'border-brand-600 ring-1 ring-brand-600' : 'border-slate-200'}`}
    >
      <div className="flex items-center justify-between gap-2">
        <ConfirmButton room={room} onToggle={actions.toggleConfirm} />
        <span className="text-sm tabular-nums text-slate-600">{area === null ? '–' : formatArea(area, areaUnit)}</span>
      </div>
      <EditableText
        key={room.name}
        value={room.name}
        label="Room name"
        className="font-medium"
        onCommit={(name) => (name ? actions.update({ name }, `Rename ${room.name}`) : Promise.resolve(false))}
      />
      <div className="grid grid-cols-[1fr_auto_1fr_7rem] items-center gap-1 text-sm">
        <LengthField room={room} side="length" actions={actions} />
        <span className="text-slate-400">×</span>
        <LengthField room={room} side="width" actions={actions} />
        <UnitPicker room={room} planUnit={planUnit} actions={actions} />
      </div>
      <EditableText
        key={room.floor ?? ''}
        value={room.floor ?? ''}
        label={`Floor of ${room.name}`}
        placeholder="Floor"
        maxLength={50}
        list="floor-suggestions"
        className="text-sm"
        onCommit={(floor) => actions.update({ floor: floor || null }, `Change floor of ${room.name}`)}
      />
      <Issues room={room} />
      <button
        onClick={(e) => {
          e.stopPropagation()
          void actions.remove()
        }}
        className="text-sm text-red-600 hover:underline"
      >
        Delete room
      </button>
    </li>
  )
}
