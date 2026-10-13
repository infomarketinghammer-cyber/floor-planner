from decimal import Decimal

from app.engine.units import LengthUnit
from app.schemas.project import Room, RoomOrigin, RoomSource
from app.services.plan_units import apply_plan_unit, detect, plan_unit_state, reinterpret
from app.services.review import review_state

_ids = iter(range(10_000))
SRC = RoomSource(file_id="f", page=0, method="pdf_text", text="KITCHEN — 3600 x 3000")


def plan_room(unit: LengthUnit, explicit: bool, length="3600", width="3000", **kw) -> Room:
    base = {
        "id": f"r{next(_ids)}",
        "name": f"Room {next(_ids)}",
        "length_mm": Decimal(length),
        "width_mm": Decimal(width),
        "unit": unit,
        "unit_explicit": explicit,
        "origin": RoomOrigin.AUTO,
        "source": SRC,
    }
    return Room(**(base | kw))


def test_reinterpret_keeps_the_written_number():
    assert reinterpret(Decimal(3600), LengthUnit.MM, LengthUnit.CM) == Decimal(36000)
    assert reinterpret(Decimal(3048), LengthUnit.FT_IN, LengthUnit.M) == Decimal(
        10000
    )  # 10 ft -> 10 m
    assert reinterpret(Decimal(3048), LengthUnit.FT_IN, LengthUnit.FT) == Decimal(3048)
    assert reinterpret(None, LengthUnit.MM, LengthUnit.CM) is None


def test_detect_prefers_drawing_units():
    unit, why = detect([plan_room(LengthUnit.MM, False)], drawing_unit=LengthUnit.FT)
    assert unit == LengthUnit.FT and "CAD drawing" in why


def test_detect_from_written_units_majority():
    rooms = [
        plan_room(LengthUnit.FT_IN, True),
        plan_room(LengthUnit.FT_IN, True),
        plan_room(LengthUnit.M, True),
    ]
    unit, why = detect(rooms, None)
    assert unit == LengthUnit.FT_IN
    assert why == "2 of 3 sizes on the plan are written in feet and inches."


def test_detect_bare_numbers_explains_the_guess():
    unit, why = detect([plan_room(LengthUnit.MM, False)], None)
    assert unit == LengthUnit.MM
    assert "No units are written" in why and '"3600 x 3000"' in why


def test_manual_rooms_do_not_require_confirmation():
    manual = Room(
        id="m", name="Hall", length_mm=Decimal(3000), width_mm=Decimal(3000), unit=LengthUnit.M
    )
    state = plan_unit_state({}, [manual])
    assert (state.unit, state.required, state.needs_confirmation) == (LengthUnit.M, False, False)


def test_apply_plan_unit_only_moves_rooms_that_follow_the_plan():
    follows = plan_room(LengthUnit.MM, False, confirmed=True)
    written = plan_room(LengthUnit.M, True, length="3600.0", width="3000.0", confirmed=True)
    changed = apply_plan_unit([follows, written], LengthUnit.CM)
    assert changed == 1
    assert (follows.length_mm, follows.unit, follows.confirmed) == (
        Decimal(36000),
        LengthUnit.CM,
        False,
    )
    assert (written.length_mm, written.unit, written.confirmed) == (
        Decimal("3600.0"),
        LengthUnit.M,
        True,
    )


def test_project_not_ready_until_plan_unit_confirmed():
    rooms = [plan_room(LengthUnit.MM, False, confirmed=True, flags=["unit_assumed"])]
    doc = {"rooms": [r.model_dump() for r in rooms]}
    pending = review_state(doc)
    assert pending.summary.unit_pending and not pending.summary.ready

    confirmed = review_state(doc | {"plan_unit": "mm", "plan_unit_confirmed": True})
    assert confirmed.summary.ready
    assert confirmed.issues[rooms[0].id] == []  # "unit assumed" no longer a question
