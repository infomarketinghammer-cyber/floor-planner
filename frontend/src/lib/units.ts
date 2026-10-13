import type { LengthUnit, Room } from '../api/types.ts'
import type { AreaUnit } from './format.ts'

// Display-only conversions. Stored values stay exact decimal millimetres on the server.

export const lengthUnitLabels: Record<LengthUnit, string> = {
  ft_in: 'Feet & inches',
  ft: 'Feet',
  in: 'Inches',
  m: 'Metres',
  cm: 'Centimetres',
  mm: 'Millimetres',
}

const MM_PER: Record<Exclude<LengthUnit, 'ft_in'>, number> = { ft: 304.8, in: 25.4, m: 1000, cm: 10, mm: 1 }
const SUFFIX: Record<Exclude<LengthUnit, 'ft_in'>, string> = { ft: ' ft', in: '"', m: ' m', cm: ' cm', mm: ' mm' }
const DECIMALS: Record<Exclude<LengthUnit, 'ft_in'>, number> = { ft: 2, in: 1, m: 3, cm: 1, mm: 0 }

function trim(value: number, decimals: number): string {
  return String(Number(value.toFixed(decimals)))
}

export function formatLength(mm: string | null, unit: LengthUnit): string {
  if (mm === null) return '?'
  const value = Number(mm)
  if (unit === 'ft_in') {
    const totalInches = Math.round((value / 25.4) * 10) / 10 // nearest 0.1"
    let feet = Math.floor(totalInches / 12)
    let inches = Math.round((totalInches - feet * 12) * 10) / 10
    if (inches >= 12) {
      feet += 1
      inches = 0
    }
    return `${feet}'${trim(inches, 1)}"`
  }
  return `${trim(value / MM_PER[unit], DECIMALS[unit])}${SUFFIX[unit]}`
}

export function roomArea(room: Room, unit: AreaUnit): number | null {
  const mm2 = room.parts?.length
    ? room.parts.reduce((sum, p) => sum + Number(p.length_mm) * Number(p.width_mm), 0)
    : room.length_mm !== null && room.width_mm !== null
      ? Number(room.length_mm) * Number(room.width_mm)
      : room.area_mm2 !== null
        ? Number(room.area_mm2)
        : null
  if (mm2 === null) return null
  return unit === 'sqm' ? mm2 / 1_000_000 : mm2 / 92_903.04
}

/** Text for an edit box: 12'6" for feet-inches, otherwise a bare number in the room's unit. */
export function editableLength(mm: string | null, unit: LengthUnit): string {
  if (mm === null) return ''
  if (unit === 'ft_in') return formatLength(mm, 'ft_in')
  return trim(Number(mm) / MM_PER[unit], 4)
}

/**
 * The bare number as written in `unit`, used when the user says "the unit was wrong":
 * the same digits are re-read in the new unit (e.g. 3600 assumed mm → actually cm).
 * Feet-inches becomes decimal feet.
 */
export function bareNumber(mm: string | null, unit: LengthUnit): string {
  if (mm === null) return ''
  return trim(Number(mm) / (unit === 'ft_in' ? 304.8 : MM_PER[unit]), 4)
}
