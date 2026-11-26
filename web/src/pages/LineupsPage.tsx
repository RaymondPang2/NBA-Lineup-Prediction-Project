import { useLineups } from '../api/hooks'
import type { LineupSort } from '../api/types'
import { PlayerPicker, SeasonSelect, TeamSelect } from '../components/filters/Filters'
import { LineupTable } from '../components/LineupTable'
import { Card, CardBody, FilterBar, PageHeader } from '../components/ui/Card'
import { Button, PossessionSelect } from '../components/ui/Controls'
import { InfoTip } from '../components/ui/InfoTip'
import { EmptyState, ErrorState, LoadingBlock, Spinner } from '../components/ui/States'
import { Pagination, type SortOrder } from '../components/ui/Table'
import { useSeasonParam, useUrlState } from '../lib/urlState'

const SORTS: LineupSort[] = ['pre_poss', 'post_poss', 'pre_net', 'post_net', 'net_change', 'pre_off', 'pre_def', 'post_off', 'post_def', 'lineup_id']

export default function LineupsPage() {
  const { set, getNum, getAll, get } = useUrlState()
  const { season, seasons } = useSeasonParam()
  const teamId = getNum('team')
  const players = getAll('player').map(Number).filter(Number.isFinite).slice(0, 5)
  const minPre = getNum('min_pre', 25)!
  const minPost = getNum('min_post', 0)!
  const sortParam = get('sort') as LineupSort | undefined
  const sort: LineupSort = sortParam && SORTS.includes(sortParam) ? sortParam : 'pre_poss'
  const order: SortOrder = get('order') === 'asc' ? 'asc' : 'desc'
  const page = Math.max(1, getNum('page', 1)!)
  const pageSize = [25, 50, 100, 200].includes(getNum('size', 50)!) ? getNum('size', 50)! : 50

  const query = useLineups(
    { season, team_id: teamId, player_id: players, min_pre_poss: minPre, min_post_poss: minPost, sort, order, page, page_size: pageSize },
    !!season,
  )
  const filtersActive = teamId !== undefined || players.length > 0 || minPre !== 25 || minPost !== 0

  return (
    <div>
      <PageHeader
        title="Lineup explorer"
        description={
          <>
            Every five-man unit, with ratings before and after the All-Star break. Thresholds apply to <em>both</em> ends (own and opponent possessions). Small samples are
            noisy: at 25 possessions a net rating’s sampling SD is about ±34 points; the ✱ marks changes larger than that noise.
          </>
        }
      />

      <FilterBar>
        <SeasonSelect seasons={seasons} value={season} onChange={(v) => set({ season: v, page: undefined, player: [] })} />
        <TeamSelect season={season} value={teamId} onChange={(v) => set({ team: v, page: undefined })} />
        <PossessionSelect label="Min pre-break poss." value={minPre} onChange={(v) => set({ min_pre: v === 25 ? undefined : v, page: undefined })} />
        <PossessionSelect label="Min post-break poss." value={minPost} onChange={(v) => set({ min_post: v || undefined, page: undefined })} />
        <PlayerPicker season={season} teamId={teamId} selected={players} onChange={(ids) => set({ player: ids, page: undefined })} label="Lineups with players" />
      </FilterBar>

      <Card>
        <CardBody className="pt-4">
          <div className="mb-3 flex min-h-8 flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-2" aria-live="polite">
              {query.data ? (
                <>
                  <span className="font-semibold text-ink">{query.data.total.toLocaleString()}</span> lineups
                  {players.length > 0 && ` containing all ${players.length} selected player${players.length > 1 ? 's' : ''}`}
                </>
              ) : (
                ' '
              )}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
                <InfoTip term="poss">Poss</InfoTip>
                <InfoTip term="ortg">ORtg</InfoTip>
                <InfoTip term="drtg">DRtg</InfoTip>
                <InfoTip term="net">Net</InfoTip>
                <InfoTip term="noise">✱ noise</InfoTip>
              </span>
              {query.isFetching && query.data && <Spinner label="Updating" />}
              {filtersActive && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => set({ team: undefined, player: [], min_pre: undefined, min_post: undefined, page: undefined })}
                >
                  Reset filters
                </Button>
              )}
            </div>
          </div>

          {query.error ? (
            <ErrorState error={query.error} onRetry={() => query.refetch()} />
          ) : !query.data ? (
            <LoadingBlock height="h-96" label="Loading lineups" />
          ) : query.data.items.length === 0 ? (
            <EmptyState title="No lineups match these filters">
              Try a lower possession threshold, another season, or fewer players. Players must have shared the floor in the same lineup.
            </EmptyState>
          ) : (
            <div className={query.isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}>
              <LineupTable
                items={query.data.items}
                showTeam={teamId === undefined}
                sort={sort}
                order={order}
                onSort={(k, o) => set({ sort: k === 'pre_poss' ? undefined : k, order: o === 'desc' ? undefined : o, page: undefined })}
              />
              <Pagination
                page={query.data.page}
                totalPages={query.data.total_pages}
                total={query.data.total}
                pageSize={pageSize}
                noun="lineups"
                onPage={(p) => set({ page: p > 1 ? p : undefined })}
                onPageSize={(n) => set({ size: n === 50 ? undefined : n, page: undefined })}
              />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
