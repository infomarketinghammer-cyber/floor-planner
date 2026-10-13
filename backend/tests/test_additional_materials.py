from decimal import Decimal

from app.engine.units import LengthUnit, to_mm
from app.schemas.cost import CostSettings
from app.schemas.extras import (
    ExtrasSettings,
    Opening,
    OpeningKind,
    SkirtingSettings,
    SkirtingSource,
    SundriesSettings,
    WallTiling,
)
from app.schemas.material import (
    MaterialOverride,
    Price,
    PriceBasis,
    ProductKind,
    ProjectMaterial,
    TileRef,
)
from app.schemas.project import Room
from app.services.cost import build_cost
from app.services.estimate import build_estimate
from app.services.review import review_state
from app.services.suggestions import suggestions

FT = LengthUnit.FT
FLOOR = TileRef(
    id="f6", name="Floor", size_label="600 × 600 mm", length_mm=600, width_mm=600,
    tiles_per_box=4, tile_type="floor", thickness_mm=9,
)  # fmt: skip
ANTI = TileRef(
    id="a3", name="Anti-skid", size_label="300 × 300 mm", length_mm=300, width_mm=300,
    tiles_per_box=11, tile_type="anti_skid",
)  # fmt: skip
WALL = TileRef(
    id="w36", name="Wall", size_label="300 × 600 mm", length_mm=300, width_mm=600,
    tiles_per_box=8, tile_type="wall",
)  # fmt: skip
OAK = TileRef(
    id="oak", name="Oak", size_label="1220 × 190 mm", length_mm=1220, width_mm=190,
    tiles_per_box=8, kind=ProductKind.PLANK, material="wood",
)  # fmt: skip
CARPET = TileRef(
    id="cp", name="Carpet", size_label="25 × 4 m", length_mm=25000, width_mm=4000,
    tiles_per_box=1, kind=ProductKind.ROLL, material="carpet",
)  # fmt: skip


def ft(n) -> Decimal:
    return to_mm(str(n), FT)


def room(name, length, width, **kw) -> Room:
    return Room(
        **(
            {
                "id": name,
                "name": name,
                "confirmed": True,
                "unit": FT,
                "length_mm": ft(length),
                "width_mm": ft(width),
            }
            | kw
        )
    )


def estimate(rooms, settings=None, default=FLOOR):
    doc = {"rooms": [r.model_dump() for r in rooms]}
    state = review_state(doc)
    material = ProjectMaterial(tile=default, breakage_pct=Decimal(5))
    return state, material, build_estimate(state, material, settings)


DOOR = Opening(id="d", kind=OpeningKind.DOOR, width_mm=Decimal(750), height_mm=Decimal(2100))


# --- floors: planks and rolls -------------------------------------------------------------------


