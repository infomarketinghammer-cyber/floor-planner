from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.cost import CostLine, CostSettings
from app.schemas.material import MaterialOverride, Price, ProjectMaterial, TileRef
from app.schemas.project import Room
from app.services import dashboards as dash
from app.services.cost import build_cost
from app.services.estimate import build_estimate
from app.services.extras import extras_settings
from app.services.materials import project_default
from app.services.review import review_state

D = Decimal
NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
T600 = TileRef(
    id="t6", name="Ivory", size_label="600 × 600 mm", length_mm=600, width_mm=600, tiles_per_box=4,
)  # fmt: skip
BIG = TileRef(
    id="b1", name="Slab", size_label="1200 × 1200 mm", length_mm=1200, width_mm=1200, tiles_per_box=2,
)  # fmt: skip


def room(name, length, width, **kw) -> dict:
    return Room(
        **({"id": name, "name": name, "confirmed": True, "unit": "mm",
            "length_mm": D(length), "width_mm": D(width)} | kw)
    ).model_dump()  # fmt: skip


def build(rooms, settings: CostSettings | None = None, default=None, costs_visible=True, **kw):
    doc = {
        "rooms": rooms,
        "default_material": (
            default or ProjectMaterial(tile=T600, breakage_pct=D(0), price=Price(amount=D(1000)))
        ).model_dump(),
        "cost_settings": (settings or CostSettings()).model_dump(),
        "plan_unit_confirmed": True,
    }
    state = review_state(doc)
    default_m = project_default(doc)
    extras = extras_settings(doc)
    estimate = build_estimate(state, default_m, extras)
    settings = settings or CostSettings()
    cost = build_cost(state, default_m, estimate, settings, extras)
    return dash.project_dashboard(
        doc, state, estimate, cost, settings, costs_visible=costs_visible,
        blueprints=kw.get("blueprints", []), versions=kw.get("versions", []), events=kw.get("events", []),
    )  # fmt: skip


def test_summary_figures_match_the_estimate():
    out = build([room("Bedroom", 3000, 3000), room("Hall", 2400, 1800)])
    assert out.ready and out.rooms_count == 2
    assert out.area_mm2 == D(9_000_000 + 4_320_000)
    assert out.boxes == sum(r.boxes for r in out.rooms)
    assert out.tiles[0].boxes == out.boxes
    assert out.cost_total == D(1000) * out.boxes  # priced per box, no tax
    assert [p.label for p in out.cost_parts] == ["Floor tiles"]


def test_costs_hidden_for_roles_without_costs():
    out = build([room("Bedroom", 3000, 3000)], costs_visible=False)
    assert out.cost_total is None and out.money is None and out.cost_parts == []
    assert all(r.cost is None for r in out.rooms) and all(t.cost is None for t in out.tiles)
    assert not any(i.key.startswith("budget") for i in out.insights)


def test_high_waste_room_is_flagged_with_a_reason():
    # 1.3 m × 1.3 m with 1.2 m slabs: four slabs for 1.69 m², far more than 20% extra.
    out = build([room("WC", 1300, 1300)], default=ProjectMaterial(tile=BIG, breakage_pct=D(0)))
    insight = next(i for i in out.insights if i.key == "high_waste:WC")
    assert insight.severity == "warning"
    assert "more than the floor area" in insight.text


def test_small_room_rounding_and_pooling():
    # Rooms that use whole tiles exactly but end on a part-box.
    rooms = [room("Store", 1200, 600), room("Utility", 1200, 600)]
    out = build(rooms)
    # 2 tiles each, 1 box each; pooled: 4 tiles = 1 box.
    pool = next(i for i in out.insights if i.key == "pool:t6")
    assert "1 box" in pool.title and "1 boxes instead of 2" in pool.text


def test_missing_size_and_unusual_size():
    out = build(
        [
            room("Bedroom", 3000, 3000),
            room("Odd", 40_000, 3000),
            room("Blank", 3000, 3000, length_mm=None),
        ]
    )
    keys = {i.key for i in out.insights}
    assert "implausible_size:Odd" in keys and "size_missing:Blank" in keys
    assert not out.ready


def test_budget_insights_and_room_shares():
    settings = CostSettings(budget=D(5_000))
    out = build([room("Bedroom", 3000, 3000), room("Hall", 2400, 1800)], settings)
    assert out.budget_status == "over"
    shares = {r.name: r.budget_share_pct for r in out.rooms}
    assert shares["Bedroom"] == (out.rooms[0].cost / D(5_000) * 100).quantize(D("0.1"))
    over = next(i for i in out.insights if i.key == "budget_over")
    assert "Bedroom" in over.text
    assert out.insights[0].severity == "warning"  # warnings first


def test_cost_parts_group_lines_and_put_tax_last():
    settings = CostSettings(
        tax_pct=D(18), tax_label="GST",
        lines=[CostLine(kind="labour", label="Fitting", amount=D(500)), CostLine(label="Skip", amount=D(200))],
    )  # fmt: skip
    out = build([room("Bedroom", 3000, 3000)], settings)
    labels = [p.label for p in out.cost_parts]
    assert labels[-1] == "GST" and "Labour" in labels and "Other costs" in labels


