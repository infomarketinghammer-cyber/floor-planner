from dataclasses import dataclass, field
from decimal import Decimal

from app.engine.units import LengthUnit

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the page, origin top-left


@dataclass
class TextToken:
    """One line of text on a page with its position."""

    text: str
    bbox: BBox

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class ExtractedRoom:
    name: str | None
    size_text: str | None
    length_mm: Decimal | None
    width_mm: Decimal | None
    unit: LengthUnit | None
    unit_explicit: bool
    confidence: float  # 0..1
    flags: list[str] = field(default_factory=list)
    bbox: BBox | None = None  # union of name and size
    name_bbox: BBox | None = None
    size_bbox: BBox | None = None
    raw_text: str = ""  # exactly what was read, for review

    @property
    def level(self) -> str:
        return confidence_level(self.confidence)


def confidence_level(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def union(*boxes: BBox | None) -> BBox | None:
    real = [b for b in boxes if b is not None]
    if not real:
        return None
    return (
        min(b[0] for b in real),
        min(b[1] for b in real),
        max(b[2] for b in real),
        max(b[3] for b in real),
    )
