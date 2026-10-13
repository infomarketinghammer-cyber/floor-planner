import type { Estimate } from '../../api/types.ts'

// Reference categorical palette, fixed order (dataviz skill). Colour follows the tile, by its
// position in the estimate's tile list; past 8 tile types, the rest share a neutral grey.
const SLOTS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
const OTHER = '#8a8984'

export function tileColors(estimate: Estimate): Map<string, string> {
  return new Map(estimate.tiles.map((t, i) => [t.tile.id, SLOTS[i] ?? OTHER]))
}
