"""Tile layouts and their geometry (PRD 4.16): brick-offset, herringbone, offcut reuse, and the
tile-by-tile drawing of a room with cut tiles marked.

Pure functions. Rooms are one or more axis-aligned rectangles (a non-rectangular room split into
rectangles); lengths are Decimal millimetres, geometry runs in float only for drawing and for
classifying herringbone and diagonal tiles, where exact decimals add nothing.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from app.engine.calc import ceil_int, floor_int
from app.engine.extras import calculate_roll

EPS = 1e-6
MAX_DRAWN_TILES = 6000  # beyond this a drawing is unreadable anyway


@dataclass(frozen=True)
class Part:
    """One rectangle of a room, placed at (x, y) from the room's top-left corner."""

    x: Decimal
    y: Decimal
    length: Decimal  # along x
    width: Decimal  # along y

    @property
    def area(self) -> Decimal:
        return self.length * self.width


# --- Brick offset (running bond) ----------------------------------------------------------------


@dataclass(frozen=True)
class RowCount:
    tiles: int  # tiles cut or laid
    cut_pieces: int
    reused_pieces: int  # cut pieces taken from offcuts instead of a new tile


def _take(pool: list[Decimal], need: Decimal) -> bool:
    """Use the smallest offcut that is long enough; put what's left back. True if found."""
    fits = [p for p in pool if p >= need - Decimal("0.000001")]
    if not fits:
        return False
    best = min(fits)
    pool.remove(best)
    if best - need > 0:
        pool.append(best - need)
    return True


def count_rows(
    run: Decimal, rows: int, tile_length: Decimal, offsets: list[Decimal], reuse: bool
) -> RowCount:
    """Tiles to lay `rows` rows of length `run`, row i starting `offsets[i]` into a tile (0 =
    starts with a whole tile). With `reuse`, a piece cut off one row end can start another row
    if it's long enough: the usual practice for brick and plank layouts."""
    pool: list[Decimal] = []
    tiles = cuts = reused = 0
    for i in range(rows):
        s = offsets[i % len(offsets)] % tile_length
        pieces: list[Decimal] = []
        x = Decimal(0)
        if s > 0:
            first = min(tile_length - s, run)
            pieces.append(first)
            x = first
        while x < run:
            piece = min(tile_length, run - x)
            pieces.append(piece)
            x += piece
        for p in pieces:
            if p >= tile_length:
                tiles += 1
                continue
            cuts += 1
            if reuse and _take(pool, p):
                reused += 1
                continue
            tiles += 1
            if reuse:
                pool.append(tile_length - p)
    return RowCount(tiles, cuts, reused)


def brick_offsets(tile_length: Decimal, offset_pct: Decimal) -> list[Decimal]:
    """Row start offsets for a running bond: each row shifted by offset% of a tile."""
    step = tile_length * offset_pct / 100
    if step <= 0:
        return [Decimal(0)]
    out, s = [], Decimal(0)
    for _ in range(64):  # the pattern repeats; 64 rows covers any sensible offset
        out.append(s % tile_length)
        s += step
        if s % tile_length == 0:
            break
    return out


def count_brick(
    length: Decimal, width: Decimal, tile_length: Decimal, tile_width: Decimal,
    offset_pct: Decimal, reuse: bool,
) -> RowCount:  # fmt: skip
    """Brick-offset over one rectangle. Rows run along the room's length."""
    rows = ceil_int(width / tile_width)
    return count_rows(length, rows, tile_length, brick_offsets(tile_length, offset_pct), reuse)


# --- Straight grid with offcut reuse ------------------------------------------------------------


