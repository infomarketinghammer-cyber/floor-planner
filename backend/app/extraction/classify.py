"""Decide whether a piece of plan text is a room name, or noise to ignore (PRD 4.2)."""

import re

# Words that almost always name a room or space on residential/commercial plans (incl. Indian usage).
ROOM_WORDS = {
    "bed",
    "bedroom",
    "bedrm",
    "br",
    "mbr",
    "master",
    "guest",
    "kids",
    "children",
    "nursery",
    "living",
    "lounge",
    "family",
    "drawing",
    "sitting",
    "hall",
    "dining",
    "kitchen",
    "kit",
    "pantry",
    "toilet",
    "bath",
    "bathroom",
    "wc",
    "washroom",
    "powder",
    "ensuite",
    "shower",
    "utility",
    "wash",
    "laundry",
    "store",
    "storage",
    "closet",
    "dress",
    "dressing",
    "wardrobe",
    "walk-in",
    "study",
    "office",
    "library",
    "den",
    "media",
    "theatre",
    "theater",
    "gym",
    "pooja",
    "puja",
    "prayer",
    "mandir",
    "foyer",
    "entrance",
    "entry",
    "lobby",
    "passage",
    "corridor",
    "gallery",
    "landing",
    "balcony",
    "terrace",
    "deck",
    "verandah",
    "veranda",
    "porch",
    "sit-out",
    "sitout",
    "patio",
    "garage",
    "parking",
    "car",
    "stilt",
    "servant",
    "maid",
    "staff",
    "security",
    "guard",
    "reception",
    "cabin",
    "conference",
    "meeting",
    "cafeteria",
    "workstation",
    "server",
    "electrical",
    "shaft",
    "duct",
    "lift",
    "stair",
    "staircase",
    "stairs",
    "mumty",
    "attic",
    "loft",
    "basement",
    "cellar",
    "room",
    "suite",
    "court",
    "courtyard",
    "garden",
    "lawn",
    "multipurpose",
    "games",
    "play",
}

# Door/window/ventilator tags: D1, W2, MD-3, V, KW1a. A number is required except for the bare
# single letters, so labels like "WC" aren't mistaken for tags.
_DOOR_WINDOW_TAG = re.compile(
    r"^(?:(?:d|w|v|dw|md|fd|sd|ed|sl|kw|ow|fw|cw|g|win|dr)\s*-?\s*\d{1,3}[a-z]?|d|w|v)$",
    re.IGNORECASE,
)
_LEVEL_TAG = re.compile(
    r"^(?:\+|-|±)?\s*\d+(?:\.\d+)?\s*(?:mm|m)?\s*(?:lvl|level|ffl|sl)?$", re.IGNORECASE
)
_NOISE = re.compile(
    r"\b(note|notes|scale|north|drawn|checked|approved|revision|rev\.?|date|sheet|title|"
    r"project|client|architect|consultant|plot|survey|road|setback|legend|section|elevation|"
    r"sq\.?\s*(?:ft|m)|sft|sqm|m²|m2|carpet|built[- ]?up|copyright|all dimensions|"
    r"do not scale|lintel|sill|opening|beam|column|footing|slab|plan|floor|level)\b"
    # "Drawing room" and "wash area" are rooms; only title-block / area-table forms are noise.
    r"|\bdrawing\s*(?:no|number|title|#)|\barea\s*[:=-]?\s*\d|\btotal\s+area\b",
    re.IGNORECASE,
)
_HAS_LETTER = re.compile(r"[a-z]", re.IGNORECASE)


def is_noise(text: str) -> bool:
    t = text.strip()
    if len(t) < 2 or not _HAS_LETTER.search(t):
        return True
    if _DOOR_WINDOW_TAG.match(t) or _LEVEL_TAG.match(t):
        return True
    if _NOISE.search(t):
        return True
    words = t.split()
    return len(t) > 40 or len(words) > 5  # sentences and notes, not labels


def name_score(text: str) -> float:
    """1.0 for a recognised room word, 0.5 for a plausible short label, 0 for noise."""
    if is_noise(text):
        return 0.0
    words = {w.strip(".,:-()#").lower() for w in re.split(r"[\s/&]+", text)}
    if words & ROOM_WORDS:
        return 1.0
    # Short alphabetic labels ("STUDIO", "ANNEX") may be rooms; lower confidence.
    letters = sum(c.isalpha() for c in text)
    return 0.5 if letters >= 3 and len(text) <= 25 else 0.0


def clean_name(text: str) -> str:
    """Tidy a label for display: 'BEDROOM  1' -> 'Bedroom 1', keeps short acronyms (WC)."""
    words = re.sub(r"\s+", " ", text.strip(" -:,.")).split(" ")
    return " ".join(
        w if len(w) <= 3 and w.isupper() and w.isalpha() else w.capitalize() for w in words
    )


# --- Room types (PRD 4.9 grouping, 4.15 suggestions) -------------------------------------------
# First match wins, so more specific groups come first ("master bath" is a bathroom).
ROOM_TYPES: list[tuple[str, set[str]]] = [
    (
        "Bathroom & toilet",
        {"toilet", "bath", "bathroom", "wc", "washroom", "powder", "ensuite", "shower"},
    ),
    ("Kitchen", {"kitchen", "kit", "pantry"}),
    ("Bedroom", {"bed", "bedroom", "bedrm", "br", "mbr", "guest", "kids", "children", "nursery"}),
    (
        "Living & dining",
        {
            "living",
            "lounge",
            "family",
            "drawing",
            "sitting",
            "hall",
            "dining",
            "media",
            "theatre",
            "theater",
        },
    ),
    (
        "Balcony & outdoor",
        {
            "balcony",
            "terrace",
            "deck",
            "verandah",
            "veranda",
            "porch",
            "sit-out",
            "sitout",
            "patio",
            "garden",
            "lawn",
            "court",
            "courtyard",
        },
    ),
    (
        "Utility & storage",
        {
            "utility",
            "wash",
            "laundry",
            "store",
            "storage",
            "closet",
            "dress",
            "dressing",
            "wardrobe",
            "walk-in",
        },
    ),
    (
        "Circulation",
        {
            "foyer",
            "entrance",
            "entry",
            "lobby",
            "passage",
            "corridor",
            "gallery",
            "landing",
            "stair",
            "staircase",
            "stairs",
        },
    ),
    (
        "Work & study",
        {
            "study",
            "office",
            "library",
            "den",
            "cabin",
            "conference",
            "meeting",
            "workstation",
            "reception",
        },
    ),
]
OTHER_ROOM_TYPE = "Other"


def room_type(name: str) -> str:
    words = {w.strip(".,:-()#").lower() for w in re.split(r"[\s/&]+", name)}
    for label, vocab in ROOM_TYPES:
        if words & vocab:
            return label
    return OTHER_ROOM_TYPE
