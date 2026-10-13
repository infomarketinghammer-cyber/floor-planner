from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.v1.rooms import rooms_out
from app.engine.units import LengthUnit, to_mm
from app.schemas.cost import CostLine, CostSettings, LineBasis, LineKind
from app.schemas.material import (
    MaterialOverride,
    Price,
    PriceBasis,
    ProjectMaterial,
    TileRef,
)
from app.schemas.project import Room
from app.services.cost import build_cost, price_per_box
from app.services.estimate import build_estimate
from app.services.review import review_state

FT = LengthUnit.FT
# 600 × 600 mm, 4 tiles a box: 1.44 m² per box.
T600 = TileRef(
    id="t6", name="600", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4
)


def ft(n) -> Decimal:
    return to_mm(str(n), FT)


def room(name, **kw) -> Room:
    return Room(**({"id": name, "name": name, "confirmed": True, "unit": FT} | kw))


def cost_for(rooms, default, settings=None):
    doc = {"rooms": [r.model_dump() for r in rooms], "default_material": default.model_dump()}
    state = review_state(doc)
    estimate = build_estimate(state, default)
    return build_cost(state, default, estimate, settings or CostSettings()), estimate


ROOMS = [
    room("Bedroom", length_mm=ft(11), width_mm=ft("9.5")),
    room("Kitchen", length_mm=ft(10), width_mm=ft(8)),
]


def default(price=None):
    return ProjectMaterial(tile=T600, breakage_pct=Decimal(5), price=price)


# --- price per box ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (Price(amount=Decimal(800), basis=PriceBasis.BOX), Decimal(800)),
        (Price(amount=Decimal(200), basis=PriceBasis.TILE), Decimal(800)),
        (Price(amount=Decimal(555), basis=PriceBasis.SQM), Decimal("799.2")),  # 1.44 m² × 555
    ],
)
def test_price_per_box(price, expected):
    assert price_per_box(price, T600) == expected


def test_price_per_sqft():
    per_sqft = price_per_box(Price(amount=Decimal(50), basis=PriceBasis.SQFT), T600)
    assert per_sqft.quantize(Decimal("0.01")) == Decimal("775.00")  # 1.44 m² = 15.5 sq ft


# --- room cost and total ------------------------------------------------------------------------


def test_room_cost_is_boxes_times_price_per_box():
    cost, est = cost_for(ROOMS, default(Price(amount=Decimal(800), basis=PriceBasis.BOX)))
    boxes = {r.room_id: r.boxes for r in est.rooms}
    by = {c.room_id: c for c in cost.rooms}
    assert cost.has_prices and cost.unpriced_rooms == 0
    for name in ("Bedroom", "Kitchen"):
        assert by[name].cost == boxes[name] * 800
    assert cost.materials == sum(c.cost for c in cost.rooms)
    assert cost.total == cost.materials  # no lines, no tax, no budget
    assert cost.budget is None and cost.warnings == []


def test_room_price_overrides_project_default():
    own = Price(amount=Decimal(1000), basis=PriceBasis.BOX)
    rooms = [
        ROOMS[0],
        room("Kitchen", length_mm=ft(10), width_mm=ft(8), material=MaterialOverride(price=own)),
    ]
    cost, est = cost_for(rooms, default(Price(amount=Decimal(800), basis=PriceBasis.BOX)))
    by = {c.room_id: c for c in cost.rooms}
    kitchen_boxes = next(r.boxes for r in est.rooms if r.room_id == "Kitchen")
    assert by["Kitchen"].cost == kitchen_boxes * 1000
    assert by["Bedroom"].price_per_box == 800


def test_no_prices_means_no_cost_columns():
    cost, _ = cost_for(ROOMS, default())
    assert not cost.has_prices and cost.materials is None
    assert all(c.cost is None for c in cost.rooms)
    assert cost.total == 0


def test_partly_priced_project_warns_and_leaves_unpriced_out():
    rooms = [
        ROOMS[0],
        room(
            "Kitchen",
            length_mm=ft(10),
            width_mm=ft(8),
            material=MaterialOverride(price=Price(amount=Decimal(900))),
        ),
    ]
    cost, _ = cost_for(rooms, default())
    assert (cost.priced_rooms, cost.unpriced_rooms) == (1, 1)
    assert cost.rooms[0].cost is None and cost.rooms[1].cost is not None
    assert cost.total == cost.materials
    assert "no price" in cost.warnings[0]


def test_not_ready_gives_no_cost():
    doc = {"rooms": [room("A").model_dump()], "default_material": default().model_dump()}  # no size
    state = review_state(doc)
    estimate = build_estimate(state, default())
    assert not estimate.ready
    assert build_cost(state, default(), estimate, CostSettings()) is None


