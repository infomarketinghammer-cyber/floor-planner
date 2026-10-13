"""Blueprints: upload, page settings, previews, download (PRD 4.1) and room extraction (PRD 4.2)."""

import asyncio
import re
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pymongo import ASCENDING

from app.api.deps import CurrentUser, parse_object_id
from app.core.config import get_settings
from app.db import storage
from app.db.mongo import get_db
from app.engine.units import LengthUnit
from app.extraction.service import extract_pages, to_room
from app.extraction.sources import render_preview
from app.schemas.blueprint import BlueprintOut, ExtractionOut, PageUpdate, blueprint_out
from app.schemas.project import Room, RoomOrigin
from app.services.projects import get_project_or_404, save_rooms, touch
from app.uploads.inspect import FileKind, UploadError, inspect_upload

router = APIRouter(prefix="/projects/{project_id}/files", tags=["files"])

MAX_FILES_PER_PROJECT = 20
# Inspection is CPU-heavy (rendering, quality checks); don't let uploads starve the API.
_inspect_slots = asyncio.Semaphore(2)


def _clean_filename(name: str | None) -> str:
    base = Path(name or "upload").name
    return re.sub(r"[\x00-\x1f\x7f]", "", base)[:200] or "upload"


async def _get_blueprint_or_404(project_id, file_id: str) -> dict:
    doc = await get_db().blueprints.find_one(
        {"_id": parse_object_id(file_id), "project_id": project_id}
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return doc


@router.get("", response_model=list[BlueprintOut])
async def list_files(project_id: str, user: CurrentUser) -> list[BlueprintOut]:
    project = await get_project_or_404(user, project_id)
    cursor = get_db().blueprints.find({"project_id": project["_id"]}).sort("created_at", ASCENDING)
    return [blueprint_out(doc) async for doc in cursor]


@router.post("", response_model=BlueprintOut, status_code=status.HTTP_201_CREATED)
async def upload_file(project_id: str, file: UploadFile, user: CurrentUser) -> BlueprintOut:
    project = await get_project_or_404(user, project_id)
    if (
        await get_db().blueprints.count_documents({"project_id": project["_id"]})
        >= MAX_FILES_PER_PROJECT
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A project can have at most {MAX_FILES_PER_PROJECT} files."
        )

    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1_048_576
    filename = _clean_filename(file.filename)
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is {file.size / 1_048_576:.1f} MB; the limit is {settings.max_upload_mb} MB.",
        )
    data = await file.read(max_bytes + 1)  # one extra byte is enough to detect "too large"

    try:
        async with _inspect_slots:
            result = await asyncio.to_thread(
                inspect_upload,
                filename,
                data,
                max_bytes=max_bytes,
                max_pages=settings.max_pdf_pages,
                dwg_converter=settings.oda_converter_path,
            )
    except UploadError as e:
        raise HTTPException(e.status_code, e.message) from None

    owner = {"project_id": project["_id"]}
    file_id = await storage.put(data, filename, result.content_type, **owner)
    converted_id = (
        await storage.put(
            result.converted_dxf, f"{Path(filename).stem}.dxf", "application/dxf", **owner
        )
        if result.converted_dxf
        else None
    )
    pages = []
    for page in result.pages:
        thumb_id = (
            await storage.put(page.thumbnail_png, f"page-{page.index}.png", "image/png", **owner)
            if page.thumbnail_png
            else None
        )
        pages.append(
            {
                "index": page.index,
                "width": page.width,
                "height": page.height,
                "has_text": page.has_text,
                "floor": page.floor_guess,
                "included": True,
                "thumbnail_id": thumb_id,
                "warnings": [w.__dict__ for w in page.warnings],
            }
        )

    doc = {
        "project_id": project["_id"],
        "uploaded_by": user["_id"],
        "filename": filename,
        "kind": result.kind.value,
        "content_type": result.content_type,
        "size_bytes": len(data),
        "file_id": file_id,
        "converted_file_id": converted_id,
        "detected_unit": result.detected_unit.value if result.detected_unit else None,
        "warnings": [w.__dict__ for w in result.warnings],
        "pages": pages,
        "created_at": datetime.now(UTC),
    }
    doc["_id"] = (await get_db().blueprints.insert_one(doc)).inserted_id
    await touch(project["_id"])
    return blueprint_out(doc)


