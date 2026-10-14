import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client.ts'
import type { BusinessDashboard, PendingItem, QuoteStatus, TeamDashboard } from '../api/types.ts'
import { BarList, ChartCard, Columns, StatTile } from '../components/charts.tsx'
import { compact } from '../lib/charts.ts'
import { ErrorText } from '../components/ui.tsx'
import { areaOf, formatArea, formatRelative, plural, useAreaUnit } from '../lib/format.ts'
import { formatMoney } from '../lib/money.ts'

type Tab = 'business' | 'team'

const STATUS_NAMES: Record<QuoteStatus, string> = { draft: 'Draft', sent: 'Sent', approved: 'Approved', rejected: 'Rejected' }
const STATUS_TONE: Record<QuoteStatus, string> = {
  draft: 'bg-slate-100 text-slate-700',
  sent: 'bg-brand-50 text-brand-700',
  approved: 'bg-green-50 text-green-800',
  rejected: 'bg-red-50 text-red-800',
}
const ROLE_NAMES: Record<string, string> = { owner: 'Your own', contractor: 'As contractor', designer: 'As designer', homeowner: 'As client' }

/**
 * Across all projects (PRD 4.21): the business (quotes, margins, conversion, tiles used, work
 * by month) for those who run projects, and what's waiting for whom across the team.
 */
