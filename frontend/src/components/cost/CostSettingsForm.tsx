import { useState } from 'react'
import type { CostLine, CostSettings, LineBasis, LineKind } from '../../api/types.ts'
import {
  CURRENCIES,
  LINE_BASIS_LABELS,
  LINE_KIND_LABELS,
  REGIONS,
  currencyName,
  formatMoney,
} from '../../lib/money.ts'
import { Button, ErrorText } from '../ui.tsx'

const inputClass = 'rounded-md border border-slate-300 px-3 py-2 text-sm'

/** Ids for lines added in this form. They are saved as they are and stay with the line. */
let draftCounter = 0
const draftId = () => `new-${++draftCounter}`

/**
 * Cost settings (PRD 4.10): currency and number format, tax, delivery/labour/other lines and the
 * budget target. Edits a local copy and saves it in one go.
 */
export function CostSettingsForm({
  settings,
  busy,
  onSave,
  onCancel,
}: {
  settings: CostSettings
  busy?: boolean
  /** Resolves with an error message, or null once saved. */
  onSave: (settings: CostSettings) => Promise<string | null>
  onCancel: () => void
}) {
  const [draft, setDraft] = useState<CostSettings>(settings)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const patch = (changes: Partial<CostSettings>) => setDraft((d) => ({ ...d, ...changes }))
  const setLine = (id: string, changes: Partial<CostLine>) =>
    patch({ lines: draft.lines.map((l) => (l.id === id ? { ...l, ...changes } : l)) })
  const addLine = (kind: LineKind) =>
    patch({
      lines: [
        ...draft.lines,
        {
          id: draftId(),
          kind,
          label: kind === 'other' ? '' : LINE_KIND_LABELS[kind],
          amount: '',
          basis: kind === 'labour' ? 'sqft' : 'fixed',
          taxable: true,
        },
      ],
    })

  const currencies = CURRENCIES.includes(draft.currency as (typeof CURRENCIES)[number])
    ? [...CURRENCIES]
    : [draft.currency, ...CURRENCIES]
  const regions = REGIONS.some((r) => r.locale === draft.locale)
    ? REGIONS
    : [{ locale: draft.locale, name: draft.locale }, ...REGIONS]

  async function submit() {
    const positive = (v: string) => Number.isFinite(Number(v)) && Number(v) > 0
    const tax = draft.tax_pct.trim() === '' ? '0' : draft.tax_pct.trim()
    if (!(Number(tax) >= 0 && Number(tax) <= 100)) return setError('Tax must be between 0 and 100%.')
    for (const line of draft.lines) {
      if (!line.label.trim()) return setError('Give every extra cost a name.')
      if (!positive(line.amount)) return setError(`Enter an amount above zero for "${line.label.trim()}", or remove it.`)
    }
    const budget = (draft.budget ?? '').trim()
    if (budget && !positive(budget)) return setError('The budget must be above zero. Leave it empty for no budget.')

    setSaving(true)
    setError('')
    const message = await onSave({
      ...draft,
      tax_label: draft.tax_label.trim() || 'Tax',
      tax_pct: tax,
      lines: draft.lines.map((l) => ({ ...l, label: l.label.trim(), amount: l.amount.trim() })),
      budget: budget || null,
    })
    setSaving(false)
    if (message) setError(message)
  }

  const sample = formatMoney(1234567.89, draft)

  return (
    <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
      <ErrorText>{error}</ErrorText>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Currency and format</legend>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Currency</span>
          <select
            value={draft.currency}
            onChange={(e) => patch({ currency: e.target.value })}
            className={`${inputClass} w-full`}
          >
            {currencies.map((c) => (
              <option key={c} value={c}>
                {c} · {currencyName(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Number format</span>
          <select
            value={draft.locale}
            onChange={(e) => patch({ locale: e.target.value })}
            className={`${inputClass} w-full`}
          >
            {regions.map((r) => (
              <option key={r.locale} value={r.locale}>
                {r.name} · {formatMoney(1234567.89, { currency: draft.currency, locale: r.locale })}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-500 sm:col-span-2">Shown as {sample}</p>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="mb-2 text-sm font-semibold">Tax</legend>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Name</span>
            <input
              value={draft.tax_label}
              onChange={(e) => patch({ tax_label: e.target.value })}
              maxLength={30}
              placeholder="GST, VAT, Sales tax"
              className={`${inputClass} w-44`}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Rate</span>
            <span className="flex items-center gap-1">
              <input
                value={draft.tax_pct}
                onChange={(e) => patch({ tax_pct: e.target.value })}
                inputMode="decimal"
                aria-label="Tax rate in percent"
                className={`${inputClass} w-24`}
              />
              %
            </span>
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={draft.tax_materials}
              onChange={(e) => patch({ tax_materials: e.target.checked })}
              className="accent-brand-600"
            />
            Charged on the tiles
          </label>
        </div>
        <p className="text-xs text-slate-500">
          Leave the rate at 0 for no tax. Tick or untick “Taxable” on each extra cost below.
        </p>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="mb-2 text-sm font-semibold">Delivery, labour and other costs</legend>
        {draft.lines.length === 0 && <p className="text-sm text-slate-500">None added.</p>}
        <ul className="space-y-3">
          {draft.lines.map((line) => (
            <li key={line.id} className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 p-3">
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-slate-500">Name</span>
                <input
                  value={line.label}
                  onChange={(e) => setLine(line.id!, { label: e.target.value })}
                  maxLength={60}
                  aria-label="Cost name"
                  className={`${inputClass} w-40`}
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-slate-500">Type</span>
                <select
                  value={line.kind}
                  onChange={(e) => setLine(line.id!, { kind: e.target.value as LineKind })}
                  aria-label="Cost type"
                  className={inputClass}
                >
                  {(Object.keys(LINE_KIND_LABELS) as LineKind[]).map((k) => (
                    <option key={k} value={k}>
                      {LINE_KIND_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-slate-500">Amount</span>
                <input
                  value={line.amount}
                  onChange={(e) => setLine(line.id!, { amount: e.target.value })}
                  inputMode="decimal"
                  aria-label="Amount"
                  className={`${inputClass} w-28`}
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-slate-500">Charged</span>
                <select
                  value={line.basis}
                  onChange={(e) => setLine(line.id!, { basis: e.target.value as LineBasis })}
                  aria-label="How the amount is charged"
                  className={inputClass}
                >
                  {(Object.keys(LINE_BASIS_LABELS) as LineBasis[]).map((b) => (
                    <option key={b} value={b}>
                      {LINE_BASIS_LABELS[b]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1.5 pb-2 text-sm">
                <input
                  type="checkbox"
                  checked={line.taxable}
                  onChange={(e) => setLine(line.id!, { taxable: e.target.checked })}
                  className="accent-brand-600"
                />
                Taxable
              </label>
              <button
                type="button"
                onClick={() => patch({ lines: draft.lines.filter((l) => l.id !== line.id) })}
                className="ml-auto pb-2 text-sm text-red-700 hover:underline"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2 text-sm">
          {(Object.keys(LINE_KIND_LABELS) as LineKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => addLine(kind)}
              disabled={draft.lines.length >= 20}
              className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50 disabled:opacity-50"
            >
              + {LINE_KIND_LABELS[kind]}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Budget</legend>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Target for the project total (optional)</span>
          <input
            value={draft.budget ?? ''}
            onChange={(e) => patch({ budget: e.target.value })}
            inputMode="decimal"
            placeholder="No budget set"
            className={`${inputClass} w-48`}
          />
        </label>
        <p className="mt-1 text-xs text-slate-500">
          You’ll see a warning at 90% of the budget and an alert once the total goes over it.
        </p>
      </fieldset>

      <div className="flex items-center gap-3">
        <Button type="button" onClick={submit} disabled={saving || busy}>
          {saving ? 'Saving…' : 'Save cost settings'}
        </Button>
        <button type="button" onClick={onCancel} className="text-sm text-slate-600 hover:underline">
          Cancel
        </button>
      </div>
    </div>
  )
}   