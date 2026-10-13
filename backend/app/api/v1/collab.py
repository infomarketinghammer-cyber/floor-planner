"""Working together on a project (PRD 4.18): people and their roles, comments, approval of the
estimate, read-only share links, and the activity log ("who edited what", PRD 4.21)."""

import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from pymongo import DESCENDING

from app.api.deps import CurrentUser, parse_object_id
from app.api.v1.teams import invite_email
from app.db.mongo import get_db
from app.services.access import current_role
from app.services.collab import log_activity
from app.services.history import version_metrics
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}", tags=["collaboration"])

MemberRole = Literal["contractor", "designer", "homeowner"]


# --- People -------------------------------------------------------------------------------------


class PersonOut(BaseModel):
    user_id: str | None
    name: str
    email: str
    role: str
    via: Literal["owner", "team", "project", "invite"]


class PeopleOut(BaseModel):
    my_role: str
    team: dict | None  # {id, name}
    people: list[PersonOut]


class MemberIn(BaseModel):
    email: EmailStr
    role: MemberRole = "homeowner"


@router.get("/people", response_model=PeopleOut)
async def people(project_id: str, user: CurrentUser) -> PeopleOut:
    project = await get_project_or_404(user, project_id)
    db = get_db()
    out: list[PersonOut] = []
    owner = await db.users.find_one({"_id": project["owner_id"]}, {"name": 1, "email": 1})
    if owner:
        out.append(
            PersonOut(
                user_id=str(owner["_id"]),
                name=owner["name"],
                email=owner["email"],
                role="owner",
                via="owner",
            )
        )
    team = await db.teams.find_one({"_id": project["team_id"]}) if project.get("team_id") else None
    if team:
        ids = [m["user_id"] for m in team["members"] if m["user_id"] != project["owner_id"]]
        users = {
            u["_id"]: u async for u in db.users.find({"_id": {"$in": ids}}, {"name": 1, "email": 1})
        }
        for m in team["members"]:
            if m["user_id"] in users:
                u = users[m["user_id"]]
                role = "contractor" if m["user_id"] == team["owner_id"] else m["role"]
                out.append(
                    PersonOut(
                        user_id=str(u["_id"]),
                        name=u["name"],
                        email=u["email"],
                        role=role,
                        via="team",
                    )
                )
    members = project.get("members", [])
    users = {
        u["_id"]: u
        async for u in db.users.find(
            {"_id": {"$in": [m["user_id"] for m in members]}}, {"name": 1, "email": 1}
        )
    }
    for m in members:
        if m["user_id"] in users:
            u = users[m["user_id"]]
            out.append(
                PersonOut(
                    user_id=str(u["_id"]),
                    name=u["name"],
                    email=u["email"],
                    role=m["role"],
                    via="project",
                )
            )
    for i in project.get("invites", []):
        out.append(
            PersonOut(user_id=None, name="Invited", email=i["email"], role=i["role"], via="invite")
        )
    return PeopleOut(
        my_role=current_role() or "owner",
        team={"id": str(team["_id"]), "name": team["name"]} if team else None,
        people=out,
    )


