import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core import crypto
from app.core.config import get_settings
from app.core.security import hash_password
from app.db import mongo
from app.schemas.user import Role
from app.services.tiles import seed_catalog

logger = logging.getLogger("floor_planner")


async def _seed_admin() -> None:
    settings = get_settings()
    if not (settings.admin_email and settings.admin_password):
        return
    users = mongo.get_db().users
    if await users.find_one({"role": Role.ADMIN.value}):
        return
    await users.insert_one(
        {
            "name": "Administrator",
            "email": settings.admin_email.lower(),
            "company": None,
            "password_hash": hash_password(settings.admin_password),
            "role": Role.ADMIN.value,
            "is_active": True,
            "created_at": datetime.now(UTC),
        }
    )
    logger.warning("Seeded admin account %s", settings.admin_email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    crypto.check_key()  # a bad key should stop startup, not the first upload
    if not crypto.enabled():
        logger.warning(
            "FILE_ENCRYPTION_KEY is not set: uploaded plans are stored unencrypted. "
            "See app/core/crypto.py to generate a key."
        )
    await mongo.connect()
    await _seed_admin()
    if seeded := await seed_catalog(mongo.get_db()):
        logger.warning("Seeded tile catalogue with %d common sizes", seeded)
    yield
    await mongo.close()


app = FastAPI(
    title="Floor Planner API",
    version="0.1.0",
    lifespan=lifespan,
    # No public API docs in production: the app is the only client.
    docs_url=None if get_settings().production else "/docs",
    redoc_url=None,
    openapi_url=None if get_settings().production else "/openapi.json",
)


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    """Refuse oversized requests before reading them, and add security headers."""
    s = get_settings()
    guest = request.url.path.startswith("/api/v1/guest/")
    limit_mb = s.max_guest_call_mb if guest else s.max_upload_mb + 1  # 1 MB for form overhead
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit_mb * 1_048_576:
        detail = (
            f"This project is too large to work on without an account (over {s.max_guest_call_mb} MB). Sign in to keep working."
            if guest
            else f"The file is too large; the limit is {s.max_upload_mb} MB."
        )
        return JSONResponse({"detail": detail}, status_code=413)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if s.production:  # browsers then stay on HTTPS (PRD 4.14, encryption in transit)
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
