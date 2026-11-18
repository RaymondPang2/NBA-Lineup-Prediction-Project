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
      return { season, pre: t?.pre_break.net_rating ?? null, post: t?.post_break.net_rating ?? null }
    }
    // League scoring level: sum points and possessions over every team, then divide.
    const pre = pooledRatings(teams.map((t) => ({ pts: t.pre_break.pts, poss: t.pre_break.poss, opp_pts: t.pre_break.opp_pts, opp_poss: t.pre_break.opp_poss })))
    const post = pooledRatings(teams.map((t) => ({ pts: t.post_break.pts, poss: t.post_break.poss, opp_pts: t.post_break.opp_pts, opp_poss: t.post_break.opp_poss })))
    return { season, pre: pre?.off ?? null, post: post?.off ?? null }
  })
  return { ...all, data }
}
