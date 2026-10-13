import type { Estimate } from '../api/types.ts'

/** One thing to buy. Mirrors the server's export shopping list (backend/app/exports/data.py). */
export interface ShopLine {
  section: 'Floor' | 'Walls' | 'Skirting' | 'Sundries'
  key: string
  name: string
  size: string
  quantity: string
  detail: string
}

const boxes = (n: number) => `${n} ${n === 1 ? 'box' : 'boxes'}`
const metres = (mm: string | number) => `${Number((Number(mm) / 1000).toFixed(2))} m`

export function shoppingLines(estimate: Estimate): ShopLine[] {
  const out: ShopLine[] = estimate.tiles.map((t) =>
    t.linear_mm !== null
      ? {
          section: 'Floor',
          key: `f:${t.tile.id}`,
          name: t.tile.name,
          size: `${metres(t.tile.width_mm)} wide roll`,
          quantity: `${metres(t.linear_mm)} of roll`,
          detail: `${t.rooms} room${t.rooms === 1 ? '' : 's'}`,
        }
      : {
          section: 'Floor',
          key: `f:${t.tile.id}`,
          name: t.tile.name,
          size: t.tile.size_label,
          quantity: boxes(t.boxes),
          detail: `${t.tiles_bought} ${t.tile.kind === 'plank' ? 'planks' : 'tiles'}, ${t.tile.tiles_per_box} per box`,
        },
  )
  const x = estimate.extras
  if (!x) return out
  for (const w of x.wall_tiles) {
    out.push({
      section: 'Walls',
      key: `w:${w.tile.id}`,
      name: w.tile.name,
      size: w.tile.size_label,
      quantity: boxes(w.boxes),
      detail: `${w.tiles_bought} tiles, ${w.tile.tiles_per_box} per box`,
    })
  }
  for (const p of x.skirting?.products ?? []) {
    out.push({
      section: 'Skirting',
      key: `s:${p.label}`,
      name: p.label,
      size: `${Number(x.skirting!.height_mm)} mm high`,
      quantity: p.boxes !== null ? boxes(p.boxes) : `${p.pieces} pieces`,
      detail: p.tile
        ? `${p.tiles} tiles cut into ${p.pieces} strips, ${metres(p.run_mm)} run`
        : `${p.pieces} pieces of ${metres(p.piece_length_mm)}, ${metres(p.run_mm)} run`,
    })
  }
  for (const s of x.sundries) {
    const unit = s.key === 'adhesive' ? 'bags' : 'packs'
    out.push({
      section: 'Sundries',
      key: `x:${s.key}`,
      name: s.label,
      size: `${Number(s.pack_size)} ${s.unit} ${unit.slice(0, -1)}`,
      quantity: `${s.packs} ${unit}`,
      detail: `${Number(s.quantity)} ${s.unit}`,
    })
  }
  return out
}

/** Plain text for pasting into a message to a supplier. */
export function shoppingText(estimate: Estimate): string {
  const lines: string[] = []
  let section = ''
  for (const l of shoppingLines(estimate)) {
    if (l.section !== section) {
      if (section) lines.push('')
      section = l.section
      lines.push(`${section}:`)
    }
    lines.push(`- ${l.size} ${l.name}: ${l.quantity} (${l.detail})`)
  }
  return [...lines, '', 'Estimate only: verify quantities before ordering.'].join('\n')
}
