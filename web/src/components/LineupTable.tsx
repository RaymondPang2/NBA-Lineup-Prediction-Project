import { Link } from 'react-router'
import type { LineupSort, LineupSummary } from '../api/types'
import { fmtInt, fmtRating, fmtSigned, lastName } from '../lib/format'
import { Badge, Delta } from './ui/Card'
import { SortTh, TableWrap, Td, Th, type SortOrder } from './ui/Table'

interface Column {
  key: LineupSort | null
  label: string
  title?: string
  render: (l: LineupSummary) => React.ReactNode
}

const COLUMNS: Column[] = [
  { key: 'pre_poss', label: 'Pre poss', title: 'Pre-break possessions (own)', render: (l) => fmtInt(l.pre_break?.poss) },
  { key: 'pre_off', label: 'Pre ORtg', render: (l) => fmtRating(l.pre_break?.off_rating) },
  { key: 'pre_def', label: 'Pre DRtg', render: (l) => fmtRating(l.pre_break?.def_rating) },
  { key: 'pre_net', label: 'Pre net', render: (l) => <span className="font-medium text-ink">{fmtSigned(l.pre_break?.net_rating)}</span> },
  { key: 'post_poss', label: 'Post poss', title: 'Post-break possessions (own)', render: (l) => fmtInt(l.post_break?.poss) },
  { key: 'post_off', label: 'Post ORtg', render: (l) => fmtRating(l.post_break?.off_rating) },
  { key: 'post_def', label: 'Post DRtg', render: (l) => fmtRating(l.post_break?.def_rating) },
  { key: 'post_net', label: 'Post net', render: (l) => <span className="font-medium text-ink">{fmtSigned(l.post_break?.net_rating)}</span> },
  {
    key: 'net_change',
    label: 'Δ Net',
    title: 'Post minus pre net rating. ✱ = larger than sampling noise (|Δ| > 1.96 SD)',
    render: (l) =>
      l.change ? (
        <span className="inline-flex items-center gap-1">
          <Delta value={l.change.net_rating} format={fmtSigned} />
          {l.change.exceeds_noise && (
            <span className="text-xs text-ink" title="Change exceeds sampling noise (|Δ| > 1.96 SD)" aria-label="exceeds sampling noise">
              ✱
            </span>
          )}
        </span>
      ) : (
        <span className="text-muted">—</span>
      ),
  },
]

export function LineupTable({
  items,
  showTeam,
  sort,
  order,
  onSort,
  compact = false,
}: {
  items: LineupSummary[]
  showTeam: boolean
  sort?: LineupSort
  order?: SortOrder
  onSort?: (k: LineupSort, o: SortOrder) => void
  compact?: boolean
}) {
  const cols = compact ? COLUMNS.filter((c) => !['pre_off', 'pre_def', 'post_off', 'post_def'].includes(c.key ?? '')) : COLUMNS
  return (
    <TableWrap label="Lineups">
      <thead>
        <tr>
          <Th align="left" className="sticky left-0 z-10 bg-surface">
            Lineup
          </Th>
          {showTeam && <Th align="left">Team</Th>}
          {cols.map((c) =>
            onSort && sort && order && c.key ? (
              <SortTh key={c.label} label={c.label} title={c.title} sortKey={c.key} sort={sort} order={order} onSort={onSort} />
            ) : (
              <Th key={c.label} title={c.title}>
                {c.label}
              </Th>
            ),
          )}
        </tr>
      </thead>
      <tbody>
        {items.map((l) => (
          <tr key={l.lineup_id} className="group hover:bg-surface-2">
            <Td align="left" className="sticky left-0 z-10 max-w-[16rem] bg-surface group-hover:bg-surface-2 sm:max-w-none">
              <Link to={`/lineups/${l.lineup_id}`} className="block truncate font-medium text-ink hover:text-accent" title={l.players.map((p) => p.player_name).join(', ')}>
                {l.players.map((p) => lastName(p.player_name)).join(' · ')}
              </Link>
            </Td>
            {showTeam && (
              <Td align="left">
                <Badge>{l.team_abbreviation}</Badge>
              </Td>
            )}
            {cols.map((c) => (
              <Td key={c.label}>{c.render(l)}</Td>
            ))}
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}
