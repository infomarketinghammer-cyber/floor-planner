"""Guest mode (PRD 4.12, local-first): the project lives in the browser; the server stores nothing.

A guest request carries the project. For the length of that one request, the database, file
storage and current user point at an in-memory sandbox loaded from it, the real endpoint runs
unchanged, and the sandbox's contents go back to the browser. These context variables are only
ever set by the guest dispatcher (app/api/v1/guest.py), never from request data.
"""

from contextvars import ContextVar
from typing import Any, Self

_db: ContextVar[Any | None] = ContextVar("guest_db", default=None)
_files: ContextVar[dict | None] = ContextVar("guest_files", default=None)
_user: ContextVar[dict | None] = ContextVar("guest_user", default=None)

AI_SIGN_IN = "Sign in to read photos and scanned pages with AI. Digital PDFs and CAD files work without an account."


def is_guest() -> bool:
    return _user.get() is not None


def guest_db():
    return _db.get()


def guest_files() -> dict | None:
    return _files.get()


def guest_user() -> dict | None:
    return _user.get()


class GuestScope:
    """Activate the sandbox: `with GuestScope(db, files, user): ...`."""

    def __init__(self, db, files: dict, user: dict):
        self._values = (db, files, user)
        self._tokens: tuple = ()

    def __enter__(self) -> Self:
        db, files, user = self._values
        self._tokens = (_db.set(db), _files.set(files), _user.set(user))
        return self

    def __exit__(self, *exc) -> None:
        for var, token in zip((_db, _files, _user), self._tokens, strict=True):
            var.reset(token)
