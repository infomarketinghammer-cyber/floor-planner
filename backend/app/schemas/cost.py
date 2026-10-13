"""Cost estimation (PRD 4.10): material cost per room, extra cost lines, tax and a budget.

Prices live on the material settings (PRD 4.6). Everything here is money: amounts are exact
decimals, sent as strings, rounded to 2 places. Currency and number format are display
choices, so the server only stores the codes and the browser formats them.
"""

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.material import DecimalStr, Price

MAX_AMOUNT = 1_000_000_000


class LineKind(StrEnum):
    DELIVERY = "delivery"
    LABOUR = "labour"
    OTHER = "other"


class LineBasis(StrEnum):
    FIXED = "fixed"  # one amount for the whole project
    SQFT = "sqft"  # amount per sq ft of area to tile
    SQM = "sqm"  # amount per m² of area to tile
    BOX = "box"  # amount per box bought


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class CostLine(BaseModel):
    """An extra line on top of the tiles: delivery, labour, or anything else."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=40)
    kind: LineKind = LineKind.OTHER
    label: str = Field(min_length=1, max_length=60)
    amount: DecimalStr = Field(gt=0, le=MAX_AMOUNT)
    basis: LineBasis = LineBasis.FIXED
    taxable: bool = True


class CostSettings(BaseModel):
    """Project-wide cost settings. All optional: a project with none just shows no costs."""

    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")  # ISO 4217
    locale: str = Field(default="en-IN", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")
    tax_label: str = Field(default="Tax", min_length=1, max_length=30)  # GST, VAT, Sales tax...
    tax_pct: DecimalStr = Field(default=0, ge=0, le=100)
    tax_materials: bool = True  # tax applies to the tiles (lines choose for themselves)
    lines: list[CostLine] = Field(default_factory=list, max_length=20)
    budget: DecimalStr | None = Field(default=None, gt=0, le=MAX_AMOUNT)  # target for the total


# --- Output -------------------------------------------------------------------------------------


class RoomCostOut(BaseModel):
    room_id: str
    price: Price | None  # the price this room uses: its own, else the project default
    price_per_box: DecimalStr | None  # the price worked out per box, whatever the basis
    cost: DecimalStr | None  # boxes × price per box; None when the room has no price


class CostLineOut(BaseModel):
    id: str
    kind: LineKind
    label: str
    basis: LineBasis
    rate: DecimalStr  # the amount as entered
    quantity: DecimalStr | None  # sq ft, m² or boxes it was multiplied by; None for fixed
    amount: DecimalStr
    taxable: bool


class TaxOut(BaseModel):
    label: str
    pct: DecimalStr
    base: DecimalStr  # what the tax is charged on
    amount: DecimalStr


class BudgetOut(BaseModel):
    target: DecimalStr
    remaining: DecimalStr  # negative when over budget
    used_pct: DecimalStr
    status: Literal["under", "near", "over"]


class CostOut(BaseModel):
    has_prices: bool  # false: the UI hides the cost columns
    priced_rooms: int
    unpriced_rooms: int
    rooms: list[RoomCostOut]
    materials: DecimalStr | None  # sum of the room costs; None when no room has a price
    lines: list[CostLineOut]
    tax: TaxOut | None
    total: DecimalStr
    budget: BudgetOut | None
    warnings: list[str]
