"""Contractor quotations (PRD 4.19): company details, quotes with versions and status, the
client PDF, and emailing it to the client."""

import asyncio
import base64
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from PIL import Image, UnidentifiedImageError
from pymongo import DESCENDING, ReturnDocument

from app.api.deps import CurrentUser
from app.db import storage
from app.db.mongo import get_db
from app.exports.formatting import format_money
from app.exports.quote_pdf import render_quote
from app.schemas.quote import (
    CompanyProfile,
    ExtraLineIn,
    Quote,
    QuoteEmailIn,
    QuoteIn,
    QuoteReviseIn,
    QuoteStatus,
    QuoteStatusIn,
)
from app.services.cost import build_cost, cost_settings
from app.services.email import EmailError, email_enabled, send_email
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import project_default
from app.services.projects import get_project_or_404, project_scope
from app.services.quotes import NotQuotable, quote_lines, totals
from app.services.review import review_state

router = APIRouter(tags=["quotes"])

MAX_LOGO_BYTES = 1_000_000


# --- Company details ----------------------------------------------------------------------------


def company_of(user: dict) -> CompanyProfile:
    profile = CompanyProfile.model_validate(user.get("company_profile") or {})
    if not profile.name and user.get("company"):
        profile.name = user["company"]  # from registration
    profile.has_logo = bool(user.get("company_logo_id"))
    return profile


@router.get("/users/me/company", response_model=CompanyProfile)
async def get_company(user: CurrentUser) -> CompanyProfile:
    return company_of(user)


@router.put("/users/me/company", response_model=CompanyProfile)
async def set_company(body: CompanyProfile, user: CurrentUser) -> CompanyProfile:
    data = body.model_dump(exclude={"has_logo"})
    doc = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"company_profile": data}},
        return_document=ReturnDocument.AFTER,
    )
    return company_of(doc)


@router.put("/users/me/company/logo", response_model=CompanyProfile)
async def set_logo(file: UploadFile, user: CurrentUser) -> CompanyProfile:
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The logo must be under 1 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        fmt = img.format
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a PNG or JPEG image."
        ) from None
    if fmt not in ("PNG", "JPEG"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a PNG or JPEG image.")
    file_id = await storage.put(data, f"logo.{fmt.lower()}", f"image/{fmt.lower()}", kind="logo")
    old = user.get("company_logo_id")
    doc = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"company_logo_id": file_id}},
        return_document=ReturnDocument.AFTER,
    )
    await storage.delete(old)
    return company_of(doc)


@router.delete("/users/me/company/logo", response_model=CompanyProfile)
async def delete_logo(user: CurrentUser) -> CompanyProfile:
    await storage.delete(user.get("company_logo_id"))
    doc = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$unset": {"company_logo_id": ""}},
        return_document=ReturnDocument.AFTER,
    )
    return company_of(doc)


