"""Scenarios (PRD 4.17): save, name, compare and apply options for a project.

Saving or editing a scenario doesn't touch the rooms, so it isn't an undo step. Applying one
changes the project's tiles and is undoable like any other change.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pymongo import ReturnDocument

from app.api.deps import CurrentUser
from app.api.v1.materials import _check_version
from app.api.v1.rooms import _replace_rooms, _rooms
from app.db.mongo import get_db
from app.schemas.material import ProjectMaterial
from app.schemas.project import RoomsOut
from app.schemas.scenario import (
    ComparisonOut,
    Scenario,
    ScenarioFromCurrentIn,
    ScenarioIn,
    ScenarioRenameIn,
    ScenarioRoom,
)
from app.services.access import require_costs
from app.services.cost import cost_settings
from app.services.extras import extras_settings
from app.services.materials import load_tile_ref, project_default
from app.services.projects import get_project_or_404
from app.services.scenarios import apply_scenario, compare, load_scenarios

router = APIRouter(prefix="/projects/{project_id}/scenarios", tags=["scenarios"])

MAX_SCENARIOS = 12


async def _library(user: dict, project: dict) -> list[dict]:
    return [
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


async def _comparison(project: dict, user: dict) -> ComparisonOut:
    return compare(
        project,
        cost_settings(project),
        extras_settings(project),
        project_default(project),
        await _library(user, project),
    )


async def _save(project: dict, scenarios: list[Scenario]) -> dict:
    return await get_db().projects.find_one_and_update(
        {"_id": project["_id"]},
        {
            "$set": {
                "scenarios": [s.model_dump() for s in scenarios],
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def _find(scenarios: list[Scenario], sid: str) -> Scenario:
    s = next((s for s in scenarios if s.id == sid), None)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Option not found")
    return s


@router.get("", response_model=ComparisonOut)
async def list_scenarios(project_id: str, user: CurrentUser) -> ComparisonOut:
    """The project as it is and every saved option, side by side, with the best one."""
    project = await get_project_or_404(user, project_id)
    return await _comparison(project, user)


@router.post("", response_model=ComparisonOut, status_code=status.HTTP_201_CREATED)
async def add_scenario(project_id: str, body: ScenarioIn, user: CurrentUser) -> ComparisonOut:
    project = await get_project_or_404(user, project_id)
    if body.price is not None or body.keep_price:
        require_costs()  # prices are for roles that see costs
    scenarios = load_scenarios(project)
    if len(scenarios) >= MAX_SCENARIOS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A project can have up to {MAX_SCENARIOS} options."
        )
    base = project_default(project)
    tile = await load_tile_ref(body.tile_id, user, project) if body.tile_id else base.tile
    same_tile = tile is not None and base.tile is not None and tile.id == base.tile.id
    default = ProjectMaterial(
        tile=tile,
        layout=body.layout or base.layout,
        breakage_pct=body.breakage_pct if body.breakage_pct is not None else base.breakage_pct,
        # Keep the project's price only for the same tile (or when asked): a different
        # tile's price is unknown.
        price=body.price or (base.price if body.keep_price or same_tile else None),
        brick_offset_pct=body.brick_offset_pct or base.brick_offset_pct,
        reuse_offcuts=base.reuse_offcuts if body.reuse_offcuts is None else body.reuse_offcuts,
    )
    room_ids = {r.id for r in _rooms(project)}
    rooms = []
    for r in body.rooms:
        if r.room_id not in room_ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
        rooms.append(
            ScenarioRoom(
                room_id=r.room_id,
                tile=await load_tile_ref(r.tile_id, user, project) if r.tile_id else None,
                layout=r.layout,
            )
        )
    now = datetime.now(UTC)
    scenarios.append(
        Scenario(
            id=uuid.uuid4().hex[:10],
            name=body.name.strip(),
            notes=(body.notes or "").strip() or None,
            default=default,
            every_room=body.every_room,
            rooms=rooms,
            created_at=now,
            updated_at=now,
        )
    )
    return await _comparison(await _save(project, scenarios), user)


@router.post("/from-current", response_model=ComparisonOut, status_code=status.HTTP_201_CREATED)
async def save_current(
    project_id: str, body: ScenarioFromCurrentIn, user: CurrentUser
) -> ComparisonOut:
    """Save the project's current tiles and layouts as a named option, to come back to later."""
    project = await get_project_or_404(user, project_id)
    scenarios = load_scenarios(project)
    if len(scenarios) >= MAX_SCENARIOS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A project can have up to {MAX_SCENARIOS} options."
        )
    now = datetime.now(UTC)
    rooms = [
        ScenarioRoom(room_id=r.id, tile=r.material.tile, layout=r.material.layout)
        for r in _rooms(project)
        if r.material.tile is not None or r.material.layout is not None
    ]
    scenarios.append(
        Scenario(
            id=uuid.uuid4().hex[:10],
            name=body.name.strip(),
            notes=(body.notes or "").strip() or None,
            default=project_default(project),
            every_room=True,  # rooms' own tiles are recorded above, so the snapshot is exact
            rooms=rooms,
            created_at=now,
            updated_at=now,
        )
    )
    return await _comparison(await _save(project, scenarios), user)


@router.patch("/{scenario_id}", response_model=ComparisonOut)
async def rename_scenario(
    project_id: str, scenario_id: str, body: ScenarioRenameIn, user: CurrentUser
) -> ComparisonOut:
    project = await get_project_or_404(user, project_id)
    scenarios = load_scenarios(project)
    s = _find(scenarios, scenario_id)
    s.name = body.name.strip()
    s.notes = (body.notes or "").strip() or None
    s.updated_at = datetime.now(UTC)
    return await _comparison(await _save(project, scenarios), user)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(project_id: str, scenario_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id)
    scenarios = load_scenarios(project)
    _find(scenarios, scenario_id)
    await _save(project, [s for s in scenarios if s.id != scenario_id])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{scenario_id}/apply", response_model=RoomsOut)
async def apply(project_id: str, scenario_id: str, version: int, user: CurrentUser) -> RoomsOut:
    """Make an option the project's setup. Undoable like any change to the tiles."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, version)
    s = _find(load_scenarios(project), scenario_id)
    rooms, default = apply_scenario(_rooms(project), s)
    return await _replace_rooms(project, rooms, {"default_material": default.model_dump()})
