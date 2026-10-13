from decimal import Decimal

from app.engine.units import LengthUnit, mm2_to_sqft, to_mm
from app.schemas.material import Exclusion, Layout, MaterialOverride, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services.estimate import build_estimate
from app.services.review import review_state

FT = LengthUnit.FT
T2 = TileRef(
    id="t2",
    name="2×2 ft",
    size_label="2 × 2 ft",
    length_mm=to_mm(2, FT),
    width_mm=to_mm(2, FT),
    tiles_per_box=4,
)
T600 = TileRef(
    id="t6", name="600", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4
)


def ft(n) -> Decimal:
    return to_mm(str(n), FT)


def project(rooms: list[Room], default: ProjectMaterial) -> tuple:
    doc = {"rooms": [r.model_dump() for r in rooms], "default_material": default.model_dump()}
    return review_state(doc), default


def room(name, **kw) -> Room:
    return Room(**({"id": name, "name": name, "confirmed": True, "unit": FT} | kw))


ROOMS = [
    room("Bedroom 1", length_mm=ft(11), width_mm=ft("9.5")),
    room(
        "Kitchen",
        length_mm=ft(10),
        width_mm=ft(8),
        material=MaterialOverride(layout=Layout.DIAGONAL),
    ),
    room(
        "Utility", area_mm2=Decimal(5_000_000), material=MaterialOverride(tile=T600)
    ),  # odd shape, 5 m²
    room("Store", skipped=True),
]


def test_worked_project():
    est = build_estimate(*project(ROOMS, ProjectMaterial(tile=T2, breakage_pct=Decimal(5))))
    assert est.ready and est.blockers == []
    by = {r.name: r for r in est.rooms}
    assert set(by) == {"Bedroom 1", "Kitchen", "Utility"}  # skipped room left out

    bed = by["Bedroom 1"]  # PRD acceptance room
    assert (bed.method, bed.columns, bed.rows, bed.tiles_needed) == ("grid", 6, 5, 30)
    assert mm2_to_sqft(bed.cut_waste_mm2) == Decimal("15.5")
    assert (bed.buffer_tiles, bed.tiles_required, bed.boxes, bed.tiles_bought) == (2, 32, 8, 32)

    kit = by["Kitchen"]  # 80 sq ft diagonal: 80 × 1.15 / 4 = 23 tiles; +5% → 25; 7 boxes
    assert (kit.method, kit.allowance_pct, kit.tiles_needed) == ("area", Decimal(15), 23)
    assert (kit.tiles_required, kit.boxes) == (25, 7)
    assert "Diagonal" in kit.method_reason

    util = by["Utility"]  # 5 m² × 1.10 / 0.36 = 15.28 → 16; +5% → 17; 5 boxes
    assert (util.method, util.tiles_needed, util.tiles_required, util.boxes) == ("area", 16, 17, 5)


def test_totals_are_the_sum_of_the_rooms():
    est = build_estimate(*project(ROOMS, ProjectMaterial(tile=T2, breakage_pct=Decimal(5))))
    assert est.totals.boxes == sum(r.boxes for r in est.rooms) == 20
    assert est.totals.usable_area_mm2 == sum(r.usable_area_mm2 for r in est.rooms)
    assert est.totals.cut_waste_mm2 == sum(r.cut_waste_mm2 for r in est.rooms)
    two_by_two = next(t for t in est.tiles if t.tile.id == "t2")
    assert (two_by_two.rooms, two_by_two.tiles_required, two_by_two.boxes) == (2, 57, 15)
    assert two_by_two.boxes_if_pooled == 15  # ceil(57 / 4)


def test_pooling_leftovers_can_save_boxes():
    rooms = [
        room(f"R{i}", length_mm=Decimal(1200), width_mm=Decimal(600)) for i in range(3)
    ]  # 2 tiles each
    est = build_estimate(*project(rooms, ProjectMaterial(tile=T600, breakage_pct=Decimal(0))))
    (total,) = est.tiles
    assert (total.boxes, total.boxes_if_pooled) == (3, 2)  # 3 rooms × 1 box vs 6 tiles → 2 boxes