@router.get("/users/me/company/logo")
async def get_logo(user: CurrentUser) -> Response:
    if not user.get("company_logo_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    data = await storage.get(user["company_logo_id"])
    media = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=300"})


# --- Quotes -------------------------------------------------------------------------------------


def _quote(doc: dict) -> Quote:
    return Quote.model_validate(
        {**doc, "id": str(doc["_id"]), "project_id": str(doc["project_id"])}
    )


async def _owner(project: dict) -> dict:
    """Quotes carry the project owner's company details, even when an admin makes them."""
    return await get_db().users.find_one({"_id": project["owner_id"]}) or {}


async def _next_number(owner_id: ObjectId, prefix: str) -> str:
    year = datetime.now(UTC).year
    counter = await get_db().counters.find_one_and_update(
        {"_id": f"quote:{owner_id}:{year}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"{prefix}-{year}-{counter['seq']:04d}"


def _build(project: dict, margin: Decimal, margin_on_labour: bool, extra) -> dict:
    state = review_state(project)
    default = project_default(project)
    extras = extras_settings(project)
    estimate = build_estimate(state, default, extras)
    settings = cost_settings(project)
    cost = build_cost(state, default, estimate, settings, extras)
    try:
        lines = quote_lines(estimate, cost, settings, margin, margin_on_labour, extra)
    except NotQuotable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    tax_pct = settings.tax_pct if settings.tax_pct > 0 else Decimal(0)
    return {
        "lines": [line.model_dump() for line in lines],
        "tax_label": settings.tax_label,
        "tax_pct": str(tax_pct),
        "currency": settings.currency,
        "locale": settings.locale,
        **{k: str(v) for k, v in totals(lines, tax_pct).items()},
    }


async def _quote_or_404(user: dict, quote_id: str) -> tuple[dict, dict]:
    try:
        oid = ObjectId(quote_id)
    except Exception:  # noqa: BLE001 - malformed id: not found
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found") from None
    doc = await get_db().quotes.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found")
    project = await get_project_or_404(user, str(doc["project_id"]))
    return doc, project


@router.get("/projects/{project_id}/quotes", response_model=list[Quote])
async def project_quotes(project_id: str, user: CurrentUser) -> list[Quote]:
    project = await get_project_or_404(user, project_id)
    cursor = get_db().quotes.find({"project_id": project["_id"]}).sort("created_at", DESCENDING)
    return [_quote(d) async for d in cursor]


@router.post(
    "/projects/{project_id}/quotes", response_model=Quote, status_code=status.HTTP_201_CREATED
)
async def create_quote(project_id: str, body: QuoteIn, user: CurrentUser) -> Quote:
    """A new quote (version 1, a new number) from the project as it is now."""
    project = await get_project_or_404(user, project_id)
    owner = await _owner(project)
    company = company_of(owner)
    margin = body.margin_pct if body.margin_pct is not None else company.default_margin_pct
    built = _build(project, margin, body.margin_on_labour, body.extra_lines)
    now = datetime.now(UTC)
    doc = {
        "project_id": project["_id"],
        "owner_id": project["owner_id"],
        "created_by": user["_id"],
        "project_name": project.get("name") or "Project",
        "number": await _next_number(project["owner_id"], company.quote_prefix),
        "version": 1,
        "latest": True,
        "status": QuoteStatus.DRAFT.value,
        "client": body.client.model_dump(),
        "margin_pct": str(margin),
        "margin_on_labour": body.margin_on_labour,
        "extra_lines": [e.model_dump(mode="json") for e in body.extra_lines],
        "notes": (body.notes or "").strip() or None,
        "terms": body.terms if body.terms is not None else company.terms,
        "valid_until": now + timedelta(days=body.validity_days or company.validity_days),
        "created_at": now,
        "sent_at": None,
        "decided_at": None,
        **built,
    }
    result = await get_db().quotes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _quote(doc)


@router.post("/quotes/{quote_id}/revise", response_model=Quote, status_code=status.HTTP_201_CREATED)
async def revise_quote(quote_id: str, body: QuoteReviseIn, user: CurrentUser) -> Quote:
    """A new version of a quote from the project as it is now; the old version is kept."""
    old, project = await _quote_or_404(user, quote_id)
    latest = await get_db().quotes.find_one(
        {"project_id": old["project_id"], "number": old["number"]}, sort=[("version", DESCENDING)]
    )
    company = company_of(await _owner(project))
    margin = body.margin_pct if body.margin_pct is not None else Decimal(old["margin_pct"])
    on_labour = (
        body.margin_on_labour
        if body.margin_on_labour is not None
        else old.get("margin_on_labour", False)
    )
    extra = (
        body.extra_lines
        if body.extra_lines is not None
        else [ExtraLineIn.model_validate(e) for e in old.get("extra_lines", [])]
    )
    built = _build(project, margin, on_labour, extra)
    now = datetime.now(UTC)
    doc = {
        **{k: v for k, v in old.items() if k != "_id"},
        "version": latest["version"] + 1,
        "latest": True,
        "status": QuoteStatus.DRAFT.value,
        "client": body.client.model_dump() if body.client else old["client"],
        "margin_pct": str(margin),
        "margin_on_labour": on_labour,
        "extra_lines": [e.model_dump(mode="json") for e in extra],
        "notes": body.notes if body.notes is not None else old.get("notes"),
        "terms": body.terms if body.terms is not None else old["terms"],
        "valid_until": now + timedelta(days=body.validity_days or company.validity_days),
        "created_at": now,
        "created_by": user["_id"],
        "project_name": project.get("name") or old["project_name"],
        "sent_at": None,
        "decided_at": None,
        **built,
    }
    await get_db().quotes.update_many(
        {"project_id": old["project_id"], "number": old["number"]}, {"$set": {"latest": False}}
    )
    result = await get_db().quotes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _quote(doc)


@router.patch("/quotes/{quote_id}/status", response_model=Quote)
async def set_quote_status(quote_id: str, body: QuoteStatusIn, user: CurrentUser) -> Quote:
    doc, _ = await _quote_or_404(user, quote_id)
    now = datetime.now(UTC)
    update: dict = {"status": body.status.value}
    if body.status == QuoteStatus.SENT and not doc.get("sent_at"):
        update["sent_at"] = now
    if body.status in (QuoteStatus.APPROVED, QuoteStatus.REJECTED):
        update["decided_at"] = now
        update.setdefault("sent_at", doc.get("sent_at") or now)
    if body.status == QuoteStatus.DRAFT:
        update.update(sent_at=None, decided_at=None)
    doc = await get_db().quotes.find_one_and_update(
        {"_id": doc["_id"]}, {"$set": update}, return_document=ReturnDocument.AFTER
    )
    return _quote(doc)


@router.delete("/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(quote_id: str, user: CurrentUser) -> Response:
    """Only drafts can be deleted: a quote a client has seen stays on record."""
    doc, _ = await _quote_or_404(user, quote_id)
    if doc["status"] != QuoteStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft quotes can be deleted.")
    await get_db().quotes.delete_one({"_id": doc["_id"]})
    if doc.get("latest"):  # the previous version becomes the latest again
        prev = await get_db().quotes.find_one(
            {"project_id": doc["project_id"], "number": doc["number"]},
            sort=[("version", DESCENDING)],
        )
        if prev:
            await get_db().quotes.update_one({"_id": prev["_id"]}, {"$set": {"latest": True}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _pdf(doc: dict, project: dict) -> tuple[bytes, str]:
    owner = await _owner(project)
    logo = await storage.get(owner["company_logo_id"]) if owner.get("company_logo_id") else None
    quote = _quote(doc)
    content = await asyncio.to_thread(render_quote, quote, company_of(owner), logo)
    suffix = f" v{quote.version}" if quote.version > 1 else ""
    return content, f"Quotation {quote.number}{suffix}.pdf"


@router.get("/quotes/{quote_id}/pdf")
async def quote_pdf(quote_id: str, user: CurrentUser) -> Response:
    doc, project = await _quote_or_404(user, quote_id)
    content, filename = await _pdf(doc, project)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/quotes/{quote_id}/email", response_model=Quote)
async def email_quote(quote_id: str, body: QuoteEmailIn, user: CurrentUser) -> Quote:
    """Email the quote PDF to the client (Resend); marks it sent. Replies go to the sender."""
    if not email_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Email isn't set up on this server."
        )
    doc, project = await _quote_or_404(user, quote_id)
    to = str(body.to or doc["client"].get("email") or "")
    if not to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Add the client's email address."
        )
    content, filename = await _pdf(doc, project)
    quote = _quote(doc)
    company = company_of(await _owner(project))
    sender = company.name or user.get("name") or user["email"]
    total = format_money(quote.total, quote.currency, quote.locale)
    message = (body.message or "").strip()
    text = (
        f"Dear {quote.client.name},\n\n"
        + (f"{message}\n\n" if message else "")
        + f"Please find attached quotation {quote.number} for {quote.project_name}, "
        f"total {total}, valid until {quote.valid_until:%d %b %Y}.\n\n{sender}"
    )
    html = "<p>" + "</p><p>".join(p.replace("\n", "<br>") for p in text.split("\n\n")) + "</p>"
    try:
        await send_email(
            to=[to],
            subject=f"Quotation {quote.number} from {sender}",
            html=html,
            text=text,
            reply_to=company.email or user["email"],
            attachments=[{"filename": filename, "content": base64.b64encode(content).decode()}],
        )
    except EmailError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    now = datetime.now(UTC)
    doc = await get_db().quotes.find_one_and_update(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": QuoteStatus.SENT.value if doc["status"] == "draft" else doc["status"],
                "sent_at": doc.get("sent_at") or now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return _quote(doc)


@router.get("/quotes", response_model=list[Quote])
async def my_quotes(user: CurrentUser) -> list[Quote]:
    """Latest version of every quote the user can see (for the business dashboard)."""
    project_ids = [p["_id"] async for p in get_db().projects.find(project_scope(user), {"_id": 1})]
    cursor = (
        get_db()
        .quotes.find({"project_id": {"$in": project_ids}, "latest": True})
        .sort("created_at", DESCENDING)
    )
    return [_quote(d) async for d in cursor]
