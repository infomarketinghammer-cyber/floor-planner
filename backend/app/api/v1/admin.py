from fastapi import APIRouter, HTTPException, status
from pymongo import DESCENDING, ReturnDocument

from app.api.deps import AdminUser, parse_object_id
from app.db.mongo import get_db
from app.schemas.user import UserOut, UserUpdate, user_out

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