# --- lines, tax, budget -------------------------------------------------------------------------


def test_lines_tax_and_total():
    price = Price(amount=Decimal(800), basis=PriceBasis.BOX)
    settings = CostSettings(
        tax_label="GST",
        tax_pct=Decimal(18),
        lines=[
            CostLine(kind=LineKind.DELIVERY, label="Delivery", amount=Decimal(1500)),
            CostLine(
                kind=LineKind.LABOUR,
                label="Fixing",
                amount=Decimal(40),
                basis=LineBasis.SQFT,
                taxable=False,
            ),
            CostLine(label="Per box handling", amount=Decimal(10), basis=LineBasis.BOX),
        ],
    )
    cost, est = cost_for(ROOMS, default(price), settings)
    boxes = est.totals.boxes
    area_sqft = est.totals.usable_area_mm2 / Decimal("92903.04")
    delivery, labour, handling = cost.lines
    assert delivery.amount == 1500 and delivery.quantity is None
    assert labour.amount == (Decimal(40) * area_sqft).quantize(Decimal("0.01"))
    assert handling.amount == 10 * boxes and handling.quantity == boxes

    base = cost.materials + delivery.amount + handling.amount  # labour isn't taxable
    assert cost.tax.base == base
    assert cost.tax.amount == (base * Decimal(18) / 100).quantize(Decimal("0.01"))
    assert (
        cost.total
        == cost.materials + delivery.amount + labour.amount + handling.amount + cost.tax.amount
    )


def test_tax_can_skip_the_tiles():
    settings = CostSettings(
        tax_pct=Decimal(10),
        tax_materials=False,
        lines=[CostLine(label="Labour", amount=Decimal(1000))],
    )
    cost, _ = cost_for(ROOMS, default(Price(amount=Decimal(800))), settings)
    assert cost.tax.base == 1000 and cost.tax.amount == 100


def test_zero_tax_has_no_tax_line():
    cost, _ = cost_for(ROOMS, default(Price(amount=Decimal(800))))
    assert cost.tax is None


def test_lines_work_without_any_tile_price():
    settings = CostSettings(lines=[CostLine(label="Labour", amount=Decimal(5000))])
    cost, _ = cost_for(ROOMS, default(), settings)
    assert not cost.has_prices and cost.total == 5000


def test_budget_status():
    price = Price(amount=Decimal(800))
    total = cost_for(ROOMS, default(price))[0].total

    def status(budget):
        c, _ = cost_for(ROOMS, default(price), CostSettings(budget=budget))
        return c.budget

    assert status(total * 2).status == "under"
    near = status(total * Decimal("1.05"))  # 95% used
    assert near.status == "near" and near.remaining > 0
    assert status(total).status == "near"  # exactly on budget isn't over
    over = status(total - 100)
    assert over.status == "over" and over.remaining == -100


# --- settings validation and API output ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"currency": "rupee"},
        {"currency": "inr"},
        {"locale": "not a locale"},
        {"tax_pct": "101"},
        {"tax_pct": "-1"},
        {"budget": "0"},
        {"lines": [{"label": "Delivery", "amount": "0"}]},
        {"lines": [{"label": "", "amount": "10"}]},
    ],
)
def test_invalid_settings_rejected(bad):
    with pytest.raises(ValidationError):
        CostSettings.model_validate(bad)


def test_settings_round_trip_as_strings():
    s = CostSettings(
        currency="USD",
        locale="en-US",
        tax_pct=Decimal("8.25"),
        budget=Decimal(12000),
        lines=[CostLine(label="Delivery", amount=Decimal("99.5"))],
    )
    dumped = s.model_dump()  # what is stored in MongoDB: no Decimal objects
    assert dumped["tax_pct"] == "8.25" and dumped["budget"] == "12000"
    assert dumped["lines"][0]["amount"] == "99.5"
    assert CostSettings.model_validate(dumped) == s


def test_rooms_out_includes_cost():
    doc = {
        "rooms": [r.model_dump() for r in ROOMS],
        "default_material": default(Price(amount=Decimal(800))).model_dump(),
        "cost_settings": CostSettings(budget=Decimal(1)).model_dump(),
        "rooms_version": 1,
    }
    out = rooms_out(doc).model_dump(mode="json")
    assert out["cost_settings"]["budget"] == "1"
    assert out["cost"]["has_prices"] and out["cost"]["budget"]["status"] == "over"
    assert isinstance(out["cost"]["total"], str)


def test_rooms_out_without_settings_uses_defaults():
    doc = {"rooms": [], "rooms_version": 0}
    out = rooms_out(doc).model_dump(mode="json")
    assert out["cost"] is None and out["cost_settings"]["currency"] == "INR"
