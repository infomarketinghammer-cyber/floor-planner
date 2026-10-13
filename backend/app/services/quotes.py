"""Building a quotation from a calculated, priced project (PRD 4.19). Pure functions.

Materials (floor tiles, wall tiles, skirting, sundries) are marked up by the margin; delivery and
labour lines pass through as entered unless `margin_on_labour`. The client sees unit prices with
the margin included; the contractor also sees cost and margin.
"""

import re
from collections import OrderedDict
from decimal import Decimal

from app.schemas.cost import CostOut, CostSettings, LineBasis
from app.schemas.estimate import EstimateOut
from app.schemas.material import ProductKind
from app.schemas.quote import ExtraLineIn, QuoteLine

_CENT = Decimal("0.01")
_BASIS_UNITS = {LineBasis.SQFT: "sq ft", LineBasis.SQM: "m²", LineBasis.BOX: "boxes"}


class NotQuotable(Exception):
    """Why a quote can't be made yet; safe to show the user."""


def _money(v: Decimal) -> Decimal:
    return v.quantize(_CENT)


def _up(v: Decimal, margin_pct: Decimal) -> Decimal:
    return v * (1 + margin_pct / 100)


def _line(kind, description, quantity, unit, unit_cost, margin_pct, taxable) -> QuoteLine:
    q = Decimal(quantity)
    unit_price = _money(_up(unit_cost, margin_pct))
    # On a client's document every line must multiply out: amount = quantity × unit price.
    return QuoteLine(
        kind=kind,
        description=description,
        quantity=q,
        unit=unit,
        unit_price=unit_price,
        amount=_money(q * unit_price),
        cost=_money(q * unit_cost),
        taxable=taxable,
    )


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]+", "x", text).strip("x")


def _describe(tile, product: str) -> str:
    """E.g. "Ivory matt tiles, 600 × 600 mm"; the size is left out if the name has it."""
    size = tile.size_label.rsplit(" ", 1)[0]  # "600 × 600"
    if _digits(size) in _digits(tile.name):
        return f"{tile.name} {product}"
    return f"{tile.name} {product}, {tile.size_label}"


def quote_lines(
    estimate: EstimateOut,
    cost: CostOut | None,
    settings: CostSettings,
    margin_pct: Decimal,
    margin_on_labour: bool,
    extra_lines: list[ExtraLineIn],
) -> list[QuoteLine]:
    if not estimate.ready or cost is None:
        raise NotQuotable("Finish the estimate first: " + "; ".join(estimate.blockers))
    if cost.unpriced_rooms or not cost.priced_rooms:
        raise NotQuotable(
            "Every room needs a tile price before you can quote. Add prices in Tiles & materials."
        )
    taxable_materials = settings.tax_materials
    lines: list[QuoteLine] = []

    # Floor products: one line per tile and price (a room with its own price gets its own line).
    groups: OrderedDict[tuple, dict] = OrderedDict()
    costs = {c.room_id: c for c in cost.rooms}
    for r in estimate.rooms:
        c = costs[r.room_id]
        key = (r.tile.id, c.price_per_box)
        g = groups.setdefault(
            key, {"tile": r.tile, "boxes": 0, "linear": Decimal(0), "cost": Decimal(0), "rooms": []}
        )
        g["boxes"] += r.boxes
        g["linear"] += r.linear_mm or 0
        g["cost"] += c.cost
        g["rooms"].append(r.name)
    for g in groups.values():
        t = g["tile"]
        rooms = ", ".join(g["rooms"][:4]) + (
            f" and {len(g['rooms']) - 4} more" if len(g["rooms"]) > 4 else ""
        )
        product = {"plank": "planks", "roll": "roll flooring"}.get(t.kind, "tiles")
        description = f"{_describe(t, product)} ({rooms})"
        if t.kind == ProductKind.ROLL:
            metres = (g["linear"] / 1000).quantize(_CENT)
            lines.append(
                _line(
                    "material",
                    description,
                    metres,
                    "m",
                    g["cost"] / metres,
                    margin_pct,
                    taxable_materials,
                )
            )
        else:
            lines.append(
                _line(
                    "material",
                    description,
                    g["boxes"],
                    "boxes",
                    g["cost"] / g["boxes"],
                    margin_pct,
                    taxable_materials,
                )
            )

    # Wall tiles, skirting, sundries.
    for x in cost.extras:
        lines.append(
            _line(
                "extra",
                x.label,
                x.quantity,
                x.unit,
                x.amount / x.quantity,
                margin_pct,
                taxable_materials,
            )
        )

    # Delivery, labour and other lines from the cost settings.
    pass_margin = margin_pct if margin_on_labour else Decimal(0)
    for line in cost.lines:
        kind = line.kind.value if line.kind.value in ("labour", "delivery") else "other"
        if line.quantity is None:
            lines.append(_line(kind, line.label, 1, "item", line.amount, pass_margin, line.taxable))
        else:
            q = line.quantity
            lines.append(
                _line(
                    kind,
                    line.label,
                    q,
                    _BASIS_UNITS[line.basis],
                    line.rate,  # the rate as entered, so quantity × rate checks
                    pass_margin,
                    line.taxable,
                )
            )

    # Lines added on this quote only.
    for e in extra_lines:
        lines.append(
            _line(e.kind, e.description, e.quantity, e.unit, e.rate, pass_margin, e.taxable)
        )
    return lines


def totals(lines: list[QuoteLine], tax_pct: Decimal) -> dict:
    subtotal = sum((line.amount for line in lines), Decimal(0))
    taxable = sum((line.amount for line in lines if line.taxable), Decimal(0))
    tax = _money(taxable * tax_pct / 100)
    cost_total = sum((line.cost for line in lines), Decimal(0))
    return {
        "subtotal": subtotal,
        "tax_amount": tax,
        "total": subtotal + tax,
        "cost_total": cost_total,
        "margin_amount": subtotal - cost_total,
    }
