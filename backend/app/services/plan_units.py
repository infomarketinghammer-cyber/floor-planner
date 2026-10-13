"""Plan unit (PRD 4.4): detect it, explain why, and re-read sizes when the user corrects it.

Rooms whose unit was *written* on the plan, or set by the user, keep their own unit (an
override). Rooms with bare numbers (unit_explicit=False) follow the plan unit; changing the
plan unit re-reads their numbers in the new unit.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.engine.units import MM_PER_UNIT, LengthUnit
from app.schemas.project import Room, RoomOrigin

UNIT_NAMES: dict[LengthUnit, str] = {
    LengthUnit.FT_IN: "feet and inches",
    LengthUnit.FT: "feet",
    LengthUnit.IN: "inches",
    LengthUnit.M: "metres",
    LengthUnit.CM: "centimetres",
    LengthUnit.MM: "millimetres",
}


@dataclass(frozen=True)
class PlanUnit:
    unit: LengthUnit | None  # the confirmed unit, else the detected one
    confirmed: bool
    detected: LengthUnit | None
    evidence: str  # why we think so, shown to the user
    required: bool  # rooms came from a plan, so the user must confirm the unit (PRD 6.3)

    @property
    def needs_confirmation(self) -> bool:
        return self.required and not self.confirmed


def _per_unit(unit: LengthUnit) -> Decimal:
    # A bare number under feet-inches means decimal feet.
    return MM_PER_UNIT[LengthUnit.FT if unit == LengthUnit.FT_IN else unit]


def reinterpret(mm: Decimal | None, old: LengthUnit, new: LengthUnit) -> Decimal | None:
    """Same written number, different unit: 3600 read as mm -> the same 3600 read as cm."""
    if mm is None or old == new:
        return mm
    return (mm / _per_unit(old) * _per_unit(new)).normalize()


def _from_plan(room: Room) -> bool:
    return room.origin in (RoomOrigin.AUTO, RoomOrigin.EDITED) and room.source is not None


def detect(rooms: list[Room], drawing_unit: LengthUnit | None) -> tuple[LengthUnit | None, str]:
    from_plan = [r for r in rooms if _from_plan(r) and r.length_mm is not None]
    if drawing_unit is not None:
        return drawing_unit, f"The CAD drawing says its units are {UNIT_NAMES[drawing_unit]}."

    written = Counter(r.unit for r in from_plan if r.origin == RoomOrigin.AUTO and r.unit_explicit)
    if written:
        unit, count = written.most_common(1)[0]
        total = sum(written.values())
        return unit, f"{count} of {total} sizes on the plan are written in {UNIT_NAMES[unit]}."

    if from_plan:
        unit = Counter(r.unit for r in from_plan).most_common(1)[0][0]
        example = from_plan[0].source.text if from_plan[0].source else ""
        hint = f' (e.g. "{example.split(" — ")[-1]}")' if example else ""
        return (
            unit,
            f"No units are written on the plan. The numbers{hint} look like {UNIT_NAMES[unit]}.",
        )

    if rooms:
        unit = Counter(r.unit for r in rooms).most_common(1)[0][0]
        return unit, f"Most rooms were entered in {UNIT_NAMES[unit]}."
    return None, ""


def plan_unit_state(doc: dict, rooms: list[Room]) -> PlanUnit:
    drawing = doc.get("drawing_unit")
    detected, evidence = detect(rooms, LengthUnit(drawing) if drawing else None)
    confirmed_unit = doc.get("plan_unit") if doc.get("plan_unit_confirmed") else None
    return PlanUnit(
        unit=LengthUnit(confirmed_unit) if confirmed_unit else detected,
        confirmed=confirmed_unit is not None,
        detected=detected,
        evidence=evidence,
        required=any(_from_plan(r) for r in rooms),
    )


def apply_plan_unit(rooms: list[Room], unit: LengthUnit) -> int:
    """Re-read rooms that follow the plan unit. Returns how many sizes changed (and were
    un-confirmed, since their quantities change)."""
    changed = 0
    for room in rooms:
        if room.unit_explicit or room.unit == unit:
            continue
        new_length = reinterpret(room.length_mm, room.unit, unit)
        new_width = reinterpret(room.width_mm, room.unit, unit)
        if (new_length, new_width) != (room.length_mm, room.width_mm):
            changed += 1
            room.confirmed = False
        room.length_mm, room.width_mm, room.unit = new_length, new_width, unit
    return changed
