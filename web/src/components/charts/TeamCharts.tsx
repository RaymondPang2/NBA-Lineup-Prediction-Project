import { CartesianGrid, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import type { TeamSeason } from '../../api/types'
import { fmtRating, fmtRecord, fmtSigned } from '../../lib/format'
import { C, TooltipBox } from './ChartFrame'

/** Each team's net rating before vs after the break. Points above the diagonal improved. */
export function TeamNetScatter({ teams, selectedTeamId, onSelect }: { teams: TeamSeason[]; selectedTeamId?: number; onSelect?: (id: number) => void }) {
  const data = teams
    .filter((t) => t.pre_break?.net_rating != null && t.post_break?.net_rating != null)
    .map((t) => ({ id: t.team_id, abbr: t.abbreviation, name: t.team_name, x: t.pre_break!.net_rating as number, y: t.post_break!.net_rating as number, t }))
  const lim = Math.ceil(Math.max(5, ...data.flatMap((d) => [Math.abs(d.x), Math.abs(d.y)])) / 5) * 5
  const ticks = Array.from({ length: (2 * lim) / 5 + 1 }, (_, i) => -lim + i * 5)
  const selected = data.filter((d) => d.id === selectedTeamId)
  const rest = data.filter((d) => d.id !== selectedTeamId)
  return (
    <div className="h-[340px] sm:h-[380px]">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
          <CartesianGrid />
          <XAxis
            type="number"
            dataKey="x"
            domain={[-lim, lim]}
            ticks={ticks}
            tickFormatter={(v: number) => fmtSigned(v, 0)}
            label={{ value: 'Pre-break net rating', position: 'insideBottom', offset: -16 }}
          />
          <YAxis type="number" dataKey="y" domain={[-lim, lim]} ticks={ticks} tickFormatter={(v: number) => fmtSigned(v, 0)} width={44} label={{ value: 'Post-break net rating', angle: -90, position: 'insideLeft', offset: 10, style: { textAnchor: 'middle' } }} />
          <ZAxis range={[70, 70]} />
          <ReferenceLine segment={[{ x: -lim, y: -lim }, { x: lim, y: lim }]} stroke={C.axis} strokeWidth={1.5} ifOverflow="hidden" />
          <ReferenceLine x={0} stroke={C.axis} />
          <ReferenceLine y={0} stroke={C.axis} />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as (typeof data)[number]
              return (
                <TooltipBox
                  title={d.name}
                  rows={[
                    { label: 'Pre-break net', value: fmtSigned(d.x) },
                    { label: 'Post-break net', value: fmtSigned(d.y) },
                    { label: 'Change', value: fmtSigned(d.y - d.x) },
                    { label: 'Record pre / post', value: `${fmtRecord(d.t.pre_break?.wins, d.t.pre_break?.losses)} / ${fmtRecord(d.t.post_break?.wins, d.t.post_break?.losses)}` },
                  ]}
                />
              )
            }}
          />
          <Scatter
            data={rest}
            fill={C.s1}
            fillOpacity={selectedTeamId ? 0.35 : 0.85}
            stroke={C.surface}
            strokeWidth={1.5}
            isAnimationActive={false}
            onClick={(d: { payload?: { id: number } }) => d?.payload && onSelect?.(d.payload.id)}
            className={onSelect ? 'cursor-pointer' : undefined}
          />
          {selected.length > 0 && (
            <Scatter data={selected} fill={C.s2} stroke={C.surface} strokeWidth={2} isAnimationActive={false}>
              <LabelList dataKey="abbr" position="top" offset={10} style={{ fill: 'var(--ink)', fontSize: 12, fontWeight: 600 }} />
            </Scatter>
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

export interface HistoryPoint {
  season: string
  pre: number | null
  post: number | null
}

/** Two series over seasons (pre- and post-break), on one axis. */
export function SeasonHistoryChart({ data, metric, signed = true }: { data: HistoryPoint[]; metric: string; signed?: boolean }) {
  const fmt = signed ? fmtSigned : fmtRating
  const last = data[data.length - 1]
  // Keep the two end labels apart: the higher series' label sits above its point, the lower one's below.
  const preAbove = (last?.pre ?? 0) >= (last?.post ?? 0)
  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 44, bottom: 4, left: 12 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="season" tickLine={false} interval="preserveStartEnd" />
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => fmt(v, 0)}
            width={56}
            label={{ value: signed ? 'Net rating (pts / 100 poss.)' : 'ORtg (pts / 100 poss.)', angle: -90, position: 'insideLeft', offset: 0, fontSize: 11, style: { textAnchor: 'middle' } }}
          />
          {signed && <ReferenceLine y={0} stroke={C.axis} />}
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as HistoryPoint
              return (
                <TooltipBox
                  title={`${label} · ${metric}`}
                  rows={[
                    { label: 'Pre-break', value: fmt(d.pre), color: C.s1 },
                    { label: 'Post-break', value: fmt(d.post), color: C.s2 },
                  ]}
                />
              )
            }}
          />
          <Line type="linear" dataKey="pre" name="Pre-break" stroke={C.s1} strokeWidth={2} dot={{ r: 4, fill: C.s1, stroke: C.surface, strokeWidth: 2 }} isAnimationActive={false} connectNulls>
            {last && <LabelList dataKey="pre" content={EndLabel(data.length - 1, 'Pre', preAbove ? -4 : 12)} />}
          </Line>
          <Line type="linear" dataKey="post" name="Post-break" stroke={C.s2} strokeWidth={2} dot={{ r: 4, fill: C.s2, stroke: C.surface, strokeWidth: 2 }} isAnimationActive={false} connectNulls>
            {last && <LabelList dataKey="post" content={EndLabel(data.length - 1, 'Post', preAbove ? 12 : -4)} />}
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Direct label at a line's last point (identity is never carried by color alone). */
function EndLabel(lastIndex: number, text: string, dy: number) {
  return (props: { x?: number | string; y?: number | string; index?: number }) => {
    if (props.index !== lastIndex || props.x === undefined || props.y === undefined) return null
    return (
      <text x={Number(props.x) + 9} y={Number(props.y)} dy={dy} fontSize={12} fill="var(--ink-2)">
        {text}
      </text>
    )
  }
}
