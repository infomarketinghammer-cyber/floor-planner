"""Dashboards (PRD 4.20, 4.21): figures, insights and trends built from data the app already
keeps. Money is only included for roles that can see costs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.material import DecimalStr, ProductKind

# --- Project dashboard: summary, insights, analytics ---------------------------------------------


class Insight(BaseModel):
    key: str  # stable id, e.g. "high_waste:<room id>"
    severity: Literal["warning", "info"]
    title: str
    text: str  # what it means and what to do about it
    room_id: str | None = None


class DashRoom(BaseModel):
    room_id: str
    name: str
    floor: str | None
    room_type: str
    tile_id: str
    tile: str  # "600 × 600 mm Ivory matt"
    area_mm2: DecimalStr  # usable area
    boxes: int
    linear_mm: DecimalStr | None  # roll goods
    extra_pct: DecimalStr  # bought over usable: cuts + spare + last-box rounding
    cut_waste_pct: DecimalStr
    rounding_tiles: int
    cost: DecimalStr | None
    budget_share_pct: DecimalStr | None  # this room's cost as a share of the budget


class DashTile(BaseModel):
    tile_id: str
    tile: str
    kind: ProductKind
    rooms: int
    boxes: int
    boxes_if_pooled: int
    linear_mm: DecimalStr | None
    area_mm2: DecimalStr
    cost: DecimalStr | None  # rooms using this tile, when priced


class CostPart(BaseModel):
    label: str  # Floor tiles, Wall tiles, Skirting, Sundries, Labour, Delivery, Other, Tax
    amount: DecimalStr


class Money(BaseModel):
    currency: str
    locale: str


class BlueprintStatus(BaseModel):
    id: str
    filename: str
    kind: str  # pdf | image | dxf | dwg
    status: str  # done | no_rooms | partial | unavailable | not_read
    message: str
    rooms_found: int
    rooms_flagged: int


class ReviewStatus(BaseModel):
    rooms: int
    confirmed: int
    to_review: int
    skipped: int
    from_plans: int  # read from a plan (rest were typed or imported)
    with_issues: int
    unit_pending: bool


class HistoryPoint(BaseModel):
    at: datetime
    label: str
    user_name: str | None
    ready: bool
    boxes: int | None
    extra_pct: DecimalStr | None
    cost: DecimalStr | None
    budget: DecimalStr | None


class TimelineEvent(BaseModel):
    at: datetime
    label: str
    detail: str | None = None
    user_name: str | None


class ProjectDashboardOut(BaseModel):
    ready: bool
    blockers: list[str]
    costs_visible: bool
    money: Money | None
    rooms_count: int
    area_mm2: DecimalStr
    boxes: int | None
    extra_pct: DecimalStr | None
    cut_waste_pct: DecimalStr | None
    cost_total: DecimalStr | None
    budget: DecimalStr | None
    budget_status: Literal["under", "near", "over"] | None
    rooms: list[DashRoom]
    tiles: list[DashTile]
    cost_parts: list[CostPart]
    insights: list[Insight]
    review: ReviewStatus
    blueprints: list[BlueprintStatus]
    history: list[HistoryPoint]  # oldest first
    timeline: list[TimelineEvent]  # newest first


# --- Business dashboard (contractors, PRD 4.21) -----------------------------------------------------


class QuoteRow(BaseModel):
    quote_id: str
    project_id: str
    project_name: str
    client: str
    number: str
    version: int
    status: str
    total: DecimalStr
    margin_amount: DecimalStr
    currency: str
    locale: str
    created_at: datetime
    sent_at: datetime | None


class TileUsage(BaseModel):
    tile: str
    projects: int
    rooms: int
    boxes: int
    typical_extra_pct: DecimalStr  # median across the rooms using it


class MonthRow(BaseModel):
    month: str  # "2026-10"
    projects: int
    area_mm2: DecimalStr
    quoted: DecimalStr  # latest quote totals, in the main currency


class BusinessOut(BaseModel):
    money: Money | None  # the currency most quotes use; others are counted separately
    quotes: int
    by_status: dict[str, int]
    quoted_total: DecimalStr
    approved_total: DecimalStr
    margin_total: DecimalStr  # on approved quotes
    margin_pct: DecimalStr | None  # margin ÷ approved subtotal
    conversion_pct: DecimalStr | None  # approved ÷ decided (approved + rejected)
    other_currency_quotes: int
    recent_quotes: list[QuoteRow]
    projects: int
    tiles: list[TileUsage]
    months: list[MonthRow]  # oldest first


# --- Team and role-based dashboard (PRD 4.21) -------------------------------------------------------


class PendingItem(BaseModel):
    kind: Literal["approve", "awaiting_client", "comments", "changes_requested", "review_rooms"]
    project_id: str
    project_name: str
    text: str
    at: datetime | None


class ActivityRow(BaseModel):
    project_id: str
    project_name: str
    at: datetime
    label: str
    user_name: str | None


class MemberActivity(BaseModel):
    user_name: str
    role: str
    changes_30d: int
    last_at: datetime | None


class TeamSummary(BaseModel):
    id: str
    name: str
    my_role: str
    projects: int
    members: list[MemberActivity]


class TeamDashboardOut(BaseModel):
    roles: dict[str, int]  # projects by my role on them
    pending: list[PendingItem]
    activity: list[ActivityRow]  # newest first
    teams: list[TeamSummary]


# --- Platform and accuracy (admins, PRD 4.21) -------------------------------------------------------


class SourceAccuracy(BaseModel):
    source: str  # "PDF with text", "Scanned PDF", "Photo or image", "CAD drawing"
    read: int
    reviewed: int
    correct: int
    accuracy_pct: DecimalStr | None


class FieldCorrections(BaseModel):
    field: Literal["name", "length", "width", "unit"]
    corrected: int
    checked: int
    rate_pct: DecimalStr | None


class FailurePattern(BaseModel):
    label: str
    count: int
    wrong_pct: (
        DecimalStr | None
    )  # of the rooms with this pattern, how many were corrected or deleted


class WeekPoint(BaseModel):
    week: str  # Monday, ISO date
    right: int = 0
    wrong: int = 0
    signups: int = 0
    projects: int = 0
    uploads: int = 0
    exports: int = 0
    quotes: int = 0


class PlatformOut(BaseModel):
    users: int
    active_users_30d: int
    projects: int
    uploads: int
    exports: int
    by_source: list[SourceAccuracy]
    fields: list[FieldCorrections]
    patterns: list[FailurePattern]
    read_failures: dict[str, int]  # plan files by extraction status
    weeks: list[WeekPoint]  # oldest first, last 12 weeks
