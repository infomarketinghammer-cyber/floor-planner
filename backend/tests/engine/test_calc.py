from decimal import Decimal

import pytest

from app.engine.calc import (
    AREA_ONLY_ALLOWANCE_PCT,
    DIAGONAL_ALLOWANCE_PCT,
    Excluded,
    Method,
    Tile,
    calculate_by_area,
    calculate_room,
    equivalent_tile_count,
)
from app.engine.units import LengthUnit, feet_inches_to_mm, mm2_to_sqft, to_mm

FT = LengthUnit.FT


def ft_tile(length: str, width: str, per_box: int = 1) -> Tile:
    return Tile(to_mm(length, FT), to_mm(width, FT), per_box)


def test_prd_acceptance_11_by_9_5_ft_with_2x2_tiles():
    """PRD 11: 11 x 9.5 ft room with 2x2 ft tiles -> 30 grid tiles, 15.5 sq ft cut waste."""
    result = calculate_room(to_mm("11", FT), to_mm("9.5", FT), ft_tile("2", "2"))
    assert (result.columns, result.rows) == (6, 5)
    assert result.grid_tiles == 30
    assert mm2_to_sqft(result.cut_waste_mm2) == Decimal("15.5")


def test_prd_acceptance_area_equivalence():
    """PRD 11: 20 tiles of 2x2 ft convert to 80 tiles of 1x1 ft."""
    assert equivalent_tile_count(20, ft_tile("2", "2"), ft_tile("1", "1")) == 80


def test_exact_fit_has_no_float_drift():
    # 0.9 m / 0.3 m is 3.0000000000000004 in float; must be exactly 3 columns.
    tile = Tile(to_mm("0.3", LengthUnit.M), to_mm("0.3", LengthUnit.M), 10)
    result = calculate_room(to_mm("0.9", LengthUnit.M), to_mm("0.6", LengthUnit.M), tile)
    assert (result.columns, result.rows, result.grid_tiles) == (3, 2, 6)
    assert result.cut_waste_mm2 == 0


def test_metric_room_with_buffer_and_box_rounding():
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    result = calculate_room(Decimal(3600), Decimal(3000), tile, breakage_pct=Decimal(5))
    assert result.grid_tiles == 30  # 6 x 5, exact fit
    assert result.buffer_tiles == 2  # ceil(1.5)
    assert result.tiles_required == 32
    assert result.boxes == 8
    assert result.tiles_bought == 32
    assert result.extra_area_mm2 == 2 * tile.area_mm2


@pytest.mark.parametrize(
    "required_tiles,per_box,expected_boxes", [(30, 4, 8), (32, 4, 8), (1, 6, 1)]
)
def test_boxes_always_round_up(required_tiles, per_box, expected_boxes):
    side = Decimal(100)
    tile = Tile(side, side, per_box)
    result = calculate_room(side * required_tiles, side, tile)
    assert result.tiles_required == required_tiles
    assert result.boxes == expected_boxes


def test_feet_inches_conversion():
    assert feet_inches_to_mm(12, 6) == Decimal("3810.0")


def test_float_inputs_are_rejected():
    with pytest.raises(TypeError):
        to_mm(1.5, FT)  # type: ignore[arg-type]


@pytest.mark.parametrize("length,width", [(Decimal(0), Decimal(1)), (Decimal(1), Decimal(-1))])
def test_invalid_room_dimensions(length, width):
    with pytest.raises(ValueError):
        calculate_room(length, width, Tile(Decimal(600), Decimal(600), 4))


# --- Exclusions (grid method) ---------------------------------------------------------------


def test_exclusion_subtracts_only_tiles_it_certainly_covers():
    # 2400×1800 mm bathroom, 300×300 tiles; a 1800×900 bathtub covers at least
    # (6-1) × (3-1) = 10 whole tiles wherever it sits on the grid.
    tile = Tile(Decimal(300), Decimal(300), tiles_per_box=11)
    tub = Excluded(Decimal(1800), Decimal(900))
    result = calculate_room(Decimal(2400), Decimal(1800), tile, exclusions=(tub,))
    assert (result.grid_tiles, result.excluded_tiles, result.tiles_needed) == (48, 10, 38)
    assert result.usable_area_mm2 == Decimal(2400 * 1800 - 1800 * 900)
    assert result.cut_waste_mm2 == 38 * tile.area_mm2 - result.usable_area_mm2  # 0.72 m²


def test_narrow_exclusion_may_straddle_rows_so_covers_nothing_for_sure():
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    cabinet = Excluded(Decimal(2400), Decimal(600))  # one tile deep: can sit across two rows
    result = calculate_room(Decimal(3600), Decimal(3000), tile, exclusions=(cabinet,))
    assert result.excluded_tiles == 0
    assert result.usable_area_mm2 == Decimal(3600 * 3000 - 2400 * 600)


