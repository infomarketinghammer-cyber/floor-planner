"""Room review rules (PRD 4.3, 6.3): what needs a closer look, and what blocks calculation.

Computed on the server from the full room list, so the UI and the calculation gate (PRD 4.7)
always agree. Pure functions.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.schemas.project import Room, RoomOrigin
from app.services.plan_units import PlanUnit, plan_unit_state

MIN_SIDE_MM, MAX_SIDE_MM = 600, 30_000

Severity = Literal["block", "warn"]

# Extraction flags that still matter while an auto-extracted room is unconfirmed.
_EXTRACTION_FLAGS: dict[str, str] = {
    "ambiguous_pairing": "More than one label was close to this size. Check the name matches.",
    "far_from_label": "The size was far from its label. Check the name matches.",
    "unusual_name": "This doesn't look like a usual room name.",
    "unclear_text": "The text was hard to read. Check it against the plan.",
}


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def room_issues(rooms: list[Room]) -> dict[str, list[Issue]]:
    by_id: dict[str, list[Issue]] = {r.id: [] for r in rooms}
    active = [r for r in rooms if not r.skipped]

    for room in active:
        issues = by_id[room.id]
        if room.floor_area_mm2 is None:
            issues.append(Issue("size_missing", "block", "Enter the length and width."))
        elif (
            room.length_mm is not None
            and room.width_mm is not None
            and not all(MIN_SIDE_MM <= v <= MAX_SIDE_MM for v in (room.length_mm, room.width_mm))
        ):
            issues.append(
                Issue(
                    "implausible_size",
                    "warn",
                    "This size looks unusual (under 0.6 m or over 30 m a side).",
                )
            )
        if room.origin == RoomOrigin.AUTO and "name_missing" in room.flags:
            issues.append(
                Issue("name_missing", "block", "No name was found. Give this room a name.")
            )

        if room.origin == RoomOrigin.AUTO and not room.confirmed:
            if room.confidence_level == "low" and room.length_mm is not None:
                issues.append(
                    Issue("low_confidence", "warn", "Low confidence. Check it against the plan.")
                )
            # "unit_assumed" isn't repeated per room: the plan unit is confirmed once for the
            # whole project (PRD 4.4) and gates readiness in summarize_review.
            for flag in room.flags:
                if flag in _EXTRACTION_FLAGS:
                    issues.append(Issue(flag, "warn", _EXTRACTION_FLAGS[flag]))

    # Duplicates: same name on the same floor, or same name and same size anywhere
    # (e.g. the same plan uploaded twice, as PDF and DXF).
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if _norm(a.name) != _norm(b.name) or not _norm(a.name):
                continue
            same_size = a.length_mm is not None and {a.length_mm, a.width_mm} == {
                b.length_mm,
                b.width_mm,
            }
            if same_size or (a.floor or "").lower() == (b.floor or "").lower():
                reason = "the same name and size" if same_size else "the same name on this floor"
                for room in (a, b):
                    if not any(x.code == "duplicate" for x in by_id[room.id]):
                        by_id[room.id].append(
                            Issue(
                                "duplicate",
                                "warn",
                                f"Another room has {reason}. Delete one or rename it.",
                            )
                        )
    return by_id


@dataclass(frozen=True)
class ReviewSummary:
    total: int
    confirmed: int
    to_review: int  # not confirmed and not skipped
    with_issues: int
    blocking: int
    unit_pending: bool  # the plan unit still needs confirming (PRD 4.4)
    ready: bool  # every room confirmed (or skipped), plan unit confirmed, at least one room


def summarize_review(
    rooms: list[Room], issues: dict[str, list[Issue]], unit_pending: bool = False
) -> ReviewSummary:
    active = [r for r in rooms if not r.skipped]
    confirmed = sum(r.confirmed for r in active)
    return ReviewSummary(
        total=len(rooms),
        confirmed=confirmed,
        to_review=len(active) - confirmed,
        with_issues=sum(1 for r in active if issues[r.id]),
        blocking=sum(1 for r in active if any(i.severity == "block" for i in issues[r.id])),
        unit_pending=unit_pending,
        ready=bool(active) and confirmed == len(active) and not unit_pending,
    )


def blocking_issues(room: Room, issues: dict[str, list[Issue]]) -> list[Issue]:
    return [i for i in issues.get(room.id, []) if i.severity == "block"]


@dataclass(frozen=True)
class ReviewState:
    rooms: list[Room]
    plan_unit: PlanUnit
    issues: dict[str, list[Issue]]
    summary: ReviewSummary


def review_state(doc: dict, rooms: list[Room] | None = None) -> ReviewState:
    """Everything the review screen and the calculation gate need, from a project document."""
    rooms = rooms if rooms is not None else [Room.model_validate(r) for r in doc.get("rooms", [])]
    plan_unit = plan_unit_state(doc, rooms)
    issues = room_issues(rooms)
    return ReviewState(
        rooms, plan_unit, issues, summarize_review(rooms, issues, plan_unit.needs_confirmation)
    )
