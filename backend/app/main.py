import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

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


app = FastAPI(title="Floor Planner API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
