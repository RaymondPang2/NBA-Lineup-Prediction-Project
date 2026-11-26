import { useState } from 'react'
import { useWidth } from '../../lib/useWidth'
import { C } from './ChartFrame'

export interface DotSeries {
  key: string
  label: string
  color: string
}

export interface DotRow {
  label: string
  /** per series: value and optional 95% interval */
  values: Record<string, { v: number | null; lo?: number; hi?: number; note?: string }>
}

/**
 * Dot-and-whisker plot on one horizontal axis: rows are categories, each row can carry several series
 * (offset vertically so they never overlap). Whiskers are 95% intervals. Hand-drawn SVG so the axis
 * need not start at zero (ratings cluster around 110) and intervals are exact.
 */
export function DotWhisker({
  rows,
  series,
  format,
  zeroLine = false,
  reference,
  axisLabel,
}: {
  rows: DotRow[]
  series: DotSeries[]
  format: (x: number) => string
  zeroLine?: boolean
  reference?: { value: number; label: string }
  /** Title of the horizontal axis, with units. */
  axisLabel?: string
}) {
  const { ref, width } = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const labelW = width < 480 ? 92 : 132
  const rowH = 22 + series.length * 16
  const top = 6
  const height = top + rows.length * rowH + (axisLabel ? 44 : 26)
  const vals = rows.flatMap((r) => series.flatMap((s) => [r.values[s.key]?.v, r.values[s.key]?.lo, r.values[s.key]?.hi])).filter((x): x is number => typeof x === 'number' && Number.isFinite(x))
  if (zeroLine) vals.push(0)
  if (reference) vals.push(reference.value)
  const minV = Math.min(...vals)
  const maxV = Math.max(...vals)
  const span = Math.max(1, maxV - minV)
  const raw = span / 5
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = (raw / mag < 1.5 ? 1 : raw / mag < 3.5 ? 2 : raw / mag < 7.5 ? 5 : 10) * mag
  const lo = Math.floor(minV / step) * step
  const hi = Math.ceil(maxV / step) * step
  const x = (v: number) => labelW + ((v - lo) / (hi - lo || 1)) * (width - labelW - 14)
  const ticks: number[] = []
  for (let t = lo; t <= hi + 1e-9; t += step) ticks.push(Number(t.toFixed(6)))
  const plotBottom = top + rows.length * rowH

  return (
    <div ref={ref} className="w-full min-w-0">
      <svg width={width} height={height} role="img" aria-label={rows.map((r) => `${r.label}: ${series.map((s) => `${s.label} ${r.values[s.key]?.v === null || r.values[s.key]?.v === undefined ? 'n/a' : format(r.values[s.key]!.v as number)}`).join(', ')}`).join('; ')}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={plotBottom} stroke={zeroLine && t === 0 ? C.axis : C.grid} />
            <text x={x(t)} y={plotBottom + 16} textAnchor="middle" fontSize={11} fill={C.muted} className="tabular">
              {format(t)}
            </text>
          </g>
        ))}
        {axisLabel && (
          <text x={labelW + (width - labelW - 14) / 2} y={plotBottom + 36} textAnchor="middle" fontSize={11} fill={C.ink2}>
            {axisLabel}
          </text>
        )}
        {reference && <line x1={x(reference.value)} x2={x(reference.value)} y1={top} y2={plotBottom} stroke={C.ink2} strokeWidth={1.5} />}
        {rows.map((r, i) => {
          const y0 = top + i * rowH
          return (
            <g key={r.label}>
              <text x={0} y={y0 + rowH / 2} dy={4} fontSize={12} fill={C.ink2}>
                {r.label}
              </text>
              {series.map((s, j) => {
                const d = r.values[s.key]
                if (!d || d.v === null || d.v === undefined) return null
                const cy = y0 + 11 + j * 16 + (series.length === 1 ? rowH / 2 - 11 : 0)
                const text = `${r.label} · ${s.label}: ${format(d.v)}${d.lo !== undefined && d.hi !== undefined ? ` (95%: ${format(d.lo)} to ${format(d.hi)})` : ''}${d.note ? ` · ${d.note}` : ''}`
                return (
                  <g key={s.key} onMouseEnter={() => setHover(text)} onMouseLeave={() => setHover(null)}>
                    <rect x={labelW} y={cy - 8} width={width - labelW} height={16} fill="transparent" />
                    {d.lo !== undefined && d.hi !== undefined && (
                      <>
                        <line x1={x(d.lo)} x2={x(d.hi)} y1={cy} y2={cy} stroke={s.color} strokeWidth={2} strokeLinecap="round" />
                        <line x1={x(d.lo)} x2={x(d.lo)} y1={cy - 4} y2={cy + 4} stroke={s.color} strokeWidth={2} />
                        <line x1={x(d.hi)} x2={x(d.hi)} y1={cy - 4} y2={cy + 4} stroke={s.color} strokeWidth={2} />
                      </>
                    )}
                    <circle cx={x(d.v)} cy={cy} r={5.5} fill={s.color} stroke={C.surface} strokeWidth={2} />
                    <title>{text}</title>
                  </g>
                )
              })}
            </g>
          )
        })}
      </svg>
      <p aria-live="polite" className="tabular min-h-5 text-xs text-ink-2">
        {hover ?? 'Hover a point for its value.'}
      </p>
    </div>
  )
}
