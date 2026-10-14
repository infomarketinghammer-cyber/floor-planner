"""Dashboard figures (PRD 4.20, 4.21). The calculations are pure functions over data the app
already keeps (the estimate, cost, history, quotes, accuracy outcomes), so a dashboard always
shows the same numbers as the rest of the app."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median

from app.schemas.cost import CostOut, CostSettings
from app.schemas.dashboard import (
    BlueprintStatus,
    CostPart,
    DashRoom,
    DashTile,
    FailurePattern,
    FieldCorrections,
    HistoryPoint,
    Insight,
    Money,
    MonthRow,
    ProjectDashboardOut,
    ReviewStatus,
    SourceAccuracy,
    TileUsage,
    TimelineEvent,
)
from app.schemas.estimate import EstimateOut, RoomEstimateOut
from app.services.accuracy import _close, _norm
from app.services.review import ReviewState

HIGH_EXTRA_PCT = Decimal(20)  # buying more than this over the area is flagged (PRD 4.20)
SMALL_ROOM_MM2 = Decimal(4_000_000)  # 4 m²: box rounding can dominate below this
ROUNDING_SHARE = Decimal("0.5")  # ...when the last part-box is over half the extra
BUDGET_HEAVY_PCT = Decimal(40)  # one room taking this much of the budget is worth a note
ONE = Decimal("0.1")


def _pct(part: Decimal | int, whole: Decimal | int) -> Decimal | None:
    return (Decimal(part) / Decimal(whole) * 100).quantize(ONE) if whole else None


def tile_label(room: RoomEstimateOut) -> str:
    return f"{room.tile.size_label} {room.tile.name}"


def _sqm(mm2: Decimal) -> str:
    return f"{(mm2 / 1_000_000).quantize(ONE).normalize():f} m²"


# --- Project dashboard ------------------------------------------------------------------------


def cost_parts(cost: CostOut) -> list[CostPart]:
    """The total split into what it's spent on, largest first; tax last."""
    parts: dict[str, Decimal] = defaultdict(Decimal)
    if cost.materials is not None:
        parts["Floor tiles"] += cost.materials
    for x in cost.extras:
        if x.key.startswith("wall:"):
            parts["Wall tiles"] += x.amount
        elif x.key.startswith("skirting:"):
            parts["Skirting"] += x.amount
        else:
            parts["Sundries"] += x.amount
    names = {"labour": "Labour", "delivery": "Delivery"}
    for line in cost.lines:
        parts[names.get(line.kind.value, "Other costs")] += line.amount
    out = [CostPart(label=k, amount=v) for k, v in parts.items() if v > 0]
    out.sort(key=lambda p: p.amount, reverse=True)
    if cost.tax and cost.tax.amount > 0:
        out.append(CostPart(label=cost.tax.label, amount=cost.tax.amount))
    return out


