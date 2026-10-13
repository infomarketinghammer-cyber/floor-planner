"""Rooms: manual entry and Excel/CSV import (PRD 4.1), review and confirmation (PRD 4.3).

Every change returns the full room list with review issues, so the client always shows the
server's view and can snapshot it for undo/redo.
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile, status

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.engine.dimensions import DimensionError, parse_length
from app.engine.units import MM2_PER_SQFT, MM2_PER_SQM, LengthUnit
from app.schemas.project import (
    IssueOut,
    PlanUnitOut,
    PlanUnitSet,
    ReviewSummaryOut,
    Room,
    RoomCreate,
    RoomImportError,
    RoomImportOut,
    RoomOrigin,
    RoomOut,
    RoomsConfirm,
    RoomsOut,
    RoomsRestore,
    RoomUpdate,
)
from app.services.cost import build_cost, cost_settings
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import (
    effective,
    exclusion_area_mm2,
    materials_summary,
    project_default,
    usable_area_mm2,
)
from app.services.plan_units import apply_plan_unit, reinterpret
from app.services.projects import get_project_or_404, save_rooms
from app.services.review import blocking_issues, review_state, room_issues
from app.uploads.inspect import UploadError
from app.uploads.room_import import MAX_TABLE_BYTES, parse_room_table

router = APIRouter(prefix="/projects/{project_id}/rooms", tags=["rooms"])

MAX_ROOMS_PER_PROJECT = 1000
_CHANGED_ELSEWHERE = (
    "The rooms were changed somewhere else (another tab or device). Reload and try again."
)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _rooms(doc: dict) -> list[Room]:
    return [Room.model_validate(r) for r in doc.get("rooms", [])]


def rooms_out(doc: dict) -> RoomsOut:
    state = review_state(doc)
    pu = state.plan_unit
    default = project_default(doc)
    extras = extras_settings(doc)
    estimate = build_estimate(state, default, extras)
    settings = cost_settings(doc)
    return RoomsOut(
        version=doc.get("rooms_version") or 0,
        rooms=[
            RoomOut(
                **r.model_dump(),
                issues=[IssueOut(**i.__dict__) for i in state.issues[r.id]],
                effective=effective(r, default),
                exclusion_area_mm2=exclusion_area_mm2(r),
                usable_area_mm2=usable_area_mm2(r),
            )
            for r in state.rooms
        ],
        review=ReviewSummaryOut(**state.summary.__dict__),
        default_material=default,
        materials=materials_summary(state.rooms, default, state.summary.ready),
        estimate=estimate,
        cost_settings=settings,
        extras_settings=extras,
        cost=build_cost(state, default, estimate, settings, extras),
        plan_unit=PlanUnitOut(
            unit=pu.unit,
            confirmed=pu.confirmed,
            detected=pu.detected,
            evidence=pu.evidence,
            required=pu.required,
        ),
    )


async def _replace_rooms(project: dict, rooms: list[Room], extra: dict | None = None) -> RoomsOut:
    doc = await save_rooms(
        project["_id"],
        {"$set": {"rooms": [r.model_dump() for r in rooms], **(extra or {})}},
        expected_version=project.get("rooms_version") or 0,
    )
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, _CHANGED_ELSEWHERE)
    return rooms_out(doc)


def _check_capacity(current: int, adding: int) -> None:
    if current + adding > MAX_ROOMS_PER_PROJECT:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A project can have at most {MAX_ROOMS_PER_PROJECT} rooms."
        )


def area_to_mm2(value: Decimal, unit: str) -> Decimal:
    return value * (MM2_PER_SQFT if unit == "sqft" else MM2_PER_SQM)


def _parse(text: str, unit: LengthUnit):
    try:
        return parse_length(text, unit)
    except DimensionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.get("", response_model=RoomsOut)
async def list_rooms(project_id: str, user: CurrentUser) -> RoomsOut:
    return rooms_out(await get_project_or_404(user, project_id))


@router.post("", response_model=RoomsOut, status_code=status.HTTP_201_CREATED)
async def add_room(project_id: str, body: RoomCreate, user: CurrentUser) -> RoomsOut:
    project = await get_project_or_404(user, project_id)
    _check_capacity(len(project.get("rooms", [])), 1)
    has_sides = body.length is not None and body.width is not None
    if not has_sides and body.area is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the length and width, or the floor area."
        )
    room = Room(
        id=_new_id(),
        name=body.name.strip(),
        floor=(body.floor or "").strip() or None,
        length_mm=_parse(body.length, body.unit) if has_sides else None,
        width_mm=_parse(body.width, body.unit) if has_sides else None,
        area_mm2=None if has_sides else area_to_mm2(body.area, body.area_unit),
        unit=body.unit,
        origin=RoomOrigin.MANUAL,
    )
    return await _replace_rooms(project, [*_rooms(project), room])


@router.patch("/{room_id}", response_model=RoomsOut)
async def update_room(
    project_id: str, room_id: str, body: RoomUpdate, user: CurrentUser
) -> RoomsOut:
    """Edit a room inline. Changing the size or unit un-confirms it; renaming doesn't.
    Changing only the unit re-reads the same numbers in the new unit (fixes a wrong unit)."""
    project = await get_project_or_404(user, project_id)
    rooms = _rooms(project)
    room = next((r for r in rooms if r.id == room_id), None)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")

    changes = body.model_dump(exclude_unset=True)
    edited = False
    if "name" in changes and changes["name"].strip() != room.name:
        room.name = changes["name"].strip()
        edited = True
    if "floor" in changes:
        room.floor = (changes["floor"] or "").strip() or None
    if body.skipped is not None:
        room.skipped = body.skipped
    if {"length", "width", "unit"} & changes.keys():
        unit = body.unit or room.unit
        if body.length is not None:
            room.length_mm = _parse(body.length, unit)
        if body.width is not None:
            room.width_mm = _parse(body.width, unit)
        room.unit = unit
        room.unit_explicit = True  # the user has now seen and set the unit
        room.confirmed = False  # quantities would change: confirm again
        edited = True
        if room.length_mm is not None and room.width_mm is not None:
            room.area_mm2 = None  # sides now known: the grid method takes over
    if "area" in changes and body.area is not None:
        room.area_mm2 = area_to_mm2(body.area, body.area_unit)
        room.confirmed = False
        edited = True
    if body.follow_plan_unit:
        plan_unit = review_state(project, rooms).plan_unit.unit
        if plan_unit is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Set the plan unit first.")
        if plan_unit != room.unit:
            room.length_mm = reinterpret(room.length_mm, room.unit, plan_unit)
            room.width_mm = reinterpret(room.width_mm, room.unit, plan_unit)
            room.confirmed = False
            edited = True
        room.unit = plan_unit
        room.unit_explicit = False

    if edited and room.origin == RoomOrigin.AUTO:
        room.origin = RoomOrigin.EDITED  # PRD 4.13: track corrections to extracted values

    if body.confirmed is not None:
        if body.confirmed:
            blocking = blocking_issues(room, review_state(project, rooms).issues)
            if blocking:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, blocking[0].message)
        room.confirmed = body.confirmed

    return await _replace_rooms(project, rooms)


@router.post("/confirm", response_model=RoomsOut)
async def confirm_rooms(project_id: str, body: RoomsConfirm, user: CurrentUser) -> RoomsOut:
    """Confirm (or un-confirm) several rooms at once. Rooms with blocking issues can't be confirmed."""
    project = await get_project_or_404(user, project_id)
    rooms = _rooms(project)
    wanted = set(body.room_ids)
    if missing := wanted - {r.id for r in rooms}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{len(missing)} room(s) not found")

    if body.confirmed:
        issues = review_state(project, rooms).issues
        blocked = [r.name for r in rooms if r.id in wanted and blocking_issues(r, issues)]
        if blocked:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Fix these rooms before confirming them: {', '.join(blocked[:5])}"
                + (f" and {len(blocked) - 5} more" if len(blocked) > 5 else ""),
            )
    for room in rooms:
        if room.id in wanted:
            room.confirmed = body.confirmed
    return await _replace_rooms(project, rooms)


