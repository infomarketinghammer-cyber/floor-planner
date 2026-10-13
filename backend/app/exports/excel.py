"""Excel workbook with live formulas (openpyxl).

The inputs are values: tiles needed, buffer tiles, tiles per box, prices, rates. Everything
worked out from them is a formula, so editing a number in Excel updates boxes, totals, the
shopping list, tax, the project total and the budget check.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.exports.data import NOTICE, ExportData
from app.exports.formatting import AREA_LABELS, area_value, excel_money_format
from app.schemas.cost import LineBasis
from app.services.cost import price_per_box
from app.services.estimate import OFFCUT_NOTE

BOLD = Font(bold=True)
MUTED = Font(color="64748B")
TITLE = Font(bold=True, size=14)
NOTICE_FONT = Font(bold=True, color="92400E")
HEADER_FILL = PatternFill("solid", fgColor="F1F5F9")
TOTAL_FILL = PatternFill("solid", fgColor="F8FAFC")
AREA_FORMAT = "#,##0.00"
INT_FORMAT = "#,##0"
HEADER_ROW = 4
FIRST_ROW = HEADER_ROW + 1


def _title(ws: Worksheet, title: str, data: ExportData) -> None:
    ws["A1"] = f"{title}: {data.project_name}"
    ws["A1"].font = TITLE
    ws["A2"] = f"{NOTICE} Made {data.created_at:%d %b %Y}."
    ws["A2"].font = NOTICE_FONT


def _header(ws: Worksheet, labels: list[str], widths: list[int]) -> None:
    for col, (label, width) in enumerate(zip(labels, widths, strict=True), start=1):
        cell = ws.cell(HEADER_ROW, col, label)
        cell.font = BOLD
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = ws.cell(FIRST_ROW, 1)


def _row(ws: Worksheet, row: int, values: list) -> None:
    for col, value in enumerate(values, start=1):
        ws.cell(row, col, value)


def _total_style(ws: Worksheet, row: int, columns: int) -> None:
    for col in range(1, columns + 1):
        ws.cell(row, col).font = BOLD
        ws.cell(row, col).fill = TOTAL_FILL


def _rooms_sheet(ws: Worksheet, data: ExportData, money: str) -> int:
    """Returns the row of the project total."""
    ws.title = "Rooms"
    _title(ws, "Tile estimate", data)
    unit = AREA_LABELS[data.area_unit]
    labels = [
        "Ref",
        "Room",
        "Floor",
        "Size",
        "Tile",
        f"Area to tile ({unit})",
        "Tiles needed",
        "Buffer tiles",
        "Tiles required",
        "Tiles per box",
        "Boxes",
        "Tiles bought",
    ]
    widths = [6, 22, 12, 18, 28, 14, 11, 11, 11, 11, 9, 12]
    if data.priced:
        labels += ["Price per box", "Cost"]
        widths += [14, 14]
    _header(ws, labels, widths)

    costs = {c.room_id: c for c in data.cost.rooms} if data.cost else {}
    rows = data.estimate.rooms
    last = FIRST_ROW + len(rows) - 1
    for i, r in enumerate(rows):
        n = FIRST_ROW + i
        values = [
            data.ref(r),
            r.name,
            r.floor or "",
            data.size(r),
            f"{r.tile.size_label} · {r.tile.name}",
            float(area_value(r.usable_area_mm2, data.area_unit)),
            r.tiles_needed,
            r.buffer_tiles,
            f"=G{n}+H{n}",
            r.tile.tiles_per_box,
            f"=ROUNDUP(I{n}/J{n},0)",
            f"=K{n}*J{n}",
        ]
        if data.priced:
            price = costs[r.room_id].price
            # The exact price per box (a per-sq-ft price rarely comes to whole cents), so the
            # cost matches the app to the cent.
            values += [
                float(price_per_box(price, r.tile)) if price else None,
                f'=IF(M{n}="","",ROUND(K{n}*M{n},2))',
            ]
        _row(ws, n, values)
        ws.cell(n, 6).number_format = AREA_FORMAT
        if data.priced:
            ws.cell(n, 13).number_format = money
            ws.cell(n, 14).number_format = money

    total = last + 1
    ws.cell(total, 2, "Project total")
    for col in ("F", "G", "H", "I", "K", "L") + (("N",) if data.priced else ()):
        ws[f"{col}{total}"] = f"=SUM({col}{FIRST_ROW}:{col}{last})"
    ws[f"F{total}"].number_format = AREA_FORMAT
    if data.priced:
        ws[f"N{total}"].number_format = money
    _total_style(ws, total, len(labels))

    ws.cell(
        total + 2,
        1,
        "Boxes = tiles required ÷ tiles per box, rounded up. Edit tiles needed, buffer, tiles "
        "per box or price per box and everything else recalculates.",
    ).font = MUTED
    return total


def _shopping_sheet(ws: Worksheet, data: ExportData, rooms_last: int) -> None:
    _title(ws, "Shopping list", data)
    labels = ["Ref", "Tile", "Size", "Tiles per box", "Boxes", "Tiles", "Boxes if leftovers shared"]
    _header(ws, labels, [6, 28, 18, 12, 10, 10, 16])
    refs = f"Rooms!$A${FIRST_ROW}:$A${rooms_last}"
    last = FIRST_ROW + len(data.shopping) - 1
    for i, item in enumerate(data.shopping):
        n = FIRST_ROW + i
        tile = item.tile.tile
        values = [
            item.ref,
            tile.name,
            tile.size_label,
            tile.tiles_per_box,
            f"=SUMIF({refs},A{n},Rooms!$K${FIRST_ROW}:$K${rooms_last})",
            f"=E{n}*D{n}",
            f"=ROUNDUP(SUMIF({refs},A{n},Rooms!$I${FIRST_ROW}:$I${rooms_last})/D{n},0)",
        ]
        _row(ws, n, values)
    total = last + 1
    ws.cell(total, 2, "Total")
    for col in ("E", "F", "G"):
        ws[f"{col}{total}"] = f"=SUM({col}{FIRST_ROW}:{col}{last})"
    _total_style(ws, total, len(labels))


def _costs_sheet(ws: Worksheet, data: ExportData, money: str, rooms_total: int) -> None:
    cost, settings = data.cost, data.settings
    assert cost is not None
    _title(ws, "Cost estimate", data)
    labels = ["Item", "Charged", "Rate", "Quantity", "Amount", "Taxable"]
    _header(ws, labels, [26, 14, 14, 12, 16, 9])

    n = FIRST_ROW
    if data.priced:
        _row(
            ws,
            n,
            [
                "Tiles",
                "boxes × price per box",
                None,
                None,
                f"=Rooms!N{rooms_total}",
                "Yes" if settings.tax_materials else "No",
            ],
        )
        n += 1
    basis_text = {
        LineBasis.FIXED: "fixed",
        LineBasis.SQFT: "per sq ft",
        LineBasis.SQM: "per m²",
        LineBasis.BOX: "per box",
    }
    for line in cost.lines:
        if line.basis == LineBasis.FIXED:
            quantity, amount = None, f"=C{n}"
        elif line.basis == LineBasis.BOX:
            quantity, amount = f"=Rooms!K{rooms_total}", f"=ROUND(C{n}*D{n},2)"
        else:
            # Exact area in the line's own unit (the Rooms sheet may show the other one).
            assert data.estimate.totals is not None
            mm2 = data.estimate.totals.usable_area_mm2
            quantity = float(area_value(mm2, "sqft" if line.basis == LineBasis.SQFT else "sqm"))
            amount = f"=ROUND(C{n}*D{n},2)"
        _row(
            ws,
            n,
            [
                line.label,
                basis_text[line.basis],
                float(line.rate),
                quantity,
                amount,
                "Yes" if line.taxable else "No",
            ],
        )
        n += 1
    last_item = n - 1
    for row in range(FIRST_ROW, n):
        ws[f"C{row}"].number_format = money
        ws[f"D{row}"].number_format = AREA_FORMAT
        ws[f"E{row}"].number_format = money

    items = f"E{FIRST_ROW}:E{last_item}"
    tax_row = None
    if settings.tax_pct > 0:
        tax_row = n
        ws.cell(n, 1, settings.tax_label)
        ws.cell(n, 2, "rate")
        ws.cell(n, 3, float(settings.tax_pct) / 100).number_format = "0.00%"
        ws.cell(n, 4, f'=SUMIF(F{FIRST_ROW}:F{last_item},"Yes",{items})').number_format = money
        ws.cell(n, 5, f"=ROUND(D{n}*C{n},2)").number_format = money
        ws.cell(n + 1, 4, "↑ taxed amount").font = MUTED
        n += 2

    total_row = n
    ws.cell(n, 1, "Project total")
    tax_part = f"+E{tax_row}" if tax_row else ""
    ws.cell(n, 5, f"=SUM({items}){tax_part}").number_format = money
    _total_style(ws, n, len(labels))

    if settings.budget is not None:
        n += 2
        ws.cell(n, 1, "Budget")
        ws.cell(n, 5, float(settings.budget)).number_format = money
        ws.cell(n + 1, 1, "Remaining (negative = over)")
        ws.cell(n + 1, 5, f"=E{n}-E{total_row}").number_format = money
        ws.cell(n + 2, 1, "Status")
        ws.cell(
            n + 2,
            5,
            f'=IF(E{total_row}>E{n},"Over budget",IF(E{total_row}>=0.9*E{n},"Near budget",'
            '"Under budget"))',
        )
        ws.cell(n + 2, 5).font = BOLD


def _assumptions_sheet(ws: Worksheet, data: ExportData) -> None:
    _title(ws, "How the numbers were worked out", data)
    _header(ws, ["Topic", "Assumption"], [22, 110])
    n = FIRST_ROW
    for a in data.estimate.assumptions:
        ws.cell(n, 1, a.title).font = BOLD
        ws.cell(n, 2, a.text).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(n, 1).alignment = Alignment(vertical="top")
        n += 1
    ws.cell(n + 1, 2, OFFCUT_NOTE).alignment = Alignment(wrap_text=True, vertical="top")
    ws.cell(n + 1, 2).font = MUTED


def render_workbook(data: ExportData) -> bytes:
    wb = Workbook()
    money = excel_money_format(data.settings.currency, data.settings.locale)
    rooms_total = _rooms_sheet(wb.active, data, money)
    _shopping_sheet(wb.create_sheet("Shopping list"), data, rooms_total - 1)
    if data.has_costs:
        _costs_sheet(wb.create_sheet("Costs"), data, money, rooms_total)
    _assumptions_sheet(wb.create_sheet("Assumptions"), data)
    wb.calculation.fullCalcOnLoad = True  # formulas have no cached values until Excel runs them
    wb.properties.title = f"{data.project_name}: tile estimate"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
