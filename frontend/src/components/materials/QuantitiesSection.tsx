import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext.tsx'
import type { Estimate } from '../../api/types.ts'
import { BudgetAlert, CostSection } from '../cost/CostSection.tsx'
import { FeedbackPanel } from '../feedback/FeedbackPanel.tsx'
import { TileAdvicePanel } from '../layout/TileAdvicePanel.tsx'
import { TileLayoutView } from '../layout/TileLayoutView.tsx'
import { ResultsOverlay } from '../results/ResultsOverlay.tsx'
import { ResultsTable } from '../results/ResultsTable.tsx'
import { tileColors } from '../results/tileColors.ts'
import { formatArea, plural, useAreaUnit } from '../../lib/format.ts'
import { formatMoney, type MoneyFormat } from '../../lib/money.ts'
import type { RoomsReview } from '../rooms/useRoomsReview.ts'
import { ExtrasResults } from './ExtrasResults.tsx'
import { WastePanel } from './WastePanel.tsx'

const MM2_PER_SQFT = 92_903.04

/**
 * Tile quantities (PRD 4.7). The estimate comes back with every room or material change, so this
 * always shows the current numbers. The full results table and waste breakdown are PRD 4.8/4.9.
 */
export function QuantitiesSection({ projectId, review }: { projectId: string; review: RoomsReview }) {
  const [areaUnit] = useAreaUnit()
  const estimate = review.state?.estimate
  if (!review.state || review.state.rooms.length === 0 || !estimate) return null
  const area = (mm2: string | number) =>
    formatArea(areaUnit === 'sqm' ? Number(mm2) / 1_000_000 : Number(mm2) / MM2_PER_SQFT, areaUnit)

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Quantities</h2>
        <p className="text-sm text-slate-500">Updated automatically whenever a room or tile setting changes.</p>
      </div>
      {estimate.ready ? (
        <Ready projectId={projectId} estimate={estimate} review={review} area={area} />
      ) : (
        <Blocked blockers={estimate.blockers} />
      )}
    </section>
  )
}

function Blocked({ blockers }: { blockers: string[] }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5">
      <p className="font-medium">Quantities appear once the project is ready:</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
        {blockers.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
    </div>
  )
}

function Ready({
  projectId,
  estimate,
  review,
  area,
}: {
  projectId: string
  estimate: Estimate
  review: RoomsReview
  area: (mm2: string | number) => string
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { isGuest } = useAuth()
  const { rooms, cost, cost_settings: costSettings } = review.state!
  const money: MoneyFormat = costSettings
  const showCost = cost !== null && (cost.has_prices || cost.lines.length > 0)
  const colors = tileColors(estimate)
  const t = estimate.totals!
  const wastePct = Number(t.usable_area_mm2) ? (Number(t.extra_area_mm2) / Number(t.usable_area_mm2)) * 100 : 0
  return (
    <div className="space-y-4">
      <BudgetAlert cost={cost} money={money} />
      <dl className={`grid gap-3 sm:grid-cols-2 ${showCost ? 'lg:grid-cols-3 xl:grid-cols-5' : 'lg:grid-cols-4'}`}>
        <Stat label="Area to tile" value={area(t.usable_area_mm2)} note={plural(t.rooms, 'room')} />
        <Stat label="Boxes to buy" value={String(t.boxes)} note={plural(estimate.tiles.length, 'tile type')} />
        <Stat label="Tile area bought" value={area(t.bought_area_mm2)} />
        <Stat
          label="Extra over room area"
          value={area(t.extra_area_mm2)}
          note={`${wastePct.toFixed(1)}%: cuts, breakage buffer and full boxes`}
        />
        {showCost && (
          <Stat
            label="Estimated cost"
            value={formatMoney(cost.total, money)}
            note={cost.tax ? `including ${cost.tax.label}` : undefined}
          />
        )}
      </dl>

      <TileAdvicePanel projectId={projectId} review={review} estimate={estimate} />

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <h3 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold">By tile</h3>
        <ul className="divide-y divide-slate-100">
          {estimate.tiles.map((tt) => (
            <li key={tt.tile.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{tt.tile.size_label}</span>{' '}
                <span className="text-slate-500">{tt.tile.name}</span>
                <span className="block text-xs text-slate-500">
                  {plural(tt.rooms, 'room')} · {area(tt.usable_area_mm2)}
                  {tt.linear_mm === null && ` · ${tt.tiles_required} ${tt.tile.kind === 'plank' ? 'planks' : 'tiles'} needed`}
                </span>
              </span>
              <span className="text-right">
                {tt.linear_mm !== null ? (
                  <>
                    <span className="block text-base font-semibold tabular-nums">
                      {Number((Number(tt.linear_mm) / 1000).toFixed(2))} m of roll
                    </span>
                    <span className="text-xs text-slate-500">{Number(tt.tile.width_mm) / 1000} m wide</span>
                  </>
                ) : (
                  <>
                    <span className="block text-base font-semibold tabular-nums">{tt.boxes} {tt.boxes === 1 ? 'box' : 'boxes'}</span>
                    <span className="text-xs text-slate-500">
                      {tt.tiles_bought} {tt.tile.kind === 'plank' ? 'planks' : 'tiles'}
                    </span>
                  </>
                )}
                {tt.boxes_if_pooled < tt.boxes && (
                  <span className="block text-xs text-green-700">
                    {tt.boxes_if_pooled} if leftovers are shared between rooms
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <ResultsTable
        estimate={estimate}
        rooms={rooms}
        area={area}
        colors={colors}
        cost={cost}
        money={money}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
      {!isGuest && <FeedbackPanel projectId={projectId} estimate={estimate} selectedRoomId={selectedId} />}
      <TileLayoutView
        projectId={projectId}
        estimate={estimate}
        roomId={selectedId}
        version={review.state!.version}
        onSelect={setSelectedId}
      />
      <ResultsOverlay
        projectId={projectId}
        estimate={estimate}
        rooms={rooms}
        colors={colors}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
      <ExtrasResults estimate={estimate} area={area} />
      <WastePanel estimate={estimate} area={area} />
      <CostSection projectId={projectId} review={review} cost={cost} settings={costSettings} />
      <p className="text-xs text-slate-500">Estimate only: verify quantities before ordering.</p>
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
