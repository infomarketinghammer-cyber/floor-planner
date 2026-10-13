"""Tile library (PRD 4.5): a shared catalogue managed by admins, plus each contractor's own tiles."""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pymongo import ASCENDING

from app.api.deps import CurrentUser, parse_object_id
from app.db.mongo import get_db
from app.schemas.tile import TileInput, TileOut, TileRegion, TileScope, TileType
from app.schemas.user import Role
from app.services.tiles import resolve, tile_out

router = APIRouter(prefix="/tiles", tags=["tiles"])

MAX_TILES_PER_USER = 500


def _visible(user: dict) -> dict:
    """The catalogue plus the user's own tiles. Archived tiles are hidden from the library
    but kept, so projects that already use them keep working."""
    return {
        "archived": {"$ne": True},
        "$or": [{"scope": TileScope.CATALOG.value}, {"owner_id": user["_id"]}],
    }


async def _get_editable(user: dict, tile_id: str) -> dict:
    doc = await get_db().tiles.find_one({"_id": parse_object_id(tile_id), **_visible(user)})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile not found")
    if doc["scope"] == TileScope.CATALOG and user["role"] != Role.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only admins can change catalogue tiles. Save a copy to edit it.",
        )
    if doc["scope"] == TileScope.USER and doc.get("owner_id") != user["_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile not found")
    return doc


async def _check_quota(user: dict) -> None:
    count = await get_db().tiles.count_documents(
        {"owner_id": user["_id"], "archived": {"$ne": True}}
    )
    if count >= MAX_TILES_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You can save up to {MAX_TILES_PER_USER} tiles."
        )


@router.get("", response_model=list[TileOut])
async def list_tiles(
    user: CurrentUser,
    scope: Literal["all", "catalog", "mine"] = "all",
    q: str | None = Query(default=None, max_length=80),
    type: TileType | None = None,
    region: TileRegion | None = None,
) -> list[TileOut]:
    query = _visible(user)
    if scope == "catalog":
        query["scope"] = TileScope.CATALOG.value
    elif scope == "mine":
        query["scope"] = TileScope.USER.value
        query["owner_id"] = user["_id"]
    if type is not None:
        query["type"] = type.value
    if region is not None:
        query["regions"] = region.value
    if q and q.strip():
        pattern = re.escape(q.strip())
        query["$and"] = [
            {"$or": [{f: {"$regex": pattern, "$options": "i"}} for f in ("name", "brand", "code")]}
        ]
    cursor = get_db().tiles.find(query).sort([("scope", ASCENDING), ("name", ASCENDING)])
    return [tile_out(doc, user) async for doc in cursor]


@router.post("", response_model=TileOut, status_code=status.HTTP_201_CREATED)
async def create_tile(body: TileInput, user: CurrentUser, catalog: bool = False) -> TileOut:
    """Contractors save their own tiles. Admins add to the shared catalogue with ?catalog=true."""
    if catalog and user["role"] != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can add catalogue tiles.")
    if not catalog:
        await _check_quota(user)
    now = datetime.now(UTC)
    doc = resolve(body) | {
        "scope": (TileScope.CATALOG if catalog else TileScope.USER).value,
        "owner_id": None if catalog else user["_id"],
        "typical": False,
        "archived": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await get_db().tiles.insert_one(doc)).inserted_id
    return tile_out(doc, user)


@router.put("/{tile_id}", response_model=TileOut)
async def update_tile(tile_id: str, body: TileInput, user: CurrentUser) -> TileOut:
    doc = await _get_editable(user, tile_id)
    # An edited preset is no longer "typical": someone checked it.
    changes = resolve(body) | {"updated_at": datetime.now(UTC), "typical": False}
    await get_db().tiles.update_one({"_id": doc["_id"]}, {"$set": changes})
    return tile_out(doc | changes, user)


@router.post("/{tile_id}/copy", response_model=TileOut, status_code=status.HTTP_201_CREATED)
async def copy_tile(tile_id: str, user: CurrentUser) -> TileOut:
    """Save a copy into "My tiles", e.g. to set your supplier's pack size."""
    source = await get_db().tiles.find_one({"_id": parse_object_id(tile_id), **_visible(user)})
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile not found")
    await _check_quota(user)
    now = datetime.now(UTC)
    doc = {k: v for k, v in source.items() if k != "_id"} | {
        "scope": TileScope.USER.value,
        "owner_id": user["_id"],
        "typical": False,
        "copied_from": source["_id"],
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await get_db().tiles.insert_one(doc)).inserted_id
    return tile_out(doc, user)


@router.delete("/{tile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tile(tile_id: str, user: CurrentUser) -> Response:
    """Removes the tile from the library. Projects already using it keep their settings."""
    doc = await _get_editable(user, tile_id)
    await get_db().tiles.update_one(
        {"_id": doc["_id"]}, {"$set": {"archived": True, "updated_at": datetime.now(UTC)}}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
