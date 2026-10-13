import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client.ts'
import type { Estimate, Feedback } from '../../api/types.ts'
import { Button, ErrorText } from '../ui.tsx'

const boxes = (n: number) => `${n} ${n === 1 ? 'box' : 'boxes'}`

/**
 * "Was this quantity right?" (PRD 4.13). Answers are stored with a snapshot of the estimate,
 * so they can be compared with what was really needed, room by room or for the whole project.
 */
export function FeedbackPanel({
  projectId,
  estimate,
  selectedRoomId,
}: {
  projectId: string
  estimate: Estimate
  selectedRoomId: string | null
}) {
  const [history, setHistory] = useState<Feedback[]>([])
  const [mode, setMode] = useState<'ask' | 'wrong' | 'thanks'>('ask')
  const [roomId, setRoomId] = useState<string>('')
  const [actual, setActual] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api.feedback
      .list(projectId)
      .then((f) => !cancelled && setHistory(f))
      .catch(() => undefined) // feedback is optional; the panel still works without history
    return () => {
      cancelled = true
    }
  }, [projectId])

  // Clicking a row in the results table points the feedback at that room.
  const [lastSelected, setLastSelected] = useState(selectedRoomId)
  if (selectedRoomId !== lastSelected) {
    setLastSelected(selectedRoomId)
    if (selectedRoomId && estimate.rooms.some((r) => r.room_id === selectedRoomId)) setRoomId(selectedRoomId)
  }

  const estimated = roomId
    ? (estimate.rooms.find((r) => r.room_id === roomId)?.boxes ?? 0)
    : (estimate.totals?.boxes ?? 0)

  async function send(right: boolean, event?: FormEvent) {
    event?.preventDefault()
    const actualBoxes = actual.trim() === '' ? undefined : Number(actual)
    if (actualBoxes !== undefined && !(Number.isInteger(actualBoxes) && actualBoxes >= 0)) {
      return setError('Enter the number of boxes as a whole number, or leave it empty.')
    }
    setBusy(true)
    setError('')
    try {
      const saved = await api.feedback.add(projectId, {
        room_id: roomId || null,
        right,
        actual_boxes: right ? undefined : actualBoxes,
        comment: right ? undefined : comment.trim() || undefined,
      })
      setHistory((h) => [saved, ...h])
      setMode('thanks')
      setActual('')
      setComment('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    try {
      await api.feedback.remove(projectId, id)
      setHistory((h) => h.filter((f) => f.id !== id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const target = roomId ? (estimate.rooms.find((r) => r.room_id === roomId)?.name ?? 'this room') : 'the whole project'

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">Was this quantity right?</span>
          <select
            value={roomId}
            onChange={(e) => {
              setRoomId(e.target.value)
              if (mode === 'thanks') setMode('ask')
            }}
            aria-label="Which quantity"
            className="rounded-md border border-slate-300 bg-white px-2 py-1"
          >
            <option value="">Whole project ({boxes(estimate.totals?.boxes ?? 0)})</option>
            {estimate.rooms.map((r) => (
              <option key={r.room_id} value={r.room_id}>
                {r.name} ({boxes(r.boxes)})
              </option>
            ))}
          </select>
        </div>
        {mode === 'ask' && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => send(true)}
              disabled={busy}
              className="rounded-md border border-slate-300 px-3 py-1.5 hover:border-green-600 hover:bg-green-50"
            >
              👍 Yes
            </button>
            <button
              type="button"
              onClick={() => setMode('wrong')}
              disabled={busy}
              className="rounded-md border border-slate-300 px-3 py-1.5 hover:border-red-600 hover:bg-red-50"
            >
              👎 No
            </button>
          </div>
        )}
        {mode === 'thanks' && (
          <span role="status" className="text-green-700">
            Thanks, that helps us improve the estimates.{' '}
            <button type="button" onClick={() => setMode('ask')} className="text-brand-600 hover:underline">
              Answer again
            </button>
          </span>
        )}
      </div>
      <ErrorText>{error}</ErrorText>

      {mode === 'wrong' && (
        <form onSubmit={(e) => send(false, e)} className="mt-3 space-y-3 border-t border-slate-100 pt-3">
          <p className="text-slate-600">
            We estimated {boxes(estimated)} for {target}. What was actually needed?
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">Boxes actually needed (optional)</span>
              <input
                value={actual}
                onChange={(e) => setActual(e.target.value)}
                inputMode="numeric"
                className="w-32 rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block min-w-60 flex-1">
              <span className="mb-1 block text-xs text-slate-500">What was off? (optional)</span>
              <input
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                maxLength={1000}
                placeholder="e.g. the room size on the plan was wrong"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={busy}>
              {busy ? 'Sending…' : 'Send feedback'}
            </Button>
            <button type="button" onClick={() => setMode('ask')} className="text-slate-600 hover:underline">
              Cancel
            </button>
          </div>
        </form>
      )}

      {history.length > 0 && (
        <details className="mt-3 border-t border-slate-100 pt-2">
          <summary className="cursor-pointer text-xs text-slate-500">Your answers ({history.length})</summary>
          <ul className="mt-2 space-y-1">
            {history.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span>
                  {f.right ? '👍' : '👎'} {f.room_name ?? 'Whole project'}: estimated {boxes(f.estimated_boxes)}
                  {f.actual_boxes !== null && `, needed ${boxes(f.actual_boxes)}`}
                  {f.comment && <span className="text-slate-500"> · “{f.comment}”</span>}
                </span>
                <button type="button" onClick={() => remove(f.id)} className="text-slate-500 hover:text-red-700 hover:underline">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
