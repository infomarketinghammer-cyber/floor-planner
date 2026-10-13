"""Project history (PRD 4.12, 4.21): a snapshot after each change, with who made it, what it
was, and the totals at that point, so changes can be reviewed, restored, and the budget tracked
over time.
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.core.activity import acting_user, current_action
from app.core.guest import is_guest
from app.db.mongo import get_db

MAX_VERSIONS = 100  # per project; the oldest are dropped
SNAPSHOT_FIELDS = (
    "rooms",
    "default_material",
    "cost_settings",
    "extras_settings",
    "plan_unit",
    "plan_unit_confirmed",
)


def _metrics(doc: dict) -> dict:
    """Totals at this version: boxes, waste and cost (None when not calculable)."""
    from app.services.cost import build_cost, cost_settings
    from app.services.estimate import build_estimate
    from app.services.extras import extras_settings
    from app.services.materials import project_default
    from app.services.review import review_state

    state = review_state(doc)
    default = project_default(doc)
    extras = extras_settings(doc)
    estimate = build_estimate(state, default, extras)
    if not estimate.ready or estimate.totals is None:
        return {"ready": False, "rooms": len(state.rooms)}
    settings = cost_settings(doc)
    cost = build_cost(state, default, estimate, settings, extras)
    t = estimate.totals
    return {
        "ready": True,
        "rooms": len(state.rooms),
        "boxes": t.boxes,
        "extra_pct": str((t.extra_area_mm2 / t.usable_area_mm2 * 100).quantize(Decimal("0.1"))),
        "cost": str(cost.total) if cost and cost.has_prices else None,
        "budget": str(settings.budget) if settings.budget is not None else None,
    }


async def record_version(doc: dict, user: dict | None = None, label: str | None = None) -> None:
    """Snapshot the project as it is now. Guests keep their history in the browser."""
    if is_guest():
        return
    user = user or acting_user()
    db = get_db()
    await db.project_versions.insert_one(
        {
            "project_id": doc["_id"],
            "at": datetime.now(UTC),
            "user_id": user["_id"] if user else None,
            "user_name": user.get("name") if user else None,
            "label": label or current_action(),
            "rooms_version": doc.get("rooms_version") or 0,
            "metrics": _metrics(doc),
            "snapshot": {k: doc.get(k) for k in SNAPSHOT_FIELDS},
        }
    )
    # Keep the newest MAX_VERSIONS.
    old = (
        db.project_versions.find({"project_id": doc["_id"]}, {"_id": 1})
        .sort("at", -1)
        .skip(MAX_VERSIONS)
    )
    stale = [v["_id"] async for v in old]
    if stale:
        await db.project_versions.delete_many({"_id": {"$in": stale}})
