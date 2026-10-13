from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.engine.units import LengthUnit
from app.schemas.tile import TileInput
from app.services.tiles import _PRESETS, resolve, size_label


def tile(**kw) -> TileInput:
    return TileInput(**({"name": "T", "length": "600", "width": "600", "tiles_per_box": 4} | kw))


def test_metric_tile():
    fields = resolve(tile())
    assert (fields["length_mm"], fields["width_mm"], fields["tiles_per_box"]) == ("600", "600", 4)


@pytest.mark.parametrize(
    "length,width,unit,expected",
    [
        ("24", "24", LengthUnit.IN, ("609.6", "609.6")),
        ("2", "2", LengthUnit.FT, ("609.6", "609.6")),
        ("2'", '24"', LengthUnit.MM, ("609.6", "609.6")),  # explicit marks beat the unit
        ("60", "120", LengthUnit.CM, ("600", "1200")),
    ],
)
def test_sizes_in_any_unit_are_exact_mm(length, width, unit, expected):
    fields = resolve(tile(length=length, width=width, size_unit=unit))
    assert (Decimal(fields["length_mm"]), Decimal(fields["width_mm"])) == tuple(
        Decimal(e) for e in expected
    )


def test_coverage_alone_gives_tiles_per_box():
    fields = resolve(tile(tiles_per_box=None, coverage_per_box_sqm=Decimal("1.44")))
    assert fields["tiles_per_box"] == 4


def test_rounded_coverage_on_the_box_is_accepted():
    # 12×12 in × 10 = 0.929 m²; boxes often say 0.93
    fields = resolve(
        tile(
            length="12",
            width="12",
            size_unit=LengthUnit.IN,
            tiles_per_box=None,
            coverage_per_box_sqm=Decimal("0.93"),
        )
    )
    assert fields["tiles_per_box"] == 10


@pytest.mark.parametrize(
    "kw,message",
    [
        ({"tiles_per_box": None}, "tiles per box or the coverage"),
        ({"tiles_per_box": None, "coverage_per_box_sqm": Decimal("1.6")}, "isn't a whole number"),
        ({"coverage_per_box_sqm": Decimal("2.0")}, "4 tiles cover 1.44 m², not 2"),
        ({"length": "20"}, "between 50 mm and 3.6 m"),
        ({"length": "6", "size_unit": LengthUnit.M}, "between 50 mm and 3.6 m"),
        ({"length": "abc"}, "not a length"),
        ({"size_unit": LengthUnit.FT_IN}, "mm, cm, m, inches or feet"),
    ],
)
def test_invalid_tiles(kw, message):
    with pytest.raises(HTTPException) as exc:
        resolve(tile(**kw))
    assert exc.value.status_code == 422 and message in exc.value.detail


def test_size_labels():
    assert size_label(Decimal(600), Decimal(1200), LengthUnit.MM) == "600 × 1200 mm"
    assert size_label(Decimal("609.6"), Decimal("609.6"), LengthUnit.FT) == "2 × 2 ft"
    assert size_label(Decimal("76.2"), Decimal("152.4"), LengthUnit.IN) == "3 × 6 in"


def test_all_presets_are_valid_and_cover_expected_regions():
    regions = set()
    for name, length, width, unit, thick, per_box, type_, finish, material, region in _PRESETS:
        fields = resolve(
            TileInput(
                name=name,
                length=length,
                width=width,
                size_unit=unit,
                thickness_mm=Decimal(thick),
                tiles_per_box=per_box,
                type=type_,
                finish=finish,
                material=material,
                regions=[region],
            )
        )
        assert fields["tiles_per_box"] == per_box
        regions.add(region)
    assert regions == {"india", "imperial"}
    names = {p[0] for p in _PRESETS}
    # The PRD's examples are all present.
    assert {
        "600×600 vitrified floor",
        "800×800 vitrified floor",
        "2×2 ft (24×24 in) floor",
        "1×1 ft (12×12 in) floor",
    } <= names
