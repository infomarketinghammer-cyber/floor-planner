"""Number, money, length and area text for exports.

The browser formats with Intl; exports are made on the server, so this mirrors it for the
regions the cost settings offer (frontend/src/lib/money.ts). Anything else falls back to
"1,234.56" with the currency code.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.engine.units import MM2_PER_SQFT, MM2_PER_SQM, MM_PER_UNIT, LengthUnit

AreaUnit = Literal["sqft", "sqm"]


@dataclass(frozen=True)
class _Region:
    group: str
    decimal: str
    indian: bool = False  # 12,34,567: groups of two after the first three digits
    symbol_after: bool = False  # "1.234,56 €"


_REGIONS: dict[str, _Region] = {
    "en-IN": _Region(",", ".", indian=True),
    "en-US": _Region(",", "."),
    "en-GB": _Region(",", "."),
    "en-AU": _Region(",", "."),
    "en-AE": _Region(",", "."),
    "de-DE": _Region(".", ",", symbol_after=True),
    "fr-FR": _Region(" ", ",", symbol_after=True),
    "es-ES": _Region(".", ",", symbol_after=True),
}
_DEFAULT_REGION = _Region(",", ".")

_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "CA$",
    "SGD": "S$",
    "NZD": "NZ$",
    "ZAR": "R",
}
_NO_DECIMALS = {"JPY"}


def _region(locale: str) -> _Region:
    return _REGIONS.get(locale, _DEFAULT_REGION)


def _group(digits: str, region: _Region) -> str:
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    size = 2 if region.indian else 3
    parts = []
    while head:
        parts.insert(0, head[-size:])
        head = head[:-size]
    return region.group.join([*parts, tail])


def format_number(value: Decimal | float, locale: str, places: int = 2) -> str:
    """Rounded to `places`, with the region's grouping and decimal mark. Trailing zeros kept."""
    region = _region(locale)
    d = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    whole, _, frac = f"{abs(d):f}".partition(".")
    text = _group(whole, region)
    return f"{sign}{text}{region.decimal}{frac}" if frac else f"{sign}{text}"


def symbol(currency: str) -> str | None:
    return _SYMBOLS.get(currency)


def format_money(
    value: Decimal | float | None, currency: str, locale: str, *, symbols: bool = True
) -> str:
    """E.g. ₹12,34,567.89, $1,234.50 or 1.234,50 €. `symbols=False` writes the code instead,
    for fonts without the currency sign."""
    if value is None:
        return "–"
    places = 0 if currency in _NO_DECIMALS else 2
    d = Decimal(str(value))
    number = format_number(abs(d), locale, places)
    sign = "-" if d < 0 else ""
    mark = symbol(currency) if symbols else None
    if _region(locale).symbol_after:
        return f"{sign}{number} {mark or currency}"
    return f"{sign}{mark}{number}" if mark else f"{sign}{currency} {number}"


def excel_money_format(currency: str, locale: str) -> str:
    """An Excel number format. Excel applies the reader's own separators."""
    mark = symbol(currency)
    number = "#,##0" if currency in _NO_DECIMALS else "#,##0.00"
    if _region(locale).symbol_after:
        return f'{number} "{mark or currency}"'
    return f'"{mark}"{number}' if mark else f'"{currency} "{number}'


def area_value(mm2: Decimal, unit: AreaUnit) -> Decimal:
    return mm2 / (MM2_PER_SQFT if unit == "sqft" else MM2_PER_SQM)


AREA_LABELS: dict[AreaUnit, str] = {"sqft": "sq ft", "sqm": "m²"}


def format_area(mm2: Decimal, unit: AreaUnit, locale: str = "en-US") -> str:
    return f"{format_number(area_value(mm2, unit), locale)} {AREA_LABELS[unit]}"


_SUFFIX = {
    LengthUnit.FT: " ft",
    LengthUnit.IN: '"',
    LengthUnit.M: " m",
    LengthUnit.CM: " cm",
    LengthUnit.MM: " mm",
}
_PLACES = {LengthUnit.FT: 2, LengthUnit.IN: 1, LengthUnit.M: 3, LengthUnit.CM: 1, LengthUnit.MM: 0}


def _trim(value: Decimal, places: int) -> str:
    d = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP).normalize()
    return f"{d:f}"


def format_length(mm: Decimal | None, unit: LengthUnit) -> str:
    """12'6" for feet-inches, else the value in the room's own unit (as the app shows it)."""
    if mm is None:
        return "?"
    if unit == LengthUnit.FT_IN:
        tenths = (mm / Decimal("2.54")).quantize(Decimal(1), rounding=ROUND_HALF_UP)  # 0.1"
        feet, rest = divmod(int(tenths), 120)
        return f"{feet}'{_trim(Decimal(rest) / 10, 1)}\""
    return f"{_trim(mm / MM_PER_UNIT[unit], _PLACES[unit])}{_SUFFIX[unit]}"
