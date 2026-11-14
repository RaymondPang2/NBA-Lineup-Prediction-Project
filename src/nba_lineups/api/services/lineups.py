"""Five-man lineups with pre- vs post-break ratings.

One SQL statement filters, sorts, counts (window function) and pages; a second fetches the players of the
lineups on the page only. Ratings come from v_lineup_window_ratings, the single SQL definition of a rating.
User input never reaches SQL text: values are bound parameters, and ORDER BY picks from a fixed whitelist.
"""
from __future__ import annotations

from collections import defaultdict

import psycopg

from .. import db
from ..errors import NotFound
from .common import PageParams, change, page, window

WINDOW_FIELDS = ("gp", "minutes", "poss", "opp_poss", "pts", "opp_pts", "off_rating", "def_rating", "net_rating")

SORTS = {   # public name -> SQL expression (never user text)
    "pre_poss": "least(pre.poss, pre.opp_poss)", "post_poss": "least(post.poss, post.opp_poss)",
    "pre_net": "pre.net_rating", "post_net": "post.net_rating", "net_change": "post.net_rating - pre.net_rating",
    "pre_off": "pre.off_rating", "pre_def": "pre.def_rating", "post_off": "post.off_rating",
    "post_def": "post.def_rating", "lineup_id": "l.lineup_id",
}


def _cols(alias: str) -> str:
    return ", ".join(f"{alias}.{c}{'::float8' if c in ('minutes', 'off_rating', 'def_rating', 'net_rating') else ''} "
                     f"AS {alias}_{c}" for c in WINDOW_FIELDS)


_BASE = f"""
    FROM lineups l
    JOIN teams t USING (team_id)
    LEFT JOIN v_lineup_window_ratings pre  ON pre.lineup_id  = l.lineup_id AND pre.window_type  = 'pre_asb'
    LEFT JOIN v_lineup_window_ratings post ON post.lineup_id = l.lineup_id AND post.window_type = 'post_asb'
    WHERE (%(season)s::text IS NULL OR l.season_id = %(season)s)
      AND (%(team)s::int IS NULL OR l.team_id = %(team)s)
      AND (cardinality(%(players)s::int[]) = 0 OR l.lineup_id IN (      -- uses the index on lineup_players(player_id)
           SELECT lp.lineup_id FROM lineup_players lp WHERE lp.player_id = ANY(%(players)s::int[])
           GROUP BY lp.lineup_id HAVING count(*) = cardinality(%(players)s::int[])))
      AND coalesce(least(pre.poss,  pre.opp_poss),  0) >= %(min_pre)s
      AND coalesce(least(post.poss, post.opp_poss), 0) >= %(min_post)s
"""
_SELECT = f"""SELECT l.lineup_id, l.season_id, l.team_id, t.abbreviation AS team_abbreviation,
                     {_cols('pre')}, {_cols('post')}"""


def players_of(conn: psycopg.Connection, lineup_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for r in db.fetch_all(conn, """
            SELECT lp.lineup_id, p.player_id, p.player_name FROM lineup_players lp JOIN players p USING (player_id)
            WHERE lp.lineup_id = ANY(%(ids)s) ORDER BY lp.lineup_id, p.player_name""", {"ids": lineup_ids}):
        out[r["lineup_id"]].append({"player_id": r["player_id"], "player_name": r["player_name"]})
    return out


def _shape(r: dict, players: list[dict], k: float | None) -> dict:
    pre, post = window(r, "pre", k, WINDOW_FIELDS), window(r, "post", k, WINDOW_FIELDS)
    return {"lineup_id": r["lineup_id"], "season_id": r["season_id"], "team_id": r["team_id"],
            "team_abbreviation": r["team_abbreviation"], "players": players,
            "pre_break": pre, "post_break": post, "change": change(pre, post, k)}


def list_lineups(conn: psycopg.Connection, *, season: str | None, team_id: int | None, player_ids: list[int],
                 min_pre_poss: int, min_post_poss: int, sort: str, order: str, p: PageParams,
                 k: float | None) -> dict:
    direction = "ASC" if order == "asc" else "DESC"
    params = {"season": season, "team": team_id, "players": list(player_ids), "min_pre": min_pre_poss,
              "min_post": min_post_poss, "limit": p.page_size, "offset": p.offset}
    rows = db.fetch_all(conn, f"""{_SELECT}, count(*) OVER () AS total {_BASE}
        ORDER BY {SORTS[sort]} {direction} NULLS LAST, l.lineup_id
        LIMIT %(limit)s OFFSET %(offset)s""", params)
    total = rows[0]["total"] if rows else (
        0 if p.offset == 0 else db.fetch_one(conn, f"SELECT count(*) AS n {_BASE}", params)["n"])
    names = players_of(conn, [r["lineup_id"] for r in rows])
    return page([_shape(r, names[r["lineup_id"]], k) for r in rows], total, p)


def get_lineup(conn: psycopg.Connection, lineup_id: int, k: float | None) -> dict:
    r = db.fetch_one(conn, f"""{_SELECT},
            tot.minutes::float8 AS tot_minutes, tot.poss AS tot_poss, tot.opp_poss AS tot_opp_poss,
            tot.pts AS tot_pts, tot.opp_pts AS tot_opp_pts, tot.off_rating::float8 AS tot_off_rating,
            tot.def_rating::float8 AS tot_def_rating, tot.net_rating::float8 AS tot_net_rating,
            (coalesce(pre.gp, 0) + coalesce(post.gp, 0)) AS tot_gp
        FROM lineups l
        JOIN teams t USING (team_id)
        LEFT JOIN v_lineup_window_ratings pre  ON pre.lineup_id  = l.lineup_id AND pre.window_type  = 'pre_asb'
        LEFT JOIN v_lineup_window_ratings post ON post.lineup_id = l.lineup_id AND post.window_type = 'post_asb'
        LEFT JOIN v_lineup_season_ratings tot ON tot.lineup_id = l.lineup_id
        WHERE l.lineup_id = %(id)s""", {"id": lineup_id})
    if r is None:
        raise NotFound(f"lineup {lineup_id} not found")
    out = _shape(r, players_of(conn, [lineup_id])[lineup_id], k)
    out["season_total"] = window(r, "tot", k, WINDOW_FIELDS)
    return out
