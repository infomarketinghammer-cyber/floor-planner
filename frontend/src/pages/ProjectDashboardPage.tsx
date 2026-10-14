import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api/client.ts'
import type { Comparison, Project, ProjectDashboard } from '../api/types.ts'
import { BarList, ChartCard, LineChart, StatTile, type BarRow } from '../components/charts.tsx'
import { ErrorText } from '../components/ui.tsx'
import { areaOf, formatArea, formatRelative, plural, useAreaUnit, type AreaUnit } from '../lib/format.ts'
import { formatMoney, type MoneyFormat } from '../lib/money.ts'

const HIGH_EXTRA = 20 // matches the server's insight threshold (PRD 4.20)

const pct = (v: string | null) => (v === null ? '–' : `${Number(v).toFixed(1)}%`)

const FILE_STATUS: Record<string, { text: string; tone: string }> = {
  done: { text: 'Read', tone: 'bg-green-50 text-green-800' },
  partial: { text: 'Partly read', tone: 'bg-amber-50 text-amber-800' },
  no_rooms: { text: 'No rooms found', tone: 'bg-amber-50 text-amber-800' },
  unavailable: { text: 'Not read', tone: 'bg-red-50 text-red-800' },
  not_read: { text: 'Not read yet', tone: 'bg-slate-100 text-slate-600' },
}

/**
 * A project at a glance (PRD 4.20, 4.21): headline figures, insights and alerts, where the
 * waste and money go, the budget over time, compared options, and how the plan was read.
 * Everyone on the project sees it; costs only for roles that see costs.
 */
