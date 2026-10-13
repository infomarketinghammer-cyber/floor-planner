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
  return null
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
