"""Additional materials (PRD 4.15): wall tiles, skirting and sundries for a calculated project.

Worked out after the floor quantities, from the same reviewed rooms. Problems with one room (no
wall tile chosen, a room known only by area) become warnings; they never block the floor
estimate.
"""

from collections import OrderedDict
from decimal import Decimal

from app.engine.calc import Excluded, Tile
from app.engine.extras import (
    DEFAULT_TILE_THICKNESS_MM,
    calculate_walls,
    default_adhesive_rate,
    grout_kg_per_m2,
    packs,
    skirting_pieces,
    strips_per_tile,
)
from app.engine.units import MM2_PER_SQM
from app.schemas.estimate import RoomEstimateOut
from app.schemas.extras import (
    ExtrasOut,
    ExtrasSettings,
    OpeningKind,
    SkirtingOut,
    SkirtingProductOut,
    SkirtingRoomOut,
    SkirtingSource,
    SundryOut,
    WallEstimateOut,
    WallTileTotalOut,
)
from app.schemas.material import ProductKind, TileRef
from app.schemas.project import Room

_KG = Decimal("0.01")


def extras_settings(doc: dict) -> ExtrasSettings:
    return ExtrasSettings.model_validate(doc.get("extras_settings") or {})


def _tile(ref: TileRef) -> Tile:
    return Tile(ref.length_mm, ref.width_mm, ref.tiles_per_box)


def perimeter_mm(room: Room) -> Decimal | None:
    """The perimeter entered for the room, else 2 × (length + width) of a rectangular room."""
    if room.perimeter_mm is not None:
        return room.perimeter_mm
    if room.parts or room.length_mm is None or room.width_mm is None:
        return None
    return 2 * (room.length_mm + room.width_mm)


def wall_tile_for(room: Room, settings: ExtrasSettings) -> TileRef | None:
    return (room.walls.tile if room.walls else None) or settings.wall_tile


# --- Walls --------------------------------------------------------------------------------------


def _walls(
    rooms: list[Room], settings: ExtrasSettings, warnings: list[str]
) -> list[WallEstimateOut]:
    out = []
    for room in rooms:
        w = room.walls
        if w is None:
            continue
        ref = wall_tile_for(room, settings)
        if ref is None:
            warnings.append(f"{room.name}: choose a wall tile (or set a default wall tile).")
            continue
        if ref.kind == ProductKind.ROLL:
            warnings.append(f"{room.name}: {ref.name} is a roll product and can't go on walls.")
            continue
        if w.length_mm is not None:
            lengths = [w.length_mm]
        elif room.perimeter_mm is not None:
            lengths = [room.perimeter_mm]
        elif not room.parts and room.length_mm is not None and room.width_mm is not None:
            lengths = [room.length_mm, room.width_mm, room.length_mm, room.width_mm]
        else:
            warnings.append(
                f"{room.name}: enter the length of wall to tile, or the room's perimeter "
                "(it isn't a simple rectangle)."
            )
            continue
        openings = tuple(Excluded(o.width_mm, o.height_mm, o.quantity) for o in room.openings)
        breakage = w.breakage_pct if w.breakage_pct is not None else settings.wall_breakage_pct
        try:
            r = calculate_walls(lengths, w.height_mm, _tile(ref), breakage, openings)
        except ValueError as e:
            warnings.append(f"{room.name}: {e}.")
            continue
        out.append(
            WallEstimateOut(
                room_id=room.id,
                name=room.name,
                tile=ref,
                height_mm=w.height_mm,
                length_mm=sum(lengths, Decimal(0)),
                wall_area_mm2=r.room_area_mm2,
                openings_area_mm2=r.room_area_mm2 - r.usable_area_mm2,
                net_area_mm2=r.usable_area_mm2,
                rows=r.rows or 0,
                tiles_needed=r.tiles_needed,
                buffer_tiles=r.buffer_tiles,
                tiles_required=r.tiles_required,
                boxes=r.boxes,
                tiles_bought=r.tiles_bought,
                extra_area_mm2=r.extra_area_mm2,
            )
        )
    return out