@router.put("", response_model=RoomsOut)
async def restore_rooms(project_id: str, body: RoomsRestore, user: CurrentUser) -> RoomsOut:
    """Undo/redo: replace the room list with an earlier snapshot, if nothing changed meanwhile."""
    project = await get_project_or_404(user, project_id)
    if (project.get("rooms_version") or 0) != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, _CHANGED_ELSEWHERE)
    if len({r.id for r in body.rooms}) != len(body.rooms):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Room ids must be unique")
    # A snapshot can't smuggle in a confirmed room that has blocking issues.
    issues = room_issues(body.rooms)
    for room in body.rooms:
        if room.confirmed and blocking_issues(room, issues):
            room.confirmed = False
    extra = {
        "plan_unit": body.plan_unit.value if body.plan_unit and body.plan_unit_confirmed else None,
        "plan_unit_confirmed": bool(body.plan_unit and body.plan_unit_confirmed),
    }
    if body.default_material is not None:
        extra["default_material"] = body.default_material.model_dump()
    return await _replace_rooms(project, body.rooms, extra)


@router.put("/plan-unit", response_model=RoomsOut)
async def set_plan_unit(project_id: str, body: PlanUnitSet, user: CurrentUser) -> RoomsOut:
    """Confirm or change the plan unit (PRD 4.4). Rooms without their own written unit are
    re-read in it; any whose size changes are un-confirmed."""
    project = await get_project_or_404(user, project_id)
    if (project.get("rooms_version") or 0) != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, _CHANGED_ELSEWHERE)
    rooms = _rooms(project)
    apply_plan_unit(rooms, body.unit)
    return await _replace_rooms(
        project, rooms, {"plan_unit": body.unit.value, "plan_unit_confirmed": True}
    )


