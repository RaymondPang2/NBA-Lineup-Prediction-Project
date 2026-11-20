import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useLineups, useTeamStats } from '../api/hooks'
import { useHistory } from '../api/useHistory'
import type { TeamSeason } from '../api/types'
import { ChartFrame } from '../components/charts/ChartFrame'
import { SeasonHistoryChart, TeamNetScatter } from '../components/charts/TeamCharts'
import { SeasonSelect, TeamSelect } from '../components/filters/Filters'
import { TeamLogo } from '../components/ui/TeamLogo'
import { LineupTable } from '../components/LineupTable'
import { Badge, Card, CardBody, CardHeader, Delta, FilterBar, PageHeader, Stat } from '../components/ui/Card'
import { EmptyState, ErrorState, LoadingBlock, QueryState, Skeleton } from '../components/ui/States'
import { SortTh, TableWrap, Td, Th, type SortOrder } from '../components/ui/Table'
import { fmtDate, fmtInt, fmtRating, fmtRecord, fmtSigned } from '../lib/format'
import { pooledRatings } from '../lib/stats'
import { useSeasonParam, useUrlState } from '../lib/urlState'

type TeamSortKey = 'team' | 'pre_net' | 'pre_off' | 'pre_def' | 'post_net' | 'change' | 'pre_win'

const teamSortValue: Record<TeamSortKey, (t: TeamSeason) => number | string> = {
  team: (t) => t.team_name,
  pre_net: (t) => t.pre_break.net_rating ?? -Infinity,
  pre_off: (t) => t.pre_break.off_rating ?? -Infinity,
  pre_def: (t) => t.pre_break.def_rating ?? Infinity,
  post_net: (t) => t.post_break.net_rating ?? -Infinity,
  change: (t) => t.change?.net_rating ?? -Infinity,
  pre_win: (t) => (t.pre_break.games ? (t.pre_break.wins ?? 0) / t.pre_break.games : 0),
}

function TeamTable({ teams, selected, onSelect }: { teams: TeamSeason[]; selected?: number; onSelect: (id: number) => void }) {
  const [sort, setSort] = useState<TeamSortKey>('pre_net')
  const [order, setOrder] = useState<SortOrder>('desc')
  const rows = useMemo(() => {
    const f = teamSortValue[sort]
    return [...teams].sort((a, b) => {
      const va = f(a)
      const vb = f(b)
      const c = typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)
      return order === 'asc' ? c : -c
    })
  }, [teams, sort, order])
  const onSort = (k: TeamSortKey, o: SortOrder) => {
    setSort(k)
    setOrder(o)
  }
  const th = (k: TeamSortKey, label: string, title?: string, defaultOrder: SortOrder = 'desc') => (
    <SortTh label={label} sortKey={k} sort={sort} order={order} onSort={onSort} title={title} defaultOrder={defaultOrder} />
  )
  return (
    <TableWrap label="Team ratings">
      <thead>
        <tr>
          <SortTh label="Team" sortKey="team" sort={sort} order={order} onSort={onSort} align="left" defaultOrder="asc" />
          {th('pre_win', 'Pre W–L')}
          {th('pre_off', 'Pre ORtg')}
          {th('pre_def', 'Pre DRtg', 'Lower is better', 'asc')}
          {th('pre_net', 'Pre net')}
          <Th>Post W–L</Th>
          {th('post_net', 'Post net')}
          {th('change', 'Δ Net')}
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.team_id} className={t.team_id === selected ? 'bg-accent-soft' : 'hover:bg-surface-2'}>
            <Td align="left">
              <button type="button" onClick={() => onSelect(t.team_id)} className="text-left font-medium text-ink hover:text-accent">
                <span className="inline-flex items-center gap-2">
                  <TeamLogo teamId={t.team_id} abbreviation={t.abbreviation} size="xs" whenUnavailable="hide" decorative />
                  <span className="inline-block w-9 text-xs text-muted">{t.abbreviation}</span>
                </span>
                {t.team_name}
              </button>
            </Td>
            <Td>{fmtRecord(t.pre_break.wins, t.pre_break.losses)}</Td>
            <Td>{fmtRating(t.pre_break.off_rating)}</Td>
            <Td>{fmtRating(t.pre_break.def_rating)}</Td>
            <Td className="font-medium text-ink">{fmtSigned(t.pre_break.net_rating)}</Td>
            <Td>{fmtRecord(t.post_break.wins, t.post_break.losses)}</Td>
            <Td className="font-medium text-ink">{fmtSigned(t.post_break.net_rating)}</Td>
            <Td>
              <Delta value={t.change?.net_rating} format={fmtSigned} />
            </Td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

