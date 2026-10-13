import { useAreaUnit, type AreaUnit } from '../lib/format.ts'

/** Account-wide display preference (PRD 4.4). Saved to the user's profile, not the browser. */
export function UnitSystemToggle() {
  const [value, setValue] = useAreaUnit()
  const options: [AreaUnit, string, string][] = [
    ['sqft', 'Imperial', 'Show areas in square feet'],
    ['sqm', 'Metric', 'Show areas in square metres'],
  ]
  return (
    <div role="group" aria-label="Units" className="flex rounded-md border border-slate-300 bg-white p-0.5 text-xs">
      {options.map(([unit, label, title]) => (
        <button
          key={unit}
          onClick={() => setValue(unit)}
          aria-pressed={value === unit}
          title={title}
          className={`rounded px-2 py-1 ${value === unit ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
