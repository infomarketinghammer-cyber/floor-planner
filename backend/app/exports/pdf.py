"""PDF report and shopping list (ReportLab).

The report has the master table with totals, the shopping list, the cost breakdown, the
assumptions panel (PRD 4.8) and the "estimate only" notice, which is also on every page footer.
"""

import io
import os
from collections.abc import Callable
from functools import lru_cache
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.exports.data import NOTICE, ExportData
from app.exports.formatting import AREA_LABELS, area_value, format_area, format_number
from app.services.estimate import OFFCUT_NOTE

# TrueType fonts that have the rupee and euro signs, tried in order. ReportLab's built-in
# Helvetica has neither, so without one of these amounts are written with the currency code.
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
RULE = colors.HexColor("#e2e8f0")
SHADE = colors.HexColor("#f8fafc")
WARN_BG = colors.HexColor("#fffbeb")
WARN_INK = colors.HexColor("#92400e")


@lru_cache
def _fonts() -> tuple[str, str, bool]:
    """(regular, bold, has currency symbols)."""
    for regular, bold in _FONT_CANDIDATES:
        if not (os.path.exists(regular) and os.path.exists(bold)):
            continue
        try:
            font = TTFont("FP-Regular", regular)
            if 0x20B9 not in font.face.charToGlyph:  # ₹
                continue
            pdfmetrics.registerFont(font)
            pdfmetrics.registerFont(TTFont("FP-Bold", bold))
            # So <b> inside a paragraph picks the bold face.
            pdfmetrics.registerFontFamily(
                "FP-Regular", normal="FP-Regular", bold="FP-Bold", italic="FP-Regular",
                boldItalic="FP-Bold",
            )  # fmt: skip
            return "FP-Regular", "FP-Bold", True
        except Exception:  # noqa: BLE001, S112 - a broken font file: try the next one
            continue
    return "Helvetica", "Helvetica-Bold", False


