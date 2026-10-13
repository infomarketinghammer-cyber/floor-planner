import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.engine.units import LengthUnit
from app.uploads.inspect import UploadError
from app.uploads.room_import import parse_room_table


def parse(filename: str, data: bytes | str, unit: LengthUnit = LengthUnit.FT_IN, max_rows: int = 500):
    raw = data.encode() if isinstance(data, str) else data
    return parse_room_table(filename, raw, default_unit=unit, max_rows=max_rows)


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_csv_with_length_width_unit_and_floor():
    result = parse(
        "rooms.csv",
        "Room,Length,Width,Unit,Floor\n"
        "Bedroom 1,12'6\",10',ft-in,Ground\n"
        "Kitchen,3.6,3.0,m,Ground\n"
        "Toilet,2400,1500,mm,First\n",
    )
    assert result.errors == []
    assert [(r.row, r.name, r.floor, r.unit) for r in result.rooms] == [
        (2, "Bedroom 1", "Ground", LengthUnit.FT_IN),
        (3, "Kitchen", "Ground", LengthUnit.M),
        (4, "Toilet", "First", LengthUnit.MM),
    ]
    assert result.rooms[0].length_mm == Decimal("3810.0")
    assert result.rooms[1].width_mm == Decimal("3000.0")


def test_default_unit_header_aliases_semicolons_and_bom():
    result = parse("rooms.csv", "﻿Room Name;L;Breadth\nHall;15;12\n", unit=LengthUnit.FT)
    assert result.errors == []
    assert result.rooms[0].length_mm == Decimal("4572.0")


def test_size_column():
    result = parse("rooms.csv", 'Room,Size\nLiving,"15\'0"" x 12\'0"""\nStore,8x6\n')
    assert result.errors == []
    assert [(r.length_mm, r.width_mm) for r in result.rooms] == [
        (Decimal("4572.0"), Decimal("3657.6")),
        (Decimal("2438.4"), Decimal("1828.8")),
    ]


def test_header_with_unit_in_brackets():
    result = parse("rooms.csv", "Room,Length (ft),Width (ft)\nHall,10,8\n")
    assert len(result.rooms) == 1


def test_row_errors_are_reported_and_good_rows_kept():
    result = parse(
        "rooms.csv",
        "Room,Length,Width,Unit\nGood,10,8,ft\n,10,8,ft\nBad,ten,8,ft\nNoWidth,10,,ft\nOdd,10,8,yards\n\n",
    )
    assert [r.name for r in result.rooms] == ["Good"]
    assert [(e.row, e.message.split(":")[0]) for e in result.errors] == [
        (3, "Room name is missing"),
        (4, "Bad"),
        (5, "NoWidth"),
        (6, "Odd"),
    ]


def test_xlsx_with_numeric_cells():
    result = parse("rooms.xlsx", xlsx([["Room", "Length", "Width", "Unit"], ["Kitchen", 3.6, 3, "m"]]))
    assert result.errors == []
    assert result.rooms[0].length_mm == Decimal("3600.0")
    assert result.rooms[0].width_mm == Decimal("3000")


@pytest.mark.parametrize(
    "filename,data,message",
    [
        ("rooms.csv", "Length,Width\n10,8\n", 'No "Room" column'),
        ("rooms.csv", "Room,Unit\nHall,ft\n", '"Length" and "Width"'),
        ("rooms.csv", "\n\n", "empty"),
        ("rooms.xls", b"\xd0\xcf\x11\xe0", ".xlsx or CSV"),
        ("rooms.xlsx", b"not a zip", "can't be opened"),
        ("rooms.txt", "Room,Length,Width\n", ".csv or .xlsx"),
    ],
)
def test_file_level_errors(filename, data, message):
    with pytest.raises(UploadError, match=message):
        parse(filename, data)


def test_row_limit():
    with pytest.raises(UploadError, match="3 rooms; the limit is 2"):
        parse("rooms.csv", "Room,Length,Width\na,1,1\nb,1,1\nc,1,1\n", max_rows=2)
