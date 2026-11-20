import clsx from 'clsx'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useLineupRanking, usePredictionRanking } from '../api/hooks'
import type { LineupRanking, PredictionRanking, RankedLineup, RankedPrediction } from '../api/types'
import { SeasonSelect, TeamSelect } from '../components/filters/Filters'
import { EstimandNotice } from '../components/prediction/EstimandNotice'
import { Badge, Callout, Card, CardBody, FilterBar, PageHeader } from '../components/ui/Card'
import { Field, PossessionSelect, Segmented } from '../components/ui/Controls'
import { EmptyState, ErrorState, LoadingBlock, Spinner } from '../components/ui/States'
import { Pagination, SortTh, TableWrap, Td, Th } from '../components/ui/Table'
import { TeamLogo } from '../components/ui/TeamLogo'
import { fmtDate, fmtInt, fmtInterval, fmtPct, fmtRating, fmtSigned, isNum, lastName } from '../lib/format'
import { useSeasonParam, useUrlState } from '../lib/urlState'

type Mode = 'actual' | 'predicted'
type Metric = 'net' | 'off' | 'def' | 'poss'
type Win = 'season' | 'pre' | 'post'

const TOPS = [10, 25, 50]
const POSS_PRESETS = [0, 25, 50, 100, 200, 300, 500]
const DEFAULT_MIN: Record<Mode, number> = { actual: 100, predicted: 50 }
const METRICS: { value: Metric; label: string; long: string }[] = [
  { value: 'net', label: 'Net rating', long: 'Best net rating: offensive minus defensive rating' },
  { value: 'off', label: 'Offense', long: 'Best offensive rating: points scored per 100 possessions' },
  { value: 'def', label: 'Defense', long: 'Best defensive rating: fewest points allowed per 100 opponent possessions' },
  { value: 'poss', label: 'Most used', long: 'Most-used lineups: most possessions played' },
]

/** Net ratings: sign and colour together, so positive and negative read at a glance without relying on colour. */
function NetValue({ value, strong = false }: { value: number | null | undefined; strong?: boolean }) {
  if (!isNum(value)) return <span className="text-muted">—</span>
  return (
    <span className={clsx('tabular', strong && 'font-semibold', value > 0 ? 'text-good' : value < 0 ? 'text-bad' : 'text-ink')}>{fmtSigned(value)}</span>
  )
}

function Rank({ n }: { n: number }) {
  return (
    <span
      className={clsx(
        'inline-flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-sm font-semibold tabular',
        n <= 3 ? 'bg-accent text-accent-ink' : 'bg-surface-3 text-ink',
      )}
    >
      {n}
    </span>
  )
}

function LineupCell({ id, players, extra }: { id: number; players: { player_name: string }[]; extra?: ReactNode }) {
  return (
    <div className="min-w-0">
      <Link to={`/lineups/${id}`} className="block font-medium whitespace-normal text-ink hover:text-accent" title={players.map((p) => p.player_name).join(', ')}>
        <span className="hidden 2xl:inline">{players.map((p) => p.player_name).join(' · ')}</span>
        <span className="2xl:hidden">{players.map((p) => lastName(p.player_name)).join(' · ')}</span>
      </Link>
      {extra}
    </div>
  )
}

function TeamCell({ id, abbr, name }: { id: number; abbr: string; name: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={name}>
      <TeamLogo teamId={id} abbreviation={abbr} name={name} size="xs" whenUnavailable="hide" decorative />
      <Badge>{abbr}</Badge>
    </span>
  )
}

const TIER_TONE = { low: 'bad', limited: 'warn', moderate: 'neutral', high: 'good' } as const

function Reliability({ r }: { r: RankedLineup }) {
  return (
    <span className="inline-flex flex-col items-end gap-0.5" title="Share of the net rating's deviation from its team that is signal rather than sampling noise">
      <span className="inline-flex items-center gap-1.5">
        {r.small_sample && (
          <Badge tone="warn" title="Fewer than 100 possessions on an end">
            small sample
          </Badge>
        )}
        {r.reliability_tier && <Badge tone={TIER_TONE[r.reliability_tier]}>{r.reliability_tier}</Badge>}
      </span>
      <span className="text-xs whitespace-nowrap text-muted tabular">
        {isNum(r.reliability) ? `${fmtPct(r.reliability)} signal` : ''}
        {isNum(r.net_rating_sampling_sd) ? ` · ±${r.net_rating_sampling_sd.toFixed(0)}` : ''}
      </span>
    </span>
  )
}

