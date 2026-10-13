from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import get_settings

_client: AsyncMongoClient | None = None


async def connect() -> None:
    global _client
    settings = get_settings()
    _client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    await _client.admin.command("ping")
    await _ensure_indexes()


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_db() -> AsyncDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client is not connected")
    return _client[get_settings().mongodb_db]


async def _ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index([("email", ASCENDING)], unique=True)
    await db.projects.create_index([("owner_id", ASCENDING), ("updated_at", ASCENDING)])
    await db.blueprints.create_index([("project_id", ASCENDING), ("created_at", ASCENDING)])
    await db.tiles.create_index(
        [("scope", ASCENDING), ("archived", ASCENDING), ("name", ASCENDING)]
    )
    await db.tiles.create_index([("owner_id", ASCENDING), ("archived", ASCENDING)])
    # Shopping-list emails sent, for the per-user hourly limit; entries expire after a day.
    await db.email_log.create_index([("user_id", ASCENDING), ("sent_at", ASCENDING)])
    await db.email_log.create_index([("sent_at", ASCENDING)], expireAfterSeconds=86_400)
    await db.extraction_outcomes.create_index(
        [("project_id", ASCENDING), ("room_id", ASCENDING)], unique=True
    )
    await db.feedback.create_index([("project_id", ASCENDING), ("created_at", ASCENDING)])
    await db.eval_plans.create_index([("project_id", ASCENDING)])
