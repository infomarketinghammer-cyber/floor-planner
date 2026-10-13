"""Quantity estimate (PRD 4.7). All areas are exact mm² (as strings); the UI converts for display."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.extras import ExtrasOut
from app.schemas.material import DecimalStr, Layout, ProductKind, TileRef


class RoomEstimateOut(BaseModel):
    room_id: str
    name: str
    floor: str | None
    room_type: str  # e.g. "Bedroom", "Bathroom & toilet" (for grouping, PRD 4.9)
    tile: TileRef
    layout: Layout
    method: Literal["grid", "area", "roll"]
    kind: ProductKind = ProductKind.TILE
    # Layouts (PRD 4.16): tiles that need cutting, and the count if offcuts were reused (None
    # where reuse isn't modelled: diagonal, herringbone, planks, rolls, area-only rooms).
    cut_tiles: int | None = None
    tiles_if_reused: int | None = None
    reuse_applied: bool = False  # the tile count above already counts on reused offcuts
    # Roll goods only: roll to buy (boxes and tiles are 0) and how it's cut.
    linear_mm: DecimalStr | None = None
    drops: int | None = None
    method_reason: str  # plain-language: why this method was used
    allowance_pct: DecimalStr  # cutting allowance (area method only)
    breakage_pct: DecimalStr
    room_area_mm2: DecimalStr
    usable_area_mm2: DecimalStr
    columns: int | None
    rows: int | None
    grid_tiles: int
    excluded_tiles: int
    tiles_needed: int  # before the breakage buffer
    cut_waste_mm2: DecimalStr
    cut_waste_pct: DecimalStr
    buffer_tiles: int
    tiles_required: int
    boxes: int
    tiles_bought: int
    extra_area_mm2: DecimalStr  # bought minus usable: cuts + buffer + box rounding
    # Waste breakdown (PRD 4.8): extra = cut waste + buffer + rounding, exactly.
    buffer_area_mm2: DecimalStr
    rounding_tiles: int  # left over in the last box
    rounding_area_mm2: DecimalStr
    extra_pct: DecimalStr  # extra as % of the usable area
    high_waste: bool  # cut waste above HIGH_WASTE_PCT
    waste_hint: str | None


class Assumption(BaseModel):
    key: str  # stable id, e.g. "method_grid", for exports and tests
    title: str
    text: str


class TileTotalOut(BaseModel):
    """Per tile type, so different sizes are never added up as if they were the same tile.
    Totals are the sum of the rooms (PRD 11)."""

    tile: TileRef
    rooms: int
    usable_area_mm2: DecimalStr
    tiles_required: int
    boxes: int  # sum of the rooms' boxes
    tiles_bought: int
    bought_area_mm2: DecimalStr
    # If leftovers from one room are used in another: tiles pooled, rounded to boxes once.
    boxes_if_pooled: int
    linear_mm: DecimalStr | None = None  # roll goods: total running length to buy


class EstimateTotalsOut(BaseModel):
    rooms: int
    room_area_mm2: DecimalStr
    usable_area_mm2: DecimalStr
    cut_waste_mm2: DecimalStr
    buffer_area_mm2: DecimalStr
    rounding_area_mm2: DecimalStr
    bought_area_mm2: DecimalStr
    extra_area_mm2: DecimalStr  # = cut waste + buffer + rounding
    cut_waste_pct: DecimalStr
    extra_pct: DecimalStr
    high_waste_rooms: int
    boxes: int


class EstimateOut(BaseModel):
    ready: bool
    blockers: list[str]  # why it can't be calculated yet (empty when ready)
    rooms: list[RoomEstimateOut]
    tiles: list[TileTotalOut]
    totals: EstimateTotalsOut | None
    assumptions: list[Assumption]  # how the numbers were worked out (PRD 4.8); also used in exports
    offcut_note: str
    extras: ExtrasOut | None = None  # wall tiles, skirting, sundries (PRD 4.15)
