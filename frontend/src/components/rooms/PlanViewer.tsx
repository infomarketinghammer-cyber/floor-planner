import { useState, type ReactNode } from 'react'
import { api } from '../../api/client.ts'
import { useApiImage } from '../../lib/apiImage.tsx'
import type { ReviewRoom } from '../../api/types.ts'

const METHOD_LABELS = { pdf_text: 'PDF text', dxf_text: 'CAD drawing', vision: 'Read by AI' } as const
const PAD = 0.006 // expand boxes slightly so the outline doesn't sit on the text

function boxStyle(bbox: number[], zoom: number) {
  const [x0, y0, x1, y1] = bbox
  return {
    left: `${(x0 - PAD) * 100}%`,
    top: `${(y0 - PAD) * 100}%`,
    width: `${(x1 - x0 + 2 * PAD) * 100}%`,
    height: `${(y1 - y0 + 2 * PAD) * 100}%`,
    borderWidth: `${2 / zoom}px`,
  }
}

/**
 * Shows the plan page a room was read from, with every room on that page outlined and the
 * selected one highlighted (PRD 4.3). Clicking an outline selects that room.
 */
export function PlanViewer({
  projectId,
  rooms,
  selected,
  onSelect,
  onClose,
}: {
  projectId: string
  rooms: ReviewRoom[]
  selected: ReviewRoom
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const [zoomed, setZoomed] = useState(true)
  const [failed, setFailed] = useState<string | null>(null)
  // Works for projects kept in the browser too (guest mode).
  const resolved = useApiImage(selected?.source ? api.files.previewUrl(projectId, selected.source.file_id, selected.source.page) : '')
  const source = selected.source

  if (!source || !source.bbox) {
    return (
      <Frame title={selected.name} onClose={onClose}>
        <p className="px-4 py-8 text-center text-sm text-slate-500">
          {selected.origin === 'manual'
            ? 'This room was added by hand, so it has no location on a plan.'
            : selected.origin === 'imported'
              ? 'This room came from an imported list, so it has no location on a plan.'
              : 'No plan location was recorded for this room.'}
        </p>
      </Frame>
    )
  }

  const src = resolved ?? ''
  const onPage = rooms.filter(
    (r) => r.source?.bbox && r.source.file_id === source.file_id && r.source.page === source.page,
  )
  const [x0, y0, x1, y1] = source.bbox
  const zoom = zoomed ? Math.min(4, Math.max(1.5, 0.35 / Math.max(x1 - x0, y1 - y0))) : 1
  const origin = `${((x0 + x1) / 2) * 100}% ${((y0 + y1) / 2) * 100}%`

  return (
    <Frame
      title={selected.name}
      subtitle={`${METHOD_LABELS[source.method]} · page ${source.page + 1}${source.text ? ` · read "${source.text}"` : ''}`}
      onClose={onClose}
      actions={
        <button
          onClick={() => setZoomed((z) => !z)}
          aria-pressed={zoomed}
          className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-50"
        >
          {zoomed ? 'Show whole page' : 'Zoom to room'}
        </button>
      }
    >
      {!src ? (
        <p className="px-4 py-8 text-center text-sm text-slate-500">Loading the plan…</p>
      ) : failed === src ? (
        <p className="px-4 py-8 text-center text-sm text-slate-500">The plan preview couldn't be loaded.</p>
      ) : (
        <div className="overflow-hidden bg-slate-100">
          <div
            className="relative mx-auto max-h-[45vh] w-fit transition-transform duration-300"
            style={{ transform: `scale(${zoom})`, transformOrigin: origin }}
          >
            <img
              src={src}
              alt={`Plan page ${source.page + 1}`}
              onError={() => setFailed(src)}
              className="block max-h-[45vh] w-auto max-w-full"
            />
            {onPage.map((room) => {
              const active = room.id === selected.id
              return (
                <button
                  key={room.id}
                  type="button"
                  onClick={() => onSelect(room.id)}
                  title={room.name}
                  aria-label={`Select ${room.name}`}
                  style={boxStyle(room.source!.bbox!, zoom)}
                  className={`absolute rounded-sm ${
                    active
                      ? 'z-10 border-brand-600 bg-brand-600/15 ring-4 ring-brand-600/25'
                      : room.confirmed
                        ? 'border-green-600/70 bg-green-500/5 hover:bg-green-500/15'
                        : 'border-amber-500/80 bg-amber-400/5 hover:bg-amber-400/20'
                  }`}
                />
              )
            })}
          </div>
        </div>
      )}
      <p className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 text-xs text-slate-500">
        <Legend className="border-brand-600 bg-brand-600/15">Selected</Legend>
        <Legend className="border-amber-500">To review</Legend>
        <Legend className="border-green-600">Confirmed</Legend>
      </p>
    </Frame>
  )
}

function Legend({ className, children }: { className: string; children: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-3 w-4 rounded-sm border-2 ${className}`} />
      {children}
    </span>
  )
}

function Frame({
  title,
  subtitle,
  actions,
  onClose,
  children,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  return (
    <section aria-label="Plan location" className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{title} on the plan</h3>
          {subtitle && <p className="truncate text-xs text-slate-500">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          <button onClick={onClose} className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">
            Close
          </button>
        </div>
      </header>
      {children}
    </section>
  )
}
