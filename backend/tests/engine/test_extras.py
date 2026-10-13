from decimal import Decimal

import pytest

from app.engine.calc import Excluded, Tile, calculate_room
from app.engine.extras import (
    calculate_roll,
    calculate_roll_by_area,
    calculate_walls,
    default_adhesive_rate,
    grout_kg_per_m2,
    packs,
    skirting_pieces,
    strips_per_tile,
)

D = Decimal
T300x600 = Tile(D(300), D(600), 8)


# --- roll flooring ------------------------------------------------------------------------------


def test_roll_picks_the_direction_needing_less_roll():
    # 5 m × 3.5 m room, 4 m roll: across 3.5 m one drop of 5.1 m beats two drops of 3.6 m.
    r = calculate_roll(D(5000), D(3500), D(4000))
    assert (r.drops, r.drop_length_mm, r.along) == (1, D(5100), "length")
    assert r.linear_mm == D(5100)
    assert r.bought_area_mm2 == D(5100) * D(4000)
    assert r.extra_area_mm2 == r.bought_area_mm2 - D(5000) * D(3500)


def test_roll_wider_room_needs_several_drops():
    r = calculate_roll(D(6000), D(5000), D(4000))  # 2 drops either way: 2×5.1 m < 2×6.1 m
    assert (r.drops, r.drop_length_mm, r.along) == (2, D(5100), "width")
    assert r.linear_mm == D(10200)


def test_roll_by_area_rounds_up_to_10cm():
    r = calculate_roll_by_area(D(10_000_000), D(4000))  # 10 m² + 15% = 11.5 m² / 4 m = 2.875 m
    assert r.linear_mm == D(2900) and r.drops is None


# --- walls --------------------------------------------------------------------------------------


def test_walls_grid_per_wall_and_best_orientation():
    # Bathroom 2400 × 1800, tiled to 2100 high with 300 × 600 tiles.
    walls = [D(2400), D(1800), D(2400), D(1800)]
    r = calculate_walls(walls, D(2100), T300x600)
    # Tile 600 wide × 300 tall: 7 rows; walls 4 + 3 + 4 + 3 = 14 columns → 98 tiles.
    # Tile 300 wide × 600 tall: 4 rows (2400 > 2100); 8 + 6 + 8 + 6 = 28 columns → 112 tiles.
    assert r.tiles_needed == 98 and r.rows == 7
    assert r.room_area_mm2 == D(8400) * D(2100)


def test_wall_openings_remove_only_certain_tiles():
    walls = [D(2400), D(1800), D(2400), D(1800)]
    base = calculate_walls(walls, D(2100), T300x600)
    # A 750 mm door can't be sure to hold a whole 600 mm-wide tile: area drops, tiles don't.
    door = calculate_walls(walls, D(2100), T300x600, openings=(Excluded(D(750), D(2100)),))
    assert door.usable_area_mm2 == base.usable_area_mm2 - D(750) * D(2100)
    assert door.tiles_needed == base.tiles_needed
    # A 1500 × 1200 window always holds (2 - 1) × (4 - 1) = 3 whole 600 × 300 tiles.
    window = calculate_walls(walls, D(2100), T300x600, openings=(Excluded(D(1500), D(1200)),))
    assert base.tiles_needed - window.tiles_needed == 3


def test_walls_add_breakage_and_boxes():
    r = calculate_walls([D(3000)], D(1200), T300x600, breakage_pct=D(5))
    assert r.tiles_needed == 20  # 5 columns × 4 rows (tile 600 wide, 300 tall)
    assert r.buffer_tiles == 1 and r.boxes == 3


def test_walls_reject_openings_covering_everything():
    with pytest.raises(ValueError):
        calculate_walls([D(1000)], D(1000), T300x600, openings=(Excluded(D(1000), D(1000)),))


# --- skirting -----------------------------------------------------------------------------------


def test_skirting_pieces_with_breakage():
    s = skirting_pieces(D(12_000), D(1200), D(5))  # 10 pieces + 5% → 10.5 → 11
    assert s.pieces == 11
    assert skirting_pieces(D(0), D(1200), D(5)).pieces == 0


def test_strips_cut_from_a_floor_tile():
    assert strips_per_tile(Tile(D(600), D(600), 4), D(100)) == (6, D(600))
    assert strips_per_tile(Tile(D(600), D(1200), 2), D(100)) == (6, D(1200))
    assert strips_per_tile(Tile(D(300), D(300), 11), D(100)) == (3, D(300))


# --- sundries -----------------------------------------------------------------------------------


def test_adhesive_rate_by_tile_size():
    assert default_adhesive_rate(Tile(D(300), D(300), 11)) == 4
    assert default_adhesive_rate(Tile(D(600), D(600), 4)) == 5
    assert default_adhesive_rate(Tile(D(800), D(800), 3)) == 6
    assert default_adhesive_rate(T300x600, wall=True) == D("3.5")


def test_grout_formula():
    # 600 × 600, 2 mm joint, 9 mm deep: 1200/360000 × 2 × 9 × 1.6 = 0.096 kg/m²
    assert grout_kg_per_m2(Tile(D(600), D(600), 4), D(2), D(9)) == D("0.096")


def test_packs_round_up_with_waste():
    assert packs(D(40), D(20)) == 2
    assert packs(D(40), D(20), D(10)) == 3
    assert packs(D(0), D(20)) == 0


def test_floor_grid_still_works():  # extras reuse calc's helpers
    assert calculate_room(D(3000), D(3000), Tile(D(600), D(600), 4)).tiles_needed == 25
