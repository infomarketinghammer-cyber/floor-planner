import { useCallback } from 'react'
import { useAuth } from '../auth/AuthContext.tsx'
import type { Project } from '../api/types.ts'

export type AreaUnit = 'sqft' | 'sqm'

const areaLabels: Record<AreaUnit, string> = { sqft: 'sq ft', sqm: 'm²' }
const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

/** Area unit from the user's account preference (PRD 4.4): imperial → sq ft, metric → m². */
export function useAreaUnit(): [AreaUnit, (unit: AreaUnit) => void] {
  const { user, updatePreferences } = useAuth()
  const unit: AreaUnit = user?.preferences.unit_system === 'metric' ? 'sqm' : 'sqft'
  const setUnit = useCallback(
    (next: AreaUnit) => void updatePreferences({ unit_system: next === 'sqm' ? 'metric' : 'imperial' }),
    [updatePreferences],
  )
  return [unit, setUnit]
}

export function projectArea(project: Project, unit: AreaUnit): number {
  return unit === 'sqm' ? project.total_area_sqm : project.total_area_sqft
}

export function formatArea(value: number, unit: AreaUnit): string {
  return `${numberFormat.format(value)} ${areaLabels[unit]}`
}

const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
const steps: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

export function formatRelative(iso: string, now = Date.now()): string {
  const seconds = (new Date(iso).getTime() - now) / 1000
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

export function attentionReasons(project: Project): string[] {
  const reasons: string[] = []
  if (project.unconfirmed_rooms) reasons.push(`${plural(project.unconfirmed_rooms, 'room')} not confirmed`)
  if (project.rooms_missing_size) reasons.push(`${plural(project.rooms_missing_size, 'room')} missing size`)
  if (project.rooms_missing_tile) reasons.push(`${plural(project.rooms_missing_tile, 'room')} without a tile`)
  if (project.unit_unconfirmed) reasons.push('plan unit not confirmed')
  return reasons
}

const PRICE_BASIS_LABELS = { box: 'box', tile: 'tile', sqft: 'sq ft', sqm: 'm²', lm: 'm' } as const

/** "52 / sq ft". Shown without a currency symbol, as the price was entered. */
export function formatPrice(price: { amount: string; basis: keyof typeof PRICE_BASIS_LABELS } | null): string {
  if (!price) return '–'
  return `${numberFormat.format(Number(price.amount))} / ${PRICE_BASIS_LABELS[price.basis]}`
}
