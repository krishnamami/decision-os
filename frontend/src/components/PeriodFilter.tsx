// Date-range dropdown shared across every product page.
// Default "All Time". The chosen value is passed to the API as ?period=…
// (month → 30d, quarter → 90d, year → 365d, all → no date filter).

export type Period = 'month' | 'quarter' | 'year' | 'all'

export const PERIOD_OPTIONS: Array<{ value: Period; label: string }> = [
  { value: 'month', label: 'This Month' },
  { value: 'quarter', label: 'This Quarter' },
  { value: 'year', label: 'This Year' },
  { value: 'all', label: 'All Time' },
]

// Map a period to the query value the API expects (undefined = no filter).
export function periodParam(p: Period): string | undefined {
  return p === 'all' ? undefined : p
}

export default function PeriodFilter({
  value,
  onChange,
  className = '',
}: {
  value: Period
  onChange: (p: Period) => void
  className?: string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as Period)}
      aria-label="Date range"
      className={`rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand ${className}`}
    >
      {PERIOD_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}
