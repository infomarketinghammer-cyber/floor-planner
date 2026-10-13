"""Extraction accuracy (PRD 4.13, 6.5): how what the plan reader found compares with what the
user confirmed.

Every extracted room keeps what was read (`Room.extracted`). After each room change the
project's outcomes are written to `extraction_outcomes`, one per room, so rooms the user deleted
(not real rooms) and rooms they added by hand (missed by the reader) are counted too.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from bson import ObjectId
from pydantic import BaseModel
from pymongo import UpdateOne

from app.db.mongo import get_db
from app.schemas.material import DecimalStr
from app.schemas.project import Room, RoomOrigin

OutcomeStatus = Literal["pending", "correct", "corrected", "deleted", "added"]

SIZE_TOLERANCE_MM = Decimal(10)  # differences this small are rounding, not a misread
SIZE_TOLERANCE_PCT = Decimal(1)
MAX_CORRECTIONS_LISTED = 50


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(SIZE_TOLERANCE_MM, b * SIZE_TOLERANCE_PCT / 100)


def same_size(
    read: tuple[Decimal | None, Decimal | None], final: tuple[Decimal | None, Decimal | None]
) -> bool:
    """Sides match within tolerance, in either order (11 × 9.5 is the same room as 9.5 × 11)."""
    (a1, b1), (a2, b2) = read, final
    if None in (a1, b1, a2, b2):
        return (a1, b1) == (a2, b2)
    return (_close(a1, a2) and _close(b1, b2)) or (_close(a1, b2) and _close(b1, a2))


def corrected_fields(room: Room) -> list[str]:
    read = room.extracted
    if read is None:
        return []
    fields = []
    if _norm(read.name) != _norm(room.name):
        fields.append("name")
    if not same_size((read.length_mm, read.width_mm), (room.length_mm, room.width_mm)):
        fields.append("size")
    return fields


def _values(name: str, length: Decimal | None, width: Decimal | None, unit) -> dict:
    return {
        "name": name,
        "length_mm": None if length is None else str(length),
        "width_mm": None if width is None else str(width),
        "unit": str(unit),
    }


def build_outcomes(rooms: list[Room]) -> list[dict]:
    """One outcome per extracted room, plus rooms added by hand once a plan has been read.
    Pure: `sync_outcomes` adds the ids and timestamps and finds deleted rooms."""
    extracted = [r for r in rooms if r.extracted is not None]
    if not extracted:
        return []
    out = []
    for r in extracted:
        fields = corrected_fields(r)
        reviewed = r.confirmed or r.skipped
        status: OutcomeStatus = ("corrected" if fields else "correct") if reviewed else "pending"
        out.append(
            {
                "room_id": r.id,
                "kind": "extracted",
                "method": r.source.method if r.source else None,
                "file_id": r.source.file_id if r.source else None,
                "page": r.source.page if r.source else None,
                "confidence_level": r.confidence_level,
                "flags": r.flags,
                "extracted": _values(
                    r.extracted.name, r.extracted.length_mm, r.extracted.width_mm, r.extracted.unit
                ),
                "final": _values(r.name, r.length_mm, r.width_mm, r.unit),
                "status": status,
                "corrected_fields": fields,
            }
        )
    for r in rooms:
        if r.origin == RoomOrigin.MANUAL and r.confirmed:
            out.append(
                {
                    "room_id": r.id,
                    "kind": "added",
                    "method": None,
                    "extracted": None,
                    "final": _values(r.name, r.length_mm, r.width_mm, r.unit),
                    "status": "added",
                    "corrected_fields": [],
                }
            )
    return out


async def sync_outcomes(project: dict) -> None:
    """Write the project's current outcomes; rooms that are gone are marked deleted."""
    rooms = [Room.model_validate(r) for r in project.get("rooms", [])]
    outcomes = build_outcomes(rooms)
    coll = get_db().extraction_outcomes
    now = datetime.now(UTC)
    pid = project["_id"]
    if outcomes:
        await coll.bulk_write(
            [
                UpdateOne(
                    {"project_id": pid, "room_id": o["room_id"]},
                    {
                        "$set": {**o, "owner_id": project.get("owner_id"), "updated_at": now},
                        "$setOnInsert": {"created_at": now},
                    },
                    upsert=True,
                )
                for o in outcomes
            ]
        )
    present = [o["room_id"] for o in outcomes]
    # An extracted room that was deleted wasn't a real room. A hand-added one that was deleted
    # tells us nothing, so it is just dropped.
    await coll.update_many(
        {"project_id": pid, "kind": "extracted", "room_id": {"$nin": present}},
        {"$set": {"status": "deleted", "updated_at": now}},
    )
    await coll.delete_many({"project_id": pid, "kind": "added", "room_id": {"$nin": present}})


