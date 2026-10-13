import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../../api/client.ts'
import type { Tile, TileRef } from '../../api/types.ts'

/** Button showing the chosen tile; opens a searchable list of the user's library. */
export function TilePicker({
  value,
  onChange,
  placeholder = 'Choose a tile',
  label,
}: {
  value: TileRef | null
  onChange: (tile: Tile) => void
  placeholder?: string
  label: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={label}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-left text-sm hover:bg-slate-50"
      >
        {value ? (
          <span className="min-w-0">
            <span className="font-medium">{value.size_label}</span>{' '}
            <span className="truncate text-slate-500">{value.name}</span>
          </span>
        ) : (
          <span className="text-slate-500">{placeholder}</span>
        )}
        <span aria-hidden="true" className="text-slate-400">
          ▾
        </span>
      </button>
      {open && (
        <TilePickerDialog
          selectedId={value?.id ?? null}
          onPick={(tile) => {
            onChange(tile)
            setOpen(false)
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

function TilePickerDialog({
  selectedId,
  onPick,
  onClose,
}: {
  selectedId: string | null
  onPick: (tile: Tile) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [query, setQuery] = useState('')
  const [tiles, setTiles] = useState<Tile[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    ref.current?.showModal()
  }, [])

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      api.tiles
        .list({ q: query.trim() })
        .then((list) => !cancelled && setTiles(list))
        .catch((err: Error) => !cancelled && setError(err.message))
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  // Your own tiles first: they carry your supplier's pack sizes.
  const sorted = tiles ? [...tiles].sort((a, b) => (a.scope === b.scope ? 0 : a.scope === 'user' ? -1 : 1)) : null

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-xl border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="space-y-3 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Choose a tile</h2>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100">
            Close
          </button>
        </div>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, brand or code"
          aria-label="Search tiles"
          autoFocus
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        {error && <p className="text-sm text-red-700">{error}</p>}
        <ul className="max-h-[50vh] divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200" role="listbox">
          {sorted === null && <li className="px-3 py-4 text-sm text-slate-500">Loading…</li>}
          {sorted?.length === 0 && (
            <li className="px-3 py-4 text-sm text-slate-500">
              No tiles found.{' '}
              <Link to="/tiles" className="text-brand-700 hover:underline">
                Add one in the tile library
              </Link>
              .
            </li>
          )}
          {sorted?.map((tile) => (
            <li key={tile.id}>
              <button
                type="button"
                role="option"
                aria-selected={tile.id === selectedId}
                onClick={() => onPick(tile)}
                className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                  tile.id === selectedId ? 'bg-brand-50' : ''
                }`}
              >
                <span className="min-w-0">
                  <span className="block font-medium">{tile.size_label}</span>
                  <span className="block truncate text-xs text-slate-500">{tile.name}</span>
                </span>
                <span className="shrink-0 text-right text-xs text-slate-500">
                  {tile.tiles_per_box}/box
                  <span className={`ml-2 rounded-full px-1.5 py-0.5 ${tile.scope === 'user' ? 'bg-brand-50 text-brand-700' : 'bg-slate-100'}`}>
                    {tile.scope === 'user' ? 'Mine' : 'Catalogue'}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </dialog>
  )
}
