"""Image quality checks for photos, scans and scanned PDF pages (PRD 4.1).

Heuristics, not guarantees: they only produce warnings, never block an upload.
Thresholds are starting points and should be tuned against the evaluation set (PRD 6.5).
"""

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

MIN_SHORT_SIDE_PX = 1000  # below this, small dimension text is hard to read
MIN_SHARPNESS = 0.6  # edge strength relative to contrast; sharp line art scores well above 1
MAX_SKEW_DEG = 2.0
MIN_INK_FRACTION = 0.001  # below this the page is effectively blank
MIN_CONTRAST = 60  # grey levels between the darkest and lightest parts

_ANALYSIS_LONG_SIDE = 1600
_SKEW_LONG_SIDE = 800
_SKEW_RANGE_DEG = 15.0
_SKEW_STEP_DEG = 0.25


@dataclass(frozen=True)
class Warning:
    code: str
    message: str


@dataclass
class QualityReport:
    width: int
    height: int
    sharpness: float | None = None
    skew_deg: float | None = None
    warnings: list[Warning] = field(default_factory=list)


def _downscale(img: Image.Image, long_side: int) -> Image.Image:
    scale = long_side / max(img.size)
    if scale >= 1:
        return img
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.BOX)


def _sharpness(gray: np.ndarray, contrast: float) -> float:
    """99.9th percentile of the Laplacian magnitude, normalised by contrast.

    Uses a high percentile rather than variance because floor plans are mostly white
    paper: the few line pixels carry all the signal.
    """
    g = gray.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(np.percentile(np.abs(lap), 99.9) / max(contrast, 1.0))


def _best_rotation(ink: Image.Image, angles: np.ndarray) -> float:
    """Rotation that makes the horizontal ink profile peakiest (walls and text rows line up)."""
    best_angle, best_score = 0.0, -1.0
    for angle in angles:
        rotated = np.asarray(ink.rotate(float(angle), resample=Image.Resampling.NEAREST, fillcolor=0))
        score = float(np.square(rotated.sum(axis=1, dtype=np.float64)).sum())
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def _skew_degrees(ink: Image.Image) -> float:
    """Coarse 1° search on a small image, then a fine search around the best angle."""
    coarse = _best_rotation(
        _downscale(ink, _SKEW_LONG_SIDE // 2),
        np.arange(-_SKEW_RANGE_DEG, _SKEW_RANGE_DEG + 1, 1.0),
    )
    fine = _best_rotation(
        _downscale(ink, _SKEW_LONG_SIDE),
        np.arange(coarse - 1, coarse + 1 + _SKEW_STEP_DEG / 2, _SKEW_STEP_DEG),
    )
    return -fine or 0.0  # rotating by +a fixes a page skewed by -a; avoid "-0.0"


def assess_image(img: Image.Image, *, check_resolution: bool = True) -> QualityReport:
    report = QualityReport(width=img.width, height=img.height)
    if check_resolution and min(img.size) < MIN_SHORT_SIDE_PX:
        report.warnings.append(
            Warning(
                "low_resolution",
                f"Low resolution ({img.width}×{img.height} px). Small text may be misread; "
                f"use a scan or photo at least {MIN_SHORT_SIDE_PX} px on the short side.",
            )
        )

    gray = np.asarray(_downscale(img.convert("L"), _ANALYSIS_LONG_SIDE))
    dark, light = np.percentile(gray, [1, 99])
    contrast = float(light - dark)
    ink_mask = gray < (dark + light) / 2
    ink_fraction = float(ink_mask.mean())

    if contrast < MIN_CONTRAST or ink_fraction < MIN_INK_FRACTION:
        report.warnings.append(
            Warning("blank_or_faint", "This page looks blank or very faint. Check the right page was uploaded.")
        )
        return report  # sharpness and skew are meaningless on an empty page

    report.sharpness = round(_sharpness(gray, contrast), 3)
    if report.sharpness < MIN_SHARPNESS:
        report.warnings.append(
            Warning("blurry", "The image looks blurry. Text may be misread; retake the photo in focus if possible.")
        )

    report.skew_deg = _skew_degrees(Image.fromarray((ink_mask * 255).astype(np.uint8)))
    if abs(report.skew_deg) >= MAX_SKEW_DEG:
        report.warnings.append(
            Warning(
                "skewed",
                f"The plan is tilted by about {abs(report.skew_deg):.1f}°. "
                "Straighten it or rescan for better results.",
            )
        )
    return report
