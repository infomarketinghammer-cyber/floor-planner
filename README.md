# Floor Planner

Turns a floor plan into a tile material estimate: upload a blueprint, confirm the extracted rooms,
assign tiles, and get per-room quantities, waste, boxes and cost. See [docs/](docs/) for the PRD.

## Architecture

```
Browser (React + Tailwind)
   │  /api/*  (httpOnly session cookie)
   ▼
Express gateway  :4000   routing, auth cookie, role guards, rate limiting, serves React in prod
   │  /api/v1/*  (Bearer JWT)
   ▼
FastAPI backend  :8000   business logic, extraction, deterministic calc engine, exports
   │
   ▼
MongoDB          :27017
```

- **Express owns routing and the session.** On login/register it calls FastAPI, receives a JWT and
  stores it in an `httpOnly`, `SameSite=Strict` cookie. Every `/api/*` request is authenticated and
  role-checked at the gateway, then proxied to FastAPI as `/api/v1/*` with the token as a Bearer header.
- **FastAPI re-checks everything** (token, user still active, role, ownership), so it is safe even if
  the gateway is bypassed.
- **The calculation engine** (`backend/app/engine`) is pure, deterministic Python using `Decimal`
  millimetres. No AI is ever called from it (PRD 6.3).

### Roles

| Role         | How created                                   | Can                                                                 |
| ------------ | --------------------------------------------- | ------------------------------------------------------------------- |
| `contractor` | Self-registration at `/register`              | Manage their own projects                                           |
| `admin`      | Seeded from `ADMIN_EMAIL`/`ADMIN_PASSWORD` on first start, or promoted by an admin | Everything a contractor can, see all projects, manage users (role, enable/disable) |

Route guards:

| Path              | Gateway                 | FastAPI                    |
| ----------------- | ----------------------- | -------------------------- |
| `/api/auth/*`     | public, rate-limited    | public                     |
| `/api/projects/*` | contractor, admin       | owner only (admin: all)    |
| `/api/admin/*`    | admin                   | admin                      |

## Project layout

```
floor-planner/
├── frontend/          React 19 + Vite + TypeScript + Tailwind v4 + React Router
│   └── src/
│       ├── api/       typed fetch client and API types
│       ├── auth/      AuthContext, RequireAuth route guard
│       ├── components/ layout and shared UI
│       └── pages/     Login, Register, Projects, admin/
├── gateway/           Express 5
│   └── src/
│       ├── server.js  route groups, role guards, proxy, static serving
│       ├── routes/    auth (login/register/logout/me + session cookie)
│       └── middleware/ authenticate, requireRole
├── backend/           FastAPI (Python 3.11+)
│   ├── app/
│   │   ├── api/v1/    routers: auth, projects, files, rooms, materials, cost, exports, feedback, admin
│   │   ├── core/      settings, password hashing, JWT
│   │   ├── db/        MongoDB client + indexes
│   │   ├── schemas/   Pydantic request/response models
│   │   ├── engine/    deterministic units + tile/waste/box calculation
│   │   ├── extraction/ blueprint extraction pipeline
│   │   ├── exports/   PDF report, Excel workbook, shopping list
│   │   └── evaluation.py  evaluation set: add verified plans, score the extractor
│   ├── devserver.py   dev entry point used with auto-reload
│   └── tests/         pytest (engine golden cases, incl. PRD acceptance examples)
├── eval/              local exports of the evaluation set (gitignored plans)
├── docs/              PRD
└── scripts/           dev helpers
```

## Inputs (PRD 4.1)

- **Blueprints**: PDF, JPG, PNG, DXF, DWG. Stored in MongoDB GridFS (`files` bucket); metadata in
  the `blueprints` collection. Each file is validated on upload: extension, actual content (magic
  bytes), size (`MAX_UPLOAD_MB`, default 25), page count (`MAX_PDF_PAGES`, default 50) and that it
  opens. Per page we store a thumbnail, whether it has a text layer, a guessed floor ("Ground Floor"
  from page text), and quality warnings.
- **Quality warnings** (`backend/app/uploads/quality.py`): low resolution, blur, skew, blank/faint
  page, scanned PDF (no text layer → OCR), DXF without text or units. They never block an upload.
  Thresholds are starting points to tune with the evaluation set.
