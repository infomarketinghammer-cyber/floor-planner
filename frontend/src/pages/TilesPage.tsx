import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'
import type { Tile, TileInput, TileRegion, TileType } from '../api/types.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import {
  FINISH_LABELS,
  MATERIAL_LABELS,
  REGION_LABELS,
  TileFormDialog,
  TYPE_LABELS,
} from '../components/tiles/TileForm.tsx'
import { Button, ErrorText } from '../components/ui.tsx'
import { formatArea, plural, useAreaUnit } from '../lib/format.ts'

type Scope = 'all' | 'catalog' | 'mine'
const SCOPE_LABELS: Record<Scope, string> = { all: 'All tiles', catalog: 'Catalogue', mine: 'My tiles' }

/** Tile library (PRD 4.5): shared catalogue of common sizes plus the user's own saved tiles. */
export function TilesPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [areaUnit] = useAreaUnit()
  const [scope, setScope] = useState<Scope>('all')
  const [query, setQuery] = useState('')
  const [type, setType] = useState<TileType | ''>('')
  const [region, setRegion] = useState<TileRegion | ''>(areaUnit === 'sqm' ? 'india' : '')
  const [tiles, setTiles] = useState<Tile[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<{ tile: Tile | null } | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      api.tiles
        .list({ scope, q: query.trim(), type, region })
        .then((list) => !cancelled && setTiles(list))
        .catch((err: Error) => !cancelled && setError(err.message))
    }, 200) // debounce typing in the search box
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [scope, query, type, region, reloadKey])

  const reload = (message = '') => {
    setNotice(message)
    setReloadKey((k) => k + 1)
  }

  async function save(data: TileInput, catalog: boolean) {
    const tile = editing?.tile
    if (tile) await api.tiles.update(tile.id, data)
    else await api.tiles.create(data, catalog)
    setEditing(null)
    reload(tile ? `Saved ${data.name}.` : `Added ${data.name}${catalog ? ' to the catalogue' : ' to your tiles'}.`)
  }

  async function copy(tile: Tile) {
    try {
      const created = await api.tiles.copy(tile.id)
      reload(`Copied to your tiles as "${created.name}". Edit it to set your supplier's pack size.`)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function remove(tile: Tile) {
    const where = tile.scope === 'catalog' ? 'the shared catalogue (for every contractor)' : 'your tiles'
    if (!confirm(`Remove "${tile.name}" from ${where}? Projects already using it are not affected.`)) return
    try {
      await api.tiles.remove(tile.id)
      reload(`Removed ${tile.name}.`)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const area = (sqm: number, sqft: number) => formatArea(areaUnit === 'sqm' ? sqm : sqft, areaUnit)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Tile library</h1>
          <p className="text-sm text-slate-500">
            Common sizes to start from, plus your own tiles with your supplier's pack sizes.
          </p>
        </div>
        <Button onClick={() => setEditing({ tile: null })}>+ Add tile</Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Which tiles" className="flex gap-1">
          {(Object.keys(SCOPE_LABELS) as Scope[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={scope === s}
              onClick={() => setScope(s)}
              className={`rounded-full px-3 py-1 text-sm ${
                scope === s ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'
              }`}
            >
              {SCOPE_LABELS[s]}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, brand or code"
          aria-label="Search tiles"
          className="min-w-0 basis-full rounded-md border border-slate-300 px-3 py-2 text-sm sm:max-w-64 sm:flex-1 sm:basis-auto"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value as TileType | '')}
          aria-label="Tile type"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All types</option>
          {(Object.keys(TYPE_LABELS) as TileType[]).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <select
          value={region}
          onChange={(e) => setRegion(e.target.value as TileRegion | '')}
          aria-label="Region"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All regions</option>
          {(Object.keys(REGION_LABELS) as TileRegion[]).map((r) => (
            <option key={r} value={r}>
              {REGION_LABELS[r]}
            </option>
          ))}
        </select>
      </div>

      {notice && (
        <p role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">
          {notice}
        </p>
      )}
      <ErrorText>{error}</ErrorText>

      {tiles === null ? (
        <p className="text-sm text-slate-500">Loading tiles…</p>
      ) : tiles.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center text-sm text-slate-500">
          {scope === 'mine' && !query && !type && !region
            ? 'You have no saved tiles yet. Add one, or copy a catalogue tile to set your own pack size.'
            : 'No tiles match these filters.'}
        </div>
      ) : (
        <>
          <p className="text-xs text-slate-500">{plural(tiles.length, 'tile')}</p>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {tiles.map((tile) => (
              <li key={tile.id} className="flex flex-col rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="font-semibold">{tile.size_label}</h2>
                    <p className="truncate text-sm text-slate-600" title={tile.name}>
                      {tile.name}
                    </p>
                  </div>
                  <TilePreview tile={tile} />
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                  <Badge tone={tile.scope === 'catalog' ? 'slate' : 'blue'}>
                    {tile.scope === 'catalog' ? 'Catalogue' : 'My tile'}
                  </Badge>
                  <Badge>{TYPE_LABELS[tile.type]}</Badge>
                  <Badge>{FINISH_LABELS[tile.finish]}</Badge>
                  <Badge>{MATERIAL_LABELS[tile.material]}</Badge>
                </div>

                <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
                  <dt className="text-slate-500">Per box</dt>
                  <dd className="text-right tabular-nums">
                    {plural(tile.tiles_per_box, 'tile')}
                    {tile.typical && (
                      <span className="ml-1 text-xs text-amber-700" title="Typical pack size. Check with your supplier.">
                        (typical)
                      </span>
                    )}
                  </dd>
                  <dt className="text-slate-500">Coverage</dt>
                  <dd className="text-right tabular-nums">
                    {area(tile.coverage_per_box_sqm, tile.coverage_per_box_sqft)} / box
                  </dd>
                  {tile.thickness_mm && (
                    <>
                      <dt className="text-slate-500">Thickness</dt>
                      <dd className="text-right tabular-nums">{Number(tile.thickness_mm)} mm</dd>
                    </>
                  )}
                  {(tile.brand || tile.code) && (
                    <>
                      <dt className="text-slate-500">Brand / code</dt>
                      <dd className="truncate text-right">{[tile.brand, tile.code].filter(Boolean).join(' · ')}</dd>
                    </>
                  )}
                </dl>

                <div className="mt-auto flex flex-wrap gap-4 pt-4 text-sm">
                  {tile.scope === 'catalog' && (
                    <button onClick={() => copy(tile)} className="font-medium text-brand-700 hover:underline">
                      Copy to my tiles
                    </button>
                  )}
                  {tile.editable && (
                    <>
                      <button onClick={() => setEditing({ tile })} className="text-slate-600 hover:underline">
                        Edit
                      </button>
                      <button onClick={() => remove(tile)} className="text-red-600 hover:underline">
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {editing && (
        <TileFormDialog
          key={editing.tile?.id ?? 'new'}
          open
          tile={editing.tile}
          isAdmin={isAdmin}
          areaUnit={areaUnit}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      )}
    </div>
  )
}

function Badge({ children, tone = 'plain' }: { children: string; tone?: 'plain' | 'slate' | 'blue' }) {
  const styles = {
    plain: 'bg-slate-50 text-slate-600 ring-1 ring-slate-200',
    slate: 'bg-slate-800 text-white',
    blue: 'bg-brand-50 text-brand-700 ring-1 ring-brand-600/20',
  }
  return <span className={`rounded-full px-2 py-0.5 ${styles[tone]}`}>{children}</span>
}

/** Small to-scale outline of the tile's proportions. */
function TilePreview({ tile }: { tile: Tile }) {
  const l = Number(tile.length_mm)
  const w = Number(tile.width_mm)
  const max = Math.max(l, w)
  const width = Math.max(8, (w / max) * 40)
  const height = Math.max(8, (l / max) * 40)
  return (
    <div className="flex h-11 w-11 shrink-0 items-center justify-center" aria-hidden="true">
      <div className="rounded-sm border-2 border-slate-400 bg-slate-100" style={{ width, height }} />
    </div>
  )
}
