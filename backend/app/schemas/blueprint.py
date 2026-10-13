from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.engine.units import LengthUnit
from app.uploads.inspect import FileKind


class WarningOut(BaseModel):
    code: str
    message: str


class PageOut(BaseModel):
    index: int
    width: int
    height: int
    has_text: bool | None
    floor: str | None
    included: bool
    has_thumbnail: bool
    warnings: list[WarningOut]


class PageExtraction(BaseModel):
    index: int
    method: str | None
    rooms: int
    error: str | None = None


class ExtractionSummary(BaseModel):
    status: Literal["done", "no_rooms", "partial", "unavailable"]
    message: str
    rooms_found: int
    rooms_flagged: int  # low/medium confidence or with review flags
    pages: list[PageExtraction]
    ran_at: datetime


class BlueprintOut(BaseModel):
    id: str
    project_id: str
    filename: str
    kind: FileKind
    content_type: str
    size_bytes: int
    detected_unit: LengthUnit | None
    warnings: list[WarningOut]
    pages: list[PageOut]
    extraction: ExtractionSummary | None = None
    created_at: datetime


class ExtractionOut(BaseModel):
    blueprint: BlueprintOut
    rooms_added: int
    rooms_replaced: int  # previous untouched auto-extracted rooms from this file
    rooms_kept: int  # rooms from this file the user had edited; never overwritten


class PageUpdate(BaseModel):
    floor: str | None = Field(default=None, max_length=50)
    included: bool | None = None


def blueprint_out(doc: dict) -> BlueprintOut:
    return BlueprintOut(
        id=str(doc["_id"]),
        project_id=str(doc["project_id"]),
        filename=doc["filename"],
        kind=doc["kind"],
        content_type=doc["content_type"],
        size_bytes=doc["size_bytes"],
        detected_unit=doc.get("detected_unit"),
        warnings=doc["warnings"],
        pages=[
            PageOut(
                index=p["index"],
                width=p["width"],
                height=p["height"],
                has_text=p["has_text"],
                floor=p["floor"],
                included=p["included"],
                has_thumbnail=p.get("thumbnail_id") is not None,
                warnings=p["warnings"],
            )
            for p in doc["pages"]
        ],
        extraction=doc.get("extraction"),
        created_at=doc["created_at"],
    )
