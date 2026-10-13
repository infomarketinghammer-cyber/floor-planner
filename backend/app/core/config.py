from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "floor_planner"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    admin_email: str | None = None
    admin_password: str | None = None

    # Uploads (PRD 4.1). Limits are starting points, to be tuned with real plans.
    max_upload_mb: int = 25
    max_pdf_pages: int = 50
    max_room_import_rows: int = 500
    # Path to ODAFileConverter(.exe). DWG uploads are rejected with guidance when unset.
    oda_converter_path: str | None = None

    # Vision model for photos and scanned pages (PRD 4.2). Unset key = feature off, with
    # a manual-entry fallback. Text in digital PDFs/DXF never goes to the model.
    anthropic_api_key: str | None = None
    vision_model: str = "claude-opus-5-5"
    vision_effort: str = "high"  # low | medium | high | xhigh | max

    # Emailing the shopping list (PRD export). Sent through Resend; unset key = feature off.
    # The sender must be on a domain verified in Resend, e.g. "Floor Planner <lists@example.com>".
    resend_api_key: str | None = None
    email_from: str | None = None
    max_emails_per_hour: int = 20  # per user, so the feature can't be used to send spam

    # Security and privacy (PRD 4.14). Uploaded plans are encrypted at rest with this key
    # (32 random bytes, base64); see app/core/crypto.py. Keep it secret and backed up: without
    # it, encrypted files can't be read.
    file_encryption_key: str | None = None
    # Shown to users on the privacy page, e.g. "AWS Mumbai (ap-south-1)". Empty: not stated.
    data_location: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