class _Styles:
    def __init__(self) -> None:
        regular, bold, self.symbols = _fonts()
        self.regular, self.bold = regular, bold
        self.title = ParagraphStyle("title", fontName=bold, fontSize=16, leading=20, textColor=INK)
        self.h2 = ParagraphStyle(
            "h2", fontName=bold, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4
        )
        self.body = ParagraphStyle("body", fontName=regular, fontSize=9, leading=12, textColor=INK)
        self.small = ParagraphStyle(
            "small", fontName=regular, fontSize=8, leading=10.5, textColor=MUTED
        )
        self.cell = ParagraphStyle("cell", fontName=regular, fontSize=8.5, leading=10.5)
        self.cell_right = ParagraphStyle("cellr", parent=self.cell, alignment=2)
        self.notice = ParagraphStyle(
            "notice", fontName=bold, fontSize=9.5, leading=12, textColor=WARN_INK
        )


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def _table(
    rows: list[list], widths: list[float], s: _Styles, *, right_from: int, total_rows: int = 1
) -> Table:
    """A header row, body rows and `total_rows` bold rows at the end. Columns from
    `right_from` on are numbers, right-aligned."""
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, -1), s.regular, 8.5),
        ("FONT", (0, 0), (-1, 0), s.bold, 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if total_rows:
        style += [
            ("FONT", (0, -total_rows), (-1, -1), s.bold, 8.5),
            ("BACKGROUND", (0, -total_rows), (-1, -1), SHADE),
            ("LINEABOVE", (0, -total_rows), (-1, -total_rows), 1, MUTED),
        ]
    table.setStyle(TableStyle(style))
    return table


def _notice_box(s: _Styles, width: float) -> Table:
    box = Table([[_p(NOTICE, s.notice)]], colWidths=[width])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f59e0b")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return box


def _footer(data: ExportData, s: _Styles) -> Callable:
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(s.regular, 7.5)
        canvas.setFillColor(MUTED)
        y = 10 * mm
        canvas.drawString(doc.leftMargin, y, f"{data.project_name} · {NOTICE}")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, y, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _header(data: ExportData, s: _Styles, title: str) -> list:
    when = data.created_at.strftime("%d %b %Y")
    return [
        _p(title, s.title),
        _p(f"{data.project_name} · {when}", s.small),
        Spacer(0, 6),
    ]


def _shopping_table(data: ExportData, s: _Styles, width: float) -> Table:
    rows: list[list] = [["Ref", "Tile", "Size", "Rooms", "Per box", "Boxes", "Tiles"]]
    for item in data.shopping:
        t = item.tile
        rows.append(
            [
                item.ref,
                _p(t.tile.name, s.cell),
                t.tile.size_label,
                t.rooms,
                t.tile.tiles_per_box,
                t.boxes,
                t.tiles_bought,
            ]
        )
    rows.append(
        [
            "",
            "Total",
            "",
            "",
            "",
            sum(i.tile.boxes for i in data.shopping),
            sum(i.tile.tiles_bought for i in data.shopping),
        ]
    )
    widths = [0.07, 0.33, 0.2, 0.09, 0.1, 0.1, 0.11]
    return _table(rows, [w * width for w in widths], s, right_from=3)


def _pooling_note(data: ExportData) -> str | None:
    saved = [(i, i.tile.boxes - i.tile.boxes_if_pooled) for i in data.shopping]
    saved = [(i, n) for i, n in saved if n > 0]
    if not saved:
        return None
    parts = ", ".join(
        f"{i.ref}: {i.tile.boxes_if_pooled} instead of {i.tile.boxes}" for i, _ in saved
    )
    return f"If leftover tiles are shared between rooms, fewer boxes are needed ({parts})."


def _master_table(data: ExportData, s: _Styles, width: float) -> Table:
    unit = AREA_LABELS[data.area_unit]
    locale = data.settings.locale
    header = [
        "Ref",
        "Room",
        "Floor",
        "Size",
        f"Area ({unit})",
        "Tiles",
        "Buffer",
        "Boxes",
        "Bought",
    ]
    if data.priced:
        header += ["Price / box", "Cost"]
    rows: list[list] = [header]
    costs = {c.room_id: c for c in data.cost.rooms} if data.cost else {}
    sym = s.symbols
    for r in data.estimate.rooms:
        row = [
            data.ref(r),
            _p(r.name, s.cell),
            _p(r.floor or "–", s.cell),
            data.size(r),
            format_number(area_value(r.usable_area_mm2, data.area_unit), locale),
            r.tiles_needed,
            r.buffer_tiles,
            r.boxes,
            r.tiles_bought,
        ]
        if data.priced:
            c = costs[r.room_id]
            row += [
                data.money(c.price_per_box, symbols=sym),
                data.money(c.cost, symbols=sym) if c.cost is not None else "No price",
            ]
        rows.append(row)

    t = data.estimate.totals
    assert t is not None
    total = [
        "",
        "Project total",
        "",
        f"{t.rooms} rooms",
        format_number(area_value(t.usable_area_mm2, data.area_unit), locale),
        sum(r.tiles_needed for r in data.estimate.rooms),
        sum(r.buffer_tiles for r in data.estimate.rooms),
        t.boxes,
        sum(r.tiles_bought for r in data.estimate.rooms),
    ]
    if data.priced:
        total += ["", data.money(data.cost.materials, symbols=sym)]
    rows.append(total)

    widths = [0.05, 0.17, 0.1, 0.14, 0.1, 0.07, 0.07, 0.07, 0.08]
    if data.priced:
        widths = [w * 0.82 / sum(widths) for w in widths] + [0.09, 0.09]
    return _table(rows, [w * width for w in widths], s, right_from=4)


def _cost_table(data: ExportData, s: _Styles, width: float) -> Table:
    cost = data.cost
    assert cost is not None
    sym = s.symbols
    rows: list[list] = [["Item", "Detail", "Amount"]]
    if cost.materials is not None:
        rows.append(
            [
                "Tiles",
                f"{cost.priced_rooms} rooms priced · boxes × price per box",
                data.money(cost.materials, symbols=sym),
            ]
        )
    for line in cost.lines:
        detail = ""
        if line.quantity is not None:
            units = {"sqft": "sq ft", "sqm": "m²", "box": "boxes"}[line.basis]
            detail = (
                f"{data.money(line.rate, symbols=sym)} × "
                f"{format_number(line.quantity, data.settings.locale, 0 if line.basis == 'box' else 2)} {units}"
            )
        if not line.taxable and cost.tax:
            detail = f"{detail} · not taxed" if detail else "Not taxed"
        rows.append(
            [_p(line.label, s.cell), _p(detail, s.cell), data.money(line.amount, symbols=sym)]
        )
    if cost.tax:
        rows.append(
            [
                f"{cost.tax.label} ({cost.tax.pct.normalize():f}%)",
                f"on {data.money(cost.tax.base, symbols=sym)}",
                data.money(cost.tax.amount, symbols=sym),
            ]
        )
    rows.append(["Project total", "", data.money(cost.total, symbols=sym)])
    return _table(rows, [0.3 * width, 0.5 * width, 0.2 * width], s, right_from=2)


def _budget_text(data: ExportData, s: _Styles) -> str | None:
    b = data.cost.budget if data.cost else None
    if b is None:
        return None
    sym = s.symbols
    if b.status == "over":
        return (
            f"Over budget by {data.money(-b.remaining, symbols=sym)} "
            f"(budget {data.money(b.target, symbols=sym)})."
        )
    return (
        f"Budget {data.money(b.target, symbols=sym)}: {b.used_pct}% used, "
        f"{data.money(b.remaining, symbols=sym)} left."
    )


def _assumptions(data: ExportData, s: _Styles) -> list:
    out: list = [_p("How the numbers were worked out", s.h2)]
    for a in data.estimate.assumptions:
        out.append(Paragraph(f"<b>{escape(a.title)}.</b> {escape(a.text)}", s.body))
        out.append(Spacer(0, 3))
    out.append(_p(OFFCUT_NOTE, s.small))
    return out


def render_report(data: ExportData) -> bytes:
    s = _Styles()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"{data.project_name}: tile estimate",
        author="Floor Planner",
    )
    width = page[0] - doc.leftMargin - doc.rightMargin
    t = data.estimate.totals
    assert t is not None

    story: list = [*_header(data, s, "Tile estimate"), _notice_box(s, width), Spacer(0, 8)]
    summary = (
        f"{t.rooms} rooms · {format_area(t.usable_area_mm2, data.area_unit, data.settings.locale)} "
        f"to tile · {t.boxes} boxes · "
        f"{format_number(t.extra_pct, data.settings.locale, 1)}% extra over the area to tile "
        "(cuts, breakage buffer and full boxes)"
    )
    if data.has_costs:
        summary += f" · estimated cost {data.money(data.cost.total, symbols=s.symbols)}"
    story += [_p(summary, s.body), Spacer(0, 4)]

    story += [_p("Rooms", s.h2), _master_table(data, s, width)]
    story += [
        _p(
            "Area is the area to tile, after untiled areas. Tiles = whole tiles needed including "
            "cuts; buffer = extra tiles for breakage; bought = boxes × tiles per box.",
            s.small,
        )
    ]

    shopping = [_p("Shopping list", s.h2), _shopping_table(data, s, width * 0.75)]
    if note := _pooling_note(data):
        shopping.append(_p(note, s.small))
    story.append(KeepTogether(shopping))

    if data.has_costs:
        block = [_p("Cost estimate", s.h2), _cost_table(data, s, width * 0.75)]
        for w in data.cost.warnings:
            block.append(_p(w, s.small))
        if budget := _budget_text(data, s):
            block += [Spacer(0, 3), _p(budget, s.body)]
        story.append(KeepTogether(block))

    story += _assumptions(data, s)
    story += [Spacer(0, 10), _notice_box(s, width)]
    footer = _footer(data, s)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def render_shopping_list(data: ExportData) -> bytes:
    s = _Styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"{data.project_name}: shopping list",
        author="Floor Planner",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin
    story: list = [*_header(data, s, "Tile shopping list"), _shopping_table(data, s, width)]
    if note := _pooling_note(data):
        story.append(_p(note, s.small))
    story += [Spacer(0, 10), _notice_box(s, width)]
    footer = _footer(data, s)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
