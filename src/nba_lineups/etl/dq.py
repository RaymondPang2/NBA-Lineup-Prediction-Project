"""Data-quality and reconciliation checks, written in SQL.

Each check's query returns the VIOLATING rows for one season. An empty result
means it passes. 'error' checks run inside the load transaction, so a failure
rolls the whole season back (the bad data never becomes visible). 'warning'
checks are recorded and reported, but they don't block the load.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

ERROR, WARNING = "error", "warning"

# Per team-window totals from the lineup feed vs the game log and the team endpoint.
_TEAM_WINDOW_TOTALS = """
WITH lu AS (
    SELECT l.team_id, s.window_type,
           sum(s.pts) AS pts, sum(s.plus_minus) AS pm, sum(s.seconds) / 60.0 AS minutes, sum(s.poss) AS poss
    FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
    WHERE s.season_id = %(season)s GROUP BY 1, 2),
gm AS (
    SELECT g.team_id, w.window_type, sum(g.pts) AS pts, sum(g.plus_minus) AS pm
    FROM team_games g
    JOIN stat_windows w ON w.season_id = g.season_id AND g.game_date BETWEEN w.date_from AND w.date_to
    WHERE g.season_id = %(season)s GROUP BY 1, 2),
tw AS (
    SELECT team_id, window_type, minutes, poss FROM team_window_stats WHERE season_id = %(season)s)
