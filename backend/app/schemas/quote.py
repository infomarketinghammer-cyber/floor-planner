"""Contractor quotations (PRD 4.19, 4.21): client-ready quotes from an estimate, with margin,
labour and tax, versions and status.

A quote is a frozen snapshot: later changes to the project don't change a quote that was sent.
"Revise" makes a new version from the current project.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.material import DecimalStr

MAX_AMOUNT = 1_000_000_000


class CompanyProfile(BaseModel):
    """The contractor's details shown on quotes. One per user."""

    model_config = ConfigDict(validate_default=True)

    name: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=400)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    website: str = Field(default="", max_length=200)
    tax_id_label: str = Field(default="GSTIN", max_length=20)
    tax_id: str = Field(default="", max_length=40)
    terms: str = Field(
        default="Prices include the materials listed. Quantities are estimates; final quantities "
        "are confirmed on site. 50% advance, balance on completion.",
        max_length=2000,
    )
    validity_days: int = Field(default=30, ge=1, le=365)
    default_margin_pct: DecimalStr = Field(default=Decimal(15), ge=0, le=300)
    quote_prefix: str = Field(default="Q", min_length=1, max_length=10, pattern=r"^[A-Za-z0-9-]+$")
    has_logo: bool = False  # the logo itself is a stored file


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    REJECTED = "rejected"


class QuoteClient(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=400)


LineKind = Literal["material", "extra", "labour", "delivery", "other"]


class QuoteLine(BaseModel):
    kind: LineKind
    description: str
    quantity: DecimalStr
    unit: str  # boxes, m, sq ft, item...
    unit_price: DecimalStr  # what the client pays per unit (margin included)
    amount: DecimalStr
    cost: DecimalStr  # what it costs the contractor (internal, never on the client's copy)
    taxable: bool


class Quote(BaseModel):
    id: str
    project_id: str
    project_name: str
    number: str  # e.g. Q-2026-0007; the same across versions
    version: int
    latest: bool  # false once revised
    status: QuoteStatus
    client: QuoteClient
    margin_pct: DecimalStr
    lines: list[QuoteLine]
    subtotal: DecimalStr
    tax_label: str
    tax_pct: DecimalStr
    tax_amount: DecimalStr
    total: DecimalStr
    cost_total: DecimalStr  # contractor's cost, before tax
    margin_amount: DecimalStr  # subtotal - cost_total
    currency: str
    locale: str
    notes: str | None
    terms: str
    margin_on_labour: bool = False
    extra_lines: list["ExtraLineIn"] = []  # as entered, so a revision keeps them
    valid_until: datetime
    created_at: datetime
    sent_at: datetime | None
    decided_at: datetime | None  # approved or rejected


# --- Requests -----------------------------------------------------------------------------------


class ExtraLineIn(BaseModel):
    """A line added on the quote only, e.g. "Floor levelling" or "Removal of old tiles"."""

    kind: Literal["labour", "delivery", "other"] = "labour"
    description: str = Field(min_length=1, max_length=120)
    quantity: Decimal = Field(default=Decimal(1), gt=0, le=1_000_000)
    unit: str = Field(default="item", max_length=20)
    rate: Decimal = Field(gt=0, le=MAX_AMOUNT)
    taxable: bool = True


class QuoteIn(BaseModel):
    client: QuoteClient
    margin_pct: Decimal | None = Field(default=None, ge=0, le=300)  # None: company default
    margin_on_labour: bool = False  # margin on delivery/labour lines too
    extra_lines: list[ExtraLineIn] = Field(default_factory=list, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)
    terms: str | None = Field(default=None, max_length=2000)  # None: company terms
    validity_days: int | None = Field(default=None, ge=1, le=365)


class QuoteReviseIn(BaseModel):
    """Revise: a new version from the current project. Fields left out are kept."""

    client: QuoteClient | None = None
    margin_pct: Decimal | None = Field(default=None, ge=0, le=300)
    margin_on_labour: bool | None = None
    extra_lines: list[ExtraLineIn] | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)
    terms: str | None = Field(default=None, max_length=2000)
    validity_days: int | None = Field(default=None, ge=1, le=365)


class QuoteStatusIn(BaseModel):
    status: QuoteStatus


class QuoteEmailIn(BaseModel):
    to: EmailStr | None = None  # None: the client's email
    message: str | None = Field(default=None, max_length=1000)


Quote.model_rebuild()