// ---------------------------------------------------------------- actual

function ActualTable({ data, onMetric }: { data: LineupRanking; onMetric: (m: Metric) => void }) {
  const metric = data.metric as Metric
  const sortTh = (key: Metric, label: string, title: string) => (
    <SortTh label={label} title={title} sortKey={key} sort={metric} order={key === 'def' ? 'asc' : 'desc'} defaultOrder={key === 'def' ? 'asc' : 'desc'} onSort={(k) => onMetric(k)} />
  )
  return (
    <TableWrap label="Lineup ranking">
      <thead>
        <tr>
          <Th align="center" className="w-12">#</Th>
          <Th align="left" className="sticky left-0 z-10 bg-surface">Lineup</Th>
          <Th align="left">Team</Th>
          <Th>Min</Th>
          {sortTh('poss', 'Poss', 'Rank by possessions (most used)')}
          {sortTh('off', 'ORtg', 'Rank by offensive rating (highest first)')}
          {sortTh('def', 'DRtg', 'Rank by defensive rating (lowest first)')}
          {sortTh('net', 'Net', 'Rank by net rating (highest first)')}
          <Th title="Sample size and reliability of the net rating">Reliability</Th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((r) => (
          <tr key={r.lineup_id} className="group hover:bg-surface-2" data-testid="rank-row">
            <Td align="center">
              <Rank n={r.rank} />
            </Td>
            <Td align="left" className="sticky left-0 z-10 w-[11rem] max-w-[11rem] bg-surface group-hover:bg-surface-2 sm:w-auto sm:max-w-none">
              <LineupCell
                id={r.lineup_id}
                players={r.players}
                extra={
                  <Link to={`/predict?season=${r.season_id}&team=${r.team_id}&lineup=${r.lineup_id}`} className="text-xs text-accent hover:underline">
                    Prediction ›
                  </Link>
                }
              />
            </Td>
            <Td align="left">
              <TeamCell id={r.team_id} abbr={r.team_abbreviation} name={r.team_name} />
            </Td>
            <Td>{fmtInt(Math.round(r.minutes))}</Td>
            <Td className={clsx(metric === 'poss' && 'font-semibold text-ink')}>{fmtInt(r.poss)}</Td>
            <Td className={clsx(metric === 'off' && 'font-semibold text-ink')}>{fmtRating(r.off_rating)}</Td>
            <Td className={clsx(metric === 'def' && 'font-semibold text-ink')}>{fmtRating(r.def_rating)}</Td>
            <Td>
              <NetValue value={r.net_rating} strong={metric === 'net'} />
            </Td>
            <Td>
              <Reliability r={r} />
            </Td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

// ---------------------------------------------------------------- predicted

function PredictedTable({ data }: { data: PredictionRanking }) {
  return (
    <TableWrap label="Prediction ranking">
      <thead>
        <tr>
          <Th align="center" className="w-12">#</Th>
          <Th align="left" className="sticky left-0 z-10 bg-surface">Recorded lineup</Th>
          <Th align="left">Team</Th>
          <Th title="Predicted post-All-Star-break net rating, if the lineup plays after the break">Predicted net</Th>
          <Th title="95% interval for the lineup's true post-break quality">95% interval</Th>
          <Th title="The team-prior baseline: the model is not shown to beat it">Team prior</Th>
          <Th title="Prediction minus the team-prior baseline">vs prior</Th>
          <Th title="Pre-break possessions together (own)">Pre poss</Th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((r: RankedPrediction) => (
          <tr key={r.lineup_id} className="group hover:bg-surface-2" data-testid="rank-row">
            <Td align="center">
              <Rank n={r.rank} />
            </Td>
            <Td align="left" className="sticky left-0 z-10 w-[11rem] max-w-[11rem] bg-surface group-hover:bg-surface-2 sm:w-auto sm:max-w-none">
              <LineupCell
                id={r.lineup_id}
                players={r.players}
                extra={
                  <span className="flex flex-wrap items-center gap-x-2 text-xs">
                    <Link to={`/predict?season=${r.season_id}&team=${r.team_id}&lineup=${r.lineup_id}`} className="text-accent hover:underline">
                      Full prediction ›
                    </Link>
                    {r.no_pre_break_history && <span className="text-warn">no pre-break minutes together</span>}
                  </span>
                }
              />
            </Td>
            <Td align="left">
              <TeamCell id={r.team_id} abbr={r.team_abbreviation} name={r.team_name} />
            </Td>
            <Td>
              <NetValue value={r.predicted_net_rating} strong />
            </Td>
            <Td className="whitespace-nowrap text-xs">{fmtInterval(r.true_rating_interval_95.lo, r.true_rating_interval_95.hi)}</Td>
            <Td>
              <NetValue value={r.team_prior} />
            </Td>
            <Td>{fmtSigned(r.model_minus_team_prior)}</Td>
            <Td>{fmtInt(r.pre_break_poss)}</Td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

function PredictionCaveats({ data }: { data: PredictionRanking }) {
  const half = data.interval_half_width
  return (
    <div className="mb-4 space-y-3">
      <EstimandNotice />
      {data.provisional && (
        <Callout tone="warn" title="Provisional: season in progress">
          <span data-testid="provisional-notice">
            {data.season_id} inputs are its pre-All-Star-break games through {data.data_cutoff ? fmtDate(data.data_cutoff) : 'the data cutoff'}. The model was evaluated on completed pre-break
            windows, so these rankings are not independently validated and the intervals are likely too narrow.
          </span>
        </Callout>
      )}
      {data.season_used_for_training && (
        <Callout tone="warn" title="In-sample season">
          {data.season_id} was a training season, so these are fitted values, not tests. Judge accuracy on the held-out seasons.
        </Callout>
      )}
      <Callout title="Read the order as weak evidence">
        <span data-testid="uncertainty-notice">
          Every prediction carries a 95% interval of about <strong className="font-semibold text-ink">±{half.toFixed(1)}</strong> points for the lineup’s true quality
          {isNum(data.prediction_spread) && (
            <>
              , while the middle 80% of the ranked predictions span only <strong className="font-semibold text-ink">{data.prediction_spread.toFixed(1)}</strong> points
            </>
          )}
          . Neighbouring ranks are not meaningfully different. Only recorded lineups are ranked; to score a hypothetical five-player combination use{' '}
          <Link to={`/predict?season=${data.season_id}${data.team_id ? `&team=${data.team_id}` : ''}`} className="text-accent hover:underline">
            Build a five
          </Link>{' '}
          on the Predict page.
        </span>
      </Callout>
    </div>
  )
}

// ---------------------------------------------------------------- page

export default function RankingsPage() {
  const { set, get, getNum } = useUrlState()
  const { season, seasons, seasonInfo } = useSeasonParam()
  const teamId = getNum('team')
  const mode: Mode = get('mode') === 'predicted' ? 'predicted' : 'actual'
  const metricParam = get('metric') as Metric | null
  const metric: Metric = metricParam && METRICS.some((m) => m.value === metricParam) ? metricParam : 'net'
  const winParam = get('window') as Win | null
  const win: Win = winParam === 'pre' || winParam === 'post' ? winParam : 'season'
  const minPoss = getNum('min', DEFAULT_MIN[mode])!
  const top = TOPS.includes(getNum('top', 25)!) ? getNum('top', 25)! : 25
  const page = Math.max(1, getNum('page', 1)!)
  const current = seasonInfo?.role === 'current'

  const actual = useLineupRanking(
    { season: season!, team_id: teamId, window: win, metric, min_poss: minPoss, page, page_size: top },
    !!season && mode === 'actual',
  )
  const predicted = usePredictionRanking({ season: season!, team_id: teamId, min_pre_poss: minPoss, page, page_size: top }, !!season && mode === 'predicted')
  const q = mode === 'actual' ? actual : predicted

  const windowOptions: { value: Win; label: string }[] = [
    { value: 'season', label: current ? 'Season to date' : 'Full season' },
    { value: 'pre', label: 'Pre-break' },
    { value: 'post', label: 'Post-break' },
  ]

  return (
    <div>
      <PageHeader
        title="Lineup rankings"
        description={
          <>
            The best five-man units by actual results, or recorded lineups ranked by the frozen model’s prediction. Every qualifying lineup of the season is ranked before the
            top rows are shown, so the ranks are league-wide (or team-wide). Possession thresholds apply to <em>both</em> ends, to keep tiny samples out of the top.
          </>
        }
      >
        {current && (
          <p className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <Badge tone="warn" title="Season to date, refreshed daily">
              {season} in progress
            </Badge>
            <span>Rankings update after each daily refresh.</span>
          </p>
        )}
      </PageHeader>

      <FilterBar>
        <SeasonSelect seasons={seasons} value={season} onChange={(v) => set({ season: v, page: undefined, window: undefined })} />
        <TeamSelect season={season} value={teamId} onChange={(v) => set({ team: v, page: undefined })} />
        <Field label="Rank by" className="col-span-2 sm:!w-auto">
          {() => (
            <Segmented
              label="Rank by"
              value={mode}
              options={[
                { value: 'actual', label: 'Actual results' },
                { value: 'predicted', label: 'Model prediction' },
              ]}
              onChange={(v) => set({ mode: v === 'actual' ? undefined : v, page: undefined, min: undefined })}
            />
          )}
        </Field>
        <PossessionSelect
          label={mode === 'actual' ? 'Min possessions' : 'Min pre-break poss.'}
          value={minPoss}
          presets={POSS_PRESETS}
          onChange={(v) => set({ min: v === DEFAULT_MIN[mode] ? undefined : v, page: undefined })}
          hint="On each end"
        />
        <Field label="Show" className="col-span-2 sm:col-span-1 sm:!w-auto">
          {() => (
            <Segmented label="Show top" value={String(top)} options={TOPS.map((t) => ({ value: String(t), label: `Top ${t}` }))} onChange={(v) => set({ top: v === '25' ? undefined : Number(v), page: undefined })} />
          )}
        </Field>
      </FilterBar>

      {mode === 'actual' && (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <Field label="Category" className="min-w-0">
            {() => <Segmented label="Category" value={metric} options={METRICS.map((m) => ({ value: m.value, label: m.label }))} onChange={(v) => set({ metric: v === 'net' ? undefined : v, page: undefined })} />}
          </Field>
          <Field label="Window" className="min-w-0">
            {() => <Segmented label="Window" value={win} options={windowOptions} onChange={(v) => set({ window: v === 'season' ? undefined : v, page: undefined })} />}
          </Field>
        </div>
      )}

      <Card>
        <CardBody className="pt-4">
          <div className="mb-3 flex min-h-8 flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-2" aria-live="polite" data-testid="ranking-summary">
              {mode === 'actual' && actual.data ? (
                <>
                  <span className="font-semibold text-ink">{METRICS.find((m) => m.value === actual.data.metric)?.long}</span> ·{' '}
                  <span className="font-medium text-ink">{actual.data.window_info.label}</span>
                  {actual.data.window_info.date_from && actual.data.window_info.date_to && ` (${fmtDate(actual.data.window_info.date_from)} – ${fmtDate(actual.data.window_info.date_to)})`} ·{' '}
                  {actual.data.total.toLocaleString()} lineups with ≥ {actual.data.min_poss} possessions per end
                </>
              ) : mode === 'predicted' && predicted.data ? (
                <>
                  <span className="font-semibold text-ink">Predicted post-All-Star-break net rating</span> · {predicted.data.total.toLocaleString()} recorded lineups with ≥{' '}
                  {predicted.data.min_pre_poss} pre-break possessions per end
                </>
              ) : (
                ' '
              )}
            </p>
            {q.isFetching && q.data && <Spinner label="Updating" />}
          </div>

          {mode === 'actual' && minPoss < 100 && (
            <div className="mb-4">
              <Callout tone="warn" title="Small samples can top this ranking">
                Below 100 possessions per end a net rating’s sampling noise alone is about ±20 points or more, so the leaders are often lucky rather than good. Raise the
                threshold for a more trustworthy ranking.
              </Callout>
            </div>
          )}
          {mode === 'predicted' && predicted.data && <PredictionCaveats data={predicted.data} />}

          {q.error ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          ) : !q.data ? (
            <LoadingBlock height="h-96" label="Ranking lineups" />
          ) : q.data.items.length === 0 ? (
            mode === 'actual' && actual.data && !actual.data.window_info.available ? (
              <EmptyState title="No post-break games yet">
                {season} has not reached the All-Star break, so there is no post-break window to rank. Choose {current ? 'Season to date' : 'Full season'} or Pre-break.
              </EmptyState>
            ) : (
              <EmptyState title="No lineups qualify">Lower the possession threshold or choose another team or season.</EmptyState>
            )
          ) : (
            <div className={q.isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}>
              {mode === 'actual' ? (
                <ActualTable data={actual.data!} onMetric={(m) => set({ metric: m === 'net' ? undefined : m, page: undefined })} />
              ) : (
                <PredictedTable data={predicted.data!} />
              )}
              <Pagination
                page={q.data.page}
                totalPages={q.data.total_pages}
                total={q.data.total}
                pageSize={top}
                noun="ranked lineups"
                onPage={(p) => set({ page: p > 1 ? p : undefined })}
              />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
