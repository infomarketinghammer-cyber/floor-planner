export type Role = 'contractor' | 'admin'
export type UnitSystem = 'imperial' | 'metric'

export interface User {
  id: string
  name: string
  email: string
  company: string | null
  role: Role
  is_active: boolean
  preferences: { unit_system: UnitSystem }
  created_at: string
}

export type ProjectStatus = 'draft' | 'reviewed' | 'calculated' | 'exported'

export interface Project {
  id: string
  owner_id: string
  name: string
  notes: string | null
  status: ProjectStatus
  room_count: number
  total_area_sqft: number
  total_area_sqm: number
  unconfirmed_rooms: number
  rooms_missing_size: number
  rooms_missing_tile: number
  unit_unconfirmed: boolean
  needs_attention: boolean
  created_at: string
  updated_at: string
  last_exported_at: string | null
}

export interface AdminStats {
  contractors: number
  admins: number
  projects: number
}

export type LengthUnit = 'ft_in' | 'ft' | 'in' | 'm' | 'cm' | 'mm'

export interface UploadWarning {
  code: string
  message: string
}

export interface BlueprintPage {
  index: number
  width: number
  height: number
  has_text: boolean | null
  floor: string | null
  included: boolean
  has_thumbnail: boolean
  warnings: UploadWarning[]
}

export interface Blueprint {
  id: string
  project_id: string
  filename: string
  kind: 'pdf' | 'image' | 'dxf' | 'dwg'
  content_type: string
  size_bytes: number
  detected_unit: LengthUnit | null
  warnings: UploadWarning[]
  pages: BlueprintPage[]
  extraction: ExtractionSummary | null
  created_at: string
}

export interface ExtractionSummary {
  status: 'done' | 'no_rooms' | 'partial' | 'unavailable'
  message: string
  rooms_found: number
  rooms_flagged: number
  pages: { index: number; method: string | null; rooms: number; error: string | null }[]
  ran_at: string
}

export interface ExtractionResult {
  blueprint: Blueprint
  rooms_added: number
  rooms_replaced: number
  rooms_kept: number
}

// --- Material assignment (PRD 4.6) ---------------------------------------------------------
export type Layout = 'straight' | 'diagonal'
export type PriceBasis = 'box' | 'tile' | 'sqft' | 'sqm'
export type MaterialField = 'tile' | 'layout' | 'breakage_pct' | 'price'

export interface Price {
  amount: string
  basis: PriceBasis
}

export interface TileRef {
  id: string
  name: string
  size_label: string
  length_mm: string
  width_mm: string
  tiles_per_box: number
}

/** A room's own settings; null = use the project default. */
export interface MaterialOverride {
  tile: TileRef | null
  layout: Layout | null
  breakage_pct: string | null
  price: Price | null
}

export interface ProjectMaterial {
  tile: TileRef | null
  layout: Layout
  breakage_pct: string
  price: Price | null
}

export interface EffectiveMaterial extends ProjectMaterial {
  overridden: MaterialField[]
}

export interface Exclusion {
  id: string
  label: string
  length_mm: string
  width_mm: string
  quantity: number
  unit: LengthUnit
}

export interface MaterialsSummary {
  rooms_needing_tile: number
  skipped: number
  rooms_over_excluded: number
  ready_for_calculation: boolean
}

export interface RoomSource {
  file_id: string
  page: number
  method: 'pdf_text' | 'dxf_text' | 'vision'
  bbox: number[] | null
  text: string
}

export interface Room {
  id: string
  name: string
  floor: string | null
  length_mm: string | null // exact decimal millimetres
  width_mm: string | null
  unit: LengthUnit
  confirmed: boolean
  skipped: boolean
  tile_id: string | null
  origin: 'auto' | 'edited' | 'manual' | 'imported'
  confidence: number | null
  confidence_level: 'high' | 'medium' | 'low' | null
  flags: string[]
  unit_explicit: boolean
  source: RoomSource | null
  material: MaterialOverride
  exclusions: Exclusion[]
  area_mm2: string | null // odd-shaped rooms known only by area
  extracted: ExtractedValues | null // what the plan reader read; never changes
}

/** What extraction read for a room, kept through later edits (PRD 4.13). */
export interface ExtractedValues {
  name: string
  length_mm: string | null
  width_mm: string | null
  unit: LengthUnit
}

