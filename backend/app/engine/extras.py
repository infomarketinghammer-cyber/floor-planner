"""Additional materials (PRD 4.15): wall tiles, skirting, sundries and roll flooring.

Pure functions, like calc.py: Decimal millimetres in, exact results out, no I/O.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.engine.calc import (
    Excluded,
    Method,
    RoomResult,
    Tile,
    _finish,
    ceil_int,
    floor_int,
)

MM2_PER_SQM = Decimal(1_000_000)

# --- Roll flooring (carpet, sheet vinyl) --------------------------------------------------------

# Extra length per drop for trimming at each wall (a common fitter allowance: ~50 mm a side).
ROLL_TRIM_MM = Decimal(100)
# Rooms known only by area: no sides to lay drops along, so area ÷ roll width plus this.
ROLL_AREA_ALLOWANCE_PCT = Decimal(15)
# Planks (wood, laminate, vinyl plank) are laid staggered and cut at the row ends: worked out
# by area plus an allowance, like a diagonal tile layout.
PLANK_ALLOWANCE_PCT = Decimal(8)
PLANK_DIAGONAL_ALLOWANCE_PCT = Decimal(15)


@dataclass(frozen=True)
class RollResult:
    room_area_mm2: Decimal
    usable_area_mm2: Decimal
    roll_width_mm: Decimal
    drops: int | None  # strips cut from the roll; None when worked out by area
    drop_length_mm: Decimal | None
    linear_mm: Decimal  # length of roll to buy
    along: str | None  # "length" or "width": which way the drops run
    allowance_pct: Decimal

    @property
    def bought_area_mm2(self) -> Decimal:
        return self.linear_mm * self.roll_width_mm

    @property
    def extra_area_mm2(self) -> Decimal:
        return self.bought_area_mm2 - self.usable_area_mm2


def calculate_roll(
    length_mm: Decimal,
    width_mm: Decimal,
    roll_width_mm: Decimal,
    excluded_area_mm2: Decimal = Decimal(0),
    trim_mm: Decimal = ROLL_TRIM_MM,
) -> RollResult:
    """Drops laid side by side across the room, each the room's length plus trim. Both
    directions are tried and the one needing less roll is used. Untiled areas don't save roll
    (the drop is cut around them), so they only reduce the usable area."""
    if min(length_mm, width_mm, roll_width_mm) <= 0:
        raise ValueError("Sizes must be positive")
    options = []
    for along, run, across in (("length", length_mm, width_mm), ("width", width_mm, length_mm)):
        drops = ceil_int(across / roll_width_mm)
        drop = run + trim_mm
        options.append((drops * drop, along, drops, drop))
    linear, along, drops, drop = min(options, key=lambda o: o[0])
    area = length_mm * width_mm
    return RollResult(
        room_area_mm2=area,
        usable_area_mm2=area - excluded_area_mm2,
        roll_width_mm=roll_width_mm,
        drops=drops,
        drop_length_mm=drop,
        linear_mm=linear,
        along=along,
        allowance_pct=Decimal(0),
    )


def calculate_roll_by_area(
    area_mm2: Decimal,
    roll_width_mm: Decimal,
    excluded_area_mm2: Decimal = Decimal(0),
    allowance_pct: Decimal = ROLL_AREA_ALLOWANCE_PCT,
) -> RollResult:
    usable = area_mm2 - excluded_area_mm2
    # Rounded up to the next 10 cm, which is how roll goods are usually cut and sold.
    raw = usable * (1 + allowance_pct / 100) / roll_width_mm
    linear = Decimal(ceil_int(raw / 100) * 100)
    return RollResult(
        room_area_mm2=area_mm2,
        usable_area_mm2=usable,
        roll_width_mm=roll_width_mm,
        drops=None,
        drop_length_mm=None,
        linear_mm=linear,
        along=None,
        allowance_pct=allowance_pct,
    )


# --- Wall tiles ---------------------------------------------------------------------------------


def _opening_tiles(opening: Excluded, tile: Tile) -> int:
    """Whole tiles certain to fall inside a door or window, wherever the grid starts. Unlike a
    floor cut-out, an opening's orientation is known: its width runs along the wall."""

    def full(span: Decimal, pitch: Decimal) -> int:
        return max(0, floor_int(span / pitch) - 1)

    return (
        full(opening.length_mm, tile.length_mm)
        * full(opening.width_mm, tile.width_mm)
        * opening.quantity
    )


