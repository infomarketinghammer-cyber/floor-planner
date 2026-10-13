"""Cost settings (PRD 4.10): currency, tax, delivery/labour lines and the budget.

Not a room change: saving doesn't bump the rooms version, so it never conflicts with room edits
or undo/redo in another tab. The response is the full room state, with the costs recalculated.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pymongo import ReturnDocument

from app.api.deps import CurrentUser
from app.api.v1.rooms import rooms_out
from app.db.mongo import get_db
from app.schemas.cost import CostSettings
from app.schemas.project import RoomsOut
from app.services.history import record_version
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/cost", tags=["cost"])


@router.put("/settings", response_model=RoomsOut)
async def set_cost_settings(project_id: str, body: CostSettings, user: CurrentUser) -> RoomsOut:
    project = await get_project_or_404(user, project_id, "cost")
    # Lines added in the browser carry temporary ids; give them, and any repeats, lasting ones.
    seen: set[str] = set()
    for line in body.lines:
        if line.id.startswith("new-") or line.id in seen:
            line.id = uuid.uuid4().hex[:8]
        seen.add(line.id)
    doc = await get_db().projects.find_one_and_update(
        {"_id": project["_id"]},
        {"$set": {"cost_settings": body.model_dump(), "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    await record_version(doc)
    return rooms_out(doc)
