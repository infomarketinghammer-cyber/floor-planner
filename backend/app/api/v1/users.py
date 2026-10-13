from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.api.deps import CurrentUser, parse_object_id
from app.core.security import verify_password
from app.db.mongo import get_db
from app.evaluation import remove_from_eval_set
from app.schemas.user import Preferences, Role, UserOut, user_out
from app.services.data_deletion import delete_account

router = APIRouter(prefix="/users", tags=["users"])


@router.put("/me/preferences", response_model=UserOut)
async def update_preferences(body: Preferences, user: CurrentUser) -> UserOut:
    doc = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"preferences": body.model_dump(mode="json")}},
        return_document=ReturnDocument.AFTER,
    )
    return user_out(doc)


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)  # confirms it's really the user


class DeleteAccountOut(BaseModel):
    projects: int
    tiles: int
    evaluation_copies: int


@router.delete("/me", response_model=DeleteAccountOut)
async def delete_me(body: DeleteAccountIn, user: CurrentUser) -> DeleteAccountOut:
    """Delete the account and everything in it (PRD 4.14). Cannot be undone."""
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That password isn't right.")
    if user["role"] == Role.ADMIN:
        admins = await get_db().users.count_documents({"role": Role.ADMIN.value, "is_active": True})
        if admins <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You're the only admin. Make someone else an admin before deleting your account.",
            )
    return DeleteAccountOut(**await delete_account(user["_id"]))


class SharedPlanOut(BaseModel):
    id: str
    project_name: str | None
    files: list[str]
    created_at: datetime
    project_exists: bool


def _mine(user: dict) -> dict:
    return {"$or": [{"owner_id": user["_id"]}, {"contributed_by": user["_id"]}]}


@router.get("/me/evaluation", response_model=list[SharedPlanOut])
async def my_shared_plans(user: CurrentUser) -> list[SharedPlanOut]:
    """Plans the user added to the evaluation set, including ones whose project was deleted,
    so the copies can always be removed."""
    db = get_db()
    out = []
    async for e in db.eval_plans.find(_mine(user)).sort("created_at", -1):
        exists = await db.projects.count_documents({"_id": e["project_id"]}, limit=1)
        out.append(
            SharedPlanOut(
                id=str(e["_id"]),
                project_name=e.get("project_name"),
                files=[f["filename"] for f in e["files"]],
                created_at=e["created_at"],
                project_exists=bool(exists),
            )
        )
    return out


@router.delete("/me/evaluation/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_shared_plan(entry_id: str, user: CurrentUser) -> Response:
    query = {"_id": parse_object_id(entry_id), **_mine(user)}
    if not await remove_from_eval_set(query):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
