import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { Project, ProjectStatus } from '../api/types.ts'
import { Button, ErrorText, Field } from './ui.tsx'

const statusStyles: Record<ProjectStatus, string> = {
  draft: 'bg-slate-100 text-slate-700',
  reviewed: 'bg-amber-100 text-amber-800',
  calculated: 'bg-blue-100 text-blue-800',
  exported: 'bg-green-100 text-green-800',
}

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusStyles[status]}`}>
      {status}
    </span>
  )
}

/** Modal form for a new project. Uses the native <dialog> for focus trapping and Esc to close. */
export function NewProjectDialog({
  open,
  onClose,
  onCreate,
}: {
  open: boolean
  onClose: () => void
  onCreate: (data: { name: string; notes?: string }) => Promise<Project>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formEl = event.currentTarget
    const form = new FormData(formEl)
    const name = String(form.get('name')).trim()
    const notes = String(form.get('notes') ?? '').trim()
    if (!name) return setError('Project name is required')
    setError('')
    setSubmitting(true)
    try {
      await onCreate({ name, notes: notes || undefined })
      formEl.reset()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-full max-w-md rounded-xl border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <form onSubmit={handleSubmit} className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-semibold">New project</h2>
          <p className="text-sm text-slate-500">You can upload the blueprint on the next screen.</p>
        </div>
        <ErrorText>{error}</ErrorText>
        <Field label="Project name" name="name" placeholder="e.g. Sharma Residence – Ground floor" maxLength={150} required autoFocus />
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Notes (optional)</span>
          <textarea
            name="notes"
            rows={3}
            maxLength={2000}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600"
          />
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <Button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create project'}
          </Button>
        </div>
      </form>
    </dialog>
  )
}
