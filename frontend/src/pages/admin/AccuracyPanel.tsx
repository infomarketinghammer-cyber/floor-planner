import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { AdminAccuracy, EvalEntry } from '../../api/types.ts'
import { ErrorText } from '../../components/ui.tsx'

const METHOD_LABELS: Record<string, string> = { pdf_text: 'PDF text', dxf_text: 'CAD drawing', vision: 'Read by AI' }
const pct = (v: string | null) => (v === null ? '–' : `${Number(v)}%`)

/** Admin: extraction accuracy across all projects, quantity feedback, and the evaluation set. */
export function AccuracyPanel() {
  const [data, setData] = useState<AdminAccuracy | null>(null)
  const [entries, setEntries] = useState<EvalEntry[]>([])
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    Promise.all([api.admin.accuracy(), api.admin.evaluationSet()])
      .then(([a, e]) => {
        setData(a)
        setEntries(e)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  async function remove(entry: EvalEntry) {
    if (!confirm(`Remove "${entry.project_name ?? 'this plan'}" from the evaluation set? Its plan copy is deleted.`)) return
    try {
      await api.admin.removeEvalEntry(entry.id)
      setEntries((list) => list.filter((e) => e.id !== entry.id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function download() {
    setDownloading(true)
    try {
      const { blob, filename } = await api.admin.evaluationExport()
      const url = URL.createObjectURL(blob)
      Object.assign(document.createElement('a'), { href: url, download: filename }).click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDownloading(false)
    }
  }

  if (!data) return error ? <ErrorText>{error}</ErrorText> : null
  const x = data.extraction
  const f = data.feedback

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">Accuracy</h2>
      <ErrorText>{error}</ErrorText>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <h3 className="font-semibold">Plan reading, all projects</h3>
          <p className="mt-1 text-slate-500">
            {x.rooms_read} rooms read · {x.correct} right as read · {x.corrected} corrected · {x.deleted} removed ·{' '}
            {x.added} missed · {x.pending} not reviewed
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(
              [
                ['Right as read', x.accuracy_pct],
                ['Names', x.name_accuracy_pct],
                ['Sizes', x.size_accuracy_pct],
                ['Rooms found', x.found_pct],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-lg bg-slate-50 p-2.5">
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{pct(value)}</dd>
              </div>
            ))}
          </dl>
          {x.by_method.length > 0 && (
            <table className="mt-3 w-full text-left">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-1 font-medium">Method</th>
                  <th className="py-1 text-right font-medium">Read</th>
                  <th className="py-1 text-right font-medium">Reviewed</th>
                  <th className="py-1 text-right font-medium">Right as read</th>
                </tr>
              </thead>
              <tbody>
                {x.by_method.map((m) => (
                  <tr key={m.method} className="border-t border-slate-100">
                    <td className="py-1">{METHOD_LABELS[m.method] ?? m.method}</td>
                    <td className="py-1 text-right tabular-nums">{m.read}</td>
                    <td className="py-1 text-right tabular-nums">{m.reviewed}</td>
                    <td className="py-1 text-right tabular-nums">{pct(m.accuracy_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <h3 className="font-semibold">"Was this quantity right?"</h3>
          <p className="mt-1 text-slate-500">
            {f.total} answers · {f.right} yes · {f.wrong} no{f.right_pct !== null && ` · ${pct(f.right_pct)} yes`}
          </p>
          {f.wrong > 0 && (
            <p className="mt-1 text-slate-500">
              Of the "no" answers, {f.wrong_on_extracted_rooms} were on rooms read from a plan and{' '}
              {f.wrong_on_corrected_rooms} on rooms whose plan reading had been corrected.
            </p>
          )}
          {f.recent.length > 0 && (
            <ul className="mt-3 space-y-1.5 text-xs">
              {f.recent.map((r, i) => (
                <li key={i} className="border-t border-slate-100 pt-1.5">
                  <span className="font-medium">{r.room_name ?? 'Whole project'}</span>: estimated {r.estimated_boxes}
                  {r.actual_boxes !== null && `, needed ${r.actual_boxes}`}
                  {r.comment && <span className="text-slate-500"> · “{r.comment}”</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Evaluation set</h3>
            <p className="text-slate-500">
              Verified plans users chose to share. Score the current plan reader with{' '}
              <code className="rounded bg-slate-100 px-1">python -m app.evaluation</code>.
            </p>
          </div>
          <button
            type="button"
            onClick={download}
            disabled={downloading || entries.length === 0}
            className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50 disabled:opacity-50"
          >
            {downloading ? 'Preparing…' : 'Download set (.zip)'}
          </button>
        </div>
        {entries.length === 0 ? (
          <p className="mt-3 text-slate-500">No plans yet.</p>
        ) : (
          <table className="mt-3 w-full text-left">
            <thead className="text-xs text-slate-500">
              <tr>
                <th className="py-1 font-medium">Project</th>
                <th className="py-1 text-right font-medium">Files</th>
                <th className="py-1 text-right font-medium">Rooms</th>
                <th className="py-1 text-right font-medium">Right as read</th>
                <th className="py-1 font-medium">Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-slate-100">
                  <td className="py-1.5">{e.project_name ?? '–'}</td>
                  <td className="py-1.5 text-right tabular-nums">{e.files}</td>
                  <td className="py-1.5 text-right tabular-nums">{e.rooms}</td>
                  <td className="py-1.5 text-right tabular-nums">{pct(e.accuracy_pct_at_add)}</td>
                  <td className="py-1.5">{new Date(e.created_at).toLocaleDateString()}</td>
                  <td className="py-1.5 text-right">
                    <button type="button" onClick={() => remove(e)} className="text-red-700 hover:underline">
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