export interface RoomIssue {
  code: string
  severity: 'block' | 'warn'
  message: string
}

/** A room as returned by the review endpoints, with server-computed issues (PRD 4.3). */
export interface ReviewRoom extends Room {
  issues: RoomIssue[]
  effective: EffectiveMaterial
  exclusion_area_mm2: string
  usable_area_mm2: string | null
}

export interface ReviewSummary {
  total: number
  confirmed: number
  to_review: number
  with_issues: number
  blocking: number
  unit_pending: boolean
  ready: boolean
}

/** The plan unit (PRD 4.4): rooms without their own written unit follow it. */
export interface PlanUnit {
  unit: LengthUnit | null // confirmed, else detected
  confirmed: boolean
  detected: LengthUnit | null
  evidence: string
  required: boolean // rooms came from a plan, so the unit must be confirmed
}

export interface RoomsState {
  version: number
  rooms: ReviewRoom[]
  review: ReviewSummary
  plan_unit: PlanUnit
  default_material: ProjectMaterial
  materials: MaterialsSummary
  estimate: Estimate // recalculated on every change
  cost_settings: CostSettings
  cost: Cost | null // null until the quantities are ready
}

export interface RoomUpdate {
  name?: string
  floor?: string | null
  length?: string
  width?: string
  unit?: LengthUnit
  skipped?: boolean
  follow_plan_unit?: boolean
  confirmed?: boolean
}

export interface RoomImportResult {
  dry_run: boolean
  rooms: Room[]
  errors: { row: number; message: string }[]
}

// --- Tile library (PRD 4.5) ---------------------------------------------------------------
export type TileType = 'floor' | 'wall' | 'floor_wall' | 'anti_skid' | 'outdoor'
export type TileFinish = 'matt' | 'glossy' | 'satin' | 'polished' | 'textured' | 'other'
export type TileMaterial = 'vitrified' | 'ceramic' | 'porcelain' | 'natural_stone' | 'mosaic' | 'other'
export type TileRegion = 'india' | 'imperial'
export type TileSizeUnit = 'mm' | 'cm' | 'm' | 'in' | 'ft'

export interface Tile {
  id: string
  scope: 'catalog' | 'user'
  owner_id: string | null
  name: string
  length_mm: string
  width_mm: string
  size_unit: TileSizeUnit
  size_label: string
  thickness_mm: string | null
  tiles_per_box: number
  tile_area_sqm: number
  tile_area_sqft: number
  coverage_per_box_sqm: number
  coverage_per_box_sqft: number
  type: TileType
  finish: TileFinish
  material: TileMaterial
  brand: string | null
  code: string | null
  regions: TileRegion[]
  notes: string | null
  typical: boolean
  editable: boolean
  created_at: string
  updated_at: string
}

export interface TileInput {
  name: string
  length: string
  width: string
  size_unit: TileSizeUnit
  thickness_mm: string | null
  tiles_per_box: number | null
  coverage_per_box_sqm: string | null
  type: TileType
  finish: TileFinish
  material: TileMaterial
  brand: string | null
  code: string | null
  regions: TileRegion[]
  notes: string | null
}

// --- Quantities (PRD 4.7) -------------------------------------------------------------------
export interface RoomEstimate {
  room_id: string
  name: string
  floor: string | null
  room_type: string // e.g. "Bedroom", "Bathroom & toilet"
  tile: TileRef
  layout: Layout
  method: 'grid' | 'area'
  method_reason: string
  allowance_pct: string
  breakage_pct: string
  room_area_mm2: string
  usable_area_mm2: string
  columns: number | null
  rows: number | null
  grid_tiles: number
  excluded_tiles: number
  tiles_needed: number
  cut_waste_mm2: string
  cut_waste_pct: string
  buffer_tiles: number
  tiles_required: number
  boxes: number
  tiles_bought: number
  extra_area_mm2: string
  // Waste breakdown (PRD 4.8): extra = cut waste + buffer + rounding.
  buffer_area_mm2: string
  rounding_tiles: number
  rounding_area_mm2: string
  extra_pct: string
  high_waste: boolean
  waste_hint: string | null
}

export interface Assumption {
  key: string
  title: string
  text: string
}

export interface TileTotal {
  tile: TileRef
  rooms: number
  usable_area_mm2: string
  tiles_required: number
  boxes: number
  tiles_bought: number
  bought_area_mm2: string
  boxes_if_pooled: number
}

