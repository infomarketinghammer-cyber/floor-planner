"""Guest dispatcher (PRD 4.12 local-first): run an API call against a project kept in the browser.

The browser sends the call (method, path, body) together with its copy of the project, the
project's plan files that the call needs, and its own saved tiles. The call runs through the
real API inside an in-memory sandbox (app/core/guest.py); the response comes back together with
the updated project, files and tiles for the browser to store. Nothing is kept on the server.

Only routes that make sense without an account are allowed: no admin, email, feedback,
evaluation set, quotes or AI reading.
"""

import base64
import json
import re
import time
from collections import defaultdict, deque
from typing import Any, Literal

import httpx
from bson import ObjectId, json_util
from bson.json_util import RELAXED_JSON_OPTIONS
from fastapi import APIRouter, HTTPException, Request, status
from mongomock_motor import AsyncMongoMockClient
from pydantic import BaseModel, Field

from app.core.guest import GuestScope
from app.db.mongo import get_db
from app.services.project_summary import project_out as project_summary

router = APIRouter(prefix="/guest", tags=["guest"])

OID = r"[0-9a-f]{24}"
ALLOWED: list[tuple[str, str]] = [
    ("POST", r"/projects"),
    ("GET|PATCH", rf"/projects/{OID}"),
    ("GET", rf"/projects/{OID}/(estimate|dashboard)"),
    ("GET|POST|PUT|PATCH|DELETE", rf"/projects/{OID}/rooms(/.*)?"),
    ("GET|POST|PUT|PATCH|DELETE", rf"/projects/{OID}/files(/.*)?"),
    ("PUT", rf"/projects/{OID}/materials/default"),
    ("PUT", rf"/projects/{OID}/(extras|cost)/settings"),
    ("GET", rf"/projects/{OID}/(suggestions|tile-advice|tile-updates)"),
    ("POST", rf"/projects/{OID}/tile-updates/apply"),
    (
        "GET",
        rf"/projects/{OID}/exports/(report\.pdf|estimate\.xlsx|shopping-list\.pdf|order-list\.pdf|options)",
    ),
    ("GET|POST|PATCH|DELETE", rf"/projects/{OID}/scenarios(/.*)?"),
    ("GET|POST", r"/tiles"),
    ("PUT|DELETE", rf"/tiles/{OID}"),
    ("POST", rf"/tiles/{OID}/copy"),
]
_ALLOWED = [(set(m.split("|")), re.compile(f"^{p}$")) for m, p in ALLOWED]

RATE_LIMIT, RATE_WINDOW_S = 600, 600  # calls per IP per 10 minutes
_calls: dict[str, deque] = defaultdict(deque)
CATALOG_TTL_S = 300
_catalog: tuple[float, list[dict]] = (0.0, [])


class Upload(BaseModel):
    field: str = "file"
    filename: str = Field(max_length=255)
    content_type: str = "application/octet-stream"
    data_b64: str
    form: dict[str, str] = Field(default_factory=dict)  # other form fields, e.g. dry_run


class GuestCallIn(BaseModel):
    guest_id: str = Field(pattern=f"^{OID}$")  # stable per browser, made by the browser
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(max_length=400)  # under /api/v1, with any query string
    body: Any = None
    upload: Upload | None = None
    project: dict | None = None  # Extended JSON, exactly as this endpoint returned it
    blueprints: list[dict] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)  # file id -> base64, only those needed
    tiles: list[dict] = Field(default_factory=list)  # the guest's own saved tiles
    preferences: dict = Field(default_factory=dict)


class GuestCallOut(BaseModel):
    status: int
    content_type: str
    content_disposition: str | None
    body: Any = None  # JSON responses
    body_b64: str | None = None  # files (PDF, Excel, images)
    project: dict | None
    summary: dict | None  # the project's card for the browser's project list (ProjectOut)
    blueprints: list[dict]
    files_added: dict[str, str]
    files_deleted: list[str]
    tiles: list[dict]