def straight_with_reuse(length: Decimal, width: Decimal, tl: Decimal, tw: Decimal) -> int:
    """Tiles for a straight grid when edge offcuts are reused: a strip cut for one edge tile
    can make several edge pieces if they're narrow enough (a 600 mm tile gives two 250 mm
    pieces), and a leftover strip can make the corner piece."""
    cols, rows = ceil_int(length / tl), ceil_int(width / tw)
    rx, ry = length - (cols - 1) * tl, width - (rows - 1) * tw  # last column / row sizes
    cut_x, cut_y = rx < tl, ry < tw
    full_cols = cols - 1 if cut_x else cols
    full_rows = rows - 1 if cut_y else rows
    tiles = full_cols * full_rows
    spare = False  # a leftover strip big enough for the corner
    if cut_x:
        per_tile = max(1, floor_int(tl / rx))
        tiles += ceil_int(Decimal(full_rows) / per_tile)
        spare = spare or full_rows % per_tile != 0
    if cut_y:
        per_tile = max(1, floor_int(tw / ry))
        tiles += ceil_int(Decimal(full_cols) / per_tile)
        spare = spare or full_cols % per_tile != 0
    if cut_x and cut_y and not spare:
        tiles += 1
    return tiles


# --- Geometry for drawing and for herringbone / diagonal counts ---------------------------------

Point = tuple[float, float]


def _rects(parts: list[Part]) -> list[tuple[float, float, float, float]]:
    return [(float(p.x), float(p.y), float(p.x + p.length), float(p.y + p.width)) for p in parts]


def _overlap_rect(poly: list[Point], rect: tuple[float, float, float, float]) -> bool:
    """Separating-axis test: does a convex polygon overlap an axis-aligned rectangle with
    positive area?"""
    x0, y0, x1, y1 = rect
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    if max(xs) <= x0 + EPS or min(xs) >= x1 - EPS or max(ys) <= y0 + EPS or min(ys) >= y1 - EPS:
        return False
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        nx, ny = by - ay, ax - bx  # edge normal
        proj_p = [nx * px + ny * py for px, py in poly]
        proj_r = [nx * cx + ny * cy for cx, cy in corners]
        if max(proj_p) <= min(proj_r) + EPS or max(proj_r) <= min(proj_p) + EPS:
            return False
    return True


def _inside(point: Point, rects) -> bool:
    x, y = point
    return any(x0 - EPS <= x <= x1 + EPS and y0 - EPS <= y <= y1 + EPS for x0, y0, x1, y1 in rects)


def _axis_area(poly: list[Point], rect) -> float:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    w = min(max(xs), rect[2]) - max(min(xs), rect[0])
    h = min(max(ys), rect[3]) - max(min(ys), rect[1])
    return max(0.0, w) * max(0.0, h)


@dataclass(frozen=True)
class Placed:
    points: list[Point]  # tile corners, clockwise
    cut: bool


def classify(polys: list[list[Point]], parts: list[Part], axis_aligned: bool) -> list[Placed]:
    """Keep tiles that touch the room; mark the ones that need cutting."""
    rects = _rects(parts)
    out = []
    for poly in polys:
        if not any(_overlap_rect(poly, r) for r in rects):
            continue
        if axis_aligned:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            area = (max(xs) - min(xs)) * (max(ys) - min(ys))
            covered = sum(_axis_area(poly, r) for r in rects)
            cut = covered < area - 1e-3
        else:
            cut = not all(_inside(p, rects) for p in poly)
        out.append(Placed(poly, cut))
    return out


def _bounds(parts: list[Part]) -> tuple[float, float, float, float]:
    rects = _rects(parts)
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def straight_polys(parts: list[Part], tl: float, tw: float, offsets: list[float] | None = None):
    """Rows of tiles from the room's top-left corner; row i shifted left by offsets[i]."""
    x0, y0, x1, y1 = _bounds(parts)
    polys = []
    row = 0
    y = y0
    while y < y1 - EPS:
        s = (offsets[row % len(offsets)] % tl) if offsets else 0.0
        x = x0 - s
        while x < x1 - EPS:
            polys.append([(x, y), (x + tl, y), (x + tl, y + tw), (x, y + tw)])
            x += tl
        y += tw
        row += 1
    return polys


