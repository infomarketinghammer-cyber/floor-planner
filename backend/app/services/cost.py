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
    ExtraCostOut,
    LineBasis,
    RoomCostOut,
    TaxOut,
)
from app.schemas.estimate import EstimateOut, RoomEstimateOut
from app.schemas.extras import ExtrasSettings
from app.schemas.material import Price, PriceBasis, ProductKind, ProjectMaterial, TileRef
from app.services.materials import effective
from app.services.review import ReviewState

_CENT = Decimal("0.01")
NEAR_BUDGET_PCT = Decimal(90)  # warn from this share of the budget


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


def cost_settings(doc: dict) -> CostSettings:
    return CostSettings.model_validate(doc.get("cost_settings") or {})


def price_per_box(price: Price, tile: TileRef) -> Decimal:
    """The price of one box, whatever basis the price was entered in. Not rounded.
    Raises ValueError for a per-running-metre price, which only fits roll goods."""
    match price.basis:
        case PriceBasis.LM:
            raise ValueError("a price per running metre only applies to roll flooring.")
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


def _room_cost(
    price: Price | None, est: RoomEstimateOut, warnings: list[str]
) -> tuple[Decimal | None, Decimal | None]:
    """(price per box, room cost). Roll goods have no boxes: priced per running metre or area."""
    if price is None:
        return None, None
    if est.kind == ProductKind.ROLL:
        bought = est.usable_area_mm2 + est.extra_area_mm2
        match price.basis:
            case PriceBasis.LM:
                return None, _money(est.linear_mm / 1000 * price.amount)
            case PriceBasis.SQM:
                return None, _money(bought / MM2_PER_SQM * price.amount)
            case PriceBasis.SQFT:
                return None, _money(bought / MM2_PER_SQFT * price.amount)
        warnings.append(f"{est.name}: price roll flooring per running metre, m² or sq ft.")
        return None, None
    try:
        per_box = price_per_box(price, est.tile)
    except ValueError as e:
        warnings.append(f"{est.name}: {e}")
        return None, None
    return per_box, _money(est.boxes * per_box)


def _extra(
    key: str, label: str, quantity, unit: str, unit_price: Decimal, amount=None
) -> ExtraCostOut:
    q = Decimal(quantity)
    return ExtraCostOut(
        key=key,
        label=label,
        quantity=q,
        unit=unit,
        unit_price=_money(unit_price),
        amount=_money(amount if amount is not None else q * unit_price),
    )


def _floor_price(tile_id: str, estimate: EstimateOut, rooms: dict, default) -> Price | None:
    """The price of a floor tile, from the first room using it that has one."""
    for e in estimate.rooms:
        if e.tile.id == tile_id:
            price = effective(rooms[e.room_id], default).price
            if price is not None:
                return price
    return None


