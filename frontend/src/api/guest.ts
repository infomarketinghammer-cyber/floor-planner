/**
 * Guest transport (PRD 4.12 local-first): without an account, API calls go to the stateless
 * guest dispatcher together with the project kept in this browser; the updated project comes back
 * and is stored again. A few calls never leave the browser: listing, deleting and duplicating
 * projects, and display preferences.
 */
import { guestId, localStore, newObjectId, type LocalProject } from '../lib/localStore.ts'

export class GuestError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface GuestResult {
  status: number
  body: unknown
  blob: Blob | null
  filename: string | null
}

interface CallOut {
  status: number
  content_type: string
  content_disposition: string | null
  body: unknown
  body_b64: string | null
  project: Record<string, unknown> | null
  summary: Record<string, unknown> | null
  blueprints: Record<string, unknown>[]
  files_added: Record<string, string>
  files_deleted: string[]
  tiles: Record<string, unknown>[]
}

const PROJECT_PATH = /^\/projects\/([0-9a-f]{24})(\/|$|\?)/

// What a change did, in words, for the history timeline (mirrors backend/app/core/activity.py).
const LABELS: [string, RegExp, string][] = [
  ['POST', /\/rooms$/, 'Added a room'],
  ['PATCH', /\/rooms\/[^/]+$/, 'Edited a room'],
  ['POST', /\/rooms\/confirm$/, 'Confirmed rooms'],
  ['PUT', /\/rooms$/, 'Undo or redo'],
  ['PUT', /\/rooms\/plan-unit$/, 'Set the plan unit'],
  ['DELETE', /\/rooms\/[^/]+$/, 'Deleted a room'],
  ['POST', /\/rooms\/import$/, 'Imported a room list'],
  ['PUT', /\/materials\/default$/, 'Changed the project tile settings'],
  ['POST', /\/rooms\/materials$/, 'Changed room tile settings'],
  ['PUT', /\/exclusions$/, 'Changed untiled areas'],
  ['PUT', /\/walls$/, 'Changed walls and doors'],
  ['PUT', /\/parts$/, "Changed a room's shape"],
  ['PUT', /\/extras\/settings$/, 'Changed walls, skirting and sundries settings'],
  ['PUT', /\/cost\/settings$/, 'Changed cost settings'],
  ['POST', /\/extract$/, 'Read rooms from a plan'],
  ['POST', /\/files$/, 'Uploaded a plan'],
  ['DELETE', /\/files\/[^/]+$/, 'Deleted a plan'],
  ['PATCH', /^\/projects\/[0-9a-f]{24}$/, 'Renamed the project'],
  ['POST', /\/apply/, 'Used a compared option'],
]

function label(method: string, path: string): string | null {
  const bare = path.split('?')[0]
  return LABELS.find(([m, rx]) => m === method && rx.test(bare))?.[2] ?? null
}

const BACKUP_FORMAT = 'floor-planner-backup'
const FILE_PATH = /^\/projects\/[0-9a-f]{24}\/files\/([0-9a-f]{24})/

function oid(value: unknown): string | null {
  if (value && typeof value === 'object' && '$oid' in value) return (value as { $oid: string }).$oid
  return typeof value === 'string' ? value : null
}

/** The stored files a plan file's call may need: the file, its DXF conversion, page thumbnails. */
function blueprintFileIds(bp: Record<string, unknown>): string[] {
  const pages = (bp.pages as Record<string, unknown>[] | undefined) ?? []
  return [oid(bp.file_id), oid(bp.converted_file_id), ...pages.map((p) => oid(p.thumbnail_id))].filter(
    (x): x is string => !!x,
  )
}

export function b64ToBlob(b64: string, type: string): Blob {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type })
}

export async function fileToB64(file: Blob): Promise<string> {
  const buf = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  return btoa(bin)
}

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return fallback
}

