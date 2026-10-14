"""Dashboards (PRD 4.20, 4.21): a project's summary, insights and analytics; a contractor's
business; team and role-based views; platform usage and accuracy for admins.

Everything is read-only and built from what the app already stores. Each dashboard shows only
what the viewer is allowed to see: costs for roles with costs, projects they can open."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bson import ObjectId
from fastapi import APIRouter
from pymongo import ASCENDING, DESCENDING

from app.api.deps import AdminUser, CurrentUser
from app.db.mongo import get_db
from app.schemas.dashboard import (
    ActivityRow,
    BusinessOut,
    MemberActivity,
    Money,
    PendingItem,
    PlatformOut,
    ProjectDashboardOut,
    QuoteRow,
    TeamDashboardOut,
    TeamSummary,
    WeekPoint,
)
from app.schemas.project import Room
from app.services import dashboards as dash
from app.services.access import can_see_costs, project_role, user_team_ids, visible_projects_query
from app.services.cost import build_cost, cost_settings
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import project_default
from app.services.projects import get_project_or_404
from app.services.review import review_state

router = APIRouter(tags=["dashboards"])

MAX_PROJECTS = 300  # business figures look at the most recent projects


def _estimate(doc: dict):
    state = review_state(doc)
    default = project_default(doc)
    extras = extras_settings(doc)
    estimate = build_estimate(state, default, extras)
    return state, default, extras, estimate


@router.get("/projects/{project_id}/dashboard", response_model=ProjectDashboardOut)
async def project_dashboard(project_id: str, user: CurrentUser) -> ProjectDashboardOut:
    """Summary, insights and analytics for one project (PRD 4.20, 4.21)."""
    project = await get_project_or_404(user, project_id)
    db = get_db()
    state, default, extras, estimate = _estimate(project)
    settings = cost_settings(project)
    cost = build_cost(state, default, estimate, settings, extras)
    pid = project["_id"]
    blueprints = [
        b async for b in db.blueprints.find({"project_id": pid}).sort("created_at", ASCENDING)
    ]
    versions = [
        v
        async for v in db.project_versions.find({"project_id": pid}, {"snapshot": 0}).sort(
            "at", ASCENDING
        )
    ]
    events = [
        e async for e in db.activity.find({"project_id": pid}).sort("at", DESCENDING).limit(40)
    ]
    return dash.project_dashboard(
        project,
        state,
        estimate,
        cost,
        settings,
        costs_visible=can_see_costs(),
        blueprints=blueprints,
        versions=versions,
        events=events,
    )


async def _business_projects(user: dict) -> list[dict]:
    """Projects the user runs: their own and their team's, where they see costs."""
    teams = await user_team_ids(user)
    cursor = (
        get_db()
        .projects.find(await visible_projects_query(user), {"snapshot": 0})
        .sort("created_at", DESCENDING)
        .limit(MAX_PROJECTS)
    )
    return [
        p async for p in cursor if await project_role(user, p, teams) in ("owner", "contractor")
    ]


@router.get("/dashboards/business", response_model=BusinessOut)
async def business(user: CurrentUser) -> BusinessOut:
    """Quotes, margins and conversion; the tiles used most; projects by month (PRD 4.21)."""
    projects = await _business_projects(user)
    ids = [p["_id"] for p in projects]
    names = {p["_id"]: p.get("name") or "Project" for p in projects}
    quotes = [
        q
        async for q in get_db()
        .quotes.find({"project_id": {"$in": ids}, "latest": True})
        .sort("created_at", DESCENDING)
    ]
    currencies = Counter(q["currency"] for q in quotes)
    main = currencies.most_common(1)[0][0] if quotes else None
    mine = [q for q in quotes if q["currency"] == main]
    locale = mine[0]["locale"] if mine else None

    def total(rows, field):
        return sum((Decimal(str(r[field])) for r in rows), Decimal(0))

    approved = [q for q in mine if q["status"] == "approved"]
    rejected = [q for q in mine if q["status"] == "rejected"]
    approved_subtotal = total(approved, "subtotal")
    margin = total(approved, "margin_amount")

    estimates = []
    area: dict[ObjectId, Decimal] = {}
    for p in projects:
        _, _, _, est = _estimate(p)
        if est.ready and est.totals:
            estimates.append((str(p["_id"]), est))
            area[p["_id"]] = est.totals.usable_area_mm2
        else:
            area[p["_id"]] = sum(
                (Room.model_validate(r).floor_area_mm2 or Decimal(0) for r in p.get("rooms", [])),
                Decimal(0),
            )
    quoted = {}
    for q in mine:
        quoted.setdefault(q["project_id"], Decimal(str(q["total"])))

    return BusinessOut(
        money=Money(currency=main, locale=locale) if main else None,
        quotes=len(quotes),
        by_status=dict(Counter(q["status"] for q in mine)),
        quoted_total=total(mine, "total"),
        approved_total=total(approved, "total"),
        margin_total=margin,
        margin_pct=dash._pct(margin, approved_subtotal),
        conversion_pct=dash._pct(len(approved), len(approved) + len(rejected)),
        other_currency_quotes=len(quotes) - len(mine),
        recent_quotes=[
            QuoteRow(
                quote_id=str(q["_id"]),
                project_id=str(q["project_id"]),
                project_name=names.get(q["project_id"], q.get("project_name") or ""),
                client=(q.get("client") or {}).get("name") or "",
                number=q["number"],
                version=q["version"],
                status=q["status"],
                total=Decimal(str(q["total"])),
                margin_amount=Decimal(str(q["margin_amount"])),
                currency=q["currency"],
                locale=q["locale"],
                created_at=q["created_at"],
                sent_at=q.get("sent_at"),
            )
            for q in quotes[:20]
        ],
        projects=len(projects),
        tiles=dash.tile_usage(estimates),
        months=dash.months_table(projects, area, quoted, datetime.now(UTC)),
    )