@router.post("/members", response_model=PeopleOut)
async def add_member(project_id: str, body: MemberIn, user: CurrentUser) -> PeopleOut:
    """Invite someone to this project: a client (homeowner) to view, comment and approve, or a
    designer or contractor to work on it. People without an account join when they sign up."""
    project = await get_project_or_404(user, project_id, "manage")
    db = get_db()
    email = str(body.email).lower()
    member = await db.users.find_one({"email": email})
    if member and (
        member["_id"] == project["owner_id"]
        or any(m["user_id"] == member["_id"] for m in project.get("members", []))
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "They already have access.")
    now = datetime.now(UTC)
    if member:
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$push": {"members": {"user_id": member["_id"], "role": body.role, "added_at": now}}},
        )
    else:
        await db.projects.update_one(
            {"_id": project["_id"]}, {"$pull": {"invites": {"email": email}}}
        )
        await db.projects.update_one(
            {"_id": project["_id"]},
            {"$push": {"invites": {"email": email, "role": body.role, "invited_at": now}}},
        )
    await log_activity(project["_id"], f"Invited {email} as {body.role}")
    await invite_email(email, user, f"the project {project.get('name', '')}")
    return await people(project_id, user)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(project_id: str, user_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id, "manage")
    await get_db().projects.update_one(
        {"_id": project["_id"]}, {"$pull": {"members": {"user_id": parse_object_id(user_id)}}}
    )
    await log_activity(project["_id"], "Removed someone from the project")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/invites/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(project_id: str, email: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id, "manage")
    await get_db().projects.update_one(
        {"_id": project["_id"]}, {"$pull": {"invites": {"email": email.lower()}}}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Comments -----------------------------------------------------------------------------------


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    room_id: str | None = None  # about one room, or the whole estimate


class CommentOut(BaseModel):
    id: str
    user_id: str | None
    user_name: str
    role: str
    text: str
    room_id: str | None
    room_name: str | None
    resolved: bool
    at: datetime
    mine: bool


def _comment_out(c: dict, user: dict) -> CommentOut:
    return CommentOut(
        id=str(c["_id"]), user_id=str(c["user_id"]) if c.get("user_id") else None, user_name=c["user_name"],
        role=c["role"], text=c["text"], room_id=c.get("room_id"), room_name=c.get("room_name"),
        resolved=c.get("resolved", False), at=c["at"], mine=c.get("user_id") == user["_id"],
    )  # fmt: skip


@router.get("/comments", response_model=list[CommentOut])
async def comments(project_id: str, user: CurrentUser) -> list[CommentOut]:
    project = await get_project_or_404(user, project_id)
    cursor = get_db().comments.find({"project_id": project["_id"]}).sort("at", 1)
    return [_comment_out(c, user) async for c in cursor]


@router.post("/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(project_id: str, body: CommentIn, user: CurrentUser) -> CommentOut:
    project = await get_project_or_404(user, project_id, "comment")
    room_name = next((r["name"] for r in project.get("rooms", []) if r["id"] == body.room_id), None)
    doc = {
        "project_id": project["_id"], "user_id": user["_id"], "user_name": user.get("name") or user["email"],
        "role": current_role() or "owner", "text": body.text.strip(), "room_id": body.room_id if room_name else None,
        "room_name": room_name, "resolved": False, "at": datetime.now(UTC),
    }  # fmt: skip
    doc["_id"] = (await get_db().comments.insert_one(doc)).inserted_id
    await log_activity(project["_id"], f"Commented{f' on {room_name}' if room_name else ''}")
    return _comment_out(doc, user)


class ResolveIn(BaseModel):
    resolved: bool


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def resolve_comment(
    project_id: str, comment_id: str, body: ResolveIn, user: CurrentUser
) -> CommentOut:
    project = await get_project_or_404(user, project_id, "comment")
    c = await get_db().comments.find_one(
        {"_id": parse_object_id(comment_id), "project_id": project["_id"]}
    )
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    if c.get("user_id") != user["_id"] and current_role() not in (
        "owner",
        "contractor",
        "designer",
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the team or the author can resolve this."
        )
    await get_db().comments.update_one({"_id": c["_id"]}, {"$set": {"resolved": body.resolved}})
    c["resolved"] = body.resolved
    return _comment_out(c, user)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(project_id: str, comment_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id, "comment")
    c = await get_db().comments.find_one(
        {"_id": parse_object_id(comment_id), "project_id": project["_id"]}
    )
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    if c.get("user_id") != user["_id"] and current_role() != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can delete only your own comments.")
    await get_db().comments.delete_one({"_id": c["_id"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Approval of the estimate -------------------------------------------------------------------


class ApprovalIn(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str | None = Field(default=None, max_length=1000)


class ApprovalOut(BaseModel):
    requested_at: datetime | None
    current_version: int
    approved_current: bool  # someone approved the estimate as it is now
    pending: bool  # approval was asked for and the current version isn't decided yet
    decisions: list[dict]  # newest first: user_name, role, decision, note, at, current, metrics


async def _approval(project: dict) -> ApprovalOut:
    version = project.get("rooms_version") or 0
    decisions = [
        {
            "user_name": a["user_name"], "role": a["role"], "decision": a["decision"], "note": a.get("note"),
            "at": a["at"], "current": a["rooms_version"] == version, "metrics": a.get("metrics") or {},
        }
        async for a in get_db().approvals.find({"project_id": project["_id"]}).sort("at", DESCENDING).limit(50)
    ]  # fmt: skip
    current = [d for d in decisions if d["current"]]
    approved = bool(current) and current[0]["decision"] == "approved"
    requested = project.get("approval_requested_at")
    return ApprovalOut(
        requested_at=requested,
        current_version=version,
        approved_current=approved,
        pending=bool(requested) and not current,
        decisions=decisions,
    )


@router.get("/approval", response_model=ApprovalOut)
async def approval(project_id: str, user: CurrentUser) -> ApprovalOut:
    return await _approval(await get_project_or_404(user, project_id))


@router.post("/approval/request", response_model=ApprovalOut)
async def request_approval(project_id: str, user: CurrentUser) -> ApprovalOut:
    """Ask the client (and anyone on the project) to review the estimate as it is now."""
    project = await get_project_or_404(user, project_id, "cost")
    now = datetime.now(UTC)
    await get_db().projects.update_one(
        {"_id": project["_id"]}, {"$set": {"approval_requested_at": now}}
    )
    project["approval_requested_at"] = now
    await log_activity(project["_id"], "Asked for approval of the estimate")
    homeowners = [m["user_id"] for m in project.get("members", []) if m["role"] == "homeowner"]
    async for h in get_db().users.find({"_id": {"$in": homeowners}}, {"email": 1}):
        await invite_email(h["email"], user, f"review the estimate for {project.get('name', '')}")
    return await _approval(project)


@router.post("/approval", response_model=ApprovalOut)
async def decide(project_id: str, body: ApprovalIn, user: CurrentUser) -> ApprovalOut:
    """Approve the estimate as it is now, or ask for changes. A later change to the rooms or
    tiles needs a new approval."""
    project = await get_project_or_404(user, project_id, "comment")
    await get_db().approvals.insert_one(
        {
            "project_id": project["_id"], "user_id": user["_id"], "user_name": user.get("name") or user["email"],
            "role": current_role() or "owner", "decision": body.decision, "note": (body.note or "").strip() or None,
            "rooms_version": project.get("rooms_version") or 0, "metrics": version_metrics(project), "at": datetime.now(UTC),
        }
    )  # fmt: skip
    label = (
        "Approved the estimate"
        if body.decision == "approved"
        else "Asked for changes to the estimate"
    )
    await log_activity(project["_id"], label, detail=body.note)
    return await _approval(project)


# --- Read-only share link -----------------------------------------------------------------------


class ShareIn(BaseModel):
    show_costs: bool = False


class ShareOut(BaseModel):
    token: str
    show_costs: bool
    created_at: datetime


@router.get("/share", response_model=ShareOut | None)
async def get_share(project_id: str, user: CurrentUser) -> ShareOut | None:
    project = await get_project_or_404(user, project_id, "manage")
    share = project.get("share")
    return ShareOut(**share) if share and share.get("token") else None


@router.post("/share", response_model=ShareOut)
async def create_share(project_id: str, body: ShareIn, user: CurrentUser) -> ShareOut:
    """A link anyone can open to see the results (no login). Making a new one stops the old one."""
    project = await get_project_or_404(user, project_id, "manage")
    share = {
        "token": secrets.token_urlsafe(24),
        "show_costs": body.show_costs,
        "created_at": datetime.now(UTC),
    }
    await get_db().projects.update_one({"_id": project["_id"]}, {"$set": {"share": share}})
    await log_activity(project["_id"], "Made a read-only link")
    return ShareOut(**share)


@router.patch("/share", response_model=ShareOut)
async def update_share(project_id: str, body: ShareIn, user: CurrentUser) -> ShareOut:
    project = await get_project_or_404(user, project_id, "manage")
    share = project.get("share")
    if not share or not share.get("token"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no link.")
    await get_db().projects.update_one(
        {"_id": project["_id"]}, {"$set": {"share.show_costs": body.show_costs}}
    )
    return ShareOut(**{**share, "show_costs": body.show_costs})


@router.delete("/share", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(project_id: str, user: CurrentUser) -> Response:
    project = await get_project_or_404(user, project_id, "manage")
    await get_db().projects.update_one({"_id": project["_id"]}, {"$unset": {"share": ""}})
    await log_activity(project["_id"], "Turned off the read-only link")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Activity -----------------------------------------------------------------------------------


class ActivityOut(BaseModel):
    at: datetime
    user_name: str | None
    label: str
    detail: str | None


@router.get("/activity", response_model=list[ActivityOut])
async def activity(project_id: str, user: CurrentUser) -> list[ActivityOut]:
    """Who did what, newest first: changes (from the history) and other events."""
    project = await get_project_or_404(user, project_id)
    db = get_db()
    items = [
        ActivityOut(at=v["at"], user_name=v.get("user_name"), label=v["label"], detail=None)
        async for v in db.project_versions.find({"project_id": project["_id"]}, {"snapshot": 0})
        .sort("at", DESCENDING)
        .limit(100)
    ]
    items += [
        ActivityOut(
            at=a["at"], user_name=a.get("user_name"), label=a["label"], detail=a.get("detail")
        )
        async for a in db.activity.find({"project_id": project["_id"]})
        .sort("at", DESCENDING)
        .limit(100)
    ]
    return sorted(items, key=lambda a: a.at, reverse=True)[:100]
