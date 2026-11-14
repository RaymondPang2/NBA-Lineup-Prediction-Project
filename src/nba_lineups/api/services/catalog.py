"""Seasons and teams. Small reference data used to fill frontend pickers and to validate ids."""
from __future__ import annotations

import psycopg

from ...config import HELDOUT_SEASONS
from .. import db
from ..errors import NotFound


def seasons(conn: psycopg.Connection) -> list[dict]:
    rows = db.fetch_all(conn, """
        SELECT s.season_id, s.start_year, s.is_irregular, s.first_game_date, s.last_game_date,
               coalesce(json_agg(json_build_object('window_type', w.window_type, 'date_from', w.date_from,
                                                   'date_to', w.date_to) ORDER BY w.date_from)
                        FILTER (WHERE w.window_type IS NOT NULL), '[]') AS windows,
               (SELECT count(*) FROM lineups l WHERE l.season_id = s.season_id) AS n_lineups
        FROM seasons s LEFT JOIN stat_windows w USING (season_id)
        GROUP BY s.season_id ORDER BY s.season_id""")
    for r in rows:
        r["role"] = "held_out" if r["season_id"] in HELDOUT_SEASONS else "development"
    return rows


def require_season(conn: psycopg.Connection, season_id: str) -> None:
    if db.fetch_one(conn, "SELECT 1 FROM seasons WHERE season_id = %(s)s", {"s": season_id}) is None:
        raise NotFound(f"season {season_id} not found")


def require_team(conn: psycopg.Connection, team_id: int) -> dict:
    r = db.fetch_one(conn, "SELECT team_id, abbreviation, team_name FROM teams WHERE team_id = %(t)s", {"t": team_id})
    if r is None:
        raise NotFound(f"team {team_id} not found")
    return r


def teams(conn: psycopg.Connection, season_id: str | None = None) -> list[dict]:
    if season_id is None:
        return db.fetch_all(conn, "SELECT team_id, abbreviation, team_name FROM teams ORDER BY abbreviation")
    require_season(conn, season_id)
    return db.fetch_all(conn, """
        SELECT t.team_id, t.abbreviation, t.team_name FROM teams t
        WHERE EXISTS (SELECT 1 FROM lineups l WHERE l.team_id = t.team_id AND l.season_id = %(s)s)
        ORDER BY t.abbreviation""", {"s": season_id})