async def forget_rooms(project_id: ObjectId, room_ids: list[str]) -> None:
    """Re-extraction replaced untouched rooms: they were never reviewed, so they don't count."""
    if room_ids:
        await get_db().extraction_outcomes.delete_many(
            {"project_id": project_id, "room_id": {"$in": room_ids}}
        )


# --- Summary ------------------------------------------------------------------------------------


class CorrectionOut(BaseModel):
    room_id: str
    status: OutcomeStatus
    fields: list[str]
    extracted: dict | None
    final: dict | None


class MethodAccuracyOut(BaseModel):
    method: str  # pdf_text | dxf_text | vision
    read: int
    reviewed: int
    correct: int
    accuracy_pct: DecimalStr | None


class AccuracySummaryOut(BaseModel):
    rooms_read: int  # rooms the plan reader found
    pending: int  # not reviewed yet
    correct: int  # confirmed as read
    corrected: int  # confirmed after a change
    names_corrected: int
    sizes_corrected: int
    deleted: int  # found by the reader but not real rooms
    added: int  # real rooms the reader missed (added by hand)
    accuracy_pct: DecimalStr | None  # correct ÷ reviewed (correct + corrected + deleted)
    name_accuracy_pct: DecimalStr | None  # among confirmed extracted rooms
    size_accuracy_pct: DecimalStr | None
    found_pct: DecimalStr | None  # real rooms found ÷ all real rooms (recall)
    by_method: list[MethodAccuracyOut]
    corrections: list[CorrectionOut]  # what changed, for the project panel


def _pct(part: int, whole: int) -> Decimal | None:
    return (Decimal(part) / whole * 100).quantize(Decimal("0.1")) if whole else None


def summarize(outcomes: list[dict], *, list_corrections: bool = True) -> AccuracySummaryOut:
    extracted = [o for o in outcomes if o["kind"] == "extracted"]

    def count(status: str, rows: list[dict] = extracted) -> int:
        return sum(1 for o in rows if o["status"] == status)

    correct, corrected, deleted = count("correct"), count("corrected"), count("deleted")
    confirmed = correct + corrected
    names_wrong = sum(1 for o in extracted if "name" in o.get("corrected_fields", []))
    sizes_wrong = sum(1 for o in extracted if "size" in o.get("corrected_fields", []))
    added = sum(1 for o in outcomes if o["kind"] == "added")

    by_method = []
    for method in sorted({o.get("method") or "unknown" for o in extracted}):
        rows = [o for o in extracted if (o.get("method") or "unknown") == method]
        ok = count("correct", rows)
        reviewed = ok + count("corrected", rows) + count("deleted", rows)
        by_method.append(
            MethodAccuracyOut(
                method=method,
                read=len(rows),
                reviewed=reviewed,
                correct=ok,
                accuracy_pct=_pct(ok, reviewed),
            )
        )

    corrections = []
    if list_corrections:
        changed = [o for o in outcomes if o["status"] in ("corrected", "deleted", "added")]
        corrections = [
            CorrectionOut(
                room_id=o["room_id"],
                status=o["status"],
                fields=o.get("corrected_fields", []),
                extracted=o.get("extracted"),
                final=o.get("final") if o["status"] != "deleted" else None,
            )
            for o in changed[:MAX_CORRECTIONS_LISTED]
        ]

    return AccuracySummaryOut(
        rooms_read=len(extracted),
        pending=count("pending"),
        correct=correct,
        corrected=corrected,
        names_corrected=names_wrong,
        sizes_corrected=sizes_wrong,
        deleted=deleted,
        added=added,
        accuracy_pct=_pct(correct, confirmed + deleted),
        name_accuracy_pct=_pct(confirmed - names_wrong, confirmed),
        size_accuracy_pct=_pct(confirmed - sizes_wrong, confirmed),
        found_pct=_pct(confirmed, confirmed + added),
        by_method=by_method,
        corrections=corrections,
    )
