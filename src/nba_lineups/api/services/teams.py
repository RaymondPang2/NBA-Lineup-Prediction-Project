"""Team ratings per season and window, built from LINEUP totals (the same possession definition as lineups;
the team endpoint counts ~3% fewer possessions), with win-loss records from the game log."""
from __future__ import annotations

import psycopg

from .. import db
from .catalog import require_season, require_team
from .common import change, window

FIELDS = ("lineup_minutes", "poss", "opp_poss", "pts", "opp_pts", "off_rating", "def_rating", "net_rating",
          "games", "wins", "losses", "n_lineups")

_SQL = """
    WITH r AS (
        SELECT season_id, team_id, window_type, lineup_minutes::float8 AS lineup_minutes, poss, opp_poss, pts, opp_pts,
               off_rating::float8 AS off_rating, def_rating::float8 AS def_rating, net_rating::float8 AS net_rating
        FROM v_team_window_ratings WHERE season_id = %(season)s AND (%(team)s::int IS NULL OR team_id = %(team)s)),
    g AS (
        SELECT g.season_id, g.team_id, w.window_type, count(*) AS games,
               count(*) FILTER (WHERE g.won) AS wins, count(*) FILTER (WHERE NOT g.won) AS losses
        FROM team_games g JOIN stat_windows w ON w.season_id = g.season_id
                                              AND g.game_date BETWEEN w.date_from AND w.date_to
        WHERE g.season_id = %(season)s AND (%(team)s::int IS NULL OR g.team_id = %(team)s)
        GROUP BY 1, 2, 3),
    n AS (
        SELECT l.season_id, l.team_id, s.window_type, count(*) AS n_lineups
        FROM lineups l JOIN lineup_window_stats s USING (lineup_id, season_id)
        WHERE l.season_id = %(season)s AND (%(team)s::int IS NULL OR l.team_id = %(team)s)
        GROUP BY 1, 2, 3),
    x AS (SELECT r.*, coalesce(g.games, 0) AS games, coalesce(g.wins, 0) AS wins, coalesce(g.losses, 0) AS losses,
                 coalesce(n.n_lineups, 0) AS n_lineups
          FROM r LEFT JOIN g USING (season_id, team_id, window_type) LEFT JOIN n USING (season_id, team_id, window_type))
    SELECT t.team_id, t.abbreviation, t.team_name, %(season)s::text AS season_id,
           {pre}, {post}
    FROM teams t
    LEFT JOIN x pre  ON pre.team_id  = t.team_id AND pre.window_type  = 'pre_asb'
    LEFT JOIN x post ON post.team_id = t.team_id AND post.window_type = 'post_asb'
    WHERE (pre.team_id IS NOT NULL OR post.team_id IS NOT NULL)
    ORDER BY pre.net_rating DESC NULLS LAST, t.abbreviation"""


def _cols(a: str) -> str:
    return ", ".join(f"{a}.{c} AS {a}_{c}" for c in FIELDS)


def _shape(r: dict) -> dict:
    pre, post = window(r, "pre", None, FIELDS), window(r, "post", None, FIELDS)
    return {"team_id": r["team_id"], "abbreviation": r["abbreviation"], "team_name": r["team_name"],
            "season_id": r["season_id"], "pre_break": pre, "post_break": post, "change": change(pre, post, None)}


def team_seasons(conn: psycopg.Connection, season: str, team_id: int | None = None) -> list[dict]:
    require_season(conn, season)
    if team_id is not None:
        require_team(conn, team_id)
    rows = db.fetch_all(conn, _SQL.format(pre=_cols("pre"), post=_cols("post")), {"season": season, "team": team_id})
    return [_shape(r) for r in rows]
