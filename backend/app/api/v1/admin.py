import io
import json
import zipfile
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from pymongo import DESCENDING, ReturnDocument

from app.api.deps import AdminUser, parse_object_id
from app.db import storage
from app.db.mongo import get_db
from app.evaluation import remove_from_eval_set
from app.schemas.user import UserOut, UserUpdate, user_out
from app.services.accuracy import AccuracySummaryOut, summarize

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(_: AdminUser) -> list[UserOut]:
    cursor = get_db().users.find().sort("created_at", DESCENDING)
    return [user_out(doc) async for doc in cursor]


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, admin: AdminUser) -> UserOut:
    target_id = parse_object_id(user_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if target_id == admin["_id"] and changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins cannot change their own account")
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No changes provided")

    doc = await get_db().users.find_one_and_update(
        {"_id": target_id}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user_out(doc)


@router.get("/stats")
async def stats(_: AdminUser) -> dict:
    db = get_db()
    return {
        "contractors": await db.users.count_documents({"role": "contractor"}),
        "admins": await db.users.count_documents({"role": "admin"}),
        "projects": await db.projects.count_documents({}),
    }


# --- Extraction accuracy, feedback and the evaluation set (PRD 4.13, 6.5) ----------------------


class FeedbackStatsOut(BaseModel):
    total: int
    right: int
    wrong: int
    right_pct: Decimal | None
    # Rooms read from a plan vs typed in: is a "wrong" usually a misread plan?
    wrong_on_extracted_rooms: int
    wrong_on_corrected_rooms: int
    recent: list[dict]  # latest wrong answers with comments


class AdminAccuracyOut(BaseModel):
    extraction: AccuracySummaryOut
    feedback: FeedbackStatsOut


class EvalEntryOut(BaseModel):
    id: str
    project_name: str | None
    files: int
    rooms: int
    accuracy_pct_at_add: str | None
    created_at: datetime


@router.get("/accuracy", response_model=AdminAccuracyOut)
async def accuracy(_: AdminUser) -> AdminAccuracyOut:
    db = get_db()
    outcomes = [
        o
        async for o in db.extraction_outcomes.find(
            {}, {"kind": 1, "status": 1, "method": 1, "corrected_fields": 1, "room_id": 1}
        )
    ]
    feedback = [f async for f in db.feedback.find({}).sort("created_at", DESCENDING)]
    wrong = [f for f in feedback if not f["right"]]
    right = len(feedback) - len(wrong)
    return AdminAccuracyOut(
        extraction=summarize(outcomes, list_corrections=False),
        feedback=FeedbackStatsOut(
            total=len(feedback),
            right=right,
            wrong=len(wrong),
            right_pct=(Decimal(right) / len(feedback) * 100).quantize(Decimal("0.1"))
            if feedback
            else None,
            wrong_on_extracted_rooms=sum(
                1 for f in wrong if f["snapshot"].get("origin") in ("auto", "edited")
            ),
            wrong_on_corrected_rooms=sum(1 for f in wrong if f["snapshot"].get("corrected_fields")),
            recent=[
                {
                    "room_name": f["snapshot"].get("room_name"),
                    "estimated_boxes": f["snapshot"]["boxes"],
                    "actual_boxes": f.get("actual_boxes"),
                    "comment": f.get("comment"),
                    "origin": f["snapshot"].get("origin"),
                    "created_at": f["created_at"],
                }
                for f in wrong[:20]
            ],
        ),
    )


@router.get("/evaluation", response_model=list[EvalEntryOut])
async def evaluation_set(_: AdminUser) -> list[EvalEntryOut]:
    cursor = get_db().eval_plans.find({}).sort("created_at", DESCENDING)
    return [
        EvalEntryOut(
            id=str(e["_id"]),
            project_name=e.get("project_name"),
            files=len(e["files"]),
            rooms=len(e["truth"]),
            accuracy_pct_at_add=(e.get("summary_at_add") or {}).get("accuracy_pct"),
            created_at=e["created_at"],
        )
        async for e in cursor
    ]


@router.get("/evaluation/export")
async def export_evaluation_set(_: AdminUser) -> Response:
    """A zip with one folder per plan: the plan file(s) and truth.json (the verified rooms)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        async for e in get_db().eval_plans.find({}).sort("created_at", 1):
            folder = str(e["_id"])
            for f in e["files"]:
                data = await storage.get(f["eval_file_id"], bucket="eval")
                zf.writestr(f"{folder}/{f['filename']}", data)
            meta = {
                "project_name": e.get("project_name"),
                "plan_unit": e.get("plan_unit"),
                "files": [{k: v for k, v in f.items() if k != "eval_file_id"} for f in e["files"]],
                "truth": e["truth"],
                "created_at": e["created_at"].isoformat(),
            }
            zf.writestr(f"{folder}/truth.json", json.dumps(meta, indent=2, default=str))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="evaluation-set.zip"'},
    )


@router.delete("/evaluation/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evaluation_entry(entry_id: str, _: AdminUser) -> Response:
    if not await remove_from_eval_set({"_id": parse_object_id(entry_id)}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in the evaluation set")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
