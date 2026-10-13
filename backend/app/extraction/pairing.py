"""Match room names to room sizes by position (PRD 4.2), for text read directly from PDF/DXF."""

from dataclasses import dataclass

from app.engine.dimensions import DimensionError
from app.engine.units import LengthUnit
from app.extraction.classify import clean_name, is_noise, name_score
from app.extraction.models import BBox, ExtractedRoom, TextToken, union
from app.extraction.sizes import SizeMatch, find_size, resolve_units, to_mm

MAX_PAIR_COST = 6.0  # in text heights; further apart than this is not a label pair
AMBIGUITY_RATIO = 1.6  # runner-up name within 1.6× the best cost makes the pair ambiguous
MIN_SIDE_MM, MAX_SIDE_MM = 600, 30_000  # outside this a "room" side is implausible


@dataclass
class _Size:
    match: SizeMatch
    bbox: BBox
    inline_name: str | None  # "BEDROOM 12'x10'" written on one line


@dataclass
class _Name:
    text: str
    bbox: BBox
    score: float


def _split_tokens(tokens: list[TextToken]) -> tuple[list[_Size], list[_Name]]:
    sizes: list[_Size] = []
    names: list[_Name] = []
    for tok in tokens:
        match = find_size(tok.text)
        if match is not None:
            prefix = tok.text[: match.start].strip(" -:,")
            inline = prefix if prefix and name_score(prefix) > 0 else None
            sizes.append(_Size(match, tok.bbox, inline))
            continue
        score = name_score(tok.text)
        if score > 0:
            names.append(_Name(tok.text, tok.bbox, score))
    return sizes, names


def _cost(name: _Name, size: _Size) -> float:
    """Distance in text heights; a name directly above its size (the usual layout) is cheapest."""
    h = max(name.bbox[3] - name.bbox[1], size.bbox[3] - size.bbox[1], 1e-6)
    ncx, ncy = (name.bbox[0] + name.bbox[2]) / 2, (name.bbox[1] + name.bbox[3]) / 2
    scx, scy = (size.bbox[0] + size.bbox[2]) / 2, (size.bbox[1] + size.bbox[3]) / 2
    dx, dy = abs(ncx - scx) / h, (scy - ncy) / h
    overlaps = name.bbox[0] < size.bbox[2] and size.bbox[0] < name.bbox[2]
    if overlaps and 0 < dy:  # name above size, horizontally aligned
        return dy
    return (dx**2 + dy**2) ** 0.5 * 1.5


def pair_rooms(tokens: list[TextToken], plan_unit: LengthUnit | None = None) -> list[ExtractedRoom]:
    sizes, names = _split_tokens(tokens)
    resolve_units([s.match for s in sizes], plan_unit)

    # Greedy one-to-one assignment by ascending cost.
    candidates = sorted(
        (
            (_cost(n, s), si, ni)
            for si, s in enumerate(sizes)
            if s.inline_name is None
            for ni, n in enumerate(names)
        ),
        key=lambda c: c[0],
    )
    costs_by_size: dict[int, list[float]] = {}
    for cost, si, _ni in candidates:
        costs_by_size.setdefault(si, []).append(cost)
    assigned_size: dict[int, int] = {}
    used_names: set[int] = set()
    for cost, si, ni in candidates:
        if cost > MAX_PAIR_COST or si in assigned_size or ni in used_names:
            continue
        assigned_size[si] = ni
        used_names.add(ni)

    rooms: list[ExtractedRoom] = []
    for si, size in enumerate(sizes):
        flags: list[str] = []
        confidence = 0.95
        name_text: str | None
        name_bbox: BBox | None = None
        if size.inline_name:
            name_text, score = size.inline_name, name_score(size.inline_name)
        elif si in assigned_size:
            name = names[assigned_size[si]]
            name_text, name_bbox, score = name.text, name.bbox, name.score
            costs = costs_by_size[si]
            if costs[0] > MAX_PAIR_COST / 2:
                confidence -= 0.15
                flags.append("far_from_label")
            if len(costs) > 1 and costs[1] <= costs[0] * AMBIGUITY_RATIO:
                confidence -= 0.15
                flags.append("ambiguous_pairing")
        else:
            name_text, score = None, 0.0
            confidence = 0.4
            flags.append("name_missing")
        if name_text is not None and score < 1:
            confidence -= 0.2
            flags.append("unusual_name")

        if not size.match.unit_explicit:
            confidence -= 0.05 if plan_unit else 0.15
            flags.append("unit_assumed")
        try:
            length_mm, width_mm = to_mm(size.match)
            if not all(MIN_SIDE_MM <= v <= MAX_SIDE_MM for v in (length_mm, width_mm)):
                confidence -= 0.3
                flags.append("implausible_size")
        except DimensionError:
            length_mm = width_mm = None
            confidence = min(confidence, 0.3)
            flags.append("size_unreadable")

        raw = f"{name_text} — {size.match.text}" if name_text else size.match.text
        rooms.append(
            ExtractedRoom(
                name=clean_name(name_text) if name_text else None,
                size_text=size.match.text,
                length_mm=length_mm,
                width_mm=width_mm,
                unit=size.match.unit,
                unit_explicit=size.match.unit_explicit,
                confidence=round(max(confidence, 0.05), 2),
                flags=flags,
                bbox=union(name_bbox, size.bbox),
                name_bbox=name_bbox,
                size_bbox=size.bbox,
                raw_text=raw,
            )
        )

    # Room names with no size nearby: keep only confident ones (others are usually stray labels).
    for ni, name in enumerate(names):
        if ni in used_names or name.score < 1 or is_noise(name.text):
            continue
        rooms.append(
            ExtractedRoom(
                name=clean_name(name.text),
                size_text=None,
                length_mm=None,
                width_mm=None,
                unit=None,
                unit_explicit=False,
                confidence=0.4,
                flags=["size_missing"],
                bbox=name.bbox,
                name_bbox=name.bbox,
                raw_text=name.text,
            )
        )
    return rooms
