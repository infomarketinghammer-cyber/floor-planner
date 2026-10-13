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
from app.services.extras import extras_settings
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


def _boxes(n: int) -> str:
    return f"{n} {'box' if n == 1 else 'boxes'}"


def _metres(mm: Decimal) -> str:
    return f"{(mm / 1000).quantize(Decimal('0.01')).normalize():f} m"


@dataclass(frozen=True)
class ShopLine:
    """One thing to buy, in any section: floor, walls, skirting or sundries (PRD 4.11, 4.15)."""

    section: str  # "Floor", "Walls", "Skirting", "Sundries"
    ref: str  # T1 for floor products (matches the rooms table), W1, S1, X1 for the rest
    name: str
    size: str
    quantity: str  # "16 boxes", "3.15 m of roll", "3 bags"
    detail: str  # "64 tiles, 4 per box"


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
        if stored.parts:
            return f"{len(stored.parts)} rectangles"
        if stored.length_mm is None or stored.width_mm is None:
            return "by area"
        return f"{format_length(stored.length_mm, stored.unit)} × {format_length(stored.width_mm, stored.unit)}"

    def money(self, value: Decimal | None, *, symbols: bool = True) -> str:
        return format_money(value, self.settings.currency, self.settings.locale, symbols=symbols)

    @property
    def priced(self) -> bool:
        """Some room has a floor price: show the room cost columns."""
        return self.cost is not None and self.cost.priced_rooms > 0

    @property
    def shopping_lines(self) -> list[ShopLine]:
        out = []
        for item in self.shopping:
            t = item.tile
            if t.tile.kind == "roll":
                out.append(
                    ShopLine(
                        "Floor",
                        item.ref,
                        t.tile.name,
                        f"{_metres(t.tile.width_mm)} wide roll",
                        f"{_metres(t.linear_mm or Decimal(0))} of roll",
                        f"{t.rooms} room{'s' if t.rooms != 1 else ''}",
                    )
                )
            else:
                piece = "planks" if t.tile.kind == "plank" else "tiles"
                out.append(
                    ShopLine(
                        "Floor",
                        item.ref,
                        t.tile.name,
                        t.tile.size_label,
                        _boxes(t.boxes),
                        f"{t.tiles_bought} {piece}, {t.tile.tiles_per_box} per box",
                    )
                )
        x = self.estimate.extras
        if x is None:
            return out
        for i, w in enumerate(x.wall_tiles, start=1):
            out.append(
                ShopLine(
                    "Walls",
                    f"W{i}",
                    w.tile.name,
                    w.tile.size_label,
                    _boxes(w.boxes),
                    f"{w.tiles_bought} tiles, {w.tile.tiles_per_box} per box",
                )
            )
        if x.skirting:
            for i, p in enumerate(x.skirting.products, start=1):
                if p.tile is not None:
                    qty = _boxes(p.boxes or 0)
                    detail = (
                        f"{p.tiles} tiles cut into {p.pieces} strips "
                        f"({p.strips_per_tile} per tile), {_metres(p.run_mm)} run"
                    )
                else:
                    qty = _boxes(p.boxes) if p.boxes is not None else f"{p.pieces} pieces"
                    detail = f"{p.pieces} pieces of {_metres(p.piece_length_mm)}, {_metres(p.run_mm)} run"
                out.append(
                    ShopLine(
                        "Skirting",
                        f"S{i}",
                        p.label,
                        f"{x.skirting.height_mm.normalize():f} mm high",
                        qty,
                        detail,
                    )
                )
        for i, item in enumerate(x.sundries, start=1):
            unit = "bags" if item.key == "adhesive" else "packs"
            out.append(
                ShopLine(
                    "Sundries",
                    f"X{i}",
                    item.label,
                    f"{item.pack_size.normalize():f} {item.unit} {unit[:-1]}",
                    f"{item.packs} {unit}",
                    f"{item.quantity.normalize():f} {item.unit}: {item.basis}",
                )
            )
        return out

    @property
    def has_costs(self) -> bool:
        return self.cost is not None and (self.cost.has_prices or bool(self.cost.lines))


def export_data(doc: dict, area_unit: AreaUnit) -> ExportData:
    state = review_state(doc)
    default = project_default(doc)
    extras = extras_settings(doc)
    estimate = build_estimate(state, default, extras)
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
        cost=build_cost(state, default, estimate, settings, extras),
        settings=settings,
    )
