"""Read positioned text from digital PDFs and DXF drawings — no AI involved (PRD 4.2, 6.1)."""

import io
import logging

import pypdfium2 as pdfium
from PIL import Image

from app.engine.units import LengthUnit
from app.extraction.models import TextToken
from app.uploads.inspect import DxfFrame, dxf_drawing, dxf_segments

logger = logging.getLogger(__name__)

_DXF_UNITS = {
    1: LengthUnit.IN,
    2: LengthUnit.FT,
    4: LengthUnit.MM,
    5: LengthUnit.CM,
    6: LengthUnit.M,
}
MAX_DXF_TEXTS = 20_000
VISION_LONG_SIDE = 2576  # current Claude models read images up to this size at full fidelity


def _merge_runs(runs: list[TextToken]) -> list[TextToken]:
    """PDF text often arrives as fragments; join pieces on the same line that nearly touch."""
    runs = sorted(runs, key=lambda t: (round(t.cy, 3), t.bbox[0]))
    lines: list[TextToken] = []
    for run in runs:
        if lines:
            last = lines[-1]
            h = max(last.height, run.height, 1e-6)
            same_line = abs(last.cy - run.cy) < 0.4 * h
            gap = run.bbox[0] - last.bbox[2]
            if same_line and -0.2 * h <= gap < 0.9 * h:
                lines[-1] = TextToken(
                    f"{last.text} {run.text}" if gap > 0.15 * h else last.text + run.text,
                    (
                        last.bbox[0],
                        min(last.bbox[1], run.bbox[1]),
                        run.bbox[2],
                        max(last.bbox[3], run.bbox[3]),
                    ),
                )
                continue
        lines.append(run)
    return lines


def pdf_page_tokens(data: bytes, page_index: int) -> list[TextToken]:
    doc = pdfium.PdfDocument(data)
    try:
        page = doc[page_index]
        width, height = page.get_size()
        textpage = page.get_textpage()
        runs = []
        for i in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(i)
            text = textpage.get_text_bounded(left, bottom, right, top).strip()
            if text:
                runs.append(
                    TextToken(
                        text, (left / width, 1 - top / height, right / width, 1 - bottom / height)
                    )
                )
        return _merge_runs(runs)
    finally:
        doc.close()


def render_pdf_page(data: bytes, page_index: int, long_side: int = VISION_LONG_SIDE) -> Image.Image:
    doc = pdfium.PdfDocument(data)
    try:
        page = doc[page_index]
        w, h = page.get_size()
        return page.render(scale=long_side / max(w, h)).to_pil()
    finally:
        doc.close()


def _text_entities(msp):
    """TEXT/MTEXT in model space, attributes on blocks, and text inside inserted blocks."""
    yield from msp.query("TEXT MTEXT")
    for insert in msp.query("INSERT"):
        yield from insert.attribs
        try:
            yield from (e for e in insert.virtual_entities() if e.dxftype() in ("TEXT", "MTEXT"))
        except Exception:  # a malformed block shouldn't fail the whole drawing
            logger.debug("Skipping text inside unreadable block %s", insert.dxf.name, exc_info=True)


def dxf_tokens(data: bytes) -> tuple[list[TextToken], LengthUnit | None]:
    """Text positions are mapped onto the same frame as the upload thumbnail."""
    from ezdxf import recover

    doc, _ = recover.read(io.BytesIO(data))
    msp = doc.modelspace()
    frame = DxfFrame.from_segments(dxf_segments(msp))
    plan_unit = _DXF_UNITS.get(doc.header.get("$INSUNITS", 0))
    if frame is None:
        return [], plan_unit

    tokens: list[TextToken] = []
    for e in _text_entities(msp):
        if len(tokens) >= MAX_DXF_TEXTS:
            break
        if e.dxftype() == "MTEXT":
            lines = e.plain_text().splitlines()
            x, y = e.dxf.insert.x, e.dxf.insert.y
            h = e.dxf.get("char_height", 1.0) or 1.0
            top = y  # default attachment is top-left
        else:  # TEXT / ATTRIB
            lines = [e.dxf.text]
            h = e.dxf.get("height", 1.0) or 1.0
            halign = e.dxf.get("halign", 0)
            if halign or e.dxf.get("valign", 0):  # aligned text is placed by its align point
                x, y = e.dxf.get("align_point", e.dxf.insert)[:2]
                if halign in (1, 4):  # center / middle
                    x -= 0.3 * h * len(e.dxf.text)
                elif halign == 2:  # right
                    x -= 0.6 * h * len(e.dxf.text)
            else:
                x, y = e.dxf.insert.x, e.dxf.insert.y
            top = y + h
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            line_top = top - i * h * 1.5
            # Approximate text box: ~0.6 × height per character.
            x0, y0 = frame.to_px(x, line_top)
            x1, y1 = frame.to_px(x + 0.6 * h * len(line), line_top - h)
            bbox = (x0 / frame.width, y0 / frame.height, x1 / frame.width, y1 / frame.height)
            tokens.append(
                TextToken(line, tuple(float(v) for v in bbox))
            )  # ezdxf may return numpy floats
    return tokens, plan_unit


PREVIEW_LONG_SIDE = 1600


def render_preview(
    kind: str, data: bytes, page_index: int, long_side: int = PREVIEW_LONG_SIDE
) -> bytes | None:
    """A larger page image for the review screen, in the same frame as the thumbnail, so source
    boxes (fractions of the page) line up. `data` is the converted DXF for DWG files."""
    from ezdxf import recover
    from PIL import ImageOps

    if kind == "pdf":
        img = render_pdf_page(data, page_index, long_side)
    elif kind == "image":
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
    else:
        doc, _ = recover.read(io.BytesIO(data))
        img = dxf_drawing(doc.modelspace(), long_side)
        if img is None:
            return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
