"""Turn reviewed rooms and their materials into tile quantities (PRD 4.7) and explain the waste
(PRD 4.8).

Quantities are only produced once the review is complete: every room confirmed, the plan unit
confirmed, and every room has a tile (PRD 6.3: nothing unreviewed reaches the calculation).
"""

from collections import OrderedDict
from decimal import Decimal

from app.engine.calc import (
    AREA_ONLY_ALLOWANCE_PCT,
    DIAGONAL_ALLOWANCE_PCT,
    Excluded,
    Tile,
    calculate_by_area,
    calculate_room,
)
from app.engine.extras import (
    PLANK_ALLOWANCE_PCT,
    PLANK_DIAGONAL_ALLOWANCE_PCT,
    ROLL_TRIM_MM,
    calculate_roll,
    calculate_roll_by_area,
)
from app.engine.units import mm2_to_sqft, mm2_to_sqm
from app.extraction.classify import room_type
from app.schemas.estimate import (
    Assumption,
    EstimateOut,
    EstimateTotalsOut,
    RoomEstimateOut,
    TileTotalOut,
)
from app.schemas.extras import ExtrasOut, ExtrasSettings
from app.schemas.material import Layout, ProductKind, ProjectMaterial
from app.schemas.project import Room
from app.services.extras import build_extras
from app.services.materials import effective, materials_summary
from app.services.plan_units import UNIT_NAMES
from app.services.review import ReviewState

_TWO = Decimal("0.01")
HIGH_WASTE_PCT = Decimal(20)  # cut waste above this is flagged (PRD 4.20 insights)

OFFCUT_NOTE = (
    "Real waste may be lower. These figures treat every cut piece as waste. With careful cutting, "
    "an offcut from one edge can often fill a gap on the opposite edge, especially where the cut "
    "strip is less than half a tile wide."
)


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def blockers(state: ReviewState, default: ProjectMaterial) -> list[str]:
    s = state.summary
    m = materials_summary(state.rooms, default, s.ready)
    out = []
    if not [r for r in state.rooms if not r.skipped]:
        out.append("Add at least one room to tile.")
    if s.blocking:
        out.append(f"Fix {_plural(s.blocking, 'room')} with a missing size or name.")
    if s.to_review:
        out.append(f"Confirm {_plural(s.to_review, 'room')} in the review.")
    if s.unit_pending:
        out.append("Confirm the plan unit.")
    if m.rooms_needing_tile:
        out.append(f"Choose a tile for {_plural(m.rooms_needing_tile, 'room')}.")
    if m.rooms_over_excluded:
        out.append(
            f"{_plural(m.rooms_over_excluded, 'room')} have untiled areas covering the whole room."
        )
    return out


def estimate_room(room: Room, default: ProjectMaterial) -> RoomEstimateOut:
    eff = effective(room, default)
    assert eff.tile is not None, "blockers() guarantees every room has a tile"
    tile = Tile(eff.tile.length_mm, eff.tile.width_mm, eff.tile.tiles_per_box)
    exclusions = tuple(Excluded(e.length_mm, e.width_mm, e.quantity) for e in room.exclusions)
    excluded_area = sum((e.area_mm2 for e in exclusions), Decimal(0))

    if eff.tile.kind == ProductKind.ROLL:
        return _estimate_roll(room, eff, excluded_area)
    if eff.tile.kind == ProductKind.PLANK:
        allowance = (
            PLANK_DIAGONAL_ALLOWANCE_PCT if eff.layout == Layout.DIAGONAL else PLANK_ALLOWANCE_PCT
        )
        reason = (
            f"Planks are laid in staggered rows: worked out by area plus {allowance:f}% for "
            "cuts at the row ends."
        )
        area = room.area_mm2 if room.area_only else room.floor_area_mm2
        result = calculate_by_area(area, tile, allowance, eff.breakage_pct, excluded_area)
    elif room.area_only:
        allowance = (
            DIAGONAL_ALLOWANCE_PCT if eff.layout == Layout.DIAGONAL else AREA_ONLY_ALLOWANCE_PCT
        )
        reason = (
            f"Known by area only, so tiles are worked out by area plus {allowance:f}% for cutting."
        )
        result = calculate_by_area(room.area_mm2, tile, allowance, eff.breakage_pct, excluded_area)
    elif eff.layout == Layout.DIAGONAL:
        allowance = DIAGONAL_ALLOWANCE_PCT
        reason = (
            f"Diagonal layout: tiles worked out by area plus {allowance:f}% for the extra cuts."
        )
        result = calculate_by_area(
            room.floor_area_mm2, tile, allowance, eff.breakage_pct, excluded_area
        )
    else:
        allowance = Decimal(0)
        reason = "Straight layout: tiles counted on a grid over the room."
        result = calculate_room(room.length_mm, room.width_mm, tile, eff.breakage_pct, exclusions)

    high_waste = result.cut_waste_pct > HIGH_WASTE_PCT
    return RoomEstimateOut(
        kind=eff.tile.kind,
        room_id=room.id,
        name=room.name,
        floor=room.floor,
        room_type=room_type(room.name),
        tile=eff.tile,
        layout=eff.layout,
        method=result.method.value,
        method_reason=reason,
        allowance_pct=allowance,
        breakage_pct=eff.breakage_pct,
        room_area_mm2=result.room_area_mm2,
        usable_area_mm2=result.usable_area_mm2,
        columns=result.columns,
        rows=result.rows,
        grid_tiles=result.grid_tiles,
        excluded_tiles=result.excluded_tiles,
        tiles_needed=result.tiles_needed,
        cut_waste_mm2=result.cut_waste_mm2,
        cut_waste_pct=result.cut_waste_pct.quantize(_TWO),
        buffer_tiles=result.buffer_tiles,
        tiles_required=result.tiles_required,
        boxes=result.boxes,
        tiles_bought=result.tiles_bought,
        extra_area_mm2=result.extra_area_mm2,
        buffer_area_mm2=result.buffer_area_mm2,
        rounding_tiles=result.rounding_tiles,
        rounding_area_mm2=result.rounding_area_mm2,
        extra_pct=result.extra_pct.quantize(_TWO),
        high_waste=high_waste,
        waste_hint=(
            f"Cut waste is {result.cut_waste_pct:.0f}% of the area. A tile size that fits this room "
            "better, or a straight layout, would reduce it."
            if high_waste
            else None
        ),
    )


