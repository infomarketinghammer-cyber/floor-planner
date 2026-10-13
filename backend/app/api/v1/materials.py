"""Material assignment (PRD 4.6): project defaults, per-room overrides, exclusions, skipping."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.api.v1.rooms import _CHANGED_ELSEWHERE, _replace_rooms, _rooms
from app.engine.dimensions import DimensionError, parse_length
from app.schemas.material import (
    MATERIAL_FIELDS,
    DefaultMaterialIn,
    Exclusion,
    ExclusionsIn,
    ProjectMaterial,
    RoomsMaterialIn,
)
from app.schemas.project import RoomsOut
from app.services.materials import load_tile_ref
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}", tags=["materials"])


def _check_version(project: dict, version: int) -> None:
    if (project.get("rooms_version") or 0) != version:
        raise HTTPException(status.HTTP_409_CONFLICT, _CHANGED_ELSEWHERE)


@router.put("/materials/default", response_model=RoomsOut)
async def set_default_material(
    project_id: str, body: DefaultMaterialIn, user: CurrentUser
) -> RoomsOut:
    """Project-wide settings every room uses unless it overrides them."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    default = ProjectMaterial(
        tile=await load_tile_ref(body.tile_id, user, project) if body.tile_id else None,
        layout=body.layout,
        breakage_pct=body.breakage_pct,
        price=body.price,
    )
    return await _replace_rooms(
        project, _rooms(project), {"default_material": default.model_dump()}
    )


@router.post("/rooms/materials", response_model=RoomsOut)
async def set_rooms_material(project_id: str, body: RoomsMaterialIn, user: CurrentUser) -> RoomsOut:
    """Change settings on selected rooms: set fields (edit, or copy from another room), reset
    fields to the project default (`inherit`), and/or mark rooms as needing no tiling."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    rooms = _rooms(project)
    wanted = set(body.room_ids)
    if missing := wanted - {r.id for r in rooms}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{len(missing)} room(s) not found")
    sent = body.set.model_fields_set
    sent_fields = {"tile" if f == "tile_id" else f for f in sent}  # same names as `inherit`
    if overlap := sent_fields & set(body.inherit):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Can't both set and reset: {', '.join(sorted(overlap))}",
        )

    tile = await load_tile_ref(body.set.tile_id, user, project) if body.set.tile_id else None
    for room in rooms:
        if room.id not in wanted:
            continue
        material = room.material
        if "tile_id" in sent:
            material.tile = tile
        for field in ("layout", "breakage_pct", "price"):
            if field in sent:
                setattr(material, field, getattr(body.set, field))
        for field in body.inherit:
            if field in MATERIAL_FIELDS:
                setattr(material, field, None)
        if body.skipped is not None:
            room.skipped = body.skipped
    return await _replace_rooms(project, rooms)


@router.put("/rooms/{room_id}/exclusions", response_model=RoomsOut)
async def set_exclusions(
    project_id: str, room_id: str, body: ExclusionsIn, user: CurrentUser
) -> RoomsOut:
    """Replace a room's untiled areas (cabinets, columns, a bathtub...)."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    rooms = _rooms(project)
    room = next((r for r in rooms if r.id == room_id), None)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")

    exclusions = []
    for item in body.exclusions:
        try:
            length, width = (
                parse_length(item.length, item.unit),
                parse_length(item.width, item.unit),
            )
        except DimensionError as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{item.label}: {e}"
            ) from None
        exclusions.append(
            Exclusion(
                id=uuid.uuid4().hex[:8],
                label=item.label.strip(),
                length_mm=length,
                width_mm=width,
                quantity=item.quantity,
                unit=item.unit,
            )
        )

    if room.length_mm is not None and room.width_mm is not None:
        total = sum((e.length_mm * e.width_mm * e.quantity for e in exclusions), 0)
        if total >= room.length_mm * room.width_mm:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The exclusions cover the whole room. If it needs no tiles, mark it as not tiled instead.",
            )
    room.exclusions = exclusions
    return await _replace_rooms(project, rooms)
