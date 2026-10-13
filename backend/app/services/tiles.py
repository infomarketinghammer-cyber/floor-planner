"""Tile library rules (PRD 4.5): parse sizes, reconcile tiles-per-box with coverage, format,
and seed the shared catalogue with common sizes by region."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status

from app.engine.calc import Tile
from app.engine.dimensions import DimensionError, parse_length
from app.engine.units import MM2_PER_SQM, MM_PER_UNIT, LengthUnit, mm2_to_sqft, mm2_to_sqm
from app.schemas.material import ProductKind
from app.schemas.tile import TILE_SIZE_UNITS, TileInput, TileOut, TileScope

MIN_SIDE_MM, MAX_SIDE_MM = Decimal(50), Decimal(3600)  # mosaic chips up to large slabs
COVERAGE_TOLERANCE = Decimal("0.02")  # stated coverage may be rounded on the box label
# Roll goods (carpet, sheet vinyl): common widths are 2, 3, 3.66, 4 and 5 m.
ROLL_MIN_WIDTH_MM, ROLL_MAX_WIDTH_MM, ROLL_MAX_LENGTH_MM = (
    Decimal(500),
    Decimal(6000),
    Decimal(100_000),
)

_UNIT_SUFFIX = {
    LengthUnit.MM: "mm",
    LengthUnit.CM: "cm",
    LengthUnit.M: "m",
    LengthUnit.IN: "in",
    LengthUnit.FT: "ft",
}


def _invalid(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def resolve(body: TileInput) -> dict:
    """Validate a tile and return the fields to store. Raises 422 with a user-facing message."""
    if body.size_unit not in TILE_SIZE_UNITS:
        raise _invalid("Tile sizes use mm, cm, m, inches or feet.")
    try:
        length = parse_length(body.length, body.size_unit)
        width = parse_length(body.width, body.size_unit)
    except DimensionError as e:
        raise _invalid(str(e)) from None
    if body.kind == ProductKind.ROLL:
        if not ROLL_MIN_WIDTH_MM <= width <= ROLL_MAX_WIDTH_MM:
            raise _invalid("Roll width must be between 0.5 m and 6 m.")
        if not width <= length <= ROLL_MAX_LENGTH_MM:
            raise _invalid("Roll length must be at least the roll width and at most 100 m.")
        return _fields(body, length, width, 1)
    for side in (length, width):
        if not MIN_SIDE_MM <= side <= MAX_SIDE_MM:
            raise _invalid("Tile sides must be between 50 mm and 3.6 m.")

    area_mm2 = length * width
    if body.tiles_per_box is not None:
        tiles_per_box = body.tiles_per_box
        if body.coverage_per_box_sqm is not None:
            stated = body.coverage_per_box_sqm * MM2_PER_SQM
            actual = tiles_per_box * area_mm2
            if abs(stated - actual) / actual > COVERAGE_TOLERANCE:
                raise _invalid(
                    f"{tiles_per_box} tiles cover {_fmt(mm2_to_sqm(actual))} m², "
                    f"not {_fmt(body.coverage_per_box_sqm)} m². Check the tiles per box or the coverage."
                )
    elif body.coverage_per_box_sqm is not None:
        exact = body.coverage_per_box_sqm * MM2_PER_SQM / area_mm2
        tiles_per_box = int(exact.to_integral_value(rounding=ROUND_HALF_UP))
        if tiles_per_box < 1 or abs(exact - tiles_per_box) / tiles_per_box > COVERAGE_TOLERANCE:
            raise _invalid(
                f"{_fmt(body.coverage_per_box_sqm)} m² isn't a whole number of these tiles "
                f"({_fmt(exact)} tiles). Enter the tiles per box instead."
            )
    else:
        raise _invalid("Enter the tiles per box or the coverage per box.")

    Tile(length, width, tiles_per_box)  # the engine's own checks
    return _fields(body, length, width, tiles_per_box)


def _fields(body: TileInput, length: Decimal, width: Decimal, tiles_per_box: int) -> dict:
    return {
        "name": body.name.strip(),
        "kind": body.kind.value,
        "length_mm": str(length),
        "width_mm": str(width),
        "size_unit": body.size_unit.value,
        "thickness_mm": str(body.thickness_mm) if body.thickness_mm is not None else None,
        "tiles_per_box": tiles_per_box,
        "type": body.type.value,
        "finish": body.finish.value,
        "material": body.material.value,
        "brand": (body.brand or "").strip() or None,
        "code": (body.code or "").strip() or None,
        "vendor": (body.vendor or "").strip() or None,
        "regions": [r.value for r in dict.fromkeys(body.regions)],
        "notes": (body.notes or "").strip() or None,
    }


def _fmt(value: Decimal, places: int = 3) -> str:
    q = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP).normalize()
    return f"{q:f}"


def size_label(length_mm: Decimal, width_mm: Decimal, unit: LengthUnit) -> str:
    per = MM_PER_UNIT[unit]
    return f"{_fmt(length_mm / per, 2)} × {_fmt(width_mm / per, 2)} {_UNIT_SUFFIX[unit]}"


def tile_out(doc: dict, user: dict) -> TileOut:
    length, width = Decimal(doc["length_mm"]), Decimal(doc["width_mm"])
    unit = LengthUnit(doc["size_unit"])
    area = length * width
    box = area * doc["tiles_per_box"]
    is_catalog = doc["scope"] == TileScope.CATALOG
    return TileOut(
        id=str(doc["_id"]),
        scope=doc["scope"],
        owner_id=str(doc["owner_id"]) if doc.get("owner_id") else None,
        name=doc["name"],
        length_mm=length,
        width_mm=width,
        size_unit=unit,
        size_label=size_label(length, width, unit),
        kind=doc.get("kind", ProductKind.TILE.value),
        thickness_mm=Decimal(doc["thickness_mm"]) if doc.get("thickness_mm") else None,
        tiles_per_box=doc["tiles_per_box"],
        tile_area_sqm=float(mm2_to_sqm(area).quantize(Decimal("0.0001"))),
        tile_area_sqft=float(mm2_to_sqft(area).quantize(Decimal("0.0001"))),
        coverage_per_box_sqm=float(mm2_to_sqm(box).quantize(Decimal("0.001"))),
        coverage_per_box_sqft=float(mm2_to_sqft(box).quantize(Decimal("0.01"))),
        type=doc["type"],
        finish=doc["finish"],
        material=doc["material"],
        brand=doc.get("brand"),
        code=doc.get("code"),
        vendor=doc.get("vendor"),
        regions=doc.get("regions", []),
        notes=doc.get("notes"),
        typical=is_catalog and doc.get("typical", False),
        editable=(user["role"] == "admin") if is_catalog else doc.get("owner_id") == user["_id"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


# --- Seed catalogue -------------------------------------------------------------------------
# Typical retail packs; manufacturers vary, so presets are marked "typical" in the UI.
# (name, length, width, unit, thickness mm, tiles/box, type, finish, material, region)
_PRESETS: list[tuple] = [
    ("600×600 vitrified floor", "600", "600", "mm", 9, 4, "floor", "glossy", "vitrified", "india"),
    ("600×600 matt anti-skid", "600", "600", "mm", 9, 4, "anti_skid", "matt", "vitrified", "india"),
    ("800×800 vitrified floor", "800", "800", "mm", 9, 3, "floor", "glossy", "vitrified", "india"),
    (
        "600×1200 vitrified slab",
        "600",
        "1200",
        "mm",
        9,
        2,
        "floor",
        "polished",
        "vitrified",
        "india",
    ),
    (
        "1200×1200 large format",
        "1200",
        "1200",
        "mm",
        10,
        1,
        "floor",
        "polished",
        "vitrified",
        "india",
    ),
    ("400×400 ceramic floor", "400", "400", "mm", 8, 6, "floor", "matt", "ceramic", "india"),
    (
        "300×300 anti-skid (toilet/balcony)",
        "300",
        "300",
        "mm",
        7,
        11,
        "anti_skid",
        "matt",
        "ceramic",
        "india",
    ),
    ("300×600 ceramic wall", "300", "600", "mm", 8, 8, "wall", "glossy", "ceramic", "india"),
    ("300×450 ceramic wall", "300", "450", "mm", 7, 6, "wall", "glossy", "ceramic", "india"),
    ("200×1200 wood-look plank", "200", "1200", "mm", 9, 4, "floor", "matt", "vitrified", "india"),
    ("1×1 ft (12×12 in) floor", "12", "12", "in", 8, 10, "floor", "matt", "porcelain", "imperial"),
    ("2×2 ft (24×24 in) floor", "24", "24", "in", 9, 4, "floor", "matt", "porcelain", "imperial"),
    ("12×24 in porcelain", "12", "24", "in", 9, 8, "floor_wall", "matt", "porcelain", "imperial"),
    ("18×18 in ceramic floor", "18", "18", "in", 8, 5, "floor", "glossy", "ceramic", "imperial"),
    ("6×24 in wood-look plank", "6", "24", "in", 9, 14, "floor", "matt", "porcelain", "imperial"),
    ("3×6 in subway wall", "3", "6", "in", 7, 80, "wall", "glossy", "ceramic", "imperial"),
]


# Other flooring (PRD 4.15), added in catalogue version 2.
# (name, kind, length, width, unit, thickness, pieces/box, type, finish, material, region)
_FLOORING_PRESETS: list[tuple] = [
    (
        "Engineered oak plank 1220×190",
        "plank",
        "1220",
        "190",
        "mm",
        14,
        8,
        "floor",
        "matt",
        "wood",
        "india",
    ),
    (
        "Laminate plank 1380×193",
        "plank",
        "1380",
        "193",
        "mm",
        8,
        8,
        "floor",
        "textured",
        "laminate",
        "india",
    ),
    (
        "Vinyl plank (LVT) 1220×180",
        "plank",
        "1220",
        "180",
        "mm",
        5,
        12,
        "floor",
        "matt",
        "vinyl",
        "india",
    ),
    (
        "Sheet vinyl roll, 2 m wide",
        "roll",
        "25000",
        "2000",
        "mm",
        2,
        1,
        "floor",
        "matt",
        "vinyl",
        "india",
    ),
    (
        "Carpet roll, 4 m wide",
        "roll",
        "25000",
        "4000",
        "mm",
        10,
        1,
        "floor",
        "textured",
        "carpet",
        "india",
    ),
    (
        "Laminate plank 48×7.5 in",
        "plank",
        "48",
        "7.5",
        "in",
        8,
        10,
        "floor",
        "textured",
        "laminate",
        "imperial",
    ),
    (
        "Carpet roll, 12 ft wide",
        "roll",
        "1200",
        "144",
        "in",
        10,
        1,
        "floor",
        "textured",
        "carpet",
        "imperial",
    ),
]
CATALOG_VERSION = 2


def _preset_doc(fields: dict, now: datetime) -> dict:
    return fields | {
        "scope": TileScope.CATALOG.value,
        "owner_id": None,
        "typical": True,
        "archived": False,
        "created_at": now,
        "updated_at": now,
    }


def _flooring_docs(now: datetime) -> list[dict]:
    docs = []
    for (
        name,
        kind,
        length,
        width,
        unit,
        thick,
        per_box,
        type_,
        finish,
        material,
        region,
    ) in _FLOORING_PRESETS:
        roll = kind == ProductKind.ROLL
        fields = resolve(
            TileInput(
                name=name,
                kind=kind,
                length=length,
                width=width,
                size_unit=LengthUnit(unit),
                thickness_mm=Decimal(thick),
                tiles_per_box=None if roll else per_box,
                coverage_per_box_sqm=Decimal(1) if roll else None,  # ignored for rolls
                type=type_,
                finish=finish,
                material=material,
                regions=[region],
            )
        )
        docs.append(_preset_doc(fields, now))
    return docs


async def seed_catalog(db) -> int:
    """Insert the presets once, into an empty catalogue, and later preset sets into existing ones
    (tracked in `meta`, so presets an admin deleted aren't brought back). Returns tiles added."""
    meta = await db.meta.find_one({"_id": "catalog"}) or {}
    version = meta.get("version", 1)
    now = datetime.now(UTC)
    if await db.tiles.count_documents({"scope": TileScope.CATALOG.value}, limit=1):
        if version >= CATALOG_VERSION:
            return 0
        names = {
            d["name"] async for d in db.tiles.find({"scope": TileScope.CATALOG.value}, {"name": 1})
        }
        new = [d for d in _flooring_docs(now) if d["name"] not in names]
        if new:
            await db.tiles.insert_many(new)
        await db.meta.update_one(
            {"_id": "catalog"}, {"$set": {"version": CATALOG_VERSION}}, upsert=True
        )
        return len(new)

    docs = []
    for name, length, width, unit, thick, per_box, type_, finish, material, region in _PRESETS:
        fields = resolve(
            TileInput(
                name=name,
                length=length,
                width=width,
                size_unit=LengthUnit(unit),
                thickness_mm=Decimal(thick),
                tiles_per_box=per_box,
                type=type_,
                finish=finish,
                material=material,
                regions=[region],
            )
        )
        docs.append(_preset_doc(fields, now))
    docs += _flooring_docs(now)
    await db.tiles.insert_many(docs)
    await db.meta.update_one(
        {"_id": "catalog"}, {"$set": {"version": CATALOG_VERSION}}, upsert=True
    )
    return len(docs)
