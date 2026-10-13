from decimal import Decimal

from app.schemas.material import (
    Exclusion,
    Layout,
    MaterialOverride,
    Price,
    PriceBasis,
    ProjectMaterial,
    TileRef,
)
from app.schemas.project import Room
from app.services.materials import effective, exclusion_area_mm2, materials_summary, usable_area_mm2

T600 = TileRef(
    id="a", name="600", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4
)
T300 = TileRef(
    id="b", name="300", size_label="300 × 300 mm", length_mm=300, width_mm=300, tiles_per_box=11
)
_ids = iter(range(1000))


def room(**kw) -> Room:
    return Room(
        **({"id": f"r{next(_ids)}", "name": "Room", "length_mm": 4000, "width_mm": 3000} | kw)
    )


def test_room_inherits_every_setting_from_the_project():
    default = ProjectMaterial(tile=T600, layout=Layout.DIAGONAL, breakage_pct=Decimal(8))
    eff = effective(room(), default)
    assert (eff.tile, eff.layout, eff.breakage_pct, eff.price, eff.overridden) == (
        T600,
        Layout.DIAGONAL,
        Decimal(8),
        None,
        [],
    )


def test_room_overrides_one_setting_and_keeps_the_rest():
    default = ProjectMaterial(tile=T600, breakage_pct=Decimal(5))
    price = Price(amount=Decimal(45), basis=PriceBasis.SQFT)
    eff = effective(room(material=MaterialOverride(tile=T300, price=price)), default)
    assert (eff.tile, eff.breakage_pct, eff.price, eff.overridden) == (
        T300,
        Decimal(5),
        price,
        ["tile", "price"],
    )


def test_default_breakage_is_five_percent():
    assert ProjectMaterial().breakage_pct == Decimal(5)


def test_exclusions_reduce_usable_area():
    r = room(
        exclusions=[
            Exclusion(id="c", label="Cabinet", length_mm=2400, width_mm=600),
            Exclusion(id="p", label="Column", length_mm=300, width_mm=300, quantity=2),
        ]
    )
    assert exclusion_area_mm2(r) == Decimal(2400 * 600 + 2 * 300 * 300)
    assert usable_area_mm2(r) == Decimal(4000 * 3000) - exclusion_area_mm2(r)
    assert usable_area_mm2(room(width_mm=None)) is None


def test_summary_counts_tiles_skips_and_readiness():
    rooms = [room(), room(skipped=True), room(material=MaterialOverride(tile=T300))]
    no_default = materials_summary(rooms, ProjectMaterial(), review_ready=True)
    assert (
        no_default.rooms_needing_tile,
        no_default.skipped,
        no_default.ready_for_calculation,
    ) == (1, 1, False)
    with_default = materials_summary(rooms, ProjectMaterial(tile=T600), review_ready=True)
    assert with_default.ready_for_calculation
    assert not materials_summary(
        rooms, ProjectMaterial(tile=T600), review_ready=False
    ).ready_for_calculation


def test_decimals_serialise_as_strings():
    dumped = ProjectMaterial(tile=T600, price=Price(amount=Decimal("49.50"))).model_dump(
        mode="json"
    )
    assert dumped["breakage_pct"] == "5" and dumped["price"]["amount"] == "49.50"
    assert dumped["tile"]["length_mm"] == "600"
