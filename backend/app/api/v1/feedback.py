"""Feedback and accuracy (PRD 4.13): "was this quantity right?", the project's extraction
summary, and adding a verified plan to the evaluation set (PRD 6.5)."""

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.db.mongo import get_db
from app.evaluation import NotEligible, add_to_eval_set, eligibility, remove_from_eval_set
from app.schemas.project import Room
from app.services.accuracy import AccuracySummaryOut, corrected_fields, summarize
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import project_default
from app.services.projects import get_project_or_404
from app.services.review import review_state

router = APIRouter(prefix="/projects/{project_id}", tags=["feedback"])


class FeedbackIn(BaseModel):
    room_id: str | None = None  # None: the project as a whole
    right: bool
    actual_boxes: int | None = Field(default=None, ge=0, le=1_000_000)  # what was really needed
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    id: str
    room_id: str | None
    room_name: str | None
    right: bool
    estimated_boxes: int
    actual_boxes: int | None
    comment: str | None
    created_at: datetime


class EvalStatusOut(BaseModel):
    in_eval_set: bool
    added_at: datetime | None
    eligible: bool
    reason: str | None  # why it can't be added yet


class AccuracyOut(BaseModel):
    summary: AccuracySummaryOut | None  # None: no rooms were read from a plan
    evaluation: EvalStatusOut


def feedback_out(doc: dict) -> FeedbackOut:
    snap = doc["snapshot"]
    return FeedbackOut(
        id=str(doc["_id"]),
        room_id=doc.get("room_id"),
        room_name=snap.get("room_name"),
        right=doc["right"],
        estimated_boxes=snap["boxes"],
        actual_boxes=doc.get("actual_boxes"),
        comment=doc.get("comment"),
        created_at=doc["created_at"],
    )


def snapshot(project: dict, room_id: str | None) -> dict:
    """What the user was looking at, so feedback can be analysed later even if rooms change:
    the estimate, and whether the room(s) came from the plan reader and were corrected."""
    state = review_state(project)
    estimate = build_estimate(state, project_default(project), extras_settings(project))
    if not estimate.ready or estimate.totals is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There are no quantities to give feedback on yet."
        )
    rooms: dict[str, Room] = {r.id: r for r in state.rooms}
    if room_id is None:
        return {
            "room_name": None,
            "boxes": estimate.totals.boxes,
            "rooms": estimate.totals.rooms,
            "origins": sorted({rooms[r.room_id].origin.value for r in estimate.rooms}),
            "tiles": [
                {"id": t.tile.id, "size": t.tile.size_label, "boxes": t.boxes}
                for t in estimate.tiles
            ],
        }
    est = next((r for r in estimate.rooms if r.room_id == room_id), None)
    if est is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That room isn't in the results.")
    room = rooms[room_id]
    return {
        "room_name": est.name,
        "boxes": est.boxes,
        "tiles_bought": est.tiles_bought,
        "tile": {"id": est.tile.id, "size": est.tile.size_label},
        "layout": est.layout.value,
        "method": est.method,
        "origin": room.origin.value,
        "extraction_method": room.source.method if room.source else None,
        "corrected_fields": corrected_fields(room),
    }


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def add_feedback(project_id: str, body: FeedbackIn, user: CurrentUser) -> FeedbackOut:
    project = await get_project_or_404(user, project_id, "comment")
    doc = {
        "project_id": project["_id"],
        "owner_id": project["owner_id"],
        "user_id": user["_id"],
        "room_id": body.room_id,
        "right": body.right,
        "actual_boxes": body.actual_boxes,
        "comment": (body.comment or "").strip() or None,
        "snapshot": snapshot(project, body.room_id),
        "created_at": datetime.now(UTC),
    }
    result = await get_db().feedback.insert_one(doc)
    doc["_id"] = result.inserted_id
    return feedback_out(doc)


@router.get("/feedback", response_model=list[FeedbackOut])
async def list_feedback(project_id: str, user: CurrentUser) -> list[FeedbackOut]:
    project = await get_project_or_404(user, project_id)
    cursor = get_db().feedback.find({"project_id": project["_id"]}).sort("created_at", -1)
    return [feedback_out(d) async for d in cursor.limit(100)]


@router.delete("/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(project_id: str, feedback_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id, "comment")
    try:
        oid = ObjectId(feedback_id)
    except Exception:  # noqa: BLE001 - any malformed id is simply "not found"
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found") from None
    result = await get_db().feedback.delete_one({"_id": oid, "project_id": project["_id"]})
    if not result.deleted_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _accuracy(project: dict) -> AccuracyOut:
    db = get_db()
    outcomes = [o async for o in db.extraction_outcomes.find({"project_id": project["_id"]})]
    entry = await db.eval_plans.find_one({"project_id": project["_id"]}, {"created_at": 1})
    blueprints = [b async for b in db.blueprints.find({"project_id": project["_id"]}, {"_id": 1})]
    reason = eligibility(project, blueprints)
    return AccuracyOut(
        summary=summarize(outcomes) if any(o["kind"] == "extracted" for o in outcomes) else None,
        evaluation=EvalStatusOut(
            in_eval_set=entry is not None,
            added_at=entry["created_at"] if entry else None,
            eligible=reason is None,
            reason=reason,
        ),
    )


@router.get("/accuracy", response_model=AccuracyOut)
async def project_accuracy(project_id: str, user: CurrentUser) -> AccuracyOut:
    """How the plan reader did on this project: what was right, corrected, removed or missed."""
    return await _accuracy(await get_project_or_404(user, project_id))


class EvalConsentIn(BaseModel):
    consent: bool  # the user agreed to share a copy of the plan for accuracy testing


@router.post("/evaluation", response_model=AccuracyOut)
async def add_to_evaluation(project_id: str, body: EvalConsentIn, user: CurrentUser) -> AccuracyOut:
    project = await get_project_or_404(user, project_id, "manage")
    if not body.consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Agree to share a copy of the plan first."
        )
    try:
        await add_to_eval_set(project, user)
    except NotEligible as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return await _accuracy(project)


@router.delete("/evaluation", response_model=AccuracyOut)
async def remove_from_evaluation(project_id: str, user: CurrentUser) -> AccuracyOut:
    project = await get_project_or_404(user, project_id, "manage")
    await remove_from_eval_set({"project_id": project["_id"]})
    return await _accuracy(project)