/** Local-only calls; null if the call must go to the dispatcher. */
async function local(method: string, path: string): Promise<GuestResult | null> {
  const ok = (body: unknown): GuestResult => ({ status: 200, body, blob: null, filename: null })
  if (method === 'GET' && path === '/projects') {
    const projects = await localStore.listProjects()
    return ok(projects.map((p) => p.summary).filter(Boolean))
  }
  const m = PROJECT_PATH.exec(path)
  if (m && method === 'DELETE' && path === `/projects/${m[1]}`) {
    await localStore.deleteProject(m[1])
    return { status: 204, body: null, blob: null, filename: null }
  }
  if (m && method === 'POST' && path === `/projects/${m[1]}/duplicate`) {
    const source = await localStore.getProject(m[1])
    if (!source) throw new GuestError(404, 'Project not found')
    // Like the server's duplicate: rooms and settings, not the plan files.
    const id = newObjectId()
    const now = { $date: new Date().toISOString() }
    const doc = {
      ...source.doc,
      _id: { $oid: id },
      name: `${String(source.doc.name).slice(0, 143)} (copy)`,
      created_at: now,
      updated_at: now,
      last_exported_at: null,
      status: source.doc.status === 'exported' ? 'calculated' : source.doc.status,
    }
    await localStore.putProject({ id, doc, blueprints: [], summary: null, updatedAt: new Date().toISOString() })
    return guestCall('GET', `/projects/${id}`) // fills in the summary
  }
  if (m && method === 'GET' && path === `/projects/${m[1]}/versions`) {
    const versions = await localStore.versions(m[1])
    return ok(
      versions.map((v) => ({ id: String(v.id), at: v.at, user_name: null, label: v.label, metrics: v.metrics })),
    )
  }
  const restore = /^\/projects\/([0-9a-f]{24})\/versions\/(\d+)\/restore/.exec(path)
  if (restore && method === 'POST') {
    const [, projectId, versionId] = restore
    const version = await localStore.getVersion(Number(versionId))
    const current = await localStore.getProject(projectId)
    if (!version || !current) throw new GuestError(404, 'Version not found')
    // Rooms and settings go back; plan files stay as they are now.
    await localStore.putProject({ ...current, doc: { ...version.doc, _id: current.doc._id }, updatedAt: new Date().toISOString() })
    const result = await guestCall('GET', `/projects/${projectId}/rooms`)
    await snapshot(projectId, 'Restored an earlier version', result.body)
    return result
  }
  if (m && method === 'GET' && path === `/projects/${m[1]}/backup`) {
    const project = await localStore.getProject(m[1])
    if (!project) throw new GuestError(404, 'Project not found')
    const files: Record<string, string> = {}
    for (const f of await localStore.projectFiles(m[1])) files[f.id] = f.b64
    const data = {
      format: BACKUP_FORMAT,
      version: 1,
      exported_at: new Date().toISOString(),
      project: project.doc,
      blueprints: project.blueprints,
      files,
    }
    const name = String(project.doc.name ?? 'project').replace(/[^\w\- ]+/g, '').trim() || 'project'
    return { status: 200, body: null, blob: new Blob([JSON.stringify(data)], { type: 'application/json' }), filename: `${name} - backup.floorplan.json` }
  }
  return null
}

/** A backup file becomes a new project in this browser, with new ids throughout. */
export async function importBackupLocally(file: File): Promise<GuestResult> {
  let data: { format?: string; version?: number; project?: Record<string, unknown>; blueprints?: Record<string, unknown>[]; files?: Record<string, string> }
  try {
    data = JSON.parse(await file.text())
  } catch {
    throw new GuestError(422, "This isn't a Floor Planner backup file.")
  }
  if (data.format !== BACKUP_FORMAT || !data.project) throw new GuestError(422, "This isn't a Floor Planner backup file.")
  if ((data.version ?? 0) > 1) throw new GuestError(422, 'This backup was made by a newer version of Floor Planner.')
  const id = newObjectId()
  const fileMap = new Map<string, string>()
  for (const [old, b64] of Object.entries(data.files ?? {})) {
    const fresh = newObjectId()
    fileMap.set(old, fresh)
    await localStore.putFile({ id: fresh, projectId: id, b64 })
  }
  const remap = (v: unknown) => {
    const old = oid(v)
    return old && fileMap.has(old) ? { $oid: fileMap.get(old)! } : v
  }
  const blueprintMap = new Map<string, string>()
  const blueprints = (data.blueprints ?? []).map((bp) => {
    const fresh = newObjectId()
    blueprintMap.set(oid(bp._id)!, fresh)
    return {
      ...bp,
      _id: { $oid: fresh },
      project_id: { $oid: id },
      file_id: remap(bp.file_id),
      converted_file_id: remap(bp.converted_file_id),
      pages: ((bp.pages as Record<string, unknown>[]) ?? []).map((p) => ({ ...p, thumbnail_id: remap(p.thumbnail_id) })),
    }
  })
  const rooms = ((data.project.rooms as Record<string, unknown>[]) ?? []).map((r) => {
    const source = r.source as { file_id?: string } | null
    return source?.file_id && blueprintMap.has(source.file_id)
      ? { ...r, source: { ...source, file_id: blueprintMap.get(source.file_id) } }
      : r
  })
  const now = { $date: new Date().toISOString() }
  const doc = { ...data.project, _id: { $oid: id }, rooms, created_at: now, updated_at: now }
  delete (doc as Record<string, unknown>).owner_id
  await localStore.putProject({ id, doc, blueprints, summary: null, updatedAt: new Date().toISOString() })
  return guestCall('GET', `/projects/${id}`) // fills in the summary
}

