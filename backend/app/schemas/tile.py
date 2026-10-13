"""Tile library (PRD 4.5). Sizes are exact decimal millimetres, like every other length."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_serializer

from app.engine.units import LengthUnit
from app.schemas.material import ProductKind


class TileType(StrEnum):
    FLOOR = "floor"
    WALL = "wall"
    FLOOR_WALL = "floor_wall"
    ANTI_SKID = "anti_skid"
    OUTDOOR = "outdoor"


class TileFinish(StrEnum):
    MATT = "matt"
    GLOSSY = "glossy"
    SATIN = "satin"
    POLISHED = "polished"
    TEXTURED = "textured"
    OTHER = "other"


class TileMaterial(StrEnum):
    VITRIFIED = "vitrified"
    CERAMIC = "ceramic"
    PORCELAIN = "porcelain"
    NATURAL_STONE = "natural_stone"
    MOSAIC = "mosaic"
    # Other flooring (PRD 4.15)
    WOOD = "wood"
    LAMINATE = "laminate"
    VINYL = "vinyl"
    CARPET = "carpet"
    OTHER = "other"


class TileRegion(StrEnum):
    INDIA = "india"  # metric sizes common in India
    IMPERIAL = "imperial"  # inch/foot sizes (US, and imperial-sized stock elsewhere)


class TileScope(StrEnum):
    CATALOG = "catalog"  # shared, managed by admins
    USER = "user"  # a contractor's own saved tile


# Size units offered for tiles; feet-inches isn't used for tile sizes.
TILE_SIZE_UNITS = (LengthUnit.MM, LengthUnit.CM, LengthUnit.M, LengthUnit.IN, LengthUnit.FT)


class TileInput(BaseModel):
    """Create/update a tile. Sizes are text in `size_unit` (or with their own marks: 24", 2').

    For a roll (carpet, sheet vinyl), `width` is the roll width and `length` the roll length;
    tiles per box doesn't apply."""

    name: str = Field(min_length=1, max_length=120)
    kind: ProductKind = ProductKind.TILE
    length: str = Field(min_length=1, max_length=20)
    width: str = Field(min_length=1, max_length=20)
    size_unit: LengthUnit = LengthUnit.MM
    thickness_mm: Decimal | None = Field(default=None, ge=2, le=50)
    # Give tiles per box, or coverage per box (m²) and we'll work out the tile count.
    tiles_per_box: int | None = Field(default=None, ge=1, le=500)
    coverage_per_box_sqm: Decimal | None = Field(default=None, gt=0, le=50)
    type: TileType = TileType.FLOOR
    finish: TileFinish = TileFinish.MATT
    material: TileMaterial = TileMaterial.VITRIFIED
    brand: str | None = Field(default=None, max_length=80)
    code: str | None = Field(default=None, max_length=60)  # supplier SKU / design code
    vendor: str | None = Field(default=None, max_length=80)  # who you buy it from (order lists)
    regions: list[TileRegion] = Field(default_factory=list, max_length=4)
    notes: str | None = Field(default=None, max_length=500)


class TileOut(BaseModel):
    id: str
    scope: TileScope
    owner_id: str | None
    name: str
    length_mm: Decimal
    width_mm: Decimal
    size_unit: LengthUnit
    size_label: str  # e.g. "600 × 600 mm", "2 × 2 ft"
    kind: ProductKind
    thickness_mm: Decimal | None
    tiles_per_box: int
    tile_area_sqm: float
    tile_area_sqft: float
    coverage_per_box_sqm: float
    coverage_per_box_sqft: float
    type: TileType
    finish: TileFinish
    material: TileMaterial
    brand: str | None
    code: str | None
    vendor: str | None
    regions: list[TileRegion]
    notes: str | None
    typical: bool  # catalogue presets: pack counts are typical, check with the supplier
    editable: bool  # the current user may edit/delete it
    created_at: datetime
    updated_at: datetime

    @field_serializer("length_mm", "width_mm", "thickness_mm")
    def _decimal_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)
