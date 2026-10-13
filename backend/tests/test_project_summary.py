from decimal import Decimal

from app.engine.units import LengthUnit, to_mm
from app.schemas.material import MaterialOverride, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services.project_summary import summarize

TILE = TileRef(
    id="t1", name="600×600", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4
)


def room(**kwargs) -> Room:
    defaults = {
        "id": "r",
        "name": "Room",
        "length_mm": to_mm(10, LengthUnit.FT),
        "width_mm": to_mm(10, LengthUnit.FT),
        "confirmed": True,
        "material": MaterialOverride(tile=TILE),
    }
    return Room(**(defaults | kwargs))


def test_empty_project_needs_no_attention():
    summary = summarize([], default=None)
    assert summary.room_count == 0
    assert summary.total_area_mm2 == 0
    assert not summary.needs_attention


def test_total_area_excludes_skipped_rooms():
    rooms = [room(), room(skipped=True)]
    summary = summarize(rooms, default=None)
    assert summary.room_count == 2
    assert summary.total_area_mm2 == to_mm(10, LengthUnit.FT) ** 2
    assert not summary.needs_attention


def test_unconfirmed_rooms_need_attention_unless_skipped():
    assert summarize([room(confirmed=False)], default=None).needs_attention
    skipped = summarize([room(confirmed=False, skipped=True)], default=None)
    assert skipped.unconfirmed_rooms == 0
    assert not skipped.needs_attention


def test_project_default_tile_covers_rooms_without_override():
    rooms = [room(material=MaterialOverride())]
    assert summarize(rooms, default=None).rooms_missing_tile == 1
    assert summarize(rooms, default=ProjectMaterial(tile=TILE)).rooms_missing_tile == 0


def test_missing_size_is_flagged_and_excluded_from_area():
    summary = summarize([room(width_mm=None), room()], default=None)
    assert summary.rooms_missing_size == 1
    assert summary.total_area_mm2 == to_mm(10, LengthUnit.FT) ** 2
    assert summary.needs_attention


def test_dimensions_survive_mongo_string_round_trip():
    stored = room(length_mm=Decimal("3352.8")).model_dump()
    assert stored["length_mm"] == "3352.8"
    assert Room.model_validate(stored).length_mm == Decimal("3352.8")