export default function OverviewPage() {
  const { set, getNum } = useUrlState()
  const { season, seasons, seasonInfo, query: seasonsQuery } = useSeasonParam()
  const teamId = getNum('team')
  const stats = useTeamStats(season)
  const history = useHistory(
    seasons.map((s) => s.season_id),
    teamId,
  )
  const team = stats.data?.find((t) => t.team_id === teamId)
  const topLineups = useLineups({ season, team_id: teamId, sort: 'pre_poss', order: 'desc', page_size: 10 }, !!season && !!teamId)

  const league = useMemo(() => {
    if (!stats.data) return null
    const pick = (w: 'pre_break' | 'post_break') =>
      pooledRatings(stats.data.map((t) => ({ pts: t[w].pts, poss: t[w].poss, opp_pts: t[w].opp_pts, opp_poss: t[w].opp_poss })))
    return { pre: pick('pre_break'), post: pick('post_break'), poss: stats.data.reduce((a, t) => a + t.pre_break.poss + t.post_break.poss, 0) }
  }, [stats.data])

  if (seasonsQuery.error) return <ErrorState error={seasonsQuery.error} onRetry={() => seasonsQuery.refetch()} />

  const pre = seasonInfo?.windows.find((w) => w.window_type === 'pre_asb')
  const post = seasonInfo?.windows.find((w) => w.window_type === 'post_asb')

  return (
    <div>
      <PageHeader
        title={team ? `${team.team_name} · ${season}` : `League overview · ${season ?? ''}`}
        leading={team ? <TeamLogo teamId={team.team_id} abbreviation={team.abbreviation} size="lg" decorative /> : undefined}
        description="Five-man lineup performance split at the All-Star break. Every rating is points per 100 possessions, computed from summed totals across lineups."
      >
        {seasonInfo && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <Badge tone={seasonInfo.role === 'held_out' ? 'accent' : 'neutral'}>{seasonInfo.role === 'held_out' ? 'Held-out season' : 'Development season'}</Badge>
            {seasonInfo.is_irregular && <Badge tone="warn">Irregular season</Badge>}
            {pre && post && (
              <span>
                Pre-break {fmtDate(pre.date_from)} – {fmtDate(pre.date_to)} · Post-break {fmtDate(post.date_from)} – {fmtDate(post.date_to)}
              </span>
            )}
          </div>
        )}
      </PageHeader>

      <FilterBar>
        <SeasonSelect seasons={seasons} value={season} onChange={(v) => set({ season: v })} />
        <TeamSelect season={season} value={teamId} onChange={(v) => set({ team: v })} />
      </FilterBar>

      {stats.error ? (
        <ErrorState error={stats.error} onRetry={() => stats.refetch()} />
      ) : !stats.data || !seasonInfo ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : team ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="kpis">
          <Stat label="Pre-break net" value={fmtSigned(team.pre_break.net_rating)} detail={`${fmtRecord(team.pre_break.wins, team.pre_break.losses)} · ORtg ${fmtRating(team.pre_break.off_rating)} · DRtg ${fmtRating(team.pre_break.def_rating)}`} />
          <Stat label="Post-break net" value={fmtSigned(team.post_break.net_rating)} detail={`${fmtRecord(team.post_break.wins, team.post_break.losses)} · ORtg ${fmtRating(team.post_break.off_rating)} · DRtg ${fmtRating(team.post_break.def_rating)}`} />
          <Stat label="Change in net" value={<Delta value={team.change?.net_rating} format={fmtSigned} />} detail="Post-break minus pre-break" />
          <Stat label="Lineups used" value={fmtInt((team.pre_break.n_lineups ?? 0) + (team.post_break.n_lineups ?? 0))} detail={`${fmtInt(team.pre_break.n_lineups)} pre · ${fmtInt(team.post_break.n_lineups)} post`} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="kpis">
          <Stat label="Lineups recorded" value={fmtInt(seasonInfo.n_lineups)} detail={`${stats.data.length} teams`} />
          <Stat label="Possessions" value={fmtInt(league?.poss)} detail="Lineup possessions, both windows" />
          <Stat label="League ORtg, pre-break" value={fmtRating(league?.pre?.off)} detail="Σ points / Σ possessions × 100" />
          <Stat label="League ORtg, post-break" value={fmtRating(league?.post?.off)} detail={<Delta value={(league?.post?.off ?? NaN) - (league?.pre?.off ?? NaN)} goodWhen="none" format={fmtSigned} />} />
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-5">
        <ChartFrame
          className="xl:col-span-2"
          title="Team net rating, before vs after the break"
          subtitle="Each dot is a team. Above the diagonal: better after the break. Click a dot to select the team."
          table={
            stats.data && (
              <TableWrap label="Team net ratings">
                <thead>
                  <tr>
                    <Th align="left">Team</Th>
                    <Th>Pre net</Th>
                    <Th>Post net</Th>
                  </tr>
                </thead>
                <tbody>
                  {stats.data.map((t) => (
                    <tr key={t.team_id}>
                      <Td align="left">{t.abbreviation}</Td>
                      <Td>{fmtSigned(t.pre_break.net_rating)}</Td>
                      <Td>{fmtSigned(t.post_break.net_rating)}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )
          }
        >
          <QueryState query={stats} loading={<LoadingBlock height="h-[340px]" />}>
            {(teams) => <TeamNetScatter teams={teams} selectedTeamId={teamId} onSelect={(id) => set({ team: id })} />}
          </QueryState>
        </ChartFrame>

        <ChartFrame
          className="xl:col-span-3"
          title={team ? `${team.abbreviation} net rating by season` : 'League offensive rating by season'}
          subtitle={
            team
              ? 'Pre- and post-break net rating, every season in the warehouse.'
              : 'Scoring level before and after the break. League net rating is zero by construction, so offense is the informative series.'
          }
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
                      <Td>{team ? fmtSigned(h.pre) : fmtRating(h.pre)}</Td>
                      <Td>{team ? fmtSigned(h.post) : fmtRating(h.post)}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )
          }
          footer={team ? 'A team missing from a season shows a gap.' : 'Seasons 2019-20 and 2020-21 were irregular (bubble; shortened schedule).'}
        >
          {history.error ? (
            <ErrorState error={history.error} onRetry={history.refetch} />
          ) : !history.data ? (
            <LoadingBlock height="h-[300px]" />
          ) : (
            <SeasonHistoryChart data={history.data} metric={team ? 'Net rating' : 'ORtg'} signed={!!team} />
          )}
        </ChartFrame>
      </div>

      {team && (
        <Card className="mt-6">
          <CardHeader
            title="Most-used lineups"
            subtitle="By pre-break possessions"
            actions={
              <Link to={`/lineups?season=${season}&team=${team.team_id}`} className="text-sm font-medium text-accent hover:underline">
                Explore all {team.abbreviation} lineups ›
              </Link>
            }
          />
          <CardBody>
            <QueryState query={topLineups} loading={<LoadingBlock height="h-48" />}>
              {(page) => (page.items.length ? <LineupTable items={page.items} showTeam={false} compact /> : <EmptyState title="No lineups recorded" />)}
            </QueryState>
          </CardBody>
        </Card>
      )}

      <Card className="mt-6">
        <CardHeader title="Team ratings" subtitle="Sort by any column. Click a team to focus the page on it." />
        <CardBody>
          <QueryState query={stats} loading={<LoadingBlock height="h-96" />}>
            {(teams) => <TeamTable teams={teams} selected={teamId} onSelect={(id) => set({ team: id })} />}
          </QueryState>
        </CardBody>
      </Card>
    </div>
  )
}
