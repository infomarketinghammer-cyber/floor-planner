"""Cost estimate (PRD 4.10): what the tiles cost per room, extra lines, tax, total and budget.

Pure functions on top of the quantity estimate: a room's cost is the boxes it needs × the price
per box, so costs only exist once the quantities do. Amounts are rounded to 2 places per line;
the total is the sum of the rounded lines, so the breakdown always adds up.
"""

from decimal import Decimal

from app.engine.units import MM2_PER_SQFT, MM2_PER_SQM
from app.schemas.cost import (
    BudgetOut,
    CostLine,
    CostLineOut,
    CostOut,
    CostSettings,
    LineBasis,
    RoomCostOut,
    TaxOut,
)
from app.schemas.estimate import EstimateOut
from app.schemas.material import Price, PriceBasis, ProjectMaterial, TileRef
from app.services.materials import effective
from app.services.review import ReviewState

_CENT = Decimal("0.01")
NEAR_BUDGET_PCT = Decimal(90)  # warn from this share of the budget


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


def cost_settings(doc: dict) -> CostSettings:
    return CostSettings.model_validate(doc.get("cost_settings") or {})


def price_per_box(price: Price, tile: TileRef) -> Decimal:
    """The price of one box, whatever basis the price was entered in. Not rounded."""
    match price.basis:
        case PriceBasis.BOX:
            return price.amount
        case PriceBasis.TILE:
            return price.amount * tile.tiles_per_box
    box_area_mm2 = tile.length_mm * tile.width_mm * tile.tiles_per_box
    per_unit = MM2_PER_SQFT if price.basis == PriceBasis.SQFT else MM2_PER_SQM
    return price.amount * box_area_mm2 / per_unit


def _line(line: CostLine, usable_area_mm2: Decimal, boxes: int) -> CostLineOut:
    quantity: Decimal | None
    match line.basis:
        case LineBasis.FIXED:
            quantity = None
        case LineBasis.SQFT:
            quantity = usable_area_mm2 / MM2_PER_SQFT
        case LineBasis.SQM:
            quantity = usable_area_mm2 / MM2_PER_SQM
        case LineBasis.BOX:
            quantity = Decimal(boxes)
    amount = line.amount if quantity is None else line.amount * quantity
    return CostLineOut(
        id=line.id,
        kind=line.kind,
        label=line.label,
        basis=line.basis,
        rate=line.amount,
        quantity=None if quantity is None else quantity.quantize(_CENT).normalize(),
        amount=_money(amount),
        taxable=line.taxable,
    )


def _budget(total: Decimal, target: Decimal) -> BudgetOut:
    used = total / target * 100
    status = "over" if total > target else "near" if used >= NEAR_BUDGET_PCT else "under"
    return BudgetOut(
        target=target,
        remaining=target - total,
        used_pct=used.quantize(Decimal("0.1")),
        status=status,
    )


def build_cost(
    state: ReviewState,
    default: ProjectMaterial,
    estimate: EstimateOut,
    settings: CostSettings,
) -> CostOut | None:
    """None until the quantities are ready: there are no boxes to price before that."""
    if not estimate.ready or estimate.totals is None:
        return None

    by_id = {r.id: r for r in state.rooms}
    rooms: list[RoomCostOut] = []
    for est in estimate.rooms:
        price = effective(by_id[est.room_id], default).price
        per_box = price_per_box(price, est.tile) if price else None
        rooms.append(
            RoomCostOut(
                room_id=est.room_id,
                price=price,
                price_per_box=_money(per_box) if per_box is not None else None,
                cost=_money(est.boxes * per_box) if per_box is not None else None,
            )
        )

    priced = [r.cost for r in rooms if r.cost is not None]
    materials = sum(priced, Decimal(0)) if priced else None
    unpriced = len(rooms) - len(priced)

    totals = estimate.totals
    lines = [_line(line, totals.usable_area_mm2, totals.boxes) for line in settings.lines]
    lines_total = sum((line.amount for line in lines), Decimal(0))

    tax = None
    if settings.tax_pct > 0:
        base = sum((line.amount for line in lines if line.taxable), Decimal(0))
        if settings.tax_materials and materials is not None:
            base += materials
        if base > 0:
            tax = TaxOut(
                label=settings.tax_label,
                pct=settings.tax_pct,
                base=base,
                amount=_money(base * settings.tax_pct / 100),
            )

    total = (materials or Decimal(0)) + lines_total + (tax.amount if tax else Decimal(0))

    warnings = []
    if priced and unpriced:
        rooms_text = "1 room has" if unpriced == 1 else f"{unpriced} rooms have"
        their = "its" if unpriced == 1 else "their"
        warnings.append(
            f"{rooms_text} no price, so {their} tiles aren't in the total. "
            "Add a price in the Materials section."
        )

    return CostOut(
        has_prices=bool(priced),
        priced_rooms=len(priced),
        unpriced_rooms=unpriced,
        rooms=rooms,
        materials=materials,
        lines=lines,
        tax=tax,
        total=total,
        budget=_budget(total, settings.budget) if settings.budget is not None else None,
        warnings=warnings,
    )
