"""Exports: PDF report, Excel workbook, shopping list PDF, and emailing the shopping list.

Every export is made from the current rooms, so it always matches the app. Exporting marks
the project as exported; the next room change moves it back (services/projects.save_rooms).
"""

import asyncio
import base64
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.db.mongo import get_db
from app.exports.data import ExportData, NotReady, export_data
from app.exports.excel import render_workbook
from app.exports.formatting import AreaUnit
from app.exports.pdf import render_order_list, render_report, render_shopping_list
from app.exports.shopping import shopping_html, shopping_text
from app.schemas.project import ProjectStatus
from app.services.access import can_see_costs
from app.services.email import EmailError, EmailNotConfigured, email_enabled, send_email
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/exports", tags=["exports"])

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

AreaQuery = Annotated[Literal["sqft", "sqm"] | None, Query()]


class ExportOptionsOut(BaseModel):
    email_enabled: bool


class ShoppingEmailIn(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=5)
    message: str | None = Field(default=None, max_length=1000)
    attach_pdf: bool = True


class ShoppingEmailOut(BaseModel):
    sent_to: list[str]


def _area_unit(user: dict, requested: AreaUnit | None) -> AreaUnit:
    if requested:
        return requested
    system = (user.get("preferences") or {}).get("unit_system")
    return "sqm" if system == "metric" else "sqft"


async def _data(user: dict, project_id: str, area_unit: AreaUnit | None) -> tuple[dict, ExportData]:
    project = await get_project_or_404(user, project_id)
    try:
        return project, export_data(project, _area_unit(user, area_unit), can_see_costs())
    except NotReady as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Nothing to export yet. " + " ".join(e.blockers)
        ) from None


async def _mark_exported(project: dict) -> None:
    await get_db().projects.update_one(
        {"_id": project["_id"]},
        {"$set": {"status": ProjectStatus.EXPORTED.value, "last_exported_at": datetime.now(UTC)}},
    )


def _filename(project_name: str, suffix: str) -> str:
    base = re.sub(r"[^\w\- ]+", "", project_name).strip() or "project"
    return f"{base[:80]} - {suffix}"


def _download(content: bytes, media_type: str, filename: str) -> Response:
    # Plain-ASCII fallback for old clients: "résidence" becomes "residence".
    ascii_name = (
        unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode() or "export"
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/options", response_model=ExportOptionsOut)
async def export_options(project_id: str, user: CurrentUser) -> ExportOptionsOut:
    await get_project_or_404(user, project_id)
    return ExportOptionsOut(email_enabled=email_enabled())


@router.get("/report.pdf")
async def report_pdf(project_id: str, user: CurrentUser, area_unit: AreaQuery = None) -> Response:
    """Master table, totals, shopping list, costs, assumptions and the 'estimate only' notice."""
    project, data = await _data(user, project_id, area_unit)
    content = await asyncio.to_thread(render_report, data)
    await _mark_exported(project)
    return _download(content, PDF, _filename(data.project_name, "tile estimate.pdf"))


@router.get("/estimate.xlsx")
async def estimate_xlsx(
    project_id: str, user: CurrentUser, area_unit: AreaQuery = None
) -> Response:
    """Rooms, shopping list, costs and assumptions, with live formulas."""
    project, data = await _data(user, project_id, area_unit)
    content = await asyncio.to_thread(render_workbook, data)
    await _mark_exported(project)
    return _download(content, XLSX, _filename(data.project_name, "tile estimate.xlsx"))


@router.get("/shopping-list.pdf")
async def shopping_list_pdf(
    project_id: str, user: CurrentUser, area_unit: AreaQuery = None
) -> Response:
    project, data = await _data(user, project_id, area_unit)
    content = await asyncio.to_thread(render_shopping_list, data)
    await _mark_exported(project)
    return _download(content, PDF, _filename(data.project_name, "shopping list.pdf"))


@router.get("/order-list.pdf")
async def order_list_pdf(
    project_id: str, user: CurrentUser, area_unit: AreaQuery = None
) -> Response:
    """The shopping list grouped by vendor (PRD 4.19)."""
    project, data = await _data(user, project_id, area_unit)
    content = await asyncio.to_thread(render_order_list, data)
    await _mark_exported(project)
    return _download(content, PDF, _filename(data.project_name, "order list.pdf"))


@router.post("/shopping-list/email", response_model=ShoppingEmailOut)
async def email_shopping_list(
    project_id: str, body: ShoppingEmailIn, user: CurrentUser
) -> ShoppingEmailOut:
    """Send the shopping list (and a PDF copy) through Resend. Replies go to the sender."""
    if not email_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Email isn't set up on this server. Download the shopping list instead.",
        )
    since = datetime.now(UTC) - timedelta(hours=1)
    sent = await get_db().email_log.count_documents(
        {"user_id": user["_id"], "sent_at": {"$gte": since}}
    )
    if sent >= get_settings().max_emails_per_hour:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You've sent a lot of emails in the last hour. Try again later.",
        )

    project, data = await _data(user, project_id, None)
    message = (body.message or "").strip() or None
    sender = user.get("name") or user["email"]
    attachments = None
    if body.attach_pdf:
        pdf = await asyncio.to_thread(render_shopping_list, data)
        attachments = [
            {
                "filename": _filename(data.project_name, "shopping list.pdf"),
                "content": base64.b64encode(pdf).decode(),
            }
        ]
    recipients = list(dict.fromkeys(str(a).lower() for a in body.to))
    try:
        await send_email(
            to=recipients,
            subject=f"Tile shopping list: {data.project_name}",
            html=shopping_html(data, sender, message),
            text=shopping_text(data, message),
            reply_to=user["email"],
            attachments=attachments,
        )
    except EmailNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Email isn't set up.") from None
    except EmailError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None

    await get_db().email_log.insert_one(
        {"user_id": user["_id"], "project_id": project["_id"], "sent_at": datetime.now(UTC)}
    )
    await _mark_exported(project)
    return ShoppingEmailOut(sent_to=recipients)
