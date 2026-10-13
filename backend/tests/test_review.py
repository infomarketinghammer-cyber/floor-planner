import io
from decimal import Decimal

import pytest
from ezdxf import recover

from app.extraction.sources import dxf_tokens
from app.schemas.project import Room, RoomOrigin
from app.services.review import blocking_issues, room_issues, summarize_review
from app.uploads.inspect import DxfFrame, dxf_segments
from tests.uploads.fixtures import plan_dxf

_ids = iter(range(10_000))


def room(**kw) -> Room:
    base = {
        "id": f"r{next(_ids)}",
        "name": "Bedroom",
        "length_mm": Decimal(3600),
        "width_mm": Decimal(3000),
        "origin": RoomOrigin.MANUAL,
    }
    return Room(**(base | kw))


def codes(rooms: list[Room]) -> dict[str, set[str]]:
    issues = room_issues(rooms)
    return {r.name: {i.code for i in issues[r.id]} for r in rooms}


def test_clean_room_has_no_issues():
    assert codes([room()]) == {"Bedroom": set()}


def test_missing_size_blocks_confirmation():
    r = room(width_mm=None)
    issues = room_issues([r])
    assert [i.code for i in blocking_issues(r, issues)] == ["size_missing"]


def test_unnamed_auto_room_blocks_until_renamed():
    auto = room(name="Unnamed room", origin=RoomOrigin.AUTO, flags=["name_missing"])
    assert "name_missing" in codes([auto])["Unnamed room"]
    renamed = auto.model_copy(update={"name": "Store", "origin": RoomOrigin.EDITED})
    assert codes([renamed])["Store"] == set()


@pytest.mark.parametrize("length", [Decimal(400), Decimal(45_000)])
def test_implausible_size_warns(length):
    issues = room_issues([r := room(length_mm=length)])[r.id]
    assert [(i.code, i.severity) for i in issues] == [("implausible_size", "warn")]


def test_duplicates_same_floor_or_same_size():
    a = room(name="Kitchen", floor="Ground")
    b = room(name="KITCHEN ", floor="ground", length_mm=Decimal(4000))  # same floor, different size
    c = room(name="Living", floor="Ground")
    d = room(name="Living", floor=None)  # same name and size, different floor (plan uploaded twice)
    e = room(name="Bedroom", floor="First")
    f = room(
        name="Bedroom", floor="Ground", length_mm=Decimal(4000)
    )  # different floor and size: fine
    issues = room_issues([a, b, c, d, e, f])
    dup = {r.id for r in (a, b, c, d, e, f) if any(i.code == "duplicate" for i in issues[r.id])}
    assert dup == {a.id, b.id, c.id, d.id}


def test_skipped_rooms_are_ignored():
    a, b = room(name="Kitchen"), room(name="Kitchen", skipped=True, width_mm=None)
    issues = room_issues([a, b])
    assert issues[a.id] == [] and issues[b.id] == []


def test_extraction_flags_show_only_until_confirmed_or_edited():
    auto = room(
        origin=RoomOrigin.AUTO, confidence_level="low", flags=["unit_assumed"], unit_explicit=False
    )
    assert codes([auto])["Bedroom"] == {"low_confidence"}  # unit is confirmed plan-wide instead
    assert codes([auto.model_copy(update={"confirmed": True})])["Bedroom"] == set()
    assert codes([auto.model_copy(update={"origin": RoomOrigin.EDITED})])["Bedroom"] == set()


def test_review_summary_ready_only_when_all_confirmed():
    rooms = [room(confirmed=True), room(name="Kitchen"), room(name="Store", skipped=True)]
    summary = summarize_review(rooms, room_issues(rooms))
    assert (summary.total, summary.confirmed, summary.to_review, summary.ready) == (3, 1, 1, False)
    rooms[1].confirmed = True
    assert summarize_review(rooms, room_issues(rooms)).ready
    assert not summarize_review([], {}).ready


def test_dxf_boxes_line_up_on_larger_previews():
    doc, _ = recover.read(io.BytesIO(plan_dxf()))
    segments = dxf_segments(doc.modelspace())
    small, large = DxfFrame.from_segments(segments, 640), DxfFrame.from_segments(segments, 1600)
    for x, y in [(0, 0), (40, 25), (17, 19.4)]:
        sx, sy = small.to_px(x, y)
        lx, ly = large.to_px(x, y)
        assert abs(sx / small.width - lx / large.width) < 0.002
        assert abs(sy / small.height - ly / large.height) < 0.002
    tokens, _ = dxf_tokens(plan_dxf())
    assert all(0 <= v <= 1 for t in tokens if t.text == "LIVING" for v in t.bbox)
