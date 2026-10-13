import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api } from '../../api/client.ts'
import type { CompanyProfile, ExtraQuoteLine, Quote, QuoteStatus } from '../../api/types.ts'
import { usePrivacyInfo } from '../../lib/privacy.ts'
import { formatMoney } from '../../lib/money.ts'
import { Button, ErrorText } from '../ui.tsx'

const STATUS: Record<QuoteStatus, [string, string]> = {
  draft: ['Draft', 'bg-slate-100 text-slate-700'],
  sent: ['Sent', 'bg-brand-100 text-brand-700'],
  approved: ['Approved', 'bg-green-100 text-green-800'],
  rejected: ['Rejected', 'bg-red-100 text-red-800'],
}
const inputClass = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'

function save({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Quotations (PRD 4.19): turn the estimate into a client-ready quote with your margin, labour and
 * tax; track versions and whether it was sent, approved or rejected.
 */
export function QuotesSection({ projectId, version }: { projectId: string; version: number }) {
  const [quotes, setQuotes] = useState<Quote[] | null>(null)
  const [company, setCompany] = useState<CompanyProfile | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([api.quotes.forProject(projectId), api.company.get()])
      .then(([q, c]) => {
        if (cancelled) return
        setQuotes(q)
        setCompany(c)
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [projectId, version])

  async function reload() {
    setQuotes(await api.quotes.forProject(projectId))
  }

  async function act(change: () => Promise<unknown>) {
    setError('')
    try {
      await change()
      await reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (!quotes || !company) return error ? <ErrorText>{error}</ErrorText> : null
  const byNumber = new Map<string, Quote[]>()
  for (const q of quotes) byNumber.set(q.number, [...(byNumber.get(q.number) ?? []), q])

  return (
    <section className="space-y-4" aria-labelledby="quotes-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="quotes-heading" className="text-lg font-semibold">
            Quotations
          </h2>
          <p className="text-sm text-slate-500">A client-ready quote from this estimate, with your margin, labour and tax.</p>
        </div>
        <Button type="button" onClick={() => setCreating((c) => !c)}>
          {creating ? 'Close' : 'New quote'}
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
      {!company.name && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Add your company name, logo and details on the{' '}
          <Link to="/account" className="font-medium underline">
            Account
          </Link>{' '}
          page so they appear on your quotes.
        </p>
      )}
      {creating && (
        <QuoteForm
          company={company}
          onCreate={async (data) => {
            await act(() => api.quotes.create(projectId, data))
            setCreating(false)
          }}
        />
      )}
      {quotes.length === 0 && !creating && (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">No quotes yet.</p>
      )}
      {[...byNumber.values()].map((versions) => (
        <QuoteCard key={versions[0].number} versions={versions} act={act} />
      ))}
    </section>
  )
}

function QuoteCard({ versions, act }: { versions: Quote[]; act: (change: () => Promise<unknown>) => Promise<void> }) {
  const latest = versions.find((v) => v.latest) ?? versions[0]
  const older = versions.filter((v) => v.id !== latest.id)
  const [open, setOpen] = useState(false)
  const [emailing, setEmailing] = useState(false)
  const privacy = usePrivacyInfo()
  const money = { currency: latest.currency, locale: latest.locale }
  const m = (v: string) => formatMoney(v, money)
  const marginPct = Number(latest.cost_total) ? (Number(latest.margin_amount) / Number(latest.cost_total)) * 100 : 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="font-semibold">
            {latest.number}
            {latest.version > 1 && <span className="font-normal text-slate-500"> · version {latest.version}</span>}
            <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[latest.status][1]}`}>{STATUS[latest.status][0]}</span>
          </p>
          <p className="text-sm text-slate-600">
            {latest.client.name} · made {new Date(latest.created_at).toLocaleDateString()} · valid until{' '}
            {new Date(latest.valid_until).toLocaleDateString()}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-semibold tabular-nums">{m(latest.total)}</p>
          <p className="text-xs text-slate-500">
            Margin {m(latest.margin_amount)} ({marginPct.toFixed(1)}% on cost) · not shown to the client
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 px-4 py-3 text-sm">
        <button type="button" onClick={() => act(async () => save(await api.quotes.pdf(latest.id)))} className="font-medium text-brand-700 hover:underline">
          Download PDF
        </button>
        {privacy?.email_enabled && (
          <button type="button" onClick={() => setEmailing((e) => !e)} className="font-medium text-brand-700 hover:underline">
            Email to client
          </button>
        )}
        <label className="flex items-center gap-1.5">
          <span className="text-slate-500">Status</span>
          <select
            value={latest.status}
            onChange={(e) => act(() => api.quotes.setStatus(latest.id, e.target.value as QuoteStatus))}
            className="rounded-md border border-slate-300 bg-white px-2 py-1"
          >
            {(Object.keys(STATUS) as QuoteStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s][0]}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => act(() => api.quotes.revise(latest.id))}
          title="A new version from the project as it is now; this one is kept"
          className="text-slate-700 hover:underline"
        >
          Revise
        </button>
        <button type="button" onClick={() => setOpen((o) => !o)} className="text-slate-700 hover:underline">
          {open ? 'Hide lines' : 'Show lines'}
        </button>
        {latest.status === 'draft' && (
          <button
            type="button"
            onClick={() => confirm(`Delete draft ${latest.number} v${latest.version}?`) && act(() => api.quotes.remove(latest.id))}
            className="ml-auto text-red-700 hover:underline"
          >
            Delete draft
          </button>
        )}
      </div>
      {emailing && (
        <EmailQuote
          quote={latest}
          onSend={async (to, message) => {
            await act(() => api.quotes.email(latest.id, { to: to || undefined, message: message || undefined }))
            setEmailing(false)
          }}
        />
      )}
      {open && (
        <div className="overflow-x-auto border-t border-slate-100">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 text-right font-medium">Qty</th>
                <th className="px-3 py-2 text-right font-medium">Unit price</th>
                <th className="px-3 py-2 text-right font-medium">Amount</th>
                <th className="px-3 py-2 text-right font-medium">Your cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {latest.lines.map((l, i) => (
                <tr key={i}>
                  <td className="px-3 py-2">{l.description}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {Number(l.quantity)} {l.unit}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{m(l.unit_price)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{m(l.amount)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">{m(l.cost)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="text-sm">
              <tr className="border-t border-slate-200">
                <td className="px-3 py-2" colSpan={3}>
                  Subtotal
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{m(latest.subtotal)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{m(latest.cost_total)}</td>
              </tr>
              {Number(latest.tax_pct) > 0 && (
                <tr>
                  <td className="px-3 py-2" colSpan={3}>
                    {latest.tax_label} ({Number(latest.tax_pct)}%)
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{m(latest.tax_amount)}</td>
                  <td />
                </tr>
              )}
              <tr className="font-semibold">
                <td className="px-3 py-2" colSpan={3}>
                  Total
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{m(latest.total)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {older.length > 0 && (
        <details className="border-t border-slate-100 px-4 py-2 text-sm">
          <summary className="cursor-pointer text-slate-500">Earlier versions ({older.length})</summary>
          <ul className="mt-2 space-y-1">
            {older.map((q) => (
              <li key={q.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  Version {q.version} · {STATUS[q.status][0]} · {m(q.total)} · {new Date(q.created_at).toLocaleDateString()}
                </span>
                <button type="button" onClick={() => act(async () => save(await api.quotes.pdf(q.id)))} className="text-brand-700 hover:underline">
                  PDF
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function EmailQuote({ quote, onSend }: { quote: Quote; onSend: (to: string, message: string) => Promise<void> }) {
  const [to, setTo] = useState(quote.client.email ?? '')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault()
        setSending(true)
        try {
          await onSend(to.trim(), message.trim())
        } finally {
          setSending(false)
        }
      }}
      className="space-y-2 border-t border-slate-100 px-4 py-3 text-sm"
    >
      <div className="grid gap-2 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
        <label className="block">
          <span className="mb-1 block text-slate-600">To</span>
          <input value={to} onChange={(e) => setTo(e.target.value)} type="email" required className={inputClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Message (optional)</span>
          <input value={message} onChange={(e) => setMessage(e.target.value)} maxLength={1000} className={inputClass} />
        </label>
        <Button type="submit" disabled={sending}>
          {sending ? 'Sending…' : 'Send with PDF'}
        </Button>
      </div>
      <p className="text-xs text-slate-500">Marks the quote as sent. Replies go to your company email.</p>
    </form>
  )
}

function QuoteForm({
  company,
  onCreate,
}: {
  company: CompanyProfile
  onCreate: (data: Parameters<typeof api.quotes.create>[1]) => Promise<void>
}) {
  const [client, setClient] = useState({ name: '', email: '', phone: '', address: '' })
  const [margin, setMargin] = useState('')
  const [onLabour, setOnLabour] = useState(false)
  const [lines, setLines] = useState<ExtraQuoteLine[]>([])
  const [notes, setNotes] = useState('')
  const [validity, setValidity] = useState('')
  const [saving, setSaving] = useState(false)
  const setLine = (i: number, patch: Partial<ExtraQuoteLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      await onCreate({
        client: { name: client.name.trim(), email: client.email.trim() || null, phone: client.phone.trim(), address: client.address.trim() },
        margin_pct: margin.trim() || null,
        margin_on_labour: onLabour,
        extra_lines: lines.filter((l) => l.description.trim() && Number(l.rate) > 0),
        notes: notes.trim() || null,
        validity_days: validity.trim() ? Number(validity) : null,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 text-sm">
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-1 font-semibold">Client</legend>
        <input value={client.name} onChange={(e) => setClient({ ...client, name: e.target.value })} required placeholder="Name" aria-label="Client name" className={inputClass} />
        <input value={client.email} onChange={(e) => setClient({ ...client, email: e.target.value })} type="email" placeholder="Email (optional)" aria-label="Client email" className={inputClass} />
        <input value={client.phone} onChange={(e) => setClient({ ...client, phone: e.target.value })} placeholder="Phone (optional)" aria-label="Client phone" className={inputClass} />
        <input value={client.address} onChange={(e) => setClient({ ...client, address: e.target.value })} placeholder="Site address (optional)" aria-label="Client address" className={inputClass} />
      </fieldset>
      <div className="flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="mb-1 block text-slate-600">Margin on materials</span>
          <span className="flex items-center gap-1.5">
            <input
              value={margin}
              onChange={(e) => setMargin(e.target.value)}
              inputMode="decimal"
              placeholder={String(Number(company.default_margin_pct))}
              className="w-20 rounded-md border border-slate-300 px-3 py-2"
            />
            %
          </span>
        </label>
        <label className="flex items-center gap-2 pb-2">
          <input type="checkbox" checked={onLabour} onChange={(e) => setOnLabour(e.target.checked)} className="accent-brand-600" />
          Add the margin to delivery and labour too
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Valid for</span>
          <span className="flex items-center gap-1.5">
            <input
              value={validity}
              onChange={(e) => setValidity(e.target.value)}
              inputMode="numeric"
              placeholder={String(company.validity_days)}
              className="w-20 rounded-md border border-slate-300 px-3 py-2"
            />
            days
          </span>
        </label>
      </div>
      <fieldset className="space-y-2">
        <legend className="font-semibold">Extra lines on this quote</legend>
        <p className="text-xs text-slate-500">
          Delivery and labour from the cost settings are already included. Add anything else, like removing old tiles.
        </p>
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_5rem_5rem_7rem_auto_auto]">
            <input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} placeholder="Description" aria-label={`Line ${i + 1} description`} className={`${inputClass} col-span-2 sm:col-span-1`} />
            <input value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} inputMode="decimal" aria-label={`Line ${i + 1} quantity`} className={inputClass} />
            <input value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} aria-label={`Line ${i + 1} unit`} className={inputClass} />
            <input value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} inputMode="decimal" placeholder="Rate" aria-label={`Line ${i + 1} rate`} className={inputClass} />
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={l.taxable} onChange={(e) => setLine(i, { taxable: e.target.checked })} className="accent-brand-600" />
              Taxable
            </label>
            <button type="button" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} className="text-red-700 hover:underline">
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setLines((ls) => [...ls, { kind: 'labour', description: '', quantity: '1', unit: 'item', rate: '', taxable: true }])}
          className="font-medium text-brand-700 hover:underline"
        >
          + Add a line
        </button>
      </fieldset>
      <label className="block">
        <span className="mb-1 block text-slate-600">Notes for the client (optional)</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={1000} className={inputClass} />
      </label>
      <p className="text-xs text-slate-500">
        The quote is a snapshot of the estimate now. If the project changes later, use Revise to make a new version.
      </p>
      <Button type="submit" disabled={saving}>
        {saving ? 'Making quote…' : 'Make quote'}
      </Button>
    </form>
  )
}
