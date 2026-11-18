import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import type { Bin } from '../../lib/stats'
import { fmtInt, fmtPct, fmtSigned } from '../../lib/format'
import { C, TooltipBox } from './ChartFrame'

/** Histogram of lineup ratings. One series: one color. */
export function HistogramChart({ bins, xLabel, mean, meanLabel }: { bins: Bin[]; xLabel: string; mean?: number; meanLabel?: string }) {
  const meanBin = mean === undefined ? undefined : bins.find((b) => mean >= b.x0 && mean < b.x1)
  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ top: 16, right: 8, bottom: 24, left: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" tickLine={false} interval="preserveStartEnd" minTickGap={18} label={{ value: xLabel, position: 'insideBottom', offset: -14 }} />
          <YAxis allowDecimals={false} width={44} />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const b = payload[0].payload as Bin
              return <TooltipBox title={b.label} rows={[{ label: 'Lineups', value: fmtInt(b.count) }]} />
            }}
          />
          {meanBin && (
            <ReferenceLine x={meanBin.label} stroke={C.ink2} strokeWidth={1.5} label={{ value: meanLabel ?? 'mean', position: 'top', fill: 'var(--ink-2)', fontSize: 11 }} />
          )}
          <Bar dataKey="count" fill={C.s1} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export interface FunnelPoint {
  id: number
  label: string
  poss: number
  net: number
}

/**
 * Net rating against possessions (log scale) with the ±1.96·SD band that pure sampling noise would produce
 * around the pooled mean. Small samples fan out; that fan is noise, not talent.
 */
export function FunnelChart({ points, band, yLim }: { points: FunnelPoint[]; band: { poss: number; lo: number; hi: number; mid: number }[]; yLim: number }) {
  const xs = points.map((p) => p.poss)
  const xMin = Math.max(1, Math.min(...xs, band[0]?.poss ?? 25))
  const xMax = Math.max(...xs, band[band.length - 1]?.poss ?? 100)
  const clamp = (v: number) => Math.max(-yLim, Math.min(yLim, v))
  const data = points.map((p) => ({ ...p, y: clamp(p.net), clipped: Math.abs(p.net) > yLim }))
  return (
    <div className="h-[340px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
          <CartesianGrid />
          <XAxis
            type="number"
            dataKey="poss"
            scale="log"
            domain={[xMin, xMax]}
            ticks={[25, 50, 100, 200, 500, 1000, 2000].filter((t) => t >= xMin && t <= xMax)}
            allowDataOverflow
            label={{ value: 'Possessions (log scale)', position: 'insideBottom', offset: -16 }}
          />
          <YAxis type="number" dataKey="y" domain={[-yLim, yLim]} tickFormatter={(v: number) => fmtSigned(v, 0)} width={44} allowDataOverflow />
          <ZAxis range={[18, 18]} />
          <ReferenceLine y={0} stroke={C.axis} />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as (typeof data)[number]
              if (d.label === undefined) return null
              return (
                <TooltipBox
                  title={d.label}
                  rows={[
                    { label: 'Possessions', value: fmtInt(d.poss) },
                    { label: 'Net rating', value: fmtSigned(d.net) + (d.clipped ? ' (off scale)' : '') },
                  ]}
                />
              )
            }}
          />
          <Scatter data={data} dataKey="y" fill={C.s1} fillOpacity={0.45} isAnimationActive={false} />
          <Line data={band} dataKey="hi" type="monotone" stroke={C.s2} strokeWidth={2} dot={false} isAnimationActive={false} activeDot={false} />
          <Line data={band} dataKey="lo" type="monotone" stroke={C.s2} strokeWidth={2} dot={false} isAnimationActive={false} activeDot={false} />
          <Line data={band} dataKey="mid" type="monotone" stroke={C.ink2} strokeWidth={1.5} dot={false} isAnimationActive={false} activeDot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export interface PairPoint {
  id: number
  label: string
  x: number
  y: number
  w: number
}

/** Pre-break vs post-break net rating with the identity line and the fitted (weighted) line. */
export function RegressionChart({ points, fit, lim }: { points: PairPoint[]; fit: { intercept: number; slope: number }; lim: number }) {
  const clamp = (v: number) => Math.max(-lim, Math.min(lim, v))
  const data = points.map((p) => ({ ...p, cx: clamp(p.x), cy: clamp(p.y) }))
  return (
    <div className="h-[340px]">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
          <CartesianGrid />
          <XAxis type="number" dataKey="cx" domain={[-lim, lim]} tickFormatter={(v: number) => fmtSigned(v, 0)} allowDataOverflow label={{ value: 'Pre-break net rating', position: 'insideBottom', offset: -16 }} />
          <YAxis type="number" dataKey="cy" domain={[-lim, lim]} tickFormatter={(v: number) => fmtSigned(v, 0)} width={44} allowDataOverflow label={{ value: 'Post-break', angle: -90, position: 'insideLeft', offset: 10 }} />
          <ZAxis range={[22, 22]} />
          <ReferenceLine segment={[{ x: -lim, y: -lim }, { x: lim, y: lim }]} stroke={C.axis} strokeWidth={1.5} />
          <ReferenceLine
            segment={[
              { x: -lim, y: fit.intercept - fit.slope * lim },
              { x: lim, y: fit.intercept + fit.slope * lim },
            ]}
            stroke={C.s2}
            strokeWidth={2}
            ifOverflow="hidden"
          />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as (typeof data)[number]
              return (
                <TooltipBox
                  title={d.label}
                  rows={[
                    { label: 'Pre-break net', value: fmtSigned(d.x) },
                    { label: 'Post-break net', value: fmtSigned(d.y) },
                    { label: 'Post-break poss', value: fmtInt(d.w) },
                  ]}
                />
              )
            }}
          />
          <Scatter data={data} fill={C.s1} fillOpacity={0.5} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

export interface ReliabilityPoint {
  id: number
  label: string
  poss: number
  reliability: number
  net: number | null
}

/** The API's per-lineup reliability (share of the pre-break rating's variance that is signal) vs sample size. */
export function ReliabilityChart({ points }: { points: ReliabilityPoint[] }) {
  const xs = points.map((p) => p.poss)
  const xMin = Math.max(1, Math.min(...xs))
  const xMax = Math.max(...xs)
  return (
    <div className="h-[320px]">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
          <CartesianGrid />
          <XAxis
            type="number"
            dataKey="poss"
            scale="log"
            domain={[xMin, xMax]}
            ticks={[1, 10, 25, 50, 100, 200, 500, 1000, 2000].filter((t) => t >= xMin && t <= xMax)}
            allowDataOverflow
            label={{ value: 'Pre-break possessions (log scale)', position: 'insideBottom', offset: -16 }}
          />
          <YAxis type="number" dataKey="reliability" domain={[0, 1]} tickFormatter={(v: number) => fmtPct(v)} width={48} />
          <ZAxis range={[26, 26]} />
          <ReferenceLine y={0.5} stroke={C.axis} label={{ value: '50% signal', position: 'insideTopLeft', fill: 'var(--muted)', fontSize: 11 }} />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as ReliabilityPoint
              return (
                <TooltipBox
                  title={d.label}
                  rows={[
                    { label: 'Pre-break poss', value: fmtInt(d.poss) },
                    { label: 'Reliability', value: fmtPct(d.reliability) },
                    { label: 'Pre-break net', value: fmtSigned(d.net) },
                  ]}
                />
              )
            }}
          />
          <Scatter data={points} fill={C.s1} fillOpacity={0.7} stroke={C.surface} strokeWidth={1} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