@router.patch("/{file_id}/pages/{page_index}", response_model=BlueprintOut)
async def update_page(
    project_id: str, file_id: str, page_index: int, body: PageUpdate, user: CurrentUser
) -> BlueprintOut:
    """Set the floor a page shows, or exclude a page (e.g. a cover sheet) from extraction."""
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    if not 0 <= page_index < len(doc["pages"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")

    changes = body.model_dump(exclude_unset=True)
    if "floor" in changes:
        changes["floor"] = (changes["floor"] or "").strip() or None
    if changes.get("included") is None:
        changes.pop("included", None)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No changes provided")

    await get_db().blueprints.update_one(
        {"_id": doc["_id"]}, {"$set": {f"pages.{page_index}.{k}": v for k, v in changes.items()}}
    )
    await touch(project["_id"])
    doc["pages"][page_index].update(changes)
    return blueprint_out(doc)


@router.get("/{file_id}/pages/{page_index}/thumbnail")
async def page_thumbnail(
    project_id: str, file_id: str, page_index: int, user: CurrentUser
) -> Response:
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    if (
        not 0 <= page_index < len(doc["pages"])
        or doc["pages"][page_index].get("thumbnail_id") is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preview not available")
    png = await storage.get(doc["pages"][page_index]["thumbnail_id"])
    return Response(
        png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}
    )


_preview_cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_PREVIEW_CACHE_SIZE = 24


@router.get("/{file_id}/pages/{page_index}/preview")
async def page_preview(
    project_id: str, file_id: str, page_index: int, user: CurrentUser
) -> Response:
    """Large page image for the review screen (PRD 4.3): source boxes are drawn over it."""
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    if not 0 <= page_index < len(doc["pages"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")

    key = (file_id, page_index)
    png = _preview_cache.get(key)
    if png is None:
        data = await storage.get(doc.get("converted_file_id") or doc["file_id"])
        async with _inspect_slots:
            png = await asyncio.to_thread(render_preview, doc["kind"], data, page_index)
        if png is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Preview not available")
        _preview_cache[key] = png
        if len(_preview_cache) > _PREVIEW_CACHE_SIZE:
            _preview_cache.popitem(last=False)
    else:
        _preview_cache.move_to_end(key)
    return Response(
        png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get("/{file_id}/download")
async def download_file(project_id: str, file_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    data = await storage.get(doc["file_id"])
    disposition = f"attachment; filename*=UTF-8''{quote(doc['filename'])}"
    return Response(
        data, media_type=doc["content_type"], headers={"Content-Disposition": disposition}
    )


@router.post("/{file_id}/extract", response_model=ExtractionOut)
async def extract_rooms(project_id: str, file_id: str, user: CurrentUser) -> ExtractionOut:
    """Read rooms from the file's included pages into the project as unconfirmed rooms.

    Re-running replaces this file's untouched auto-extracted rooms. Rooms the user edited,
    added or imported are never touched (PRD 6.3: no lost work).
    """
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    data = await storage.get(doc.get("converted_file_id") or doc["file_id"])
    plan_unit = LengthUnit(project["plan_unit"]) if project.get("plan_unit_confirmed") else None
    results = await extract_pages(FileKind(doc["kind"]), data, doc["pages"], plan_unit)

    fid = str(doc["_id"])
    floors = {p["index"]: p["floor"] for p in doc["pages"]}
    # A CAD drawing's declared units are the strongest evidence for the plan unit (PRD 4.4).
    drawing_unit = {"drawing_unit": doc["detected_unit"]} if doc.get("detected_unit") else {}
    extracted_rooms = [
        to_room(
            extracted,
            file_id=fid,
            page=page.index,
            method=page.method,
            floor=floors.get(page.index),
        )
        for page in results
        for extracted in page.rooms
    ]

    # Extraction can take a while (vision calls). Merge into the *latest* room list and save
    # with a version check, so edits made meanwhile are never overwritten.
    for _attempt in range(3):
        current = await get_db().projects.find_one({"_id": project["_id"]})
        existing = [Room.model_validate(r) for r in current.get("rooms", [])]
        from_this_file = [r for r in existing if r.source and r.source.file_id == fid]
        replaced = [r for r in from_this_file if r.origin == RoomOrigin.AUTO]
        kept_edited = {
            (r.name.lower(), r.source.page) for r in from_this_file if r.origin != RoomOrigin.AUTO
        }
        new_rooms = [
            r for r in extracted_rooms if (r.name.lower(), r.source.page) not in kept_edited
        ]
        replaced_ids = {r.id for r in replaced}
        rooms = [r for r in existing if r.id not in replaced_ids] + new_rooms
        saved = await save_rooms(
            project["_id"],
            {"$set": {"rooms": [r.model_dump() for r in rooms], **drawing_unit}},
            expected_version=current.get("rooms_version") or 0,
        )
        if saved is not None:
            break
    else:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The rooms kept changing during extraction. Try again."
        )

    errors = [p.error for p in results if p.error]
    flagged = sum(1 for r in new_rooms if r.confidence_level != "high" or r.flags)
    if errors and len(errors) == len(results):
        status_, message = "unavailable", errors[0]
    elif errors:
        status_, message = "partial", f"Some pages couldn't be read: {errors[0]}"
    elif not new_rooms:
        status_, message = (
            "no_rooms",
            "No room names or sizes were found. Add rooms manually or import a list.",
        )
    else:
        status_ = "done"
        message = f"Found {len(new_rooms)} room{'s' if len(new_rooms) != 1 else ''}"
        message += (
            f"; {flagged} {'needs' if flagged == 1 else 'need'} a closer look." if flagged else "."
        )
    extraction = {
        "status": status_,
        "message": message,
        "rooms_found": len(new_rooms),
        "rooms_flagged": flagged,
        "pages": [
            {"index": p.index, "method": p.method, "rooms": len(p.rooms), "error": p.error}
            for p in results
        ],
        "ran_at": datetime.now(UTC),
    }
    await get_db().blueprints.update_one({"_id": doc["_id"]}, {"$set": {"extraction": extraction}})
    doc["extraction"] = extraction
    return ExtractionOut(
        blueprint=blueprint_out(doc),
        rooms_added=len(new_rooms),
        rooms_replaced=len(replaced),
        rooms_kept=len(kept_edited),
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(project_id: str, file_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id)
    doc = await _get_blueprint_or_404(project["_id"], file_id)
    await delete_blueprint_files(doc)
    await get_db().blueprints.delete_one({"_id": doc["_id"]})
    await touch(project["_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def delete_blueprint_files(doc: dict) -> None:
    for key in [k for k in _preview_cache if k[0] == str(doc["_id"])]:
        del _preview_cache[key]
    await storage.delete(
        doc["file_id"], doc.get("converted_file_id"), *(p.get("thumbnail_id") for p in doc["pages"])
    )
