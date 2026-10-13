"""Read room labels from photos and scanned pages with a vision model (PRD 4.2, 6.1).

The model only *reads* text and says where it is. Sizes are parsed, units resolved and
confidence scored by our own deterministic code, exactly as for digital PDFs (PRD 6.3).
"""

import base64
import io
import logging
from typing import Literal

import anthropic
from PIL import Image
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.engine.dimensions import DimensionError
from app.engine.units import LengthUnit
from app.extraction.classify import clean_name, name_score
from app.extraction.models import ExtractedRoom
from app.extraction.pairing import MAX_SIDE_MM, MIN_SIDE_MM
from app.extraction.sizes import find_size, resolve_units, to_mm
from app.extraction.sources import VISION_LONG_SIDE

logger = logging.getLogger(__name__)

VISION_BASE_CONFIDENCE = 0.85  # below digital text (0.95): reading pixels is less certain

PROMPT = """This image is an architectural floor plan. List every room or space that has a name \
label printed on it (for example BEDROOM 1, KITCHEN, TOILET, BALCONY).

For each room:
- name: the room label exactly as printed.
- size_text: the room size printed with that label, copied exactly as written including \
feet/inch marks and units (for example 12'0" x 10'0", 3.6 x 3.0 m, 3600 x 3000, 12x10). \
Use null if no size is printed for that room. Never calculate, convert or guess a size.
- box: pixel bounding box [x0, y0, x1, y1] covering the name label and its size text.
- legibility: "clear" if you can read the label and size with certainty, otherwise "unclear".

Ignore door and window tags (D1, W2, V), wall dimension lines, notes, title blocks, scale \
bars, area tables and furniture labels. If the image is not a floor plan, return no rooms."""


class VisionRoom(BaseModel):
    name: str
    size_text: str | None
    box: list[int] = Field(description="[x0, y0, x1, y1] in image pixels")
    legibility: Literal["clear", "unclear"]


class VisionResult(BaseModel):
    rooms: list[VisionRoom]


class VisionUnavailable(Exception):
    """No vision provider configured, or the provider failed. Message is user-facing."""


def is_configured() -> bool:
    return bool(get_settings().anthropic_api_key)


def _prepare(img: Image.Image) -> tuple[str, int, int]:
    img = img.convert("RGB")
    if max(img.size) > VISION_LONG_SIDE:
        img.thumbnail((VISION_LONG_SIDE, VISION_LONG_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), img.width, img.height


async def _ask_model(image_b64: str) -> VisionResult:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0)
    try:
        response = await client.beta.messages.parse(
            model=settings.vision_model,
            max_tokens=16000,
            output_config={"effort": settings.vision_effort},
            # On a safety decline, the API retries on a suitable fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=VisionResult,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError:
        raise VisionUnavailable(
            "The AI reading service rejected its API key. Ask an admin to check it."
        ) from None
    except anthropic.RateLimitError:
        raise VisionUnavailable("The AI reading service is busy. Try again in a minute.") from None
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        logger.warning("Vision extraction failed: %s", e)
        raise VisionUnavailable(
            "The AI reading service is unavailable right now. Try again later."
        ) from None
    finally:
        await client.close()

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise VisionUnavailable(
            "The plan couldn't be read automatically. Enter the rooms manually."
        )
    return response.parsed_output


async def read_rooms(img: Image.Image, plan_unit: LengthUnit | None = None) -> list[ExtractedRoom]:
    if not is_configured():
        raise VisionUnavailable(
            "Reading photos and scans needs the AI reading service, which isn't set up yet. "
            "Add the rooms manually or import a room list."
        )
    image_b64, width, height = _prepare(img)
    result = await _ask_model(image_b64)
    return rooms_from_vision(result, width, height, plan_unit)


def rooms_from_vision(
    result: VisionResult, width: int, height: int, plan_unit: LengthUnit | None
) -> list[ExtractedRoom]:
    """Deterministic post-processing of what the model read."""
    sizes = [find_size(r.size_text) if r.size_text else None for r in result.rooms]
    resolve_units([s for s in sizes if s is not None], plan_unit)

    rooms: list[ExtractedRoom] = []
    for vr, size in zip(result.rooms, sizes, strict=True):
        flags = ["ai_read"]
        confidence = VISION_BASE_CONFIDENCE
        if vr.legibility == "unclear":
            confidence -= 0.25
            flags.append("unclear_text")
        if name_score(vr.name) < 1:
            confidence -= 0.2
            flags.append("unusual_name")

        length_mm = width_mm = None
        if size is None:
            confidence = min(confidence, 0.4)
            flags.append("size_unreadable" if vr.size_text else "size_missing")
        else:
            if not size.unit_explicit:
                confidence -= 0.05 if plan_unit else 0.15
                flags.append("unit_assumed")
            try:
                length_mm, width_mm = to_mm(size)
                if not all(MIN_SIDE_MM <= v <= MAX_SIDE_MM for v in (length_mm, width_mm)):
                    confidence -= 0.3
                    flags.append("implausible_size")
            except DimensionError:
                confidence = min(confidence, 0.3)
                flags.append("size_unreadable")

        x0, y0, x1, y1 = (vr.box + [0, 0, 0, 0])[:4]
        bbox = (
            max(0.0, min(x0, x1) / width),
            max(0.0, min(y0, y1) / height),
            min(1.0, max(x0, x1) / width),
            min(1.0, max(y0, y1) / height),
        )
        rooms.append(
            ExtractedRoom(
                name=clean_name(vr.name),
                size_text=size.text if size else vr.size_text,
                length_mm=length_mm,
                width_mm=width_mm,
                unit=size.unit if size else None,
                unit_explicit=bool(size and size.unit_explicit),
                confidence=round(max(confidence, 0.05), 2),
                flags=flags,
                bbox=bbox,
                raw_text=f"{vr.name} — {vr.size_text}" if vr.size_text else vr.name,
            )
        )
    return rooms