export function InsightsPage() {
  const [business, setBusiness] = useState<BusinessDashboard | null>(null)
  const [team, setTeam] = useState<TeamDashboard | null>(null)
  const [tab, setTab] = useState<Tab | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.dashboards.business(), api.dashboards.team()])
      .then(([b, t]) => {
        setBusiness(b)
        setTeam(t)
        setTab(b.projects > 0 ? 'business' : 'team')
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!business || !team || !tab) return <p className="text-sm text-slate-500">Loading…</p>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Insights</h1>
          <p className="text-sm text-slate-500">Across every project you can open.</p>
        </div>
        <div role="tablist" aria-label="Insights" className="flex rounded-lg border border-slate-200 bg-white p-1 text-sm">
          {(
            [
              ['business', 'Business'],
              ['team', `Team and approvals${team.pending.length ? ` (${team.pending.length})` : ''}`],
            ] as const
          )
            // Business figures are for people who run projects; clients only see the team view.
            .filter(([key]) => key === 'team' || business.projects > 0)
            .map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`rounded-md px-3 py-1.5 font-medium ${tab === key ? 'bg-brand-gradient text-white' : 'text-slate-600 hover:bg-slate-50'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'business' ? <Business data={business} /> : <Team data={team} />}
    </div>
  )
}

function Business({ data }: { data: BusinessDashboard }) {
  const [unit] = useAreaUnit()
  const money = data.money
  const fm = (v: string | number | null) => (money ? formatMoney(v, money) : '–')
  const fmCompact = (n: number) => {
    if (!money) return compact(n)
    try {
      return new Intl.NumberFormat(money.locale, { style: 'currency', currency: money.currency, notation: 'compact', maximumFractionDigits: 1 }).format(n)
    } catch {
      return compact(n)
    }
  }
  const monthName = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short' })
  const monthLong = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })

  if (data.projects === 0)
    return (
      <p className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
        No projects of your own yet. Business figures appear once you run projects and make quotes.
      </p>
    )

  const decided = (data.by_status.approved ?? 0) + (data.by_status.rejected ?? 0)
  return (
    <div className="space-y-6">
      <section aria-label="Quotes" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Quoted" value={fm(data.quoted_total)} note={plural(data.quotes, 'quote')} />
        <StatTile label="Won" value={fm(data.approved_total)} note={`${plural(data.by_status.approved ?? 0, 'approved quote')}`} />
        <StatTile
          label="Margin on won work"
          value={fm(data.margin_total)}
          note={data.margin_pct !== null ? `${Number(data.margin_pct).toFixed(1)}% of the price before tax` : 'No approved quotes yet'}
        />
        <StatTile
          label="Conversion"
          value={data.conversion_pct !== null ? `${Number(data.conversion_pct).toFixed(0)}%` : '–'}
          note={decided ? `approved, of ${plural(decided, 'decided quote')}` : 'Mark quotes approved or rejected to see this'}
        />
      </section>
      {data.other_currency_quotes > 0 && (
        <p className="text-xs text-slate-500">
          {plural(data.other_currency_quotes, 'quote')} in other currencies {data.other_currency_quotes === 1 ? 'is' : 'are'} listed below but not added to these totals.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard
          title="New projects by month"
          table={{ columns: ['Month', 'Projects'], rows: data.months.map((m) => [monthLong(m.month), m.projects]) }}
        >
          <Columns
            label="New projects by month"
            series={['Projects']}
            points={data.months.map((m) => ({ key: m.month, label: monthName(m.month), values: [m.projects], tooltip: `${monthLong(m.month)}\n${plural(m.projects, 'project')}` }))}
          />
        </ChartCard>
        <ChartCard
          title="Area by month"
          subtitle={unit === 'sqm' ? 'm² to tile' : 'sq ft to tile'}
          table={{ columns: ['Month', 'Area'], rows: data.months.map((m) => [monthLong(m.month), formatArea(areaOf(m.area_mm2, unit), unit)]) }}
        >
          <Columns
            label="Area by month"
            series={['Area']}
            points={data.months.map((m) => ({
              key: m.month,
              label: monthName(m.month),
              values: [areaOf(m.area_mm2, unit)],
              tooltip: `${monthLong(m.month)}\n${formatArea(areaOf(m.area_mm2, unit), unit)}`,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Quoted value by month"
          subtitle="Latest quote of each project, by the month the project started"
          table={{ columns: ['Month', 'Quoted'], rows: data.months.map((m) => [monthLong(m.month), fm(m.quoted)]) }}
        >
          <Columns
            label="Quoted value by month"
            series={['Quoted']}
            format={fmCompact}
            points={data.months.map((m) => ({ key: m.month, label: monthName(m.month), values: [Number(m.quoted)], tooltip: `${monthLong(m.month)}\n${fm(m.quoted)}` }))}
          />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Tiles you use most"
          subtitle="Typical extra: the middle value across the rooms that used it"
          table={{
            columns: ['Tile', 'Projects', 'Rooms', 'Boxes', 'Typical extra'],
            rows: data.tiles.map((t) => [t.tile, t.projects, t.rooms, t.boxes, `${Number(t.typical_extra_pct).toFixed(1)}%`]),
          }}
        >
          {data.tiles.length ? (
            <BarList
              label="Projects per tile"
              rows={data.tiles.map((t) => ({
                key: t.tile,
                label: t.tile,
                value: t.projects,
                display: String(t.projects),
                tooltip: `${t.tile}: ${plural(t.projects, 'project')}, ${plural(t.rooms, 'room')}, typically ${Number(t.typical_extra_pct).toFixed(1)}% extra`,
              }))}
            />
          ) : (
            <p className="text-sm text-slate-500">Appears once projects have tiles assigned.</p>
          )}
        </ChartCard>
        <ChartCard
          title="Typical extra by tile"
          subtitle="Bigger tiles usually need more for cuts"
          table={{ columns: ['Tile', 'Typical extra'], rows: data.tiles.map((t) => [t.tile, `${Number(t.typical_extra_pct).toFixed(1)}%`]) }}
        >
          {data.tiles.length ? (
            <BarList
              label="Typical extra by tile"
              rows={data.tiles.map((t) => ({
                key: t.tile,
                label: t.tile,
                value: Number(t.typical_extra_pct),
                display: `${Number(t.typical_extra_pct).toFixed(1)}%`,
              }))}
            />
          ) : (
            <p className="text-sm text-slate-500">Appears once projects have tiles assigned.</p>
          )}
        </ChartCard>
      </div>

      <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[680px] text-left text-sm">
          <caption className="border-b border-slate-100 px-4 py-3 text-left font-semibold">Client quotes</caption>
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Client</th>
              <th className="px-4 py-2 font-medium">Project</th>
              <th className="px-4 py-2 font-medium">Quote</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 text-right font-medium">Total</th>
              <th className="px-4 py-2 text-right font-medium">Margin</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.recent_quotes.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  No quotes yet. Make one from a project's Quotes section.
                </td>
              </tr>
            )}
            {data.recent_quotes.map((q) => {
              const qm = { currency: q.currency, locale: q.locale }
              return (
                <tr key={q.quote_id}>
                  <td className="px-4 py-2 font-medium">{q.client || '–'}</td>
                  <td className="px-4 py-2">
                    <Link to={`/projects/${q.project_id}`} className="hover:underline">
                      {q.project_name}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {q.number}
                    {q.version > 1 ? ` v${q.version}` : ''}
                    <span className="block text-xs text-slate-500">{formatRelative(q.sent_at ?? q.created_at)}</span>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[q.status]}`}>{STATUS_NAMES[q.status]}</span>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatMoney(q.total, qm)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatMoney(q.margin_amount, qm)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}

