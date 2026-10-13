import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { Correction, ProjectAccuracy, RoomValues } from '../../api/types.ts'
import { formatLength } from '../../lib/units.ts'
import { Button, ErrorText } from '../ui.tsx'

const METHOD_LABELS: Record<string, string> = { pdf_text: 'PDF text', dxf_text: 'CAD drawing', vision: 'Read by AI' }

function describe(v: RoomValues | null): string {
  if (!v) return '–'
  const size =
    v.length_mm !== null && v.width_mm !== null
      ? `${formatLength(v.length_mm, v.unit)} × ${formatLength(v.width_mm, v.unit)}`
      : 'no size'
  return `${v.name} · ${size}`
}

function CorrectionRow({ c }: { c: Correction }) {
  if (c.status === 'deleted') {
    return (
      <li>
        <span className="font-medium text-red-700">Removed</span> {describe(c.extracted)}{' '}
        <span className="text-slate-500">(not a real room)</span>
      </li>
    )
  }
  if (c.status === 'added') {
    return (
      <li>
        <span className="font-medium text-amber-700">Missed</span> {describe(c.final)}{' '}
        <span className="text-slate-500">(added by hand)</span>
      </li>
    )
  }
  return (
    <li>
      <span className="font-medium text-brand-700">Corrected {c.fields.join(' and ')}</span> {describe(c.extracted)} →{' '}
      {describe(c.final)}
    </li>
  )
}

/**
 * How the plan reader did on this project (PRD 4.13): rooms read, confirmed as read, corrected,
 * removed or missed, and an opt-in to add the verified plan to the evaluation set (PRD 6.5).
 */
export function ExtractionSummary({ projectId, version }: { projectId: string; version: number }) {
  const [data, setData] = useState<ProjectAccuracy | null>(null)
  const [error, setError] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.accuracy
      .get(projectId)
      .then((d) => !cancelled && setData(d))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [projectId, version])

  async function change(add: boolean) {
    setBusy(true)
    setError('')
    try {
      setData(await (add ? api.accuracy.addToEvalSet(projectId) : api.accuracy.removeFromEvalSet(projectId)))
      setConsent(false)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const s = data?.summary
  if (!s) return null
  const reviewed = s.correct + s.corrected + s.deleted
  const evaluation = data.evaluation

  return (
    <details className="rounded-xl border border-slate-200 bg-white" open={s.pending === 0 && reviewed > 0}>
      <summary className="cursor-pointer list-none px-5 py-4">
        <span className="font-semibold">Plan reading summary</span>{' '}
        <span className="text-sm text-slate-500">
          {s.rooms_read} rooms read
          {reviewed > 0 && s.accuracy_pct !== null && ` · ${Number(s.accuracy_pct)}% right as read`}
          {s.pending > 0 && ` · ${s.pending} still to review`}
        </span>
      </summary>
      <div className="space-y-4 px-5 pb-5 text-sm">
        <ErrorText>{error}</ErrorText>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {(
            [
              ['Right as read', s.correct, 'text-green-700'],
              ['Corrected', s.corrected, 'text-brand-700'],
              ['Removed', s.deleted, 'text-red-700'],
              ['Missed', s.added, 'text-amber-700'],
              ['To review', s.pending, 'text-slate-600'],
            ] as const
          ).map(([label, value, color]) => (
            <div key={label} className="rounded-lg bg-slate-50 p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className={`text-xl font-semibold tabular-nums ${color}`}>{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-slate-600">
          {s.name_accuracy_pct !== null && `Names right: ${Number(s.name_accuracy_pct)}%. `}
          {s.size_accuracy_pct !== null && `Sizes right: ${Number(s.size_accuracy_pct)}%. `}
          {s.found_pct !== null && `Rooms found: ${Number(s.found_pct)}% of the rooms you confirmed. `}
          {s.by_method.length > 1 &&
            s.by_method
              .map((m) => `${METHOD_LABELS[m.method] ?? m.method}: ${m.accuracy_pct === null ? '–' : `${Number(m.accuracy_pct)}%`}`)
              .join(' · ')}
        </p>
        {s.corrections.length > 0 && (
          <ul className="space-y-1 text-xs">
            {s.corrections.map((c) => (
              <CorrectionRow key={c.room_id} c={c} />
            ))}
          </ul>
        )}

        <div className="rounded-lg border border-slate-200 p-3">
          <p className="font-medium">Help improve plan reading</p>
          {evaluation.in_eval_set ? (
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
              <span className="text-slate-600">
                This plan is in the evaluation set
                {evaluation.added_at && ` (added ${new Date(evaluation.added_at).toLocaleDateString()})`}. Thank you.
              </span>
              <button type="button" onClick={() => change(false)} disabled={busy} className="text-red-700 hover:underline">
                Remove it
              </button>
            </div>
          ) : evaluation.eligible ? (
            <div className="mt-2 space-y-2">
              <label className="flex items-start gap-2 text-slate-600">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-0.5 accent-brand-600"
                />
                <span>
                  Share a copy of this plan file and its confirmed room list with the Floor Planner team, used only to
                  test and improve how plans are read. The copy is kept until you remove it here, even if you delete
                  the project.
                </span>
              </label>
              <Button type="button" onClick={() => change(true)} disabled={!consent || busy}>
                {busy ? 'Adding…' : 'Add to evaluation set'}
              </Button>
            </div>
          ) : (
            <p className="mt-1 text-slate-500">{evaluation.reason}</p>
          )}
        </div>
      </div>
    </details>
  )
}