def _estimate_roll(room: Room, eff, excluded_area: Decimal) -> RoomEstimateOut:
    """Carpet or sheet vinyl: drops cut from a roll of the product's width (PRD 4.15)."""
    roll_width = eff.tile.width_mm
    if room.area_only:
        r = calculate_roll_by_area(room.area_mm2, roll_width, excluded_area)
        reason = (
            f"Known by area only: roll length is the area ÷ roll width plus {r.allowance_pct:f}%."
        )
    else:
        r = calculate_roll(room.length_mm, room.width_mm, roll_width, excluded_area)
        reason = (
            f"{r.drops} drop{'s' if r.drops != 1 else ''} along the room's {r.along}, each "
            f"{ROLL_TRIM_MM:f} mm longer than the room for trimming."
        )
    waste_pct = r.extra_area_mm2 / r.usable_area_mm2 * 100
    high_waste = waste_pct > HIGH_WASTE_PCT
    return RoomEstimateOut(
        room_id=room.id,
        name=room.name,
        floor=room.floor,
        room_type=room_type(room.name),
        tile=eff.tile,
        layout=eff.layout,
        method="roll",
        kind=ProductKind.ROLL,
        method_reason=reason,
        allowance_pct=r.allowance_pct,
        breakage_pct=Decimal(0),
        room_area_mm2=r.room_area_mm2,
        usable_area_mm2=r.usable_area_mm2,
        columns=r.drops,
        rows=None,
        grid_tiles=0,
        excluded_tiles=0,
        tiles_needed=0,
        cut_waste_mm2=r.extra_area_mm2,
        cut_waste_pct=waste_pct.quantize(_TWO),
        buffer_tiles=0,
        tiles_required=0,
        boxes=0,
        tiles_bought=0,
        extra_area_mm2=r.extra_area_mm2,
        buffer_area_mm2=Decimal(0),
        rounding_tiles=0,
        rounding_area_mm2=Decimal(0),
        extra_pct=waste_pct.quantize(_TWO),
        high_waste=high_waste,
        waste_hint=(
            f"{waste_pct:.0f}% of the roll is trimmed off. A different roll width would reduce it."
            if high_waste
            else None
        ),
        linear_mm=r.linear_mm,
        drops=r.drops,
    )


