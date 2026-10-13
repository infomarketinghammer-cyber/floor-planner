import { useState } from 'react'
import { api } from '../../api/client.ts'
import type { Cost, CostSettings } from '../../api/types.ts'
import { formatMoney, lineDetail, type MoneyFormat } from '../../lib/money.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { CostSettingsForm } from './CostSettingsForm.tsx'

/** Shown above the quantities as soon as the project is close to, or over, its budget. */
export function BudgetAlert({ cost, money }: { cost: Cost | null; money: MoneyFormat }) {
  const b = cost?.budget
  if (!b || b.status === 'under') return null
  const over = b.status === 'over'
  return (
    <p
      role={over ? 'alert' : 'status'}
      className={`rounded-md px-3 py-2 text-sm ${over ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-800'}`}
    >
      {over
        ? `Over budget by ${formatMoney(-Number(b.remaining), money)}. The total is ${formatMoney(cost.total, money)} against a budget of ${formatMoney(b.target, money)}.`
        : `Close to budget: ${Number(b.used_pct)}% used, ${formatMoney(b.remaining, money)} left of ${formatMoney(b.target, money)}.`}
    </p>
  )
}

/**
 * Cost estimate (PRD 4.10): tiles, delivery/labour lines, tax and the project total, with the
 * budget target. Prices come from the materials; everything here is added up by the server.
 */
export function CostSection({
  projectId,
  review,
  cost,
  settings,
}: {
  projectId: string
  review: RoomsReview
  cost: Cost | null
  settings: CostSettings
}) {
  const [editing, setEditing] = useState(false)
  if (!cost) return null
  const money: MoneyFormat = settings
  const m = (v: string | null) => formatMoney(v, money)
  const nothing = !cost.has_prices && cost.lines.length === 0

  async function save(next: CostSettings): Promise<string | null> {
    try {
      // Not a room change, so it isn't an undo step: show the new state without touching history.
      review.replaceState(await api.cost.setSettings(projectId, next))
      setEditing(false)
      return null
    } catch (err) {
      return (err as Error).message
    }
  }

  return (
    <section className="space-y-3" aria-labelledby="cost-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="cost-heading" className="font-semibold">
          Cost estimate
        </h3>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Currency, tax, extras and budget
          </button>
        )}
      </div>

      {editing && (
        <CostSettingsForm settings={settings} busy={review.busy} onSave={save} onCancel={() => setEditing(false)} />
      )}

      {!cost.has_prices && (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
          No tile prices yet. Add a price in the Materials section to see what the tiles cost
          {cost.lines.length === 0 ? ', or add delivery and labour costs above.' : '.'}
        </p>
      )}
      {cost.warnings.map((w) => (
        <p key={w} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {w}
        </p>
      ))}

      {!nothing && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[420px] text-left text-sm">
            <caption className="sr-only">Cost breakdown</caption>
            <tbody className="divide-y divide-slate-100">
              {cost.materials !== null && (
                <CostRow
                  label="Tiles"
                  note={`${cost.priced_rooms} ${cost.priced_rooms === 1 ? 'room' : 'rooms'} priced · boxes × price per box`}
                  amount={m(cost.materials)}
                />
              )}
              {cost.lines.map((line) => (
                <CostRow
                  key={line.id}
                  label={line.label}
                  note={lineDetail(line, money)}
                  amount={m(line.amount)}
                />
              ))}
              {cost.tax && (
                <CostRow
                  label={`${cost.tax.label} (${Number(cost.tax.pct)}%)`}
                  note={`on ${m(cost.tax.base)}`}
                  amount={m(cost.tax.amount)}
                />
              )}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold">
                <td className="px-4 py-3">Project total</td>
                <td className="px-4 py-3 text-right tabular-nums">{m(cost.total)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {cost.budget && <BudgetBar cost={cost} budget={cost.budget} money={money} />}
    </section>
  )
}

function CostRow({ label, note, amount }: { label: string; note?: string; amount: string }) {
  return (
    <tr>
      <td className="px-4 py-2.5">
        {label}
        {note && <span className="block text-xs text-slate-500">{note}</span>}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums">{amount}</td>
    </tr>
  )
}

function BudgetBar({ cost, budget, money }: { cost: Cost; budget: NonNullable<Cost['budget']>; money: MoneyFormat }) {
  const used = Number(budget.used_pct)
  const color = budget.status === 'over' ? 'bg-red-600' : budget.status === 'near' ? 'bg-amber-500' : 'bg-green-600'
  const text =
    budget.status === 'over'
      ? `${formatMoney(-Number(budget.remaining), money)} over budget`
      : `${formatMoney(budget.remaining, money)} left`
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">Budget {formatMoney(budget.target, money)}</span>
        <span className={budget.status === 'over' ? 'font-semibold text-red-700' : 'text-slate-600'}>{text}</span>
      </div>
      <div
        role="progressbar"
        aria-label="Share of the budget used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(used, 100)}
        aria-valuetext={`${used}% of the budget, total ${formatMoney(cost.total, money)}`}
        className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"
      >
        <div className={`h-full ${color}`} style={{ width: `${Math.min(used, 100)}%` }} />
      </div>
      <p className="mt-1 text-xs text-slate-500">{used}% of the budget used</p>
    </div>
  )
}