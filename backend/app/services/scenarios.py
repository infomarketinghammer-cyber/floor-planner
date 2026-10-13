"""Scenario comparison and recommendation (PRD 4.17). Pure except `load_scenarios`.

Each option is the project's own rooms with a different default material (and optional room
changes), calculated by the same engine as the project, including walls, extras and costs.
"""

from collections.abc import Callable
from decimal import Decimal

from app.exports.formatting import format_money
from app.schemas.cost import CostSettings
from app.schemas.estimate import EstimateOut
from app.schemas.extras import ExtrasSettings
from app.schemas.material import ProductKind, ProjectMaterial
from app.schemas.project import Room
from app.schemas.scenario import (
    ComparisonOut,
    Recommendation,
    Scenario,
    ScenarioResultOut,
    ScenarioRoomOut,
    ScenarioTileOut,
    SuggestedOption,
)
from app.services.cost import build_cost
from app.services.estimate import build_estimate
from app.services.review import review_state
from app.services.tile_advice import advise

_ONE = Decimal("0.1")
CURRENT = "current"


def load_scenarios(doc: dict) -> list[Scenario]:
    return [Scenario.model_validate(s) for s in doc.get("scenarios", [])]


def apply_scenario(rooms: list[Room], scenario: Scenario) -> tuple[list[Room], ProjectMaterial]:
    """The rooms and default material with the scenario's choices in place."""
    changes = {c.room_id: c for c in scenario.rooms}
    out = []
    for room in rooms:
        material = room.material.model_copy()
        if scenario.every_room:
            material.tile = None
            material.layout = None
        change = changes.get(room.id)
        if change:
            if change.tile is not None:
                material.tile = change.tile
            if change.layout is not None:
                material.layout = change.layout
        out.append(room.model_copy(update={"material": material}))
    return out, scenario.default


def _result(
    sid: str,
    name: str,
    notes: str | None,
    every_room: bool,
    doc: dict,
    rooms: list[Room],
    default: ProjectMaterial,
    cost_settings: CostSettings,
    extras: ExtrasSettings,
) -> ScenarioResultOut:
    state = review_state(doc, rooms)
    estimate = build_estimate(state, default, extras)
    if not estimate.ready or estimate.totals is None:
        return ScenarioResultOut(
            id=sid, name=name, notes=notes, every_room=every_room, ready=False,
            blockers=estimate.blockers, tiles=[], boxes=0, tiles_bought=0,
            usable_area_mm2=Decimal(0), bought_area_mm2=Decimal(0), extra_area_mm2=Decimal(0),
            extra_pct=Decimal(0), cut_waste_pct=Decimal(0), cost=None, fully_priced=False,
            budget_remaining=None, rooms=[], badges=[],
        )  # fmt: skip
    cost = build_cost(state, default, estimate, cost_settings, extras)
    t = estimate.totals
    costs = {c.room_id: c.cost for c in cost.rooms} if cost else {}
    priced = cost is not None and cost.has_prices
    return ScenarioResultOut(
        id=sid,
        name=name,
        notes=notes,
        every_room=every_room,
        ready=True,
        blockers=[],
        tiles=[
            ScenarioTileOut(tile=x.tile, rooms=x.rooms, boxes=x.boxes, linear_mm=x.linear_mm)
            for x in estimate.tiles
        ],
        boxes=t.boxes,
        tiles_bought=sum(r.tiles_bought for r in estimate.rooms),
        usable_area_mm2=t.usable_area_mm2,
        bought_area_mm2=t.bought_area_mm2,
        extra_area_mm2=t.extra_area_mm2,
        extra_pct=(t.extra_area_mm2 / t.usable_area_mm2 * 100).quantize(_ONE),
        cut_waste_pct=t.cut_waste_pct.quantize(_ONE),
        cost=cost.total if priced else None,
        fully_priced=bool(priced and cost.unpriced_rooms == 0),
        budget_remaining=cost.budget.remaining if priced and cost.budget else None,
        rooms=[
            ScenarioRoomOut(
                room_id=r.room_id,
                name=r.name,
                tile=r.tile,
                layout=r.layout,
                boxes=r.boxes,
                extra_pct=r.extra_pct.quantize(_ONE),
                cost=costs.get(r.room_id),
            )
            for r in estimate.rooms
        ],
        badges=[],
    )


def _plain_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,f}"


