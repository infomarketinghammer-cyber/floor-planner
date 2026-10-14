"""Teams (PRD 4.18 "team access for contractors and designers"): a contractor's company, whose
members see and work on the team's projects in their role."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, parse_object_id
from app.core.config import get_settings
from app.db.mongo import get_db
from app.services.collab import log_activity
from app.services.email import email_enabled, send_email
from app.services.projects import get_project_or_404

router = APIRouter(tags=["teams"])

TeamRole = Literal["contractor", "designer"]


class TeamMemberOut(BaseModel):
    user_id: str
    name: str
    email: str
    role: str  # owner, contractor, designer


class TeamOut(BaseModel):
    id: str
    name: str
    my_role: str
    members: list[TeamMemberOut]
    invites: list[dict]  # {email, role, invited_at}
    projects: int


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MemberIn(BaseModel):
    email: EmailStr
    role: TeamRole = "contractor"


class RoleIn(BaseModel):
    role: TeamRole


async def _team_out(team: dict, user: dict) -> TeamOut:
    ids = [m["user_id"] for m in team["members"]]
    users = {
        u["_id"]: u
        async for u in get_db().users.find({"_id": {"$in": ids}}, {"name": 1, "email": 1})
    }
    me = next((m for m in team["members"] if m["user_id"] == user["_id"]), None)
    return TeamOut(
        id=str(team["_id"]),
        name=team["name"],
        my_role="owner" if team["owner_id"] == user["_id"] else (me["role"] if me else "none"),
        members=[
            TeamMemberOut(
                user_id=str(m["user_id"]),
                name=users.get(m["user_id"], {}).get("name", "Former member"),
                email=users.get(m["user_id"], {}).get("email", ""),
                role="owner" if m["user_id"] == team["owner_id"] else m["role"],
            )
            for m in team["members"]
        ],
        invites=list(team.get("invites", [])),
        projects=await get_db().projects.count_documents({"team_id": team["_id"]}),
    )


async def _owned_team(user: dict, team_id: str) -> dict:
    team = await get_db().teams.find_one({"_id": parse_object_id(team_id)})
    if team is None or not any(m["user_id"] == user["_id"] for m in team["members"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    if team["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the team's owner can do this.")
    return team


async def invite_email(to: str, inviter: dict, what: str) -> None:
    """Tell an invited person, if email is set up. Inviting works without it."""
    if not email_enabled():
        return
    app_url = get_settings().app_url.rstrip("/")
    text = (
        f"{inviter.get('name') or 'A Floor Planner user'} invited you to {what} on Floor Planner.\n\n"
        "Sign in, or create an account with this email address, to see it."
        + (f"\n\n{app_url}/login" if app_url else "")
    )
    try:
        await send_email(
            to=[to], subject=f"You're invited to {what}", html=f"<p>{text.replace(chr(10), '<br>')}</p>",
            text=text, reply_to=inviter.get("email"),
        )  # fmt: skip
    except Exception:  # noqa: BLE001, S110 - the invitation stands even if the email fails
        pass


@router.get("/teams", response_model=list[TeamOut])
async def my_teams(user: CurrentUser) -> list[TeamOut]:
    return [
        await _team_out(t, user)
        async for t in get_db().teams.find({"members.user_id": user["_id"]})
    ]


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(body: TeamIn, user: CurrentUser) -> TeamOut:
    now = datetime.now(UTC)
    team = {
        "name": body.name.strip(),
        "owner_id": user["_id"],
        "members": [{"user_id": user["_id"], "role": "contractor", "added_at": now}],
        "invites": [],
        "created_at": now,
    }
    team["_id"] = (await get_db().teams.insert_one(team)).inserted_id
    return await _team_out(team, user)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(team_id: str, body: TeamIn, user: CurrentUser) -> TeamOut:
    team = await _owned_team(user, team_id)
    await get_db().teams.update_one({"_id": team["_id"]}, {"$set": {"name": body.name.strip()}})
    team["name"] = body.name.strip()
    return await _team_out(team, user)


@router.post("/teams/{team_id}/members", response_model=TeamOut)
async def add_member(team_id: str, body: MemberIn, user: CurrentUser) -> TeamOut:
    """Add someone who has an account; otherwise invite their email (they join on sign-up)."""
    team = await _owned_team(user, team_id)
    email = str(body.email).lower()
    db = get_db()
    member = await db.users.find_one({"email": email})
    if member and any(m["user_id"] == member["_id"] for m in team["members"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "They're already in the team.")
    if member:
        await db.teams.update_one(
            {"_id": team["_id"]},
            {
                "$push": {
                    "members": {
                        "user_id": member["_id"],
                        "role": body.role,
                        "added_at": datetime.now(UTC),
                    }
                }
            },
        )
    else:
        await db.teams.update_one({"_id": team["_id"]}, {"$pull": {"invites": {"email": email}}})
        await db.teams.update_one(
            {"_id": team["_id"]},
            {
                "$push": {
                    "invites": {"email": email, "role": body.role, "invited_at": datetime.now(UTC)}
                }
            },
        )
    await invite_email(email, user, f"join the team {team['name']}")
    return await _team_out(await db.teams.find_one({"_id": team["_id"]}), user)


@router.patch("/teams/{team_id}/members/{user_id}", response_model=TeamOut)
async def change_role(team_id: str, user_id: str, body: RoleIn, user: CurrentUser) -> TeamOut:
    team = await _owned_team(user, team_id)
    uid = parse_object_id(user_id)
    if uid == team["owner_id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The owner's role can't change.")
    await get_db().teams.update_one(
        {"_id": team["_id"], "members.user_id": uid}, {"$set": {"members.$.role": body.role}}
    )
    return await _team_out(await get_db().teams.find_one({"_id": team["_id"]}), user)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(team_id: str, user_id: str, user: CurrentUser) -> Response:
    """The owner removes someone, or a member leaves."""
    uid = parse_object_id(user_id)
    team = await get_db().teams.find_one(
        {"_id": parse_object_id(team_id), "members.user_id": user["_id"]}
    )
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    if uid != user["_id"] and team["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the team's owner can do this.")
    if uid == team["owner_id"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The owner can't leave; delete the team instead."
        )
    await get_db().teams.update_one({"_id": team["_id"]}, {"$pull": {"members": {"user_id": uid}}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/teams/{team_id}/invites/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(team_id: str, email: str, user: CurrentUser) -> Response:
    team = await _owned_team(user, team_id)
    await get_db().teams.update_one(
        {"_id": team["_id"]}, {"$pull": {"invites": {"email": email.lower()}}}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: str, user: CurrentUser) -> Response:
    """Projects stay with their owners; they just leave the team."""
    team = await _owned_team(user, team_id)
    await get_db().projects.update_many({"team_id": team["_id"]}, {"$unset": {"team_id": ""}})
    await get_db().teams.delete_one({"_id": team["_id"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ProjectTeamIn(BaseModel):
    team_id: str | None  # None: take the project out of its team


@router.put("/projects/{project_id}/team", status_code=status.HTTP_204_NO_CONTENT)
async def set_project_team(project_id: str, body: ProjectTeamIn, user: CurrentUser) -> Response:
    """Share a project with one of your teams (or stop sharing it)."""
    project = await get_project_or_404(user, project_id, "manage")
    if body.team_id is None:
        await get_db().projects.update_one({"_id": project["_id"]}, {"$unset": {"team_id": ""}})
        await log_activity(project["_id"], "Took the project out of its team")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    team = await get_db().teams.find_one(
        {"_id": parse_object_id(body.team_id), "members.user_id": user["_id"]}
    )
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    await get_db().projects.update_one({"_id": project["_id"]}, {"$set": {"team_id": team["_id"]}})
    await log_activity(project["_id"], f"Shared the project with the team {team['name']}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
