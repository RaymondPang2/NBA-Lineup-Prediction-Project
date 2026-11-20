import type { HistoryPoint } from '../components/charts/TeamCharts'
import { pooledRatings } from '../lib/stats'
import { useTeamStatsForSeasons } from './hooks'

/**
 * Season-by-season series from /teams/stats: one team's pre/post net rating, or (no team) the league's
 * pre/post offensive rating pooled from summed team totals.
 */
export function useHistory(seasonIds: string[], teamId: number | undefined) {
  const all = useTeamStatsForSeasons(seasonIds)
  const data: HistoryPoint[] | undefined = all.data?.map(({ season, teams }) => {
    if (teamId) {
      const t = teams.find((x) => x.team_id === teamId)
      return { season, pre: t?.pre_break?.net_rating ?? null, post: t?.post_break?.net_rating ?? null }
    }
    // League scoring level: sum points and possessions over every team, then divide.
    // A window a season has not reached yet (the season in progress before the break) is a gap, not a zero.
    const totals = (w: 'pre_break' | 'post_break') => {
      const rows = teams.flatMap((t) => (t[w] ? [{ pts: t[w].pts, poss: t[w].poss, opp_pts: t[w].opp_pts, opp_poss: t[w].opp_poss }] : []))
      return rows.length ? pooledRatings(rows) : null
    }
    const pre = totals('pre_break')
    const post = totals('post_break')
    return { season, pre: pre?.off ?? null, post: post?.off ?? null }
  })
  return { ...all, data }
}
