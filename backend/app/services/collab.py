"""Collaboration helpers (PRD 4.18, 4.21): activity log, invitations, the read-only shared view."""

from datetime import UTC, datetime
from decimal import Decimal

from app.core.activity import acting_user
from app.db.mongo import get_db


async def log_activity(
    project_id, label: str, user: dict | None = None, detail: str | None = None
) -> None:
    """Events that aren't project versions: comments, approvals, sharing, people, quotes.
    (Changes to the rooms and settings are in project_versions, with the same who/what/when.)"""
    user = user or acting_user()
    await get_db().activity.insert_one(
        {
            "project_id": project_id,
            "at": datetime.now(UTC),
            "user_id": user["_id"] if user else None,
            "user_name": user.get("name") if user else None,
            "label": label,
            "detail": detail,
        }
    )


async def attach_invites(user: dict) -> int:
    """Turn invitations to this user's email into team and project memberships (on sign-up or
    sign-in). Returns how many were accepted."""
    db = get_db()
    email = (user.get("email") or "").lower()
    if not email:
        return 0
    accepted = 0
    now = datetime.now(UTC)
    async for team in db.teams.find({"invites.email": email}):
        invite = next(i for i in team["invites"] if i["email"] == email)
        if not any(m["user_id"] == user["_id"] for m in team["members"]):
            await db.teams.update_one(
                {"_id": team["_id"]},
                {
                    "$push": {
                        "members": {"user_id": user["_id"], "role": invite["role"], "added_at": now}
                    }
                },
            )
            accepted += 1
        await db.teams.update_one({"_id": team["_id"]}, {"$pull": {"invites": {"email": email}}})
    async for project in db.projects.find({"invites.email": email}):
        invite = next(i for i in project["invites"] if i["email"] == email)
        if not any(m["user_id"] == user["_id"] for m in project.get("members", [])):
            await db.projects.update_one(
                {"_id": project["_id"]},
                {
                    "$push": {
                        "members": {"user_id": user["_id"], "role": invite["role"], "added_at": now}
                    }
                },
            )
            await log_activity(project["_id"], "Joined the project", user)
            accepted += 1
        await db.projects.update_one(
            {"_id": project["_id"]}, {"$pull": {"invites": {"email": email}}}
        )
    return accepted


def shared_view(doc: dict, show_costs: bool, company_name: str | None) -> dict:
    """What a read-only link shows: results, shopping list, assumptions, and costs if the owner
    chose to include them. Never plan files, prices per box, notes or people."""
    from app.exports.data import NOTICE, NotReady, export_data
    from app.exports.formatting import area_value

    try:
        data = export_data(doc, "sqft", include_costs=show_costs)  # areas are sent in both units
    except NotReady as e:
        return {
            "ready": False,
            "blockers": e.blockers,
            "project_name": doc.get("name"),
            "company": company_name,
        }
    est = data.estimate
    t = est.totals
    rooms = []
    for r in est.rooms:
        rooms.append(
            {
                "name": r.name,
                "floor": r.floor,
                "size": data.size(r),
                "area_sqft": str(area_value(r.usable_area_mm2, "sqft").quantize(Decimal("0.01"))),
                "area_sqm": str(area_value(r.usable_area_mm2, "sqm").quantize(Decimal("0.01"))),
                "tile": f"{r.tile.size_label} {r.tile.name}",
                "layout": r.layout.value,
                "boxes": r.boxes,
                "roll_m": str((r.linear_mm / 1000).quantize(Decimal("0.01")))
                if r.linear_mm
                else None,
            }
        )
    out = {
        "ready": True,
        "project_name": data.project_name,
        "company": company_name,
        "updated_at": doc.get("updated_at"),
        "rooms": rooms,
        "totals": {
            "rooms": t.rooms,
            "boxes": t.boxes,
            "area_sqft": str(area_value(t.usable_area_mm2, "sqft").quantize(Decimal("0.01"))),
            "area_sqm": str(area_value(t.usable_area_mm2, "sqm").quantize(Decimal("0.01"))),
            "extra_pct": str((t.extra_area_mm2 / t.usable_area_mm2 * 100).quantize(Decimal("0.1"))),
        },
        "shopping": [
            {
                "section": s.section,
                "name": s.name,
                "size": s.size,
                "quantity": s.quantity,
                "detail": s.detail,
            }
            for s in data.shopping_lines
        ],
        "assumptions": [{"title": a.title, "text": a.text} for a in est.assumptions],
        "notice": NOTICE,
        "cost": None,
    }
    if show_costs and data.cost and data.cost.has_prices:
        c = data.cost
        out["cost"] = {
            "currency": data.settings.currency,
            "locale": data.settings.locale,
            "materials": str(c.materials) if c.materials is not None else None,
            "extras": [{"label": x.label, "amount": str(x.amount)} for x in c.extras],
            "lines": [{"label": line.label, "amount": str(line.amount)} for line in c.lines],
            "tax": {"label": c.tax.label, "pct": str(c.tax.pct), "amount": str(c.tax.amount)}
            if c.tax
            else None,
            "total": str(c.total),
        }
    return out
