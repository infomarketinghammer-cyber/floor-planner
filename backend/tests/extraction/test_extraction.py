from decimal import Decimal

import pytest
from PIL import Image

from app.engine.units import LengthUnit
from app.extraction import vision
from app.extraction.classify import clean_name, is_noise, name_score
from app.extraction.models import TextToken
from app.extraction.pairing import pair_rooms
from app.extraction.service import extract_pages
from app.extraction.sources import dxf_tokens, pdf_page_tokens
from app.extraction.vision import VisionResult, VisionRoom, rooms_from_vision
from app.uploads.inspect import FileKind
from tests.uploads.fixtures import (
    PLAN_EXPECTED,
    PLAN_LABELS,
    encode,
    image_pdf,
    layout_pdf,
    plan_dxf,
    plan_image,
)


def by_name(rooms):
    return {r.name: r for r in rooms}


# --- Classification


@pytest.mark.parametrize(
    "text",
    [
        "BEDROOM 1",
        "Master Bedroom",
        "DRAWING ROOM",
        "WASH AREA",
        "Sit-out",
        "POOJA",
        "WC",
        "Kitchen/Dining",
    ],
)
def test_room_names_score_high(text):
    assert name_score(text) == 1.0


@pytest.mark.parametrize(
    "text",
    [
        "D1",
        "W2",
        "V",
        "MD-3",
        "+0.45 FFL",
        "NOTE: ALL DIMENSIONS IN MM",
        "SCALE 1:100",
        "GROUND FLOOR PLAN",
        "DRAWING NO. A-101",
        "AREA: 1200 SQ FT",
        "TOTAL AREA",
        "12'6\"",
        "LINTEL LEVEL",
    ],
)
def test_noise_is_ignored(text):
    assert is_noise(text)


def test_unknown_short_label_scores_low_but_not_zero():
    assert name_score("STUDIO") == 0.5


def test_clean_name():
    assert clean_name("  BEDROOM  1 ") == "Bedroom 1"
    assert clean_name("MASTER WC") == "Master WC"


# --- Digital PDF and DXF (no AI)


def assert_matches_plan(rooms, expected_names=PLAN_EXPECTED):
    found = by_name(rooms)
    assert set(found) == set(expected_names)
    for name, size in expected_names.items():
        room = found[name]
        if size is None:
            assert room.length_mm is None and "size_missing" in room.flags
        else:
            assert (room.length_mm, room.width_mm) == (Decimal(size[0]), Decimal(size[1])), name
            assert room.level == "high", (name, room.flags)
            assert room.bbox is not None and all(0 <= v <= 1 for v in room.bbox)


def test_pdf_text_plan_extracts_rooms_and_ignores_noise():
    rooms = pair_rooms(pdf_page_tokens(layout_pdf(PLAN_LABELS), 0))
    assert_matches_plan(rooms)


def test_pdf_source_location_points_at_the_label():
    rooms = by_name(pair_rooms(pdf_page_tokens(layout_pdf(PLAN_LABELS), 0)))
    x0, y0, x1, y1 = rooms["Kitchen"].bbox
    # KITCHEN is printed at x≈595-640pt, y≈120-144pt on an 842×595pt page.
    assert 0.69 < x0 < 0.72 and x1 < 0.8
    assert 0.18 < y0 < 0.23 and y1 < 0.27


def test_dxf_plan_uses_drawing_units():
    tokens, unit = dxf_tokens(plan_dxf())
    assert unit == LengthUnit.FT
    rooms = pair_rooms(tokens, unit)
    expected = {k: v for k, v in PLAN_EXPECTED.items() if k not in ("Store",)}
    expected["Living"] = expected.pop("Living / Dining")
    assert_matches_plan(rooms, expected)


def test_dxf_dimension_entities_are_not_read_as_text():
    tokens, _ = dxf_tokens(plan_dxf())
    assert not any(t.text.strip() in ("14'", "14'0\"", "14") for t in tokens)


def test_bare_sizes_use_page_majority_unit_and_are_flagged():
    tokens = [
        TextToken("KITCHEN", (0.1, 0.10, 0.2, 0.12)),
        TextToken("3600 x 3000", (0.1, 0.13, 0.2, 0.15)),
    ]
    room = pair_rooms(tokens)[0]
    assert room.unit == LengthUnit.MM
    assert "unit_assumed" in room.flags
    assert room.level == "medium"


def test_ambiguous_pairing_is_flagged():
    # Two names equally close to one size.
    tokens = [
        TextToken("BEDROOM", (0.10, 0.10, 0.20, 0.12)),
        TextToken("STUDY", (0.10, 0.16, 0.20, 0.18)),
        TextToken("12'0\" x 10'0\"", (0.10, 0.13, 0.20, 0.15)),
    ]
    rooms = pair_rooms(tokens)
    paired = next(r for r in rooms if r.size_text)
    assert "ambiguous_pairing" in paired.flags
    assert paired.level != "high"