def test_plank_floor_by_area_plus_allowance():
    _, _, est = estimate([room("Bedroom", 12, 10)], default=OAK)
    r = est.rooms[0]
    assert r.kind == ProductKind.PLANK and r.method == "area"
    assert r.allowance_pct == 8
    assert r.boxes == -(-r.tiles_required // 8)
    assert any(a.key == "method_plank" for a in est.assumptions)


def test_roll_floor_in_running_metres():
    _, _, est = estimate([room("Bedroom", 12, 10)], default=CARPET)  # 3658 × 3048 mm
    r = est.rooms[0]
    assert r.kind == ProductKind.ROLL and r.method == "roll"
    assert r.boxes == 0 and r.drops == 1
    assert r.linear_mm == ft(10) + 100  # one 4 m-wide drop along the 10 ft side: less roll
    t = est.tiles[0]
    assert t.linear_mm == r.linear_mm and t.bought_area_mm2 == r.linear_mm * 4000
    assert est.totals.boxes == 0


def test_roll_priced_per_running_metre():
    state, material, est = estimate([room("Bedroom", 12, 10)], default=CARPET)
    material.price = Price(amount=Decimal(1000), basis=PriceBasis.LM)
    cost = build_cost(state, material, est, CostSettings())
    assert cost.rooms[0].cost == (est.rooms[0].linear_mm / 1000 * 1000).quantize(Decimal("0.01"))
    material.price = Price(amount=Decimal(1000), basis=PriceBasis.BOX)
    cost = build_cost(state, material, est, CostSettings())
    assert cost.rooms[0].cost is None and "running metre" in cost.warnings[0]


# --- walls --------------------------------------------------------------------------------------


def test_wall_tiles_per_room_with_openings():
    bath = room(
        "Bathroom",
        8,
        6,
        walls=WallTiling(height_mm=Decimal(2100), tile=WALL),
        openings=[DOOR],
    )
    _, _, est = estimate([bath])
    w = est.extras.walls[0]
    perimeter = 2 * (ft(8) + ft(6))
    assert w.length_mm == perimeter and w.wall_area_mm2 == perimeter * 2100
    assert w.net_area_mm2 == w.wall_area_mm2 - Decimal(750) * 2100
    assert w.boxes == -(-w.tiles_required // 8)
    assert est.extras.wall_tiles[0].boxes == w.boxes
    assert any(a.key == "walls" for a in est.assumptions)


def test_wall_tile_falls_back_to_project_default_and_warns_without_one():
    bath = room("Bathroom", 8, 6, walls=WallTiling(height_mm=Decimal(2100)))
    _, _, est = estimate([bath], ExtrasSettings(wall_tile=WALL))
    assert est.extras.walls[0].tile.id == "w36"
    _, _, est = estimate([bath])
    assert est.extras.walls == [] and "choose a wall tile" in est.extras.warnings[0]


def test_partial_wall_length_for_a_backsplash():
    kitchen = room(
        "Kitchen",
        10,
        8,
        walls=WallTiling(height_mm=Decimal(600), tile=WALL, length_mm=Decimal(3000)),
    )
    _, _, est = estimate([kitchen])
    assert est.extras.walls[0].length_mm == 3000


# --- skirting -----------------------------------------------------------------------------------


def test_skirting_cut_from_floor_tiles_leaves_out_doors_and_tiled_rooms():
    rooms = [
        room("Bedroom", 12, 10, openings=[DOOR]),
        room("Bathroom", 8, 6, walls=WallTiling(height_mm=Decimal(2100), tile=WALL)),
    ]
    settings = ExtrasSettings(skirting=SkirtingSettings(enabled=True))
    _, _, est = estimate(rooms, settings)
    sk = est.extras.skirting
    assert [r.name for r in sk.rooms] == ["Bedroom"]
    bed = sk.rooms[0]
    assert bed.run_mm == 2 * (ft(12) + ft(10)) - 750
    p = sk.products[0]
    assert p.tile.id == "f6" and p.strips_per_tile == 6 and p.piece_length_mm == 600
    assert p.tiles == -(-p.pieces // 6) and p.boxes == -(-p.tiles // 4)


def test_skirting_pieces_and_room_override():
    rooms = [
        room("Bedroom", 12, 10),
        room("Store", 5, 4, skirting=False),
    ]
    settings = ExtrasSettings(
        skirting=SkirtingSettings(
            enabled=True,
            source=SkirtingSource.PIECES,
            piece_length_mm=Decimal(1200),
            pieces_per_box=10,
            price=Price(amount=Decimal(100), basis=PriceBasis.TILE),
        )
    )
    state, material, est = estimate(rooms, settings)
    sk = est.extras.skirting
    assert [r.name for r in sk.rooms] == ["Bedroom"]
    p = sk.products[0]
    assert p.tile is None and p.boxes == -(-p.pieces // 10)
    cost = build_cost(state, material, est, CostSettings(), settings)
    line = next(x for x in cost.extras if x.key == "skirting:pieces")
    assert line.unit == "pieces" and line.amount == p.pieces * 100
    assert cost.has_prices and cost.total == line.amount


def test_wood_floor_cant_be_cut_into_skirting():
    settings = ExtrasSettings(skirting=SkirtingSettings(enabled=True))
    _, _, est = estimate([room("Bedroom", 12, 10)], settings, default=OAK)
    assert est.extras.skirting.products == []
    assert "ready-made pieces" in est.extras.warnings[0]


# --- sundries -----------------------------------------------------------------------------------


def test_sundries_cover_floor_and_wall_tiles():
    rooms = [
        room("Bedroom", 12, 10),
        room("Bathroom", 8, 6, walls=WallTiling(height_mm=Decimal(2100), tile=WALL)),
    ]
    settings = ExtrasSettings(
        sundries=SundriesSettings(enabled=True, adhesive_bag_price=Decimal(400))
    )
    state, material, est = estimate(rooms, settings)
    items = {s.key: s for s in est.extras.sundries}
    floor_area = sum(r.usable_area_mm2 for r in est.rooms)
    wall_area = est.extras.walls[0].net_area_mm2
    assert items["adhesive"].area_mm2 == floor_area + wall_area
    expected = (5 * floor_area + Decimal("3.5") * wall_area) / 1_000_000  # 600×600 floor, walls
    assert items["adhesive"].quantity == expected.quantize(Decimal("0.01"))
    assert items["adhesive"].packs == -(-int(expected * Decimal("1.1") * 100) // 2000)
    tiles = sum(r.tiles_needed for r in est.rooms) + est.extras.walls[0].tiles_needed
    assert items["spacers"].quantity == tiles
    cost = build_cost(state, material, est, CostSettings(tax_pct=Decimal(10)), settings)
    adhesive = next(x for x in cost.extras if x.key == "adhesive")
    assert adhesive.amount == items["adhesive"].packs * 400
    assert cost.tax.base == adhesive.amount  # extras are taxed like the tiles


def test_no_extras_by_default():
    _, _, est = estimate([room("Bedroom", 12, 10)])
    assert est.extras is None
    not_included = next(a for a in est.assumptions if a.key == "not_included")
    assert "skirting" in not_included.text and "wall tiles" in not_included.text


# --- suggestions --------------------------------------------------------------------------------

LIBRARY = [
    {"id": "f6", "name": "Floor", "type": "floor", "length_mm": "600", "width_mm": "600"},
    {"id": "a3", "name": "Anti 300", "type": "anti_skid", "length_mm": "300", "width_mm": "300"},
    {"id": "a6", "name": "Anti 600", "type": "anti_skid", "length_mm": "600", "width_mm": "600"},
    {"id": "w36", "name": "Wall", "type": "wall", "length_mm": "300", "width_mm": "600"},
]


def test_suggestions_by_room_type():
    rooms = [
        room("Toilet", 6, 5),
        room("Balcony", 10, 4),
        room("Kitchen", 10, 8),
        room("Bedroom", 12, 10),
        room("Bath 2", 6, 5, material=MaterialOverride(tile=ANTI)),
    ]
    found = {
        s.key: s for s in suggestions(rooms, ProjectMaterial(tile=FLOOR), ExtrasSettings(), LIBRARY)
    }
    anti = found["anti_skid"]
    assert anti.room_names == ["Toilet", "Balcony"]  # Bath 2 already has one
    assert anti.action.tile_id == "a6"  # same size as the current 600 × 600
    walls = found["bathroom_walls"]
    assert walls.room_names == ["Toilet", "Bath 2"] and walls.action.height_mm == 2100
    assert walls.action.tile_id == "w36"  # no default wall tile yet
    assert found["backsplash"].action.needs_length
    assert "wet_room_flooring" not in found


def test_wood_in_a_bathroom_is_a_warning():
    rooms = [room("Bathroom", 8, 6, material=MaterialOverride(tile=OAK))]
    found = {
        s.key: s for s in suggestions(rooms, ProjectMaterial(tile=FLOOR), ExtrasSettings(), LIBRARY)
    }
    assert found["wet_room_flooring"].severity == "warn"
    assert found["wet_room_flooring"].action.tile_id in {"a3", "a6"}


def test_suggested_wall_tile_matches_the_projects_unit_system():
    library = [
        {"id": "i", "name": "12×24 in porcelain", "type": "floor_wall", "size_unit": "in",
         "length_mm": "304.8", "width_mm": "609.6"},
        {"id": "s", "name": "3×6 in subway", "type": "wall", "size_unit": "in",
         "length_mm": "76.2", "width_mm": "152.4"},
        {"id": "m", "name": "300×600 ceramic wall", "type": "wall", "size_unit": "mm",
         "length_mm": "300", "width_mm": "600"},
    ]  # fmt: skip
    rooms = [room("Bathroom", 8, 6)]
    found = {
        s.key: s for s in suggestions(rooms, ProjectMaterial(tile=FLOOR), ExtrasSettings(), library)
    }
    assert found["bathroom_walls"].action.tile_id == "m"  # a metric project: the mm wall tile
