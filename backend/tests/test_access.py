import asyncio

import pytest
from bson import ObjectId

from app.services.access import ALLOWED, project_role

OWNER, MEMBER, OTHER = ObjectId(), ObjectId(), ObjectId()
TEAM = ObjectId()


def role(user_id, project, teams=None, admin=False):
    user = {"_id": user_id, "role": "admin" if admin else "contractor"}
    return asyncio.run(project_role(user, project, teams if teams is not None else {}))


def test_owner_admin_and_strangers():
    project = {"owner_id": OWNER}
    assert role(OWNER, project) == "owner"
    assert role(OTHER, project, admin=True) == "owner"  # admins act as owners, for support
    assert role(OTHER, project) is None


def test_team_members_get_their_team_role():
    project = {"owner_id": OWNER, "team_id": TEAM}
    assert role(MEMBER, project, {TEAM: "designer"}) == "designer"
    assert role(MEMBER, project, {TEAM: "owner"}) == "contractor"  # another member owning the team
    assert role(MEMBER, project, {ObjectId(): "designer"}) is None  # a different team


def test_invited_project_members():
    project = {"owner_id": OWNER, "members": [{"user_id": MEMBER, "role": "homeowner"}]}
    assert role(MEMBER, project) == "homeowner"


@pytest.mark.parametrize(
    ("need", "allowed"),
    [
        ("view", {"owner", "contractor", "designer", "homeowner"}),
        ("comment", {"owner", "contractor", "designer", "homeowner"}),
        ("edit", {"owner", "contractor", "designer"}),
        ("cost", {"owner", "contractor"}),
        ("manage", {"owner"}),
    ],
)
def test_permission_matrix(need, allowed):
    assert ALLOWED[need] == allowed
