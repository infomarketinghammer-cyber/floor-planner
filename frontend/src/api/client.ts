import type {
  AdminStats,
  Blueprint,
  CostSettings,
  OpeningKind,
  SkirtingSettings,
  Suggestion,
  RoomLayout,
  Comparison,
  ScenarioInput,
  CompanyProfile,
  ExtraQuoteLine,
  Quote,
  QuoteClient,
  QuoteStatus,
  TileAdvice,
  TileUpdate,
  SundriesSettings,
  AdminAccuracy,
  EvalEntry,
  Feedback,
  ProjectAccuracy,
  PrivacyInfo,
  ExtractionResult,
  LengthUnit,
  Project,
  Room,
  RoomImportResult,
  Layout,
  MaterialField,
  Price,
  ProjectMaterial,
  RoomsState,
  RoomUpdate,
  Tile,
  TileInput,
  TileRegion,
  TileType,
  User,
} from './types.ts'
import type { AreaUnit } from '../lib/format.ts'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors: [{ loc, msg }, ...]
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return fallback
}

// --- Guest mode (PRD 4.12): no account, projects in this browser ---------------------------
let guestMode = false
/** Set by AuthContext. While on, project calls go through the guest dispatcher (api/guest.ts). */
export function setGuestMode(on: boolean) {
  guestMode = on
}
export function isGuestMode(): boolean {
  return guestMode
}
// Paths that always talk to the real API: sign-in, public pages.
const ALWAYS_REMOTE = /^\/(auth|public)\//

function viaGuest(path: string): boolean {
  return guestMode && !ALWAYS_REMOTE.test(path)
}

/** Preferences live in the browser for guests. */
async function guestPreferences(preferences: User['preferences']): Promise<User> {
  const { guestId, localStore } = await import('../lib/localStore.ts')
  await localStore.set('preferences', preferences)
  return guestUser(await guestId(), preferences)
}

export function guestUser(id: string, preferences: User['preferences']): User {
  return {
    id,
    name: 'Guest',
    email: '',
    company: null,
    role: 'contractor',
    is_active: true,
    preferences,
    created_at: new Date(0).toISOString(),
  }
}

async function guestRequest<T>(path: string, init: RequestInit): Promise<T> {
  const { guestCall, GuestError } = await import('./guest.ts')
  const method = init.method ?? 'GET'
  let body: unknown
  let upload: { field: string; file: File; form: Record<string, string> } | undefined
  if (typeof init.body === 'string') body = JSON.parse(init.body)
  else if (init.body instanceof FormData) {
    const form: Record<string, string> = {}
    let file: File | null = null
    let field = 'file'
    for (const [key, value] of init.body.entries()) {
      if (value instanceof File) {
        file = value
        field = key
      } else form[key] = value
    }
    if (file) upload = { field, file, form }
  }
  try {
    const result = await guestCall(method, path, body, upload)
    return result.body as T
  } catch (err) {
    if (err instanceof GuestError) throw new ApiError(err.status, err.message)
    throw err
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (viaGuest(path)) {
    if (path === '/users/me/preferences') {
      return (await guestPreferences(JSON.parse(String(init.body)))) as T
    }
    return guestRequest<T>(path, init)
  }
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    // FormData bodies set their own multipart content-type.
    headers: typeof init.body === 'string' ? { 'content-type': 'application/json', ...init.headers } : init.headers,
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response.statusText))
  return body as T
}

/** A file from the API, with the name the server gave it (Content-Disposition). */
async function requestFile(path: string): Promise<{ blob: Blob; filename: string }> {
  if (viaGuest(path)) {
    const { guestCall, GuestError } = await import('./guest.ts')
    try {
      const result = await guestCall('GET', path)
      return { blob: result.blob ?? new Blob(), filename: result.filename ?? 'export' }
    } catch (err) {
      if (err instanceof GuestError) throw new ApiError(err.status, err.message)
      throw err
    }
  }
  const response = await fetch(`/api${path}`, { credentials: 'same-origin' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, errorMessage(body, response.statusText))
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1]
  return { blob: await response.blob(), filename: encoded ? decodeURIComponent(encoded) : (plain ?? 'export') }
}