def insights(
    state: ReviewState,
    estimate: EstimateOut,
    cost: CostOut | None,
    settings: CostSettings,
    rooms: list[DashRoom],
) -> list[Insight]:
    """Things worth a look, warnings first (PRD 4.20 insights and alerts)."""
    out: list[Insight] = []

    # Rooms that block or need checking: no size, no tile, unusual sizes, duplicates.
    for room in state.rooms:
        for issue in state.issues.get(room.id, []):
            if issue.code in ("size_missing", "implausible_size", "duplicate"):
                out.append(
                    Insight(
                        key=f"{issue.code}:{room.id}",
                        severity="warning",
                        title=f"{room.name}: "
                        + {
                            "size_missing": "no size",
                            "implausible_size": "unusual size",
                            "duplicate": "possible duplicate",
                        }[issue.code],
                        text=issue.message,
                        room_id=room.id,
                    )
                )
    if not estimate.ready:
        for blocker in estimate.blockers:
            if "tile" in blocker.lower():
                out.append(
                    Insight(key="no_tile", severity="warning", title="Tiles missing", text=blocker)
                )

    for r in estimate.rooms:
        extra = Decimal(r.extra_pct)
        if extra > HIGH_EXTRA_PCT:
            parts = []
            if r.cut_waste_pct > 0:
                parts.append(f"cuts {r.cut_waste_pct.quantize(ONE)}%")
            if r.rounding_tiles:
                parts.append(
                    f"{r.rounding_tiles} tile{'s' if r.rounding_tiles != 1 else ''} left in the last box"
                )
            hint = r.waste_hint or (
                "Most of it is the last part-box: use the leftovers in another room with the same tile."
                if r.rounding_area_mm2 > r.cut_waste_mm2
                else "A different tile size or a straight layout may cut less."
            )
            out.append(
                Insight(
                    key=f"high_waste:{r.room_id}",
                    severity="warning",
                    title=f"{r.name}: {extra.quantize(ONE)}% extra",
                    text=f"You buy {extra.quantize(ONE)}% more than the floor area"
                    + (f" ({', '.join(parts)})" if parts else "")
                    + f". {hint}",
                    room_id=r.room_id,
                )
            )
        elif (
            r.usable_area_mm2 < SMALL_ROOM_MM2
            and r.rounding_tiles > 0
            and r.extra_area_mm2 > 0
            and r.rounding_area_mm2 / r.extra_area_mm2 > ROUNDING_SHARE
        ):
            out.append(
                Insight(
                    key=f"rounding:{r.room_id}",
                    severity="info",
                    title=f"{r.name}: small room, whole boxes",
                    text=f"Only {_sqm(r.usable_area_mm2)} to tile, so most of the extra is "
                    f"{r.rounding_tiles} tile{'s' if r.rounding_tiles != 1 else ''} left in the last box. "
                    "Using the same tile as a "
                    "neighbouring room lets the leftovers be used there.",
                    room_id=r.room_id,
                )
            )

    for t in estimate.tiles:
        saved = t.boxes - t.boxes_if_pooled
        if saved > 0:
            out.append(
                Insight(
                    key=f"pool:{t.tile.id}",
                    severity="info",
                    title=f"Save {saved} box{'es' if saved != 1 else ''} of {t.tile.name}",
                    text=f"{t.rooms} rooms use {t.tile.size_label} {t.tile.name}. Using one room's "
                    f"leftover tiles in another needs {t.boxes_if_pooled} boxes instead of {t.boxes}.",
                )
            )

    if cost is not None:
        if cost.unpriced_rooms and cost.priced_rooms:
            out.append(
                Insight(
                    key="unpriced",
                    severity="warning",
                    title=f"{cost.unpriced_rooms} room{'s' if cost.unpriced_rooms != 1 else ''} without a price",
                    text="The cost total leaves these rooms out. Add a price to their tile.",
                )
            )
        if cost.budget is not None:
            heavy = sorted(
                (r for r in rooms if r.budget_share_pct is not None),
                key=lambda r: r.budget_share_pct or 0,
                reverse=True,
            )
            top = ", ".join(f"{r.name} ({r.budget_share_pct}%)" for r in heavy[:3])
            if cost.budget.status == "over":
                out.append(
                    Insight(
                        key="budget_over",
                        severity="warning",
                        title="Over budget",
                        text=f"The estimate is {cost.budget.used_pct}% of the budget."
                        + (f" Largest shares: {top}." if top else ""),
                    )
                )
            elif cost.budget.status == "near":
                out.append(
                    Insight(
                        key="budget_near",
                        severity="info",
                        title="Close to the budget",
                        text=f"The estimate uses {cost.budget.used_pct}% of the budget."
                        + (f" Largest shares: {top}." if top else ""),
                    )
                )
            # Over budget, the largest shares are already named above.
            for r in heavy if cost.budget.status != "over" else []:
                if r.budget_share_pct is not None and r.budget_share_pct >= BUDGET_HEAVY_PCT:
                    out.append(
                        Insight(
                            key=f"budget_room:{r.room_id}",
                            severity="info",
                            title=f"{r.name} takes {r.budget_share_pct}% of the budget",
                            text="A less expensive tile here would make the most difference.",
                            room_id=r.room_id,
                        )
                    )
    out.sort(key=lambda i: i.severity != "warning")
    return out


