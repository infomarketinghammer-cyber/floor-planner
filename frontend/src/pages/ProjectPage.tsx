import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { api, ApiError } from '../api/client.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import type { Project } from '../api/types.ts'
import { BlueprintsSection } from '../components/Blueprints.tsx'
import { ExportSection } from '../components/exports/ExportSection.tsx'
import { HistoryPanel } from '../components/history/HistoryPanel.tsx'
import { ExtractionSummary } from '../components/feedback/ExtractionSummary.tsx'
import { ScenariosSection } from '../components/scenarios/ScenariosSection.tsx'
import { QuotesSection } from '../components/quotes/QuotesSection.tsx'
import { StatusBadge } from '../components/projects.tsx'
import { MaterialsSection } from '../components/materials/MaterialsSection.tsx'
import { QuantitiesSection } from '../components/materials/QuantitiesSection.tsx'
import { RoomsSection } from '../components/rooms/RoomsSection.tsx'
import { useRoomsReview } from '../components/rooms/useRoomsReview.ts'
import { Button, ErrorText, Field } from '../components/ui.tsx'
import { attentionReasons, formatArea, plural, projectArea, useAreaUnit } from '../lib/format.ts'

/** Project workspace: inputs (PRD 4.1). Room review and calculation (4.3–4.9) build on this page. */
export function ProjectPage() {
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [areaUnit] = useAreaUnit()
  const { isGuest } = useAuth()

  const refreshProject = useCallback(() => {
    api.projects
      .get(projectId)
      .then(setProject)
      .catch((err: Error) => (err instanceof ApiError && err.status === 404 ? setNotFound(true) : setError(err.message)))
  }, [projectId])

  useEffect(refreshProject, [refreshProject])

  // Extraction adds rooms from the Blueprints section; bump this so the room state reloads.
  const [roomsVersion, setRoomsVersion] = useState(0)
  // One room state and undo history for both the review and the materials sections.
  const review = useRoomsReview(projectId, roomsVersion, refreshProject)
  const handleBlueprintsChange = useCallback(() => {
    refreshProject()
    setRoomsVersion((v) => v + 1)
  }, [refreshProject])

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError('')
    setSaved(false)
    try {
      const notes = String(form.get('notes') ?? '').trim()
      setProject(await api.projects.update(projectId, { name: String(form.get('name')).trim(), notes: notes || null }))
      setSaved(true)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (notFound) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold">Project not found</h1>
        <Link to="/" className="text-sm text-brand-600 hover:underline">
          ← Back to home
        </Link>
      </div>
    )
  }
  if (!project) return error ? <ErrorText>{error}</ErrorText> : <p className="text-sm text-slate-500">Loading…</p>

  const reasons = attentionReasons(project)

  return (
    <div className="space-y-8">
      <div>
        <Link to="/" className="text-sm text-slate-500 hover:underline">
          ← Home
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <StatusBadge status={project.status} />
        </div>
        <p className="text-sm text-slate-500">
          {plural(project.room_count, 'room')} · {formatArea(projectArea(project, areaUnit), areaUnit)}
        </p>
      </div>

      {reasons.length > 0 && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{reasons.join(' · ')}</p>
      )}

      <BlueprintsSection projectId={projectId} onChange={handleBlueprintsChange} />
      <RoomsSection projectId={projectId} review={review} />
      {review.state && !isGuest && <ExtractionSummary projectId={projectId} version={review.state.version} />}
      <MaterialsSection projectId={projectId} review={review} />
      <QuantitiesSection projectId={projectId} review={review} />
      {review.state?.estimate.ready && <ScenariosSection projectId={projectId} review={review} />}
      {review.state?.estimate.ready && !isGuest && <QuotesSection projectId={projectId} version={review.state.version} />}
      {review.state?.estimate.ready && (
        <ExportSection projectId={projectId} estimate={review.state.estimate} onExported={refreshProject} />
      )}

      <HistoryPanel projectId={projectId} review={review} />

      <details className="group max-w-xl rounded-xl border border-slate-200 bg-white">
        <summary className="cursor-pointer list-none px-6 py-4 font-semibold">
          Project details <span className="text-sm font-normal text-slate-500">(name and notes)</span>
        </summary>
        <form onSubmit={handleSave} className="space-y-4 px-6 pb-6">
          <ErrorText>{error}</ErrorText>
          <Field label="Name" name="name" defaultValue={project.name} maxLength={150} required />
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Notes</span>
            <textarea
              name="notes"
              rows={3}
              maxLength={2000}
              defaultValue={project.notes ?? ''}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600"
            />
          </label>
          <div className="flex items-center gap-3">
            <Button type="submit">Save</Button>
            {saved && <span className="text-sm text-green-700">Saved</span>}
          </div>
        </form>
      </details>
    </div>
  )
}