def _wall_totals(walls: list[WallEstimateOut]) -> list[WallTileTotalOut]:
    groups: OrderedDict[str, list[WallEstimateOut]] = OrderedDict()
    for w in walls:
        groups.setdefault(w.tile.id, []).append(w)
    return [
        WallTileTotalOut(
            tile=g[0].tile,
            rooms=len(g),
            net_area_mm2=sum((w.net_area_mm2 for w in g), Decimal(0)),
            tiles_required=sum(w.tiles_required for w in g),
            boxes=sum(w.boxes for w in g),
            tiles_bought=sum(w.tiles_bought for w in g),
        )
        for g in groups.values()
    ]


# --- Skirting -----------------------------------------------------------------------------------


def wants_skirting(room: Room, settings: ExtrasSettings) -> bool:
    if room.skipped:
        return False
    if room.skirting is not None:
        return room.skirting
    return not (settings.skirting.skip_tiled_walls and room.walls is not None)


def _skirting(
    rooms: list[Room],
    floor: dict[str, RoomEstimateOut],
    settings: ExtrasSettings,
    warnings: list[str],
) -> SkirtingOut | None:
    s = settings.skirting
    if not s.enabled:
        return None
    room_rows: list[SkirtingRoomOut] = []
    # product key -> (label, tile, piece length, strips per tile, pieces, run)
    products: OrderedDict[str, dict] = OrderedDict()
    for room in rooms:
        if not wants_skirting(room, settings) or room.id not in floor:
            continue
        perimeter = perimeter_mm(room)
        if perimeter is None:
            warnings.append(
                f"{room.name}: skirting needs the room's perimeter (it isn't a simple rectangle)."
            )
            continue
        doors = sum(
            (o.width_mm * o.quantity for o in room.openings if o.kind == OpeningKind.DOOR),
            Decimal(0),
        )
        run = max(Decimal(0), perimeter - doors)

        if s.source == SkirtingSource.FLOOR_TILE:
            ref = floor[room.id].tile
            if ref.kind != ProductKind.TILE:
                warnings.append(
                    f"{room.name}: {ref.name} can't be cut into skirting. Use ready-made pieces."
                )
                continue
            strips, length = strips_per_tile(_tile(ref), s.height_mm)
            if strips == 0:
                warnings.append(
                    f"{room.name}: {ref.size_label} tiles are narrower than the skirting height."
                )
                continue
            key, label = ref.id, f"Skirting cut from {ref.size_label} {ref.name}"
        else:
            ref, strips, length = None, None, s.piece_length_mm
            key, label = "pieces", s.piece_name
        pieces = skirting_pieces(run, length, s.breakage_pct).pieces
        room_rows.append(
            SkirtingRoomOut(
                room_id=room.id,
                name=room.name,
                perimeter_mm=perimeter,
                doors_mm=doors,
                run_mm=run,
                pieces=pieces,
            )
        )
        p = products.setdefault(
            key,
            {
                "label": label,
                "tile": ref,
                "length": length,
                "strips": strips,
                "pieces": 0,
                "run": 0,
            },
        )
        p["pieces"] += pieces
        p["run"] += run

    out = []
    for p in products.values():
        if p["tile"] is not None:
            tiles = -(-p["pieces"] // p["strips"])
            boxes = -(-tiles // p["tile"].tiles_per_box)
        else:
            tiles = None
            boxes = -(-p["pieces"] // s.pieces_per_box) if s.pieces_per_box else None
        out.append(
            SkirtingProductOut(
                label=p["label"],
                tile=p["tile"],
                piece_length_mm=p["length"],
                strips_per_tile=p["strips"],
                pieces=p["pieces"],
                tiles=tiles,
                boxes=boxes,
                run_mm=p["run"],
            )
        )
    return SkirtingOut(
        source=s.source.value,
        height_mm=s.height_mm,
        rooms=room_rows,
        products=out,
        run_mm=sum((r.run_mm for r in room_rows), Decimal(0)),
    )


# --- Sundries -----------------------------------------------------------------------------------


def _sundries(
    floor: list[RoomEstimateOut], walls: list[WallEstimateOut], settings: ExtrasSettings
) -> list[SundryOut]:
    s = settings.sundries
    if not s.enabled:
        return []
    # (tile, net area, tiles laid, is wall) for every tiled surface. Planks and rolls aren't
    # stuck down with tile adhesive or grouted, so they're left out.
    surfaces = [
        (r.tile, r.usable_area_mm2, r.tiles_needed, False)
        for r in floor
        if r.kind == ProductKind.TILE
    ]
    surfaces += [(w.tile, w.net_area_mm2, w.tiles_needed, True) for w in walls]
    if not surfaces:
        return []

    area = sum((a for _, a, _, _ in surfaces), Decimal(0))
    adhesive = sum(
        (
            (s.adhesive_rate_kg_m2 or default_adhesive_rate(_tile(t), wall)) * a / MM2_PER_SQM
            for t, a, _, wall in surfaces
        ),
        Decimal(0),
    )
    grout = sum(
        (
            grout_kg_per_m2(
                _tile(t),
                s.grout_joint_mm,
                s.grout_depth_mm or t.thickness_mm or DEFAULT_TILE_THICKNESS_MM,
            )
            * a
            / MM2_PER_SQM
            for t, a, _, _ in surfaces
        ),
        Decimal(0),
    )
    spacers = sum(n for _, _, n, _ in surfaces) * s.spacers_per_tile
    rate = (
        f"{s.adhesive_rate_kg_m2.normalize():f} kg/m²"
        if s.adhesive_rate_kg_m2
        else "4–6 kg/m² by tile size (3.5 on walls)"
    )
    depth = f"{s.grout_depth_mm.normalize():f} mm" if s.grout_depth_mm else "the tile thickness"
    waste = f"{s.waste_pct.normalize():f}%"
    return [
        SundryOut(
            key="adhesive",
            label="Tile adhesive",
            quantity=adhesive.quantize(_KG),
            unit="kg",
            pack_size=s.adhesive_bag_kg,
            packs=packs(adhesive, s.adhesive_bag_kg, s.waste_pct),
            area_mm2=area,
            waste_pct=s.waste_pct,
            basis=f"{rate}, plus {waste} waste",
        ),
        SundryOut(
            key="grout",
            label="Grout",
            quantity=grout.quantize(_KG),
            unit="kg",
            pack_size=s.grout_pack_kg,
            packs=packs(grout, s.grout_pack_kg, s.waste_pct),
            area_mm2=area,
            waste_pct=s.waste_pct,
            basis=f"{s.grout_joint_mm.normalize():f} mm joints, {depth} deep, plus {waste} waste",
        ),
        SundryOut(
            key="spacers",
            label=f"Tile spacers ({s.grout_joint_mm.normalize():f} mm)",
            quantity=Decimal(spacers).quantize(Decimal(1)),
            unit="pcs",
            pack_size=Decimal(s.spacer_pack),
            packs=packs(Decimal(spacers), Decimal(s.spacer_pack), s.waste_pct),
            area_mm2=area,
            waste_pct=s.waste_pct,
            basis=f"{s.spacers_per_tile.normalize():f} per tile, plus {waste} waste",
        ),
    ]


def build_extras(
    rooms: list[Room], floor: list[RoomEstimateOut], settings: ExtrasSettings
) -> ExtrasOut | None:
    active = [r for r in rooms if not r.skipped]
    if not (any(r.walls for r in active) or settings.skirting.enabled or settings.sundries.enabled):
        return None
    warnings: list[str] = []
    walls = _walls(active, settings, warnings)
    by_room = {r.room_id: r for r in floor}
    return ExtrasOut(
        walls=walls,
        wall_tiles=_wall_totals(walls),
        skirting=_skirting(active, by_room, settings, warnings),
        sundries=_sundries(floor, walls, settings),
        warnings=warnings,
    )
