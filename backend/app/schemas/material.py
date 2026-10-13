"""Material assignment (PRD 4.6): which tile each room gets, laid how, with what buffer and price.

A project has default settings; each room can override any single setting. Assigned tiles are
stored as a snapshot (TileRef), so later edits to the library don't silently change an estimate.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from app.engine.units import LengthUnit

# Decimals travel as strings so no precision is lost to float.
DecimalStr = Annotated[
    Decimal, PlainSerializer(lambda v: str(v), return_type=str, when_used="always")
]

DEFAULT_BREAKAGE_PCT = Decimal(5)


class Layout(StrEnum):
    STRAIGHT = "straight"
    DIAGONAL = "diagonal"


class PriceBasis(StrEnum):
    BOX = "box"
    TILE = "tile"  # also "per piece" for planks and skirting pieces
    SQFT = "sqft"  # common for tiles in India
    SQM = "sqm"
    LM = "lm"  # per running metre: roll goods (carpet, sheet vinyl)


class ProductKind(StrEnum):
    """How a flooring product is sold and laid (PRD 4.15)."""

    TILE = "tile"  # counted on a grid, sold in boxes
    PLANK = "plank"  # wood, laminate, vinyl plank: staggered rows, by area + allowance, boxes
    ROLL = "roll"  # carpet, sheet vinyl: drops cut from a roll, sold by the running metre


class Price(BaseModel):
    amount: DecimalStr = Field(gt=0, le=10_000_000)
    basis: PriceBasis = PriceBasis.BOX


class TileRef(BaseModel):
    """Snapshot of a library tile at the time it was assigned. For a roll, width_mm is the roll
    width and tiles_per_box is 1."""

    id: str
    name: str
    size_label: str
    length_mm: DecimalStr
    width_mm: DecimalStr
    tiles_per_box: int
    kind: ProductKind = ProductKind.TILE
    thickness_mm: DecimalStr | None = None  # grout depth (PRD 4.15)
    tile_type: str | None = None  # floor, wall, anti_skid...: for room-type suggestions
    material: str | None = None


class MaterialOverride(BaseModel):
    """A room's own settings. None = use the project default for that setting."""

    tile: TileRef | None = None
    layout: Layout | None = None
    breakage_pct: DecimalStr | None = Field(default=None, ge=0, le=50)
    price: Price | None = None


class ProjectMaterial(BaseModel):
    """Project-wide default settings."""

    tile: TileRef | None = None
    layout: Layout = Layout.STRAIGHT
    breakage_pct: DecimalStr = Field(default=DEFAULT_BREAKAGE_PCT, ge=0, le=50)
    price: Price | None = None


MaterialField = Literal["tile", "layout", "breakage_pct", "price"]
MATERIAL_FIELDS: tuple[MaterialField, ...] = ("tile", "layout", "breakage_pct", "price")


class EffectiveMaterial(BaseModel):
    """What a room actually uses (computed, not stored)."""

    tile: TileRef | None
    layout: Layout
    breakage_pct: DecimalStr
    price: Price | None
    overridden: list[MaterialField]  # settings that come from the room, not the project


class Exclusion(BaseModel):
    """An untiled area inside a room: a kitchen cabinet base, a column, a bathtub."""

    id: str
    label: str = Field(min_length=1, max_length=60)
    length_mm: DecimalStr = Field(gt=0)
    width_mm: DecimalStr = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=100)
    unit: LengthUnit = LengthUnit.FT_IN  # as entered, for display


# --- Requests ---------------------------------------------------------------------------------


class DefaultMaterialIn(BaseModel):
    tile_id: str | None = None
    layout: Layout = Layout.STRAIGHT
    breakage_pct: Decimal = Field(default=DEFAULT_BREAKAGE_PCT, ge=0, le=50)
    price: Price | None = None
    version: int


class MaterialPatch(BaseModel):
    """Settings to set on rooms. Only the fields you send are changed."""

    tile_id: str | None = None
    layout: Layout | None = None
    breakage_pct: Decimal | None = Field(default=None, ge=0, le=50)
    price: Price | None = None


class RoomsMaterialIn(BaseModel):
    """Bulk change for selected rooms: edit settings, copy from another room, reset, or skip."""

    room_ids: list[str] = Field(min_length=1, max_length=1000)
    set: MaterialPatch = Field(default_factory=MaterialPatch)
    inherit: list[MaterialField] = Field(default_factory=list)  # go back to the project default
    skipped: bool | None = None
    version: int


class ExclusionIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    length: str = Field(min_length=1, max_length=30)
    width: str = Field(min_length=1, max_length=30)
    quantity: int = Field(default=1, ge=1, le=100)
    unit: LengthUnit = LengthUnit.FT_IN


class ExclusionsIn(BaseModel):
    exclusions: list[ExclusionIn] = Field(max_length=50)
    version: int


class MaterialsSummaryOut(BaseModel):
    rooms_needing_tile: int  # not skipped, no tile from room or project
    skipped: int
    rooms_over_excluded: int  # exclusions cover the whole room
    ready_for_calculation: bool  # review done (PRD 4.3/4.4) and every room has a tile
