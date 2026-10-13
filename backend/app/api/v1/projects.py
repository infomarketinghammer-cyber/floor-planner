from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pymongo import DESCENDING, ReturnDocument

from app.api.deps import CurrentUser
from app.db.mongo import get_db
from app.schemas.estimate import EstimateOut
from app.schemas.project import ProjectCreate, ProjectOut, ProjectStatus, ProjectUpdate
from app.services.access import current_role, project_role, user_team_ids, visible_projects_query
from app.services.data_deletion import delete_project_data
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import project_default
from app.services.project_summary import project_out
from app.services.projects import get_project_or_404
from app.services.review import review_state

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser) -> list[ProjectOut]:
    query = await visible_projects_query(user)
    teams = await user_team_ids(user)
    cursor = get_db().projects.find(query).sort("updated_at", DESCENDING)
    return [project_out(doc, await project_role(user, doc, teams)) async for doc in cursor]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: CurrentUser) -> ProjectOut:
    now = datetime.now(UTC)
    doc = {
        "owner_id": user["_id"],
        "name": body.name,
        "notes": body.notes,
        "status": ProjectStatus.DRAFT.value,
        "rooms": [],
        "created_at": now,
        "updated_at": now,
        "last_exported_at": None,
    }
    result = await get_db().projects.insert_one(doc)
    doc["_id"] = result.inserted_id
    return project_out(doc)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, user: CurrentUser) -> ProjectOut:
    doc = await get_project_or_404(user, project_id)
    return project_out(doc, current_role())


@router.get("/{project_id}/estimate", response_model=EstimateOut)
async def get_estimate(project_id: str, user: CurrentUser) -> EstimateOut:
    """Tile quantities for every room (PRD 4.7), or why they can't be calculated yet."""
    doc = await get_project_or_404(user, project_id)
    return build_estimate(review_state(doc), project_default(doc), extras_settings(doc))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate, user: CurrentUser) -> ProjectOut:
    project = await get_project_or_404(user, project_id)
    changes = body.model_dump(exclude_unset=True)
    changes["updated_at"] = datetime.now(UTC)
    doc = await get_db().projects.find_one_and_update(
        {"_id": project["_id"]},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    return project_out(doc, current_role())


@router.post(
    "/{project_id}/duplicate", response_model=ProjectOut, status_code=status.HTTP_201_CREATED
)
async def duplicate_project(project_id: str, user: CurrentUser) -> ProjectOut:
    """Copies rooms and material choices. The copy belongs to the caller and is not exported."""
    source = await get_project_or_404(user, project_id, "edit")

    now = datetime.now(UTC)
    # The copy is the caller's own: no team, members, share link or quotes come with it.
    drop = {"_id", "team_id", "members", "invites", "share", "approval_requested_at"}
    copy = {k: v for k, v in source.items() if k not in drop}
    copy.update(
        owner_id=user["_id"],
        name=f"{source['name'][:143]} (copy)",  # stays within the 150-char limit
        created_at=now,
        updated_at=now,
        last_exported_at=None,
    )
    if copy["status"] == ProjectStatus.EXPORTED:
        copy["status"] = ProjectStatus.CALCULATED.value
    result = await get_db().projects.insert_one(copy)
    copy["_id"] = result.inserted_id
    return project_out(copy)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, user: CurrentUser) -> Response:
    found = await get_project_or_404(user, project_id, "manage")
    project = await get_db().projects.find_one_and_delete({"_id": found["_id"]})
    # Uploaded plans are sensitive (PRD 4.14): remove them, and everything else, with it.
    await delete_project_data(project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
