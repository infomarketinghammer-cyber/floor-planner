"""Additional materials (PRD 4.15): wall tiles, skirting and sundries.

Per room: openings (doors, windows) and wall tiling. Per project: the default wall tile, and
skirting and sundries settings. All lengths are exact decimal millimetres.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.units import LengthUnit
from app.schemas.material import DecimalStr, Price, TileRef

MAX_PACK = 100_000


class OpeningKind(StrEnum):
    DOOR = "door"  # also stops the skirting
    WINDOW = "window"
    OTHER = "other"  # niches, mirrors, anything not tiled on a wall


class Opening(BaseModel):
    id: str
    kind: OpeningKind = OpeningKind.DOOR
    label: str = Field(default="", max_length=60)
    width_mm: DecimalStr = Field(gt=0)
    height_mm: DecimalStr = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=50)
    unit: LengthUnit = LengthUnit.FT_IN  # as entered, for display


class WallTiling(BaseModel):
    """Tiles on the walls of a room, up to a height (full height in a bathroom, a dado or a
    kitchen backsplash band)."""

    height_mm: DecimalStr = Field(gt=0, le=10_000)
    tile: TileRef | None = None  # None: the project's default wall tile
    breakage_pct: DecimalStr | None = Field(default=None, ge=0, le=50)  # None: project default
    # Length of wall to tile. None: the whole perimeter of a rectangular room. Needed for rooms
    # known only by area, or when only some walls are tiled (e.g. a kitchen backsplash).
    length_mm: DecimalStr | None = Field(default=None, gt=0)
    price: Price | None = None  # None: the project's wall tile price


class SkirtingSource(StrEnum):
    FLOOR_TILE = "floor_tile"  # strips cut from each room's floor tile
    PIECES = "pieces"  # ready-made skirting pieces


class SkirtingSettings(BaseModel):
    model_config = ConfigDict(validate_default=True)  # defaults become Decimals

    enabled: bool = False
    height_mm: DecimalStr = Field(default=100, gt=0, le=300)
    source: SkirtingSource = SkirtingSource.FLOOR_TILE
    piece_name: str = Field(default="Skirting", min_length=1, max_length=60)
    piece_length_mm: DecimalStr = Field(default=1200, gt=0, le=6000)
    pieces_per_box: int | None = Field(default=None, ge=1, le=500)  # None: sold per piece
    price: Price | None = None  # for pieces: per box or per piece ("tile" basis)
    breakage_pct: DecimalStr = Field(default=5, ge=0, le=50)
    # Rooms with tiled walls (bathrooms) don't need skirting.
    skip_tiled_walls: bool = True


class SundriesSettings(BaseModel):
    """Adhesive, grout and spacers from coverage rates (PRD 4.15). Rates left empty use typical
    values (see app/engine/extras.py)."""

    model_config = ConfigDict(validate_default=True)  # defaults become Decimals

    enabled: bool = False
    adhesive_rate_kg_m2: DecimalStr | None = Field(default=None, gt=0, le=20)
    adhesive_bag_kg: DecimalStr = Field(default=20, gt=0, le=100)
    adhesive_bag_price: DecimalStr | None = Field(default=None, gt=0, le=MAX_PACK)
    grout_joint_mm: DecimalStr = Field(default=2, gt=0, le=20)
    grout_depth_mm: DecimalStr | None = Field(default=None, gt=0, le=30)  # None: tile thickness
    grout_pack_kg: DecimalStr = Field(default=1, gt=0, le=50)
    grout_pack_price: DecimalStr | None = Field(default=None, gt=0, le=MAX_PACK)
    spacers_per_tile: DecimalStr = Field(default=1, ge=0, le=10)  # crosses at the corners
    spacer_pack: int = Field(default=100, ge=1, le=10_000)
    spacer_pack_price: DecimalStr | None = Field(default=None, gt=0, le=MAX_PACK)
    waste_pct: DecimalStr = Field(default=10, ge=0, le=50)


class ExtrasSettings(BaseModel):
    """Project-wide settings for the additional materials. Stored on the project."""

    model_config = ConfigDict(validate_default=True)  # defaults become Decimals

    wall_tile: TileRef | None = None
    wall_breakage_pct: DecimalStr = Field(default=5, ge=0, le=50)
    wall_price: Price | None = None
    skirting: SkirtingSettings = Field(default_factory=SkirtingSettings)
    sundries: SundriesSettings = Field(default_factory=SundriesSettings)


# --- Requests -----------------------------------------------------------------------------------


class OpeningIn(BaseModel):
    kind: OpeningKind = OpeningKind.DOOR
    label: str = Field(default="", max_length=60)
    width: str = Field(min_length=1, max_length=30)
    height: str = Field(min_length=1, max_length=30)
    quantity: int = Field(default=1, ge=1, le=50)
    unit: LengthUnit = LengthUnit.FT_IN


class WallTilingIn(BaseModel):
    height: str = Field(min_length=1, max_length=30)
    unit: LengthUnit = LengthUnit.FT_IN
    tile_id: str | None = None  # None: project default wall tile
    breakage_pct: DecimalStr | None = Field(default=None, ge=0, le=50)
    length: str | None = Field(default=None, max_length=30)  # wall length to tile, if partial
    price: Price | None = None


class RoomWallsIn(BaseModel):
    """Openings, wall tiling and skirting for one room. Replaces all three."""

    openings: list[OpeningIn] = Field(default_factory=list, max_length=30)
    walls: WallTilingIn | None = None  # None: walls not tiled
    skirting: bool | None = None  # None: follow the project setting
    version: int


class ExtrasSettingsIn(BaseModel):
    model_config = ConfigDict(validate_default=True)  # defaults become Decimals

    wall_tile_id: str | None = None
    wall_breakage_pct: DecimalStr = Field(default=5, ge=0, le=50)
    wall_price: Price | None = None
    skirting: SkirtingSettings = Field(default_factory=SkirtingSettings)
    sundries: SundriesSettings = Field(default_factory=SundriesSettings)


# --- Results ------------------------------------------------------------------------------------


class WallEstimateOut(BaseModel):
    room_id: str
    name: str
    tile: TileRef
    height_mm: DecimalStr
    length_mm: DecimalStr  # wall length tiled
    wall_area_mm2: DecimalStr
    openings_area_mm2: DecimalStr
    net_area_mm2: DecimalStr
    rows: int
    tiles_needed: int
    buffer_tiles: int
    tiles_required: int
    boxes: int
    tiles_bought: int
    extra_area_mm2: DecimalStr


class WallTileTotalOut(BaseModel):
    tile: TileRef
    rooms: int
    net_area_mm2: DecimalStr
    tiles_required: int
    boxes: int
    tiles_bought: int


class SkirtingRoomOut(BaseModel):
    room_id: str
    name: str
    perimeter_mm: DecimalStr
    doors_mm: DecimalStr  # door widths left out
    run_mm: DecimalStr
    pieces: int  # strips or pieces, with breakage


class SkirtingProductOut(BaseModel):
    """One thing to buy: a floor tile cut into strips, or ready-made pieces."""

    label: str
    tile: TileRef | None  # floor tile the strips are cut from
    piece_length_mm: DecimalStr
    strips_per_tile: int | None
    pieces: int
    tiles: int | None  # floor tiles to cut
    boxes: int | None  # None: sold per piece
    run_mm: DecimalStr


class SkirtingOut(BaseModel):
    source: Literal["floor_tile", "pieces"]
    height_mm: DecimalStr
    rooms: list[SkirtingRoomOut]
    products: list[SkirtingProductOut]
    run_mm: DecimalStr


class SundryOut(BaseModel):
    key: Literal["adhesive", "grout", "spacers"]
    label: str
    quantity: DecimalStr  # kg, or pieces for spacers
    unit: Literal["kg", "pcs"]
    pack_size: DecimalStr
    waste_pct: DecimalStr
    packs: int
    area_mm2: DecimalStr  # area it covers (floor + walls)
    basis: str  # how it was worked out, in words


class ExtrasOut(BaseModel):
    walls: list[WallEstimateOut]
    wall_tiles: list[WallTileTotalOut]
    skirting: SkirtingOut | None
    sundries: list[SundryOut]
    warnings: list[str]  # e.g. a room with tiled walls but no wall tile chosen
