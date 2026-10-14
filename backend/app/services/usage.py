"""Usage events for the platform dashboard (PRD 4.21): uploads, exports, new projects and quotes.

Plan files and projects can be deleted, so counting what's left would undercount; one small
event per action is kept instead. No content, only what kind of action it was and when.
Guests are not counted: nothing about them is kept on the server.
"""

from datetime import UTC, datetime
from typing import Literal

from app.core.activity import acting_user, current_action
from app.core.guest import is_guest
from app.db.mongo import get_db

UsageKind = Literal["upload", "export", "project", "quote"]


async def log_usage(kind: UsageKind, detail: str | None = None) -> None:
    if is_guest():
        return
    user = acting_user()
    await get_db().usage_events.insert_one(
        {
            "kind": kind,
            "detail": detail or current_action(""),
            "user_id": user["_id"] if user else None,
            "at": datetime.now(UTC),
        }
    )
