"""Public information, no login needed (served by the gateway under /api/public)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import crypto
from app.core.config import get_settings
from app.services.email import email_enabled

router = APIRouter(prefix="/public", tags=["public"])


class PrivacyOut(BaseModel):
    """How this deployment handles uploaded plans (PRD 4.14), read from its real settings so the
    privacy page never promises more than is configured."""

    ai_reading_enabled: bool  # photos and scanned pages are sent to the AI provider
    ai_provider: str | None
    files_encrypted_at_rest: bool
    data_location: str | None
    email_enabled: bool
    email_provider: str | None
    retention: str
    max_upload_mb: int


@router.get("/privacy", response_model=PrivacyOut)
async def privacy() -> PrivacyOut:
    s = get_settings()
    ai = bool(s.anthropic_api_key)
    email = email_enabled()
    return PrivacyOut(
        ai_reading_enabled=ai,
        ai_provider="Anthropic (Claude API)" if ai else None,
        files_encrypted_at_rest=crypto.enabled(),
        data_location=s.data_location or None,
        email_enabled=email,
        email_provider="Resend" if email else None,
        retention="Kept until you delete them",
        max_upload_mb=s.max_upload_mb,
    )