def project_dashboard(
    doc: dict,
    state: ReviewState,
    estimate: EstimateOut,
    cost: CostOut | None,
    settings: CostSettings,
    *,
    costs_visible: bool,
    blueprints: list[dict],
    versions: list[dict],
    events: list[dict],
) -> ProjectDashboardOut:
    if not costs_visible:
        cost = None
    room_cost = {rc.room_id: rc.cost for rc in cost.rooms} if cost else {}
    budget = settings.budget if costs_visible else None

    rooms = []
    for r in estimate.rooms:
        c = room_cost.get(r.room_id)
        rooms.append(
            DashRoom(
                room_id=r.room_id,
                name=r.name,
                floor=r.floor,
                room_type=r.room_type,
                tile_id=r.tile.id,
                tile=tile_label(r),
                area_mm2=r.usable_area_mm2,
                boxes=r.boxes,
                linear_mm=r.linear_mm,
                extra_pct=r.extra_pct,
                cut_waste_pct=r.cut_waste_pct,
                rounding_tiles=r.rounding_tiles,
                cost=c,
                budget_share_pct=_pct(c, budget) if c is not None and budget else None,
            )
        )

    tiles = []
    for t in estimate.tiles:
        costs = [room_cost.get(r.room_id) for r in estimate.rooms if r.tile.id == t.tile.id]
        priced = [c for c in costs if c is not None]
        tiles.append(
            DashTile(
                tile_id=t.tile.id,
                tile=f"{t.tile.size_label} {t.tile.name}",
                kind=t.tile.kind,
                rooms=t.rooms,
                boxes=t.boxes,
                boxes_if_pooled=t.boxes_if_pooled,
                linear_mm=t.linear_mm,
                area_mm2=t.usable_area_mm2,
                cost=sum(priced, Decimal(0)) if priced else None,
            )
        )

    s = state.summary
    review = ReviewStatus(
        rooms=s.total,
        confirmed=s.confirmed,
        to_review=s.to_review,
        skipped=sum(1 for r in state.rooms if r.skipped),
        from_plans=sum(1 for r in state.rooms if r.extracted is not None),
        with_issues=s.with_issues,
        unit_pending=s.unit_pending,
    )
    files = [
        BlueprintStatus(
            id=str(b["_id"]),
            filename=b["filename"],
            kind=b["kind"],
            status=(b.get("extraction") or {}).get("status", "not_read"),
            message=(b.get("extraction") or {}).get("message", "Not read yet."),
            rooms_found=(b.get("extraction") or {}).get("rooms_found", 0),
            rooms_flagged=(b.get("extraction") or {}).get("rooms_flagged", 0),
        )
        for b in blueprints
    ]

    history = []
    for v in versions:
        m = v.get("metrics") or {}
        history.append(
            HistoryPoint(
                at=v["at"],
                label=v.get("label") or "Changed the project",
                user_name=v.get("user_name"),
                ready=bool(m.get("ready")),
                boxes=m.get("boxes"),
                extra_pct=m.get("extra_pct"),
                cost=m.get("cost") if costs_visible else None,
                budget=m.get("budget") if costs_visible else None,
            )
        )
    timeline = [
        TimelineEvent(
            at=e["at"], label=e["label"], detail=e.get("detail"), user_name=e.get("user_name")
        )
        for e in sorted(
            [*({**v, "detail": None} for v in versions), *events],
            key=lambda e: e["at"],
            reverse=True,
        )[:40]
    ]

    t = estimate.totals
    has_money = cost is not None and cost.has_prices
    return ProjectDashboardOut(
        ready=estimate.ready,
        blockers=estimate.blockers,
        costs_visible=costs_visible,
        money=Money(currency=settings.currency, locale=settings.locale) if costs_visible else None,
        rooms_count=sum(1 for r in state.rooms if not r.skipped),
        area_mm2=t.usable_area_mm2
        if t
        else sum(
            (r.floor_area_mm2 or Decimal(0) for r in state.rooms if not r.skipped), Decimal(0)
        ),
        boxes=t.boxes if t else None,
        extra_pct=t.extra_pct if t else None,
        cut_waste_pct=t.cut_waste_pct if t else None,
        cost_total=cost.total if has_money else None,
        budget=budget,
        budget_status=cost.budget.status if cost and cost.budget else None,
        rooms=rooms,
        tiles=tiles,
        cost_parts=cost_parts(cost) if has_money else [],
        insights=insights(state, estimate, cost, settings, rooms),
        review=review,
        blueprints=files,
        history=history,
        timeline=timeline,
    )


