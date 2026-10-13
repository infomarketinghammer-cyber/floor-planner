"""Project access rules shared by every project-scoped router."""

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument

from app.api.deps import parse_object_id
from app.db.mongo import get_db
from app.schemas.project import ProjectStatus
from app.schemas.user import Role
from app.services.access import Need, check_access
from app.services.accuracy import sync_outcomes
from app.services.history import record_version
from app.services.materials import materials_summary, project_default
from app.services.review import review_state


def project_scope(user: dict, project_id: str | None = None) -> dict:
    """Projects the user owns (admins: all). Team and invited access is checked by
    get_project_or_404 and listed with access.visible_projects_query."""
    query: dict = {}
    if user["role"] != Role.ADMIN:
        query["owner_id"] = user["_id"]
    if project_id is not None:
        query["_id"] = parse_object_id(project_id)
    return query


async def get_project_or_404(user: dict, project_id: str, need: Need | None = None) -> dict:
    """The project, if the user's role on it allows `need` (by default: view for reads, edit
    for changes). Records the role for the rest of the request (e.g. hiding costs)."""
    doc = await get_db().projects.find_one({"_id": parse_object_id(project_id)})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    await check_access(user, doc, need)
    return doc


async def touch(project_id: ObjectId, update: dict | None = None) -> None:
    """Bump updated_at (drives "last edited" on the dashboard), optionally with other changes."""
    update = dict(update or {})
    update.setdefault("$set", {})["updated_at"] = datetime.now(UTC)
    await get_db().projects.update_one({"_id": project_id}, update)


async def save_rooms(
    project_id: ObjectId, update: dict, *, expected_version: int | None = None
) -> dict | None:
    """Apply a change to the room list. Every room change goes through here so that the
    version (undo/redo safety) and the project's review status stay correct.

    Returns the updated project, or None if `expected_version` no longer matches.
    """
    update = dict(update)
    update.setdefault("$set", {})["updated_at"] = datetime.now(UTC)
    update.setdefault("$inc", {})["rooms_version"] = 1
    query: dict = {"_id": project_id}
    if expected_version is not None:
        query["rooms_version"] = expected_version if expected_version else {"$in": [0, None]}

    doc = await get_db().projects.find_one_and_update(
        query, update, return_document=ReturnDocument.AFTER
    )
    if doc is None:
        return None

    # Any room change makes earlier results stale: status follows the current state.
    state = review_state(doc)
    if materials_summary(
        state.rooms, project_default(doc), state.summary.ready
    ).ready_for_calculation:
        status_ = ProjectStatus.CALCULATED  # quantities are produced on every read from here
    elif state.summary.ready:
        status_ = ProjectStatus.REVIEWED
    else:
        status_ = ProjectStatus.DRAFT
    if doc["status"] != status_:
        await get_db().projects.update_one({"_id": project_id}, {"$set": {"status": status_.value}})
        doc["status"] = status_.value
    await sync_outcomes(doc)  # extraction accuracy follows every room change (PRD 4.13)
    await record_version(doc)  # project history (PRD 4.12)
    return doc
