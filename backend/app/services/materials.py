"""Material assignment rules (PRD 4.6). Pure functions except `load_tile_ref`."""

from decimal import Decimal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.db.mongo import get_db
from app.engine.units import LengthUnit
from app.schemas.material import (
    MATERIAL_FIELDS,
    EffectiveMaterial,
    MaterialsSummaryOut,
    ProductKind,
    ProjectMaterial,
    TileRef,
)
from app.schemas.project import Room
from app.services.tiles import size_label


def project_default(doc: dict) -> ProjectMaterial:
    return ProjectMaterial.model_validate(doc.get("default_material") or {})


def effective(room: Room, default: ProjectMaterial) -> EffectiveMaterial:
    own = room.material
    values = {
        f: getattr(own, f) if getattr(own, f) is not None else getattr(default, f)
        for f in MATERIAL_FIELDS
    }
    return EffectiveMaterial(
        **values, overridden=[f for f in MATERIAL_FIELDS if getattr(own, f) is not None]
    )


def exclusion_area_mm2(room: Room) -> Decimal:
    return sum((e.length_mm * e.width_mm * e.quantity for e in room.exclusions), Decimal(0))


def usable_area_mm2(room: Room) -> Decimal | None:
    area = room.floor_area_mm2
    return None if area is None else area - exclusion_area_mm2(room)


def materials_summary(
    rooms: list[Room], default: ProjectMaterial, review_ready: bool
) -> MaterialsSummaryOut:
    active = [r for r in rooms if not r.skipped]
    needing_tile = sum(1 for r in active if effective(r, default).tile is None)
    over_excluded = sum(1 for r in active if (u := usable_area_mm2(r)) is not None and u <= 0)
    return MaterialsSummaryOut(
        rooms_needing_tile=needing_tile,
        skipped=len(rooms) - len(active),
        rooms_over_excluded=over_excluded,
        ready_for_calculation=review_ready and needing_tile == 0 and over_excluded == 0,
    )


async def load_tile_ref(tile_id: str, user: dict, project: dict) -> TileRef:
    """A tile the user may assign: the shared catalogue, or a tile saved by the user or by the
    project's owner (so an admin helping on a project can use the contractor's tiles)."""
    try:
        oid = ObjectId(tile_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That tile doesn't exist."
        ) from None
    doc = await get_db().tiles.find_one(
        {
            "_id": oid,
            "archived": {"$ne": True},
            "$or": [
                {"scope": "catalog"},
                {"owner_id": {"$in": [user["_id"], project["owner_id"]]}},
            ],
        }
    )
    if doc is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That tile isn't in your library."
        )
    return tile_ref_from_doc(doc)


def tile_ref_from_doc(doc: dict) -> TileRef:
    """A snapshot of a library tile document, as stored on rooms."""
    length, width = Decimal(doc["length_mm"]), Decimal(doc["width_mm"])
    return TileRef(
        id=str(doc["_id"]),
        name=doc["name"],
        size_label=size_label(length, width, LengthUnit(doc["size_unit"])),
        length_mm=length,
        width_mm=width,
        tiles_per_box=doc["tiles_per_box"],
        kind=doc.get("kind", ProductKind.TILE.value),
        thickness_mm=Decimal(doc["thickness_mm"]) if doc.get("thickness_mm") else None,
        tile_type=doc.get("type"),
        material=doc.get("material"),
    )
