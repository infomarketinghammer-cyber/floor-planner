from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.cost import CostSettings
from app.schemas.extras import ExtrasSettings
from app.schemas.material import Layout, MaterialOverride, Price, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.schemas.scenario import Scenario, ScenarioResultOut, ScenarioRoom
from app.services.scenarios import apply_scenario, compare, recommend

D = Decimal
NOW = datetime.now(UTC)
T600 = TileRef(
    id="t6", name="600", size_label="600 × 600 mm", length_mm=600, width_mm=600,
    tiles_per_box=4, tile_type="floor",
)  # fmt: skip
T800 = TileRef(
    id="t8", name="800", size_label="800 × 800 mm", length_mm=800, width_mm=800,
    tiles_per_box=3, tile_type="floor",
)  # fmt: skip
ANTI = TileRef(
    id="a3", name="Anti", size_label="300 × 300 mm", length_mm=300, width_mm=300,
    tiles_per_box=11, tile_type="anti_skid",
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
    room("Bedroom", 3200, 3200),
    room("Living", 4800, 4000),
    room("Toilet", 1500, 1200, material=MaterialOverride(tile=ANTI, price=Price(amount=D(500)))),
]


def scenario(sid, tile, price=None, **kw) -> Scenario:
    return Scenario(
        id=sid, name=sid, default=ProjectMaterial(tile=tile, breakage_pct=D(0), price=price),
        created_at=NOW, updated_at=NOW, **kw,
    )  # fmt: skip


def doc(scenarios=()) -> dict:
    return {
        "rooms": [r.model_dump() for r in ROOMS],
        "scenarios": [s.model_dump() for s in scenarios],
    }


def test_apply_keeps_rooms_own_tiles_unless_every_room():
    rooms, default = apply_scenario(ROOMS, scenario("s", T800))
    assert default.tile.id == "t8"
    assert rooms[2].material.tile.id == "a3"  # the toilet keeps its anti-skid tile
    rooms, _ = apply_scenario(ROOMS, scenario("s", T800, every_room=True))
    assert rooms[2].material.tile is None
    rooms, _ = apply_scenario(
        ROOMS,
        scenario("s", T800, every_room=True, rooms=[ScenarioRoom(room_id="Toilet", tile=ANTI)]),
    )
    assert rooms[2].material.tile.id == "a3"


def test_compare_side_by_side_and_recommend_least_waste_without_prices():
    project_default = ProjectMaterial(tile=T600, breakage_pct=D(0))
    c = compare(
        doc([scenario("Big tiles", T800)]), CostSettings(), ExtrasSettings(), project_default, []
    )
    current, big = c.results
    assert current.id == "current" and big.name == "Big tiles"
    assert big.extra_area_mm2 < current.extra_area_mm2  # 800 tiles fit 3200 and 4800 exactly
    assert c.best.scenario_id == big.id
    assert "wastes the least" in c.best.reasons[0]
    assert "lowest_waste" in big.badges
    assert any("Add prices" in r for r in c.best.reasons)  # only the toilet is priced


def test_recommend_cheapest_within_budget():
    project_default = ProjectMaterial(tile=T600, breakage_pct=D(0), price=Price(amount=D(800)))
    cheap = scenario("Cheap 800", T800, Price(amount=D(700)))
    pricey = scenario("Premium 800", T800, Price(amount=D(2500)))
    settings = CostSettings(budget=D(30000))
    c = compare(doc([cheap, pricey]), settings, ExtrasSettings(), project_default, [])
    by_name = {r.name: r for r in c.results}
    assert all(r.fully_priced for r in c.results)
    assert c.best.scenario_id == by_name["Cheap 800"].id
    assert "within your budget" in c.best.reasons[0]
    assert "over_budget" in by_name["Premium 800"].badges
    assert "lowest_cost" in by_name["Cheap 800"].badges


def _r(sid, cost, extra, boxes, priced=True) -> ScenarioResultOut:
    return ScenarioResultOut(
        id=sid, name=sid, notes=None, every_room=False, ready=True, blockers=[], tiles=[],
        boxes=boxes, tiles_bought=0, usable_area_mm2=D(100), bought_area_mm2=D(100),
        extra_area_mm2=D(extra), extra_pct=D(extra), cut_waste_pct=D(0),
        cost=D(cost) if cost is not None else None, fully_priced=priced,
        budget_remaining=None, rooms=[], badges=[],
    )  # fmt: skip


def test_recommend_when_nothing_fits_the_budget():
    best = recommend([_r("a", 1200, 5, 10), _r("b", 1100, 9, 12)], budget=D(1000))
    assert best.scenario_id == "b" and "closest" in best.reasons[0]


def test_recommend_says_when_cheapest_is_also_least_waste():
    best = recommend([_r("a", 900, 5, 10), _r("b", 1000, 9, 12)], budget=None)
    assert best.scenario_id == "a"
    assert "less than the next option" in best.reasons[0]
    assert any("least waste" in r for r in best.reasons)
    assert any("fewest boxes" in r for r in best.reasons)


def test_layout_only_scenario():
    project_default = ProjectMaterial(tile=T600, breakage_pct=D(0))
    s = Scenario(
        id="d", name="Diagonal", default=ProjectMaterial(tile=T600, layout=Layout.DIAGONAL, breakage_pct=D(0)),
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip
    c = compare(doc([s]), CostSettings(), ExtrasSettings(), project_default, [])
    assert c.results[1].boxes > c.results[0].boxes  # diagonal cuts cost more tiles


def test_ties_go_to_the_current_setup():
    best = recommend(
        [_r("current", None, 5, 10, priced=False), _r("b", None, 5, 10, priced=False)], budget=None
    )
    assert best.scenario_id == "current"
    assert "No option wastes less" in best.reasons[0] and "no need to change" in best.reasons[0]
