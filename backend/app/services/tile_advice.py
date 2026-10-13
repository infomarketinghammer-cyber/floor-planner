"""Best tile size for the least waste (PRD 4.16, 6.4 "AI tile advisor"): every room is recounted
by the engine with the other suitable tiles in the library, and the results are explained in
plain language. Deterministic: no AI makes up the numbers.
"""

from decimal import Decimal

from pydantic import BaseModel

from app.schemas.estimate import EstimateOut, RoomEstimateOut
from app.schemas.material import DecimalStr, ProductKind, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services.estimate import estimate_room
from app.services.materials import effective, tile_ref_from_doc

MIN_GAIN_PCT = Decimal(2)  # suggest a tile only if it saves at least this much extra (points)
MAX_ROOMS = 60  # large projects: advise on the rooms with the most waste
_ONE = Decimal("0.1")


class TileOption(BaseModel):
    tile: TileRef
    boxes: int
    tiles_bought: int
    extra_area_mm2: DecimalStr  # bought minus area to tile
    extra_pct: DecimalStr


class RoomAdvice(BaseModel):
    room_id: str
    name: str
    current: TileOption
    best: TileOption | None  # None: the current tile is already (near) the best
    alternatives: list[TileOption]  # up to 3, least waste first


class ProjectAdvice(BaseModel):
    """One tile for every room that uses the project default."""

    rooms: int
    current: TileOption
    best: TileOption | None


class TileAdviceOut(BaseModel):
    rooms: list[RoomAdvice]
    project: ProjectAdvice | None
    summary: str | None  # plain-language headline, e.g. "Bedroom 1 drives most of your waste…"


def _metric(tile: TileRef) -> bool:
    return tile.size_label.rsplit(" ", 1)[-1] in ("mm", "cm", "m")


def _families(current: TileRef) -> set[str]:
    """Tile types that can replace the current one: slip-resistant stays slip-resistant."""
    if current.tile_type in ("anti_skid", "outdoor"):
        return {"anti_skid", "outdoor"}
    return {"floor", "floor_wall", current.tile_type or "floor"}


def _option(r: RoomEstimateOut) -> TileOption:
    return TileOption(
        tile=r.tile,
        boxes=r.boxes,
        tiles_bought=r.tiles_bought,
        extra_area_mm2=r.extra_area_mm2,
        extra_pct=r.extra_pct.quantize(_ONE),
    )


def _with_tile(room: Room, tile: TileRef) -> Room:
    return room.model_copy(update={"material": room.material.model_copy(update={"tile": tile})})


def _size(tile: TileRef) -> str:
    return tile.size_label


def advise(
    rooms: list[Room], default: ProjectMaterial, estimate: EstimateOut, library: list[dict]
) -> TileAdviceOut:
    if not estimate.ready:
        return TileAdviceOut(rooms=[], project=None, summary=None)
    candidates = [tile_ref_from_doc(d) for d in library if d.get("kind", "tile") == "tile"]
    # Suggest sizes from the project's own unit system (metric or imperial) when there are any:
    # a metric project's supplier won't stock 12 × 12 in tiles.
    if default.tile is not None:
        metric = _metric(default.tile)
        same = [t for t in candidates if _metric(t) == metric]
        candidates = same or candidates
    by_id = {r.id: r for r in rooms}
    tiled = [r for r in estimate.rooms if r.kind == ProductKind.TILE]
    tiled = sorted(tiled, key=lambda r: r.extra_area_mm2, reverse=True)[:MAX_ROOMS]

    advice: list[RoomAdvice] = []
    for est in tiled:
        room = by_id[est.room_id]
        families = _families(est.tile)
        options = []
        for tile in candidates:
            if tile.id == est.tile.id or tile.tile_type not in families:
                continue
            if est.layout == "herringbone" and tile.length_mm == tile.width_mm:
                continue  # herringbone needs oblong tiles
            try:
                options.append(_option(estimate_room(_with_tile(room, tile), default)))
            except ValueError:
                continue  # e.g. a tile bigger than an untiled area allows
        options.sort(key=lambda o: (o.extra_area_mm2, o.boxes))
        current = _option(est)
        best = (
            options[0]
            if options and current.extra_pct - options[0].extra_pct >= MIN_GAIN_PCT
            else None
        )
        advice.append(
            RoomAdvice(
                room_id=est.room_id,
                name=est.name,
                current=current,
                best=best,
                alternatives=options[:3],
            )
        )

    project = _project_advice(rooms, default, estimate, candidates)
    return TileAdviceOut(rooms=advice, project=project, summary=_summary(estimate, advice, project))


def _project_advice(
    rooms: list[Room], default: ProjectMaterial, estimate: EstimateOut, candidates: list[TileRef]
) -> ProjectAdvice | None:
    """The single tile that wastes least across every room using the project default."""
    if default.tile is None or default.tile.kind != ProductKind.TILE:
        return None
    by_id = {r.id: r for r in rooms}
    on_default = [
        by_id[e.room_id]
        for e in estimate.rooms
        if "tile" not in effective(by_id[e.room_id], default).overridden
    ]
    if not on_default:
        return None

    def total(tile: TileRef) -> TileOption | None:
        try:
            ests = [estimate_room(_with_tile(r, tile), default) for r in on_default]
        except ValueError:
            return None
        extra = sum((e.extra_area_mm2 for e in ests), Decimal(0))
        usable = sum((e.usable_area_mm2 for e in ests), Decimal(0))
        return TileOption(
            tile=tile,
            boxes=sum(e.boxes for e in ests),
            tiles_bought=sum(e.tiles_bought for e in ests),
            extra_area_mm2=extra,
            extra_pct=(extra / usable * 100).quantize(_ONE),
        )

    current = total(default.tile)
    families = _families(default.tile)
    options = [
        o
        for t in candidates
        if t.id != default.tile.id and t.tile_type in families and (o := total(t)) is not None
    ]
    options.sort(key=lambda o: (o.extra_area_mm2, o.boxes))
    best = (
        options[0]
        if options and current and current.extra_pct - options[0].extra_pct >= MIN_GAIN_PCT
        else None
    )
    return ProjectAdvice(rooms=len(on_default), current=current, best=best)


def _summary(
    estimate: EstimateOut, advice: list[RoomAdvice], project: ProjectAdvice | None
) -> str | None:
    """E.g. "Bedroom 1 drives most of your waste (41% of the extra). An 800 × 800 mm tile would
    cut its waste from 23% to 6%." (PRD 6.1 plain-language summary)."""
    if not advice or estimate.totals is None or estimate.totals.extra_area_mm2 <= 0:
        return None
    worst = advice[0]  # sorted by extra area
    share = (worst.current.extra_area_mm2 / estimate.totals.extra_area_mm2 * 100).quantize(
        Decimal(1)
    )
    text = f"{worst.name} drives most of your waste ({share}% of the extra tile area)."
    if worst.best:
        text += (
            f" A {_size(worst.best.tile)} tile would cut its waste from "
            f"{worst.current.extra_pct.normalize():f}% to {worst.best.extra_pct.normalize():f}%."
        )
    elif project and project.best:
        text += (
            f" Switching the project tile to {_size(project.best.tile)} would cut the waste in "
            f"those rooms from {project.current.extra_pct.normalize():f}% to "
            f"{project.best.extra_pct.normalize():f}%."
        )
    else:
        text += " Its tile is already the best fit in your library."
    return text
