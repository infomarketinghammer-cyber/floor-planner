import { useEffect, useRef, useState, type ReactNode } from 'react'
import { SERIES, compact } from '../lib/charts.ts'

/**
 * Small chart kit for the dashboards (PRD 4.20, 4.21). Thin marks, hairline grid, values at the
 * bar ends, a hover/focus tooltip on every mark, and a table view for every chart, so no value
 * depends on colour or hovering alone. Colours: lib/charts.ts.
 */
const GRID = '#e2e8f0'
const AXIS = '#cbd5e1'
const MUTED = '#64748b'

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

/** Round axis steps: 0 / 5 / 10, 0 / 250 / 500, 0 / 1K / 2K. */
function niceTicks(max: number, count = 4, integer = false): number[] {
  if (max <= 0) return [0, 1]
  const raw = integer ? Math.max(max / count, 1) : max / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks = []
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v)
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

// --- Card with a table view ---------------------------------------------------------------------

export interface TableView {
  columns: string[]
  rows: (string | number)[][]
}

export function ChartCard({
  title,
  subtitle,
  table,
  children,
  className = '',
}: {
  title: string
  subtitle?: ReactNode
  table?: TableView
  children: ReactNode
  className?: string
}) {
  const [showTable, setShowTable] = useState(false)
  return (
    <section className={`min-w-0 rounded-xl border border-slate-200 bg-white p-4 ${className}`}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        {table && (
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-pressed={showTable}
            className="shrink-0 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            {showTable ? 'Chart' : 'Table'}
          </button>
        )}
      </div>
      {showTable && table ? <DataTable table={table} /> : children}
    </section>
  )
}

