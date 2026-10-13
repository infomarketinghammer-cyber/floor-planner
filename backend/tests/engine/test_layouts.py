from decimal import Decimal

import pytest

from app.engine.calc import Tile, calculate_room
from app.engine.layouts import (
    Part,
    brick_offsets,
    count_brick,
    count_herringbone,
    count_rows,
    herringbone_polys,
    layout_tiles,
    straight_with_reuse,
)

D = Decimal


def rect(length, width, x=0, y=0) -> Part:
    return Part(D(x), D(y), D(length), D(width))


# --- herringbone geometry -----------------------------------------------------------------------


@pytest.mark.parametrize(("tl", "tw"), [(600, 150), (600, 300), (1200, 200), (300, 300)])
def test_herringbone_tiles_the_plane_without_gaps_or_overlaps(tl, tw):
    window = (1000.0, 1000.0, 4000.0, 3500.0)  # well inside the generated area
    polys = herringbone_polys([rect(6000, 5000)], float(tl), float(tw))
    boxes = [(min(p[0] for p in q), min(p[1] for p in q), max(p[0] for p in q), max(p[1] for p in q)) for q in polys]
    inside = [b for b in boxes if b[2] > window[0] and b[0] < window[2] and b[3] > window[1] and b[1] < window[3]]
    # No two tiles overlap.
    for i, a in enumerate(inside):
        for b in inside[i + 1 :]:
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            assert not (w > 1e-6 and h > 1e-6), (a, b)
    # Together they cover the window exactly.
    covered = sum(
        max(0, min(b[2], window[2]) - max(b[0], window[0])) * max(0, min(b[3], window[3]) - max(b[1], window[1]))
        for b in inside
    )
    assert covered == pytest.approx((window[2] - window[0]) * (window[3] - window[1]))


def test_herringbone_count_covers_the_room():
    total, cut = count_herringbone([rect(3000, 2400)], D(600), D(150))
    assert total * 600 * 150 >= 3000 * 2400  # at least the room's area of tiles
    assert 0 < cut < total


# --- brick offset -------------------------------------------------------------------------------


def test_brick_offsets_repeat():
    assert brick_offsets(D(600), D(50)) == [D(0), D(300)]
    assert brick_offsets(D(600), D("33.333333")) [:3] == [D(0), D("199.999998"), D("399.999996")]


def test_brick_half_offset_counts_and_reuse():
    # 3 m run, 600 mm tiles, rows alternate: 5 whole tiles; then 300 + 4×600 + 300.
    plain = count_brick(D(3000), D(1200), D(600), D(300), D(50), reuse=False)
    assert plain.tiles == 5 + 6 + 5 + 6  # 4 rows
    # With reuse, the 300 mm end of one offset row starts the other end: one tile per offset row.
    reused = count_brick(D(3000), D(1200), D(600), D(300), D(50), reuse=True)
    assert reused.tiles == 5 + 5 + 5 + 5
    assert reused.reused_pieces == 2


def test_count_rows_without_offset_is_a_straight_grid():
    r = count_rows(D(3100), 3, D(600), [D(0)], reuse=False)
    assert r.tiles == 6 * 3 and r.cut_pieces == 3


# --- straight with reuse ------------------------------------------------------------------------


def test_straight_reuse_halves_narrow_edges():
    tile = Tile(D(600), D(600), 4)
    # 3250 × 3000: 6 columns (last 250 wide), 5 rows exact. Edge pieces 250 wide: 2 per tile.
    plain = calculate_room(D(3250), D(3000), tile).tiles_needed
    assert plain == 30
    assert straight_with_reuse(D(3250), D(3000), D(600), D(600)) == 25 + 3


def test_straight_reuse_wide_edges_save_nothing():
    # Last column 400 wide: one piece per tile, nothing to reuse.
    assert straight_with_reuse(D(3400), D(3000), D(600), D(600)) == 30


def test_straight_reuse_corner_from_leftover():
    # 3250 × 3250: right and bottom strips of 250; 5 pieces each → 3 tiles each, one strip spare
    # for the corner.
    assert straight_with_reuse(D(3250), D(3250), D(600), D(600)) == 25 + 3 + 3


# --- drawing ------------------------------------------------------------------------------------


def test_straight_drawing_matches_the_grid_count():
    placed = layout_tiles([rect(3250, 3000)], D(600), D(600), "straight")
    assert len(placed) == calculate_room(D(3250), D(3000), Tile(D(600), D(600), 4)).tiles_needed
    assert sum(p.cut for p in placed) == 5  # the 250 mm column


def test_drawing_of_an_l_shaped_room():
    parts = [rect(3000, 3000), rect(1200, 1800, x=3000, y=0)]
    placed = layout_tiles(parts, D(600), D(600), "straight")
    assert len(placed) == 25 + 6 and not any(p.cut for p in placed)


def test_diagonal_and_brick_drawings_have_cut_edges():
    for layout in ("diagonal", "brick", "herringbone"):
        placed = layout_tiles([rect(3000, 2400)], D(600), D(300), layout)
        assert any(p.cut for p in placed) and any(not p.cut for p in placed), layout