@router.delete("/{room_id}", response_model=RoomsOut)
async def delete_room(project_id: str, room_id: str, user: CurrentUser) -> RoomsOut:
    project = await get_project_or_404(user, project_id)
    rooms = _rooms(project)
    if not any(r.id == room_id for r in rooms):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    return await _replace_rooms(project, [r for r in rooms if r.id != room_id])


@router.post("/import", response_model=RoomImportOut)
async def import_rooms(
    project_id: str,
    file: UploadFile,
    user: CurrentUser,
    default_unit: Annotated[LengthUnit, Form()] = LengthUnit.FT_IN,
    mode: Annotated[Literal["append", "replace"], Form()] = "append",
    dry_run: Annotated[bool, Form()] = True,
) -> RoomImportOut:
    """Parse an Excel/CSV room list. With dry_run (default) nothing is saved: the UI shows a
    preview with per-row errors, then posts again with dry_run=false to add the valid rows."""
    project = await get_project_or_404(user, project_id)
    data = await file.read(MAX_TABLE_BYTES + 1)
    try:
        result = await asyncio.to_thread(
            parse_room_table,
            file.filename or "",
            data,
            default_unit=default_unit,
            max_rows=get_settings().max_room_import_rows,
        )
    except UploadError as e:
        raise HTTPException(e.status_code, e.message) from None

    rooms = [
        Room(
            id=_new_id(),
            name=r.name,
            floor=r.floor,
            length_mm=r.length_mm,
            width_mm=r.width_mm,
            unit=r.unit,
            origin=RoomOrigin.IMPORTED,
        )
        for r in result.rooms
    ]
    errors = [RoomImportError(row=e.row, message=e.message) for e in result.errors]

    if not dry_run and rooms:
        existing = [] if mode == "replace" else _rooms(project)
        _check_capacity(len(existing), len(rooms))
        await _replace_rooms(project, [*existing, *rooms])

    return RoomImportOut(dry_run=dry_run, rooms=rooms, errors=errors)