function DataTable({ table }: { table: TableView }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-white text-xs text-slate-500">
          <tr>
            {table.columns.map((c, i) => (
              <th key={c} className={`py-1 pr-3 font-medium ${i ? 'text-right' : ''}`}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {table.rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <td key={i} className={`py-1 pr-3 ${i ? 'text-right tabular-nums' : ''}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- Stat tile ------------------------------------------------------------------------------------

export function StatTile({
  label,
  value,
  note,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: 'default' | 'warning' | 'good'
}) {
  const border = tone === 'warning' ? 'border-amber-300' : 'border-slate-200'
  return (
    <div className={`min-w-0 rounded-xl border bg-white p-4 ${border}`}>
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 truncate text-2xl font-semibold">{value}</p>
      {note && (
        <p className={`mt-0.5 text-xs ${tone === 'warning' ? 'text-amber-800' : tone === 'good' ? 'text-green-800' : 'text-slate-500'}`}>
          {tone === 'warning' && <span aria-hidden="true">⚠ </span>}
          {note}
        </p>
      )}
    </div>
  )
}

// --- Horizontal bars ------------------------------------------------------------------------------

export interface BarRow {
  key: string
  label: string
  value: number
  display: string // value as shown at the bar end
  tooltip?: string
  highlight?: boolean // drawn in the second colour, with the reason in the tooltip and table
}

/** One bar per row, values at the ends. A reference line (e.g. the 20% waste threshold) is a
 * solid hairline with its own label. */
export function BarList({
  rows,
  reference,
  label,
}: {
  rows: BarRow[]
  reference?: { value: number; label: string }
  label: string
}) {
  const max = Math.max(...rows.map((r) => r.value), reference?.value ?? 0) || 1
  const pct = (v: number) => `${(Math.max(v, 0) / max) * 100}%`
  return (
    <div role="list" aria-label={label} className="relative space-y-1.5">
      {reference && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-[calc(min(40%,10rem)+0.5rem)] right-16">
          <div className="absolute inset-y-0 w-px" style={{ left: pct(reference.value), background: MUTED }} />
        </div>
      )}
      {rows.map((r) => (
        <div
          key={r.key}
          role="listitem"
          tabIndex={0}
          className="group relative flex items-center gap-2 rounded text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <span className="w-[min(40%,10rem)] shrink-0 truncate text-slate-700" title={r.label}>
            {r.label}
          </span>
          <span className="relative flex h-5 flex-1 items-center">
            <span
              className="block h-3 rounded-r"
              style={{ width: pct(r.value), minWidth: r.value > 0 ? 2 : 0, background: r.highlight ? SERIES[1] : SERIES[0] }}
            />
          </span>
          <span className="w-14 shrink-0 text-right tabular-nums text-slate-700">{r.display}</span>
          <Tip text={r.tooltip ?? `${r.label}: ${r.display}`} />
        </div>
      ))}
      {reference && <p className="pt-1 text-right text-xs text-slate-500">│ {reference.label}</p>}
    </div>
  )
}

function Tip({ text }: { text: string }) {
  return (
    <span
      role="tooltip"
      className="pointer-events-none absolute -top-8 left-1/3 z-10 hidden whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-xs text-white shadow group-hover:block group-focus-visible:block"
    >
      {text}
    </span>
  )
}

// --- Columns (one or two stacked series) ----------------------------------------------------------

export interface ColumnPoint {
  key: string
  label: string // x-axis label
  values: number[] // one per series, stacked
  tooltip: string
}

export function Columns({
  points,
  series,
  format = compact,
  height = 160,
  label,
}: {
  points: ColumnPoint[]
  series: string[] // series names, for the legend (shown for two or more)
  format?: (n: number) => string
  height?: number
  label: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const left = 40
  const bottom = 22
  const plotW = Math.max(width - left - 4, 0)
  const plotH = height
  const totals = points.map((p) => p.values.reduce((a, b) => a + b, 0))
  // Counts (projects, uploads) get whole-number ticks.
  const ticks = niceTicks(Math.max(...totals, 0), 4, totals.every(Number.isInteger))
  const top = ticks[ticks.length - 1] || 1
  const band = points.length ? plotW / points.length : 0
  const barW = Math.min(24, Math.max(band - 6, 2))
  const y = (v: number) => plotH - (v / top) * plotH
  const every = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor(plotW / 48))))

  return (
    <div ref={ref} className="relative">
      {series.length > 1 && <Legend names={series} />}
      {width > 0 && (
        <svg width={width} height={plotH + bottom + 8} role="img" aria-label={label} className="overflow-visible">
          <g transform="translate(0,4)">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={left} x2={left + plotW} y1={y(t)} y2={y(t)} stroke={t === 0 ? AXIS : GRID} />
                <text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={MUTED} className="tabular-nums">
                  {format(t)}
                </text>
              </g>
            ))}
            {points.map((p, i) => {
              const x = left + band * i + (band - barW) / 2
              let acc = 0
              const segs = p.values.map((v, s) => {
                const y0 = y(acc)
                acc += v
                const y1 = y(acc)
                const h = Math.max(y0 - y1 - (s > 0 && v > 0 ? 2 : 0), 0) // 2px surface gap between segments
                const isTop = p.values.slice(s + 1).every((n) => n === 0)
                return v > 0 ? (
                  <path key={s} d={roundedTop(x, y1, barW, h, isTop ? 4 : 0)} fill={SERIES[s] ?? SERIES[0]} />
                ) : null
              })
              return (
                <g
                  key={p.key}
                  tabIndex={0}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  className="outline-none"
                >
                  <rect x={left + band * i} y={0} width={band} height={plotH} fill={hover === i ? '#f1f5f9' : 'transparent'} />
                  {segs}
                  {i % every === 0 && (
                    <text x={left + band * i + band / 2} y={plotH + 15} textAnchor="middle" fontSize={11} fill={MUTED}>
                      {p.label}
                    </text>
                  )}
                </g>
              )
            })}
          </g>
        </svg>
      )}
      {hover !== null && points[hover] && (
        <div
          role="tooltip"
          className="pointer-events-none absolute top-0 z-10 rounded-md bg-slate-900 px-2 py-1 text-xs whitespace-pre text-white shadow"
          style={{ left: Math.min(left + band * hover + band / 2, Math.max(width - 160, 0)) }}
        >
          {points[hover].tooltip}
        </div>
      )}
    </div>
  )
}

/** A bar with a 4px rounded data end and a square base. */
function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`
}

export function Legend({ names }: { names: string[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {names.map((n, i) => (
        <li key={n} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-2.5 rounded-sm" style={{ background: SERIES[i] }} />
          {n}
        </li>
      ))}
    </ul>
  )
}

// --- Line over time -------------------------------------------------------------------------------

export interface LinePoint {
  key: string
  at: number // ms since epoch
  value: number | null // null: a gap (e.g. the estimate couldn't be calculated)
  tooltip: string
}

export function LineChart({
  points,
  reference,
  format = compact,
  height = 160,
  label,
}: {
  points: LinePoint[]
  reference?: { value: number; label: string }
  format?: (n: number) => string
  height?: number
  label: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const left = 48
  const right = 12
  const bottom = 22
  const plotW = Math.max(width - left - right, 0)
  const values = points.map((p) => p.value).filter((v): v is number => v !== null)
  const ticks = niceTicks(Math.max(...values, reference?.value ?? 0, 0))
  const top = ticks[ticks.length - 1] || 1
  const t0 = points[0]?.at ?? 0
  const t1 = points[points.length - 1]?.at ?? 1
  // Evenly spaced by change when the times are bunched together; real time otherwise.
  const byIndex = t1 - t0 < 60_000 || points.length < 2
  const x = (p: LinePoint, i: number) =>
    left + (byIndex ? (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2) : ((p.at - t0) / (t1 - t0)) * plotW)
  const y = (v: number) => height - (v / top) * height

  // Segments split at gaps.
  const paths: string[] = []
  let d = ''
  points.forEach((p, i) => {
    if (p.value === null) {
      if (d) paths.push(d)
      d = ''
      return
    }
    d += `${d ? 'L' : 'M'}${x(p, i)},${y(p.value)}`
  })
  if (d) paths.push(d)
  const lastIndex = points.map((p) => p.value !== null).lastIndexOf(true)
  const last = lastIndex >= 0 ? points[lastIndex] : null

  function onMove(e: React.MouseEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - box.left + left
    let best = 0
    points.forEach((p, i) => {
      if (Math.abs(x(p, i) - mx) < Math.abs(x(points[best], best) - mx)) best = i
    })
    setHover(best)
  }

  const fmtDate = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg
          width={width}
          height={height + bottom + 8}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight') setHover((h) => Math.min((h ?? -1) + 1, points.length - 1))
            if (e.key === 'ArrowLeft') setHover((h) => Math.max((h ?? points.length) - 1, 0))
          }}
          onBlur={() => setHover(null)}
          className="overflow-visible outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <g transform="translate(0,4)">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={left} x2={left + plotW} y1={y(t)} y2={y(t)} stroke={t === 0 ? AXIS : GRID} />
                <text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={MUTED} className="tabular-nums">
                  {format(t)}
                </text>
              </g>
            ))}
            {reference && (
              <g>
                <line x1={left} x2={left + plotW} y1={y(reference.value)} y2={y(reference.value)} stroke={MUTED} />
                <text x={left + 4} y={y(reference.value) - 4} fontSize={11} fill={MUTED}>
                  {reference.label}
                </text>
              </g>
            )}
            {paths.map((p) => (
              <path key={p} d={p} fill="none" stroke={SERIES[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {points.length > 0 && (
              <>
                <text x={left} y={height + 15} fontSize={11} fill={MUTED}>
                  {fmtDate(points[0].at)}
                </text>
                {points.length > 1 && (
                  <text x={left + plotW} y={height + 15} textAnchor="end" fontSize={11} fill={MUTED}>
                    {fmtDate(points[points.length - 1].at)}
                  </text>
                )}
              </>
            )}
            {last && last.value !== null && (
              <circle cx={x(last, lastIndex)} cy={y(last.value)} r={4} fill={SERIES[0]} stroke="#fff" strokeWidth={2} />
            )}
            {hover !== null && points[hover] && (
              <g pointerEvents="none">
                <line x1={x(points[hover], hover)} x2={x(points[hover], hover)} y1={0} y2={height} stroke={AXIS} />
                {points[hover].value !== null && (
                  <circle cx={x(points[hover], hover)} cy={y(points[hover].value!)} r={5} fill={SERIES[0]} stroke="#fff" strokeWidth={2} />
                )}
              </g>
            )}
            <rect
              x={left}
              y={0}
              width={plotW}
              height={height}
              fill="transparent"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            />
          </g>
        </svg>
      )}
      {hover !== null && points[hover] && (
        <div
          role="tooltip"
          className="pointer-events-none absolute top-0 z-10 max-w-60 rounded-md bg-slate-900 px-2 py-1 text-xs whitespace-pre-line text-white shadow"
          style={{ left: Math.min(Math.max(x(points[hover], hover) - 60, 0), Math.max(width - 240, 0)) }}
        >
          {points[hover].tooltip}
        </div>
      )}
    </div>
  )
}