# --- Business dashboard -----------------------------------------------------------------------


def tile_usage(estimates: list[tuple[str, EstimateOut]]) -> list[TileUsage]:
    """Tiles used most across a contractor's projects and how much extra they usually need."""
    projects: dict[str, set[str]] = defaultdict(set)
    rooms: dict[str, list[Decimal]] = defaultdict(list)
    boxes: Counter[str] = Counter()
    for project_id, est in estimates:
        for r in est.rooms:
            label = tile_label(r)
            projects[label].add(project_id)
            rooms[label].append(Decimal(r.extra_pct))
            boxes[label] += r.boxes
    out = [
        TileUsage(
            tile=label,
            projects=len(projects[label]),
            rooms=len(rooms[label]),
            boxes=boxes[label],
            typical_extra_pct=Decimal(median(rooms[label])).quantize(ONE),
        )
        for label in rooms
    ]
    out.sort(key=lambda u: (u.projects, u.rooms), reverse=True)
    return out[:10]


def month_key(at: datetime) -> str:
    return f"{at.year:04d}-{at.month:02d}"


def last_months(now: datetime, n: int = 12) -> list[str]:
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def months_table(
    projects: list[dict], area_by_project: dict, quoted_by_project: dict, now: datetime
) -> list[MonthRow]:
    keys = last_months(now)
    rows = {k: {"projects": 0, "area": Decimal(0), "quoted": Decimal(0)} for k in keys}
    for p in projects:
        k = month_key(p["created_at"])
        if k in rows:
            rows[k]["projects"] += 1
            rows[k]["area"] += area_by_project.get(p["_id"], Decimal(0))
            rows[k]["quoted"] += quoted_by_project.get(p["_id"], Decimal(0))
    return [
        MonthRow(month=k, projects=v["projects"], area_mm2=v["area"], quoted=v["quoted"])
        for k, v in rows.items()
    ]


# --- Platform and accuracy --------------------------------------------------------------------


def source_of(outcome: dict, kinds: dict[str, str]) -> str:
    """What sort of file a room was read from: text PDFs, scans and photos read very differently."""
    method = outcome.get("method")
    kind = kinds.get(outcome.get("file_id") or "")
    if method == "dxf_text" or kind in ("dxf", "dwg"):
        return "CAD drawing"
    if method == "pdf_text":
        return "PDF with text"
    if kind == "image":
        return "Photo or image"
    if kind == "pdf":
        return "Scanned PDF"
    return "Other"


