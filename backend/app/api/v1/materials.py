"""Material assignment (PRD 4.6): project defaults, per-room overrides, exclusions, skipping."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.api.deps import CurrentUser
from app.api.v1.rooms import _CHANGED_ELSEWHERE, _replace_rooms, _rooms, rooms_out
from app.db.mongo import get_db
from app.engine.dimensions import DimensionError, parse_length
from app.engine.layouts import MAX_DRAWN_TILES, layout_tiles, roll_drops
from app.engine.units import LengthUnit
from app.schemas.extras import ExtrasSettings, ExtrasSettingsIn, Opening, RoomWallsIn, WallTiling
from app.schemas.material import (
    MATERIAL_FIELDS,
    DefaultMaterialIn,
    Exclusion,
    ExclusionsIn,
    Layout,
    ProductKind,
    ProjectMaterial,
    RoomsMaterialIn,
    TileRef,
)
from app.schemas.project import RoomOrigin, RoomPart, RoomsOut
from app.services.estimate import build_estimate, room_parts
from app.services.extras import extras_settings
from app.services.history import record_version
from app.services.materials import effective, load_tile_ref, project_default, tile_ref_from_doc
from app.services.projects import get_project_or_404
from app.services.review import review_state
from app.services.suggestions import SuggestionOut, suggestions
from app.services.tile_advice import TileAdviceOut, advise
from app.services.tile_updates import TileUpdateOut, apply_updates, find_updates

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
        brick_offset_pct=body.brick_offset_pct,
        reuse_offcuts=body.reuse_offcuts,
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
    await record_version(doc)
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


# --- Layouts (PRD 4.16) -------------------------------------------------------------------------


class RoomPartIn(BaseModel):
    label: str = Field(default="", max_length=40)
    length: str = Field(min_length=1, max_length=30)
    width: str = Field(min_length=1, max_length=30)
    x: str | None = Field(default=None, max_length=30)  # position from the room's top-left
    y: str | None = Field(default=None, max_length=30)


class RoomPartsIn(BaseModel):
    """Split a room into rectangles. An empty list puts it back to one rectangle (the first
    part). The room is un-confirmed, since its size changed."""

    parts: list[RoomPartIn] = Field(max_length=12)
    perimeter: str | None = Field(default=None, max_length=30)
    unit: LengthUnit = LengthUnit.FT_IN
    version: int


@router.put("/rooms/{room_id}/parts", response_model=RoomsOut)
async def set_room_parts(
    project_id: str, room_id: str, body: RoomPartsIn, user: CurrentUser
) -> RoomsOut:
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    rooms = _rooms(project)
    room = next((r for r in rooms if r.id == room_id), None)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    if len(body.parts) == 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Split a room into at least two rectangles, or give it one length and width.",
        )
    parts, next_x = [], Decimal(0)
    for i, p in enumerate(body.parts, start=1):
        label = p.label.strip() or f"Part {i}"
        length = _length(p.length, body.unit, f"{label} length")
        width = _length(p.width, body.unit, f"{label} width")
        x = _length(p.x, body.unit, f"{label} position") if p.x else next_x
        y = _length(p.y, body.unit, f"{label} position") if p.y else Decimal(0)
        parts.append(
            RoomPart(
                id=uuid.uuid4().hex[:8],
                label=label,
                length_mm=length,
                width_mm=width,
                x_mm=x,
                y_mm=y,
            )
        )
        next_x = max(next_x, x + length)
    if parts:
        room.parts = parts
        room.length_mm = room.width_mm = room.area_mm2 = None
    else:  # back to a plain rectangle: keep the main part
        if room.parts:
            room.length_mm, room.width_mm = room.parts[0].length_mm, room.parts[0].width_mm
        room.parts = []
    room.perimeter_mm = _length(body.perimeter, body.unit, "Perimeter") if body.perimeter else None
    room.unit = body.unit
    room.confirmed = False
    if room.origin == RoomOrigin.AUTO:
        room.origin = RoomOrigin.EDITED
    return await _replace_rooms(project, rooms)


class LayoutTileOut(BaseModel):
    points: list[tuple[float, float]]
    cut: bool


class RoomLayoutOut(BaseModel):
    room_id: str
    name: str
    layout: str
    tile: TileRef
    parts: list[tuple[float, float, float, float]]  # x, y, length, width (mm)
    tiles: list[LayoutTileOut]
    total: int
    cut: int
    too_many: bool  # too many tiles to draw; counts still given
    estimate_tiles: int | None  # the estimate's tile count, before the breakage buffer
    note: str | None  # when the drawing illustrates rather than counts


@router.get("/rooms/{room_id}/layout", response_model=RoomLayoutOut)
async def room_layout(project_id: str, room_id: str, user: CurrentUser) -> RoomLayoutOut:
    """The room drawn tile by tile, cut tiles marked (PRD 4.16)."""
    project = await get_project_or_404(user, project_id)
    state = review_state(project)
    room = next((r for r in state.rooms if r.id == room_id), None)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    default = project_default(project)
    eff = effective(room, default)
    parts = room_parts(room)
    if eff.tile is None or parts is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Choose a tile and give the room a length and width (or split it into rectangles) "
            "to see its layout.",
        )
    estimate = build_estimate(state, default, extras_settings(project))
    est = next((r for r in estimate.rooms if r.room_id == room_id), None)
    tile = eff.tile
    note = None
    if tile.kind == ProductKind.ROLL:
        placed = roll_drops(parts, tile.width_mm)
        layout = "roll"
    else:
        layout = "brick" if tile.kind == ProductKind.PLANK else eff.layout.value
        placed = layout_tiles(
            parts, tile.length_mm, tile.width_mm, layout, default.brick_offset_pct
        )
        if tile.kind == ProductKind.PLANK:
            note = "Planks drawn in staggered rows; the quantity is the area plus an allowance."
        elif eff.layout == Layout.DIAGONAL:
            note = "The quantity uses the area plus an allowance for diagonal cuts, not this count."
    if est and est.reuse_applied:
        note = "The quantity counts on reusing offcuts, so it is lower than the tiles drawn."
    too_many = len(placed) > MAX_DRAWN_TILES
    return RoomLayoutOut(
        room_id=room.id,
        name=room.name,
        layout=layout,
        tile=tile,
        parts=[(float(p.x), float(p.y), float(p.length), float(p.width)) for p in parts],
        tiles=[]
        if too_many
        else [
            LayoutTileOut(points=[(round(x, 1), round(y, 1)) for x, y in t.points], cut=t.cut)
            for t in placed
        ],
        total=len(placed),
        cut=sum(t.cut for t in placed),
        too_many=too_many,
        estimate_tiles=est.tiles_needed if est and tile.kind != ProductKind.ROLL else None,
        note=note,
    )


@router.get("/tile-advice", response_model=TileAdviceOut)
async def tile_advice(project_id: str, user: CurrentUser) -> TileAdviceOut:
    """The tile size that wastes least, per room and for the project default (PRD 4.16)."""
    project = await get_project_or_404(user, project_id)
    state = review_state(project)
    default = project_default(project)
    estimate = build_estimate(state, default, extras_settings(project))
    library = [
        t
        async for t in get_db().tiles.find(
            {
                "archived": {"$ne": True},
                "$or": [
                    {"scope": "catalog"},
                    {"owner_id": {"$in": [user["_id"], project["owner_id"]]}},
                ],
            }
        )
    ]
    return advise(state.rooms, default, estimate, library)


# --- Library tile changes (PRD 4.12) ------------------------------------------------------------


class TileUpdatesIn(BaseModel):
    tile_ids: list[str] = Field(min_length=1, max_length=50)
    version: int


async def _library_by_id(project: dict, user: dict, ids: list[str]) -> dict[str, dict]:
    oids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
    docs = get_db().tiles.find(
        {
            "_id": {"$in": oids},
            "$or": [
                {"scope": "catalog"},
                {"owner_id": {"$in": [user["_id"], project["owner_id"]]}},
            ],
        }
    )
    return {str(d["_id"]): d async for d in docs}


def _used_tile_ids(project: dict) -> list[str]:
    state = review_state(project)
    default, extras = project_default(project), extras_settings(project)
    ids = {t.id for t in (default.tile, extras.wall_tile) if t}
    for r in state.rooms:
        ids |= {t.id for t in (r.material.tile, r.walls.tile if r.walls else None) if t}
    return sorted(ids)


@router.get("/tile-updates", response_model=list[TileUpdateOut])
async def tile_updates(project_id: str, user: CurrentUser) -> list[TileUpdateOut]:
    """Tiles that changed in the library since this project chose them."""
    project = await get_project_or_404(user, project_id)
    library = await _library_by_id(project, user, _used_tile_ids(project))
    state = review_state(project)
    return find_updates(state.rooms, project_default(project), extras_settings(project), library)


@router.post("/tile-updates/apply", response_model=RoomsOut)
async def apply_tile_updates(project_id: str, body: TileUpdatesIn, user: CurrentUser) -> RoomsOut:
    """Use the library's current version of these tiles everywhere in the project, and
    recalculate. Undoable."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, body.version)
    library = await _library_by_id(project, user, body.tile_ids)
    fresh = {i: tile_ref_from_doc(d) for i, d in library.items() if not d.get("archived")}
    if not fresh:
        raise HTTPException(status.HTTP_409_CONFLICT, "Those tiles are no longer in the library.")
    rooms, default, extras = apply_updates(
        _rooms(project), project_default(project), extras_settings(project), fresh
    )
    return await _replace_rooms(
        project,
        rooms,
        {"default_material": default.model_dump(), "extras_settings": extras.model_dump()},
    )
