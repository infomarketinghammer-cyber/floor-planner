import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api/client.ts'
import type { SharedProject } from '../api/types.ts'
import { formatMoney } from '../lib/money.ts'

/** A project's results through a read-only link (PRD 4.18). No login needed. */
export function SharedPage() {
  const { token = '' } = useParams()
  const [data, setData] = useState<SharedProject | null>(null)
  const [error, setError] = useState('')
  const [metric, setMetric] = useState(false)

  useEffect(() => {
    api.collab
      .shared(token)
      .then(setData)
      .catch((err: Error) => setError(err.message))
  }, [token])

  const area = (sqft: string, sqm: string) => (metric ? `${Number(sqm).toFixed(2)} m²` : `${Number(sqft).toFixed(2)} sq ft`)

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div aria-hidden="true" className="h-1 bg-brand-gradient" />
      <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm text-slate-500">{data?.company ? `Shared by ${data.company}` : 'Shared estimate'}</p>
            <h1 className="text-2xl font-semibold">{data?.project_name ?? (error ? 'Link not available' : 'Loading…')}</h1>
            {data?.updated_at && <p className="text-xs text-slate-500">Updated {new Date(data.updated_at).toLocaleString()}</p>}
          </div>
          <div role="group" aria-label="Units" className="flex rounded-md border border-slate-300 bg-white p-0.5 text-xs">
            {(
              [
                [false, 'sq ft'],
                [true, 'm²'],
              ] as const
            ).map(([m, label]) => (
              <button
                key={label}
                type="button"
                aria-pressed={metric === m}
                onClick={() => setMetric(m)}
                className={`rounded px-2 py-1 ${metric === m ? 'bg-brand-600 text-white' : 'text-slate-600'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="rounded-md bg-amber-50 px-3 py-2 text-amber-800">{error}</p>}
        {data && !data.ready && <p className="rounded-md bg-slate-100 px-3 py-2 text-slate-600">The estimate isn't finished yet.</p>}

        {data?.ready && data.totals && (
          <>
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800">{data.notice}</p>
            <dl className="grid gap-3 sm:grid-cols-3">
              <Stat label="Area to tile" value={area(data.totals.area_sqft, data.totals.area_sqm)} note={`${data.totals.rooms} rooms`} />
              <Stat label="Boxes" value={String(data.totals.boxes)} note={`${data.totals.extra_pct}% extra for cuts and breakage`} />
              {data.cost ? (
                <Stat label="Estimated cost" value={formatMoney(data.cost.total, data.cost)} note={data.cost.tax ? `including ${data.cost.tax.label}` : undefined} />
              ) : (
                <Stat label="Tile types" value={String(new Set(data.rooms?.map((r) => r.tile)).size)} />
              )}
            </dl>

            <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="w-full min-w-[560px] text-left text-sm">
                <caption className="border-b border-slate-100 px-4 py-3 text-left font-semibold">Rooms</caption>
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">Room</th>
                    <th className="px-4 py-2 font-medium">Size</th>
                    <th className="px-4 py-2 text-right font-medium">Area</th>
                    <th className="px-4 py-2 font-medium">Tile</th>
                    <th className="px-4 py-2 text-right font-medium">Boxes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.rooms?.map((r) => (
                    <tr key={r.name}>
                      <td className="px-4 py-2 font-medium">{r.name}</td>
                      <td className="px-4 py-2">{r.size}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{area(r.area_sqft, r.area_sqm)}</td>
                      <td className="px-4 py-2">{r.tile}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{r.roll_m ? `${r.roll_m} m` : r.boxes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white">
              <h2 className="border-b border-slate-100 px-4 py-3 font-semibold">Shopping list</h2>
              <ul className="divide-y divide-slate-100">
                {data.shopping?.map((s, i) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
                    <span>
                      <span className="font-medium">{s.size}</span> <span className="text-slate-500">{s.name}</span>
                    </span>
                    <span className="text-right">
                      <span className="font-semibold">{s.quantity}</span>
                      <span className="block text-xs text-slate-500">{s.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            {data.cost && (
              <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
                <h2 className="mb-2 font-semibold">Cost estimate</h2>
                <dl className="space-y-1">
                  {data.cost.materials && <Row label="Tiles" value={formatMoney(data.cost.materials, data.cost)} />}
                  {[...data.cost.extras, ...data.cost.lines].map((l) => (
                    <Row key={l.label} label={l.label} value={formatMoney(l.amount, data.cost!)} />
                  ))}
                  {data.cost.tax && <Row label={`${data.cost.tax.label} (${Number(data.cost.tax.pct)}%)`} value={formatMoney(data.cost.tax.amount, data.cost)} />}
                  <Row label="Total" value={formatMoney(data.cost.total, data.cost)} strong />
                </dl>
              </section>
            )}

            <details className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
              <summary className="cursor-pointer font-semibold">How the numbers were worked out</summary>
              <dl className="mt-2 space-y-1.5">
                {data.assumptions?.map((a) => (
                  <div key={a.title}>
                    <dt className="font-medium">{a.title}</dt>
                    <dd className="text-slate-600">{a.text}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        )}
        <p className="text-xs text-slate-500">
          Made with{' '}
          <Link to="/" className="font-medium text-brand-700 hover:underline">
            Floor Planner
          </Link>
        </p>
      </div>
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {note && <dd className="text-xs text-slate-500">{note}</dd>}
    </div>
  )
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${strong ? 'border-t border-slate-200 pt-1 font-semibold' : ''}`}>
      <dt>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  )
}
