from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class Role(StrEnum):
    CONTRACTOR = "contractor"
    ADMIN = "admin"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company: str | None = Field(default=None, max_length=150)


class LoginRequest(BaseModel):
    # Plain str: format is validated at registration; login only needs an exact match.
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UnitSystem(StrEnum):
    IMPERIAL = "imperial"  # feet, sq ft
    METRIC = "metric"  # metres, m²


class Preferences(BaseModel):
    """Display preferences (PRD 4.4). Stored values are always exact millimetres."""

    unit_system: UnitSystem = UnitSystem.IMPERIAL


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    company: str | None = None
    role: Role
    is_active: bool
    preferences: Preferences = Field(default_factory=Preferences)
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserUpdate(BaseModel):
    """Admin-only changes to a user account."""

    role: Role | None = None
    is_active: bool | None = None


def user_out(doc: dict) -> UserOut:
    return UserOut(
        id=str(doc["_id"]),
        name=doc["name"],
        email=doc["email"],
        company=doc.get("company"),
        role=doc["role"],
        is_active=doc["is_active"],
        preferences=Preferences.model_validate(doc.get("preferences") or {}),
        created_at=doc["created_at"],
    )
