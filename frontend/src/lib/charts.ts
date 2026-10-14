/** Chart colours (checked for colour-blind separation and 3:1 contrast on white): one series uses
 * the brand teal; a second series uses orange. Text never takes the series colour. */
export const SERIES = ['#039583', '#eb6834'] as const

/** 1,284 / 12.9K / 4.2M, for axis ticks. */
export function compact(n: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}