def _load(obj: Any) -> Any:
    return json_util.loads(json.dumps(obj))


def _dump(obj: Any) -> Any:
    return json.loads(json_util.dumps(obj, json_options=RELAXED_JSON_OPTIONS))


def _check_rate(ip: str) -> None:
    now = time.monotonic()
    calls = _calls[ip]
    while calls and now - calls[0] > RATE_WINDOW_S:
        calls.popleft()
    if len(calls) >= RATE_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests. Wait a few minutes and try again.",
        )
    calls.append(now)


async def _catalog_tiles() -> list[dict]:
    """The shared catalogue, read from the real database (outside the sandbox) and cached."""
    global _catalog
    if time.monotonic() - _catalog[0] > CATALOG_TTL_S:
        docs = [
            d async for d in get_db().tiles.find({"scope": "catalog", "archived": {"$ne": True}})
        ]
        _catalog = (time.monotonic(), docs)
    return _catalog[1]


def _allowed(method: str, path: str) -> bool:
    bare = path.split("?", 1)[0]
    return any(method in methods and rx.match(bare) for methods, rx in _ALLOWED)


@router.post("/call", response_model=GuestCallOut)
async def guest_call(body: GuestCallIn, request: Request) -> GuestCallOut:
    if not _allowed(body.method, body.path):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in to use this.")
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    _check_rate(ip)

    guest_oid = ObjectId(body.guest_id)
    catalog = await _catalog_tiles()
    sandbox = AsyncMongoMockClient(tz_aware=True)["guest"]  # like the real client
    if catalog:
        await sandbox.tiles.insert_many([dict(d) for d in catalog])
    own_tiles = [_load(t) | {"owner_id": guest_oid, "scope": "user"} for t in body.tiles]
    if own_tiles:
        await sandbox.tiles.insert_many(own_tiles)
    if body.project:
        project = _load(body.project) | {
            "owner_id": guest_oid
        }  # the browser's project is the guest's
        await sandbox.projects.insert_one(project)
        blueprints = [_load(b) | {"project_id": project["_id"]} for b in body.blueprints]
        if blueprints:
            await sandbox.blueprints.insert_many(blueprints)
    files = {ObjectId(k): base64.b64decode(v) for k, v in body.files.items()}
    sent_files = set(files)
    user = {
        "_id": guest_oid,
        "name": "Guest",
        "email": "guest@local",
        "company": None,
        "role": "contractor",
        "is_active": True,
        "preferences": body.preferences,
    }

    kwargs: dict[str, Any] = {}
    if body.upload:
        up = body.upload
        kwargs["files"] = {up.field: (up.filename, base64.b64decode(up.data_b64), up.content_type)}
        kwargs["data"] = up.form
    elif body.body is not None:
        kwargs["json"] = body.body
    with GuestScope(sandbox, files, user):
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://guest") as client:
            response = await client.request(body.method, f"/api/v1{body.path}", **kwargs)

    content_type = response.headers.get("content-type", "")
    projects = [d async for d in sandbox.projects.find({})]
    project_out = projects[0] if len(projects) == 1 else None
    blueprints_out = (
        [d async for d in sandbox.blueprints.find({"project_id": project_out["_id"]})]
        if project_out
        else []
    )
    tiles_out = [d async for d in sandbox.tiles.find({"owner_id": guest_oid})]
    return GuestCallOut(
        status=response.status_code,
        content_type=content_type,
        content_disposition=response.headers.get("content-disposition"),
        body=response.json() if "json" in content_type and response.content else None,
        body_b64=None if "json" in content_type else base64.b64encode(response.content).decode(),
        project=_dump(project_out) if project_out else None,
        summary=project_summary(project_out).model_dump(mode="json") if project_out else None,
        blueprints=_dump(blueprints_out),
        files_added={
            str(k): base64.b64encode(v).decode() for k, v in files.items() if k not in sent_files
        },
        files_deleted=[str(k) for k in sent_files if k not in files],
        tiles=_dump(tiles_out),
    )
