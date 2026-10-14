"""Sign-up, sign-in and the session (PRD 4.14). The session token lives in an httpOnly,
SameSite=Strict cookie, so page scripts can't read it and other sites can't send it."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import CurrentUser
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.ratelimit import RateLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.mongo import get_db
from app.schemas.user import LoginRequest, RegisterRequest, Role, SessionOut, user_out
from app.services.collab import attach_invites

router = APIRouter(prefix="/auth", tags=["auth"])

# Keyed by IP and email: this stops guessing one account's password, and visitors behind a
# shared address (an office, a proxy) don't use up each other's allowance.
_credentials = RateLimiter(30, 15 * 60, "Too many sign-in attempts. Try again in a few minutes.")


def _limit(request: Request, email: str) -> None:
    _credentials.check(f"{client_ip(request)}|{email.lower()}")


def _start_session(response: Response, user: dict) -> SessionOut:
    s = get_settings()
    response.set_cookie(
        s.cookie_name,
        create_access_token(str(user["_id"]), user["role"]),
        max_age=s.jwt_expire_minutes * 60,
        httponly=True,
        secure=s.production,
        samesite="strict",
        path="/",
    )
    return SessionOut(user=user_out(user))


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, response: Response) -> SessionOut:
    """Self-registration always creates a contractor. Admins are seeded or promoted."""
    _limit(request, body.email)
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
    await attach_invites(user)  # teams and projects they were invited to before signing up
    return _start_session(response, user)


@router.post("/login", response_model=SessionOut)
async def login(body: LoginRequest, request: Request, response: Response) -> SessionOut:
    _limit(request, body.email)
    user = await get_db().users.find_one({"email": body.email.lower()})
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    await attach_invites(user)
    return _start_session(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    s = get_settings()
    response.delete_cookie(
        s.cookie_name, path="/", httponly=True, secure=s.production, samesite="strict"
    )
    return response


@router.get("/me", response_model=SessionOut)
async def me(user: CurrentUser) -> SessionOut:
    return SessionOut(user=user_out(user))
