from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.engine.units import LengthUnit
from app.schemas.cost import CostOut, CostSettings
from app.schemas.estimate import EstimateOut
from app.schemas.extras import ExtrasSettings, Opening, WallTiling
from app.schemas.material import (
    DecimalStr,
    EffectiveMaterial,
    Exclusion,
    MaterialOverride,
    MaterialsSummaryOut,
    ProjectMaterial,
)


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    CALCULATED = "calculated"
    EXPORTED = "exported"


class RoomOrigin(StrEnum):
    AUTO = "auto"  # extracted from the blueprint, untouched
    EDITED = "edited"  # extracted, then corrected by the user
    MANUAL = "manual"  # typed in by the user
    IMPORTED = "imported"  # from an Excel/CSV room list


class RoomSource(BaseModel):
    """Where an extracted room was read from (PRD 4.2), for the plan overlay and audit."""

    file_id: str
    page: int
    method: Literal["pdf_text", "dxf_text", "vision"]
    bbox: list[float] | None = (
        None  # [x0, y0, x1, y1] fractions of the page preview, top-left origin
    )
    name_bbox: list[float] | None = None
    size_bbox: list[float] | None = None
    text: str = ""  # exactly what was read


class RoomPart(BaseModel):
    """One rectangle of a non-rectangular room (PRD 4.16), placed from the room's top-left."""

    id: str
    label: str = Field(default="", max_length=40)
    length_mm: DecimalStr = Field(gt=0)
    width_mm: DecimalStr = Field(gt=0)
    x_mm: DecimalStr = Field(default=Decimal(0), ge=0)
    y_mm: DecimalStr = Field(default=Decimal(0), ge=0)


class ExtractedValues(BaseModel):
    """What extraction read, kept unchanged through later edits (PRD 4.13), so corrections
    can be measured against it."""

    name: str
    length_mm: DecimalStr | None = None
    width_mm: DecimalStr | None = None
    unit: LengthUnit = LengthUnit.FT_IN


class Room(BaseModel):
    """A room as stored inside a project. Dimensions are canonical millimetres;
    `unit` is only how the user entered/sees them."""

    id: str
    name: str = Field(min_length=1, max_length=100)
    floor: str | None = None
    length_mm: Decimal | None = Field(default=None, gt=0)
    width_mm: Decimal | None = Field(default=None, gt=0)
    unit: LengthUnit = LengthUnit.FT
    confirmed: bool = False
    skipped: bool = False  # no tiling needed
    material: MaterialOverride = Field(
        default_factory=MaterialOverride
    )  # PRD 4.6; empty = all default
    exclusions: list[Exclusion] = Field(default_factory=list)  # untiled areas: cabinets, columns
    # Floor area for odd-shaped rooms known only by area (PRD 4.7 fallback); ignored when
    # length and width are both set.
    area_mm2: DecimalStr | None = Field(default=None, gt=0)

    # A non-rectangular room split into rectangles (PRD 4.16). When set, length, width and
    # area are cleared: the parts are the room.
    parts: list[RoomPart] = Field(default_factory=list, max_length=12)
    # Perimeter for skirting and wall tiles where it can't be worked out (split or area-only
    # rooms). None: 2 × (length + width) for a rectangular room.
    perimeter_mm: DecimalStr | None = Field(default=None, gt=0)

    @property
    def floor_area_mm2(self) -> Decimal | None:
        if self.parts:
            return sum((p.length_mm * p.width_mm for p in self.parts), Decimal(0))
        if self.length_mm is not None and self.width_mm is not None:
            return self.length_mm * self.width_mm
        return self.area_mm2

    @property
    def area_only(self) -> bool:
        return (
            not self.parts
            and (self.length_mm is None or self.width_mm is None)
            and self.area_mm2 is not None
        )

    origin: RoomOrigin = RoomOrigin.MANUAL
    # Extraction metadata (PRD 4.2, 6.3): set only for rooms read from a blueprint.
    confidence: float | None = None  # 0..1
    confidence_level: Literal["high", "medium", "low"] | None = None
    flags: list[str] = Field(default_factory=list)
    unit_explicit: bool = True  # False when the unit was assumed, not written on the plan
    source: RoomSource | None = None
    extracted: ExtractedValues | None = None  # set once, at extraction; never edited
    # Additional materials (PRD 4.15)
    openings: list[Opening] = Field(default_factory=list)  # doors and windows
    walls: WallTiling | None = None  # None: walls not tiled
    skirting: bool | None = None  # None: follow the project setting

    @field_serializer("length_mm", "width_mm")
    def _decimal_as_str(self, value: Decimal | None) -> str | None:
        # Stored and sent as strings so no precision is lost to float.
        return None if value is None else str(value)