export function ProjectDashboardPage() {
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [data, setData] = useState<ProjectDashboard | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [error, setError] = useState('')
  const [unit] = useAreaUnit()

  useEffect(() => {
    Promise.all([api.projects.get(projectId), api.dashboards.project(projectId)])
      .then(([p, d]) => {
        setProject(p)
        setData(d)
        if (d.ready && p.my_role !== 'homeowner') api.scenarios.compare(projectId).then(setComparison, () => {})
      })
      .catch((err: Error) => setError(err.message))
  }, [projectId])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!data || !project) return <p className="text-sm text-slate-500">Loading…</p>

  const money: MoneyFormat | null = data.money
  const fm = (v: string | number | null) => (money ? formatMoney(v, money) : '–')
  const warnings = data.insights.filter((i) => i.severity === 'warning').length

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm text-slate-500 hover:underline">
            ← {project.name}
          </Link>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
        </div>
        <Link
          to={`/projects/${projectId}`}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Open project
        </Link>
      </div>

      {!data.ready && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-medium">The estimate can't be calculated yet</p>
          <ul className="mt-1 list-disc pl-5">
            {data.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Summary (PRD 4.20) */}
      <section aria-label="Summary" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Area to tile" value={formatArea(areaOf(data.area_mm2, unit), unit)} note={plural(data.rooms_count, 'room')} />
        <StatTile
          label="Boxes to buy"
          value={data.boxes ?? '–'}
          note={data.tiles.length ? plural(data.tiles.length, 'tile type') : undefined}
        />
        <StatTile
          label="Extra over the area"
          value={pct(data.extra_pct)}
          note={data.cut_waste_pct !== null ? `${pct(data.cut_waste_pct)} of it is cuts` : undefined}
          tone={data.extra_pct !== null && Number(data.extra_pct) > HIGH_EXTRA ? 'warning' : 'default'}
        />
        {data.costs_visible ? (
          <StatTile
            label="Estimated cost"
            value={fm(data.cost_total)}
            note={
              data.budget
                ? `Budget ${fm(data.budget)}${data.budget_status === 'over' ? ': over' : data.budget_status === 'near' ? ': close' : ''}`
                : data.cost_total
                  ? undefined
                  : 'Add prices to see costs'
            }
            tone={data.budget_status === 'over' ? 'warning' : data.budget_status === 'under' ? 'good' : 'default'}
          />
        ) : (
          <StatTile label="Rooms confirmed" value={`${data.review.confirmed} of ${data.review.rooms - data.review.skipped}`} />
        )}
      </section>

      {/* Insights and alerts (PRD 4.20) */}
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">
          Insights and alerts{' '}
          {data.insights.length > 0 && (
            <span className="text-sm font-normal text-slate-500">
              · {warnings ? `${plural(warnings, 'warning')}, ` : ''}
              {plural(data.insights.length - warnings, 'tip')}
            </span>
          )}
        </h2>
        {data.insights.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">Nothing needs attention.</p>
        ) : (
          <ul className="mt-2 divide-y divide-slate-100">
            {data.insights.map((i) => (
              <li key={i.key} className="flex gap-3 py-2 text-sm">
                <span
                  aria-hidden="true"
                  className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    i.severity === 'warning' ? 'bg-amber-100 text-amber-800' : 'bg-brand-50 text-brand-700'
                  }`}
                >
                  {i.severity === 'warning' ? '!' : 'i'}
                </span>
                <div>
                  <p className="font-medium">
                    <span className="sr-only">{i.severity === 'warning' ? 'Warning: ' : 'Tip: '}</span>
                    {i.title}
                  </p>
                  <p className="text-slate-600">{i.text}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {data.ready && (
        <div className="grid gap-4 lg:grid-cols-2">
          <WasteByRoom data={data} />
          <ChartCard
            title="Boxes by tile type"
            subtitle="Each tile type is bought separately."
            table={{
              columns: ['Tile', 'Rooms', 'Boxes', 'If leftovers are shared'],
              rows: data.tiles.map((t) => [t.tile, t.rooms, t.linear_mm ? `${(Number(t.linear_mm) / 1000).toFixed(2)} m` : t.boxes, t.boxes_if_pooled]),
            }}
          >
            <BarList
              label="Boxes by tile type"
              rows={data.tiles.map((t) => ({
                key: t.tile_id,
                label: t.tile,
                value: t.linear_mm ? Number(t.linear_mm) / 1000 : t.boxes,
                display: t.linear_mm ? `${(Number(t.linear_mm) / 1000).toFixed(1)} m` : String(t.boxes),
                tooltip: `${t.tile}: ${t.linear_mm ? `${(Number(t.linear_mm) / 1000).toFixed(2)} m of roll` : `${t.boxes} boxes`} for ${plural(t.rooms, 'room')}`,
              }))}
            />
          </ChartCard>
          {data.costs_visible && data.tiles.some((t) => t.cost) && (
            <ChartCard
              title="Cost by tile type"
              table={{ columns: ['Tile', 'Cost'], rows: data.tiles.map((t) => [t.tile, fm(t.cost)]) }}
            >
              <BarList
                label="Cost by tile type"
                rows={data.tiles
                  .filter((t) => t.cost)
                  .map((t) => ({ key: t.tile_id, label: t.tile, value: Number(t.cost), display: compactMoney(t.cost, money) , tooltip: `${t.tile}: ${fm(t.cost)}` }))}
              />
            </ChartCard>
          )}
          {data.cost_parts.length > 0 && (
            <ChartCard
              title="Where the money goes"
              subtitle={`Total ${fm(data.cost_total)}`}
              table={{ columns: ['Part', 'Amount'], rows: data.cost_parts.map((p) => [p.label, fm(p.amount)]) }}
            >
              <BarList
                label="Cost by category"
                rows={data.cost_parts.map((p) => ({
                  key: p.label,
                  label: p.label,
                  value: Number(p.amount),
                  display: compactMoney(p.amount, money),
                  tooltip: `${p.label}: ${fm(p.amount)} (${((Number(p.amount) / Number(data.cost_total)) * 100).toFixed(0)}%)`,
                }))}
              />
            </ChartCard>
          )}
        </div>
      )}

      {data.ready && <RoomTable data={data} unit={unit} fm={fm} />}

      <Trend data={data} fm={fm} />

      {comparison && comparison.results.length > 1 && <OptionsChart comparison={comparison} fm={fm} costs={data.costs_visible} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Extraction data={data} />
        <Timeline data={data} />
      </div>
    </div>
  )
}

function compactMoney(v: string | null, money: MoneyFormat | null): string {
  if (v === null || !money) return '–'
  try {
    return new Intl.NumberFormat(money.locale, { style: 'currency', currency: money.currency, notation: 'compact', maximumFractionDigits: 1 }).format(Number(v))
  } catch {
    return formatMoney(v, money)
  }
}

function WasteByRoom({ data }: { data: ProjectDashboard }) {
  const rows: BarRow[] = [...data.rooms]
    .sort((a, b) => Number(b.extra_pct) - Number(a.extra_pct))
    .map((r) => {
      const high = Number(r.extra_pct) > HIGH_EXTRA
      return {
        key: r.room_id,
        label: r.name,
        value: Number(r.extra_pct),
        display: pct(r.extra_pct),
        highlight: high,
        tooltip: `${r.name}: ${pct(r.extra_pct)} extra (cuts ${pct(r.cut_waste_pct)}${r.rounding_tiles ? `, ${r.rounding_tiles} spare in last box` : ''})${high ? ' · over 20%' : ''}`,
      }
    })
  return (
    <ChartCard
      title="Extra by room"
      subtitle="What you buy over the floor area: cuts, spares and the last part-box. Orange: over 20%."
      table={{
        columns: ['Room', 'Extra', 'Cuts', 'Spare in last box', 'Over 20%'],
        rows: data.rooms.map((r) => [r.name, pct(r.extra_pct), pct(r.cut_waste_pct), r.rounding_tiles, Number(r.extra_pct) > HIGH_EXTRA ? 'Yes' : '']),
      }}
    >
      <BarList label="Extra by room" rows={rows} reference={{ value: HIGH_EXTRA, label: '20% high-waste line' }} />
    </ChartCard>
  )
}

function RoomTable({ data, unit, fm }: { data: ProjectDashboard; unit: AreaUnit; fm: (v: string | null) => string }) {
  const showCost = data.costs_visible && data.rooms.some((r) => r.cost)
  const showShare = showCost && data.budget
  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full min-w-[640px] text-left text-sm">
        <caption className="border-b border-slate-100 px-4 py-3 text-left font-semibold">Room breakdown</caption>
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">Room</th>
            <th className="px-4 py-2 font-medium">Tile</th>
            <th className="px-4 py-2 text-right font-medium">Area</th>
            <th className="px-4 py-2 text-right font-medium">Boxes</th>
            <th className="px-4 py-2 text-right font-medium">Extra</th>
            {showCost && <th className="px-4 py-2 text-right font-medium">Cost</th>}
            {showShare && <th className="px-4 py-2 text-right font-medium">Of budget</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.rooms.map((r) => (
            <tr key={r.room_id}>
              <td className="px-4 py-2">
                <span className="font-medium">{r.name}</span>
                {r.floor && <span className="block text-xs text-slate-500">{r.floor}</span>}
              </td>
              <td className="px-4 py-2 text-slate-600">{r.tile}</td>
              <td className="px-4 py-2 text-right tabular-nums">{formatArea(areaOf(r.area_mm2, unit), unit)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{r.linear_mm ? `${(Number(r.linear_mm) / 1000).toFixed(2)} m` : r.boxes}</td>
              <td className={`px-4 py-2 text-right tabular-nums ${Number(r.extra_pct) > HIGH_EXTRA ? 'font-medium text-amber-800' : ''}`}>
                {pct(r.extra_pct)}
              </td>
              {showCost && <td className="px-4 py-2 text-right tabular-nums">{fm(r.cost)}</td>}
              {showShare && <td className="px-4 py-2 text-right tabular-nums">{pct(r.budget_share_pct)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** Budget vs estimate over time (PRD 4.21), from the project's history. */
function Trend({ data, fm }: { data: ProjectDashboard; fm: (v: string | null) => string }) {
  const withCost = data.costs_visible && data.history.some((h) => h.cost !== null)
  const points = data.history.map((h, i) => {
    const value = withCost ? (h.cost === null ? null : Number(h.cost)) : h.boxes
    const when = new Date(h.at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
    return {
      key: `${h.at}-${i}`,
      at: new Date(h.at).getTime(),
      value: h.ready ? value : null,
      tooltip: `${when}\n${h.label}${h.user_name ? ` · ${h.user_name}` : ''}\n${
        !h.ready ? 'Not calculable at this point' : withCost ? `Estimate ${fm(h.cost)}` : `${h.boxes} boxes`
      }`,
    }
  })
  if (points.filter((p) => p.value !== null).length < 2) return null
  const budget = withCost ? data.history.map((h) => h.budget).filter(Boolean).pop() : null
  return (
    <ChartCard
      title={withCost ? 'Estimate against budget over time' : 'Boxes over time'}
      subtitle={`${plural(data.history.length, 'change')} recorded. Gaps: the estimate couldn't be calculated then.`}
      table={{
        columns: ['When', 'Change', 'By', withCost ? 'Estimate' : 'Boxes', ...(withCost ? ['Budget'] : [])],
        rows: [...data.history].reverse().map((h) => [
          new Date(h.at).toLocaleString(),
          h.label,
          h.user_name ?? '',
          h.ready ? (withCost ? fm(h.cost) : String(h.boxes)) : '–',
          ...(withCost ? [fm(h.budget)] : []),
        ]),
      }}
    >
      <LineChart
        label={withCost ? 'Estimated cost over time' : 'Boxes over time'}
        points={points}
        reference={budget ? { value: Number(budget), label: `Budget ${fm(budget)}` } : undefined}
      />
    </ChartCard>
  )
}

/** Saved options side by side (PRD 4.21 scenario comparison). One chart per measure. */
function OptionsChart({ comparison, fm, costs }: { comparison: Comparison; fm: (v: string | null) => string; costs: boolean }) {
  const ready = comparison.results.filter((r) => r.ready)
  const best = comparison.best?.scenario_id
  const name = (r: (typeof ready)[number]) => `${r.name}${r.id === best ? ' ★' : ''}`
  const priced = costs && ready.every((r) => r.cost !== null)
  return (
    <section className="space-y-2">
      <h2 className="font-semibold">Compared options</h2>
      {comparison.best && (
        <p className="text-sm text-slate-600">
          ★ Recommended: {comparison.results.find((r) => r.id === best)?.name}. {comparison.best.reasons.join(' ')}
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Boxes" table={{ columns: ['Option', 'Boxes'], rows: ready.map((r) => [name(r), r.boxes]) }}>
          <BarList label="Boxes per option" rows={ready.map((r) => ({ key: r.id, label: name(r), value: r.boxes, display: String(r.boxes) }))} />
        </ChartCard>
        <ChartCard title="Extra over the area" table={{ columns: ['Option', 'Extra'], rows: ready.map((r) => [name(r), pct(r.extra_pct)]) }}>
          <BarList
            label="Extra per option"
            rows={ready.map((r) => ({ key: r.id, label: name(r), value: Number(r.extra_pct), display: pct(r.extra_pct) }))}
          />
        </ChartCard>
        {priced && (
          <ChartCard title="Cost" table={{ columns: ['Option', 'Cost'], rows: ready.map((r) => [name(r), fm(r.cost)]) }}>
            <BarList
              label="Cost per option"
              rows={ready.map((r) => ({ key: r.id, label: name(r), value: Number(r.cost), display: fm(r.cost), tooltip: `${r.name}: ${fm(r.cost)}` }))}
            />
          </ChartCard>
        )}
      </div>
    </section>
  )
}

function Extraction({ data }: { data: ProjectDashboard }) {
  const r = data.review
  const active = r.rooms - r.skipped
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <h2 className="font-semibold">Plans and room review</h2>
      <div className="mt-2">
        <div className="flex justify-between text-slate-600">
          <span>Rooms confirmed</span>
          <span className="tabular-nums">
            {r.confirmed} of {active}
          </span>
        </div>
        <div
          className="mt-1 h-2 overflow-hidden rounded-full bg-brand-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={active}
          aria-valuenow={r.confirmed}
          aria-label="Rooms confirmed"
        >
          <div className="h-full rounded-full bg-brand-500" style={{ width: `${active ? (r.confirmed / active) * 100 : 0}%` }} />
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {r.from_plans} read from plans · {r.rooms - r.from_plans} added by hand
          {r.skipped ? ` · ${r.skipped} not tiled` : ''}
          {r.with_issues ? ` · ${plural(r.with_issues, 'room')} to check` : ''}
          {r.unit_pending ? ' · plan unit not confirmed' : ''}
        </p>
      </div>
      {data.blueprints.length > 0 ? (
        <ul className="mt-3 divide-y divide-slate-100">
          {data.blueprints.map((b) => {
            const s = FILE_STATUS[b.status] ?? FILE_STATUS.not_read
            return (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="min-w-0">
                  <span className="block truncate font-medium" title={b.filename}>
                    {b.filename}
                  </span>
                  <span className="text-xs text-slate-500">{b.message}</span>
                </span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${s.tone}`}>{s.text}</span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="mt-3 text-slate-500">No plans uploaded: rooms were entered by hand or imported.</p>
      )}
    </section>
  )
}

function Timeline({ data }: { data: ProjectDashboard }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <h2 className="font-semibold">Timeline</h2>
      {data.timeline.length === 0 ? (
        <p className="mt-1 text-slate-500">No changes recorded yet.</p>
      ) : (
        <ol className="mt-2 max-h-80 space-y-2 overflow-auto pr-1">
          {data.timeline.map((e, i) => (
            <li key={`${e.at}-${i}`} className="flex gap-3">
              <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-full bg-brand-500" />
              <span className="min-w-0">
                <span className="font-medium">{e.label}</span>
                {e.detail && <span className="text-slate-600">: {e.detail}</span>}
                <span className="block text-xs text-slate-500" title={new Date(e.at).toLocaleString()}>
                  {e.user_name ? `${e.user_name} · ` : ''}
                  {formatRelative(e.at)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
