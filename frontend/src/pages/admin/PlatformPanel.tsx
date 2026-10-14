import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { PlatformDashboard } from '../../api/types.ts'
import { BarList, ChartCard, Columns, StatTile } from '../../components/charts.tsx'
import { ErrorText } from '../../components/ui.tsx'

const FIELD_NAMES = { name: 'Room name', length: 'Length', width: 'Width', unit: 'Unit' } as const
const READ_STATUS: Record<string, string> = {
  done: 'Read',
  partial: 'Partly read',
  no_rooms: 'No rooms found',
  unavailable: "Couldn't be read",
}
const pct = (v: string | null) => (v === null ? '–' : `${Number(v).toFixed(1)}%`)

/** Platform and accuracy (PRD 4.21): how well plans are read, what goes wrong, feedback and
 * usage over the last 12 weeks. Admins only. */
export function PlatformPanel() {
  const [data, setData] = useState<PlatformDashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.admin
      .platform()
      .then(setData)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!data) return <p className="text-sm text-slate-500">Loading platform figures…</p>

  const week = (w: string) => new Date(`${w}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  const usage = (
    [
      ['signups', 'Sign-ups'],
      ['projects', 'New projects'],
      ['uploads', 'Plans uploaded'],
      ['exports', 'Exports'],
    ] as const
  ).map(([key, title]) => ({ key, title, total: data.weeks.reduce((s, w) => s + w[key], 0) }))

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">Platform and accuracy</h2>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile label="Users" value={data.users} />
        <StatTile label="Active, last 30 days" value={data.active_users_30d} note="made a change to a project" />
        <StatTile label="Projects" value={data.projects} />
        <StatTile label="Plans uploaded" value={data.uploads} />
        <StatTile label="Exports" value={data.exports} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Reading accuracy by kind of file"
          subtitle="Rooms confirmed exactly as read, of those reviewed"
          table={{
            columns: ['Kind of file', 'Rooms read', 'Reviewed', 'Correct', 'Accuracy'],
            rows: data.by_source.map((s) => [s.source, s.read, s.reviewed, s.correct, pct(s.accuracy_pct)]),
          }}
        >
          {data.by_source.some((s) => s.accuracy_pct !== null) ? (
            <BarList
              label="Accuracy by kind of file"
              rows={data.by_source
                .filter((s) => s.accuracy_pct !== null)
                .map((s) => ({
                  key: s.source,
                  label: s.source,
                  value: Number(s.accuracy_pct),
                  display: pct(s.accuracy_pct),
                  tooltip: `${s.source}: ${s.correct} of ${s.reviewed} reviewed rooms correct`,
                }))}
            />
          ) : (
            <p className="text-sm text-slate-500">Appears once rooms read from plans have been reviewed.</p>
          )}
        </ChartCard>
        <ChartCard
          title="How often each field is corrected"
          subtitle={`Of ${data.fields[0]?.checked ?? 0} confirmed rooms read from plans`}
          table={{
            columns: ['Field', 'Corrected', 'Checked', 'Rate'],
            rows: data.fields.map((f) => [FIELD_NAMES[f.field], f.corrected, f.checked, pct(f.rate_pct)]),
          }}
        >
          {data.fields[0]?.checked ? (
            <BarList
              label="Correction rate by field"
              rows={data.fields.map((f) => ({
                key: f.field,
                label: FIELD_NAMES[f.field],
                value: Number(f.rate_pct ?? 0),
                display: pct(f.rate_pct),
                tooltip: `${FIELD_NAMES[f.field]}: corrected in ${f.corrected} of ${f.checked} rooms`,
              }))}
            />
          ) : (
            <p className="text-sm text-slate-500">Appears once rooms read from plans have been confirmed.</p>
          )}
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Answer feedback per week"
          subtitle="“Was this estimate right?” answers"
          table={{ columns: ['Week of', 'Right', 'Wrong'], rows: data.weeks.map((w) => [week(w.week), w.right, w.wrong]) }}
        >
          <Columns
            label="Feedback per week"
            series={['Right', 'Wrong']}
            points={data.weeks.map((w) => ({
              key: w.week,
              label: week(w.week),
              values: [w.right, w.wrong],
              tooltip: `Week of ${week(w.week)}\nRight: ${w.right}\nWrong: ${w.wrong}`,
            }))}
          />
        </ChartCard>
        <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
          <h3 className="font-semibold">What usually goes wrong</h3>
          <p className="text-xs text-slate-500">Review flags and confidence, and how often those rooms needed correcting</p>
          {data.patterns.length ? (
            <table className="mt-2 w-full text-left">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-1 font-medium">Pattern</th>
                  <th className="py-1 text-right font-medium">Rooms</th>
                  <th className="py-1 text-right font-medium">Then wrong</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.patterns.map((p) => (
                  <tr key={p.label}>
                    <td className="py-1">{p.label}</td>
                    <td className="py-1 text-right tabular-nums">{p.count}</td>
                    <td className="py-1 text-right tabular-nums">{pct(p.wrong_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="mt-2 text-slate-500">No flagged rooms reviewed yet.</p>
          )}
          {Object.keys(data.read_failures).length > 0 && (
            <>
              <h4 className="mt-4 font-medium">Plan files</h4>
              <ul className="mt-1 flex flex-wrap gap-2">
                {Object.entries(data.read_failures).map(([status, n]) => (
                  <li key={status} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700">
                    {READ_STATUS[status] ?? status}: <span className="tabular-nums font-medium">{n}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {usage.map((u) => (
          <ChartCard
            key={u.key}
            title={u.title}
            subtitle={`${u.total} in 12 weeks`}
            table={{ columns: ['Week of', u.title], rows: data.weeks.map((w) => [week(w.week), w[u.key]]) }}
          >
            <Columns
              label={`${u.title} per week`}
              series={[u.title]}
              height={100}
              points={data.weeks.map((w) => ({
                key: w.week,
                label: week(w.week),
                values: [w[u.key]],
                tooltip: `Week of ${week(w.week)}\n${u.title}: ${w[u.key]}`,
              }))}
            />
          </ChartCard>
        ))}
      </div>
    </section>
  )
}