def _extras_costs(
    estimate: EstimateOut,
    rooms: dict,
    default: ProjectMaterial,
    settings: ExtrasSettings,
    warnings: list[str],
) -> list[ExtraCostOut]:
    """Prices for wall tiles, skirting and sundries (PRD 4.15). Unpriced ones are left out."""
    x = estimate.extras
    if x is None:
        return []
    out: list[ExtraCostOut] = []

    # Wall tiles: each room's own wall price, else the project's wall price; grouped by tile.
    walls: dict[str, list] = {}
    for w in x.walls:
        own = rooms[w.room_id].walls
        price = (own.price if own else None) or settings.wall_price
        if price is None:
            continue
        try:
            per_box = price_per_box(price, w.tile)
        except ValueError:
            warnings.append(f"{w.name}: price wall tiles per box, tile, m² or sq ft.")
            continue
        group = walls.setdefault(w.tile.id, [w.tile, 0, Decimal(0)])
        group[1] += w.boxes
        group[2] += w.boxes * per_box
    for tile_id, (tile, boxes, amount) in walls.items():
        if boxes:
            label = f"Wall tiles {tile.size_label} {tile.name}"
            out.append(_extra(f"wall:{tile_id}", label, boxes, "boxes", amount / boxes, amount))

    # Skirting: strips cut from a floor tile cost that tile's price; pieces have their own.
    if x.skirting:
        sk = settings.skirting
        for p in x.skirting.products:
            if p.tile is not None:
                price = _floor_price(p.tile.id, estimate, rooms, default)
                if price is None or not p.boxes:
                    continue
                try:
                    per_box = price_per_box(price, p.tile)
                except ValueError:
                    continue
                out.append(_extra(f"skirting:{p.tile.id}", p.label, p.boxes, "boxes", per_box))
            elif sk.price is not None and p.pieces:
                basis = sk.price.basis
                if basis == PriceBasis.BOX and p.boxes is not None:
                    out.append(
                        _extra("skirting:pieces", p.label, p.boxes, "boxes", sk.price.amount)
                    )
                elif basis == PriceBasis.TILE:
                    out.append(
                        _extra("skirting:pieces", p.label, p.pieces, "pieces", sk.price.amount)
                    )
                elif basis == PriceBasis.LM:
                    metres = (p.pieces * p.piece_length_mm / 1000).quantize(_CENT)
                    out.append(_extra("skirting:pieces", p.label, metres, "m", sk.price.amount))
                else:
                    warnings.append(
                        "Price skirting pieces per box (with pieces per box set), per piece or "
                        "per running metre."
                    )

    # Sundries: packs × pack price.
    s = settings.sundries
    pack_prices = {
        "adhesive": (s.adhesive_bag_price, "bags"),
        "grout": (s.grout_pack_price, "packs"),
        "spacers": (s.spacer_pack_price, "packs"),
    }
    for item in x.sundries:
        price, unit = pack_prices[item.key]
        if price is not None and item.packs:
            out.append(_extra(item.key, item.label, item.packs, unit, price))
    return out


def build_cost(
    state: ReviewState,
    default: ProjectMaterial,
    estimate: EstimateOut,
    settings: CostSettings,
    extras_settings: ExtrasSettings | None = None,
) -> CostOut | None:
    """None until the quantities are ready: there are no boxes to price before that."""
    if not estimate.ready or estimate.totals is None:
        return None

    by_id = {r.id: r for r in state.rooms}
    rooms: list[RoomCostOut] = []
    warnings: list[str] = []
    for est in estimate.rooms:
        price = effective(by_id[est.room_id], default).price
        per_box, cost = _room_cost(price, est, warnings)
        rooms.append(
            RoomCostOut(
                room_id=est.room_id,
                price=price,
                price_per_box=_money(per_box) if per_box is not None else None,
                cost=cost,
            )
        )

    priced = [r.cost for r in rooms if r.cost is not None]
    materials = sum(priced, Decimal(0)) if priced else None
    unpriced = len(rooms) - len(priced)
    extras = _extras_costs(estimate, by_id, default, extras_settings or ExtrasSettings(), warnings)
    extras_total = sum((x.amount for x in extras), Decimal(0))

    totals = estimate.totals
    lines = [_line(line, totals.usable_area_mm2, totals.boxes) for line in settings.lines]
    lines_total = sum((line.amount for line in lines), Decimal(0))

    tax = None
    if settings.tax_pct > 0:
        base = sum((line.amount for line in lines if line.taxable), Decimal(0))
        if settings.tax_materials:
            base += (materials or Decimal(0)) + extras_total
        if base > 0:
            tax = TaxOut(
                label=settings.tax_label,
                pct=settings.tax_pct,
                base=base,
                amount=_money(base * settings.tax_pct / 100),
            )

    total = (
        (materials or Decimal(0)) + extras_total + lines_total + (tax.amount if tax else Decimal(0))
    )

    if priced and unpriced:
        rooms_text = "1 room has" if unpriced == 1 else f"{unpriced} rooms have"
        their = "its" if unpriced == 1 else "their"
        warnings.append(
            f"{rooms_text} no price, so {their} tiles aren't in the total. "
            "Add a price in the Materials section."
        )

    return CostOut(
        has_prices=bool(priced or extras),
        priced_rooms=len(priced),
        unpriced_rooms=unpriced,
        rooms=rooms,
        materials=materials,
        extras=extras,
        lines=lines,
        tax=tax,
        total=total,
        budget=_budget(total, settings.budget) if settings.budget is not None else None,
        warnings=warnings,
    )