class RoomCreate(BaseModel):
    """Manual entry. Lengths are text so users can type 12'6", 3.6 m, 3600 etc."""

    name: str = Field(min_length=1, max_length=100)
    floor: str | None = Field(default=None, max_length=50)
    length: str | None = Field(default=None, min_length=1, max_length=30)
    width: str | None = Field(default=None, min_length=1, max_length=30)
    unit: LengthUnit = LengthUnit.FT_IN
    # Odd-shaped room known only by area: give `area` instead of length and width.
    area: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    area_unit: Literal["sqft", "sqm"] = "sqft"


class RoomImportError(BaseModel):
    row: int
    message: str


class RoomImportOut(BaseModel):
    dry_run: bool
    rooms: list[Room]  # parsed rooms (preview) or the rooms actually added
    errors: list[RoomImportError]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    id: str
    owner_id: str
    name: str
    notes: str | None = None
    status: ProjectStatus
    room_count: int
    # Display-only figures for dashboards; quantities always come from the engine.
    total_area_sqft: float
    total_area_sqm: float
    unconfirmed_rooms: int
    rooms_missing_size: int
    rooms_missing_tile: int
    unit_unconfirmed: bool  # rooms came from a plan and the plan unit isn't confirmed (PRD 4.4)
    needs_attention: bool
    created_at: datetime
    updated_at: datetime
    last_exported_at: datetime | None = None
    # Collaboration (PRD 4.18): the viewer's role on this project, and its sharing state.
    my_role: Literal["owner", "contractor", "designer", "homeowner"] = "owner"
    team_id: str | None = None
    shared: bool = False  # a read-only link is active
    approval_requested_at: datetime | None = None


# --- Review (PRD 4.3) ------------------------------------------------------------------


class RoomUpdate(BaseModel):
    """Inline edit. Lengths are text in `unit` (or with their own marks, e.g. 12'6", 3.6 m)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    floor: str | None = Field(default=None, max_length=50)
    length: str | None = Field(default=None, min_length=1, max_length=30)
    width: str | None = Field(default=None, min_length=1, max_length=30)
    unit: LengthUnit | None = None
    area: Decimal | None = Field(default=None, gt=0, le=1_000_000)  # area-only rooms
    area_unit: Literal["sqft", "sqm"] = "sqft"
    skipped: bool | None = None  # no tiling needed (PRD 4.6)
    # True: drop this room's own unit and follow the plan unit (numbers are re-read in it).
    follow_plan_unit: bool | None = None
    confirmed: bool | None = None


class RoomsConfirm(BaseModel):
    room_ids: list[str] = Field(min_length=1, max_length=1000)
    confirmed: bool = True


class RoomsRestore(BaseModel):
    """Undo/redo: put back an earlier snapshot of the room list."""

    version: int  # the version the client last saw; mismatches are rejected (409)
    rooms: list[Room] = Field(max_length=1000)
    plan_unit: LengthUnit | None = None  # the confirmed plan unit at the time of the snapshot
    plan_unit_confirmed: bool = False
    default_material: ProjectMaterial | None = None  # project defaults at the time of the snapshot


class PlanUnitSet(BaseModel):
    unit: LengthUnit
    version: int  # rooms version the client last saw


class PlanUnitOut(BaseModel):
    unit: LengthUnit | None
    confirmed: bool
    detected: LengthUnit | None
    evidence: str
    required: bool


class IssueOut(BaseModel):
    code: str
    severity: Literal["block", "warn"]
    message: str


class RoomOut(Room):
    issues: list[IssueOut] = Field(default_factory=list)
    effective: EffectiveMaterial  # settings actually used: room override, else project default
    exclusion_area_mm2: DecimalStr
    usable_area_mm2: DecimalStr | None  # room area minus exclusions


class ReviewSummaryOut(BaseModel):
    total: int
    confirmed: int
    to_review: int
    with_issues: int
    blocking: int
    unit_pending: bool
    ready: bool


class RoomsOut(BaseModel):
    version: int
    rooms: list[RoomOut]
    review: ReviewSummaryOut
    plan_unit: PlanUnitOut
    default_material: ProjectMaterial
    materials: MaterialsSummaryOut
    estimate: EstimateOut  # recalculated on every change (PRD 4.7)
    cost_settings: CostSettings
    extras_settings: ExtrasSettings
    cost: CostOut | None  # PRD 4.10; None until the quantities are ready