def recommend(
    results: list[ScenarioResultOut],
    budget: Decimal | None,
    money: Callable[[Decimal], str] = _plain_money,
) -> Recommendation | None:
    """Pick the best option and say why (PRD 4.17).

    With complete prices: the cheapest option within budget (or the cheapest at all, if none
    fits); ties go to less waste. Without prices: the option with the least waste; ties go to
    fewer boxes. Also marks each result's badges.
    """
    ready = [r for r in results if r.ready]
    if len(ready) < 2:
        return None
    # Ties go to the current setup: no change needed.
    least_waste = min(ready, key=lambda r: (r.extra_area_mm2, r.boxes, r.id != CURRENT))
    fewest = min(ready, key=lambda r: (r.boxes, r.extra_area_mm2, r.id != CURRENT))
    least_waste.badges.append("lowest_waste")
    fewest.badges.append("fewest_boxes")
    priced = [r for r in ready if r.fully_priced and r.cost is not None]
    cheapest = (
        min(priced, key=lambda r: (r.cost, r.extra_area_mm2, r.id != CURRENT)) if priced else None
    )
    if cheapest is not None:
        cheapest.badges.append("lowest_cost")
    if budget is not None:
        for r in priced:
            r.badges.append("within_budget" if r.cost <= budget else "over_budget")

    reasons: list[str] = []
    by_waste = False  # the main reason is already "least waste"
    if len(priced) >= 2:
        fitting = [r for r in priced if budget is None or r.cost <= budget]
        pool = fitting or priced
        best = min(pool, key=lambda r: (r.cost, r.extra_area_mm2, r.id != CURRENT))
        others = [r for r in priced if r is not best]
        saving = min(o.cost for o in others) - best.cost if others else Decimal(0)
        if budget is not None and fitting:
            reasons.append(
                f"It's the cheapest option within your budget, {money(budget - best.cost)} under it."
                if len(fitting) > 1 or saving > 0
                else "It's the only option within your budget."
            )
        elif budget is not None:
            reasons.append(
                f"No option fits the budget; this one is closest, {money(best.cost - budget)} over."
            )
        elif saving > 0:
            reasons.append(f"It costs {money(saving)} less than the next option.")
        else:
            reasons.append("It costs the same as the cheapest alternative, with less waste.")
    else:
        best, by_waste = least_waste, True
        others = [r for r in ready if r is not best]
        next_best = min(others, key=lambda r: r.extra_area_mm2)
        if next_best.extra_area_mm2 == best.extra_area_mm2:
            reasons.append(
                f"No option wastes less ({best.extra_pct.normalize():f}% extra over the area to "
                f"tile); {next_best.name} wastes the same"
                + (", so there's no need to change." if best.id == CURRENT else ".")
            )
        else:
            reasons.append(
                f"It wastes the least: {best.extra_pct.normalize():f}% extra over the area to "
                f"tile, against {next_best.extra_pct.normalize():f}% for the next option."
            )
        if len(priced) < len(ready):
            reasons.append("Add prices to every option to compare costs too.")
    if best is least_waste and not by_waste:
        reasons.append(f"It also has the least waste ({best.extra_pct.normalize():f}% extra).")
    if best is fewest and best.boxes < max(r.boxes for r in ready):
        reasons.append(f"It needs the fewest boxes ({best.boxes}).")
    return Recommendation(scenario_id=best.id, reasons=reasons)


def compare(
    doc: dict,
    cost_settings: CostSettings,
    extras: ExtrasSettings,
    default: ProjectMaterial,
    library: list[dict],
) -> ComparisonOut:
    rooms = review_state(doc).rooms
    results = [_result(CURRENT, "Current", None, False, doc, rooms, default, cost_settings, extras)]
    for s in load_scenarios(doc):
        s_rooms, s_default = apply_scenario(rooms, s)
        results.append(
            _result(
                s.id, s.name, s.notes, s.every_room, doc, s_rooms, s_default, cost_settings, extras
            )
        )
    best = recommend(
        results,
        cost_settings.budget,
        lambda v: format_money(v, cost_settings.currency, cost_settings.locale),
    )
    return ComparisonOut(
        results=results, best=best, suggestions=_suggestions(doc, rooms, default, extras, library)
    )


def _suggestions(
    doc: dict,
    rooms: list[Room],
    default: ProjectMaterial,
    extras: ExtrasSettings,
    library: list[dict],
) -> list[SuggestedOption]:
    """Options worth adding: the lowest-waste tile for the project (PRD 4.17 "suggest
    alternatives based on lowest waste"). Skipped when already saved as a scenario."""
    estimate: EstimateOut = build_estimate(review_state(doc, rooms), default, extras)
    if not estimate.ready or default.tile is None or default.tile.kind != ProductKind.TILE:
        return []
    advice = advise(rooms, default, estimate, library)
    saved = {s.default.tile.id for s in load_scenarios(doc) if s.default.tile}
    out = []
    if advice.project and advice.project.best and advice.project.best.tile.id not in saved:
        best = advice.project.best
        out.append(
            SuggestedOption(
                key="lowest_waste",
                name=f"Lowest waste: {best.tile.size_label}",
                reason=(
                    f"Wastes {best.extra_pct.normalize():f}% instead of "
                    f"{advice.project.current.extra_pct.normalize():f}% in the rooms on the project tile."
                ),
                tile=best.tile,
            )
        )
    return out
