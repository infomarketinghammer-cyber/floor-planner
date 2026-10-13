"""Suggested defaults by room type (PRD 4.15, 6.4): anti-skid floors in toilets and balconies,
tiled bathroom walls, a kitchen backsplash, and no wood or carpet in wet rooms.

Pure: takes the rooms and the tiles the user can choose from; every suggestion carries an action
the client can apply with the existing endpoints, so nothing changes without the user.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.extraction.classify import room_type
from app.schemas.extras import ExtrasSettings
from app.schemas.material import ProductKind, ProjectMaterial
from app.schemas.project import Room
from app.services.materials import effective

WET = "Bathroom & toilet"
OUTDOOR = "Balcony & outdoor"
KITCHEN = "Kitchen"
SLIP_RESISTANT = {"anti_skid", "outdoor"}
SLIP_RESISTANT_ORDER = ["anti_skid", "outdoor"]
BATHROOM_WALL_HEIGHT_MM = Decimal(2100)
BACKSPLASH_HEIGHT_MM = Decimal(600)


class SuggestionAction(BaseModel):
    type: Literal["set_tile", "tile_walls"]
    tile_id: str | None = None  # set_tile: floor tile; tile_walls: wall tile if none is set
    tile_name: str | None = None
    height_mm: Decimal | None = None  # tile_walls
    needs_length: bool = False  # tile_walls on part of the walls only (backsplash)


class SuggestionOut(BaseModel):
    key: str  # stable id, e.g. "anti_skid", so the client can dismiss it
    severity: Literal["suggest", "warn"]
    title: str
    detail: str
    room_ids: list[str]
    room_names: list[str]
    action: SuggestionAction | None


METRIC_UNITS = {"mm", "cm", "m"}


def _best(
    tiles: list[dict], types: list[str], like: dict | None, metric: bool | None = None
) -> dict | None:
    """The library tile best matching: earlier `types` first, then the project's unit system
    (metric or imperial sizes), then closest in size to `like` (same size if there is one)."""
    candidates = [t for t in tiles if t.get("type") in types and t.get("kind", "tile") == "tile"]
    if not candidates:
        return None
    target = Decimal(like["length_mm"]) * Decimal(like["width_mm"]) if like else Decimal(0)

    def key(t: dict):
        other_system = metric is not None and (t.get("size_unit") in METRIC_UNITS) != metric
        size = abs(Decimal(t["length_mm"]) * Decimal(t["width_mm"]) - target) if like else 0
        return (types.index(t["type"]), other_system, size, t["name"])

    return min(candidates, key=key)


def suggestions(
    rooms: list[Room], default: ProjectMaterial, settings: ExtrasSettings, tiles: list[dict]
) -> list[SuggestionOut]:
    """`tiles`: library tile documents the user can choose (with "id" as a string)."""
    out: list[SuggestionOut] = []
    active = [r for r in rooms if not r.skipped]
    # Metric or imperial project, judged from the default floor tile's size label.
    metric = default.tile.size_label.rsplit(" ", 1)[-1] in METRIC_UNITS if default.tile else None

    def group(rs: list[Room]) -> tuple[list[str], list[str]]:
        return [r.id for r in rs], [r.name for r in rs]

    # Wet rooms and balconies: slip-resistant floors; never wood or carpet in wet rooms.
    slippery, unsuitable = [], []
    for r in active:
        kind = room_type(r.name)
        if kind not in (WET, OUTDOOR):
            continue
        tile = effective(r, default).tile
        if tile is None:
            continue
        if kind == WET and tile.kind != ProductKind.TILE:
            unsuitable.append(r)
        elif tile.kind == ProductKind.TILE and tile.tile_type not in SLIP_RESISTANT:
            slippery.append(r)
    for rs, key, severity, title, detail in (
        (
            unsuitable,
            "wet_room_flooring",
            "warn",
            "Wood, vinyl plank and carpet don't suit wet rooms",
            "Water damages them. Use an anti-skid tile in bathrooms and toilets.",
        ),
        (
            slippery,
            "anti_skid",
            "suggest",
            "Use an anti-skid tile",
            "Floors in toilets, bathrooms and balconies get wet. A slip-resistant tile is safer.",
        ),
    ):
        if not rs:
            continue
        current = effective(rs[0], default).tile
        like = {"length_mm": current.length_mm, "width_mm": current.width_mm} if current else None
        best = _best(tiles, SLIP_RESISTANT_ORDER, like, metric)
        ids, names = group(rs)
        out.append(
            SuggestionOut(
                key=key,
                severity=severity,
                title=title,
                detail=detail,
                room_ids=ids,
                room_names=names,
                action=SuggestionAction(type="set_tile", tile_id=best["id"], tile_name=best["name"])
                if best
                else None,
            )
        )

    wall_tile = None if settings.wall_tile else _best(tiles, ["wall", "floor_wall"], None, metric)
    wall_action = {
        "tile_id": wall_tile["id"] if wall_tile else None,
        "tile_name": wall_tile["name"] if wall_tile else None,
    }

    bathrooms = [r for r in active if room_type(r.name) == WET and r.walls is None]
    if bathrooms:
        ids, names = group(bathrooms)
        out.append(
            SuggestionOut(
                key="bathroom_walls",
                severity="suggest",
                title="Tile the bathroom walls",
                detail="Bathroom walls are usually tiled to 2.1 m (7 ft) to keep water off them.",
                room_ids=ids,
                room_names=names,
                action=SuggestionAction(
                    type="tile_walls", height_mm=BATHROOM_WALL_HEIGHT_MM, **wall_action
                ),
            )
        )

    kitchens = [r for r in active if room_type(r.name) == KITCHEN and r.walls is None]
    if kitchens:
        ids, names = group(kitchens)
        out.append(
            SuggestionOut(
                key="backsplash",
                severity="suggest",
                title="Add a kitchen backsplash",
                detail="A 600 mm (2 ft) band of wall tiles above the counter. Enter the length of "
                "the counter walls.",
                room_ids=ids,
                room_names=names,
                action=SuggestionAction(
                    type="tile_walls",
                    height_mm=BACKSPLASH_HEIGHT_MM,
                    needs_length=True,
                    **wall_action,
                ),
            )
        )

    on_floor = [
        r for r in active if (t := effective(r, default).tile) is not None and t.tile_type == "wall"
    ]
    if on_floor:
        ids, names = group(on_floor)
        best = _best(tiles, ["floor", "floor_wall"], None, metric)
        out.append(
            SuggestionOut(
                key="wall_tile_on_floor",
                severity="warn",
                title="A wall tile is set as the floor tile",
                detail="Wall tiles are thinner and softer, and crack or wear underfoot.",
                room_ids=ids,
                room_names=names,
                action=SuggestionAction(type="set_tile", tile_id=best["id"], tile_name=best["name"])
                if best
                else None,
            )
        )
    return out
