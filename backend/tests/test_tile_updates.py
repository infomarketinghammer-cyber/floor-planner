from decimal import Decimal

from bson import ObjectId

from app.schemas.extras import ExtrasSettings, WallTiling
from app.schemas.material import MaterialOverride, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services.tile_updates import apply_updates, find_updates

TID = str(ObjectId())
OLD = TileRef(
    id=TID, name="Ivory", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4
)
GONE = TileRef(
    id=str(ObjectId()),
    name="Old wall",
    size_label="300 × 600 mm",
    length_mm=300,
    width_mm=600,
    tiles_per_box=8,
)


def library_doc(**kw) -> dict:
    doc = {
        "_id": ObjectId(TID), "name": "Ivory", "length_mm": "600", "width_mm": "600", "size_unit": "mm",
        "tiles_per_box": 4, "kind": "tile", "type": "floor",
    }  # fmt: skip
    return doc | kw


ROOMS = [
    Room(id="b", name="Bedroom"),
    Room(id="k", name="Kitchen", material=MaterialOverride(tile=OLD)),
    Room(id="t", name="Toilet", walls=WallTiling(height_mm=Decimal(2100), tile=GONE)),
]


def test_unchanged_tiles_are_not_reported():
    assert [
        u
        for u in find_updates(
            ROOMS, ProjectMaterial(tile=OLD), ExtrasSettings(), {TID: library_doc()}
        )
        if u.available
    ] == []


def test_changed_pack_size_is_reported_with_where_it_is_used():
    updates = find_updates(
        ROOMS, ProjectMaterial(tile=OLD), ExtrasSettings(), {TID: library_doc(tiles_per_box=3)}
    )
    changed = next(u for u in updates if u.tile_id == TID)
    assert changed.available and changed.used_in == ["Project default", "Kitchen"]
    assert [(c.field, c.old, c.new) for c in changed.changes] == [("tiles per box", "4", "3")]
    removed = next(u for u in updates if u.tile_id == GONE.id)
    assert not removed.available and removed.used_in == ["Toilet walls"]


def test_apply_replaces_every_copy():
    fresh = OLD.model_copy(update={"tiles_per_box": 3})
    rooms, default, extras = apply_updates(
        ROOMS, ProjectMaterial(tile=OLD), ExtrasSettings(wall_tile=OLD), {TID: fresh}
    )
    assert default.tile.tiles_per_box == 3 and extras.wall_tile.tiles_per_box == 3
    assert rooms[1].material.tile.tiles_per_box == 3
    assert rooms[2].walls.tile.id == GONE.id  # other tiles untouched
    assert ROOMS[1].material.tile.tiles_per_box == 4  # inputs not modified
