from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import CurrentUser
from app.core.security import create_access_token, hash_password, verify_password
from app.db.mongo import get_db
from app.schemas.user import AuthResponse, LoginRequest, RegisterRequest, Role, UserOut, user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_response(user: dict) -> AuthResponse:
    token = create_access_token(str(user["_id"]), user["role"])
    return AuthResponse(access_token=token, user=user_out(user))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> AuthResponse:
    """Self-registration always creates a contractor. Admins are seeded or promoted."""
    user = {
        "name": body.name,
        "email": body.email.lower(),
        "company": body.company,
        "password_hash": hash_password(body.password),
        "role": Role.CONTRACTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    try:
        result = await get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from None
    user["_id"] = result.inserted_id
    return _auth_response(user)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest) -> AuthResponse:
    user = await get_db().users.find_one({"email": body.email.lower()})
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    return _auth_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)