@router.get("/dashboards/team", response_model=TeamDashboardOut)
async def team(user: CurrentUser) -> TeamDashboardOut:
    """What's waiting for the user, who changed what, and each team's activity (PRD 4.21).
    Only projects the user can open are included."""
    db = get_db()
    teams = await user_team_ids(user)
    projects = [
        p
        async for p in db.projects.find(
            await visible_projects_query(user),
            {"name": 1, "owner_id": 1, "team_id": 1, "members": 1, "rooms": 1, "rooms_version": 1,
             "approval_requested_at": 1, "updated_at": 1},
        ).sort("updated_at", DESCENDING).limit(MAX_PROJECTS)
    ]  # fmt: skip
    roles = {p["_id"]: await project_role(user, p, teams) for p in projects}
    names = {p["_id"]: p.get("name") or "Project" for p in projects}
    ids = list(names)

    # Latest decision per project (for the current version only).
    decisions: dict[ObjectId, dict] = {}
    async for a in db.approvals.find({"project_id": {"$in": ids}}).sort("at", DESCENDING):
        decisions.setdefault(a["project_id"], a)
    open_comments = Counter()
    async for c in db.comments.find(
        {"project_id": {"$in": ids}, "resolved": {"$ne": True}}, {"project_id": 1, "user_id": 1}
    ):
        if c.get("user_id") != user["_id"]:
            open_comments[c["project_id"]] += 1

    pending: list[PendingItem] = []
    for p in projects:
        pid, role = p["_id"], roles[p["_id"]]
        version = p.get("rooms_version") or 0
        latest = decisions.get(pid)
        decided_now = latest is not None and latest.get("rooms_version") == version
        requested = p.get("approval_requested_at")
        name = names[pid]
        if requested and not decided_now:
            if role == "homeowner":
                pending.append(PendingItem(kind="approve", project_id=str(pid), project_name=name,
                                           text="Review and approve the estimate", at=requested))  # fmt: skip
            elif role in ("owner", "contractor"):
                pending.append(PendingItem(kind="awaiting_client", project_id=str(pid), project_name=name,
                                           text="Waiting for the client's approval", at=requested))  # fmt: skip
        if decided_now and latest["decision"] == "changes_requested" and role != "homeowner":
            pending.append(PendingItem(kind="changes_requested", project_id=str(pid), project_name=name,
                                       text=f"{latest['user_name']} asked for changes"
                                       + (f": {latest['note']}" if latest.get("note") else ""),
                                       at=latest["at"]))  # fmt: skip
        if open_comments[pid]:
            n = open_comments[pid]
            pending.append(PendingItem(kind="comments", project_id=str(pid), project_name=name,
                                       text=f"{n} open comment{'s' if n != 1 else ''}", at=None))  # fmt: skip
        if role in ("owner", "contractor", "designer"):
            unconfirmed = sum(
                1 for r in p.get("rooms", []) if not r.get("confirmed") and not r.get("skipped")
            )
            if unconfirmed:
                pending.append(PendingItem(kind="review_rooms", project_id=str(pid), project_name=name,
                                           text=f"{unconfirmed} room{'s' if unconfirmed != 1 else ''} to review",
                                           at=p.get("updated_at")))  # fmt: skip

    # Who edited what: changes (versions) and other events, newest first.
    since = datetime.now(UTC) - timedelta(days=30)
    rows = [
        *[v async for v in db.project_versions.find({"project_id": {"$in": ids}}, {"snapshot": 0, "metrics": 0}).sort("at", DESCENDING).limit(60)],
        *[e async for e in db.activity.find({"project_id": {"$in": ids}}).sort("at", DESCENDING).limit(60)],
    ]  # fmt: skip
    rows.sort(key=lambda r: r["at"], reverse=True)
    activity = [
        ActivityRow(project_id=str(r["project_id"]), project_name=names.get(r["project_id"], ""), at=r["at"],
                    label=r.get("label") or "Changed the project", user_name=r.get("user_name"))
        for r in rows[:50]
    ]  # fmt: skip

    summaries = []
    async for t in db.teams.find({"_id": {"$in": list(teams)}}):
        team_projects = [p["_id"] for p in projects if p.get("team_id") == t["_id"]]
        changes = Counter()
        last: dict = {}
        async for v in db.project_versions.find(
            {"project_id": {"$in": team_projects}}, {"user_id": 1, "at": 1}
        ):
            if v["at"].replace(tzinfo=v["at"].tzinfo or UTC) >= since:
                changes[v.get("user_id")] += 1
            if v.get("user_id") and (v["user_id"] not in last or v["at"] > last[v["user_id"]]):
                last[v["user_id"]] = v["at"]
        member_ids = [m["user_id"] for m in t["members"]]
        people = {
            u["_id"]: u
            async for u in db.users.find({"_id": {"$in": member_ids}}, {"name": 1, "email": 1})
        }
        summaries.append(
            TeamSummary(
                id=str(t["_id"]), name=t["name"], my_role=teams[t["_id"]], projects=len(team_projects),
                members=[
                    MemberActivity(
                        user_name=(people.get(m["user_id"]) or {}).get("name") or (people.get(m["user_id"]) or {}).get("email") or "Former member",
                        role="owner" if t.get("owner_id") == m["user_id"] else m["role"],
                        changes_30d=changes[m["user_id"]], last_at=last.get(m["user_id"]),
                    )
                    for m in t["members"]
                ],
            )
        )  # fmt: skip

    return TeamDashboardOut(
        roles=dict(Counter(r for r in roles.values() if r)),
        pending=pending,
        activity=activity,
        teams=summaries,
    )


