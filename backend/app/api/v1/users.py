from fastapi import APIRouter
from pymongo import ReturnDocument

from app.api.deps import CurrentUser
from app.db.mongo import get_db
from app.schemas.user import Preferences, UserOut, user_out

router = APIRouter(prefix="/users", tags=["users"])


@router.put("/me/preferences", response_model=UserOut)
async def update_preferences(body: Preferences, user: CurrentUser) -> UserOut:
    doc = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"preferences": body.model_dump(mode="json")}},
        return_document=ReturnDocument.AFTER,
    )
    return user_out(doc)