def test_exclusions_flow_through():
    kitchen = room(
        "Kitchen",
        length_mm=Decimal(3600),
        width_mm=Decimal(3000),
        exclusions=[
            Exclusion(id="i", label="Island", length_mm=Decimal(1800), width_mm=Decimal(1200))
        ],
    )
    (r,) = build_estimate(
        *project([kitchen], ProjectMaterial(tile=T600, breakage_pct=Decimal(0)))
    ).rooms
    # Island covers at least (3-1)×(2-1) = 2 whole tiles; 30 - 2 = 28.
    assert (r.grid_tiles, r.excluded_tiles, r.tiles_needed) == (30, 2, 28)
    assert r.usable_area_mm2 == Decimal(3600 * 3000 - 1800 * 1200)


def test_nothing_is_calculated_until_reviewed_and_tiled():
    unconfirmed = [
        room("Hall", length_mm=ft(10), width_mm=ft(10), confirmed=False),
        room("Bath", length_mm=ft(6), width_mm=ft(5)),
    ]
    est = build_estimate(*project(unconfirmed, ProjectMaterial()))
    assert not est.ready and est.rooms == [] and est.totals is None
    assert est.blockers == ["Confirm 1 room in the review.", "Choose a tile for 2 rooms."]


def test_empty_project_is_blocked():
    est = build_estimate(*project([], ProjectMaterial(tile=T2)))
    assert est.blockers == ["Add at least one room to tile."]


# --- Waste analysis (PRD 4.8) ---------------------------------------------------------------


def test_project_waste_breakdown_adds_up():
    est = build_estimate(*project(ROOMS, ProjectMaterial(tile=T2, breakage_pct=Decimal(5))))
    t = est.totals
    assert t.extra_area_mm2 == t.cut_waste_mm2 + t.buffer_area_mm2 + t.rounding_area_mm2
    assert t.extra_area_mm2 == t.bought_area_mm2 - t.usable_area_mm2
    for r in est.rooms:
        assert r.extra_area_mm2 == r.cut_waste_mm2 + r.buffer_area_mm2 + r.rounding_area_mm2
    assert t.cut_waste_pct == (t.cut_waste_mm2 / t.usable_area_mm2 * 100).quantize(Decimal("0.01"))


def test_high_waste_rooms_are_flagged_with_a_hint():
    # 700×700 mm room with 600 mm tiles: 4 tiles (1.44 m²) for 0.49 m² → 194% cut waste.
    small = room("Powder room", length_mm=Decimal(700), width_mm=Decimal(700))
    snug = room("Hall", length_mm=Decimal(3600), width_mm=Decimal(3000))  # exact fit: no cut waste
    est = build_estimate(*project([small, snug], ProjectMaterial(tile=T600)))
    by = {r.name: r for r in est.rooms}
    assert by["Powder room"].high_waste and "tile size that fits" in by["Powder room"].waste_hint
    assert not by["Hall"].high_waste and by["Hall"].waste_hint is None
    assert est.totals.high_waste_rooms == 1


def test_assumptions_describe_this_project():
    toilet = room(
        "Toilet",
        length_mm=ft(7),
        width_mm=ft(5),
        material=MaterialOverride(breakage_pct=Decimal(8)),
        exclusions=[
            Exclusion(id="w", label="WC pan", length_mm=Decimal(700), width_mm=Decimal(400))
        ],
    )
    state, default = project([*ROOMS, toilet], ProjectMaterial(tile=T2, breakage_pct=Decimal(5)))
    est = build_estimate(state, default)
    text = {a.key: a.text for a in est.assumptions}
    assert set(text) >= {
        "method_grid",
        "method_diagonal",
        "method_area",
        "buffer",
        "exclusions",
        "rounding",
        "not_included",
    }
    assert (
        "Bedroom 1" in text["method_grid"]
        and "Kitchen: area to tile plus 15%" in text["method_diagonal"]
    )
    assert (
        text["buffer"]
        == "5% extra tiles for breakage (project default); 8% for Toilet, rounded up to whole tiles."
    )
    assert text["exclusions"].startswith(
        "Toilet: WC pan (3.01 sq ft / 0.28 m² not tiled; 0 tiles subtracted)"
    )
    assert "Store: marked as needing no tiles." == text["skipped"]
    assert "offcut" in est.offcut_note


def test_assumptions_when_nothing_is_excluded():
    est = build_estimate(*project(ROOMS[:1], ProjectMaterial(tile=T2)))
    assert next(a for a in est.assumptions if a.key == "exclusions").text.startswith(
        "No untiled areas"
    )
