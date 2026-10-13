"""Deterministic tile quantity and waste calculation (PRD 4.7, 4.8).

Pure functions only: no I/O, no AI. Every result must be reproducible from its inputs.
All lengths are Decimal millimetres; areas are Decimal mm².
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

# Extra cutting allowance when tiles are laid diagonally (on top of the room area). Diagonal
# laying cuts a tile at every wall; 10–15% is the usual trade allowance.
DIAGONAL_ALLOWANCE_PCT = Decimal(15)
# Allowance for rooms known only by their area (odd shapes): no grid to count cuts from.
AREA_ONLY_ALLOWANCE_PCT = Decimal(10)


def ceil_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def floor_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


class Method(StrEnum):
    GRID = "grid"  # rectangular room, straight layout: count the grid (PRD 4.7)
    AREA = "area"  # percentage fallback: diagonal layouts, rooms known only by area


@dataclass(frozen=True)
class Tile:
    length_mm: Decimal
    width_mm: Decimal
    tiles_per_box: int

    def __post_init__(self) -> None:
        if self.length_mm <= 0 or self.width_mm <= 0:
            raise ValueError("Tile dimensions must be positive")
        if self.tiles_per_box < 1:
            raise ValueError("tiles_per_box must be at least 1")

    @property
    def area_mm2(self) -> Decimal:
        return self.length_mm * self.width_mm


@dataclass(frozen=True)
class Excluded:
    """An untiled rectangle inside the room (cabinet base, column...)."""

    length_mm: Decimal
    width_mm: Decimal
    quantity: int = 1

    @property
    def area_mm2(self) -> Decimal:
        return self.length_mm * self.width_mm * self.quantity


@dataclass(frozen=True)
class RoomResult:
    method: Method
    room_area_mm2: Decimal
    usable_area_mm2: Decimal  # room area minus untiled areas
    columns: int | None  # grid method only
    rows: int | None
    grid_tiles: int  # full grid before exclusions (grid) / tiles from area (area)
    excluded_tiles: int  # tiles certain to sit under untiled areas
    tiles_needed: int  # before the breakage buffer
    allowance_pct: Decimal  # area method only: cutting allowance used
    cut_waste_mm2: Decimal  # area of tiles needed minus usable area
    buffer_tiles: int
    tiles_required: int
    boxes: int
    tiles_bought: int
    extra_area_mm2: Decimal  # bought area minus usable area: cut waste + buffer + box rounding
    tile_area_mm2: Decimal

    # Waste breakdown (PRD 4.8): extra = cut waste + breakage buffer + box rounding, exactly.
    @property
    def buffer_area_mm2(self) -> Decimal:
        return self.buffer_tiles * self.tile_area_mm2

    @property
    def rounding_tiles(self) -> int:
        """Tiles left over in the last box."""
        return self.tiles_bought - self.tiles_required

    @property
    def rounding_area_mm2(self) -> Decimal:
        return self.rounding_tiles * self.tile_area_mm2

    @property
    def cut_waste_pct(self) -> Decimal:
        return self.cut_waste_mm2 / self.usable_area_mm2 * 100

    @property
    def extra_pct(self) -> Decimal:
        return self.extra_area_mm2 / self.usable_area_mm2 * 100


def _covered_tiles(ex: Excluded, tile: Tile) -> int:
    """Tiles an untiled rectangle is certain to cover wherever it sits on the grid.

    A span of L over tiles of pitch t always contains at least floor(L/t) - 1 whole tiles
    (fewer than the aligned count when it starts just past a grid line). Both orientations are
    tried and the smaller count kept, so exclusions never cause under-ordering.
    """

    def full(span: Decimal, pitch: Decimal) -> int:
        return max(0, floor_int(span / pitch) - 1)

    as_given = full(ex.length_mm, tile.length_mm) * full(ex.width_mm, tile.width_mm)
    rotated = full(ex.length_mm, tile.width_mm) * full(ex.width_mm, tile.length_mm)
    return min(as_given, rotated) * ex.quantity


def _finish(
    *,
    method: Method,
    tile: Tile,
    room_area: Decimal,
    usable_area: Decimal,
    columns: int | None,
    rows: int | None,
    grid_tiles: int,
    excluded_tiles: int,
    tiles_needed: int,
    allowance_pct: Decimal,
    breakage_pct: Decimal,
) -> RoomResult:
    buffer_tiles = ceil_int(tiles_needed * breakage_pct / 100)
    tiles_required = tiles_needed + buffer_tiles
    boxes = ceil_int(Decimal(tiles_required) / tile.tiles_per_box)
    tiles_bought = boxes * tile.tiles_per_box
    return RoomResult(
        method=method,
        room_area_mm2=room_area,
        usable_area_mm2=usable_area,
        columns=columns,
        rows=rows,
        grid_tiles=grid_tiles,
        excluded_tiles=excluded_tiles,
        tiles_needed=tiles_needed,
        allowance_pct=allowance_pct,
        cut_waste_mm2=tiles_needed * tile.area_mm2 - usable_area,
        buffer_tiles=buffer_tiles,
        tiles_required=tiles_required,
        boxes=boxes,
        tiles_bought=tiles_bought,
        extra_area_mm2=tiles_bought * tile.area_mm2 - usable_area,
        tile_area_mm2=tile.area_mm2,
    )


def _check(breakage_pct: Decimal, room_area: Decimal, excluded: Decimal) -> None:
    if breakage_pct < 0:
        raise ValueError("breakage_pct cannot be negative")
    if excluded >= room_area:
        raise ValueError("Untiled areas cover the whole room")


def calculate_room(
    length_mm: Decimal,
    width_mm: Decimal,
    tile: Tile,
    breakage_pct: Decimal = Decimal(0),
    exclusions: tuple[Excluded, ...] = (),
) -> RoomResult:
    """Grid method for a rectangular room with a straight layout (PRD 4.7).

    columns = ceil(length / tile length), rows = ceil(width / tile width). Tiles certain to sit
    under untiled areas are taken off. Cut waste = tiles needed × tile area − usable area.
    Ignores offcut reuse, so it is slightly conservative.
    """
    if length_mm <= 0 or width_mm <= 0:
        raise ValueError("Room dimensions must be positive")
    room_area = length_mm * width_mm
    excluded_area = sum((e.area_mm2 for e in exclusions), Decimal(0))
    _check(breakage_pct, room_area, excluded_area)

    columns = ceil_int(length_mm / tile.length_mm)
    rows = ceil_int(width_mm / tile.width_mm)
    grid_tiles = columns * rows
    excluded_tiles = min(sum(_covered_tiles(e, tile) for e in exclusions), grid_tiles - 1)
    return _finish(
        method=Method.GRID,
        tile=tile,
        room_area=room_area,
        usable_area=room_area - excluded_area,
        columns=columns,
        rows=rows,
        grid_tiles=grid_tiles,
        excluded_tiles=excluded_tiles,
        tiles_needed=grid_tiles - excluded_tiles,
        allowance_pct=Decimal(0),
        breakage_pct=breakage_pct,
    )


def calculate_by_area(
    area_mm2: Decimal,
    tile: Tile,
    allowance_pct: Decimal,
    breakage_pct: Decimal = Decimal(0),
    excluded_area_mm2: Decimal = Decimal(0),
) -> RoomResult:
    """Percentage fallback (PRD 4.7): tiles = ceil(usable area × (1 + allowance) ÷ tile area).

    Used where a grid count doesn't apply: diagonal layouts and rooms known only by area.
    """
    if area_mm2 <= 0:
        raise ValueError("Room area must be positive")
    if allowance_pct < 0:
        raise ValueError("allowance_pct cannot be negative")
    _check(breakage_pct, area_mm2, excluded_area_mm2)

    usable = area_mm2 - excluded_area_mm2
    tiles_needed = ceil_int(usable * (1 + allowance_pct / 100) / tile.area_mm2)
    return _finish(
        method=Method.AREA,
        tile=tile,
        room_area=area_mm2,
        usable_area=usable,
        columns=None,
        rows=None,
        grid_tiles=tiles_needed,
        excluded_tiles=0,
        tiles_needed=tiles_needed,
        allowance_pct=allowance_pct,
        breakage_pct=breakage_pct,
    )


def equivalent_tile_count(count: int, from_tile: Tile, to_tile: Tile) -> int:
    """Convert a tile count by area, e.g. 20 tiles of 2x2 ft = 80 tiles of 1x1 ft."""
    return ceil_int(count * from_tile.area_mm2 / to_tile.area_mm2)
