import { Link, useParams } from 'react-router'
import { useLineup, useSeasons } from '../api/hooks'
import type { LineupDetail, WindowStats } from '../api/types'
import { ChartFrame } from '../components/charts/ChartFrame'
import { DotWhisker } from '../components/charts/DotWhisker'
import { Badge, Callout, Card, CardBody, CardHeader, Delta, PageHeader, Stat } from '../components/ui/Card'
import { EmptyState, ErrorState, LoadingBlock } from '../components/ui/States'
import { TableWrap, Td, Th } from '../components/ui/Table'
import { fmtInt, fmtNum, fmtRating, fmtSigned } from '../lib/format'

const Z = 1.959964

type WindowKey = 'pre_break' | 'post_break' | 'season_total'
const WINDOWS: { key: WindowKey; label: string }[] = [
  { key: 'pre_break', label: 'Pre-break' },
  { key: 'post_break', label: 'Post-break' },
  { key: 'season_total', label: 'Full season' },
]

function windowOf(l: LineupDetail, k: WindowKey): WindowStats | null | undefined {
  return l[k]
}

function WindowTable({ lineup }: { lineup: LineupDetail }) {
  const rows: [string, (w: WindowStats) => string][] = [
    ['Games', (w) => fmtInt(w.gp)],
    ['Minutes', (w) => fmtNum(w.minutes, 1)],
    ['Possessions (own / opp.)', (w) => `${fmtInt(w.poss)} / ${fmtInt(w.opp_poss)}`],
    ['Points (own / opp.)', (w) => `${fmtInt(w.pts)} / ${fmtInt(w.opp_pts)}`],
    ['Offensive rating', (w) => fmtRating(w.off_rating)],
    ['Defensive rating', (w) => fmtRating(w.def_rating)],
    ['Net rating', (w) => fmtSigned(w.net_rating)],
    ['Net rating sampling SD', (w) => fmtNum(w.net_rating_sampling_sd, 1)],
  ]
  return (
    <TableWrap label="Ratings by window">
      <thead>
        <tr>
          <Th align="left">Statistic</Th>
          {WINDOWS.map((w) => (
            <Th key={w.key}>{w.label}</Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, f]) => (
          <tr key={label}>
            <Td align="left" className="text-ink-2">
              {label}
            </Td>
            {WINDOWS.map((w) => {
              const s = windowOf(lineup, w.key)
              return (
                <Td key={w.key} className="text-ink">
                  {s ? f(s) : '—'}
                </Td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

export default function LineupDetailPage() {
  const { lineupId } = useParams()
  const id = Number(lineupId)
  const valid = Number.isInteger(id) && id > 0
  const q = useLineup(valid ? id : undefined)
  const seasons = useSeasons()

  if (!valid) return <EmptyState title="Invalid lineup id">Lineup ids are positive integers.</EmptyState>
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  if (!q.data) return <LoadingBlock label="Loading lineup" height="h-96" />

  const l = q.data
  const season = seasons.data?.find((s) => s.season_id === l.season_id)
  const pre = l.pre_break
  const post = l.post_break
  const available = WINDOWS.filter((w) => windowOf(l, w.key))

  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
        <Link to={`/lineups?season=${l.season_id}&team=${l.team_id}`} className="hover:text-accent">
          ‹ {l.team_abbreviation} lineups, {l.season_id}
        </Link>
      </nav>
      <PageHeader
        title={l.players.map((p) => p.player_name).join(' · ')}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge>{l.team_abbreviation}</Badge>
            <span>{l.season_id}</span>
            {season?.role === 'held_out' && <Badge tone="accent">Held-out season</Badge>}
            {season?.is_irregular && <Badge tone="warn">Irregular season</Badge>}
            <span className="text-muted">Lineup #{l.lineup_id}</span>
          </span>
        }
      >
        <div className="flex flex-wrap gap-2">
          <Link
            to={`/predict?season=${l.season_id}&team=${l.team_id}&lineup=${l.lineup_id}`}
            className="inline-flex h-10 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-110"
          >
            See the frozen-model prediction ›
          </Link>
          {l.players.map((p) => (
            <Link
              key={p.player_id}
              to={`/lineups?season=${l.season_id}&player=${p.player_id}`}
              className="inline-flex h-10 items-center rounded-md border border-line-strong px-3 text-sm text-ink-2 hover:bg-surface-2"
              title={`All ${l.season_id} lineups with ${p.player_name}`}
            >
              {p.player_name.split(' ').slice(-1)[0]} lineups
            </Link>
          ))}
        </div>
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Pre-break net" value={fmtSigned(pre?.net_rating)} detail={pre ? `${fmtInt(pre.poss)} poss · ± ${fmtNum(pre.net_rating_sampling_sd, 1)} SD` : 'Did not play before the break'} />
        <Stat label="Post-break net" value={fmtSigned(post?.net_rating)} detail={post ? `${fmtInt(post.poss)} poss · ± ${fmtNum(post.net_rating_sampling_sd, 1)} SD` : 'Did not play after the break'} />
        <Stat
          label="Change in net"
          value={<Delta value={l.change?.net_rating} format={fmtSigned} />}
          detail={l.change ? (l.change.exceeds_noise ? 'Larger than sampling noise' : 'Within sampling noise') : 'Needs both windows'}
        />
        <Stat label="Full season" value={fmtSigned(l.season_total?.net_rating)} detail={l.season_total ? `${fmtInt(l.season_total.poss)} poss · ${fmtInt(l.season_total.gp)} games` : undefined} />
      </div>

      {l.change && (
        <div className="mt-4">
          <Callout tone={l.change.exceeds_noise ? 'warn' : 'info'} title={l.change.exceeds_noise ? 'A change larger than noise' : 'A change within noise'}>
            Net rating moved {fmtSigned(l.change.net_rating)} after the break. With these sample sizes the change has a sampling SD of {fmtNum(l.change.net_rating_sampling_sd, 1)}, so
            a 95% band for pure noise is ±{fmtNum((l.change.net_rating_sampling_sd ?? NaN) * Z, 1)}.{' '}
            {l.change.exceeds_noise
              ? 'This change is outside that band: it is unlikely to be sampling noise alone (though opponents, injuries and roles also change).'
              : 'This change is inside that band: it is consistent with no real change at all.'}
          </Callout>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ChartFrame
          title="Net rating by window"
          subtitle="Dots are observed net ratings; whiskers are 95% sampling intervals (±1.96 SD)."
          table={<WindowTable lineup={l} />}
        >
          {available.length ? (
            <DotWhisker
              zeroLine
              format={(v) => fmtSigned(v, 0)}
              series={[{ key: 'net', label: 'Net rating', color: 'var(--series-1)' }]}
              rows={available.map((w) => {
                const s = windowOf(l, w.key)!
                const sd = s.net_rating_sampling_sd
                return {
                  label: w.label,
                  values: {
                    net: {
                      v: s.net_rating,
                      lo: s.net_rating !== null && sd !== null ? s.net_rating - Z * sd : undefined,
                      hi: s.net_rating !== null && sd !== null ? s.net_rating + Z * sd : undefined,
                      note: `${fmtInt(s.poss)} poss`,
                    },
                  },
                }
              })}
            />
          ) : (
            <EmptyState title="No ratings recorded" />
          )}
        </ChartFrame>

        <ChartFrame
          title="Offense and defense by window"
          subtitle="Points scored and allowed per 100 possessions. Lower defensive rating is better."
          legend={[
            { label: 'Offensive rating', color: 'var(--series-1)' },
            { label: 'Defensive rating', color: 'var(--series-2)' },
          ]}
          table={<WindowTable lineup={l} />}
        >
          <DotWhisker
            format={(v) => fmtRating(v, 0)}
            series={[
              { key: 'off', label: 'ORtg', color: 'var(--series-1)' },
              { key: 'def', label: 'DRtg', color: 'var(--series-2)' },
            ]}
            rows={available.map((w) => {
              const s = windowOf(l, w.key)!
              return { label: w.label, values: { off: { v: s.off_rating }, def: { v: s.def_rating } } }
            })}
          />
        </ChartFrame>
      </div>

      <Card className="mt-6">
        <CardHeader title="All statistics" subtitle="Ratings are 100 × points ÷ possessions, with opponent possessions counted separately." />
        <CardBody>
          <WindowTable lineup={l} />
        </CardBody>
      </Card>
    </div>
  )
}
