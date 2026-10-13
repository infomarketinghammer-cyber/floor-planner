from decimal import Decimal

import pytest

from app.engine.dimensions import DimensionError, parse_length, parse_unit
from app.engine.units import LengthUnit

FT_IN = LengthUnit.FT_IN


@pytest.mark.parametrize(
    "text,default,expected_mm",
    [
        ("12'6\"", FT_IN, "3810.0"),
        ("12' 6\"", FT_IN, "3810.0"),
        ("12'-6\"", FT_IN, "3810.0"),
        ("12’6”", FT_IN, "3810.0"),  # typographic quotes from PDFs/Word
        ("12'6", FT_IN, "3810.0"),
        ("12'", FT_IN, "3657.6"),
        ("12 ft 6 in", FT_IN, "3810.0"),
        ("12.5", FT_IN, "3810.0"),  # bare number in ft-in means decimal feet
        ('150"', FT_IN, "3810.0"),
        ("3.6 m", FT_IN, "3600.0"),  # explicit unit beats the default
        ("3600mm", LengthUnit.M, "3600"),
        ("360 cm", LengthUnit.M, "3600"),
        ("3.6", LengthUnit.M, "3600.0"),
        ("3600", LengthUnit.MM, "3600"),
        (12, LengthUnit.FT, "3657.6"),
    ],
)
def test_parse_length(text, default, expected_mm):
    assert parse_length(text, default) == Decimal(expected_mm)


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "empty"),
        ("12'13\"", "less than 12"),
        ("3,600", "dot for decimals"),
        ("twelve", "not a length"),
        ("0", "greater than zero"),
        ("-3", "not a length"),
    ],
)
def test_parse_length_errors(text, message):
    with pytest.raises(DimensionError, match=message):
        parse_length(text, LengthUnit.FT)


@pytest.mark.parametrize(
    "text,unit",
    [("Feet", LengthUnit.FT), ("ft-in", FT_IN), (" metres ", LengthUnit.M), ("MM", LengthUnit.MM)],
)
def test_parse_unit(text, unit):
    assert parse_unit(text) == unit


def test_parse_unit_rejects_unknown():
    with pytest.raises(DimensionError, match="Unknown unit"):
        parse_unit("yards")
