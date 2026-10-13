"""Client-ready quotation PDF (PRD 4.19): company logo and details, client, line items with the
margin already in the prices, tax, total, terms and a place to accept. Costs and margin are
never printed on the client's copy."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.exports.data import NOTICE
from app.exports.formatting import format_money
from app.exports.pdf import MUTED, RULE, SHADE, _p, _Styles, _table
from app.schemas.quote import CompanyProfile, Quote

NAVY = colors.HexColor("#023b77")
TEAL = colors.HexColor("#039583")


def _qty(value) -> str:
    return f"{value.normalize():f}"


def render_quote(quote: Quote, company: CompanyProfile, logo: bytes | None) -> bytes:
    s = _Styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"Quotation {quote.number}",
        author=company.name or "Floor Planner",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin

    def m(v) -> str:
        return format_money(v, quote.currency, quote.locale, symbols=s.symbols)

    # Header: logo and company on the left, the quotation's details on the right.
    left = []
    if logo:
        try:
            img = Image(io.BytesIO(logo))
            ratio = img.imageWidth / img.imageHeight
            img.drawHeight = 16 * mm
            img.drawWidth = min(16 * mm * ratio, 60 * mm)
            img.hAlign = "LEFT"
            left.append(img)
        except Exception:  # noqa: BLE001, S110 - an unreadable logo just isn't shown
            pass
    if company.name:
        left.append(Paragraph(f"<b>{escape(company.name)}</b>", s.body))
    for line in (company.address, company.phone, company.email, company.website):
        if line:
            left.append(_p(line, s.small))
    if company.tax_id:
        left.append(_p(f"{company.tax_id_label}: {company.tax_id}", s.small))
    title = ParagraphStyle(
        "qtitle", fontName=s.bold, fontSize=20, leading=24, textColor=NAVY, alignment=2
    )
    body_r = ParagraphStyle("qbody", parent=s.body, alignment=2)
    small_r = ParagraphStyle("qsmall", parent=s.small, alignment=2)
    version = f" (version {quote.version})" if quote.version > 1 else ""
    right = [
        Paragraph("Quotation", title),
        Spacer(0, 4),
        _p(f"No. {quote.number}{version}", body_r),
        _p(f"Date: {quote.created_at:%d %b %Y}", small_r),
        _p(f"Valid until: {quote.valid_until:%d %b %Y}", small_r),
    ]
    header = Table([[left, right]], colWidths=[width * 0.6, width * 0.4])
    header.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")])
    )
    band = Table([[""]], colWidths=[width], rowHeights=[3])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL)]))

    client = [Paragraph("<b>Prepared for</b>", s.small), _p(quote.client.name, s.body)]
    for line in (quote.client.address, quote.client.phone, quote.client.email or ""):
        if line:
            client.append(_p(line, s.small))
    project = [Paragraph("<b>Project</b>", s.small), _p(quote.project_name, s.body)]
    who = Table([[client, project]], colWidths=[width * 0.55, width * 0.45])
    who.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    rows: list[list] = [["Description", "Qty", "Unit", "Unit price", "Amount"]]
    for line in quote.lines:
        rows.append(
            [
                _p(line.description, s.cell),
                _qty(line.quantity),
                line.unit,
                m(line.unit_price),
                m(line.amount),
            ]
        )
    items = _table(
        rows, [width * w for w in (0.48, 0.1, 0.1, 0.16, 0.16)], s, right_from=1, total_rows=0
    )

    summary_rows = [["Subtotal", m(quote.subtotal)]]
    if quote.tax_pct > 0:
        summary_rows.append(
            [f"{quote.tax_label} ({quote.tax_pct.normalize():f}%)", m(quote.tax_amount)]
        )
    summary_rows.append(["Total", m(quote.total)])
    summary = Table(summary_rows, colWidths=[width * 0.25, width * 0.2], hAlign="RIGHT")
    summary.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), s.regular, 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
                ("FONT", (0, -1), (-1, -1), s.bold, 11),
                ("TEXTCOLOR", (0, -1), (-1, -1), NAVY),
                ("BACKGROUND", (0, -1), (-1, -1), SHADE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    story: list = [
        header,
        Spacer(0, 6),
        band,
        Spacer(0, 10),
        who,
        Spacer(0, 10),
        items,
        Spacer(0, 8),
        summary,
    ]
    if quote.notes:
        story += [Spacer(0, 10), Paragraph("<b>Notes</b>", s.small), _p(quote.notes, s.body)]
    if quote.terms:
        story += [Spacer(0, 8), Paragraph("<b>Terms</b>", s.small), _p(quote.terms, s.body)]
    accept = Table(
        [["Accepted by (name and signature)", "Date"], ["", ""]],
        colWidths=[width * 0.65, width * 0.35],
        rowHeights=[None, 14 * mm],
    )
    accept.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), s.regular, 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("LINEBELOW", (0, 1), (-1, 1), 0.6, colors.black),
            ]
        )
    )
    story += [Spacer(0, 14), KeepTogether([accept])]
    story += [
        Spacer(0, 10),
        _p(f"{NOTICE} Quantities are worked out from the plan and confirmed on site.", s.small),
    ]

    def footer(canvas, d) -> None:
        canvas.saveState()
        canvas.setFont(s.regular, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(d.leftMargin, 10 * mm, f"{company.name or 'Quotation'} · {quote.number}")
        canvas.drawRightString(d.pagesize[0] - d.rightMargin, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
