"""Read-only data access for Phase 4. Every query is restricted to the development seasons.

The guard is applied twice: in SQL (`season_id = ANY(dev)`) and again on the returned frame
(`require_dev`). A query that accidentally drops the filter fails loudly instead of quietly
looking at held-out data.
"""
from __future__ import annotations

import pandas as pd
import psycopg

from ..config import DEV_SEASONS, HELDOUT_SEASONS


class HeldOutDataError(RuntimeError):
    pass


def require_dev(df: pd.DataFrame, column: str = "season_id") -> pd.DataFrame:
    leaked = set(df[column].unique()) - set(DEV_SEASONS)
    if leaked:
        raise HeldOutDataError(f"non-development seasons in analysis data: {sorted(leaked)} "
                               f"(held out: {list(HELDOUT_SEASONS)})")
    return df


def query(conn: psycopg.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query; NUMERIC (Decimal) columns become floats."""
    cur = conn.execute(sql, (params or {}) | {"dev": list(DEV_SEASONS)})
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for c in df.columns:
        if df[c].dtype == object:
            try:
                df[c] = pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    return df


def lineup_windows(conn: psycopg.Connection) -> pd.DataFrame:
    """One row per lineup-window (both windows), development seasons only."""
    return require_dev(query(conn, """
        SELECT r.season_id, se.is_irregular, r.window_type, r.team_id, r.abbreviation, r.lineup_id,
               r.minutes::float AS minutes, r.poss, r.opp_poss, r.pts, r.opp_pts,
               r.off_rating::float AS off_rating, r.def_rating::float AS def_rating, r.net_rating::float AS net_rating
        FROM v_lineup_window_ratings r JOIN seasons se USING (season_id)
        WHERE r.season_id = ANY(%(dev)s)"""))


def location_splits(conn: psycopg.Connection) -> pd.DataFrame:
    """Pre-break lineups with home and road halves side by side (columns suffixed _home / _road)."""
    df = require_dev(query(conn, """
        SELECT s.season_id, l.team_id, s.lineup_id, s.split, s.poss, s.opp_poss, s.pts, s.opp_pts,
               per100(s.pts, s.poss)::float - per100(s.opp_pts, s.opp_poss)::float AS net_rating
        FROM lineup_split_stats s JOIN lineups l USING (lineup_id, season_id)
        WHERE s.season_id = ANY(%(dev)s) AND s.window_type = 'pre_asb'"""))
    wide = df.pivot_table(index=["season_id", "team_id", "lineup_id"], columns="split",
                          values=["poss", "opp_poss", "pts", "opp_pts", "net_rating"], aggfunc="first")
    wide.columns = [f"{v}_{s}" for v, s in wide.columns]
    return wide.reset_index()


def team_games(conn: psycopg.Connection) -> pd.DataFrame:
    """Team game logs with the window each game falls in (development seasons)."""
    return require_dev(query(conn, """
        SELECT g.season_id, g.team_id, g.game_id, g.game_date, g.is_home, g.plus_minus, w.window_type
        FROM team_games g
        JOIN stat_windows w ON w.season_id = g.season_id AND g.game_date BETWEEN w.date_from AND w.date_to
        WHERE g.season_id = ANY(%(dev)s)
        ORDER BY g.season_id, g.team_id, g.game_date"""))


def pre_break_lineup_players(conn: psycopg.Connection) -> pd.DataFrame:
    """Pre-break only: each lineup's five players with their on-court possessions for that team, and
    how many teams each player appeared for before the break (a mid-season trade).

    Built from LINEUP data only. player_window_stats.last_team_id is deliberately not used: the API reports
    the player's latest team even under a pre-break date filter, which leaks post-break moves."""
    return require_dev(query(conn, """
        WITH oc AS (SELECT season_id, team_id, player_id, poss FROM v_player_window_on_court
                    WHERE window_type = 'pre_asb' AND season_id = ANY(%(dev)s)),
             nteams AS (SELECT season_id, player_id, count(DISTINCT team_id) AS n_teams FROM oc GROUP BY 1, 2)
        SELECT l.season_id, l.team_id, l.lineup_id, lp.player_id, oc.poss AS player_on_court_poss, nt.n_teams
        FROM lineups l
        JOIN lineup_window_stats s ON s.lineup_id = l.lineup_id AND s.window_type = 'pre_asb'
        JOIN lineup_players lp ON lp.lineup_id = l.lineup_id
        JOIN oc ON oc.season_id = l.season_id AND oc.team_id = l.team_id AND oc.player_id = lp.player_id
        JOIN nteams nt ON nt.season_id = l.season_id AND nt.player_id = lp.player_id
        WHERE l.season_id = ANY(%(dev)s)"""))
