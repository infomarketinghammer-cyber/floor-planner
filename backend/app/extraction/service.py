"""Run extraction for one uploaded blueprint (PRD 4.2) and turn results into project rooms.

Routing (PRD 6.1): digital PDF pages and DXF/DWG are read as text with no AI; photos and
scanned pages go to the vision model. A text page that yields no rooms (e.g. a scan with a
typed title block) falls back to vision when it's configured.
"""

import asyncio
import io
import uuid
from dataclasses import dataclass, field

from PIL import Image, ImageOps

from app.core.guest import AI_SIGN_IN, is_guest
from app.engine.units import LengthUnit
from app.extraction import vision
from app.extraction.models import ExtractedRoom
from app.extraction.pairing import pair_rooms
from app.extraction.sources import dxf_tokens, pdf_page_tokens, render_pdf_page
from app.schemas.project import ExtractedValues, Room, RoomOrigin, RoomSource
from app.uploads.inspect import FileKind

_vision_slots = asyncio.Semaphore(3)  # concurrent vision calls across the server


@dataclass
class PageResult:
    index: int
    method: str | None = None  # pdf_text | dxf_text | vision
    rooms: list[ExtractedRoom] = field(default_factory=list)
    error: str | None = None


async def _vision_page(img: Image.Image, plan_unit: LengthUnit | None, result: PageResult) -> None:
    result.method = "vision"
    if is_guest():  # AI reading costs money per page: signed-in users only
        result.error = AI_SIGN_IN
        return
    try:
        async with _vision_slots:
            result.rooms = await vision.read_rooms(img, plan_unit)
    except vision.VisionUnavailable as e:
        result.error = str(e)


async def _extract_pdf_page(data: bytes, page: dict, plan_unit: LengthUnit | None) -> PageResult:
    result = PageResult(page["index"])
    if page["has_text"]:
        tokens = await asyncio.to_thread(pdf_page_tokens, data, page["index"])
        result.method = "pdf_text"
        result.rooms = await asyncio.to_thread(pair_rooms, tokens, plan_unit)
        if result.rooms or not vision.is_configured():
            return result
    img = await asyncio.to_thread(render_pdf_page, data, page["index"])
    await _vision_page(img, plan_unit, result)
    return result


async def extract_pages(
    kind: FileKind, data: bytes, pages: list[dict], plan_unit: LengthUnit | None = None
) -> list[PageResult]:
    """`data` is the original file, or the converted DXF for DWG. Only included pages run.
    `plan_unit` (the user-confirmed plan unit, PRD 4.4) is used for sizes written without units."""
    included = [p for p in pages if p.get("included", True)]
    if kind == FileKind.PDF:
        return list(
            await asyncio.gather(*(_extract_pdf_page(data, p, plan_unit) for p in included))
        )

    if kind in (FileKind.DXF, FileKind.DWG):
        if not included:
            return []
        tokens, drawing_unit = await asyncio.to_thread(dxf_tokens, data)
        rooms = await asyncio.to_thread(pair_rooms, tokens, drawing_unit or plan_unit)
        return [PageResult(0, "dxf_text", rooms)]

    if not included:
        return []
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    result = PageResult(0)
    await _vision_page(img, plan_unit, result)
    return [result]


def _box(b) -> list[float] | None:
    return [round(float(v), 4) for v in b] if b is not None else None


def to_room(
    extracted: ExtractedRoom, *, file_id: str, page: int, method: str, floor: str | None
) -> Room:
    name = (extracted.name or "Unnamed room")[:100]
    unit = extracted.unit or LengthUnit.FT_IN
    return Room(
        id=uuid.uuid4().hex[:12],
        name=name,
        floor=floor,
        length_mm=extracted.length_mm,
        width_mm=extracted.width_mm,
        unit=unit,
        confirmed=False,  # PRD 6.3: nothing extracted reaches calculation unreviewed
        origin=RoomOrigin.AUTO,
        confidence=extracted.confidence,
        confidence_level=extracted.level,
        flags=extracted.flags,
        unit_explicit=extracted.unit_explicit,
        source=RoomSource(
            file_id=file_id,
            page=page,
            method=method,
            bbox=_box(extracted.bbox),
            name_bbox=_box(extracted.name_bbox),
            size_bbox=_box(extracted.size_bbox),
            text=extracted.raw_text[:300],
        ),
        extracted=ExtractedValues(
            name=name, length_mm=extracted.length_mm, width_mm=extracted.width_mm, unit=unit
        ),
    )
