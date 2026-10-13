"""Library tiles that changed after a project chose them (PRD 4.12 "recalculate saved projects
when materials change").

Projects keep a copy of each tile as it was when chosen, so an estimate never changes behind
the user's back. This finds copies that differ from the library now and, on request, replaces
them so the project recalculates.
"""

from decimal import Decimal

from pydantic import BaseModel

from app.schemas.extras import ExtrasSettings
from app.schemas.material import ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services.materials import tile_ref_from_doc

# Fields that change the numbers (or what the user sees), with names for the message.
FIELDS = {
    "name": "name",
    "length_mm": "length",
    "width_mm": "width",
    "tiles_per_box": "tiles per box",
    "kind": "product type",
    "thickness_mm": "thickness",
    "tile_type": "type",
    "vendor": "vendor",
    "code": "code",
}


class TileChange(BaseModel):
    field: str  # in words, e.g. "tiles per box"
    old: str | None
    new: str | None


class TileUpdateOut(BaseModel):
    tile_id: str
    name: str  # as the project has it
    size_label: str
    available: bool  # false: removed from the library, nothing to update to
    changes: list[TileChange]
    used_in: list[str]  # "Project default", room names, "Default wall tile"...


def _text(v) -> str | None:
    if v is None:
        return None
    return f"{v.normalize():f}" if isinstance(v, Decimal) else str(v)


def _uses(
    rooms: list[Room], default: ProjectMaterial, extras: ExtrasSettings
) -> dict[str, tuple[TileRef, list[str]]]:
    found: dict[str, tuple[TileRef, list[str]]] = {}

    def add(ref: TileRef | None, where: str) -> None:
        if ref is not None:
            found.setdefault(ref.id, (ref, []))[1].append(where)

    add(default.tile, "Project default")
    add(extras.wall_tile, "Default wall tile")
    for r in rooms:
        add(r.material.tile, r.name)
        if r.walls:
            add(r.walls.tile, f"{r.name} walls")
    return found


def find_updates(
    rooms: list[Room], default: ProjectMaterial, extras: ExtrasSettings, library: dict[str, dict]
) -> list[TileUpdateOut]:
    """`library`: current library tile documents by id (archived ones included)."""
    out = []
    for tile_id, (ref, where) in _uses(rooms, default, extras).items():
        doc = library.get(tile_id)
        if doc is None or doc.get("archived"):
            out.append(
                TileUpdateOut(
                    tile_id=tile_id, name=ref.name, size_label=ref.size_label, available=False,
                    changes=[], used_in=where,
                )
            )  # fmt: skip
            continue
        fresh = tile_ref_from_doc(doc)
        changes = [
            TileChange(field=label, old=_text(getattr(ref, f)), new=_text(getattr(fresh, f)))
            for f, label in FIELDS.items()
            if _text(getattr(ref, f)) != _text(getattr(fresh, f))
            # Snapshots taken before a field existed aren't "changed" by it.
            and not (
                getattr(ref, f) is None and f in ("vendor", "code", "thickness_mm", "tile_type")
            )
        ]
        if changes:
            out.append(
                TileUpdateOut(
                    tile_id=tile_id, name=ref.name, size_label=ref.size_label, available=True,
                    changes=changes, used_in=where,
                )
            )  # fmt: skip
    return out


def apply_updates(
    rooms: list[Room],
    default: ProjectMaterial,
    extras: ExtrasSettings,
    fresh: dict[str, TileRef],
) -> tuple[list[Room], ProjectMaterial, ExtrasSettings]:
    """Replace every copy of the given tiles with the library's current version."""

    def swap(ref: TileRef | None) -> TileRef | None:
        return fresh.get(ref.id, ref) if ref is not None else None

    default = default.model_copy(update={"tile": swap(default.tile)})
    extras = extras.model_copy(update={"wall_tile": swap(extras.wall_tile)})
    out = []
    for r in rooms:
        r = r.model_copy(deep=True)
        r.material.tile = swap(r.material.tile)
        if r.walls:
            r.walls.tile = swap(r.walls.tile)
        out.append(r)
    return out, default, extras
