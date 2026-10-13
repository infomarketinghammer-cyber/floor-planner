"""Dashboard summary figures for a project (PRD 4.20). Pure functions, no I/O."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.engine.units import mm2_to_sqft, mm2_to_sqm
from app.schemas.material import ProjectMaterial
from app.schemas.project import ProjectOut, Room
from app.services.materials import effective, project_default
from app.services.plan_units import plan_unit_state

_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class ProjectSummary:
    room_count: int
    total_area_mm2: Decimal
    unconfirmed_rooms: int
    rooms_missing_size: int
    rooms_missing_tile: int

    @property
    def needs_attention(self) -> bool:
        return bool(self.unconfirmed_rooms or self.rooms_missing_size or self.rooms_missing_tile)


def summarize(rooms: list[Room], default: ProjectMaterial | None = None) -> ProjectSummary:
    """Skipped rooms count towards room_count but not confirmation, area or material checks."""
    total_area = Decimal(0)
    missing_size = missing_tile = unconfirmed = 0

    for room in rooms:
        if room.skipped:  # needs no tiling, so nothing to confirm or assign (PRD 4.6)
            continue
        if not room.confirmed:
            unconfirmed += 1
        if room.floor_area_mm2 is None:
            missing_size += 1
        else:
            total_area += room.floor_area_mm2
        if effective(room, default or ProjectMaterial()).tile is None:
            missing_tile += 1

    return ProjectSummary(
        room_count=len(rooms),
        total_area_mm2=total_area,
        unconfirmed_rooms=unconfirmed,
        rooms_missing_size=missing_size,
        rooms_missing_tile=missing_tile,
    )


def _display(area: Decimal) -> float:
    return float(area.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def project_out(doc: dict) -> ProjectOut:
    rooms = [Room.model_validate(r) for r in doc.get("rooms", [])]
    summary = summarize(rooms, project_default(doc))
    unit_unconfirmed = plan_unit_state(doc, rooms).needs_confirmation
    return ProjectOut(
        id=str(doc["_id"]),
        owner_id=str(doc["owner_id"]),
        name=doc["name"],
        notes=doc.get("notes"),
        status=doc["status"],
        room_count=summary.room_count,
        total_area_sqft=_display(mm2_to_sqft(summary.total_area_mm2)),
        total_area_sqm=_display(mm2_to_sqm(summary.total_area_mm2)),
        unconfirmed_rooms=summary.unconfirmed_rooms,
        rooms_missing_size=summary.rooms_missing_size,
        rooms_missing_tile=summary.rooms_missing_tile,
        unit_unconfirmed=unit_unconfirmed,
        needs_attention=summary.needs_attention or unit_unconfirmed,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        last_exported_at=doc.get("last_exported_at"),
    )
