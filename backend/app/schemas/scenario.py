"""Scenarios (PRD 4.17): the same project with different tiles or layouts, side by side.

A scenario replaces the project's default material and, optionally, the tile or layout of
particular rooms. Everything else (rooms, untiled areas, walls, costs) is the project's own, so
options compare like for like.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.material import DecimalStr, Layout, Price, ProjectMaterial, TileRef


class ScenarioRoom(BaseModel):
    """A room-specific choice inside a scenario."""

    room_id: str
    tile: TileRef | None = None  # None: the scenario's default tile
    layout: Layout | None = None


class Scenario(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=300)
    default: ProjectMaterial
    # True: the scenario's tile goes in every room, replacing rooms' own tiles (except rooms
    # listed below). False: rooms with their own tile keep it (anti-skid bathrooms stay).
    every_room: bool = False
    rooms: list[ScenarioRoom] = Field(default_factory=list, max_length=1000)
    created_at: datetime
    updated_at: datetime


# --- Requests -----------------------------------------------------------------------------------


class ScenarioRoomIn(BaseModel):
    room_id: str
    tile_id: str | None = None
    layout: Layout | None = None


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=300)
    tile_id: str | None = None  # None: keep the project's default tile
    layout: Layout | None = None  # None: keep the project's layout
    breakage_pct: Decimal | None = Field(default=None, ge=0, le=50)
    price: Price | None = None  # None: no price for this option's tile
    keep_price: bool = False  # true: keep the project's price (same tile, different layout)
    brick_offset_pct: Decimal | None = Field(default=None, ge=10, le=50)
    reuse_offcuts: bool | None = None
    every_room: bool = False
    rooms: list[ScenarioRoomIn] = Field(default_factory=list, max_length=1000)


class ScenarioFromCurrentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=300)


class ScenarioRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=300)


# --- Results ------------------------------------------------------------------------------------


class ScenarioTileOut(BaseModel):
    tile: TileRef
    rooms: int
    boxes: int
    linear_mm: DecimalStr | None  # roll goods


class ScenarioRoomOut(BaseModel):
    room_id: str
    name: str
    tile: TileRef
    layout: Layout
    boxes: int
    extra_pct: DecimalStr
    cost: DecimalStr | None


Badge = Literal["lowest_waste", "lowest_cost", "fewest_boxes", "within_budget", "over_budget"]


class ScenarioResultOut(BaseModel):
    id: str  # "current" for the project as it is
    name: str
    notes: str | None
    every_room: bool
    ready: bool
    blockers: list[str]
    tiles: list[ScenarioTileOut]
    boxes: int
    tiles_bought: int
    usable_area_mm2: DecimalStr
    bought_area_mm2: DecimalStr
    extra_area_mm2: DecimalStr
    extra_pct: DecimalStr
    cut_waste_pct: DecimalStr
    cost: DecimalStr | None  # project total incl. extras, lines and tax; None: no prices
    fully_priced: bool  # every room has a price, so the cost is complete
    budget_remaining: DecimalStr | None
    rooms: list[ScenarioRoomOut]
    badges: list[Badge]


class Recommendation(BaseModel):
    scenario_id: str
    reasons: list[str]  # plain-language, most important first


class SuggestedOption(BaseModel):
    """An option worth comparing that isn't saved yet, ready to add with one click."""

    key: str
    name: str
    reason: str
    tile: TileRef
    layout: Layout | None = None


class ComparisonOut(BaseModel):
    results: list[ScenarioResultOut]  # current first, then saved scenarios
    best: Recommendation | None
    suggestions: list[SuggestedOption]