def by_source(outcomes: list[dict], kinds: dict[str, str]) -> list[SourceAccuracy]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in outcomes:
        if o["kind"] == "extracted":
            groups[source_of(o, kinds)].append(o)
    out = []
    for source, rows in groups.items():
        correct = sum(1 for o in rows if o["status"] == "correct")
        reviewed = sum(1 for o in rows if o["status"] in ("correct", "corrected", "deleted"))
        out.append(
            SourceAccuracy(
                source=source,
                read=len(rows),
                reviewed=reviewed,
                correct=correct,
                accuracy_pct=_pct(correct, reviewed),
            )
        )
    out.sort(key=lambda s: s.read, reverse=True)
    return out


def _dec(v) -> Decimal | None:
    return None if v in (None, "None") else Decimal(str(v))


def field_changes(extracted: dict, final: dict) -> set[str]:
    """Which of name, length, width and unit the user changed. Sides read the other way round
    (11 × 9.5 for 9.5 × 11) are not a correction."""
    changed = set()
    if _norm(extracted.get("name") or "") != _norm(final.get("name") or ""):
        changed.add("name")
    if extracted.get("unit") != final.get("unit"):
        changed.add("unit")
    a1, b1 = _dec(extracted.get("length_mm")), _dec(extracted.get("width_mm"))
    a2, b2 = _dec(final.get("length_mm")), _dec(final.get("width_mm"))
    if None in (a1, b1, a2, b2):
        if a1 != a2:
            changed.add("length")
        if b1 != b2:
            changed.add("width")
        return changed
    if _close(a1, b2) and _close(b1, a2) and not (_close(a1, a2) and _close(b1, b2)):
        a2, b2 = b2, a2  # swapped
    if not _close(a1, a2):
        changed.add("length")
    if not _close(b1, b2):
        changed.add("width")
    return changed


def field_corrections(outcomes: list[dict]) -> list[FieldCorrections]:
    checked = [
        o
        for o in outcomes
        if o["kind"] == "extracted"
        and o["status"] in ("correct", "corrected")
        and o.get("extracted")
        and o.get("final")
    ]
    counts: Counter[str] = Counter()
    for o in checked:
        counts.update(field_changes(o["extracted"], o["final"]))
    return [
        FieldCorrections(
            field=f,
            corrected=counts[f],
            checked=len(checked),
            rate_pct=_pct(counts[f], len(checked)),
        )
        for f in ("name", "length", "width", "unit")
    ]


PATTERN_LABELS = {
    "ambiguous_pairing": "Several labels near one size",
    "far_from_label": "Size far from its label",
    "unusual_name": "Unusual room name",
    "unclear_text": "Hard-to-read text",
    "name_missing": "No name found",
    "unit_assumed": "Unit had to be assumed",
    "low": "Low confidence",
    "medium": "Medium confidence",
}


def failure_patterns(outcomes: list[dict]) -> list[FailurePattern]:
    """Review flags and confidence levels, and how often rooms with them turned out wrong."""
    seen: Counter[str] = Counter()
    wrong: Counter[str] = Counter()
    for o in outcomes:
        if o["kind"] != "extracted" or o["status"] == "pending":
            continue
        marks = set(o.get("flags") or [])
        if o.get("confidence_level") in ("low", "medium"):
            marks.add(o["confidence_level"])
        bad = o["status"] in ("corrected", "deleted")
        for m in marks:
            seen[m] += 1
            wrong[m] += bad
    out = [
        FailurePattern(
            label=PATTERN_LABELS.get(m, m.replace("_", " ").capitalize()),
            count=n,
            wrong_pct=_pct(wrong[m], n),
        )
        for m, n in seen.items()
    ]
    out.sort(key=lambda p: p.count, reverse=True)
    return out


def week_start(at: datetime) -> str:
    d = at.astimezone(UTC).date() if at.tzinfo else at.date()
    return (d - timedelta(days=d.weekday())).isoformat()


def last_weeks(now: datetime, n: int = 12) -> list[str]:
    start = datetime.fromisoformat(week_start(now))
    return [(start - timedelta(weeks=i)).date().isoformat() for i in range(n - 1, -1, -1)]
