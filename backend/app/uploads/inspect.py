"""Validate and inspect an uploaded blueprint (PRD 4.1). CPU-bound: call from a worker thread.

Checks, in order: extension is supported, content matches the extension (magic bytes),
size and page limits, the file actually opens, then per-page quality and metadata.
"""

import io
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from app.engine.units import LengthUnit
from app.uploads.quality import Warning, assess_image

Image.MAX_IMAGE_PIXELS = 100_000_000  # larger raises DecompressionBombError

THUMBNAIL_LONG_SIDE = 640
SCAN_ANALYSIS_DPI = 150
SCAN_ANALYSIS_MAX_PX = 2000


class FileKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DXF = "dxf"
    DWG = "dwg"


EXTENSIONS: dict[str, FileKind] = {
    ".pdf": FileKind.PDF,
    ".png": FileKind.IMAGE,
    ".jpg": FileKind.IMAGE,
    ".jpeg": FileKind.IMAGE,
    ".dxf": FileKind.DXF,
    ".dwg": FileKind.DWG,
}

_DXF_UNITS = {1: LengthUnit.IN, 2: LengthUnit.FT, 4: LengthUnit.MM, 5: LengthUnit.CM, 6: LengthUnit.M}
_FLOOR = re.compile(
    r"\b(basement|cellar|stilt|lower ground|upper ground|ground|first|second|third|fourth|fifth|"
    r"terrace|roof|mezzanine|\d+(?:st|nd|rd|th))\s+floor\b",
    re.IGNORECASE,
)