/** Keep a snapshot of a guest project after a change (the history timeline). */
async function snapshot(projectId: string, what: string, body: unknown) {
  const project = await localStore.getProject(projectId)
  if (!project) return
  const state = body as { estimate?: { ready?: boolean; totals?: { boxes?: number } | null }; cost?: { total?: string; has_prices?: boolean } | null; rooms?: unknown[] } | null
  await localStore.addVersion({
    projectId,
    at: new Date().toISOString(),
    label: what,
    doc: project.doc,
    metrics: {
      ready: !!state?.estimate?.ready,
      rooms: Array.isArray(state?.rooms) ? state!.rooms!.length : undefined,
      boxes: state?.estimate?.totals?.boxes,
      cost: state?.cost?.has_prices ? state.cost.total : null,
    },
  })
}

export async function guestCall(
  method: string,
  path: string,
  body?: unknown,
  upload?: { field: string; file: File; form: Record<string, string> },
): Promise<GuestResult> {
  const handled = await local(method, path)
  if (handled) return handled

  const projectId = PROJECT_PATH.exec(path)?.[1] ?? null
  const stored: LocalProject | undefined = projectId ? await localStore.getProject(projectId) : undefined
  if (projectId && !stored) throw new GuestError(404, 'Project not found in this browser')
  const files: Record<string, string> = {}
  const fileId = FILE_PATH.exec(path)?.[1]
  if (stored && fileId) {
    const bp = stored.blueprints.find((b) => oid(b._id) === fileId)
    for (const id of bp ? blueprintFileIds(bp) : []) {
      const f = await localStore.getFile(id)
      if (f) files[id] = f.b64
    }
  }
  const payload = {
    guest_id: await guestId(),
    method,
    path,
    body: body ?? null,
    upload: upload
      ? {
          field: upload.field,
          filename: upload.file.name,
          content_type: upload.file.type || 'application/octet-stream',
          data_b64: await fileToB64(upload.file),
          form: upload.form,
        }
      : null,
    project: stored?.doc ?? null,
    blueprints: stored?.blueprints ?? [],
    files,
    tiles: (await localStore.get<Record<string, unknown>[]>('tiles')) ?? [],
    preferences: (await localStore.get<Record<string, unknown>>('preferences')) ?? {},
  }
  const response = await fetch('/api/guest/call', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const out = (await response.json().catch(() => null)) as CallOut | null
  if (!response.ok || !out) throw new GuestError(response.status, errorMessage(out, response.statusText || 'Request failed'))

  // Store what came back.
  if (out.project) {
    const id = oid(out.project._id)!
    await localStore.putProject({
      id,
      doc: out.project,
      blueprints: out.blueprints,
      summary: out.summary,
      updatedAt: new Date().toISOString(),
    })
    for (const [fid, b64] of Object.entries(out.files_added)) await localStore.putFile({ id: fid, projectId: id, b64 })
    // Drop files no plan file refers to any more (e.g. a deleted plan).
    const used = new Set(out.blueprints.flatMap(blueprintFileIds))
    for (const f of await localStore.projectFiles(id)) if (!used.has(f.id)) await localStore.deleteFile(f.id)
  }
  await localStore.set('tiles', out.tiles)

  if (out.status >= 400) throw new GuestError(out.status, errorMessage(out.body, 'Request failed'))
  const what = label(method, path)
  if (what && out.project) await snapshot(oid(out.project._id)!, what, out.body)
  const filename = /filename\*=UTF-8''([^;]+)/i.exec(out.content_disposition ?? '')?.[1]
  return {
    status: out.status,
    body: out.body,
    blob: out.body_b64 !== null ? b64ToBlob(out.body_b64, out.content_type) : null,
    filename: filename ? decodeURIComponent(filename) : (/filename="([^"]+)"/i.exec(out.content_disposition ?? '')?.[1] ?? null),
  }
}

/** A stored file of a guest project as an object URL (page thumbnails), or null. */
export async function localFileUrl(fileId: string, type = 'image/png'): Promise<string | null> {
  const f = await localStore.getFile(fileId)
  return f ? URL.createObjectURL(b64ToBlob(f.b64, type)) : null
}
