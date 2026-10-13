import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../../api/client.ts'
import type { CompanyProfile } from '../../api/types.ts'
import { Button, ErrorText } from '../ui.tsx'

const inputClass = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      {children}
    </label>
  )
}

/** Company details and logo shown on quotations (PRD 4.19). */
export function CompanyCard() {
  const [form, setForm] = useState<CompanyProfile | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [logoKey, setLogoKey] = useState(0) // re-fetch the image after a change

  useEffect(() => {
    api.company
      .get()
      .then(setForm)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (!form) return error ? <ErrorText>{error}</ErrorText> : null
  const set = <K extends keyof CompanyProfile>(k: K, v: CompanyProfile[K]) => {
    setForm({ ...form, [k]: v })
    setSaved(false)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      setForm(await api.company.save(form!))
      setSaved(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function logo(file: File | null) {
    setError('')
    try {
      setForm(file ? await api.company.uploadLogo(file) : await api.company.removeLogo())
      setLogoKey((k) => k + 1)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <div>
        <h2 className="font-semibold">Company details for quotes</h2>
        <p className="text-sm text-slate-500">Shown on every quotation you send.</p>
      </div>
      <ErrorText>{error}</ErrorText>
      <div className="flex flex-wrap items-center gap-4">
        {form.has_logo ? (
          <img key={logoKey} src={`${api.company.logoUrl}?v=${logoKey}`} alt="Company logo" className="h-14 max-w-48 rounded border border-slate-200 object-contain p-1" />
        ) : (
          <div className="flex h-14 w-28 items-center justify-center rounded border border-dashed border-slate-300 text-xs text-slate-400">No logo</div>
        )}
        <label className="cursor-pointer text-sm font-medium text-brand-700 hover:underline">
          {form.has_logo ? 'Change logo' : 'Upload logo'}
          <input type="file" accept="image/png,image/jpeg" className="sr-only" onChange={(e) => void logo(e.target.files?.[0] ?? null)} />
        </label>
        {form.has_logo && (
          <button type="button" onClick={() => void logo(null)} className="text-sm text-slate-600 hover:underline">
            Remove
          </button>
        )}
        <span className="text-xs text-slate-500">PNG or JPEG, under 1 MB</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Company name">
          <input value={form.name} onChange={(e) => set('name', e.target.value)} maxLength={120} className={inputClass} />
        </Field>
        <Field label="Email">
          <input value={form.email} onChange={(e) => set('email', e.target.value)} maxLength={254} className={inputClass} />
        </Field>
        <Field label="Phone">
          <input value={form.phone} onChange={(e) => set('phone', e.target.value)} maxLength={40} className={inputClass} />
        </Field>
        <Field label="Website">
          <input value={form.website} onChange={(e) => set('website', e.target.value)} maxLength={200} className={inputClass} />
        </Field>
        <Field label="Address">
          <textarea value={form.address} onChange={(e) => set('address', e.target.value)} rows={2} maxLength={400} className={inputClass} />
        </Field>
        <div className="grid grid-cols-[7rem_1fr] gap-2">
          <Field label="Tax ID name">
            <input value={form.tax_id_label} onChange={(e) => set('tax_id_label', e.target.value)} maxLength={20} className={inputClass} />
          </Field>
          <Field label="Tax ID">
            <input value={form.tax_id} onChange={(e) => set('tax_id', e.target.value)} maxLength={40} className={inputClass} />
          </Field>
        </div>
      </div>
      <div className="flex flex-wrap gap-4">
        <Field label="Default margin on materials (%)">
          <input value={form.default_margin_pct} onChange={(e) => set('default_margin_pct', e.target.value)} inputMode="decimal" className={`${inputClass} w-24`} />
        </Field>
        <Field label="Quotes valid for (days)">
          <input
            value={form.validity_days}
            onChange={(e) => set('validity_days', Math.max(1, Number(e.target.value) || 1))}
            inputMode="numeric"
            className={`${inputClass} w-24`}
          />
        </Field>
        <Field label="Quote number prefix">
          <input value={form.quote_prefix} onChange={(e) => set('quote_prefix', e.target.value)} maxLength={10} className={`${inputClass} w-24`} />
        </Field>
      </div>
      <Field label="Terms printed on quotes">
        <textarea value={form.terms} onChange={(e) => set('terms', e.target.value)} rows={3} maxLength={2000} className={inputClass} />
      </Field>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save company details'}
        </Button>
        {saved && <span className="text-sm text-green-700">Saved</span>}
      </div>
    </form>
  )
}
