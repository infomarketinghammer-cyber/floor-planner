from decimal import Decimal

from app.engine.calc import Tile, calculate_room
from app.engine.layouts import Part, count_brick, count_herringbone
from app.schemas.extras import ExtrasSettings, SkirtingSettings
from app.schemas.material import Layout, MaterialOverride, ProjectMaterial, TileRef
from app.schemas.project import Room, RoomPart
from app.services.estimate import build_estimate, estimate_room
from app.services.review import review_state
from app.services.tile_advice import advise

D = Decimal
T600 = TileRef(
    id="t6", name="600", size_label="600 × 600 mm", length_mm=600, width_mm=600,
    tiles_per_box=4, tile_type="floor",
)  # fmt: skip
T800 = TileRef(
    id="t8", name="800", size_label="800 × 800 mm", length_mm=800, width_mm=800,
    tiles_per_box=3, tile_type="floor",
)  # fmt: skip
PLANK = TileRef(
    id="p", name="Plank tile", size_label="600 × 150 mm", length_mm=600, width_mm=150,
    tiles_per_box=12, tile_type="floor",
)  # fmt: skip


def room(name="Hall", length=3250, width=3000, **kw) -> Room:
    return Room(
        **(
            {
                "id": name,
                "name": name,
                "confirmed": True,
                "unit": "mm",
                "length_mm": None if length is None else D(length),
                "width_mm": None if width is None else D(width),
            }
            | kw
        )
    )


def default(tile=T600, **kw) -> ProjectMaterial:
    return ProjectMaterial(tile=tile, breakage_pct=D(0), **kw)


def test_straight_rooms_unchanged_and_report_cuts_and_reuse():
    r = estimate_room(room(), default())
    assert r.tiles_needed == calculate_room(D(3250), D(3000), Tile(D(600), D(600), 4)).tiles_needed
    assert r.cut_tiles == 5 and r.tiles_if_reused == 28 and not r.reuse_applied


def test_reuse_offcuts_setting_lowers_the_count():
    r = estimate_room(room(), default(reuse_offcuts=True))
    assert r.tiles_needed == 28 and r.reuse_applied
    assert "offcuts" in r.method_reason


def test_brick_layout():
    r = estimate_room(
        room(length=3000, width=1200, material=MaterialOverride(layout=Layout.BRICK)),
        default(PLANK),
    )
    expected = count_brick(D(3000), D(1200), D(600), D(150), D(50), reuse=False)
    assert r.method == "grid" and r.layout == Layout.BRICK
    assert r.tiles_needed == expected.tiles and r.cut_tiles == expected.cut_pieces
    assert r.tiles_if_reused < r.tiles_needed


def test_herringbone_layout():
    r = estimate_room(
        room(length=3000, width=2400, material=MaterialOverride(layout=Layout.HERRINGBONE)),
        default(PLANK),
    )
    total, cut = count_herringbone([Part(D(0), D(0), D(3000), D(2400))], D(600), D(150))
    assert r.tiles_needed == total and r.cut_tiles == cut and r.tiles_if_reused is None


def test_split_room_counts_each_rectangle():
    parts = [
        RoomPart(id="a", label="Main", length_mm=D(3000), width_mm=D(3000)),
        RoomPart(id="b", label="Nook", length_mm=D(1200), width_mm=D(1800), x_mm=D(3000)),
    ]
    shaped = room(length=None, width=None, parts=parts)
    assert shaped.floor_area_mm2 == D(3000) * 3000 + D(1200) * 1800
    r = estimate_room(shaped, default())
    assert r.tiles_needed == 25 + 6
    assert r.room_area_mm2 == shaped.floor_area_mm2
    doc = {"rooms": [shaped.model_dump()]}
    est = build_estimate(review_state(doc), default())
    assert est.ready and any(a.key == "split_rooms" for a in est.assumptions)


def test_split_room_skirting_needs_a_perimeter():
    parts = [
        RoomPart(id="a", length_mm=D(3000), width_mm=D(3000)),
        RoomPart(id="b", length_mm=D(1200), width_mm=D(1800), x_mm=D(3000)),
    ]
    settings = ExtrasSettings(skirting=SkirtingSettings(enabled=True))
    doc = {"rooms": [room(length=None, width=None, parts=parts).model_dump()]}
    est = build_estimate(review_state(doc), default(), settings)
    assert "perimeter" in est.extras.warnings[0]
    doc = {
        "rooms": [room(length=None, width=None, parts=parts, perimeter_mm=D(15600)).model_dump()]
    }
    est = build_estimate(review_state(doc), default(), settings)
    assert est.extras.skirting.rooms[0].run_mm == 15600


def test_tile_advice_finds_a_less_wasteful_size():
    # 3200 × 3200 fits 800 tiles exactly; 600 tiles leave 200 mm slivers.
    rooms = [room("Bedroom 1", 3200, 3200)]
    doc = {"rooms": [r.model_dump() for r in rooms]}
    state = review_state(doc)
    est = build_estimate(state, default())
    library = [
        {
            "_id": "t6",
            "name": "600",
            "length_mm": "600",
            "width_mm": "600",
            "size_unit": "mm",
            "tiles_per_box": 4,
            "type": "floor",
        },
        {
            "_id": "t8",
            "name": "800",
            "length_mm": "800",
            "width_mm": "800",
            "size_unit": "mm",
            "tiles_per_box": 3,
            "type": "floor",
        },
        {
            "_id": "w",
            "name": "Wall",
            "length_mm": "300",
            "width_mm": "600",
            "size_unit": "mm",
            "tiles_per_box": 8,
            "type": "wall",
        },
    ]
    advice = advise(state.rooms, default(), est, library)
    a = advice.rooms[0]
    assert a.best.tile.id == "t8" and a.best.extra_pct < a.current.extra_pct
    assert all(o.tile.id != "w" for o in a.alternatives)  # wall tiles aren't floor options
    assert advice.project.best.tile.id == "t8"
    assert "Bedroom 1" in advice.summary and "800 × 800 mm" in advice.summary