export interface Estimate {
  ready: boolean
  blockers: string[]
  rooms: RoomEstimate[]
  tiles: TileTotal[]
  totals: {
    rooms: number
    room_area_mm2: string
    usable_area_mm2: string
    cut_waste_mm2: string
    buffer_area_mm2: string
    rounding_area_mm2: string
    bought_area_mm2: string
    extra_area_mm2: string
    cut_waste_pct: string
    extra_pct: string
    high_waste_rooms: number
    boxes: number
  } | null
  assumptions: Assumption[]
  offcut_note: string
}

// --- Cost estimate (PRD 4.10) ---------------------------------------------------------------
export type LineKind = 'delivery' | 'labour' | 'other'
export type LineBasis = 'fixed' | 'sqft' | 'sqm' | 'box'

/** An extra cost on top of the tiles. Amounts are decimal strings. */
export interface CostLine {
  id?: string // assigned by the server for new lines
  kind: LineKind
  label: string
  amount: string
  basis: LineBasis
  taxable: boolean
}

export interface CostSettings {
  currency: string // ISO 4217, e.g. "INR"
  locale: string // number format, e.g. "en-IN"
  tax_label: string
  tax_pct: string
  tax_materials: boolean
  lines: CostLine[]
  budget: string | null
}

export interface RoomCost {
  room_id: string
  price: Price | null
  price_per_box: string | null
  cost: string | null // boxes × price per box; null when the room has no price
}

export interface CostLineResult {
  id: string
  kind: LineKind
  label: string
  basis: LineBasis
  rate: string // the amount as entered
  quantity: string | null // sq ft, m² or boxes; null for fixed amounts
  amount: string
  taxable: boolean
}

export interface Cost {
  has_prices: boolean // false: hide the cost columns
  priced_rooms: number
  unpriced_rooms: number
  rooms: RoomCost[]
  materials: string | null
  lines: CostLineResult[]
  tax: { label: string; pct: string; base: string; amount: string } | null
  total: string
  budget: { target: string; remaining: string; used_pct: string; status: 'under' | 'near' | 'over' } | null
  warnings: string[]
}

// --- Feedback and accuracy (PRD 4.13, 6.5) -------------------------------------------------------
export interface Feedback {
  id: string
  room_id: string | null // null: the whole project
  room_name: string | null
  right: boolean
  estimated_boxes: number
  actual_boxes: number | null
  comment: string | null
  created_at: string
}

export interface RoomValues {
  name: string
  length_mm: string | null
  width_mm: string | null
  unit: LengthUnit
}

export interface Correction {
  room_id: string
  status: 'corrected' | 'deleted' | 'added'
  fields: ('name' | 'size')[]
  extracted: RoomValues | null
  final: RoomValues | null
}

export interface AccuracySummary {
  rooms_read: number
  pending: number
  correct: number
  corrected: number
  names_corrected: number
  sizes_corrected: number
  deleted: number
  added: number
  accuracy_pct: string | null
  name_accuracy_pct: string | null
  size_accuracy_pct: string | null
  found_pct: string | null
  by_method: { method: string; read: number; reviewed: number; correct: number; accuracy_pct: string | null }[]
  corrections: Correction[]
}

export interface ProjectAccuracy {
  summary: AccuracySummary | null // null: no rooms were read from a plan
  evaluation: { in_eval_set: boolean; added_at: string | null; eligible: boolean; reason: string | null }
}

export interface AdminAccuracy {
  extraction: AccuracySummary
  feedback: {
    total: number
    right: number
    wrong: number
    right_pct: string | null
    wrong_on_extracted_rooms: number
    wrong_on_corrected_rooms: number
    recent: {
      room_name: string | null
      estimated_boxes: number
      actual_boxes: number | null
      comment: string | null
      origin: string | null
      created_at: string
    }[]
  }
}

export interface EvalEntry {
  id: string
  project_name: string | null
  files: number
  rooms: number
  accuracy_pct_at_add: string | null
  created_at: string
}

// --- Privacy (PRD 4.14) --------------------------------------------------------------------------
/** How this deployment handles uploaded plans, from its real settings. */
export interface PrivacyInfo {
  ai_reading_enabled: boolean
  ai_provider: string | null
  files_encrypted_at_rest: boolean
  data_location: string | null
  email_enabled: boolean
  email_provider: string | null
  retention: string
  max_upload_mb: number
}
