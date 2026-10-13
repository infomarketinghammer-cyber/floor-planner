import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client.ts'
import type { Estimate } from '../../api/types.ts'
import { plural, useAreaUnit } from '../../lib/format.ts'
import { Button, ErrorText } from '../ui.tsx'

type FileKind = 'report.pdf' | 'estimate.xlsx' | 'shopping-list.pdf'

const FILES: { kind: FileKind; label: string; note: string }[] = [
  { kind: 'report.pdf', label: 'PDF report', note: 'Rooms table, totals, costs and assumptions' },
  { kind: 'estimate.xlsx', label: 'Excel workbook', note: 'Live formulas: edit a number and totals update' },
  { kind: 'shopping-list.pdf', label: 'Shopping list PDF', note: 'Tile types and boxes only' },
]

const boxes = (n: number) => `${n} ${n === 1 ? 'box' : 'boxes'}`

/** Plain text for pasting into a message to a supplier. */
function shoppingText(estimate: Estimate): string {
  const lines = estimate.tiles.map(
    (t) => `- ${t.tile.size_label} ${t.tile.name}: ${boxes(t.boxes)} (${t.tiles_bought} tiles, ${t.tile.tiles_per_box} per box)`,
  )
  const total = estimate.tiles.reduce((n, t) => n + t.boxes, 0)
  return [...lines, '', `Total: ${boxes(total)}`, 'Estimate only: verify quantities before ordering.'].join('\n')
}

function save({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Exports (PRD 4.11): PDF report, Excel workbook with live formulas, and the compact shopping
 * list, which can also be copied or emailed (sent by the server through Resend).
 */
export function ExportSection({
  projectId,
  estimate,
  onExported,
}: {
  projectId: string
  estimate: Estimate
  onExported: () => void
}) {
  const [areaUnit] = useAreaUnit()
  const [downloading, setDownloading] = useState<FileKind | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const totalBoxes = estimate.tiles.reduce((n, t) => n + t.boxes, 0)

  async function download(kind: FileKind) {
    setDownloading(kind)
    setError('')
    try {
      save(await api.exports.file(projectId, kind, areaUnit))
      onExported()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDownloading(null)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(shoppingText(estimate))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError("Couldn't copy. Select the list and copy it yourself.")
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="export-heading">
      <div>
        <h2 id="export-heading" className="text-lg font-semibold">
          Export and share
        </h2>
        <p className="text-sm text-slate-500">Made from the current numbers. Every export says to verify before ordering.</p>
      </div>
      <ErrorText>{error}</ErrorText>

      <div className="grid gap-3 sm:grid-cols-3">
        {FILES.map((f) => (
          <button
            key={f.kind}
            type="button"
            onClick={() => download(f.kind)}
            disabled={downloading !== null}
            className="rounded-xl border border-slate-200 bg-white p-4 text-left hover:border-brand-600 hover:bg-slate-50 disabled:opacity-60"
          >
            <span className="block font-medium">{downloading === f.kind ? 'Preparing…' : f.label}</span>
            <span className="text-xs text-slate-500">{f.note}</span>
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold">Shopping list</h3>
          <button type="button" onClick={copy} className="text-sm font-medium text-brand-600 hover:underline">
            {copied ? 'Copied' : 'Copy as text'}
          </button>
        </div>
        <ul className="divide-y divide-slate-100">
          {estimate.tiles.map((t) => (
            <li key={t.tile.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{t.tile.size_label}</span> <span className="text-slate-500">{t.tile.name}</span>
              </span>
              <span className="whitespace-nowrap text-right tabular-nums">
                <span className="font-semibold">{boxes(t.boxes)}</span>
                <span className="block text-xs text-slate-500">{t.tiles_bought} tiles</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between border-t border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-semibold">
          <span>Total ({plural(estimate.tiles.length, 'tile type')})</span>
          <span className="tabular-nums">{boxes(totalBoxes)}</span>
        </p>
        <EmailForm projectId={projectId} onSent={onExported} />
      </div>
    </section>
  )
}

function EmailForm({ projectId, onSent }: { projectId: string; onSent: () => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [to, setTo] = useState('')
  const [message, setMessage] = useState('')
  const [attach, setAttach] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [sentTo, setSentTo] = useState<string[] | null>(null)

  useEffect(() => {
    let cancelled = false
    api.exports
      .options(projectId)
      .then((o) => !cancelled && setEnabled(o.email_enabled))
      .catch(() => !cancelled && setEnabled(false))
    return () => {
      cancelled = true
    }
  }, [projectId])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const recipients = to
      .split(/[,;\s]+/)
      .map((a) => a.trim())
      .filter(Boolean)
    if (recipients.length === 0) return setError('Enter an email address.')
    if (recipients.length > 5) return setError('Send to at most 5 addresses at a time.')
    const bad = recipients.find((a) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a))
    if (bad) return setError(`"${bad}" doesn't look like an email address.`)

    setSending(true)
    setError('')
    setSentTo(null)
    try {
      const result = await api.exports.emailShoppingList(projectId, {
        to: recipients,
        message: message.trim() || undefined,
        attach_pdf: attach,
      })
      setSentTo(result.sent_to)
      setTo('')
      setMessage('')
      onSent()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSending(false)
    }
  }

  if (enabled === null) return null
  if (!enabled) {
    return (
      <p className="border-t border-slate-100 px-4 py-3 text-sm text-slate-500">
        Emailing isn't set up on this server. Copy the list or download the PDF to share it.
      </p>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-3 border-t border-slate-100 px-4 py-4">
      <h4 className="text-sm font-semibold">Send by email</h4>
      <ErrorText>{error}</ErrorText>
      {sentTo && (
        <p role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">
          Sent to {sentTo.join(', ')}. Replies come to your email address.
        </p>
      )}
      <label className="block text-sm">
        <span className="mb-1 block text-slate-600">To (up to 5, separated by commas)</span>
        <input
          type="text"
          inputMode="email"
          autoComplete="email"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="supplier@example.com"
          className="w-full rounded-md border border-slate-300 px-3 py-2"
        />
      </label>
      <label className="block text-sm">
        <span className="mb-1 block text-slate-600">Message (optional)</span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={2}
          maxLength={1000}
          placeholder="Please send a quote and delivery date."
          className="w-full rounded-md border border-slate-300 px-3 py-2"
        />
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} className="accent-brand-600" />
          Attach the shopping list as a PDF
        </label>
        <Button type="submit" disabled={sending}>
          {sending ? 'Sending…' : 'Send shopping list'}
        </Button>
      </div>
    </form>
  )
}
