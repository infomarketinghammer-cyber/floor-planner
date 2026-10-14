from typing import Annotated

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.activity import set_acting_user
from app.core.config import get_settings
from app.core.guest import guest_user
from app.core.security import decode_access_token
from app.db.mongo import get_db
from app.schemas.user import Role

_bearer = HTTPBearer(auto_error=False)


def parse_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    guest = guest_user()  # set only by the guest dispatcher, for its internal call
    if guest is not None:
        return guest
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    # The browser sends the session cookie; scripts and tools can send a Bearer token.
    token = (
        credentials.credentials if credentials else request.cookies.get(get_settings().cookie_name)
    )
    if not token:
        raise unauthorized
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise unauthorized from None

    user = await get_db().users.find_one({"_id": parse_object_id(payload["sub"])})
    if user is None or not user["is_active"]:
        raise unauthorized
    set_acting_user(user)  # for the project history and activity log
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_role(*roles: Role):
    async def checker(user: CurrentUser) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker


AdminUser = Annotated[dict, Depends(require_role(Role.ADMIN))]