"""


@dataclass(frozen=True)
class Check:
    name: str
    severity: str
    description: str
    sql: str


CHECKS: tuple[Check, ...] = (
    Check("lineup_has_five_players", ERROR, "every lineup links to exactly 5 players", """
        SELECT l.lineup_id, count(lp.player_id) AS n_players
        FROM lineups l LEFT JOIN lineup_players lp USING (lineup_id)
        WHERE l.season_id = %(season)s
        GROUP BY l.lineup_id HAVING count(lp.player_id) <> 5"""),
    Check("lineup_has_stats", ERROR, "every lineup has at least one window of stats", """
        SELECT l.lineup_id FROM lineups l
        WHERE l.season_id = %(season)s
          AND NOT EXISTS (SELECT 1 FROM lineup_window_stats s WHERE s.lineup_id = l.lineup_id)"""),
    Check("game_has_two_teams", ERROR, "every game appears exactly twice (once per team)", """
        SELECT game_id, count(*) AS n FROM team_games WHERE season_id = %(season)s
        GROUP BY game_id HAVING count(*) <> 2"""),
    Check("game_rows_consistent", ERROR,
          "the two rows of a game agree: scores, exactly one winner, and exactly one home team or a neutral site", """
        SELECT a.game_id, a.team_id FROM team_games a
        JOIN team_games b ON a.game_id = b.game_id AND a.team_id <> b.team_id
        WHERE a.season_id = %(season)s
          AND (a.plus_minus <> a.pts - b.pts
               OR a.won = b.won
               OR (a.is_home IS NULL) <> (b.is_home IS NULL)   -- neutral must be neutral for both teams
               OR a.is_home = b.is_home)                      -- both home or both away (NULL = NULL is not TRUE)"""),
    Check("game_in_exactly_one_window", ERROR, "every game date falls in exactly one window (no gaps, no overlap)", """
        SELECT g.game_id, g.team_id, count(w.window_type) AS n_windows
        FROM team_games g
        LEFT JOIN stat_windows w ON w.season_id = g.season_id AND g.game_date BETWEEN w.date_from AND w.date_to
        WHERE g.season_id = %(season)s GROUP BY 1, 2 HAVING count(w.window_type) <> 1"""),
    # Every team that played a game in a window has lineup stats for it (for a completed season: all 30 teams
    # in both windows; for a season in progress, a team that has not played since the break is excused).
    Check("team_has_lineups_in_both_windows", ERROR, "every team with games in a window has lineup stats for it", """
        SELECT DISTINCT g.team_id, w.window_type
        FROM team_games g
        JOIN stat_windows w ON w.season_id = g.season_id AND g.game_date BETWEEN w.date_from AND w.date_to
        WHERE g.season_id = %(season)s AND NOT EXISTS (
            SELECT 1 FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
            WHERE s.season_id = w.season_id AND s.window_type = w.window_type AND l.team_id = g.team_id)"""),
    # Points: ERROR beyond a 2-point tolerance per team-window (a lost game or lineup would be tens of
    # points), WARNING for any non-zero difference so tiny source inconsistencies stay visible.
    # Known case: game 0022500704 (2026-02-01, BKN @ DET), where the box score has 1 BKN point that is not
    # credited to any lineup in the lineup feed.
    Check("points_reconcile", ERROR, "lineup points within 2 of game-log points per team-window",
          _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, lu.pts AS lineup_pts, gm.pts AS game_pts
        FROM lu FULL JOIN gm USING (team_id, window_type)
        WHERE lu.pts IS NULL OR gm.pts IS NULL OR abs(lu.pts - gm.pts) > 2"""),
    Check("plus_minus_reconcile", ERROR, "lineup plus-minus within 2 of game-log plus-minus per team-window",
          _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, lu.pm AS lineup_pm, gm.pm AS game_pm
        FROM lu FULL JOIN gm USING (team_id, window_type)
        WHERE lu.pm IS NULL OR gm.pm IS NULL OR abs(lu.pm - gm.pm) > 2"""),
    Check("points_exact", WARNING, "lineup points equal game-log points exactly", _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, lu.pts - gm.pts AS diff
        FROM lu JOIN gm USING (team_id, window_type) WHERE lu.pts <> gm.pts"""),
    Check("plus_minus_exact", WARNING, "lineup plus-minus equals game-log plus-minus exactly",
          _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, lu.pm - gm.pm AS diff
        FROM lu JOIN gm USING (team_id, window_type) WHERE lu.pm <> gm.pm"""),
    Check("minutes_reconcile", ERROR, "lineup time sums to team minutes (within 1 min) per team-window",
          _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, round(lu.minutes, 2) AS lineup_min, tw.minutes AS team_min
        FROM lu FULL JOIN tw USING (team_id, window_type)
        WHERE lu.minutes IS NULL OR tw.minutes IS NULL OR abs(lu.minutes - tw.minutes) > 1"""),
    Check("possession_ratio_in_band", WARNING,
          "lineup-feed possessions / team-endpoint possessions within [1.00, 1.08] (feeds count differently)",
          _TEAM_WINDOW_TOTALS + """
        SELECT team_id, window_type, round(lu.poss::numeric / tw.poss, 4) AS ratio
        FROM lu JOIN tw USING (team_id, window_type)
        WHERE lu.poss::numeric / tw.poss NOT BETWEEN 1.00 AND 1.08"""),
    Check("lineup_players_have_window_stats", WARNING, "players in a window's lineups have player stats for it", """
        SELECT DISTINCT lp.player_id, s.window_type
        FROM lineup_window_stats s JOIN lineup_players lp USING (lineup_id)
        WHERE s.season_id = %(season)s AND NOT EXISTS (
            SELECT 1 FROM player_window_stats p
            WHERE p.player_id = lp.player_id AND p.season_id = s.season_id AND p.window_type = s.window_type)"""),
    Check("opp_poss_close_to_poss", WARNING,
          "for lineups with >=100 possessions, opponent possessions within 15% of own (real exceptions exist)", """
        SELECT lineup_id, window_type, poss, opp_poss FROM lineup_window_stats
        WHERE season_id = %(season)s AND poss >= 100
          AND (opp_poss IS NULL OR abs(opp_poss - poss) > 0.15 * poss)"""),
    # ---- Phase 3: metric validation
    Check("opp_poss_known_when_time_played", ERROR,
          "canonical opponent possessions are known for every lineup-window with playing time", """
        SELECT lineup_id, window_type, seconds FROM lineup_window_stats
        WHERE season_id = %(season)s AND seconds > 0 AND opp_poss IS NULL"""),
    Check("ratings_match_nba", ERROR,
          "our exact ORtg/DRtg/Net, rounded half-up to 0.1, equal NBA's published values (un-merged lineups)", """
        SELECT lineup_id, window_type,
               round(per100(pts, poss), 1) AS our_off, nba_off_rating,
               round(per100(opp_pts, opp_poss), 1) AS our_def, nba_def_rating, nba_net_rating
        FROM lineup_window_stats
        WHERE season_id = %(season)s AND n_source_rows = 1 AND poss > 0 AND opp_poss > 0
          AND (round(per100(pts, poss), 1) <> nba_off_rating
               OR round(per100(opp_pts, opp_poss), 1) <> nba_def_rating
               OR round(per100(pts, poss) - per100(opp_pts, opp_poss), 1) <> nba_net_rating)"""),
)


@dataclass
class CheckResult:
    name: str
    severity: str
    description: str
    violations: int
    sample: list[Any] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.violations == 0


def run_checks(conn: psycopg.Connection, season: str, checks: tuple[Check, ...] = CHECKS) -> list[CheckResult]:
    results = []
    with conn.cursor() as cur:
        for c in checks:
            rows = cur.execute(c.sql, {"season": season}).fetchall()
            results.append(CheckResult(c.name, c.severity, c.description, len(rows),
                                       [list(map(str, r)) for r in rows[:3]]))
    return results
