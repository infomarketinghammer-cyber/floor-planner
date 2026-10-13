"""Material assignment (PRD 4.6): project defaults, per-room overrides, exclusions, skipping."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pymongo import ReturnDocument

from app.api.deps import CurrentUser
from app.api.v1.rooms import _CHANGED_ELSEWHERE, _replace_rooms, _rooms, rooms_out
from app.db.mongo import get_db
from app.engine.dimensions import DimensionError, parse_length
from app.schemas.extras import ExtrasSettings, ExtrasSettingsIn, Opening, RoomWallsIn, WallTiling
from app.schemas.material import (
    MATERIAL_FIELDS,
    DefaultMaterialIn,
    Exclusion,
    ExclusionsIn,
    ProjectMaterial,
    RoomsMaterialIn,
)
from app.schemas.project import RoomsOut
from app.services.extras import extras_settings
from app.services.materials import load_tile_ref, project_default
from app.services.projects import get_project_or_404
from app.services.review import review_state
from app.services.suggestions import SuggestionOut, suggestions

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


# --- Additional materials (PRD 4.15) ------------------------------------------------------------


def _length(text: str, unit, label: str):
    try:
        return parse_length(text, unit)
    except DimensionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{label}: {e}") from None


@router.put("/rooms/{room_id}/walls", response_model=RoomsOut)
async def set_room_walls(
    project_id: str, room_id: str, body: RoomWallsIn, user: CurrentUser
) -> RoomsOut:
    """A room's doors and windows, wall tiling and skirting choice. Undoable like any room edit."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    rooms = _rooms(project)
    room = next((r for r in rooms if r.id == room_id), None)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")

    room.openings = [
        Opening(
            id=uuid.uuid4().hex[:8],
            kind=o.kind,
            label=o.label.strip(),
            width_mm=_length(o.width, o.unit, o.label or "Opening width"),
            height_mm=_length(o.height, o.unit, o.label or "Opening height"),
            quantity=o.quantity,
            unit=o.unit,
        )
        for o in body.openings
    ]
    if body.walls is None:
        room.walls = None
    else:
        w = body.walls
        room.walls = WallTiling(
            height_mm=_length(w.height, w.unit, "Tiling height"),
            tile=await load_tile_ref(w.tile_id, user, project) if w.tile_id else None,
            breakage_pct=w.breakage_pct,
            length_mm=_length(w.length, w.unit, "Wall length") if w.length else None,
            price=w.price,
        )
    room.skirting = body.skirting
    return await _replace_rooms(project, rooms)


@router.put("/extras/settings", response_model=RoomsOut)
async def set_extras_settings(
    project_id: str, body: ExtrasSettingsIn, user: CurrentUser
) -> RoomsOut:
    """Default wall tile, skirting and sundries. Like cost settings, not a room change: it
    doesn't bump the rooms version or add an undo step."""
    project = await get_project_or_404(user, project_id)
    settings = ExtrasSettings(
        wall_tile=await load_tile_ref(body.wall_tile_id, user, project)
        if body.wall_tile_id
        else None,
        wall_breakage_pct=body.wall_breakage_pct,
        wall_price=body.wall_price,
        skirting=body.skirting,
        sundries=body.sundries,
    )
    doc = await get_db().projects.find_one_and_update(
        {"_id": project["_id"]},
        {"$set": {"extras_settings": settings.model_dump(), "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    return rooms_out(doc)


@router.get("/suggestions", response_model=list[SuggestionOut])
async def room_suggestions(project_id: str, user: CurrentUser) -> list[SuggestionOut]:
    """Suggested tiles and wall tiling by room type, each with an action to apply."""
    project = await get_project_or_404(user, project_id)
    tiles = [
        {**t, "id": str(t["_id"])}
        async for t in get_db()
        .tiles.find(
            {
                "archived": {"$ne": True},
                "$or": [
                    {"scope": "catalog"},
                    {"owner_id": {"$in": [user["_id"], project["owner_id"]]}},
                ],
            }
        )
        .sort("name", 1)
    ]
    state = review_state(project)
    return suggestions(state.rooms, project_default(project), extras_settings(project), tiles)
