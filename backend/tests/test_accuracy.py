from decimal import Decimal

from app.engine.units import LengthUnit, to_mm
from app.evaluation import eligibility, match_rooms, truth_rooms
from app.schemas.project import ExtractedValues, Room, RoomOrigin, RoomSource
from app.services.accuracy import build_outcomes, corrected_fields, same_size, summarize

FT = LengthUnit.FT


def ft(n) -> Decimal:
    return to_mm(str(n), FT)


def read_room(read_name, length, width, **kw) -> Room:
    """A room as the plan reader produced it, then possibly edited (kw)."""
    values = {
        "id": read_name,
        "name": read_name,
        "length_mm": ft(length),
        "width_mm": ft(width),
        "unit": FT,
        "origin": RoomOrigin.AUTO,
        "source": RoomSource(file_id="f1", page=0, method="pdf_text"),
        "extracted": ExtractedValues(
            name=read_name, length_mm=ft(length), width_mm=ft(width), unit=FT
        ),
    }
    return Room(**(values | kw))


def test_same_size_allows_rounding_and_swapped_sides():
    assert same_size((ft(11), ft("9.5")), (ft("9.5"), ft(11)))
    assert same_size((Decimal(3000), Decimal(3600)), (Decimal(3005), Decimal(3600)))
    assert not same_size((ft(11), ft("9.5")), (ft(11), ft(10)))
    assert same_size((None, None), (None, None))
    assert not same_size((ft(10), None), (ft(10), ft(8)))


def test_corrected_fields():
    room = read_room("Kitchen", 10, 8)
    assert corrected_fields(room) == []
    room.name = "kitchen "  # case and spacing aren't corrections
    assert corrected_fields(room) == []
    room.name, room.width_mm = "Dining", ft("8.5")
    assert corrected_fields(room) == ["name", "size"]
    assert corrected_fields(Room(id="m", name="Store")) == []  # typed in: nothing was read


def test_outcomes_for_each_kind_of_room():
    rooms = [
        read_room("Bedroom", 11, "9.5", confirmed=True),  # right as read
        read_room("Kitchn", 10, 8, name="Kitchen", confirmed=True, origin=RoomOrigin.EDITED),
        read_room("Bath", 6, 5),  # not reviewed yet
        read_room("Balcony", 10, 4, skipped=True),  # looked at and marked not tiled
        Room(id="store", name="Store", length_mm=ft(5), width_mm=ft(4), confirmed=True),
        Room(id="draft", name="Draft", length_mm=ft(5), width_mm=ft(4)),  # unconfirmed hand room
    ]
    by_id = {o["room_id"]: o for o in build_outcomes(rooms)}
    assert by_id["Bedroom"]["status"] == "correct"
    assert by_id["Kitchn"]["status"] == "corrected"
    assert by_id["Kitchn"]["corrected_fields"] == ["name"]
    assert by_id["Kitchn"]["extracted"]["name"] == "Kitchn"
    assert by_id["Kitchn"]["final"]["name"] == "Kitchen"
    assert by_id["Bath"]["status"] == "pending"
    assert by_id["Balcony"]["status"] == "correct"
    assert by_id["store"]["status"] == "added"  # missed by the reader
    assert "draft" not in by_id


def test_no_outcomes_without_extraction():
    rooms = [Room(id="a", name="A", length_mm=ft(5), width_mm=ft(4), confirmed=True)]
    assert build_outcomes(rooms) == []  # a typed-in project says nothing about the reader


def test_summary_rates():
    rooms = [
        read_room("Bedroom", 11, "9.5", confirmed=True),
        read_room("Hall", 12, 10, confirmed=True),
        read_room("Kitchn", 10, 8, name="Kitchen", confirmed=True),
        read_room("Bath", 6, 5, width_mm=ft(6), confirmed=True),
        Room(id="store", name="Store", length_mm=ft(5), width_mm=ft(4), confirmed=True),
    ]
    outcomes = build_outcomes(rooms)
    outcomes.append({**outcomes[0], "room_id": "gone", "status": "deleted", "corrected_fields": []})
    s = summarize(outcomes)
    assert (s.rooms_read, s.correct, s.corrected, s.deleted, s.added) == (5, 2, 2, 1, 1)
    assert s.accuracy_pct == Decimal("40.0")  # 2 right out of 5 reviewed
    assert s.name_accuracy_pct == Decimal("75.0")  # 3 of 4 confirmed names
    assert s.size_accuracy_pct == Decimal("75.0")
    assert s.found_pct == Decimal("80.0")  # 4 of 5 real rooms were found
    assert [m.method for m in s.by_method] == ["pdf_text"]
    assert {c.status for c in s.corrections} == {"corrected", "deleted", "added"}


def test_summary_of_nothing():
    s = summarize([])
    assert s.rooms_read == 0 and s.accuracy_pct is None and s.found_pct is None


# --- evaluation set -----------------------------------------------------------------------------


def project_doc(rooms, **kw) -> dict:
    return {
        "rooms": [r.model_dump() for r in rooms],
        "plan_unit": "ft",
        "plan_unit_confirmed": True,
    } | kw


def test_eligibility():
    blueprint = [{"_id": "f1"}]
    unconfirmed = project_doc([read_room("Bedroom", 11, "9.5")])
    assert "Confirm" in eligibility(unconfirmed, blueprint)
    typed = project_doc([Room(id="a", name="A", length_mm=ft(5), width_mm=ft(4), confirmed=True)])
    assert "read from" in eligibility(typed, blueprint)
    ready = project_doc([read_room("Bedroom", 11, "9.5", confirmed=True)])
    assert eligibility(ready, blueprint) is None
    assert "deleted" in eligibility(ready, [])


def test_truth_is_the_confirmed_room_list():
    doc = project_doc(
        [
            read_room("Bedroom", 11, "9.5", confirmed=True),
            read_room("Balcony", 10, 4, skipped=True),
            read_room("Bath", 6, 5),  # unconfirmed: not verified, not truth
        ]
    )
    truth = truth_rooms(doc)
    assert [t["name"] for t in truth] == ["Bedroom", "Balcony"]
    assert truth[0]["file_id"] == "f1" and truth[0]["page"] == 0


def test_match_rooms_scores_found_missed_and_extra():
    truth = [
        {"name": "Bedroom", "length_mm": ft(11), "width_mm": ft("9.5")},
        {"name": "Kitchen", "length_mm": ft(10), "width_mm": ft(8)},
        {"name": "Store", "length_mm": ft(5), "width_mm": ft(4)},
    ]
    found = [
        {"name": "BEDROOM", "length_mm": ft("9.5"), "width_mm": ft(11)},  # exact, sides swapped
        {"name": "Kitchn", "length_mm": ft(10), "width_mm": ft(8)},  # matched by size
        {"name": "Door", "length_mm": ft(3), "width_mm": ft(7)},  # not a room
    ]
    s = match_rooms(truth, found)
    assert (s.truth, s.found, s.matched) == (3, 3, 2)
    assert s.name_correct == 1 and s.size_correct == 2
    assert s.missed == ["Store"] and s.extra == ["Door"]
