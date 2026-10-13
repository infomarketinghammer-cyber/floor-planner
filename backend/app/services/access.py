"""Who can do what on a project (PRD 4.18 teams, 4.21 role-based views).

Roles on a project:
- owner: the project's owner (admins act as owners, for support): everything
- contractor: a member of the project's team: edit, costs, quotes, exports
- designer: a team member who edits rooms and materials, without costs or quotes
- homeowner: a client invited to the project: view, comment and approve

A user reaches a project as its owner, through the project's team, or as a project member.
"""

from contextvars import ContextVar
from typing import Literal

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.guest import is_guest
from app.db.mongo import get_db

ProjectRole = Literal["owner", "contractor", "designer", "homeowner"]
Need = Literal["view", "comment", "edit", "cost", "manage"]
ROLES: tuple[ProjectRole, ...] = ("owner", "contractor", "designer", "homeowner")

ALLOWED: dict[Need, set[str]] = {
    "view": set(ROLES),
    "comment": set(ROLES),
    "edit": {"owner", "contractor", "designer"},
    "cost": {"owner", "contractor"},
    "manage": {"owner"},
}
NEED_MESSAGES: dict[Need, str] = {
    "view": "You don't have access to this project.",
    "comment": "You don't have access to this project.",
    "edit": "Your role on this project can view and comment, but not change it.",
    "cost": "Your role on this project doesn't include costs or quotes.",
    "manage": "Only the project's owner can do this.",
}

_role: ContextVar[str | None] = ContextVar("project_role", default=None)
_method: ContextVar[str] = ContextVar("request_method", default="GET")


def set_request_method(method: str) -> None:
    _method.set(method)


def default_need() -> Need:
    return "view" if _method.get() in ("GET", "HEAD") else "edit"


def current_role() -> str | None:
    return _role.get()


def can_see_costs() -> bool:
    """Whether this request may see prices and costs (owner and contractor only). Outside a
    project request (no role recorded) there's nothing to hide."""
    role = _role.get()
    return role is None or role in ALLOWED["cost"]


async def user_team_ids(user: dict) -> dict[ObjectId, str]:
    """The user's teams and their role in each."""
    out: dict[ObjectId, str] = {}
    async for team in get_db().teams.find(
        {"members.user_id": user["_id"]}, {"members": 1, "owner_id": 1}
    ):
        member = next(m for m in team["members"] if m["user_id"] == user["_id"])
        out[team["_id"]] = "owner" if team.get("owner_id") == user["_id"] else member["role"]
    return out


async def project_role(
    user: dict, project: dict, teams: dict[ObjectId, str] | None = None
) -> str | None:
    if project.get("owner_id") == user["_id"] or is_guest():
        return "owner"
    if user.get("role") == "admin":
        return "owner"
    if project.get("team_id"):
        teams = teams if teams is not None else await user_team_ids(user)
        team_role = teams.get(project["team_id"])
        if team_role is not None:
            # A team's owner manages its projects; members work on them in their role.
            return "contractor" if team_role == "owner" else team_role
    member = next((m for m in project.get("members", []) if m.get("user_id") == user["_id"]), None)
    return member["role"] if member else None


async def visible_projects_query(user: dict) -> dict:
    """Projects the user can see: own, their teams', and ones they were invited to."""
    if user.get("role") == "admin":
        return {}
    teams = await user_team_ids(user)
    return {
        "$or": [
            {"owner_id": user["_id"]},
            {"team_id": {"$in": list(teams)}},
            {"members.user_id": user["_id"]},
        ]
    }


async def check_access(user: dict, project: dict, need: Need | None) -> str:
    """The user's role on the project, or 404 (no access) / 403 (role can't do this)."""
    role = await project_role(user, project)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    need = need or default_need()
    if role not in ALLOWED[need]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NEED_MESSAGES[need])
    _role.set(role)
    return role


def require_costs() -> None:
    """For changes that touch prices inside an otherwise "edit" request."""
    if not can_see_costs():
        raise HTTPException(status.HTTP_403_FORBIDDEN, NEED_MESSAGES["cost"])
