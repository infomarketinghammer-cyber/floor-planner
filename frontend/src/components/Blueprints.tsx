import { useEffect, useRef, useState, type DragEvent } from 'react'
import { api } from '../api/client.ts'
import type { Blueprint, BlueprintPage } from '../api/types.ts'
import { lengthUnitLabels } from '../lib/units.ts'
import { ErrorText } from './ui.tsx'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.dxf,.dwg'
const MAX_MB = 25
const FLOOR_SUGGESTIONS = ['Basement', 'Ground Floor', 'First Floor', 'Second Floor', 'Third Floor', 'Terrace']
const KIND_LABELS: Record<Blueprint['kind'], string> = { pdf: 'PDF', image: 'Image', dxf: 'DXF', dwg: 'DWG' }

interface UploadJob {
  key: string
  name: string
  progress: number
  error?: string
}

function formatBytes(bytes: number): string {
  return bytes < 1_048_576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`
}

export function BlueprintsSection({ projectId, onChange }: { projectId: string; onChange: () => void }) {
  const [files, setFiles] = useState<Blueprint[] | null>(null)
  const [jobs, setJobs] = useState<UploadJob[]>([])
  const [extracting, setExtracting] = useState<Set<string>>(new Set())
  const [error, setError] = useState('')

  useEffect(() => {
    api.files
      .list(projectId)
      .then(setFiles)
      .catch((err: Error) => setError(err.message))
  }, [projectId])

  const replaceFile = (next: Blueprint) =>
    setFiles((prev) => prev?.map((f) => (f.id === next.id ? next : f)) ?? null)

  async function runExtraction(fileId: string) {
    setExtracting((prev) => new Set(prev).add(fileId))
    try {
      const result = await api.files.extract(projectId, fileId)
      replaceFile(result.blueprint)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setExtracting((prev) => {
        const next = new Set(prev)
        next.delete(fileId)
        return next
      })
    }
  }

  const updateJob = (key: string, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((j) => (j.key === key ? { ...j, ...patch } : j)))

  async function uploadAll(selected: File[]) {
    const queued = selected.map((file, i) => ({ file, key: `${Date.now()}-${i}-${file.name}` }))
    setJobs((prev) => [...prev, ...queued.map(({ file, key }) => ({ key, name: file.name, progress: 0 }))])

    // One at a time: the server inspects each file (renders pages, checks quality).
    for (const { file, key } of queued) {
      if (file.size > MAX_MB * 1_048_576) {
        updateJob(key, { error: `${(file.size / 1_048_576).toFixed(1)} MB; the limit is ${MAX_MB} MB.` })
        continue
      }
      try {
        const created = await api.files.upload(projectId, file, (p) => updateJob(key, { progress: p }))
        setFiles((prev) => [...(prev ?? []), created])
        setJobs((prev) => prev.filter((j) => j.key !== key))
        onChange()
        void runExtraction(created.id) // read rooms straight away; the next upload can start meanwhile
      } catch (err) {
        updateJob(key, { error: (err as Error).message })
      }
    }
  }

  async function handleDelete(file: Blueprint) {
    if (!confirm(`Delete "${file.filename}"? Rooms already in the project are kept.`)) return
    try {
      await api.files.remove(projectId, file.id)
      setFiles((prev) => prev?.filter((f) => f.id !== file.id) ?? null)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handlePageChange(file: Blueprint, page: number, data: { floor?: string | null; included?: boolean }) {
    // Optimistic: show the change immediately, roll back if the save fails.
    replaceFile({ ...file, pages: file.pages.map((p) => (p.index === page ? { ...p, ...data } : p)) })
    try {
      replaceFile(await api.files.updatePage(projectId, file.id, page, data))
    } catch (err) {
      replaceFile(file)
      setError((err as Error).message)
    }
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Blueprints</h2>
        <p className="text-sm text-slate-500">
          Upload one file per floor, or a single multi-page file. Label each page with its floor.
        </p>
      </div>

      <DropZone onFiles={uploadAll} />
      <ErrorText>{error}</ErrorText>

      {jobs.length > 0 && (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li key={job.key} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate font-medium">{job.name}</span>
                {job.error ? (
                  <button
                    onClick={() => setJobs((prev) => prev.filter((j) => j.key !== job.key))}
                    className="shrink-0 text-xs text-slate-500 hover:underline"
                  >
                    Dismiss
                  </button>
                ) : (
                  <span className="shrink-0 text-xs text-slate-500">
                    {job.progress < 1 ? `Uploading ${Math.round(job.progress * 100)}%` : 'Checking file…'}
                  </span>
                )}
              </div>
              {job.error ? (
                <p className="mt-1 text-red-700">{job.error}</p>
              ) : (
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-100">
                  <div
                    className={`h-full bg-brand-600 transition-all ${job.progress >= 1 ? 'animate-pulse' : ''}`}
                    style={{ width: `${Math.max(5, job.progress * 100)}%` }}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {files?.map((file) => (
        <BlueprintCard
          key={file.id}
          projectId={projectId}
          file={file}
          extracting={extracting.has(file.id)}
          onExtract={() => runExtraction(file.id)}
          onDelete={() => handleDelete(file)}
          onPageChange={(page, data) => handlePageChange(file, page, data)}
        />
      ))}

      <datalist id="floor-suggestions">
        {FLOOR_SUGGESTIONS.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>
    </section>
  )
}

function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files)
    if (files.length) onFiles(files)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
        dragging ? 'border-brand-600 bg-brand-50' : 'border-slate-300 bg-white'
      }`}
    >
      <p className="font-medium">Drag blueprint files here</p>
      <p className="mt-1 text-sm text-slate-500">
        PDF, JPG, PNG, DXF or DWG · up to {MAX_MB} MB each · PDFs up to 50 pages
      </p>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="mt-4 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
      >
        Choose files
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = '' // allow re-selecting the same file after an error
          if (files.length) onFiles(files)
        }}
      />
    </div>
  )
}

