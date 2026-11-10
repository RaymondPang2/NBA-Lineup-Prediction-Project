"""Load: write a SilverSeason into PostgreSQL inside ONE transaction.

Strategy:
  * Dimensions (seasons, teams, players, lineups) are UPSERTED with
    INSERT ... ON CONFLICT, so surrogate keys like lineup_id stay stable.
  * Facts for the season are REPLACED: delete the season's windows (which
    cascade to its window-level stats), then bulk-insert fresh rows.
  * Bulk inserts use COPY into a temporary staging table, then INSERT ... SELECT
    with joins to resolve natural keys into surrogate keys. COPY streams rows
    and is far faster than one INSERT per row.
  * Error-level DQ checks run BEFORE commit. If one fails, the whole season
    rolls back, so readers never see half-loaded or inconsistent data
    (atomicity, the "A" in ACID).
Re-running a load is idempotent: same input -> same database state.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import psycopg

from .dq import ERROR, CheckResult, run_checks
from .transform import SilverSeason

log = logging.getLogger(__name__)

LWS_COLUMNS = ["n_source_rows", "gp", "seconds", "poss", "opp_poss_implied",
               "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "tov", "pts",
               "opp_fgm", "opp_fga", "opp_fg3m", "opp_fg3a", "opp_ftm", "opp_fta", "opp_oreb", "opp_dreb",
               "opp_tov", "opp_pts", "plus_minus", "nba_off_rating", "nba_def_rating", "nba_net_rating", "nba_pace"]


class DataQualityError(Exception):
    def __init__(self, season: str, failures: list[CheckResult]) -> None:
        super().__init__(f"{season}: {len(failures)} error-level DQ checks failed: "
                         + ", ".join(f"{f.name} ({f.violations})" for f in failures))
        self.failures = failures


def _rows(df: pd.DataFrame, columns: list[str]):
    """Yield plain Python tuples (NaN -> None, numpy scalars -> Python) for the driver."""
    sub = df[columns].astype(object)
    return sub.where(sub.notna(), None).itertuples(index=False, name=None)


def _copy(cur: psycopg.Cursor, table: str, df: pd.DataFrame, columns: list[str]) -> None:
    with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
        for row in _rows(df, columns):
            cp.write_row(row)


def _stage(cur: psycopg.Cursor, name: str, like: str, df: pd.DataFrame, columns: list[str],
           extra_columns: dict[str, str] | None = None) -> None:
    """Create a temp staging table shaped like (a subset of) a real table (+ extra columns), then COPY into it."""
    cur.execute(f"CREATE TEMP TABLE {name} ON COMMIT DROP AS SELECT {', '.join(columns)} FROM {like} WITH NO DATA")
    for col, sqltype in (extra_columns or {}).items():
        cur.execute(f"ALTER TABLE {name} ADD COLUMN {col} {sqltype}")
    _copy(cur, name, df, columns + list(extra_columns or {}))


def load_season(conn: psycopg.Connection, silver: SilverSeason) -> tuple[dict[str, int], list[CheckResult]]:
    """Load one season atomically. Returns (row counts, DQ results); raises DataQualityError on failure."""
    t, s = silver.tables, silver.season
    with conn.transaction(), conn.cursor() as cur:
        # --- dimensions: upsert
        cur.executemany("""
            INSERT INTO seasons (season_id, start_year, is_irregular, first_game_date, last_game_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (season_id) DO UPDATE SET start_year = EXCLUDED.start_year,
                is_irregular = EXCLUDED.is_irregular, first_game_date = EXCLUDED.first_game_date,
                last_game_date = EXCLUDED.last_game_date""",
            list(_rows(t["seasons"], ["season_id", "start_year", "is_irregular", "first_game_date", "last_game_date"])))
        cur.executemany("""
            INSERT INTO teams (team_id, abbreviation, team_name) VALUES (%s, %s, %s)
            ON CONFLICT (team_id) DO UPDATE SET abbreviation = EXCLUDED.abbreviation, team_name = EXCLUDED.team_name""",
            list(_rows(t["teams"], ["team_id", "abbreviation", "team_name"])))
        _stage(cur, "stg_players", "players", t["players"], ["player_id", "player_name"])
        cur.execute("""
            INSERT INTO players (player_id, player_name) SELECT player_id, player_name FROM stg_players
            ON CONFLICT (player_id) DO UPDATE SET player_name = EXCLUDED.player_name""")

        # --- facts: replace this season (CASCADE removes window-level stats)
        cur.execute("DELETE FROM stat_windows WHERE season_id = %s", (s,))
        cur.execute("DELETE FROM team_games WHERE season_id = %s", (s,))
        _copy(cur, "stat_windows", t["stat_windows"], ["season_id", "window_type", "date_from", "date_to"])
        _copy(cur, "team_games", t["team_games"],
              ["game_id", "team_id", "season_id", "game_date", "is_home", "won", "minutes", "pts", "plus_minus"])

        # --- lineups: upsert by natural key, keeping existing surrogate ids
        _stage(cur, "stg_lineups", "lineups", t["lineups"], ["season_id", "team_id", "player_key"])
        cur.execute("""
            INSERT INTO lineups (season_id, team_id, player_key)
            SELECT season_id, team_id, player_key FROM stg_lineups
            ON CONFLICT (season_id, team_id, player_key) DO NOTHING""")
        _stage(cur, "stg_lineup_players", "lineups", t["lineup_players"], ["season_id", "team_id", "player_key"],
               extra_columns={"player_id": "INT NOT NULL"})
        cur.execute("""
            INSERT INTO lineup_players (lineup_id, player_id)
            SELECT l.lineup_id, s.player_id
            FROM stg_lineup_players s JOIN lineups l USING (season_id, team_id, player_key)
            ON CONFLICT DO NOTHING""")

        # --- lineup window stats: stage with the natural key, then resolve lineup_id with a join
        cols = ", ".join(LWS_COLUMNS)
        cur.execute(f"""CREATE TEMP TABLE stg_lws ON COMMIT DROP AS
                        SELECT l.season_id, l.team_id, l.player_key, s.window_type, {", ".join("s." + c for c in LWS_COLUMNS)}
                        FROM lineup_window_stats s JOIN lineups l USING (lineup_id) WITH NO DATA""")
        _copy(cur, "stg_lws", t["lineup_window_stats"],
              ["season_id", "team_id", "player_key", "window_type"] + LWS_COLUMNS)
        cur.execute(f"""
            INSERT INTO lineup_window_stats (lineup_id, season_id, window_type, {cols})
            SELECT l.lineup_id, s.season_id, s.window_type, {", ".join("s." + c for c in LWS_COLUMNS)}
            FROM stg_lws s JOIN lineups l USING (season_id, team_id, player_key)""")

        _copy(cur, "player_window_stats", t["player_window_stats"],
              ["player_id", "season_id", "window_type", "last_team_id", "gp", "minutes", "poss",
               "off_rating", "def_rating", "net_rating", "usg_pct", "ts_pct"])
        _copy(cur, "team_window_stats", t["team_window_stats"],
              ["team_id", "season_id", "window_type", "gp", "minutes", "poss",
               "off_rating", "def_rating", "net_rating", "pace"])

        # lineups that no longer have any stats (would only happen if source data changed)
        cur.execute("""DELETE FROM lineups l WHERE l.season_id = %s AND NOT EXISTS
                       (SELECT 1 FROM lineup_window_stats s WHERE s.lineup_id = l.lineup_id)""", (s,))

        counts = {tbl: cur.execute(f"SELECT count(*) FROM {tbl} WHERE season_id = %s", (s,)).fetchone()[0]
                  for tbl in ("stat_windows", "team_games", "lineups", "lineup_window_stats",
                              "player_window_stats", "team_window_stats")}

        # --- quality gate: still inside the transaction.
        # Refresh planner statistics first: just-loaded rows aren't reflected in them yet, and stale
        # stats made the DQ joins pick nested loops (~80 s per season instead of < 1 s).
        cur.execute("ANALYZE lineups, lineup_players, lineup_window_stats, team_games, stat_windows, "
                    "player_window_stats, team_window_stats")
        results = run_checks(conn, s)
        failures = [r for r in results if r.severity == ERROR and not r.passed]
        if failures:
            raise DataQualityError(s, failures)   # exiting the `with` block via exception -> ROLLBACK
    return counts, results


def load_ingestion_log(conn: psycopg.Connection, manifest_path: Path) -> int:
    """Append manifest records not yet loaded. Idempotent thanks to the UNIQUE constraint."""
    if not manifest_path.exists():
        return 0
    records = [json.loads(line) for line in manifest_path.read_text().splitlines() if line.strip()]
    with conn.transaction(), conn.cursor() as cur:
        before = cur.execute("SELECT count(*) FROM ingestion_log").fetchone()[0]
        cur.executemany("""
            INSERT INTO ingestion_log (run_id, request_key, endpoint, season_id, window_type, measure, team_id,
                params, status, attempts, duration_s, row_count, raw_path, sha256, errors, warnings, recorded_at)
            VALUES (%(run_id)s, %(request_key)s, %(endpoint)s, %(season)s, %(window)s, %(measure)s, %(team_id)s,
                %(params)s, %(status)s, %(attempts)s, %(duration_s)s, %(row_count)s, %(raw_path)s, %(sha256)s,
                %(errors)s, %(warnings)s, %(recorded_at)s)
            ON CONFLICT (run_id, request_key, recorded_at) DO NOTHING""",
            [r | {k: json.dumps(r[k]) for k in ("params", "errors", "warnings")} for r in records])
        after = cur.execute("SELECT count(*) FROM ingestion_log").fetchone()[0]
    return after - before