const PENDING_ICON: Record<PendingItem['kind'], string> = {
  approve: '✓',
  awaiting_client: '…',
  changes_requested: '!',
  comments: '💬',
  review_rooms: '◻',
}

export function PendingList({ items, limit }: { items: PendingItem[]; limit?: number }) {
  const shown = limit ? items.slice(0, limit) : items
  return (
    <ul className="divide-y divide-slate-100">
      {shown.map((p, i) => (
        <li key={`${p.kind}-${p.project_id}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
          <span aria-hidden="true" className="w-5 text-center text-slate-500">
            {PENDING_ICON[p.kind]}
          </span>
          <Link to={`/projects/${p.project_id}`} className="font-medium hover:underline">
            {p.project_name}
          </Link>
          <span className={p.kind === 'approve' || p.kind === 'changes_requested' ? 'text-amber-800' : 'text-slate-600'}>{p.text}</span>
          {p.at && <span className="ml-auto text-xs text-slate-500">{formatRelative(p.at)}</span>}
        </li>
      ))}
    </ul>
  )
}

function Team({ data }: { data: TeamDashboard }) {
  return (
    <div className="space-y-6">
      <section aria-label="Your projects by role" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(['owner', 'contractor', 'designer', 'homeowner'] as const)
          .filter((r) => data.roles[r])
          .map((r) => (
            <StatTile key={r} label={ROLE_NAMES[r]} value={data.roles[r]} note="projects" />
          ))}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Waiting for attention</h2>
        {data.pending.length ? (
          <PendingList items={data.pending} />
        ) : (
          <p className="mt-1 text-sm text-slate-500">Nothing is waiting: no approvals, open comments or rooms to review.</p>
        )}
      </section>

      {data.teams.map((t) => (
        <section key={t.id} className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[520px] text-left text-sm">
            <caption className="border-b border-slate-100 px-4 py-3 text-left">
              <span className="font-semibold">{t.name}</span>{' '}
              <span className="text-slate-500">
                · {plural(t.projects, 'shared project')} · you are {t.my_role}
              </span>
            </caption>
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">Member</th>
                <th className="px-4 py-2 font-medium">Role</th>
                <th className="px-4 py-2 text-right font-medium">Changes, last 30 days</th>
                <th className="px-4 py-2 text-right font-medium">Last change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {t.members.map((m) => (
                <tr key={m.user_name + m.role}>
                  <td className="px-4 py-2 font-medium">{m.user_name}</td>
                  <td className="px-4 py-2 capitalize text-slate-600">{m.role}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{m.changes_30d}</td>
                  <td className="px-4 py-2 text-right text-slate-500">{m.last_at ? formatRelative(m.last_at) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="font-semibold">Who changed what</h2>
        {data.activity.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">No changes yet.</p>
        ) : (
          <ul className="mt-2 max-h-96 divide-y divide-slate-100 overflow-auto">
            {data.activity.map((a, i) => (
              <li key={`${a.at}-${i}`} className="flex flex-wrap items-baseline gap-x-2 py-1.5 text-sm">
                <span className="font-medium">{a.user_name ?? 'Someone'}</span>
                <span className="text-slate-600">{a.label.charAt(0).toLowerCase() + a.label.slice(1)}</span>
                <span className="text-slate-500">in</span>
                <Link to={`/projects/${a.project_id}`} className="hover:underline">
                  {a.project_name}
                </Link>
                <span className="ml-auto text-xs text-slate-500" title={new Date(a.at).toLocaleString()}>
                  {formatRelative(a.at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
