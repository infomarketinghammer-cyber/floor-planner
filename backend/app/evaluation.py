"""Evaluation set of verified plans (PRD 6.5): plan files plus the rooms a user confirmed on them.

Users opt in per project. A copy of the plan goes to a separate GridFS bucket ("eval"), so
deleting the project doesn't remove it; the user or an admin removes it explicitly.

Run the current extractor against the whole set and score it:

    python -m app.evaluation            # score, per plan and overall
    python -m app.evaluation --export eval/plans   # also write the files and truth.json there
"""

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.db import storage
from app.db.mongo import get_db
from app.engine.units import LengthUnit
from app.services.accuracy import same_size, summarize
from app.services.review import review_state


class NotEligible(Exception):
    """Why a project can't be added; safe to show the user."""


# --- Adding a project ---------------------------------------------------------------------------


def eligibility(project: dict, blueprints: list[dict]) -> str | None:
    """None when the project can be added, else the reason it can't."""
    state = review_state(project)
    extracted = [r for r in state.rooms if r.extracted is not None]
    if not extracted:
        return "Only plans that rooms were read from can be added."
    if not state.summary.ready:
        return "Confirm every room (and the plan unit) first, so the room list is verified."
    files = {r.source.file_id for r in extracted if r.source}
    if not files & {str(b["_id"]) for b in blueprints}:
        return "The plan file these rooms came from has been deleted."
    return None


def truth_rooms(project: dict) -> list[dict]:
    """The verified room list: every confirmed or skipped room (a balcony that isn't tiled is
    still a room on the plan). Extracted rooms the user deleted are gone, so they aren't here."""
    out = []
    for r in review_state(project).rooms:
        if not (r.confirmed or r.skipped):
            continue
        out.append(
            {
                "name": r.name,
                "floor": r.floor,
                "length_mm": None if r.length_mm is None else str(r.length_mm),
                "width_mm": None if r.width_mm is None else str(r.width_mm),
                "area_mm2": None if r.area_mm2 is None else str(r.area_mm2),
                "file_id": r.source.file_id if r.source else None,
                "page": r.source.page if r.source else None,
                "origin": r.origin.value,
            }
        )
    return out


async def add_to_eval_set(project: dict, user: dict) -> dict:
    db = get_db()
    blueprints = [b async for b in db.blueprints.find({"project_id": project["_id"]})]
    if reason := eligibility(project, blueprints):
        raise NotEligible(reason)

    truth = truth_rooms(project)
    used = {t["file_id"] for t in truth if t["file_id"]}
    files = []
    for b in blueprints:
        if str(b["_id"]) not in used:
            continue
        # Keep what the extractor actually reads: the converted DXF for a DWG.
        converted = b.get("converted_file_id")
        data = await storage.get(converted or b["file_id"])
        kind = "dxf" if converted else b["kind"]
        filename = b["filename"] if not converted else f"{Path(b['filename']).stem}.dxf"
        eval_id = await storage.put(
            data, filename, b["content_type"] if not converted else "image/vnd.dxf", bucket="eval"
        )
        files.append(
            {
                "source_file_id": str(b["_id"]),
                "eval_file_id": eval_id,
                "filename": filename,
                "kind": kind,
                "pages": [
                    {
                        "index": p["index"],
                        "included": p.get("included", True),
                        "floor": p.get("floor"),
                    }
                    for p in b["pages"]
                ],
                "detected_unit": b.get("detected_unit"),
            }
        )

    outcomes = [o async for o in db.extraction_outcomes.find({"project_id": project["_id"]})]
    entry = {
        "project_id": project["_id"],
        "owner_id": project["owner_id"],
        "contributed_by": user["_id"],
        "project_name": project.get("name"),
        "plan_unit": project.get("plan_unit"),
        "files": files,
        "truth": truth,
        "summary_at_add": summarize(outcomes, list_corrections=False).model_dump(mode="json"),
        "created_at": datetime.now(UTC),
    }
    await remove_from_eval_set({"project_id": project["_id"]})  # one entry per project
    result = await db.eval_plans.insert_one(entry)
    entry["_id"] = result.inserted_id
    return entry


async def remove_from_eval_set(query: dict) -> int:
    db = get_db()
    removed = 0
    async for entry in db.eval_plans.find(query):
        await storage.delete(*(f["eval_file_id"] for f in entry["files"]), bucket="eval")
        await db.eval_plans.delete_one({"_id": entry["_id"]})
        removed += 1
    return removed


# --- Scoring ------------------------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _sides(room: dict) -> tuple[Decimal | None, Decimal | None]:
    def d(v):
        return None if v is None else Decimal(str(v))

    return d(room.get("length_mm")), d(room.get("width_mm"))


