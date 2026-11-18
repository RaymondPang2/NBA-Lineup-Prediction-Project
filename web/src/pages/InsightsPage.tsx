import { useMemo, useState } from 'react'
import { useAllLineups, useTeamPredictions, useTeams } from '../api/hooks'
import type { LineupSummary } from '../api/types'
import { useHistory } from '../api/useHistory'
import { ChartFrame } from '../components/charts/ChartFrame'
import { FunnelChart, HistogramChart, RegressionChart, ReliabilityChart } from '../components/charts/LineupCharts'
import { SeasonHistoryChart } from '../components/charts/TeamCharts'
import { SeasonSelect, TeamSelect } from '../components/filters/Filters'
import { Callout, FilterBar, PageHeader } from '../components/ui/Card'
import { PossessionSelect, Segmented } from '../components/ui/Controls'
import { EmptyState, ErrorState, LoadingBlock } from '../components/ui/States'
import { TableWrap, Td, Th } from '../components/ui/Table'
import { fmtInt, fmtNum, fmtPct, fmtRating, fmtSigned, lineupLabel } from '../lib/format'
import { histogram, logSpace, quantile, samplingK, samplingSd, weightedMean, weightedSd, wlsLine } from '../lib/stats'
import { useSeasonParam, useUrlState } from '../lib/urlState'

type Metric = 'net' | 'off' | 'def'
type Win = 'pre' | 'post'
const Z = 1.959964
const METRIC: Record<Metric, { label: string; field: 'net_rating' | 'off_rating' | 'def_rating' }> = {
  net: { label: 'Net rating', field: 'net_rating' },
  off: { label: 'Offensive rating', field: 'off_rating' },
  def: { label: 'Defensive rating', field: 'def_rating' },
}

function windowStats(l: LineupSummary, w: Win) {
  return w === 'pre' ? l.pre_break : l.post_break
}