def test_unpriced_rooms_are_called_out():
    priced = MaterialOverride(tile=BIG, price=Price(amount=D(900)))
    rooms = [room("Bedroom", 3000, 3000), room("Bath", 2000, 1500, material=priced)]
    out = build(rooms, default=ProjectMaterial(tile=T600, breakage_pct=D(0)))
    assert any(i.key == "unpriced" for i in out.insights)


def test_history_and_timeline():
    versions = [
        {"at": NOW, "label": "Added a room", "user_name": "Asha",
         "metrics": {"ready": True, "boxes": 10, "extra_pct": "8.0", "cost": "9000", "budget": "10000"}},
    ]  # fmt: skip
    events = [{"at": NOW.replace(hour=13), "label": "Commented", "user_name": "Ravi"}]
    out = build([room("Bedroom", 3000, 3000)], versions=versions, events=events)
    assert out.history[0].cost == D(9000) and out.history[0].boxes == 10
    assert [e.label for e in out.timeline] == ["Commented", "Added a room"]
    hidden = build([room("Bedroom", 3000, 3000)], costs_visible=False, versions=versions)
    assert hidden.history[0].cost is None and hidden.history[0].budget is None


# --- Accuracy -----------------------------------------------------------------------------------


def vals(name, length, width, unit="ft"):
    return {"name": name, "length_mm": str(length), "width_mm": str(width), "unit": unit}


def test_field_changes_ignore_swapped_sides():
    assert dash.field_changes(vals("Bed", 3000, 2000), vals("bed", 2000, 3000)) == set()
    assert dash.field_changes(vals("Bed", 3000, 2000), vals("Bedroom", 3000, 2500)) == {
        "name",
        "width",
    }
    assert dash.field_changes(vals("Bed", 3000, 2000), vals("Bed", 3000, 2000, "m")) == {"unit"}
    assert dash.field_changes(vals("Bed", 3000, 2000), vals("Bed", 3300, 2000)) == {"length"}


def outcome(status, method="pdf_text", file_id="f1", flags=(), confidence="high", **kw):
    return {"kind": "extracted", "status": status, "method": method, "file_id": file_id,
            "flags": list(flags), "confidence_level": confidence, **kw}  # fmt: skip


def test_accuracy_by_source_splits_scans_from_photos():
    kinds = {"pdf1": "pdf", "img1": "image", "cad": "dxf"}
    rows = [
        outcome("correct", "pdf_text", "pdf1"),
        outcome("corrected", "vision", "pdf1"),
        outcome("correct", "vision", "img1"),
        outcome("deleted", "vision", "img1"),
        outcome("pending", "dxf_text", "cad"),
    ]
    by = {s.source: s for s in dash.by_source(rows, kinds)}
    assert by["PDF with text"].accuracy_pct == D(100)
    assert by["Scanned PDF"].accuracy_pct == D(0)
    assert by["Photo or image"].reviewed == 2 and by["Photo or image"].accuracy_pct == D(50)
    assert by["CAD drawing"].reviewed == 0 and by["CAD drawing"].accuracy_pct is None


def test_field_correction_rates():
    rows = [
        outcome("correct", extracted=vals("Bed", 3000, 2000), final=vals("Bed", 3000, 2000)),
        outcome("corrected", extracted=vals("Bed", 3000, 2000), final=vals("Bedroom", 3000, 2000)),
        outcome("deleted", extracted=vals("Note", 1, 1), final=vals("Note", 1, 1)),  # not counted
    ]
    rates = {f.field: f for f in dash.field_corrections(rows)}
    assert (
        rates["name"].corrected == 1
        and rates["name"].checked == 2
        and rates["name"].rate_pct == D(50)
    )
    assert rates["length"].corrected == 0


def test_failure_patterns():
    rows = [
        outcome("corrected", flags=["far_from_label"], confidence="low"),
        outcome("correct", flags=["far_from_label"]),
        outcome("pending", flags=["far_from_label"]),  # not reviewed: ignored
    ]
    p = {x.label: x for x in dash.failure_patterns(rows)}
    assert p["Size far from its label"].count == 2 and p["Size far from its label"].wrong_pct == D(
        50
    )
    assert p["Low confidence"].wrong_pct == D(100)


def test_weeks_and_months():
    weeks = dash.last_weeks(NOW)
    assert len(weeks) == 12 and weeks[-1] == "2026-10-12"  # the Monday of this week
    assert dash.week_start(datetime(2026, 10, 18, tzinfo=UTC)) == "2026-10-12"
    months = dash.last_months(NOW)
    assert months[0] == "2025-11" and months[-1] == "2026-10"


def test_tile_usage_typical_extra():
    a = build([room("A", 3000, 3000), room("B", 1300, 1300)])
    from app.schemas.estimate import EstimateOut  # noqa: F401 (type only)

    doc = {"rooms": [room("A", 3000, 3000)], "default_material": ProjectMaterial(tile=T600).model_dump(),
           "plan_unit_confirmed": True}  # fmt: skip
    state = review_state(doc)
    est = build_estimate(state, project_default(doc), extras_settings(doc))
    usage = dash.tile_usage([("p1", est), ("p2", est)])
    assert usage[0].projects == 2 and usage[0].rooms == 2 and usage[0].tile == "600 × 600 mm Ivory"
    assert a.ready