def calculate_walls(
    wall_lengths_mm: list[Decimal],
    height_mm: Decimal,
    tile: Tile,
    breakage_pct: Decimal = Decimal(0),
    openings: tuple[Excluded, ...] = (),
) -> RoomResult:
    """Grid count per wall up to the tiling height, minus tiles certain to sit inside door and
    window openings (given as Excluded(width along the wall, height)). The tile is turned whichever way needs fewer tiles (fixers lay wall tiles
    either way), and each wall is counted on its own, since cuts at corners can't be shared."""
    if height_mm <= 0 or not wall_lengths_mm or any(w <= 0 for w in wall_lengths_mm):
        raise ValueError("Walls and height must be positive")
    perimeter = sum(wall_lengths_mm, Decimal(0))
    gross = perimeter * height_mm
    opening_area = sum((o.area_mm2 for o in openings), Decimal(0))
    if opening_area >= gross:
        raise ValueError("Openings cover the whole wall area")

    best = None
    for t in (tile, Tile(tile.width_mm, tile.length_mm, tile.tiles_per_box)):
        rows = ceil_int(height_mm / t.width_mm)
        grid = sum(ceil_int(w / t.length_mm) * rows for w in wall_lengths_mm)
        covered = min(sum(_opening_tiles(o, t) for o in openings), grid - 1)
        if best is None or grid - covered < best[0]:
            best = (grid - covered, t, rows, grid, covered)
    needed, t, rows, grid, covered = best
    return _finish(
        method=Method.GRID,
        tile=t,
        room_area=gross,
        usable_area=gross - opening_area,
        columns=None,
        rows=rows,
        grid_tiles=grid,
        excluded_tiles=covered,
        tiles_needed=needed,
        allowance_pct=Decimal(0),
        breakage_pct=breakage_pct,
    )


# --- Skirting -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SkirtingPieces:
    run_mm: Decimal  # running length to cover
    piece_length_mm: Decimal
    pieces: int  # including the breakage buffer


def skirting_pieces(
    run_mm: Decimal, piece_length_mm: Decimal, breakage_pct: Decimal
) -> SkirtingPieces:
    """Pieces of a given length to cover a run, plus breakage, rounded up to whole pieces."""
    if piece_length_mm <= 0:
        raise ValueError("Piece length must be positive")
    if run_mm <= 0:
        return SkirtingPieces(Decimal(0), piece_length_mm, 0)
    pieces = ceil_int(run_mm / piece_length_mm * (1 + breakage_pct / 100))
    return SkirtingPieces(run_mm, piece_length_mm, pieces)


def strips_per_tile(tile: Tile, height_mm: Decimal) -> tuple[int, Decimal]:
    """Skirting strips cut from one floor tile: strips run along the tile's longer side.
    Returns (strips per tile, strip length)."""
    long_side, short_side = max(tile.length_mm, tile.width_mm), min(tile.length_mm, tile.width_mm)
    return floor_int(short_side / height_mm), long_side


# --- Sundries: adhesive, grout, spacers ---------------------------------------------------------

# Typical cement-based tile adhesive spread rates (kg per m²) by tile size: bigger tiles need a
# deeper notch trowel. Used unless a rate is entered.
ADHESIVE_RATES: list[tuple[Decimal, Decimal]] = [
    (Decimal("0.1"), Decimal(4)),  # up to 0.1 m² a tile (e.g. 300 × 300)
    (Decimal("0.4"), Decimal(5)),  # up to 0.4 m² (e.g. 600 × 600)
    (Decimal(999), Decimal(6)),  # larger formats
]
WALL_ADHESIVE_RATE = Decimal("3.5")
GROUT_DENSITY = Decimal("1.6")  # g/cm³, cement grout
DEFAULT_TILE_THICKNESS_MM = Decimal(8)


def default_adhesive_rate(tile: Tile, wall: bool = False) -> Decimal:
    if wall:
        return WALL_ADHESIVE_RATE
    area_m2 = tile.area_mm2 / MM2_PER_SQM
    return next(rate for limit, rate in ADHESIVE_RATES if area_m2 <= limit)


def grout_kg_per_m2(
    tile: Tile, joint_mm: Decimal, depth_mm: Decimal, density: Decimal = GROUT_DENSITY
) -> Decimal:
    """The usual manufacturers' formula: (L + W) ÷ (L × W) × joint width × joint depth × density,
    with sizes in mm and density in g/cm³, giving kg per m²."""
    return (
        (tile.length_mm + tile.width_mm)
        * joint_mm
        * depth_mm
        * density
        / (tile.length_mm * tile.width_mm)
    )


def packs(quantity: Decimal, pack_size: Decimal, waste_pct: Decimal = Decimal(0)) -> int:
    if quantity <= 0:
        return 0
    return ceil_int(quantity * (1 + waste_pct / 100) / pack_size)
