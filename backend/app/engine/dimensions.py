"""Parse a single written length (e.g. 12'6", 3.6 m, 3600) into exact millimetres."""

import re
from decimal import Decimal, InvalidOperation

from app.engine.units import LengthUnit, feet_inches_to_mm, to_mm

_NUM = r"(\d+(?:\.\d+)?)"
_FEET_INCHES = re.compile(
    rf"^{_NUM}\s*(?:'|ft\.?|feet|foot)\s*-?\s*(?:{_NUM}\s*(?:\"|''|in\.?|inch(?:es)?)?)?$"
)
_INCHES = re.compile(rf"^{_NUM}\s*(?:\"|''|in\.?|inch(?:es)?)$")
_METRIC = re.compile(rf"^{_NUM}\s*(mm|cm|m)$")
_BARE = re.compile(rf"^{_NUM}$")

_QUOTE_FIXES = str.maketrans({"’": "'", "′": "'", "‘": "'", "”": '"', "″": '"', "“": '"'})

_UNIT_ALIASES: dict[str, LengthUnit] = {
    "ft_in": LengthUnit.FT_IN,
    "ft-in": LengthUnit.FT_IN,
    "feet-inches": LengthUnit.FT_IN,
    "ft": LengthUnit.FT,
    "feet": LengthUnit.FT,
    "foot": LengthUnit.FT,
    "in": LengthUnit.IN,
    "inch": LengthUnit.IN,
    "inches": LengthUnit.IN,
    "m": LengthUnit.M,
    "metre": LengthUnit.M,
    "metres": LengthUnit.M,
    "meter": LengthUnit.M,
    "meters": LengthUnit.M,
    "cm": LengthUnit.CM,
    "mm": LengthUnit.MM,
}


class DimensionError(ValueError):
    """A length that can't be read. The message is shown to the user as-is."""


def parse_unit(text: str) -> LengthUnit:
    unit = _UNIT_ALIASES.get(text.strip().lower())
    if unit is None:
        raise DimensionError(f'Unknown unit "{text}". Use ft-in, ft, in, m, cm or mm.')
    return unit


def parse_length(text: str | int | Decimal, default_unit: LengthUnit) -> Decimal:
    """Bare numbers use `default_unit` (feet for ft-in). Explicit marks always win."""
    raw = str(text).strip()
    s = raw.translate(_QUOTE_FIXES).lower()
    if not s:
        raise DimensionError("Length is empty")
    if "," in s:
        raise DimensionError(f'"{raw}": use a dot for decimals and no thousands separators')

    try:
        if m := _FEET_INCHES.match(s):
            feet, inches = Decimal(m[1]), Decimal(m[2] or 0)
            if inches >= 12:
                raise DimensionError(f'"{raw}": inches must be less than 12')
            mm = feet_inches_to_mm(feet, inches)
        elif m := _INCHES.match(s):
            mm = to_mm(m[1], LengthUnit.IN)
        elif m := _METRIC.match(s):
            mm = to_mm(m[1], LengthUnit(m[2]))
        elif m := _BARE.match(s):
            unit = LengthUnit.FT if default_unit == LengthUnit.FT_IN else default_unit
            mm = to_mm(m[1], unit)
        else:
            raise DimensionError(f'"{raw}" is not a length. Examples: 12\'6", 12.5, 3.6 m, 3600 mm')
    except InvalidOperation:
        raise DimensionError(f'"{raw}" is not a valid number') from None

    if mm <= 0:
        raise DimensionError(f'"{raw}": length must be greater than zero')
    return mm
