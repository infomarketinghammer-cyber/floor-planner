"""Find and parse room size text: 12'0" x 10'0", 3.6 x 3.0 m, 3600 x 3000, 12x10 (PRD 4.2)."""

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.engine.dimensions import DimensionError, parse_length
from app.engine.units import LengthUnit

_QUOTES = str.maketrans({"’": "'", "′": "'", "‘": "'", "`": "'", "”": '"', "″": '"', "“": '"'})

_NUM = r"\d+(?:\.\d+)?"
# One side: 12'6"  12'-6"  12'  150"  3.6  3600  3.6m  3600 mm
_SIDE = rf"""{_NUM}(?:\s*'\s*-?\s*(?:{_NUM}\s*(?:"|'')?)?|\s*"|\s*(?:mm|cm|m)(?![a-z]))?"""
_SIZE = re.compile(
    rf"(?<![\w.])(?P<a>{_SIDE})\s*(?:x|\*|×|by)\s*(?P<b>{_SIDE})(?:\s*(?P<unit>mm|cm|m|ft|feet)(?![a-z]))?",
    re.IGNORECASE,
)
_EXPLICIT_METRIC = re.compile(r"(mm|cm|m)$")


@dataclass
class SizeMatch:
    """A size found in text. `unit` is None until resolved for bare numbers like 12x10."""

    text: str  # the matched size text, as written
    start: int  # position in the source string (to split "BEDROOM 12'x10'" into name + size)
    end: int
    a: str
    b: str
    unit: LengthUnit | None
    unit_explicit: bool


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


def _side_unit(side: str) -> LengthUnit | None:
    s = side.lower()
    if "'" in s or '"' in s:
        return LengthUnit.FT_IN
    if m := _EXPLICIT_METRIC.search(s.strip()):
        return LengthUnit(m[1])
    return None


def find_size(text: str) -> SizeMatch | None:
    """First L x W size in `text`, or None. Single lengths (wall dimension lines) never match."""
    norm = normalize(text)
    m = _SIZE.search(norm)
    if m is None:
        return None
    unit: LengthUnit | None = None
    if m["unit"]:
        unit = (
            LengthUnit.FT if m["unit"].lower() in ("ft", "feet") else LengthUnit(m["unit"].lower())
        )
    else:
        unit = _side_unit(m["a"]) or _side_unit(m["b"])
    return SizeMatch(
        text=m[0].strip(),
        start=m.start(),
        end=m.end(),
        a=m["a"].strip(),
        b=m["b"].strip(),
        unit=unit,
        unit_explicit=unit is not None,
    )


def _numbers(match: SizeMatch) -> list[Decimal]:
    return [Decimal(n) for n in re.findall(_NUM, f"{match.a} {match.b}")]


def guess_unit_from_values(match: SizeMatch) -> LengthUnit:
    """Typical room sizes: 3000-9000 → mm, 300-900 → cm, 2.0-15.0 with decimals → m, 6-40 → ft."""
    values = _numbers(match)
    biggest = max(values)
    if biggest >= 1000:
        return LengthUnit.MM
    if biggest >= 100:
        return LengthUnit.CM
    if any(v != v.to_integral_value() for v in values) and biggest < 20:
        return LengthUnit.M
    return LengthUnit.FT


def resolve_units(matches: list[SizeMatch], plan_unit: LengthUnit | None) -> None:
    """Give bare sizes a unit: the drawing's declared unit, else the most common explicit unit
    on the same page, else a guess from the values. Mutates matches; never marks guesses explicit."""
    explicit = Counter(m.unit for m in matches if m.unit_explicit)
    page_unit = plan_unit or (explicit.most_common(1)[0][0] if explicit else None)
    for m in matches:
        if m.unit is None:
            m.unit = page_unit or guess_unit_from_values(m)


def to_mm(match: SizeMatch) -> tuple[Decimal, Decimal]:
    """Raises DimensionError if a side can't be read."""
    assert match.unit is not None, "resolve_units first"
    a, b = parse_length(match.a, match.unit), parse_length(match.b, match.unit)
    return a, b


__all__ = [
    "DimensionError",
    "SizeMatch",
    "find_size",
    "guess_unit_from_values",
    "normalize",
    "resolve_units",
    "to_mm",
]
