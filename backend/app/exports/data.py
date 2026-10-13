"""Everything an export needs, gathered once from the project document.

Exports use exactly the numbers the app shows: the same estimate (PRD 4.7), assumptions
(PRD 4.8) and costs (PRD 4.10), recalculated from the stored rooms at export time.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.exports.formatting import AreaUnit, format_length, format_money
from app.schemas.cost import CostOut, CostSettings
from app.schemas.estimate import EstimateOut, RoomEstimateOut, TileTotalOut
from app.schemas.project import Room
from app.services.cost import build_cost, cost_settings
from app.services.estimate import build_estimate
from app.services.materials import project_default
from app.services.review import review_state

NOTICE = "Estimate only: verify quantities before ordering."


class NotReady(Exception):
    """The quantities can't be calculated yet; carries the reasons to show the user."""

    def __init__(self, blockers: list[str]):
        super().__init__("; ".join(blockers))
        self.blockers = blockers


@dataclass(frozen=True)
class ShoppingItem:
    ref: str  # "T1", "T2"...: links rooms to tiles in the PDF and spreadsheet
    tile: TileTotalOut

    @property
    def label(self) -> str:
        return f"{self.tile.tile.size_label} · {self.tile.tile.name}"


@dataclass(frozen=True)
class ExportData:
    project_name: str
    created_at: datetime
    area_unit: AreaUnit
    estimate: EstimateOut
    rooms: dict[str, Room]  # stored rooms by id, for sizes as entered
    shopping: list[ShoppingItem]
    cost: CostOut | None
    settings: CostSettings

    def ref(self, room: RoomEstimateOut) -> str:
        return next(s.ref for s in self.shopping if s.tile.tile.id == room.tile.id)

    def size(self, room: RoomEstimateOut) -> str:
        stored = self.rooms[room.room_id]
        if stored.length_mm is None or stored.width_mm is None:
            return "by area"
        return f"{format_length(stored.length_mm, stored.unit)} × {format_length(stored.width_mm, stored.unit)}"

    def money(self, value: Decimal | None, *, symbols: bool = True) -> str:
        return format_money(value, self.settings.currency, self.settings.locale, symbols=symbols)

    @property
    def priced(self) -> bool:
        return self.cost is not None and self.cost.has_prices

    @property
    def has_costs(self) -> bool:
        return self.cost is not None and (self.cost.has_prices or bool(self.cost.lines))


def export_data(doc: dict, area_unit: AreaUnit) -> ExportData:
    state = review_state(doc)
    default = project_default(doc)
    estimate = build_estimate(state, default)
    if not estimate.ready:
        raise NotReady(estimate.blockers)
    settings = cost_settings(doc)
    return ExportData(
        project_name=doc.get("name") or "Project",
        created_at=datetime.now(UTC),
        area_unit=area_unit,
        estimate=estimate,
        rooms={r.id: r for r in state.rooms},
        shopping=[ShoppingItem(f"T{i}", t) for i, t in enumerate(estimate.tiles, start=1)],
        cost=build_cost(state, default, estimate, settings),
        settings=settings,
    )