def test_exclusion_uses_the_more_conservative_orientation():
    tile = Tile(Decimal(300), Decimal(600), tiles_per_box=8)
    # As given: (4-1)×(1-1)=0; rotated: (2-1)×(2-1)=1 → keep 0.
    result = calculate_room(
        Decimal(3000), Decimal(3000), tile, exclusions=(Excluded(Decimal(1200), Decimal(600)),)
    )
    assert result.excluded_tiles == 0


def test_exclusion_quantity_multiplies():
    tile = Tile(Decimal(300), Decimal(300), tiles_per_box=11)
    columns = Excluded(Decimal(900), Decimal(900), quantity=3)  # (3-1)×(3-1)=4 each
    assert (
        calculate_room(Decimal(6000), Decimal(6000), tile, exclusions=(columns,)).excluded_tiles
        == 12
    )


def test_exclusions_covering_the_room_are_rejected():
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    with pytest.raises(ValueError, match="whole room"):
        calculate_room(
            Decimal(1000), Decimal(1000), tile, exclusions=(Excluded(Decimal(1000), Decimal(1000)),)
        )


# --- Percentage fallback ----------------------------------------------------------------------


def test_diagonal_layout_by_area_with_allowance():
    # 3.6 × 3.0 m = 10.8 m²; 600×600 = 0.36 m²; +15% → 34.5 → 35 tiles.
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    result = calculate_by_area(
        Decimal(3600 * 3000), tile, DIAGONAL_ALLOWANCE_PCT, breakage_pct=Decimal(5)
    )
    assert result.method == Method.AREA and result.columns is None
    assert result.tiles_needed == 35
    assert result.buffer_tiles == 2  # ceil(1.75)
    assert (result.tiles_required, result.boxes, result.tiles_bought) == (37, 10, 40)
    assert result.extra_area_mm2 == 40 * tile.area_mm2 - Decimal(3600 * 3000)  # 3.6 m²


def test_area_only_room():
    # 15 m² odd-shaped room, 800×800 (0.64 m², 3/box), +10% → 25.78 → 26 tiles → 9 boxes.
    tile = Tile(Decimal(800), Decimal(800), tiles_per_box=3)
    result = calculate_by_area(Decimal(15_000_000), tile, AREA_ONLY_ALLOWANCE_PCT)
    assert (result.tiles_needed, result.boxes, result.tiles_bought) == (26, 9, 27)


def test_area_method_subtracts_excluded_area():
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    result = calculate_by_area(
        Decimal(10_800_000), tile, Decimal(0), excluded_area_mm2=Decimal(1_440_000)
    )
    assert result.usable_area_mm2 == Decimal(9_360_000)
    assert result.tiles_needed == 26  # 9.36 / 0.36


@pytest.mark.parametrize("area,allowance", [(Decimal(0), Decimal(10)), (Decimal(100), Decimal(-1))])
def test_invalid_area_inputs(area, allowance):
    with pytest.raises(ValueError):
        calculate_by_area(area, Tile(Decimal(600), Decimal(600), 4), allowance)


def test_area_and_grid_agree_for_exact_fit_rooms_with_no_allowance():
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=4)
    grid = calculate_room(Decimal(3600), Decimal(3000), tile)
    area = calculate_by_area(Decimal(3600 * 3000), tile, Decimal(0))
    assert grid.tiles_needed == area.tiles_needed == 30


# --- Waste breakdown (PRD 4.8) --------------------------------------------------------------


def test_waste_breakdown_on_the_prd_room():
    tile = Tile(to_mm("2", FT), to_mm("2", FT), tiles_per_box=4)
    r = calculate_room(to_mm("11", FT), to_mm("9.5", FT), tile, breakage_pct=Decimal(5))
    assert mm2_to_sqft(r.cut_waste_mm2) == Decimal("15.5")
    assert mm2_to_sqft(r.buffer_area_mm2) == Decimal(8)  # 2 tiles × 4 sq ft
    assert (r.rounding_tiles, r.rounding_area_mm2) == (0, 0)  # 32 tiles = exactly 8 boxes
    assert mm2_to_sqft(r.extra_area_mm2) == Decimal("23.5")
    assert round(r.cut_waste_pct, 2) == Decimal("14.83")  # 15.5 / 104.5


@pytest.mark.parametrize("per_box", [1, 3, 4, 7, 11])
@pytest.mark.parametrize("diagonal", [False, True])
def test_extra_is_exactly_cut_waste_plus_buffer_plus_rounding(per_box, diagonal):
    tile = Tile(Decimal(600), Decimal(600), tiles_per_box=per_box)
    if diagonal:
        r = calculate_by_area(Decimal(3700 * 2900), tile, DIAGONAL_ALLOWANCE_PCT, Decimal(7))
    else:
        r = calculate_room(Decimal(3700), Decimal(2900), tile, Decimal(7))
    assert r.extra_area_mm2 == r.cut_waste_mm2 + r.buffer_area_mm2 + r.rounding_area_mm2
    assert r.rounding_tiles == r.boxes * per_box - r.tiles_required >= 0