def build_estimate(
    state: ReviewState, default: ProjectMaterial, extras: ExtrasSettings | None = None
) -> EstimateOut:
    problems = blockers(state, default)
    if problems:
        return EstimateOut(
            ready=False,
            blockers=problems,
            rooms=[],
            tiles=[],
            totals=None,
            assumptions=[],
            offcut_note=OFFCUT_NOTE,
        )

    rooms = [estimate_room(r, default) for r in state.rooms if not r.skipped]

    # Per tile type. Totals add up the rooms (PRD 11: totals = sum of rooms); `boxes_if_pooled`
    # shows the saving if leftover tiles from one room are used in another.
    by_tile: OrderedDict[str, list[RoomEstimateOut]] = OrderedDict()
    for r in rooms:
        by_tile.setdefault(r.tile.id, []).append(r)
    tiles = []
    for group in by_tile.values():
        ref = group[0].tile
        required = sum(r.tiles_required for r in group)
        bought = sum(r.tiles_bought for r in group)
        roll = ref.kind == ProductKind.ROLL
        tiles.append(
            TileTotalOut(
                tile=ref,
                rooms=len(group),
                usable_area_mm2=sum((r.usable_area_mm2 for r in group), Decimal(0)),
                tiles_required=required,
                boxes=sum(r.boxes for r in group),
                tiles_bought=bought,
                # Usable + extra = what's bought, for boxes and rolls alike.
                bought_area_mm2=sum(
                    (r.usable_area_mm2 + r.extra_area_mm2 for r in group), Decimal(0)
                ),
                boxes_if_pooled=0 if roll else -(-required // ref.tiles_per_box),
                linear_mm=sum((r.linear_mm for r in group), Decimal(0)) if roll else None,
            )
        )

    def total(field: str) -> Decimal:
        return sum((getattr(r, field) for r in rooms), Decimal(0))

    usable = total("usable_area_mm2")
    totals = EstimateTotalsOut(
        rooms=len(rooms),
        room_area_mm2=total("room_area_mm2"),
        usable_area_mm2=usable,
        cut_waste_mm2=total("cut_waste_mm2"),
        buffer_area_mm2=total("buffer_area_mm2"),
        rounding_area_mm2=total("rounding_area_mm2"),
        bought_area_mm2=sum((t.bought_area_mm2 for t in tiles), Decimal(0)),
        extra_area_mm2=total("extra_area_mm2"),
        cut_waste_pct=(total("cut_waste_mm2") / usable * 100).quantize(_TWO),
        extra_pct=(total("extra_area_mm2") / usable * 100).quantize(_TWO),
        high_waste_rooms=sum(r.high_waste for r in rooms),
        boxes=sum(t.boxes for t in tiles),
    )
    settings = extras or ExtrasSettings()
    extras_out = build_extras(state.rooms, rooms, settings)
    return EstimateOut(
        ready=True,
        blockers=[],
        rooms=rooms,
        tiles=tiles,
        totals=totals,
        assumptions=assumptions(state, default, rooms, tiles, settings, extras_out),
        offcut_note=OFFCUT_NOTE,
        extras=extras_out,
    )


# --- Assumptions panel (PRD 4.8) ----------------------------------------------------------------


def _area(mm2: Decimal) -> str:
    sqft = mm2_to_sqft(mm2).quantize(_TWO).normalize()
    sqm = mm2_to_sqm(mm2).quantize(_TWO).normalize()
    return f"{sqft:f} sq ft / {sqm:f} m²"


def _pct(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + "."


def _names(rooms: list) -> str:
    names = [r.name for r in rooms]
    return (
        ", ".join(names) if len(names) <= 4 else f"{', '.join(names[:3])} and {len(names) - 3} more"
    )


def assumptions(
    state: ReviewState,
    default: ProjectMaterial,
    rooms: list[RoomEstimateOut],
    tiles: list[TileTotalOut],
    settings: ExtrasSettings | None = None,
    extras: ExtrasOut | None = None,
) -> list[Assumption]:
    """Plain-language statement of how the numbers were worked out, from the project's own data."""
    settings = settings or ExtrasSettings()
    out: list[Assumption] = []
    grid = [r for r in rooms if r.method == "grid"]
    planks = [r for r in rooms if r.kind == ProductKind.PLANK]
    rolls = [r for r in rooms if r.kind == ProductKind.ROLL]
    rooms = [r for r in rooms if r.kind == ProductKind.TILE]  # tile rules below
    diagonal = [r for r in rooms if r.method == "area" and r.layout == Layout.DIAGONAL]
    by_area = [r for r in rooms if r.method == "area" and r.layout != Layout.DIAGONAL]

    if grid:
        out.append(
            Assumption(
                key="method_grid",
                title="Straight layout",
                text=f"{_names(grid)}: whole tiles counted on a grid starting from one corner. Every "
                "part-tile at the edges counts as a full tile; cut waste is the grid area minus the "
                "area to tile.",
            )
        )
    if diagonal:
        out.append(
            Assumption(
                key="method_diagonal",
                title="Diagonal layout",
                text=f"{_names(diagonal)}: area to tile plus {_pct(DIAGONAL_ALLOWANCE_PCT)} for the extra "
                "cuts at every wall.",
            )
        )
    if by_area:
        out.append(
            Assumption(
                key="method_area",
                title="Known by area only",
                text=f"{_names(by_area)}: area to tile plus {_pct(AREA_ONLY_ALLOWANCE_PCT)} for cuts, since "
                "there's no length and width to count a grid from.",
            )
        )

    others = [r for r in rooms if r.breakage_pct != default.breakage_pct]
    text = f"{_pct(default.breakage_pct)} extra tiles for breakage (project default)"
    if others:
        text += "; " + "; ".join(f"{_pct(r.breakage_pct)} for {r.name}" for r in others)
    out.append(
        Assumption(
            key="buffer", title="Breakage buffer", text=f"{text}, rounded up to whole tiles."
        )
    )

    excluded = [r for r in state.rooms if r.exclusions and not r.skipped]
    if excluded:
        parts = []
        for room in excluded:
            est = next(e for e in rooms if e.room_id == room.id)
            items = ", ".join(
                f"{e.label}{f' ×{e.quantity}' if e.quantity > 1 else ''}" for e in room.exclusions
            )
            area = sum((e.length_mm * e.width_mm * e.quantity for e in room.exclusions), Decimal(0))
            removed = (
                f"{_plural(est.excluded_tiles, 'tile')} subtracted"
                if est.method == "grid"
                else "area subtracted"
            )
            parts.append(f"{room.name}: {items} ({_area(area)} not tiled; {removed})")
        text = (
            "; ".join(parts)
            + ". Only tiles these areas are certain to cover are subtracted, wherever they sit."
        )
    else:
        text = "No untiled areas (cabinets, columns...) were entered."
    out.append(Assumption(key="exclusions", title="Untiled areas", text=text))

    savings = sum(t.boxes - t.boxes_if_pooled for t in tiles)
    text = "Boxes are rounded up for each room; tiles left in a part-used box are counted as extra."
    if savings:
        text += f" Using leftover tiles from one room in another would save {_plural(savings, 'box', 'boxes')}."
    out.append(Assumption(key="rounding", title="Box rounding", text=text))

    unit = state.plan_unit.unit
    if unit is not None:
        confirmed = " (confirmed)" if state.plan_unit.confirmed else ""
        out.append(
            Assumption(
                key="units",
                title="Units",
                text=f"Plan unit: {UNIT_NAMES[unit]}{confirmed}. Sizes are stored exactly; areas are "
                "converted only for display.",
            )
        )
    skipped = [r for r in state.rooms if r.skipped]
    if skipped:
        out.append(
            Assumption(
                key="skipped",
                title="Not tiled",
                text=f"{_names(skipped)}: marked as needing no tiles.",
            )
        )
    if planks:
        out.append(
            Assumption(
                key="method_plank",
                title="Planks",
                text=f"{_names(planks)}: area plus {_pct(PLANK_ALLOWANCE_PCT)} for cuts at the row "
                f"ends ({_pct(PLANK_DIAGONAL_ALLOWANCE_PCT)} if laid diagonally), then boxes.",
            )
        )
    if rolls:
        out.append(
            Assumption(
                key="method_roll",
                title="Roll flooring",
                text=f"{_names(rolls)}: drops cut from the roll, laid whichever way needs less, each "
                f"{ROLL_TRIM_MM:f} mm longer than the room for trimming. Seams aren't matched for "
                "pattern repeat.",
            )
        )
    if extras and extras.walls:
        out.append(
            Assumption(
                key="walls",
                title="Wall tiles",
                text=f"{_names(extras.walls)}: tiles counted on a grid for each wall up to the tiling "
                "height, turned whichever way needs fewer. Only tiles certain to fall inside a door "
                "or window are taken off.",
            )
        )
    if extras and extras.skirting:
        sk = settings.skirting
        source = (
            "cut from each room's floor tile (strips along the long side)"
            if sk.source == "floor_tile"
            else f"{sk.piece_name}, {sk.piece_length_mm.normalize():f} mm pieces"
        )
        out.append(
            Assumption(
                key="skirting",
                title="Skirting",
                text=f"{sk.height_mm.normalize():f} mm high, {source}. Room perimeter minus door "
                f"widths, plus {_pct(sk.breakage_pct)} breakage."
                + (" Rooms with tiled walls are left out." if sk.skip_tiled_walls else ""),
            )
        )
    if extras and extras.sundries:
        out.append(
            Assumption(
                key="sundries",
                title="Adhesive, grout and spacers",
                text="; ".join(f"{x.label}: {x.basis}" for x in extras.sundries)
                + ". Planks and roll flooring aren't included.",
            )
        )
    missing = ["grout joint width (tiles are counted edge to edge)"]
    if not (extras and extras.skirting):
        missing.append("skirting")
    if not (extras and extras.walls):
        missing.append("wall tiles")
    if not (extras and extras.sundries):
        missing.append("adhesive, grout and spacers")
    missing.append("underlay and trims for wood, vinyl and carpet")
    out.append(
        Assumption(
            key="not_included",
            title="Not included",
            text=_sentence(", ".join(missing)),
        )
    )
    return out
