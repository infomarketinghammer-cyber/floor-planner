/**
 * Projects kept in this browser (PRD 4.12 local-first), in IndexedDB. Used without an account;
 * the server stores nothing for guests.
 *
 * - projects: { id, doc, blueprints, summary, updatedAt }: the project exactly as the server
 *   returned it (Extended JSON), its plan files' metadata, and its card for the project list
 * - files: { id, projectId, b64 }: plan files and page previews, base64
 * - kv: guest id, the guest's own tiles, display preferences
 */

const DB_NAME = 'floor-planner'
const DB_VERSION = 1

export interface LocalProject {
  id: string
  doc: Record<string, unknown>
  blueprints: Record<string, unknown>[]
  summary: Record<string, unknown> | null
  updatedAt: string
}

export interface LocalFile {
  id: string
  projectId: string
  b64: string
}

let opening: Promise<IDBDatabase> | null = null

function open(): Promise<IDBDatabase> {
  opening ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains('projects')) db.createObjectStore('projects', { keyPath: 'id' })
      if (!db.objectStoreNames.contains('files')) {
        db.createObjectStore('files', { keyPath: 'id' }).createIndex('projectId', 'projectId')
      }
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv')
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => {
      opening = null
      reject(req.error ?? new Error("This browser can't store projects (private window?)."))
    }
  })
  return opening
}

function done<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function store(name: 'projects' | 'files' | 'kv', mode: IDBTransactionMode = 'readonly') {
  return (await open()).transaction(name, mode).objectStore(name)
}

export const localStore = {
  async listProjects(): Promise<LocalProject[]> {
    return done((await store('projects')).getAll() as IDBRequest<LocalProject[]>)
  },
  async getProject(id: string): Promise<LocalProject | undefined> {
    return done((await store('projects')).get(id) as IDBRequest<LocalProject | undefined>)
  },
  async putProject(p: LocalProject): Promise<void> {
    await done((await store('projects', 'readwrite')).put(p))
  },
  async deleteProject(id: string): Promise<void> {
    await done((await store('projects', 'readwrite')).delete(id))
    for (const f of await localStore.projectFiles(id)) await localStore.deleteFile(f.id)
  },
  async getFile(id: string): Promise<LocalFile | undefined> {
    return done((await store('files')).get(id) as IDBRequest<LocalFile | undefined>)
  },
  async putFile(f: LocalFile): Promise<void> {
    await done((await store('files', 'readwrite')).put(f))
  },
  async deleteFile(id: string): Promise<void> {
    await done((await store('files', 'readwrite')).delete(id))
  },
  async projectFiles(projectId: string): Promise<LocalFile[]> {
    const index = (await store('files')).index('projectId')
    return done(index.getAll(projectId) as IDBRequest<LocalFile[]>)
  },
  async get<T>(key: string): Promise<T | undefined> {
    return done((await store('kv')).get(key) as IDBRequest<T | undefined>)
  },
  async set(key: string, value: unknown): Promise<void> {
    await done((await store('kv', 'readwrite')).put(value, key))
  },
  /** Delete everything kept in this browser. */
  async clear(): Promise<void> {
    for (const name of ['projects', 'files', 'kv'] as const) await done((await store(name, 'readwrite')).clear())
  },
}

/** A 24-hex id like MongoDB's, so guest projects use the same ids and paths as the server. */
export function newObjectId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12))
  const seconds = Math.floor(Date.now() / 1000)
  bytes[0] = (seconds >>> 24) & 0xff
  bytes[1] = (seconds >>> 16) & 0xff
  bytes[2] = (seconds >>> 8) & 0xff
  bytes[3] = seconds & 0xff
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export async function guestId(): Promise<string> {
  let id = await localStore.get<string>('guest_id')
  if (!id) {
    id = newObjectId()
    await localStore.set('guest_id', id)
  }
  return id
}
