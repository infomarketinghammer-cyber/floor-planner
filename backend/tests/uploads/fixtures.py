"""Synthetic test inputs: a simple floor plan drawing, PDFs, DXF and DWG headers."""

import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def plan_image(width: int = 2000, height: int = 1400) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    s = width / 2000
    font = ImageFont.load_default(size=max(10, round(28 * s)))
    lw = max(1, round(4 * s))
    rooms = [
        ((100, 100, 900, 700), "BEDROOM 1", "12'0\" x 10'0\""),
        ((900, 100, 1900, 700), "LIVING", "15'0\" x 12'0\""),
        ((100, 700, 700, 1300), "KITCHEN", "10'0\" x 8'0\""),
        ((700, 700, 1900, 1300), "BEDROOM 2", "11'0\" x 9'6\""),
    ]
    for (x0, y0, x1, y1), name, size in rooms:
        box = [round(v * s) for v in (x0, y0, x1, y1)]
        d.rectangle(box, outline="black", width=lw)
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        d.text((cx, cy - 20 * s), name, fill="black", font=font, anchor="mm")
        d.text((cx, cy + 20 * s), size, fill="black", font=font, anchor="mm")
    return img


def blurred(img: Image.Image, radius: float = 4) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def rotated(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, expand=True, fillcolor="white", resample=Image.Resampling.BICUBIC)


def encode(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def text_pdf(page_texts: list[str]) -> bytes:
    """Minimal hand-built PDF with one line of real (selectable) text per page."""
    n = len(page_texts)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET"
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{obj}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def image_pdf(images: list[Image.Image]) -> bytes:
    """A 'scanned' PDF: pages are images with no text layer."""
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=150)
    return buf.getvalue()


def dxf_bytes(*, with_text: bool = True, insunits: int = 2) -> bytes:
    import ezdxf

    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (12, 0), (12, 10), (0, 10)], close=True)
    msp.add_line((12, 0), (27, 0))
    if with_text:
        msp.add_text("BEDROOM 1", dxfattribs={"height": 0.5}).set_placement((4, 5))
        msp.add_mtext("12'0\" x 10'0\"", dxfattribs={"char_height": 0.4}).set_location((4, 4))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


# --- Realistic plan text for extraction tests ------------------------------------------
# (x, y from top, text) in PDF points on a 842 × 595 (A4 landscape) page, 10pt text.
PLAN_LABELS: list[tuple[float, float, str]] = [
    (120, 120, "BEDROOM 1"),
    (115, 134, "12'0\" x 10'0\""),
    (360, 120, "LIVING / DINING"),
    (360, 134, "15'0\" x 12'0\""),
    (600, 120, "KITCHEN"),
    (595, 134, "10'0\" x 8'0\""),
    (120, 330, "TOILET"),
    (115, 344, "7'0\" x 5'0\""),
    (360, 330, "BALCONY 10'0\" x 4'0\""),  # name and size on one line
    (600, 330, "STORE"),  # no size printed
    # Noise the extractor must ignore:
    (250, 200, "D1"),
    (480, 60, "W2"),
    (250, 60, "12'6\""),  # lone wall dimension
    (40, 540, "NOTE: ALL DIMENSIONS ARE IN FEET AND INCHES"),
    (650, 560, "SCALE 1:100"),
    (360, 500, "GROUND FLOOR PLAN"),
]
PLAN_EXPECTED = {
    "Bedroom 1": ("3657.6", "3048.0"),
    "Living / Dining": ("4572.0", "3657.6"),
    "Kitchen": ("3048.0", "2438.4"),
    "Toilet": ("2133.6", "1524.0"),
    "Balcony": ("3048.0", "1219.2"),
    "Store": None,  # flagged: size missing
}


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\(").replace(")", "\)")


def layout_pdf(labels: list[tuple[float, float, str]], width: int = 842, height: int = 595, size: int = 10) -> bytes:
    """One-page PDF with text at given positions (y measured from the top)."""
    ops = " ".join(
        f"BT /F1 {size} Tf {x:.1f} {height - y - size:.1f} Td ({_pdf_escape(t)}) Tj ET" for x, y, t in labels
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
        "/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{obj}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def plan_dxf(insunits: int = 2) -> bytes:
    """The same plan as a DXF in feet: walls, room labels (TEXT and MTEXT), tags, a dimension."""
    import ezdxf

    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 25), (0, 25)], close=True)
    msp.add_line((14, 0), (14, 25))
    msp.add_line((28, 0), (28, 25))
    msp.add_line((0, 12), (40, 12))
    # 0.5 ft text; y measured from the bottom in DXF
    for x, y, text in [(3, 20, "BEDROOM 1"), (17, 20, "LIVING"), (30, 20, "KITCHEN"), (3, 8, "TOILET")]:
        msp.add_text(text, dxfattribs={"height": 0.5}).set_placement((x, y))
    for x, y, text in [(3, 19, "12'0\" x 10'0\""), (17, 19, "15'0\" x 12'0\""), (30, 19, "10'0\" x 8'0\""), (3, 7, "7'0\" x 5'0\"")]:
        msp.add_text(text, dxfattribs={"height": 0.4}).set_placement((x, y))
    msp.add_mtext("BALCONY\P10'0\" x 4'0\"", dxfattribs={"char_height": 0.5}).set_location((17, 8.5))
    msp.add_text("D1", dxfattribs={"height": 0.4}).set_placement((13, 15))
    msp.add_text("NOTE: ALL DIMENSIONS IN FEET", dxfattribs={"height": 0.4}).set_placement((0, -2))
    dim = msp.add_linear_dim(base=(0, 27), p1=(0, 25), p2=(14, 25))  # a wall dimension line
    dim.render()
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()
