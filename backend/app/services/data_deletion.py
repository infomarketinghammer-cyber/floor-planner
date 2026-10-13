"""Deleting user data (PRD 4.14). One place, so every way of deleting removes the same things.

Retention rule: uploaded plans and project data are kept until the user deletes them. Nothing is
deleted automatically. Deleting:
- a plan file removes the file, its converted copy, its page thumbnails and cached previews;
- a project removes its plan files, rooms, accuracy records, feedback and quotes;
- an account removes all of the above for every project, the user's own tiles, their feedback,
  their evaluation-set copies, their email log, their company logo and quote numbering, and the
  account itself.
"""

from bson import ObjectId

from app.api.v1.files import delete_blueprint_files
from app.db import storage
from app.db.mongo import get_db
from app.evaluation import remove_from_eval_set


async def delete_project_data(project: dict) -> None:
    """Everything that belongs to a project, after the project document itself is deleted.
    Evaluation-set copies are separate (the user agreed to keep them) and stay."""
    db = get_db()
    pid = project["_id"]
    async for blueprint in db.blueprints.find({"project_id": pid}):
        await delete_blueprint_files(blueprint)
    await db.blueprints.delete_many({"project_id": pid})
    await db.extraction_outcomes.delete_many({"project_id": pid})
    await db.feedback.delete_many({"project_id": pid})
    await db.quotes.delete_many({"project_id": pid})
    for coll in ("project_versions", "comments", "approvals", "activity"):
        await db[coll].delete_many({"project_id": pid})


async def delete_account(user_id: ObjectId) -> dict[str, int]:
    """Delete a user and all their data. Returns counts, for the confirmation message."""
    db = get_db()
    projects = 0
    async for project in db.projects.find({"owner_id": user_id}):
        await db.projects.delete_one({"_id": project["_id"]})
        await delete_project_data(project)
        projects += 1
    eval_copies = await remove_from_eval_set(
        {"$or": [{"owner_id": user_id}, {"contributed_by": user_id}]}
    )
    tiles = (
        await db.tiles.delete_many({"owner_id": user_id, "scope": {"$ne": "catalog"}})
    ).deleted_count
    await db.feedback.delete_many({"user_id": user_id})
    await db.email_log.delete_many({"user_id": user_id})
    user = await db.users.find_one({"_id": user_id}, {"company_logo_id": 1})
    if user and user.get("company_logo_id"):
        await storage.delete(user["company_logo_id"])
    await db.counters.delete_many({"_id": {"$regex": f"^quote:{user_id}:"}})
    # Teams they own are dissolved (projects stay with their owners); other teams drop them.
    async for team in db.teams.find({"owner_id": user_id}, {"_id": 1}):
        await db.projects.update_many({"team_id": team["_id"]}, {"$unset": {"team_id": ""}})
        await db.teams.delete_one({"_id": team["_id"]})
    await db.teams.update_many({}, {"$pull": {"members": {"user_id": user_id}}})
    await db.projects.update_many({}, {"$pull": {"members": {"user_id": user_id}}})
    await db.users.delete_one({"_id": user_id})
    return {"projects": projects, "tiles": tiles, "evaluation_copies": eval_copies}
