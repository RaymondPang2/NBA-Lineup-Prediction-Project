"""Is the season-in-progress data current or stale? Read-only; used by the API's /data-status.

The data is CURRENT when its cutoff has reached the cutoff that the most recent scheduled refresh (07:00
America/Toronto, with a grace period for the run itself) would have produced. Otherwise it is STALE: the
scheduled refresh has not succeeded yet (Mac asleep or off, database or NBA API down, or the job disabled).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from ..config import CURRENT_SEASON
from ..ingest.live import data_cutoff
from .schedule import latest_slot

GRACE = timedelta(hours=2)


def expected_cutoff(now: datetime) -> date:
    return data_cutoff(latest_slot(now - GRACE))


def status(conn: psycopg.Connection, now: datetime, season: str = CURRENT_SEASON) -> dict:
    out = {"season_id": season, "data_version": None, "last_updated_at": None, "last_loaded_at": None,
           "data_cutoff": None, "last_game_date": None, "games_total": None,
           "expected_cutoff": expected_cutoff(now), "freshness": "unknown", "stale_reason": None,
           "last_attempt": None, "refresh_command": "python -m nba_lineups.refresh"}
    with conn.cursor(row_factory=dict_row) as cur:
        if cur.execute("SELECT to_regclass('data_refreshes') IS NOT NULL AS ok").fetchone()["ok"] is False:
            out["stale_reason"] = "no refresh has run yet"
            return out
        ok = cur.execute("""
            SELECT refresh_id, status, finished_at, data_cutoff, last_game_date, games_total
            FROM data_refreshes WHERE season_id = %(s)s AND status IN ('success', 'no_change')
            ORDER BY refresh_id DESC LIMIT 1""", {"s": season}).fetchone()
        loaded = cur.execute("""
            SELECT refresh_id, finished_at FROM data_refreshes
            WHERE season_id = %(s)s AND status = 'success' ORDER BY refresh_id DESC LIMIT 1""", {"s": season}).fetchone()
        last = cur.execute("""
            SELECT status, trigger, started_at, finished_at, message FROM data_refreshes
            WHERE season_id = %(s)s ORDER BY refresh_id DESC LIMIT 1""", {"s": season}).fetchone()
    if last:
        out["last_attempt"] = {**last, "message": (last["message"] or "").splitlines()[0][:300] or None}
    if loaded:
        out["data_version"], out["last_loaded_at"] = loaded["refresh_id"], loaded["finished_at"]
    if not ok:
        out["stale_reason"] = "no successful refresh yet"
        return out
    out |= {"last_updated_at": ok["finished_at"], "data_cutoff": ok["data_cutoff"],
            "last_game_date": ok["last_game_date"], "games_total": ok["games_total"]}
    if ok["data_cutoff"] >= out["expected_cutoff"]:
        out["freshness"] = "current"
    else:
        out["freshness"] = "stale"
        failed = last and last["status"] == "failed"
        out["stale_reason"] = (f"data runs through {ok['data_cutoff']}, expected through {out['expected_cutoff']}; "
                               + ("the last refresh attempt failed" if failed else
                                  "the scheduled 07:00 refresh has not run yet (Mac asleep or job disabled?)"))
    return out


def data_version(conn: psycopg.Connection, season: str) -> int:
    """Id of the last refresh that LOADED data for the season (0 if none): bumps when its data changes."""
    if conn.execute("SELECT to_regclass('data_refreshes') IS NULL").fetchone()[0]:
        return 0
    return conn.execute("SELECT coalesce(max(refresh_id), 0) FROM data_refreshes "
                        "WHERE season_id = %s AND status = 'success'", (season,)).fetchone()[0]
