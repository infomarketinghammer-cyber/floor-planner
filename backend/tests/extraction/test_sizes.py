from decimal import Decimal

import pytest

from app.engine.units import LengthUnit
from app.extraction.sizes import find_size, resolve_units, to_mm


@pytest.mark.parametrize(
    "text,unit,explicit,mm",
    [
        ("12'0\" x 10'0\"", LengthUnit.FT_IN, True, ("3657.6", "3048.0")),
        ("12'-6\"X10'-0\"", LengthUnit.FT_IN, True, ("3810.0", "3048.0")),
        ("12’0” × 10’0”", LengthUnit.FT_IN, True, ("3657.6", "3048.0")),
        ("3.6 x 3.0 m", LengthUnit.M, True, ("3600.0", "3000.0")),
        ("3.60M X 3.00M", LengthUnit.M, True, ("3600.00", "3000.00")),
        ("3600 x 3000 mm", LengthUnit.MM, True, ("3600", "3000")),
        ("12 x 10 ft", LengthUnit.FT, True, ("3657.6", "3048.0")),
        ("11' x 9'6\"", LengthUnit.FT_IN, True, ("3352.8", "2895.6")),
    ],
)
def test_explicit_sizes(text, unit, explicit, mm):
    m = find_size(text)
    assert m is not None
    assert (m.unit, m.unit_explicit) == (unit, explicit)
    assert to_mm(m) == (Decimal(mm[0]), Decimal(mm[1]))


@pytest.mark.parametrize(
    "text,guessed",
    [
        ("12x10", LengthUnit.FT),
        ("3600 x 3000", LengthUnit.MM),
        ("3.6 x 3.0", LengthUnit.M),
        ("360 x 300", LengthUnit.CM),
    ],
)
def test_bare_sizes_get_a_guessed_unit(text, guessed):
    m = find_size(text)
    assert m is not None and m.unit is None
    resolve_units([m], plan_unit=None)
    assert m.unit == guessed
    assert not m.unit_explicit


def test_plan_unit_beats_guess_and_page_majority_beats_guess():
    m = find_size("12x10")
    resolve_units([m], plan_unit=LengthUnit.M)
    assert m.unit == LengthUnit.M

    bare, explicit = find_size("3600 x 3000"), find_size("12'0\" x 10'0\"")
    resolve_units([bare, explicit], plan_unit=None)
    assert bare.unit == LengthUnit.FT_IN  # follows the page's written convention


def test_size_inside_a_label_reports_its_position():
    text = "BEDROOM 1 12'0\" x 10'0\""
    m = find_size(text)
    assert text[: m.start].strip() == "BEDROOM 1"


@pytest.mark.parametrize(
    "text",
    ["12'6\"", "3600", "BEDROOM", "D1", "SCALE 1:100", "AREA 120 SQ FT", "Bedroom 2"],
)
def test_not_a_room_size(text):
    assert find_size(text) is None  # single lengths (wall dimension lines) and labels