class UploadError(Exception):
    """Rejected upload. `message` is shown to the user as-is."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PageInfo:
    index: int
    width: int  # pixels for images, points for PDF pages, drawing units for DXF
    height: int
    has_text: bool | None  # None when not applicable (images)
    floor_guess: str | None = None
    warnings: list[Warning] = field(default_factory=list)
    thumbnail_png: bytes | None = None


@dataclass
class Inspection:
    kind: FileKind
    content_type: str
    pages: list[PageInfo]
    warnings: list[Warning] = field(default_factory=list)
    detected_unit: LengthUnit | None = None
    converted_dxf: bytes | None = None  # DWG converted to DXF


def _png(img: Image.Image) -> bytes:
    img = img.copy()
    img.thumbnail((THUMBNAIL_LONG_SIDE, THUMBNAIL_LONG_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _floor_guess(text: str) -> str | None:
    m = _FLOOR.search(text)
    return f"{m[1].title()} Floor" if m else None


# --- Type detection -----------------------------------------------------------------


def detect_kind(filename: str, data: bytes) -> tuple[FileKind, str]:
    ext = Path(filename).suffix.lower()
    kind = EXTENSIONS.get(ext)
    if kind is None:
        raise UploadError(
            f'"{ext or filename}" files are not supported. Upload a PDF, JPG, PNG, DXF or DWG file.',
            status_code=415,
        )
    if not data:
        raise UploadError("The file is empty.")

    head = data[:2048]
    if kind == FileKind.PDF and b"%PDF-" in head[:1024]:
        return kind, "application/pdf"
    if kind == FileKind.IMAGE:
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return kind, "image/png"
        if head.startswith(b"\xff\xd8\xff"):
            return kind, "image/jpeg"
    if kind == FileKind.DWG and head[:4] == b"AC10":
        return kind, "application/acad"
    if kind == FileKind.DXF and (
        head.startswith(b"AutoCAD Binary DXF") or b"SECTION" in head.upper()
    ):
        return kind, "application/dxf"
    raise UploadError(
        f"This file's contents don't match its {ext} extension. It may be corrupt or renamed.",
        status_code=415,
    )


# --- Per-kind inspection ------------------------------------------------------------


def _inspect_pdf(data: bytes, max_pages: int) -> Inspection:
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise UploadError("This PDF is password-protected. Remove the password and upload it again.") from None
        raise UploadError("This PDF can't be opened. It may be damaged; try exporting it again.") from None

    try:
        if len(doc) == 0:
            raise UploadError("This PDF has no pages.")
        if len(doc) > max_pages:
            raise UploadError(f"This PDF has {len(doc)} pages; the limit is {max_pages}. Upload only the floor plan pages.")

        pages: list[PageInfo] = []
        scanned = 0
        for i, page in enumerate(doc):
            w_pt, h_pt = page.get_size()
            text = page.get_textpage().get_text_range()
            info = PageInfo(index=i, width=round(w_pt), height=round(h_pt), has_text=bool(text.strip()))
            info.floor_guess = _floor_guess(text)

            info.thumbnail_png = _png(page.render(scale=THUMBNAIL_LONG_SIDE / max(w_pt, h_pt)).to_pil())
            if not info.has_text:
                scanned += 1
                scale = min(SCAN_ANALYSIS_DPI / 72, SCAN_ANALYSIS_MAX_PX / max(w_pt, h_pt))
                # Render size is our choice, so resolution says nothing about the scan itself.
                report = assess_image(page.render(scale=scale).to_pil(), check_resolution=False)
                info.warnings.extend(report.warnings)
            pages.append(info)
    finally:
        doc.close()

    warnings = []
    if scanned:
        which = "All pages" if scanned == len(pages) else f"{scanned} of {len(pages)} pages"
        warnings.append(
            Warning(
                "no_text_layer",
                f"{which} have no selectable text (scanned or image-only). "
                "Room details will be read with OCR, which is less accurate.",
            )
        )
    return Inspection(FileKind.PDF, "application/pdf", pages, warnings)


def _inspect_image(data: bytes, content_type: str) -> Inspection:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.load()
    except Image.DecompressionBombError:
        raise UploadError("This image is too large to process. Reduce it below 100 megapixels.") from None
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise UploadError("This image can't be opened. It may be damaged or incomplete.") from None

    report = assess_image(img)
    page = PageInfo(
        index=0, width=img.width, height=img.height, has_text=None, warnings=report.warnings, thumbnail_png=_png(img)
    )
    return Inspection(FileKind.IMAGE, content_type, [page])


Segment = tuple[tuple[float, float], tuple[float, float]]


def dxf_segments(msp) -> list[Segment]:
    segments: list[Segment] = []
    for e in msp.query("LINE LWPOLYLINE"):
        if len(segments) > 50_000:
            break
        if e.dxftype() == "LINE":
            segments.append(((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)))
        else:
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if e.closed and pts:
                pts.append(pts[0])
            segments.extend(zip(pts, pts[1:], strict=False))
    return segments


@dataclass(frozen=True)
class DxfFrame:
    """Maps drawing coordinates onto the preview image, so extracted text positions line up
    with the thumbnail the user sees (PRD 4.2 source location / 4.3 plan overlay)."""

    min_x: float
    min_y: float
    k: float  # pixels per drawing unit
    pad: int
    width: int
    height: int

    @classmethod
    def from_segments(cls, segments: list[Segment], long_side: int = THUMBNAIL_LONG_SIDE) -> "DxfFrame | None":
        """The padding scales with the size, so positions stored as fractions of the thumbnail
        line up on a larger preview too."""
        if not segments:
            return None
        xs = [x for s in segments for x, _ in s]
        ys = [y for s in segments for _, y in s]
        min_x, min_y = min(xs), min(ys)
        span = max(max(xs) - min_x, max(ys) - min_y) or 1.0
        pad = round(long_side / 40)  # 16 px at the 640 px thumbnail size
        k = (long_side - 2 * pad) / span
        return cls(min_x, min_y, k, pad, round((max(xs) - min_x) * k) + 2 * pad, round((max(ys) - min_y) * k) + 2 * pad)

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        # DXF y points up; images point down.
        return self.pad + (x - self.min_x) * self.k, self.height - self.pad - (y - self.min_y) * self.k


def dxf_drawing(msp, long_side: int = THUMBNAIL_LONG_SIDE) -> Image.Image | None:
    """Rough line drawing of model space so users can recognise the file. Best effort."""
    segments = dxf_segments(msp)
    frame = DxfFrame.from_segments(segments, long_side)
    if frame is None:
        return None
    img = Image.new("RGB", (frame.width, frame.height), "white")
    draw = ImageDraw.Draw(img)
    width = max(1, round(long_side / 640))
    for start, end in segments:
        draw.line([frame.to_px(*start), frame.to_px(*end)], fill="black", width=width)
    return img


def _dxf_thumbnail(msp) -> bytes | None:
    img = dxf_drawing(msp)
    return _png(img) if img else None


def _inspect_dxf(data: bytes) -> Inspection:
    from ezdxf import recover
    from ezdxf.lldxf.const import DXFError

    try:
        doc, _auditor = recover.read(io.BytesIO(data))
    except (DXFError, UnicodeDecodeError, ValueError):
        raise UploadError("This DXF file can't be read. Try saving it again from your CAD software.") from None

    msp = doc.modelspace()
    texts = [e.dxf.text for e in msp.query("TEXT")] + [e.plain_text() for e in msp.query("MTEXT")]
    texts += [a.dxf.text for ins in msp.query("INSERT") for a in ins.attribs]
    warnings: list[Warning] = []
    if not texts:
        warnings.append(
            Warning(
                "no_text",
                "No text was found in this drawing, so room names and sizes can't be read. "
                "Check that labels aren't exploded into lines, or enter rooms manually.",
            )
        )

    unit = _DXF_UNITS.get(doc.header.get("$INSUNITS", 0))
    if unit is None:
        warnings.append(Warning("units_unknown", "The drawing doesn't specify its units. You'll be asked to confirm them."))

    try:
        thumb = _dxf_thumbnail(msp)
    except Exception:  # noqa: BLE001 - preview is optional; never fail the upload for it
        thumb = None
    extmin, extmax = doc.header.get("$EXTMIN", (0, 0, 0)), doc.header.get("$EXTMAX", (0, 0, 0))
    page = PageInfo(
        index=0,
        width=max(0, round(extmax[0] - extmin[0])),
        height=max(0, round(extmax[1] - extmin[1])),
        has_text=bool(texts),
        floor_guess=_floor_guess(" ".join(texts)),
        thumbnail_png=thumb,
    )
    return Inspection(FileKind.DXF, "application/dxf", [page], warnings, detected_unit=unit)


def convert_dwg(data: bytes, converter: str) -> bytes:
    """DWG -> DXF with the ODA File Converter (licence terms apply, see PRD 9)."""
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp, "in"), Path(tmp, "out")
        src.mkdir()
        out.mkdir()
        (src / "plan.dwg").write_bytes(data)
        try:
            subprocess.run(
                [converter, str(src), str(out), "ACAD2018", "DXF", "0", "1", "*.DWG"],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            raise UploadError("This DWG file couldn't be converted. Export it as DXF or PDF and upload that.") from None
        converted = next(out.glob("*.dxf"), None)
        if converted is None:
            raise UploadError("This DWG file couldn't be converted. Export it as DXF or PDF and upload that.")
        return converted.read_bytes()


def inspect_upload(
    filename: str, data: bytes, *, max_bytes: int, max_pages: int, dwg_converter: str | None
) -> Inspection:
    if len(data) > max_bytes:
        raise UploadError(
            f"The file is {len(data) / 1_048_576:.1f} MB; the limit is {max_bytes // 1_048_576} MB.", status_code=413
        )
    kind, content_type = detect_kind(filename, data)

    if kind == FileKind.PDF:
        return _inspect_pdf(data, max_pages)
    if kind == FileKind.IMAGE:
        return _inspect_image(data, content_type)
    if kind == FileKind.DXF:
        return _inspect_dxf(data)

    if not dwg_converter:
        raise UploadError(
            "DWG files can't be converted on this server yet. "
            "Export the drawing as DXF or PDF from your CAD software and upload that.",
        )
    dxf = convert_dwg(data, dwg_converter)
    result = _inspect_dxf(dxf)
    result.kind, result.content_type, result.converted_dxf = FileKind.DWG, content_type, dxf
    return result