@router.get("/admin/platform", response_model=PlatformOut)
async def platform(_: AdminUser) -> PlatformOut:
    """Accuracy by kind of file and by field, what usually goes wrong, feedback and usage over
    the last 12 weeks (PRD 4.21)."""
    db = get_db()
    now = datetime.now(UTC)
    weeks = dash.last_weeks(now)
    first = datetime.fromisoformat(weeks[0]).replace(tzinfo=UTC)
    points = {w: WeekPoint(week=w) for w in weeks}

    def bump(at: datetime | None, field: str) -> None:
        if at is None:
            return
        w = dash.week_start(at if at.tzinfo else at.replace(tzinfo=UTC))
        if w in points:
            setattr(points[w], field, getattr(points[w], field) + 1)

    outcomes = [o async for o in db.extraction_outcomes.find({}, {"extracted": 1, "final": 1, "kind": 1, "status": 1, "method": 1, "file_id": 1, "flags": 1, "confidence_level": 1})]  # fmt: skip
    file_ids = {
        ObjectId(o["file_id"])
        for o in outcomes
        if o.get("file_id") and ObjectId.is_valid(o["file_id"])
    }
    kinds = {str(b["_id"]): b["kind"] async for b in db.blueprints.find({"_id": {"$in": list(file_ids)}}, {"kind": 1})}  # fmt: skip
    read_failures = Counter()
    async for b in db.blueprints.find({"extraction": {"$exists": True}}, {"extraction.status": 1}):
        read_failures[b["extraction"]["status"]] += 1

    async for f in db.feedback.find({"created_at": {"$gte": first}}, {"right": 1, "created_at": 1}):
        bump(f["created_at"], "right" if f["right"] else "wrong")
    async for u in db.users.find({"created_at": {"$gte": first}}, {"created_at": 1}):
        bump(u["created_at"], "signups")
    field = {"project": "projects", "upload": "uploads", "export": "exports", "quote": "quotes"}
    async for e in db.usage_events.find({"at": {"$gte": first}}, {"kind": 1, "at": 1}):
        if e["kind"] in field:
            bump(e["at"], field[e["kind"]])

    active = await db.project_versions.distinct(
        "user_id", {"at": {"$gte": now - timedelta(days=30)}}
    )
    return PlatformOut(
        users=await db.users.count_documents({}),
        active_users_30d=len([a for a in active if a]),
        projects=await db.projects.count_documents({}),
        uploads=await db.usage_events.count_documents({"kind": "upload"}),
        exports=await db.usage_events.count_documents({"kind": "export"}),
        by_source=dash.by_source(outcomes, kinds),
        fields=dash.field_corrections(outcomes),
        patterns=dash.failure_patterns(outcomes),
        read_failures=dict(read_failures),
        weeks=list(points.values()),
    )