function Warnings({ items }: { items: { code: string; message: string }[] }) {
  if (!items.length) return null
  return (
    <ul className="space-y-1">
      {items.map((w) => (
        <li key={w.code} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          ⚠ {w.message}
        </li>
      ))}
    </ul>
  )
}

function ExtractionStatus({
  file,
  extracting,
  onExtract,
}: {
  file: Blueprint
  extracting: boolean
  onExtract: () => void
}) {
  const ex = file.extraction
  const tone = extracting
    ? 'bg-slate-50 text-slate-600'
    : !ex
      ? 'bg-slate-50 text-slate-600'
      : ex.status === 'done'
        ? ex.rooms_flagged
          ? 'bg-amber-50 text-amber-800'
          : 'bg-green-50 text-green-800'
        : ex.status === 'unavailable'
          ? 'bg-slate-100 text-slate-700'
          : 'bg-amber-50 text-amber-800'
  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2 text-sm ${tone}`}>
      <span role="status">
        {extracting ? (
          <span className="animate-pulse">Reading rooms from this file…</span>
        ) : ex ? (
          ex.message
        ) : (
          'Rooms not read yet.'
        )}
      </span>
      <button onClick={onExtract} disabled={extracting} className="font-medium hover:underline disabled:opacity-50">
        {ex ? 'Read again' : 'Read rooms'}
      </button>
    </div>
  )
}

function BlueprintCard({
  projectId,
  file,
  extracting,
  onExtract,
  onDelete,
  onPageChange,
}: {
  projectId: string
  file: Blueprint
  extracting: boolean
  onExtract: () => void
  onDelete: () => void
  onPageChange: (page: number, data: { floor?: string | null; included?: boolean }) => void
}) {
  const pageCount = file.pages.length
  return (
    <article className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-medium" title={file.filename}>
            {file.filename}
          </h3>
          <p className="text-sm text-slate-500">
            {KIND_LABELS[file.kind]} · {formatBytes(file.size_bytes)} · {pageCount} page{pageCount === 1 ? '' : 's'}
            {file.detected_unit && <> · Drawing units: {lengthUnitLabels[file.detected_unit].toLowerCase()}</>}
          </p>
        </div>
        <div className="flex gap-4 text-sm">
          <a href={api.files.downloadUrl(projectId, file.id)} className="text-slate-600 hover:underline">
            Download
          </a>
          <button onClick={onDelete} className="text-red-600 hover:underline">
            Delete
          </button>
        </div>
      </header>

      <ExtractionStatus file={file} extracting={extracting} onExtract={onExtract} />
      <Warnings items={file.warnings} />

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {file.pages.map((page) => (
          <PageTile
            key={`${page.index}:${page.floor ?? ''}`}
            page={page}
            showNumber={pageCount > 1}
            thumbnailUrl={api.files.thumbnailUrl(projectId, file.id, page.index)}
            onChange={(data) => onPageChange(page.index, data)}
          />
        ))}
      </ul>
    </article>
  )
}

function PageTile({
  page,
  showNumber,
  thumbnailUrl,
  onChange,
}: {
  page: BlueprintPage
  showNumber: boolean
  thumbnailUrl: string
  onChange: (data: { floor?: string | null; included?: boolean }) => void
}) {
  // Remounted (via key) when the saved floor changes, so this only holds unsaved typing.
  const [floor, setFloor] = useState(page.floor ?? '')

  function commitFloor() {
    const value = floor.trim()
    if (value !== (page.floor ?? '')) onChange({ floor: value || null })
  }

  return (
    <li className={`space-y-2 rounded-lg border p-3 ${page.included ? 'border-slate-200' : 'border-slate-200 opacity-60'}`}>
      <div className="flex aspect-[4/3] items-center justify-center overflow-hidden rounded bg-slate-50">
        {page.has_thumbnail ? (
          <img src={thumbnailUrl} alt={`Preview of page ${page.index + 1}`} loading="lazy" className="max-h-full max-w-full object-contain" />
        ) : (
          <span className="text-xs text-slate-400">No preview</span>
        )}
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{showNumber ? `Page ${page.index + 1}` : 'Plan'}</span>
        <label className="flex items-center gap-1.5 text-slate-600">
          <input
            type="checkbox"
            checked={page.included}
            onChange={(e) => onChange({ included: e.target.checked })}
            className="accent-brand-600"
          />
          Use this page
        </label>
      </div>
      <label className="block text-sm">
        <span className="sr-only">Floor</span>
        <input
          value={floor}
          onChange={(e) => setFloor(e.target.value)}
          onBlur={commitFloor}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
          list="floor-suggestions"
          placeholder="Floor (e.g. Ground Floor)"
          maxLength={50}
          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5"
        />
      </label>
      {page.has_text === false && <p className="text-xs text-slate-500">Scanned page · will use OCR</p>}
      {page.warnings.map((w) => (
        <p key={w.code} className="text-xs text-amber-700">
          ⚠ {w.message}
        </p>
      ))}
    </li>
  )
}