@dataclass
class Score:
    truth: int = 0  # real rooms
    found: int = 0  # rooms the extractor reported
    matched: int = 0
    name_correct: int = 0  # among matched
    size_correct: int = 0
    missed: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    def add(self, other: "Score") -> None:
        for f in ("truth", "found", "matched", "name_correct", "size_correct"):
            setattr(self, f, getattr(self, f) + getattr(other, f))
        self.missed += other.missed
        self.extra += other.extra

    @staticmethod
    def _pct(a: int, b: int) -> str:
        return f"{a / b * 100:.1f}%" if b else "–"

    def line(self) -> str:
        return (
            f"found {self._pct(self.matched, self.truth)} of rooms ({self.matched}/{self.truth}), "
            f"precision {self._pct(self.matched, self.found)}, "
            f"names {self._pct(self.name_correct, self.matched)}, "
            f"sizes {self._pct(self.size_correct, self.matched)}"
        )


def match_rooms(truth: list[dict], found: list[dict]) -> Score:
    """Pair found rooms with real ones: same name and size first, then same name, then same
    size. Each room is used once. Rooms are compared within one page."""
    score = Score(truth=len(truth), found=len(found))
    left = list(found)
    pairs = []
    for test in (
        lambda t, f: _norm(t["name"]) == _norm(f["name"]) and same_size(_sides(f), _sides(t)),
        lambda t, f: _norm(t["name"]) == _norm(f["name"]),
        lambda t, f: _sides(t) != (None, None) and same_size(_sides(f), _sides(t)),
    ):
        for t in [t for t in truth if not any(t is p[0] for p in pairs)]:
            f = next((f for f in left if test(t, f)), None)
            if f is not None:
                pairs.append((t, f))
                left.remove(f)
    score.matched = len(pairs)
    score.name_correct = sum(1 for t, f in pairs if _norm(t["name"]) == _norm(f["name"]))
    score.size_correct = sum(1 for t, f in pairs if same_size(_sides(f), _sides(t)))
    matched_truth = [p[0] for p in pairs]
    score.missed = [t["name"] for t in truth if not any(t is m for m in matched_truth)]
    score.extra = [f["name"] for f in left]
    return score


async def score_entry(entry: dict) -> tuple[Score, list[str]]:
    """Run today's extractor on one plan. Returns the score and any page errors."""
    from app.extraction.service import extract_pages  # heavy imports only when scoring
    from app.uploads.inspect import FileKind

    plan_unit = LengthUnit(entry["plan_unit"]) if entry.get("plan_unit") else None
    total, errors = Score(), []
    for f in entry["files"]:
        data = await storage.get(f["eval_file_id"], bucket="eval")
        results = await extract_pages(FileKind(f["kind"]), data, f["pages"], plan_unit)
        for page in results:
            if page.error:
                errors.append(f"{f['filename']} p{page.index + 1}: {page.error}")
            truth = [
                t
                for t in entry["truth"]
                if t["file_id"] == f["source_file_id"] and t["page"] == page.index
            ]
            found = [
                {
                    "name": r.name or "",
                    "length_mm": r.length_mm,
                    "width_mm": r.width_mm,
                }
                for r in page.rooms
            ]
            total.add(match_rooms(truth, found))
        # Rooms added by hand have no page; they count as missed for the plan as a whole.
        manual = [t for t in entry["truth"] if t["file_id"] is None]
        total.truth += len(manual)
        total.missed += [t["name"] for t in manual]
    return total, errors


async def export_entry(entry: dict, root: Path) -> None:
    folder = root / str(entry["_id"])
    folder.mkdir(parents=True, exist_ok=True)
    for f in entry["files"]:
        (folder / f["filename"]).write_bytes(await storage.get(f["eval_file_id"], bucket="eval"))
    meta = {
        k: v
        for k, v in entry.items()
        if k not in ("_id", "project_id", "owner_id", "contributed_by")
    }
    meta["files"] = [{k: v for k, v in f.items() if k != "eval_file_id"} for f in entry["files"]]
    (folder / "truth.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


async def _main(export: Path | None) -> None:
    from app.db import mongo

    await mongo.connect()
    try:
        overall = Score()
        entries = [e async for e in get_db().eval_plans.find().sort("created_at", 1)]
        if not entries:
            print("The evaluation set is empty. Users add verified plans from a project page.")
            return
        for entry in entries:
            score, errors = await score_entry(entry)
            overall.add(score)
            print(f"{entry.get('project_name') or entry['_id']}: {score.line()}")
            for e in errors:
                print(f"  error: {e}")
            if score.missed:
                print(f"  missed: {', '.join(score.missed[:10])}")
            if export:
                await export_entry(entry, export)
        print(f"\nOverall ({len(entries)} plans): {overall.line()}")
    finally:
        await mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--export", type=Path, help="write plan files and truth.json here")
    args = parser.parse_args()
    asyncio.run(_main(args.export))