function DistributionPanel({ season, teamId, threshold }: { season: string; teamId?: number; threshold: number }) {
  const [metric, setMetric] = useState<Metric>('net')
  const [win, setWin] = useState<Win>('pre')
  const q = useAllLineups(win === 'pre' ? { season, team_id: teamId, min_pre_poss: threshold } : { season, team_id: teamId, min_post_poss: threshold })
  const summary = useMemo(() => {
    if (!q.data) return null
    const rows = q.data.items.map((l) => windowStats(l, win)).filter((s): s is NonNullable<typeof s> => !!s && s[METRIC[metric].field] !== null)
    const values = rows.map((s) => s[METRIC[metric].field] as number)
    const weights = rows.map((s) => s.poss)
    const center = metric === 'net' ? 0 : 110
    const width = metric === 'net' ? 5 : 4
    const half = metric === 'net' ? 60 : 32
    return {
      n: values.length,
      bins: histogram(values, width, center - half, center + half),
      mean: weightedMean(values, weights),
      sd: weightedSd(values, weights),
      p05: quantile(values, 0.05),
      p95: quantile(values, 0.95),
    }
  }, [q.data, metric, win])
  const fmt = metric === 'net' ? fmtSigned : fmtRating

  return (
    <ChartFrame
      title="Rating distribution"
      subtitle={`Lineups with ≥ ${threshold} ${win === 'pre' ? 'pre' : 'post'}-break possessions per end. The line marks the possession-weighted mean.`}
      actions={
        <>
          <Segmented size="sm" label="Metric" value={metric} onChange={setMetric} options={[{ value: 'net', label: 'Net' }, { value: 'off', label: 'ORtg' }, { value: 'def', label: 'DRtg' }]} />
          <Segmented size="sm" label="Window" value={win} onChange={setWin} options={[{ value: 'pre', label: 'Pre' }, { value: 'post', label: 'Post' }]} />
        </>
      }
      table={
        summary && (
          <TableWrap label="Histogram bins">
            <thead>
              <tr>
                <Th align="left">{METRIC[metric].label}</Th>
                <Th>Lineups</Th>
              </tr>
            </thead>
            <tbody>
              {summary.bins.map((b) => (
                <tr key={b.label}>
                  <Td align="left">{b.label}</Td>
                  <Td>{fmtInt(b.count)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )
      }
      footer={q.data?.truncated ? 'Showing the first 5,000 lineups; raise the threshold or pick a team for the full set.' : 'Edge bins collect everything beyond the axis range.'}
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !summary ? (
        <LoadingBlock height="h-[300px]" label="Loading lineups" />
      ) : summary.n === 0 ? (
        <EmptyState title="No lineups at this threshold">Lower the possession threshold.</EmptyState>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniStat label="Lineups" value={fmtInt(summary.n)} />
            <MiniStat label="Weighted mean" value={fmt(summary.mean)} />
            <MiniStat label="Weighted SD" value={fmtNum(summary.sd, 1)} />
            <MiniStat label="5th–95th pct." value={`${fmt(summary.p05, 0)} to ${fmt(summary.p95, 0)}`} />
          </div>
          <HistogramChart bins={summary.bins} xLabel={`${METRIC[metric].label}, ${win === 'pre' ? 'pre' : 'post'}-break`} mean={summary.mean} meanLabel="mean" />
        </>
      )}
    </ChartFrame>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2">
      <p className="text-[11px] font-medium tracking-wide text-muted uppercase">{label}</p>
      <p className="tabular text-sm font-semibold text-ink">{value}</p>
    </div>
  )
}

function NoisePanels({ season, teamId, threshold }: { season: string; teamId?: number; threshold: number }) {
  const q = useAllLineups({ season, team_id: teamId, min_pre_poss: threshold })
  const funnel = useMemo(() => {
    if (!q.data) return null
    const rows = q.data.items.filter((l) => l.pre_break && l.pre_break.net_rating !== null)
    if (rows.length < 3) return { empty: true as const }
    const pts = rows.map((l) => ({ id: l.lineup_id, label: lineupLabel(l.players), poss: l.pre_break!.poss, net: l.pre_break!.net_rating as number }))
    const k = samplingK(rows.map((l) => ({ sd: l.pre_break!.net_rating_sampling_sd, poss: l.pre_break!.poss, opp_poss: l.pre_break!.opp_poss })))
    const mu = weightedMean(
      pts.map((p) => p.net),
      pts.map((p) => p.poss),
    )
    const xs = pts.map((p) => p.poss)
    const band = logSpace(Math.min(...xs), Math.max(...xs), 40).map((n) => ({ poss: n, mid: mu, lo: mu - Z * samplingSd(k, n), hi: mu + Z * samplingSd(k, n) }))
    const inside = rows.filter((l) => Math.abs((l.pre_break!.net_rating as number) - mu) <= Z * (l.pre_break!.net_rating_sampling_sd ?? Infinity)).length
    const yLim = Math.max(30, Math.ceil(quantile(pts.map((p) => Math.abs(p.net)), 0.98) / 10) * 10)
    return { empty: false as const, pts, band, k, mu, share: inside / rows.length, yLim }
  }, [q.data])

  const pairs = useMemo(() => {
    if (!q.data) return null
    const rows = q.data.items.filter(
      (l) => l.pre_break?.net_rating !== null && l.pre_break?.net_rating !== undefined && l.post_break && l.post_break.net_rating !== null && l.post_break.poss >= 25 && (l.post_break.opp_poss ?? 0) >= 25,
    )
    if (rows.length < 5) return { empty: true as const, n: rows.length }
    const pts = rows.map((l) => ({ id: l.lineup_id, label: lineupLabel(l.players), x: l.pre_break!.net_rating as number, y: l.post_break!.net_rating as number, w: l.post_break!.poss }))
    const fit = wlsLine(
      pts.map((p) => p.x),
      pts.map((p) => p.y),
      pts.map((p) => p.w),
    )
    const lim = Math.max(30, Math.ceil(quantile(pts.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)]), 0.98) / 10) * 10)
    return { empty: false as const, pts, fit, lim }
  }, [q.data])

  const loading = <LoadingBlock height="h-[340px]" label="Loading lineups" />
  return (
    <>
      <ChartFrame
        title="Reliability funnel: how noise shrinks with possessions"
        subtitle="Each dot is a lineup’s pre-break net rating. The orange curves are ±1.96 SD of pure sampling noise around the weighted mean (center line)."
        legend={[
          { label: 'Lineup', color: 'var(--series-1)' },
          { label: '95% noise band', color: 'var(--series-2)', shape: 'line' },
          { label: 'Weighted mean', color: 'var(--ink-2)', shape: 'line' },
        ]}
        table={
          funnel && !funnel.empty && (
            <TableWrap label="Noise band">
              <thead>
                <tr>
                  <Th align="left">Possessions</Th>
                  <Th>Noise SD</Th>
                  <Th>95% band</Th>
                </tr>
              </thead>
              <tbody>
                {[25, 50, 100, 200, 400, 800, 1600].map((n) => (
                  <tr key={n}>
                    <Td align="left">{n}</Td>
                    <Td>{fmtNum(samplingSd(funnel.k, n), 1)}</Td>
                    <Td>±{fmtNum(Z * samplingSd(funnel.k, n), 1)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )
        }
        footer={
          funnel && !funnel.empty
            ? `K = ${fmtInt(funnel.k)}, recovered from the API’s per-lineup sampling SDs (SD = √(K·(1/poss + 1/opp_poss))). Points beyond ±${funnel.yLim} are drawn at the edge.`
            : undefined
        }
      >
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !funnel ? (
          loading
        ) : funnel.empty ? (
          <EmptyState title="Too few lineups">Lower the threshold or choose all teams.</EmptyState>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              <MiniStat label="Lineups" value={fmtInt(funnel.pts.length)} />
              <MiniStat label="Inside the noise band" value={fmtPct(funnel.share)} />
              <MiniStat label="Noise SD at 100 poss." value={`±${fmtNum(samplingSd(funnel.k, 100), 1)}`} />
            </div>
            <FunnelChart points={funnel.pts} band={funnel.band} yLim={funnel.yLim} />
          </>
        )}
      </ChartFrame>

      <ChartFrame
        title="Regression to the mean"
        subtitle="Lineups that played on both sides of the break (≥ 25 post-break possessions per end). The gray diagonal is “no change”; the orange line is the possession-weighted fit."
        legend={[
          { label: 'Lineup', color: 'var(--series-1)' },
          { label: 'Weighted fit', color: 'var(--series-2)', shape: 'line' },
          { label: 'No change (y = x)', color: 'var(--axis)', shape: 'line' },
        ]}
        table={
          pairs && !pairs.empty && (
            <TableWrap label="Pre vs post">
              <thead>
                <tr>
                  <Th align="left">Lineup</Th>
                  <Th>Pre net</Th>
                  <Th>Post net</Th>
                  <Th>Post poss</Th>
                </tr>
              </thead>
              <tbody>
                {pairs.pts.slice(0, 300).map((p) => (
                  <tr key={p.id}>
                    <Td align="left">{p.label}</Td>
                    <Td>{fmtSigned(p.x)}</Td>
                    <Td>{fmtSigned(p.y)}</Td>
                    <Td>{fmtInt(p.w)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )
        }
        footer={
          pairs && !pairs.empty
            ? `Slope ${fmtNum(pairs.fit.slope, 2)}: a lineup ${10} points above average before the break was, on average, about ${fmtNum(pairs.fit.slope * 10, 1)} above after it. A slope below 1 is regression to the mean; it is why the model shrinks lineup history.`
            : undefined
        }
      >
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !pairs ? (
          loading
        ) : pairs.empty ? (
          <EmptyState title="Too few lineups played on both sides of the break">
            {pairs.n} qualify. Lower the pre-break threshold or choose all teams.
          </EmptyState>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              <MiniStat label="Lineups" value={fmtInt(pairs.pts.length)} />
              <MiniStat label="Fitted slope" value={fmtNum(pairs.fit.slope, 2)} />
              <MiniStat label="Fit weights" value="Post-break poss." />
            </div>
            <RegressionChart points={pairs.pts} fit={pairs.fit} lim={pairs.lim} />
          </>
        )}
      </ChartFrame>
    </>
  )
}

function ReliabilityPanel({ season, teamId, threshold }: { season: string; teamId?: number; threshold: number }) {
  const teams = useTeams(season)
  const [localTeam, setLocalTeam] = useState<number | undefined>(undefined)
  // Default to the first team alphabetically so the panel opens with data; the picker changes it.
  const firstTeam = teams.data ? [...teams.data].sort((a, b) => a.team_name.localeCompare(b.team_name))[0]?.team_id : undefined
  const team = teamId ?? localTeam ?? firstTeam
  const q = useTeamPredictions(team, season, threshold)
  const points = useMemo(
    () =>
      q.data?.items
        .filter((p) => p.lineup_id !== null && p.pre_break.poss > 0)
        .map((p) => ({ id: p.lineup_id as number, label: lineupLabel(p.players), poss: p.pre_break.poss, reliability: p.pre_break.reliability, net: p.pre_break.net_rating })) ?? [],
    [q.data],
  )
  const teamName = teams.data?.find((t) => t.team_id === team)?.team_name
  return (
    <ChartFrame
      title="Lineup reliability"
      subtitle="From the model API: the share of each lineup’s pre-break net rating that is signal rather than sampling noise."
      actions={teamId === undefined && <TeamSelect season={season} value={team} onChange={setLocalTeam} allowAll={false} label="Team" />}
      table={
        points.length > 0 && (
          <TableWrap label="Reliability">
            <thead>
              <tr>
                <Th align="left">Lineup</Th>
                <Th>Pre poss</Th>
                <Th>Reliability</Th>
              </tr>
            </thead>
            <tbody>
              {[...points]
                .sort((a, b) => b.poss - a.poss)
                .map((p) => (
                  <tr key={p.id}>
                    <Td align="left">{p.label}</Td>
                    <Td>{fmtInt(p.poss)}</Td>
                    <Td>{fmtPct(p.reliability)}</Td>
                  </tr>
                ))}
            </tbody>
          </TableWrap>
        )
      }
      footer={team ? `${teamName ?? ''}, lineups with ≥ ${threshold} pre-break possessions per end.` : undefined}
    >
      {team === undefined ? (
        <EmptyState title="Choose a team">Reliability comes from the model API one team at a time. Pick a team above.</EmptyState>
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data ? (
        <LoadingBlock height="h-[320px]" label="Loading reliability" />
      ) : points.length === 0 ? (
        <EmptyState title="No lineups at this threshold" />
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MiniStat label="Lineups" value={fmtInt(points.length)} />
            <MiniStat label="Median reliability" value={fmtPct(quantile(points.map((p) => p.reliability), 0.5))} />
            <MiniStat label="Above 50%" value={fmtInt(points.filter((p) => p.reliability >= 0.5).length)} />
          </div>
          <ReliabilityChart points={points} />
        </>
      )}
    </ChartFrame>
  )
}

export default function InsightsPage() {
  const { set, getNum } = useUrlState()
  const { season, seasons } = useSeasonParam()
  const teamId = getNum('team')
  const threshold = [25, 50, 100, 200].includes(getNum('min_poss', 25)!) ? getNum('min_poss', 25)! : 25
  const history = useHistory(
    seasons.map((s) => s.season_id),
    teamId,
  )

  return (
    <div>
      <PageHeader
        title="Insights"
        description="How lineup ratings are distributed, how much of them is noise, and how teams have trended. Small samples make lineup ratings look far more extreme than lineups really are."
      />
      <FilterBar>
        <SeasonSelect seasons={seasons} value={season} onChange={(v) => set({ season: v })} />
        <TeamSelect season={season} value={teamId} onChange={(v) => set({ team: v })} />
        <PossessionSelect label="Min possessions" value={threshold} onChange={(v) => set({ min_poss: v === 25 ? undefined : v })} presets={[25, 50, 100, 200]} />
      </FilterBar>

      {!season ? (
        <LoadingBlock />
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          <DistributionPanel season={season} teamId={teamId} threshold={threshold} />
          <ReliabilityPanel season={season} teamId={teamId} threshold={threshold} />
          <NoisePanels season={season} teamId={teamId} threshold={threshold} />
          <ChartFrame
            className="xl:col-span-2"
            title={teamId ? 'Historical performance: net rating by season' : 'Historical performance: league offensive rating by season'}
            subtitle="Pre- and post-break, every season in the warehouse (2018-19 to 2025-26)."
            legend={[
              { label: 'Pre-break', color: 'var(--series-1)', shape: 'line' },
              { label: 'Post-break', color: 'var(--series-2)', shape: 'line' },
            ]}
            table={
              history.data && (
                <TableWrap label="History">
                  <thead>
                    <tr>
                      <Th align="left">Season</Th>
                      <Th>Pre-break</Th>
                      <Th>Post-break</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.data.map((h) => (
                      <tr key={h.season}>
                        <Td align="left">{h.season}</Td>
                        <Td>{teamId ? fmtSigned(h.pre) : fmtRating(h.pre)}</Td>
                        <Td>{teamId ? fmtSigned(h.post) : fmtRating(h.post)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </TableWrap>
              )
            }
          >
            {history.error ? (
              <ErrorState error={history.error} onRetry={history.refetch} />
            ) : !history.data ? (
              <LoadingBlock height="h-[300px]" />
            ) : (
              <SeasonHistoryChart data={history.data} metric={teamId ? 'Net rating' : 'ORtg'} signed={!!teamId} />
            )}
          </ChartFrame>
        </div>
      )}

      <div className="mt-6">
        <Callout title="Reading these charts">
          A lineup’s rating after a few dozen possessions is mostly noise: the funnel’s fan at small samples is what pure chance produces. That is why the project’s reliability analysis
          shrinks lineup ratings toward their team, and why the prediction model leans on team and player information instead of a lineup’s own record.
        </Callout>
      </div>
    </div>
  )
}
