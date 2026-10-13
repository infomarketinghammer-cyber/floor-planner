import type { CostLine, CostSettings } from '../api/types.ts'

/** Currency and number format (PRD 4.10). Display only: the server stores plain decimal amounts. */
export type MoneyFormat = Pick<CostSettings, 'currency' | 'locale'>

export const DEFAULT_MONEY: MoneyFormat = { currency: 'INR', locale: 'en-IN' }

/** Currencies offered in the settings. A saved currency outside this list is still shown. */
export const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'AUD', 'CAD', 'SGD', 'SAR', 'ZAR', 'NZD', 'JPY'] as const

/** Number formats by region: this decides the digit grouping, the decimal mark and the symbol position. */
export const REGIONS: { locale: string; name: string }[] = [
  { locale: 'en-IN', name: 'India' },
  { locale: 'en-US', name: 'United States' },
  { locale: 'en-GB', name: 'United Kingdom' },
  { locale: 'en-AU', name: 'Australia' },
  { locale: 'en-AE', name: 'UAE' },
  { locale: 'de-DE', name: 'Germany' },
  { locale: 'fr-FR', name: 'France' },
  { locale: 'es-ES', name: 'Spain' },
]

const formatters = new Map<string, (n: number) => string>()

function formatterFor({ currency, locale }: MoneyFormat): (n: number) => string {
  const key = `${locale}|${currency}`
  let format = formatters.get(key)
  if (!format) {
    try {
      format = new Intl.NumberFormat(locale, { style: 'currency', currency }).format
    } catch {
      // An unknown locale or currency code: show the code and a plain number instead of crashing.
      const plain = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      format = (n) => `${currency} ${plain.format(n)}`
    }
    formatters.set(key, format)
  }
  return format
}

/** "₹12,34,567.89" in India, "$1,234,567.89" in the US, "1.234.567,89 €" in Germany. */
export function formatMoney(value: string | number | null | undefined, fmt: MoneyFormat): string {
  if (value === null || value === undefined || value === '') return '–'
  const n = Number(value)
  return Number.isFinite(n) ? formatterFor(fmt)(n) : '–'
}

export function currencyName(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'currency' }).of(code) ?? code
  } catch {
    return code
  }
}

export function formatNumber(value: string | number, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(Number(value))
  } catch {
    return String(value)
  }
}

export const LINE_KIND_LABELS = { delivery: 'Delivery', labour: 'Labour', other: 'Other' } as const
export const LINE_BASIS_LABELS = { fixed: 'Fixed amount', sqft: 'per sq ft', sqm: 'per m²', box: 'per box' } as const
const BASIS_UNITS = { sqft: 'sq ft', sqm: 'm²', box: 'boxes' } as const

/** "₹40.00 × 232.5 sq ft": how a per-area or per-box line was worked out. Empty for fixed amounts. */
export function lineDetail(
  line: Pick<CostLine, 'basis'> & { rate: string; quantity: string | null },
  fmt: MoneyFormat,
): string {
  if (line.basis === 'fixed' || line.quantity === null) return ''
  return `${formatMoney(line.rate, fmt)} × ${formatNumber(line.quantity, fmt.locale)} ${BASIS_UNITS[line.basis]}`
}