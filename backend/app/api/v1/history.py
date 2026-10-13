"""Project history and backups (PRD 4.12).

- History: a timeline of versions (who, what, when, totals), each restorable.
- Backup: the whole project as one JSON file, plan files included, in the same Extended JSON
  format the browser keeps for projects without an account, so a backup moves freely between a
  browser and an account.
"""

import base64
import json
import uuid
from datetime import UTC, datetime

from bson import ObjectId, json_util
from bson.json_util import RELAXED_JSON_OPTIONS
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ValidationError

from app.api.deps import CurrentUser, parse_object_id
from app.api.v1.materials import _check_version
from app.api.v1.rooms import _replace_rooms
from app.db import storage
from app.db.mongo import get_db
from app.schemas.project import ProjectOut, Room, RoomsOut
from app.services.history import SNAPSHOT_FIELDS
from app.services.project_summary import project_out
from app.services.projects import get_project_or_404, save_rooms

router = APIRouter(tags=["history"])

BACKUP_FORMAT = "floor-planner-backup"
BACKUP_VERSION = 1
MAX_BACKUP_BYTES = 80 * 1024 * 1024


class VersionOut(BaseModel):
    id: str
    at: datetime
    user_name: str | None
    label: str
    metrics: dict


@router.get("/projects/{project_id}/versions", response_model=list[VersionOut])
async def list_versions(project_id: str, user: CurrentUser) -> list[VersionOut]:
    project = await get_project_or_404(user, project_id)
    cursor = (
        get_db()
        .project_versions.find({"project_id": project["_id"]}, {"snapshot": 0})
        .sort("at", -1)
    )
    return [
        VersionOut(
            id=str(v["_id"]),
            at=v["at"],
            user_name=v.get("user_name"),
            label=v["label"],
            metrics=v.get("metrics") or {},
        )
        async for v in cursor
    ]


@router.post("/projects/{project_id}/versions/{version_id}/restore", response_model=RoomsOut)
async def restore_version(
    project_id: str, version_id: str, version: int, user: CurrentUser
) -> RoomsOut:
    """Put the rooms, tiles and settings back as they were. Plan files aren't affected, and the
    restore itself becomes a new version, so it can be undone the same way."""
    project = await get_project_or_404(user, project_id)
    _check_version(project, version)
    v = await get_db().project_versions.find_one(
        {"_id": parse_object_id(version_id), "project_id": project["_id"]}
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    snap = v["snapshot"]
    rooms = [Room.model_validate(r) for r in snap.get("rooms") or []]
    extra = {k: snap.get(k) for k in SNAPSHOT_FIELDS if k != "rooms"}
    return await _replace_rooms(project, rooms, extra)


# --- Backups ------------------------------------------------------------------------------------


def _dump(obj) -> dict:
    return json.loads(json_util.dumps(obj, json_options=RELAXED_JSON_OPTIONS))


def blueprint_file_ids(bp: dict) -> list[ObjectId]:
    ids = [bp.get("file_id"), bp.get("converted_file_id")] + [
        p.get("thumbnail_id") for p in bp.get("pages", [])
    ]
    return [i for i in ids if i]


@router.get("/projects/{project_id}/backup")
async def download_backup(project_id: str, user: CurrentUser) -> Response:
    """The project, its plan files and settings, as one file to keep or move."""
    project = await get_project_or_404(user, project_id)
    blueprints = [b async for b in get_db().blueprints.find({"project_id": project["_id"]})]
    files = {}
    for bp in blueprints:
        for fid in blueprint_file_ids(bp):
            files[str(fid)] = base64.b64encode(await storage.get(fid)).decode()
    data = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": _dump(
            {k: v for k, v in project.items() if k not in ("owner_id", "team_id", "share")}
        ),
        "blueprints": _dump(blueprints),
        "files": files,
    }
    name = (
        "".join(c for c in project.get("name", "project") if c.isalnum() or c in " -_").strip()
        or "project"
    )
    return Response(
        json.dumps(data),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{name[:80]} - backup.floorplan.json"',
            "Cache-Control": "no-store",
        },
    )


def parse_backup(raw: bytes) -> dict:
    """Validate a backup file; raises HTTPException with a user-facing message."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This isn't a Floor Planner backup file."
        ) from None
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This isn't a Floor Planner backup file."
        )
    if data.get("version", 0) > BACKUP_VERSION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This backup was made by a newer version of Floor Planner.",
        )
    return data


@router.post("/projects/import", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def import_project(file: UploadFile, user: CurrentUser) -> ProjectOut:
    """A backup (or a project moved from this browser) becomes a new project in the account,
    with new ids throughout."""
    raw = await file.read(MAX_BACKUP_BYTES + 1)
    if len(raw) > MAX_BACKUP_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The backup is over 80 MB.")
    data = parse_backup(raw)
    project = json_util.loads(json.dumps(data["project"]))
    try:
        rooms = [Room.model_validate(r) for r in project.get("rooms", [])]
    except ValidationError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The backup's rooms couldn't be read."
        ) from None

    # New ids for the project, its plan files and their stored files.
    pid = ObjectId()
    file_map: dict[str, ObjectId] = {}
    for old_id, b64 in (data.get("files") or {}).items():
        content = base64.b64decode(b64)
        file_map[old_id] = await storage.put(
            content, f"import-{old_id}", "application/octet-stream"
        )
    blueprint_map: dict[str, str] = {}
    blueprints = []
    for bp in json_util.loads(json.dumps(data.get("blueprints") or [])):
        new_bp = ObjectId()
        blueprint_map[str(bp["_id"])] = str(new_bp)
        bp.update(_id=new_bp, project_id=pid, uploaded_by=user["_id"])
        for key in ("file_id", "converted_file_id"):
            if bp.get(key):
                bp[key] = file_map.get(str(bp[key]))
        for page in bp.get("pages", []):
            if page.get("thumbnail_id"):
                page["thumbnail_id"] = file_map.get(str(page["thumbnail_id"]))
        blueprints.append(bp)
    for room in rooms:  # rooms point at the plan they were read from
        if room.source and room.source.file_id in blueprint_map:
            room.source.file_id = blueprint_map[room.source.file_id]
        room.id = room.id or uuid.uuid4().hex[:12]

    now = datetime.now(UTC)
    doc = {
        **{
            k: v
            for k, v in project.items()
            if k not in ("_id", "owner_id", "team_id", "share", "rooms")
        },
        "_id": pid,
        "owner_id": user["_id"],
        "rooms": [],
        "rooms_version": 0,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "last_exported_at": None,
    }
    await get_db().projects.insert_one(doc)
    if blueprints:
        await get_db().blueprints.insert_many(blueprints)
    # Rooms go through the normal save, so status, history and checks are all set as usual.
    saved = await save_rooms(pid, {"$set": {"rooms": [r.model_dump() for r in rooms]}})
    return project_out(saved)
