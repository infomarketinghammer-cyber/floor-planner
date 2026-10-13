"""Parse an Excel/CSV room list (PRD 4.1 alternative input). Pure: bytes in, rows + errors out."""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.engine.dimensions import DimensionError, parse_length, parse_unit
from app.engine.units import LengthUnit
from app.uploads.inspect import UploadError

MAX_TABLE_BYTES = 2 * 1_048_576

_HEADERS: dict[str, set[str]] = {
    "name": {"room", "room name", "name", "room_name", "space"},
    "length": {"length", "l", "len", "room length"},
    "width": {"width", "w", "breadth", "b", "room width"},
    "size": {"size", "dimensions", "dimension", "room size", "l x w"},
    "unit": {"unit", "units", "uom"},
    "floor": {"floor", "level", "storey", "story"},
}
_SIZE_SPLIT = re.compile(r"\s*(?:x|×|\*|by)\s*", re.IGNORECASE)


@dataclass
class ParsedRoom:
    row: int  # spreadsheet row number, header = 1
    name: str
    floor: str | None
    length_mm: Decimal
    width_mm: Decimal
    unit: LengthUnit


@dataclass
class RowError:
    row: int
    message: str


@dataclass
class ImportResult:
    rooms: list[ParsedRoom] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):  # Excel numbers; repr keeps 3.6 as "3.6", not 3.6000000000000001
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value).strip()


def _read_csv(data: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UploadError("The CSV file's text encoding isn't supported. Save it as UTF-8 CSV.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError):
        raise UploadError("This Excel file can't be opened. Save it again as .xlsx and retry.") from None
    try:
        sheet = wb.worksheets[0]
        return [[_cell(c) for c in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        wb.close()


def _map_headers(header: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for i, raw in enumerate(header):
        key = re.sub(r"\s*\(.*\)\s*$", "", raw.strip().lower())  # "Length (ft)" -> "length"
        for field_name, aliases in _HEADERS.items():
            if key in aliases and field_name not in columns:
                columns[field_name] = i
    if "name" not in columns:
        raise UploadError('No "Room" column found. The first row must be headers: Room, Length, Width, Unit, Floor.')
    if not ({"length", "width"} <= columns.keys() or "size" in columns):
        raise UploadError('Add "Length" and "Width" columns (or one "Size" column like 12\'0" x 10\'0").')
    return columns


def parse_room_table(
    filename: str, data: bytes, *, default_unit: LengthUnit, max_rows: int
) -> ImportResult:
    ext = Path(filename).suffix.lower()
    if len(data) > MAX_TABLE_BYTES:
        raise UploadError("Room lists are limited to 2 MB.", status_code=413)
    if ext == ".csv":
        table = _read_csv(data)
    elif ext == ".xlsx":
        table = _read_xlsx(data)
    elif ext == ".xls":
        raise UploadError("Old .xls files aren't supported. Save the sheet as .xlsx or CSV.", status_code=415)
    else:
        raise UploadError("Room lists must be .csv or .xlsx files.", status_code=415)

    table = [row for row in table if any(row)]
    if not table:
        raise UploadError("The file is empty.")
    columns = _map_headers(table[0])
    if len(table) - 1 > max_rows:
        raise UploadError(f"The list has {len(table) - 1} rooms; the limit is {max_rows}.")

    def get(row: list[str], name: str) -> str:
        i = columns.get(name)
        return row[i] if i is not None and i < len(row) else ""

    result = ImportResult()
    for offset, row in enumerate(table[1:], start=2):
        name = get(row, "name")
        if not name:
            result.errors.append(RowError(offset, "Room name is missing"))
            continue
        try:
            unit = parse_unit(get(row, "unit")) if get(row, "unit") else default_unit
            if get(row, "length") or get(row, "width") or "size" not in columns:
                length_text, width_text = get(row, "length"), get(row, "width")
            else:
                parts = _SIZE_SPLIT.split(get(row, "size"))
                if len(parts) != 2:
                    raise DimensionError(f'Size "{get(row, "size")}" should look like 12\'0" x 10\'0"')
                length_text, width_text = parts
            if not length_text or not width_text:
                raise DimensionError("Length and width are both required")
            result.rooms.append(
                ParsedRoom(
                    row=offset,
                    name=name[:100],
                    floor=get(row, "floor")[:50] or None,
                    length_mm=parse_length(length_text, unit),
                    width_mm=parse_length(width_text, unit),
                    unit=unit,
                )
            )
        except DimensionError as e:
            result.errors.append(RowError(offset, f"{name}: {e}"))
    return result
