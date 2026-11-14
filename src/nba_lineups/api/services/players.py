"""Player statistics per (season, team), pre vs post break.

On-court and on/off numbers come from the lineup feed (v_player_window_on_court, v_player_window_on_off), so a
traded player gets one row per team. Usage comes from the player endpoint, which combines a traded player's
teams into one row per season and window. `player_window_stats.last_team_id` is never selected: the API fills
it with the player's LATEST team even under a pre-break date filter (Phase 4 leakage finding).
"""
from __future__ import annotations

import psycopg

from .. import db
from ..errors import NotFound
from .common import PageParams, like_pattern, page, window

WINDOW_FIELDS = ("n_lineups", "minutes", "poss", "opp_poss", "off_rating", "def_rating", "net_rating",
                 "off_court_net_rating", "on_off_net")
USAGE_FIELDS = ("gp", "minutes", "usg_pct", "ts_pct")

SORTS = {"pre_minutes": "pre.minutes", "post_minutes": "post.minutes", "pre_net": "pre.net_rating",
         "post_net": "post.net_rating", "pre_on_off": "pre.on_off_net", "post_on_off": "post.on_off_net",
         "name": "p.player_name"}


def _w(alias: str) -> str:
    return ", ".join(f"{alias}.{c} AS {alias}_{c}" for c in WINDOW_FIELDS)


def _u(alias: str) -> str:
    return ", ".join(f"{alias}.{c}::float8 AS {alias}_{c}" if c != "gp" else f"{alias}.gp AS {alias}_gp"
                     for c in USAGE_FIELDS)


def _query(where: str, order: str = "p.player_name, k.season_id, t.abbreviation", tail: str = "") -> str:
    return f"""
    WITH oc AS (
        SELECT season_id, window_type, team_id, player_id, n_lineups, minutes::float8 AS minutes, poss, opp_poss,
               off_rating::float8 AS off_rating, def_rating::float8 AS def_rating, net_rating::float8 AS net_rating
        FROM v_player_window_on_court WHERE {where}),
    oo AS (
        SELECT season_id, window_type, team_id, player_id, off_net_rating::float8 AS off_court_net_rating,
               on_off_net::float8 AS on_off_net
        FROM v_player_window_on_off WHERE {where}),
    w AS (SELECT oc.*, oo.off_court_net_rating, oo.on_off_net
          FROM oc LEFT JOIN oo USING (season_id, window_type, team_id, player_id)),
    k AS (SELECT DISTINCT season_id, team_id, player_id FROM w)
    SELECT k.season_id, k.team_id, k.player_id, p.player_name, t.abbreviation AS team_abbreviation,
           {_w('pre')}, {_w('post')}, {_u('upre')}, {_u('upost')}, count(*) OVER () AS total
    FROM k
    JOIN players p USING (player_id)
    JOIN teams t USING (team_id)
    LEFT JOIN w pre  ON (pre.season_id, pre.team_id, pre.player_id, pre.window_type)
                      = (k.season_id, k.team_id, k.player_id, 'pre_asb')
    LEFT JOIN w post ON (post.season_id, post.team_id, post.player_id, post.window_type)
                      = (k.season_id, k.team_id, k.player_id, 'post_asb')
    LEFT JOIN player_window_stats upre  ON (upre.player_id, upre.season_id, upre.window_type)
                                         = (k.player_id, k.season_id, 'pre_asb')
    LEFT JOIN player_window_stats upost ON (upost.player_id, upost.season_id, upost.window_type)
                                         = (k.player_id, k.season_id, 'post_asb')
    WHERE (%(search)s::text IS NULL OR p.player_name ILIKE %(search)s)
      AND coalesce(pre.minutes, 0) >= %(min_pre_minutes)s
    ORDER BY {order} {tail}"""


def _shape(r: dict) -> dict:
    return {"player_id": r["player_id"], "player_name": r["player_name"], "season_id": r["season_id"],
            "team_id": r["team_id"], "team_abbreviation": r["team_abbreviation"],
            "pre_break": window(r, "pre", None, WINDOW_FIELDS), "post_break": window(r, "post", None, WINDOW_FIELDS),
            "usage_pre_break": _usage(r, "upre"), "usage_post_break": _usage(r, "upost")}


def _usage(r: dict, prefix: str) -> dict | None:
    return None if r.get(f"{prefix}_gp") is None else {f: r[f"{prefix}_{f}"] for f in USAGE_FIELDS}


def list_players(conn: psycopg.Connection, *, season: str, team_id: int | None, search: str | None,
                 min_pre_minutes: float, sort: str, order: str, p: PageParams) -> dict:
    where = "season_id = %(season)s AND (%(team)s::int IS NULL OR team_id = %(team)s)"
    direction = "ASC" if order == "asc" else "DESC"
    params = {"season": season, "team": team_id, "search": like_pattern(search) if search else None,
              "min_pre_minutes": min_pre_minutes, "limit": p.page_size, "offset": p.offset}
    rows = db.fetch_all(conn, _query(where, f"{SORTS[sort]} {direction} NULLS LAST, k.player_id, k.team_id",
                                     "LIMIT %(limit)s OFFSET %(offset)s"), params)
    total = rows[0]["total"] if rows else 0
    if not rows and p.offset:
        total = len(db.fetch_all(conn, _query(where), params))
    return page([_shape(r) for r in rows], total, p)


def get_player(conn: psycopg.Connection, player_id: int, season: str | None) -> dict:
    name = db.fetch_one(conn, "SELECT player_name FROM players WHERE player_id = %(p)s", {"p": player_id})
    if name is None:
        raise NotFound(f"player {player_id} not found")
    seasons = [season] if season else [r["season_id"] for r in db.fetch_all(conn, """
        SELECT DISTINCT l.season_id FROM lineup_players lp JOIN lineups l USING (lineup_id)
        WHERE lp.player_id = %(p)s""", {"p": player_id})]
    # Filter the views by season AND team: the on/off view needs whole-team totals, so restricting to the
    # player's own team-seasons keeps the query small.
    where = ("season_id = ANY(%(seasons)s) AND (season_id, team_id) IN (SELECT l.season_id, l.team_id FROM "
             "lineup_players lp JOIN lineups l USING (lineup_id) WHERE lp.player_id = %(p)s) AND player_id = %(p)s")
    rows = db.fetch_all(conn, _query(where, "k.season_id, t.abbreviation"),
                        {"seasons": seasons, "p": player_id, "search": None, "min_pre_minutes": 0})
    return {"player_id": player_id, "player_name": name["player_name"], "seasons": [_shape(r) for r in rows]}