def test_implausible_size_is_flagged():
    tokens = [
        TextToken("HALL", (0.1, 0.10, 0.2, 0.12)),
        TextToken("120' x 100'", (0.1, 0.13, 0.2, 0.15)),
    ]
    assert "implausible_size" in pair_rooms(tokens)[0].flags


# --- Vision post-processing (model response is faked; no API calls in tests)


def test_vision_results_are_parsed_by_our_code():
    result = VisionResult(
        rooms=[
            VisionRoom(
                name="BEDROOM 1",
                size_text="12'0\" x 10'0\"",
                box=[100, 50, 300, 120],
                legibility="clear",
            ),
            VisionRoom(
                name="KITCHEN", size_text="10x8", box=[400, 50, 520, 120], legibility="unclear"
            ),
            VisionRoom(name="STORE", size_text=None, box=[600, 50, 680, 90], legibility="clear"),
        ]
    )
    rooms = by_name(rooms_from_vision(result, width=1000, height=500, plan_unit=None))
    bed = rooms["Bedroom 1"]
    assert (bed.length_mm, bed.width_mm) == (Decimal("3657.6"), Decimal("3048.0"))
    assert bed.bbox == (0.1, 0.1, 0.3, 0.24)
    assert "ai_read" in bed.flags and bed.level == "high"
    kitchen = rooms["Kitchen"]
    assert kitchen.unit == LengthUnit.FT_IN  # follows the page's written convention
    assert {"unclear_text", "unit_assumed"} <= set(kitchen.flags) and kitchen.level == "low"
    assert "size_missing" in rooms["Store"].flags


def test_vision_box_is_clamped_and_normalised():
    result = VisionResult(
        rooms=[
            VisionRoom(
                name="HALL", size_text="15x12", box=[900, 400, 1200, 700], legibility="clear"
            )
        ]
    )
    (room,) = rooms_from_vision(result, width=1000, height=500, plan_unit=LengthUnit.FT)
    assert room.bbox == (0.9, 0.8, 1.0, 1.0)


async def test_vision_without_api_key_fails_gracefully(monkeypatch):
    monkeypatch.setattr(vision, "is_configured", lambda: False)
    with pytest.raises(vision.VisionUnavailable, match="manually"):
        await vision.read_rooms(Image.new("RGB", (100, 100), "white"))


# --- Routing (PRD 6.1)


async def test_digital_pdf_never_calls_vision(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("vision must not be called for digital PDFs")

    monkeypatch.setattr(vision, "read_rooms", boom)
    (page,) = await extract_pages(
        FileKind.PDF, layout_pdf(PLAN_LABELS), [{"index": 0, "has_text": True}]
    )
    assert page.method == "pdf_text" and len(page.rooms) == 6


async def test_scans_and_photos_route_to_vision(monkeypatch):
    calls = []

    async def fake_read(img, plan_unit=None):
        calls.append(img.size)
        return []

    monkeypatch.setattr(vision, "read_rooms", fake_read)
    pages = [{"index": 0, "has_text": False}, {"index": 1, "has_text": False, "included": False}]
    results = await extract_pages(FileKind.PDF, image_pdf([plan_image(), plan_image()]), pages)
    assert [r.method for r in results] == ["vision"]  # excluded page skipped
    await extract_pages(FileKind.IMAGE, encode(plan_image()), [{"index": 0, "has_text": None}])
    assert len(calls) == 2


async def test_unconfigured_vision_reports_error_per_page(monkeypatch):
    monkeypatch.setattr(vision, "is_configured", lambda: False)
    (page,) = await extract_pages(
        FileKind.IMAGE, encode(plan_image()), [{"index": 0, "has_text": None}]
    )
    assert page.rooms == [] and "isn't set up" in page.error


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Master Bedroom", "Bedroom"),
        ("MBR", "Bedroom"),
        ("Master Bath", "Bathroom & toilet"),  # more specific group wins
        ("Common Toilet", "Bathroom & toilet"),
        ("Kitchen/Dining", "Kitchen"),
        ("Living / Dining", "Living & dining"),
        ("Drawing Room", "Living & dining"),
        ("Sit-out", "Balcony & outdoor"),
        ("Utility", "Utility & storage"),
        ("Passage", "Circulation"),
        ("Study", "Work & study"),
        ("Pooja", "Other"),
    ],
)
def test_room_type(name, expected):
    from app.extraction.classify import room_type

    assert room_type(name) == expected
