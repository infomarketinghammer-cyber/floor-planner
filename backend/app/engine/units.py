"""Exact unit conversion. All internal lengths are Decimal millimetres."""

from decimal import Decimal
from enum import StrEnum


class LengthUnit(StrEnum):
    FT_IN = "ft_in"  # feet + inches, e.g. 12'6"
    FT = "ft"
    IN = "in"
    M = "m"
    CM = "cm"
    MM = "mm"


MM_PER_UNIT: dict[LengthUnit, Decimal] = {
    LengthUnit.FT: Decimal("304.8"),
    LengthUnit.IN: Decimal("25.4"),
    LengthUnit.M: Decimal(1000),
    LengthUnit.CM: Decimal(10),
    LengthUnit.MM: Decimal(1),
}

MM2_PER_SQFT = MM_PER_UNIT[LengthUnit.FT] ** 2
MM2_PER_SQM = MM_PER_UNIT[LengthUnit.M] ** 2


def _dec(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Pass lengths as Decimal, int or str, never float")
    return Decimal(value)


def to_mm(value: Decimal | int | str, unit: LengthUnit) -> Decimal:
    if unit == LengthUnit.FT_IN:
        raise ValueError("Use feet_inches_to_mm for feet-inches values")
    return _dec(value) * MM_PER_UNIT[unit]


def feet_inches_to_mm(feet: Decimal | int | str, inches: Decimal | int | str = 0) -> Decimal:
    return _dec(feet) * MM_PER_UNIT[LengthUnit.FT] + _dec(inches) * MM_PER_UNIT[LengthUnit.IN]


def mm2_to_sqft(area_mm2: Decimal) -> Decimal:
    return area_mm2 / MM2_PER_SQFT


def mm2_to_sqm(area_mm2: Decimal) -> Decimal:
    return area_mm2 / MM2_PER_SQM