def herringbone_polys(parts: list[Part], tl: float, tw: float):
    """Herringbone (zigzag) of tl × tw tiles: lattice vectors (tw, tw) and (tl, −tl), with a
    horizontal tile at (0, 0) and a vertical one at (0, tw) in each cell."""
    x0, y0, x1, y1 = _bounds(parts)
    span = (x1 - x0) + (y1 - y0) + 2 * tl
    n_a = int(span / tw) + 4
    n_b = int(span / tl) + 4
    polys = []
    for i in range(-n_a, n_a + 1):
        for j in range(-n_b, n_b + 1):
            ox = x0 + i * tw + j * tl
            oy = y0 + i * tw - j * tl
            if ox > x1 + tl or oy > y1 + tl or ox < x0 - 2 * tl or oy < y0 - 2 * tl:
                continue
            polys.append([(ox, oy), (ox + tl, oy), (ox + tl, oy + tw), (ox, oy + tw)])
            vx, vy = ox, oy + tw
            polys.append([(vx, vy), (vx + tw, vy), (vx + tw, vy + tl), (vx, vy + tl)])
    return polys


def diagonal_polys(parts: list[Part], tl: float, tw: float):
    """The grid turned 45°, starting from the room's top-left corner."""
    x0, y0, x1, y1 = _bounds(parts)
    c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
    span = math.hypot(x1 - x0, y1 - y0) + 2 * max(tl, tw)
    n_u, n_v = int(span / tl) + 2, int(span / tw) + 2
    polys = []
    for i in range(-n_u, n_u + 1):
        for j in range(-n_v, n_v + 1):
            corners = [
                (i * tl, j * tw),
                ((i + 1) * tl, j * tw),
                ((i + 1) * tl, (j + 1) * tw),
                (i * tl, (j + 1) * tw),
            ]
            pts = [(x0 + u * c - v * s, y0 + u * s + v * c) for u, v in corners]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
            polys.append(pts)
    return polys


def count_herringbone(parts: list[Part], tl: Decimal, tw: Decimal) -> tuple[int, int]:
    """(tiles touching the room, of which cut). Each cut tile counts as a whole tile."""
    long_side, short_side = float(max(tl, tw)), float(min(tl, tw))
    placed = classify(herringbone_polys(parts, long_side, short_side), parts, axis_aligned=True)
    return len(placed), sum(p.cut for p in placed)


def layout_tiles(
    parts: list[Part], tl: Decimal, tw: Decimal, layout: str, offset_pct: Decimal = Decimal(50)
) -> list[Placed]:
    """Every tile of the drawing, whole or cut, for any layout."""
    a, b = float(tl), float(tw)
    if layout == "herringbone":
        polys = herringbone_polys(parts, max(a, b), min(a, b))
        return classify(polys, parts, axis_aligned=True)
    if layout == "diagonal":
        return classify(diagonal_polys(parts, a, b), parts, axis_aligned=False)
    offsets = [float(o) for o in brick_offsets(tl, offset_pct)] if layout == "brick" else None
    return classify(straight_polys(parts, a, b, offsets), parts, axis_aligned=True)


def roll_drops(parts: list[Part], roll_width: Decimal) -> list[Placed]:
    """Roll drops for each rectangle, laid the way the estimate lays them (whichever needs less
    roll, see extras.calculate_roll); a drop narrower than the roll is trimmed."""
    out = []
    w = float(roll_width)
    for p in parts:
        x0, y0, length, width = float(p.x), float(p.y), float(p.length), float(p.width)
        along_x = calculate_roll(p.length, p.width, roll_width).along == "length"
        run, across = (length, width) if along_x else (width, length)
        offset = 0.0
        while offset < across - EPS:
            strip = min(w, across - offset)
            if along_x:
                pts = [
                    (x0, y0 + offset),
                    (x0 + run, y0 + offset),
                    (x0 + run, y0 + offset + strip),
                    (x0, y0 + offset + strip),
                ]
            else:
                pts = [
                    (x0 + offset, y0),
                    (x0 + offset + strip, y0),
                    (x0 + offset + strip, y0 + run),
                    (x0 + offset, y0 + run),
                ]
            out.append(Placed(pts, strip < w - EPS))
            offset += w
    return out