- **DWG** needs the [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
  (check its licence). Set `ODA_CONVERTER_PATH` in `backend/.env`; without it, DWG uploads are
  rejected with a message asking for DXF or PDF.
- **Room lists**: `.xlsx`/`.csv` with Room, Length, Width, optional Unit and Floor (or one Size column
  like `12'0" x 10'0"`). Import is previewed first (`dry_run`), with per-row errors.
- **Manual entry** accepts `12'6"`, `12.5`, `3.6 m`, `3600 mm`, etc. (`backend/app/engine/dimensions.py`).
  All lengths are stored as exact decimal millimetres.

## Blueprint extraction (PRD 4.2)

`POST /api/projects/:id/files/:fileId/extract` (run automatically after upload, or "Read again").

| Input | How it's read | Code |
|---|---|---|
| Digital PDF page | Positioned text from the PDF, no AI | `extraction/sources.py` |
| DXF / DWG (converted on upload) | TEXT, MTEXT, block attributes; DIMENSION entities ignored | `extraction/sources.py` |
| Photo / scanned page | Vision model reads labels + positions only | `extraction/vision.py` |

Then the same deterministic code for every source: sizes parsed (`12'0" x 10'0"`, `3.6 x 3.0 m`,
`3600 x 3000`, `12x10`), bare units resolved from the drawing's units or the page's written
convention (else guessed from the values and flagged), names paired to sizes by position
(`extraction/pairing.py`), and noise dropped (door/window tags, notes, scale, titles, area tables,
wall dimension lines: `extraction/classify.py`).

Every room gets a confidence (0–1, high/medium/low), review flags (`unit_assumed`,
`ambiguous_pairing`, `size_missing`, …) and a source (file, page, box, method, raw text). Rooms
always arrive **unconfirmed**. Re-running replaces only that file's untouched auto rooms; edited,
manual and imported rooms are kept.

Vision needs `ANTHROPIC_API_KEY` (model `claude-opus-5-5`, effort `high`, server-side refusal
fallback). Without it, photos/scans report "not set up" and users enter rooms manually.

## Room review (PRD 4.3)

- Every room change goes through `services/projects.save_rooms`, which bumps `rooms_version` and
  sets the project status (`reviewed` when every room is confirmed, otherwise `draft`).
- Review issues are computed on the server (`services/review.py`) from the whole list:
  **block** = size missing, name missing (can't be confirmed); **warn** = duplicate, implausible
  size, low confidence, assumed unit, unclear pairing.
- Editing a size or unit un-confirms a room; renaming doesn't. Changing only the unit re-reads the
  same numbers (fixes "3600 × 3000 assumed mm, actually cm"). Edited auto rooms become `edited`.
- Undo/redo: the client keeps snapshots and restores them with `PUT /rooms` + the version it last
  saw; a mismatch returns 409 instead of overwriting changes from another tab.
- `GET /files/:id/pages/:n/preview` renders a 1600 px page in the same frame as the thumbnail, so
  stored source boxes line up for highlighting.

## Units (PRD 4.4)

- **Storage:** every length is exact decimal millimetres; `unit` on a room is only how it was
  written/entered. All conversions go through `engine/units.py`.
- **Plan unit:** detected on read (`services/plan_units.py`) from, in order: the CAD drawing's
  declared units → the majority unit written on the plan → the look of bare numbers. The reason is
  shown to the user. Projects with rooms read from a plan aren't "reviewed" until the user
  confirms it (`PUT /rooms/plan-unit`).
- **Overrides:** rooms with `unit_explicit=false` follow the plan unit. Changing the plan unit
  re-reads their numbers in the new unit and un-confirms any whose size changes. A room given its
  own unit is an override; choosing "Plan" in its unit menu makes it follow the plan again.
- **Display:** `users.preferences.unit_system` (`imperial` → sq ft, `metric` → m²), set from the
  header and saved to the account (`PUT /users/me/preferences`).

## Tile library (PRD 4.5)

- `tiles` collection, two scopes: **catalog** (shared; admins create/edit with `?catalog=true`)
  and **user** (a contractor's own, private). Contractors can copy a catalogue tile to "My tiles"
  to set their supplier's pack size.
- Seeded once on startup with common sizes (`services/tiles.py` `_PRESETS`): India/metric
  (600×600, 800×800, 600×1200, …) and imperial (1×1 ft, 2×2 ft, 12×24 in, …). Pack sizes are
  marked *typical*; editing a preset clears that mark.
- Sizes are entered in mm/cm/m/in/ft and stored as exact mm. Enter tiles per box, or coverage per
  box (must be a whole number of tiles within 2%); coverage is always derived from the count.
- Deleting archives a tile (hidden from the library) so projects that use it keep working.

## Material assignment (PRD 4.6)

- **Project defaults** (`project.default_material`): tile, layout (straight/diagonal), breakage
  buffer % (default 5), optional price per box / tile / sq ft / m². `PUT /materials/default`.
- **Per-room overrides** (`room.material`): each setting separately; `null` = use the default.
  `effective` on every room in the rooms API shows what's actually used and which settings are
  the room's own. Bulk changes (edit, copy from a room, reset to default, skip) go through
  `POST /rooms/materials`.
- **Tile snapshots:** assigning stores a `TileRef` (size, pack) so later library edits don't
  silently change an estimate.
- **Exclusions** (`room.exclusions`): untiled areas (L × W × qty), `PUT /rooms/:id/exclusions`;
  rejected if they'd cover the whole room. How they reduce tile counts is decided in PRD 4.7.
- **Skipped rooms** need no tiling: they're left out of review, area totals and tile checks.
- `materials.ready_for_calculation` = review done (rooms + plan unit) and every non-skipped room
  has a tile. Material changes share the rooms' version and undo history.

## Quantity calculation (PRD 4.7)

Engine: `backend/app/engine/calc.py` (pure, exact `Decimal` mm; unit-tested against hand
calculations, including the PRD acceptance examples).

| Room | Method |
|---|---|
| Rectangular, straight layout | **Grid**: columns = ⌈L ÷ tile L⌉, rows = ⌈W ÷ tile W⌉, minus tiles an untiled area is *certain* to cover (⌊span ÷ tile⌋ − 1 per side, worst orientation), so it never under-orders |
| Diagonal layout | **By area** + 15% cutting allowance (`DIAGONAL_ALLOWANCE_PCT`) |
| Known only by floor area (odd shapes) | **By area** + 10% (`AREA_ONLY_ALLOWANCE_PCT`) |

Then: buffer = ⌈tiles needed × buffer %⌉, boxes = ⌈tiles ÷ tiles per box⌉. Totals are the sum of
the rooms; `boxes_if_pooled` shows the saving if leftovers are shared between rooms. Cut waste
ignores offcut reuse (slightly conservative).

`services/estimate.py` builds the estimate only when the project is ready (rooms confirmed, plan
unit confirmed, every room has a tile); otherwise it lists what's missing. It's returned with
every room/material change (instant recalculation) and at `GET /projects/:id/estimate`. Project
status becomes `calculated` while quantities are available.

## Waste analysis (PRD 4.8)

Every room and the project report the extra area bought over the area to tile, split exactly:
**extra = cut waste + breakage buffer + box rounding** (tested for every pack size and both
methods). Cut waste = tiles needed × tile area − usable area (grid area for straight layouts,
the cutting allowance for diagonal/area-only rooms). All parts are given as area and as % of the
area to tile; rooms with cut waste over 20% are flagged with a hint.

`estimate.assumptions` is a plain-language list generated from the project (methods per room,
buffers, untiled areas, rounding, units, what's not included), plus `offcut_note`. The UI shows
them under "How these numbers were worked out"; exports (PRD 4.11) will include the same text.

## Results table (PRD 4.9)

- `components/results/ResultsTable.tsx`: one row per room. **Basic** (room, size, area, tile,
  boxes, tiles bought) or **Detailed** (+ tiles in grid, cut waste, buffer, extra area, each with
  %). **Group by** floor or room type with subtotals; the project total row is always the sum
  of the rooms. View choices are remembered per browser (`localStorage`, optional).
- Room types come from the server (`extraction/classify.room_type`: Bedroom, Kitchen, Bathroom &
  toilet, Living & dining, …) so exports group the same way.
- `components/results/ResultsOverlay.tsx`: each plan page with rooms outlined in their tile's
  colour and labelled with their boxes; selecting a row highlights it on the plan and vice versa.
  Rooms added by hand/imported are listed as "not on a plan".

## Setup

Prerequisites: Node 22+, Python 3.11+, MongoDB running on `localhost:27017`.

```bash
# 1. Install JS dependencies
npm install
npm --prefix gateway install
npm --prefix frontend install

# 2. Backend virtualenv
cd backend
py -3.11 -m venv .venv            # macOS/Linux: python3 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip ...
cd ..

# 3. Environment: copy the examples and set the SAME long random JWT_SECRET in both
cp backend/.env.example backend/.env
cp gateway/.env.example gateway/.env
```

## Run

```bash
npm run dev     # FastAPI :8000, Express :4000, Vite :5173 — open http://localhost:5173
npm test        # backend tests
```

Production: `npm run build` then `npm start`. Express serves `frontend/dist` and the API on one port.
Run FastAPI separately (e.g. `uvicorn app.main:app --host 127.0.0.1 --port 8000`) and set
`NODE_ENV=production` so the session cookie is `Secure` (requires HTTPS).

Note: dev auto-reload for the backend uses `watchfiles` instead of `uvicorn --reload`, because
uvicorn's reloader hangs on Windows when its output is piped.

## Exports (PRD 4.11)

`GET /api/projects/:id/exports/report.pdf`, `estimate.xlsx` and `shopping-list.pdf`. The workbook
uses live formulas (boxes, totals, costs, tax, budget). Emailing the shopping list goes through
[Resend](https://resend.com): set `RESEND_API_KEY` and `EMAIL_FROM` (a sender on a domain verified in
Resend) in `backend/.env`; without them the email option is hidden. PDFs use Arial (Windows) or
DejaVu Sans (Linux, `fonts-dejavu-core`) so currency signs like ₹ render.

## Feedback and accuracy (PRD 4.13, 6.5)

- Every extracted room keeps what was read (`extracted`), so edits are measurable. After each room
  change, one outcome per room is written to `extraction_outcomes`: right as read, corrected (name
  and/or size), removed (not a real room), missed (added by hand) or still pending.
- Each project shows a plan reading summary; admins see accuracy across all projects by method.
- "Was this quantity right?" answers are stored in `feedback` with a snapshot of the estimate.
- **Evaluation set**: users opt in per verified project; a copy of the plan goes to the `eval`
  GridFS bucket with the confirmed room list as ground truth. It survives project deletion until
  the user or an admin removes it. Score the current extractor against it:

  ```
  cd backend
  python -m app.evaluation                    # per plan and overall
  python -m app.evaluation --export ../eval/plans   # also write files + truth.json
  ```

Deleting a project deletes its outcomes and feedback.
