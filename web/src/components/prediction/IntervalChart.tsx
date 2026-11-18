import { useState } from 'react'
import type { Prediction } from '../../api/types'
import { fmtInterval, fmtSigned } from '../../lib/format'
import { useWidth } from '../../lib/useWidth'
import { C, Legend, type LegendItem } from '../charts/ChartFrame'

function niceStep(span: number): number {
  const raw = span / 6
  const mag = 10 ** Math.floor(Math.log10(raw))
  const n = raw / mag
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag
}

/**
 * The prediction on one net-rating axis, with both 95% intervals as bands and the baselines as reference
 * lines. Hand-drawn SVG: two bands, three reference values and an optional observed result.
 */
export function IntervalChart({ prediction, observed }: { prediction: Prediction; observed?: number | null }) {
  const { ref, width } = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const u = prediction.uncertainty
  const yhat = prediction.predicted_net_rating
  const prior = prediction.baselines.team_prior
  const league = prediction.baselines.league_mean
  const bands = [
    { key: 'true', label: width < 520 ? 'True quality, 95%' : 'True quality · 95% interval', sub: `model SD ${u.model_sd.toFixed(1)}`, lo: u.true_rating_interval_95.lo, hi: u.true_rating_interval_95.hi, fill: C.band1 },
    {
      key: 'observed',
      label: width < 520 ? `Observed over ${u.possessions.toLocaleString()} poss., 95%` : `Observed rating over ${u.possessions.toLocaleString()} possessions · 95% interval`,
      sub: `total SD ${u.total_sd.toFixed(1)}`,
      lo: u.observed_rating_interval_95.lo,
      hi: u.observed_rating_interval_95.hi,
      fill: C.band2,
    },
  ]
  const values = [yhat, prior, league, 0, ...bands.flatMap((b) => [b.lo, b.hi]), ...(typeof observed === 'number' ? [observed] : [])]
  const step = niceStep(Math.max(...values) - Math.min(...values))
  const lo = Math.floor(Math.min(...values) / step) * step
  const hi = Math.ceil(Math.max(...values) / step) * step
  const pad = { l: 12, r: 12 }
  const top = 22
  const rowH = 58
  const height = top + bands.length * rowH + 26
  const x = (v: number) => pad.l + ((v - lo) / (hi - lo)) * (width - pad.l - pad.r)
  const ticks: number[] = []
  for (let t = lo; t <= hi + 1e-9; t += step) ticks.push(Number(t.toFixed(6)))
  const plotBottom = top + bands.length * rowH

  const refs = [
    { key: 'prior', label: 'Team-prior baseline', v: prior, color: C.s2 },
    { key: 'league', label: 'League mean', v: league, color: C.s3 },
  ]
  const legend: LegendItem[] = [
    { label: 'Model prediction', color: C.s1 },
    { label: 'Team-prior baseline', color: C.s2, shape: 'line' },
    { label: 'League mean', color: C.s3, shape: 'line' },
    { label: 'True-quality interval', color: C.band1, shape: 'band' },
    { label: 'Observed-rating interval', color: C.band2, shape: 'band' },
    ...(typeof observed === 'number' ? [{ label: 'Realized post-break', color: C.ink, shape: 'dot' as const }] : []),
  ]
  const hoverText: Record<string, string> = {
    model: `Model prediction ${fmtSigned(yhat)}`,
    prior: `Team-prior baseline ${fmtSigned(prior)}`,
    league: `League mean ${fmtSigned(league)}`,
    true: `True quality 95%: ${fmtInterval(bands[0].lo, bands[0].hi)}`,
    observed: `Observed 95%: ${fmtInterval(bands[1].lo, bands[1].hi)}`,
    realized: `Realized post-break ${fmtSigned(observed)}`,
  }

  return (
    <div>
      <div className="mb-3">
        <Legend items={legend} />
      </div>
      <div ref={ref} className="relative w-full min-w-0">
        <svg width={width} height={height} role="img" aria-label={`Prediction ${fmtSigned(yhat)} with 95% intervals ${hoverText.true} and ${hoverText.observed}; team prior ${fmtSigned(prior)}; league mean ${fmtSigned(league)}.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={top - 4} y2={plotBottom} stroke={t === 0 ? C.axis : C.grid} strokeWidth={1} />
              <text x={x(t)} y={plotBottom + 16} textAnchor="middle" fontSize={11} fill={C.muted} className="tabular">
                {t > 0 ? `+${t}` : t < 0 ? `−${Math.abs(t)}` : '0'}
              </text>
            </g>
          ))}
          {bands.map((b, i) => {
            const y = top + i * rowH
            return (
              <g key={b.key} onMouseEnter={() => setHover(b.key)} onMouseLeave={() => setHover(null)}>
                <text x={pad.l} y={y + 12} fontSize={12} fill={C.ink2} stroke={C.surface} strokeWidth={4} strokeLinejoin="round" paintOrder="stroke">
                  {b.label} <tspan fill={C.muted}>({b.sub})</tspan>
                </text>
                <rect x={x(b.lo)} y={y + 20} width={Math.max(2, x(b.hi) - x(b.lo))} height={24} rx={4} fill={b.fill} />
                <title>{hoverText[b.key]}</title>
              </g>
            )
          })}
          {refs.map((r) => (
            <g key={r.key} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}>
              <line x1={x(r.v)} x2={x(r.v)} y1={top - 6} y2={plotBottom} stroke={r.color} strokeWidth={2} />
              <line x1={x(r.v)} x2={x(r.v)} y1={top - 6} y2={plotBottom} stroke="transparent" strokeWidth={12} />
              <title>{hoverText[r.key]}</title>
            </g>
          ))}
          {bands.map((b, i) => {
            const y = top + i * rowH
            return (
              <g key={`m-${b.key}`}>
                <g onMouseEnter={() => setHover('model')} onMouseLeave={() => setHover(null)}>
                  <circle cx={x(yhat)} cy={y + 32} r={6} fill={C.s1} stroke={C.surface} strokeWidth={2} />
                  <title>{hoverText.model}</title>
                </g>
                {i === 1 && typeof observed === 'number' && (
                  <g onMouseEnter={() => setHover('realized')} onMouseLeave={() => setHover(null)}>
                    <path d={`M${x(observed) - 5},${y + 27} l10,10 m0,-10 l-10,10`} stroke={C.ink} strokeWidth={2.5} strokeLinecap="round" />
                    <title>{hoverText.realized}</title>
                  </g>
                )}
              </g>
            )
          })}
        </svg>
        <p aria-live="polite" className="tabular h-5 text-xs text-ink-2">
          {hover ? hoverText[hover] : 'Hover a band, line or marker for its value.'}
        </p>
      </div>
    </div>
  )
}