function formData(fields: Record<string, string | File>): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) form.append(key, value)
  return form
}

/** fetch() can't report upload progress, so large blueprint uploads use XHR. */
function uploadWithProgress<T>(path: string, body: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  if (viaGuest(path)) {
    onProgress?.(0.5) // the file is read and sent in one go
    return guestRequest<T>(path, { method: 'POST', body }).finally(() => onProgress?.(1))
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api${path}`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as T)
      else reject(new ApiError(xhr.status, errorMessage(xhr.response, xhr.statusText || 'Upload failed')))
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error. Check your connection and try again.'))
    xhr.send(body)
  })
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  body: data === undefined ? undefined : JSON.stringify(data),
})

export const api = {
  auth: {
    me: () => request<{ user: User }>('/auth/me'),
    login: (email: string, password: string) =>
      request<{ user: User }>('/auth/login', json('POST', { email, password })),
    register: (data: { name: string; email: string; password: string; company?: string }) =>
      request<{ user: User }>('/auth/register', json('POST', data)),
    logout: () => request<void>('/auth/logout', json('POST')),
  },
  projects: {
    list: () => request<Project[]>('/projects'),
    get: (id: string) => request<Project>(`/projects/${id}`),
    create: (data: { name: string; notes?: string }) =>
      request<Project>('/projects', json('POST', data)),
    update: (id: string, data: { name?: string; notes?: string | null }) =>
      request<Project>(`/projects/${id}`, json('PATCH', data)),
    duplicate: (id: string) => request<Project>(`/projects/${id}/duplicate`, json('POST')),
    remove: (id: string) => request<void>(`/projects/${id}`, json('DELETE')),
  },
  files: {
    list: (projectId: string) => request<Blueprint[]>(`/projects/${projectId}/files`),
    upload: (projectId: string, file: File, onProgress?: (fraction: number) => void) =>
      uploadWithProgress<Blueprint>(`/projects/${projectId}/files`, formData({ file }), onProgress),
    updatePage: (projectId: string, fileId: string, page: number, data: { floor?: string | null; included?: boolean }) =>
      request<Blueprint>(`/projects/${projectId}/files/${fileId}/pages/${page}`, json('PATCH', data)),
    remove: (projectId: string, fileId: string) =>
      request<void>(`/projects/${projectId}/files/${fileId}`, json('DELETE')),
    extract: (projectId: string, fileId: string) =>
      request<ExtractionResult>(`/projects/${projectId}/files/${fileId}/extract`, json('POST')),
    thumbnailUrl: (projectId: string, fileId: string, page: number) =>
      `/api/projects/${projectId}/files/${fileId}/pages/${page}/thumbnail`,
    downloadUrl: (projectId: string, fileId: string) => `/api/projects/${projectId}/files/${fileId}/download`,
    download: (projectId: string, fileId: string) => requestFile(`/projects/${projectId}/files/${fileId}/download`),
    previewUrl: (projectId: string, fileId: string, page: number) =>
      `/api/projects/${projectId}/files/${fileId}/pages/${page}/preview`,
  },
  rooms: {
    list: (projectId: string) => request<RoomsState>(`/projects/${projectId}/rooms`),
    add: (
      projectId: string,
      data: {
        name: string
        floor?: string
        length?: string
        width?: string
        unit: LengthUnit
        area?: string
        area_unit?: 'sqft' | 'sqm'
      },
    ) => request<RoomsState>(`/projects/${projectId}/rooms`, json('POST', data)),
    update: (projectId: string, roomId: string, data: RoomUpdate) =>
      request<RoomsState>(`/projects/${projectId}/rooms/${roomId}`, json('PATCH', data)),
    confirm: (projectId: string, roomIds: string[], confirmed = true) =>
      request<RoomsState>(`/projects/${projectId}/rooms/confirm`, json('POST', { room_ids: roomIds, confirmed })),
    /** Undo/redo: put back a snapshot. `version` is the version the client last saw. */
    restore: (
      projectId: string,
      version: number,
      rooms: Room[],
      planUnit: { unit: LengthUnit | null; confirmed: boolean },
      defaultMaterial: ProjectMaterial,
    ) =>
      request<RoomsState>(
        `/projects/${projectId}/rooms`,
        json('PUT', {
          version,
          rooms,
          plan_unit: planUnit.unit,
          plan_unit_confirmed: planUnit.confirmed,
          default_material: defaultMaterial,
        }),
      ),
    setPlanUnit: (projectId: string, unit: LengthUnit, version: number) =>
      request<RoomsState>(`/projects/${projectId}/rooms/plan-unit`, json('PUT', { unit, version })),
    remove: (projectId: string, roomId: string) =>
      request<RoomsState>(`/projects/${projectId}/rooms/${roomId}`, json('DELETE')),
    import: (
      projectId: string,
      file: File,
      options: { defaultUnit: LengthUnit; mode: 'append' | 'replace'; dryRun: boolean },
    ) =>
      request<RoomImportResult>(`/projects/${projectId}/rooms/import`, {
        method: 'POST',
        body: formData({
          file,
          default_unit: options.defaultUnit,
          mode: options.mode,
          dry_run: String(options.dryRun),
        }),
      }),
  },
  materials: {
    setDefault: (
      projectId: string,
      data: {
        tile_id: string | null
        layout: Layout
        breakage_pct: string
        price: Price | null
        brick_offset_pct: string
        reuse_offcuts: boolean
      },
      version: number,
    ) => request<RoomsState>(`/projects/${projectId}/materials/default`, json('PUT', { ...data, version })),
    /** Split a room into rectangles (PRD 4.16); an empty list makes it one rectangle again. */
    setRoomParts: (
      projectId: string,
      roomId: string,
      data: {
        parts: { label: string; length: string; width: string; x: string; y: string }[]
        perimeter: string | null
        unit: LengthUnit
      },
      version: number,
    ) =>
      request<RoomsState>(`/projects/${projectId}/rooms/${roomId}/parts`, json('PUT', {
        ...data,
        parts: data.parts.map((p) => ({ ...p, x: p.x || null, y: p.y || null })),
        version,
      })),
    roomLayout: (projectId: string, roomId: string) => request<RoomLayout>(`/projects/${projectId}/rooms/${roomId}/layout`),
    tileAdvice: (projectId: string) => request<TileAdvice>(`/projects/${projectId}/tile-advice`),
    tileUpdates: (projectId: string) => request<TileUpdate[]>(`/projects/${projectId}/tile-updates`),
    applyTileUpdates: (projectId: string, tileIds: string[], version: number) =>
      request<RoomsState>(`/projects/${projectId}/tile-updates/apply`, json('POST', { tile_ids: tileIds, version })),
    /** Bulk change for selected rooms: set fields, reset fields to the default, and/or skip. */
    setRooms: (
      projectId: string,
      data: {
        room_ids: string[]
        set?: { tile_id?: string; layout?: Layout; breakage_pct?: string; price?: Price }
        inherit?: MaterialField[]
        skipped?: boolean
      },
      version: number,
    ) => request<RoomsState>(`/projects/${projectId}/rooms/materials`, json('POST', { ...data, version })),
    /** Doors and windows, wall tiling and skirting for one room (PRD 4.15). Undoable. */
    setRoomWalls: (
      projectId: string,
      roomId: string,
      data: {
        openings: { kind: OpeningKind; label: string; width: string; height: string; quantity: number; unit: LengthUnit }[]
        walls: {
          height: string
          unit: LengthUnit
          tile_id: string | null
          breakage_pct: string | null
          length: string | null
          price: Price | null
        } | null
        skirting: boolean | null
      },
      version: number,
    ) => request<RoomsState>(`/projects/${projectId}/rooms/${roomId}/walls`, json('PUT', { ...data, version })),
    /** Default wall tile, skirting and sundries. Not an undo step. */
    setExtras: (
      projectId: string,
      data: {
        wall_tile_id: string | null
        wall_breakage_pct: string
        wall_price: Price | null
        skirting: SkirtingSettings
        sundries: SundriesSettings
      },
    ) => request<RoomsState>(`/projects/${projectId}/extras/settings`, json('PUT', data)),
    suggestions: (projectId: string) => request<Suggestion[]>(`/projects/${projectId}/suggestions`),
    setExclusions: (
      projectId: string,
      roomId: string,
      exclusions: { label: string; length: string; width: string; quantity: number; unit: LengthUnit }[],
      version: number,
    ) =>
      request<RoomsState>(`/projects/${projectId}/rooms/${roomId}/exclusions`, json('PUT', { exclusions, version })),
  },
  cost: {
    setSettings: (projectId: string, settings: CostSettings) =>
      request<RoomsState>(`/projects/${projectId}/cost/settings`, json('PUT', settings)),
  },
  exports: {
    options: (projectId: string) => request<{ email_enabled: boolean }>(`/projects/${projectId}/exports/options`),
    file: (
      projectId: string,
      kind: 'report.pdf' | 'estimate.xlsx' | 'shopping-list.pdf' | 'order-list.pdf',
      areaUnit: AreaUnit,
    ) =>
      requestFile(`/projects/${projectId}/exports/${kind}?area_unit=${areaUnit}`),
    emailShoppingList: (projectId: string, data: { to: string[]; message?: string; attach_pdf: boolean }) =>
      request<{ sent_to: string[] }>(`/projects/${projectId}/exports/shopping-list/email`, json('POST', data)),
  },
  company: {
    get: () => request<CompanyProfile>('/users/me/company'),
    save: (data: CompanyProfile) => request<CompanyProfile>('/users/me/company', json('PUT', data)),
    uploadLogo: (file: File) =>
      request<CompanyProfile>('/users/me/company/logo', { method: 'PUT', body: formData({ file }) }),
    removeLogo: () => request<CompanyProfile>('/users/me/company/logo', json('DELETE')),
    logoUrl: '/api/users/me/company/logo',
  },
  quotes: {
    forProject: (projectId: string) => request<Quote[]>(`/projects/${projectId}/quotes`),
    all: () => request<Quote[]>('/quotes'),
    create: (
      projectId: string,
      data: {
        client: QuoteClient
        margin_pct: string | null
        margin_on_labour: boolean
        extra_lines: ExtraQuoteLine[]
        notes: string | null
        validity_days: number | null
      },
    ) => request<Quote>(`/projects/${projectId}/quotes`, json('POST', data)),
    revise: (id: string) => request<Quote>(`/quotes/${id}/revise`, json('POST', {})),
    setStatus: (id: string, status: QuoteStatus) => request<Quote>(`/quotes/${id}/status`, json('PATCH', { status })),
    remove: (id: string) => request<void>(`/quotes/${id}`, json('DELETE')),
    pdf: (id: string) => requestFile(`/quotes/${id}/pdf`),
    email: (id: string, data: { to?: string; message?: string }) =>
      request<Quote>(`/quotes/${id}/email`, json('POST', data)),
  },
  scenarios: {
    compare: (projectId: string) => request<Comparison>(`/projects/${projectId}/scenarios`),
    add: (projectId: string, data: ScenarioInput) =>
      request<Comparison>(`/projects/${projectId}/scenarios`, json('POST', data)),
    saveCurrent: (projectId: string, name: string) =>
      request<Comparison>(`/projects/${projectId}/scenarios/from-current`, json('POST', { name })),
    rename: (projectId: string, id: string, name: string) =>
      request<Comparison>(`/projects/${projectId}/scenarios/${id}`, json('PATCH', { name })),
    remove: (projectId: string, id: string) => request<void>(`/projects/${projectId}/scenarios/${id}`, json('DELETE')),
    /** Make an option the project's setup. Undoable. */
    apply: (projectId: string, id: string, version: number) =>
      request<RoomsState>(`/projects/${projectId}/scenarios/${id}/apply?version=${version}`, json('POST')),
  },
  history: {
    versions: (projectId: string) =>
      request<{ id: string; at: string; user_name: string | null; label: string; metrics: Record<string, unknown> }[]>(
        `/projects/${projectId}/versions`,
      ),
    restore: (projectId: string, versionId: string, version: number) =>
      request<RoomsState>(`/projects/${projectId}/versions/${versionId}/restore?version=${version}`, json('POST')),
    backup: (projectId: string) => requestFile(`/projects/${projectId}/backup`),
    /** A backup file becomes a new project (in the account, or in this browser for guests). */
    importBackup: async (file: File): Promise<Project> => {
      if (guestMode) {
        const { importBackupLocally, GuestError } = await import('./guest.ts')
        try {
          return (await importBackupLocally(file)).body as Project
        } catch (err) {
          if (err instanceof GuestError) throw new ApiError(err.status, err.message)
          throw err
        }
      }
      return request<Project>('/projects/import', { method: 'POST', body: formData({ file }) })
    },
  },
  feedback: {
    list: (projectId: string) => request<Feedback[]>(`/projects/${projectId}/feedback`),
    add: (
      projectId: string,
      data: { room_id: string | null; right: boolean; actual_boxes?: number; comment?: string },
    ) => request<Feedback>(`/projects/${projectId}/feedback`, json('POST', data)),
    remove: (projectId: string, id: string) => request<void>(`/projects/${projectId}/feedback/${id}`, json('DELETE')),
  },
  accuracy: {
    get: (projectId: string) => request<ProjectAccuracy>(`/projects/${projectId}/accuracy`),
    addToEvalSet: (projectId: string) =>
      request<ProjectAccuracy>(`/projects/${projectId}/evaluation`, json('POST', { consent: true })),
    removeFromEvalSet: (projectId: string) =>
      request<ProjectAccuracy>(`/projects/${projectId}/evaluation`, json('DELETE')),
  },
  tiles: {
    list: (filters: { scope?: 'all' | 'catalog' | 'mine'; q?: string; type?: TileType | ''; region?: TileRegion | '' } = {}) => {
      const params = new URLSearchParams()
      for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
      const qs = params.toString()
      return request<Tile[]>(`/tiles${qs ? `?${qs}` : ''}`)
    },
    create: (data: TileInput, catalog = false) => request<Tile>(`/tiles${catalog ? '?catalog=true' : ''}`, json('POST', data)),
    update: (id: string, data: TileInput) => request<Tile>(`/tiles/${id}`, json('PUT', data)),
    copy: (id: string) => request<Tile>(`/tiles/${id}/copy`, json('POST')),
    remove: (id: string) => request<void>(`/tiles/${id}`, json('DELETE')),
  },
  public: {
    privacy: () => request<PrivacyInfo>('/public/privacy'),
  },
  users: {
    updatePreferences: (preferences: User['preferences']) =>
      request<User>('/users/me/preferences', json('PUT', preferences)),
    sharedPlans: () =>
      request<{ id: string; project_name: string | null; files: string[]; created_at: string; project_exists: boolean }[]>(
        '/users/me/evaluation',
      ),
    removeSharedPlan: (id: string) => request<void>(`/users/me/evaluation/${id}`, json('DELETE')),
    /** Deletes the account and all its data. Cannot be undone. */
    deleteAccount: (password: string) =>
      request<{ projects: number; tiles: number; evaluation_copies: number }>(
        '/users/me',
        json('DELETE', { password }),
      ),
  },
  admin: {
    stats: () => request<AdminStats>('/admin/stats'),
    accuracy: () => request<AdminAccuracy>('/admin/accuracy'),
    evaluationSet: () => request<EvalEntry[]>('/admin/evaluation'),
    removeEvalEntry: (id: string) => request<void>(`/admin/evaluation/${id}`, json('DELETE')),
    evaluationExport: () => requestFile('/admin/evaluation/export'),
    users: () => request<User[]>('/admin/users'),
    updateUser: (id: string, data: Partial<Pick<User, 'role' | 'is_active'>>) =>
      request<User>(`/admin/users/${id}`, json('PATCH', data)),
  },
}
