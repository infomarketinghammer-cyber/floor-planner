"""Sending email through Resend (https://resend.com/docs/api-reference/emails/send-email)."""

import httpx

from app.core.config import get_settings

RESEND_URL = "https://api.resend.com/emails"


class EmailNotConfigured(Exception):
    pass


class EmailError(Exception):
    """Resend refused or couldn't be reached. The message is safe to show the user."""


def email_enabled() -> bool:
    s = get_settings()
    return bool(s.resend_api_key and s.email_from)


async def send_email(
    *,
    to: list[str],
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
) -> str:
    """Send one email; returns Resend's message id. `attachments` are {filename, content}
    with base64 content."""
    s = get_settings()
    if not (s.resend_api_key and s.email_from):
        raise EmailNotConfigured
    payload: dict = {"from": s.email_from, "to": to, "subject": subject, "html": html, "text": text}
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = attachments
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {s.resend_api_key}"},
            )
    except httpx.HTTPError:
        raise EmailError("The email service couldn't be reached. Try again in a minute.") from None
    if response.status_code >= 400:
        try:
            detail = response.json().get("message")
        except ValueError:
            detail = None
        raise EmailError(f"The email wasn't sent: {detail or response.reason_phrase}.")
    return response.json().get("id", "")
