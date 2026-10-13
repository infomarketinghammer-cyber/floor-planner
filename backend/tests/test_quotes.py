from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.exports.data import export_data
from app.exports.pdf import render_order_list
from app.exports.quote_pdf import render_quote
from app.schemas.cost import CostLine, CostSettings, LineBasis, LineKind
from app.schemas.material import MaterialOverride, Price, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.schemas.quote import CompanyProfile, ExtraLineIn, Quote, QuoteClient
from app.services.cost import build_cost
from app.services.estimate import build_estimate
from app.services.quotes import NotQuotable, quote_lines, totals
from app.services.review import review_state
from tests.test_exports import pdf_text

D = Decimal
T600 = TileRef(
    id="t6", name="Ivory", size_label="600 × 600 mm", length_mm=600, width_mm=600,
    tiles_per_box=4, vendor="Sharma Tiles", code="IV-600",
)  # fmt: skip
ANTI = TileRef(
    id="a3", name="Grip", size_label="300 × 300 mm", length_mm=300, width_mm=300,
    tiles_per_box=11, vendor="Coastal Ceramics",
)  # fmt: skip


def room(name, length, width, **kw) -> Room:
    return Room(
        **(
            {
                "id": name,
                "name": name,
                "confirmed": True,
                "unit": "mm",
                "length_mm": D(length),
                "width_mm": D(width),
            }
            | kw
        )
    )


ROOMS = [
    room("Bedroom", 3200, 3000),
    room("Living", 4800, 4000),
    room("Toilet", 1500, 1200, material=MaterialOverride(tile=ANTI, price=Price(amount=D(600)))),
]
SETTINGS = CostSettings(
    tax_label="GST",
    tax_pct=D(18),
    lines=[
        CostLine(kind=LineKind.DELIVERY, label="Delivery", amount=D(1500)),
        CostLine(
            kind=LineKind.LABOUR, label="Fixing", amount=D(40), basis=LineBasis.SQFT, taxable=False
        ),
    ],
)


def priced(price=Price(amount=D(800))):
    state = review_state({"rooms": [r.model_dump() for r in ROOMS]})
    default = ProjectMaterial(tile=T600, breakage_pct=D(5), price=price)
    estimate = build_estimate(state, default)
    return estimate, build_cost(state, default, estimate, SETTINGS)


def test_margin_on_materials_only_and_tax():
    estimate, cost = priced()
    lines = quote_lines(
        estimate, cost, SETTINGS, D(20), False, [ExtraLineIn(description="Levelling", rate=D(2000))]
    )
    materials = [line for line in lines if line.kind == "material"]
    assert len(materials) == 2  # 600 × 600 (two rooms) and the toilet's own tile
    ivory = materials[0]
    assert ivory.unit == "boxes" and ivory.unit_price == D("960.00")  # 800 + 20%
    assert ivory.cost == ivory.quantity * 800 and ivory.amount == ivory.quantity * D(960)
    delivery = next(line for line in lines if line.description == "Delivery")
    assert delivery.amount == delivery.cost == D(1500)  # labour/delivery pass through
    fixing = next(line for line in lines if line.description == "Fixing")
    assert fixing.unit == "sq ft" and not fixing.taxable
    levelling = next(line for line in lines if line.description == "Levelling")
    assert levelling.kind == "labour" and levelling.amount == 2000

    t = totals(lines, D(18))
    assert t["subtotal"] == sum(line.amount for line in lines)
    taxable = sum(line.amount for line in lines if line.taxable)
    assert t["tax_amount"] == (taxable * D(18) / 100).quantize(D("0.01"))
    assert t["total"] == t["subtotal"] + t["tax_amount"]
    assert t["margin_amount"] == sum(
        line.amount - line.cost for line in lines if line.kind == "material"
    )


def test_margin_on_labour_when_asked():
    estimate, cost = priced()
    lines = quote_lines(estimate, cost, SETTINGS, D(10), True, [])
    delivery = next(line for line in lines if line.description == "Delivery")
    assert delivery.amount == D("1650.00") and delivery.cost == D(1500)


def test_unpriced_rooms_cant_be_quoted():
    estimate, cost = priced(price=None)  # only the toilet has a price
    with pytest.raises(NotQuotable, match="price"):
        quote_lines(estimate, cost, SETTINGS, D(10), False, [])


def _quote(lines) -> Quote:
    t = totals(lines, D(18))
    now = datetime.now(UTC)
    return Quote(
        id="q", project_id="p", project_name="Sharma residence", number="Q-2026-0007", version=2,
        latest=True, status="draft", client=QuoteClient(name="Mr & Mrs Rao", email="rao@example.com"),
        margin_pct=D(20), lines=lines, tax_label="GST", tax_pct=D(18), currency="INR", locale="en-IN",
        notes="Includes removal of old tiles.", terms="50% advance.", valid_until=now + timedelta(days=30),
        created_at=now, sent_at=None, decided_at=None, **t,
    )  # fmt: skip


def test_quote_pdf_shows_prices_but_never_cost_or_margin():
    estimate, cost = priced()
    lines = quote_lines(estimate, cost, SETTINGS, D(20), False, [])
    q = _quote(lines)
    company = CompanyProfile(
        name="Asha Tiling", address="12 MG Road, Pune", tax_id="27ABCDE1234F1Z5"
    )
    text = pdf_text(render_quote(q, company, None))
    for expected in (
        "Quotation",
        "Q-2026-0007",
        "version 2",
        "Asha Tiling",
        "27ABCDE1234F1Z5",
        "Mr & Mrs Rao",
        "Sharma residence",
        "Accepted by",
    ):
        assert expected in text, expected
    assert "960.00" in text  # client unit price
    assert "800.00" not in text  # the contractor's cost price never appears
    assert "margin" not in text.lower()


def test_order_list_groups_by_vendor():
    from tests.test_exports import project

    doc = project(price=Price(amount=D(800)), rooms=ROOMS)
    doc["default_material"]["tile"] = T600.model_dump()
    data = export_data(doc, "sqft")
    assert {line.vendor for line in data.shopping_lines} == {"Sharma Tiles", "Coastal Ceramics"}
    text = pdf_text(render_order_list(data))
    assert text.index("Coastal Ceramics") < text.index("Sharma Tiles")  # alphabetical
    assert "IV-600" in text
