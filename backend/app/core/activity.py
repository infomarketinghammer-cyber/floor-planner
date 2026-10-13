"""What the current request is doing, in words, for the project history and activity log
(PRD 4.12 history, 4.21 "who edited what").

A router dependency records the matched route; anything that saves a change reads it here, so
the label doesn't have to be passed through every endpoint.
"""

from contextvars import ContextVar

from fastapi import Request

from app.services.access import set_request_method

_action: ContextVar[str | None] = ContextVar("action", default=None)
_user: ContextVar[dict | None] = ContextVar("acting_user", default=None)

# Route function name -> what the user did.
LABELS: dict[str, str] = {
    "add_room": "Added a room",
    "update_room": "Edited a room",
    "confirm_rooms": "Confirmed rooms",
    "restore_rooms": "Undo or redo",
    "set_plan_unit": "Set the plan unit",
    "delete_room": "Deleted a room",
    "import_rooms": "Imported a room list",
    "set_default_material": "Changed the project tile settings",
    "set_rooms_material": "Changed room tile settings",
    "set_exclusions": "Changed untiled areas",
    "set_room_walls": "Changed walls and doors",
    "set_room_parts": "Changed a room's shape",
    "set_extras_settings": "Changed walls, skirting and sundries settings",
    "set_cost_settings": "Changed cost settings",
    "extract_rooms": "Read rooms from a plan",
    "upload_file": "Uploaded a plan",
    "delete_file": "Deleted a plan",
    "update_project": "Renamed the project",
    "apply": "Used a compared option",
    "restore_version": "Restored an earlier version",
    "import_project": "Imported a backup",
    "add_scenario": "Added an option to compare",
    "create_quote": "Made a quote",
    "revise_quote": "Revised a quote",
    "apply_tile_updates": "Updated tiles from the library",
    "set_project_team": "Changed the project's team",
}


async def track_action(request: Request) -> None:
    """Router dependency: remember which route is running."""
    set_request_method(request.method)
    route = request.scope.get("route")
    name = getattr(route, "name", None)
    _action.set(LABELS.get(name, name.replace("_", " ").capitalize() if name else None))


def current_action(default: str = "Changed the project") -> str:
    return _action.get() or default


def set_acting_user(user: dict) -> None:
    """Called once the request's user is known (deps.get_current_user)."""
    _user.set(user)


def acting_user() -> dict | None:
    return _user.get()
