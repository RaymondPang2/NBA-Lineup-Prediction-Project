"""Phase 4: home/road lineup splits (bronze -> silver), loaded in one transaction per season.

The split files come from the same per-team LeagueDashLineups requests as the main
window totals, with an added Location filter. They reuse the main transform
(join_measures, collapse_name_variants), so opponent possessions and name-variant
merging follow exactly the same rules.

Checks (error-level; any failure rolls the season's splits back):
  * home + road equal the window total for every lineup: the split-half analysis relies on the
    two halves partitioning the same possessions. Seasons with neutral-site games would need a
    different rule and are refused (the development seasons have none).
  * every un-merged split row reproduces NBA's published ORtg / DRtg / net rating.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg

from ..ingest.pipeline import gamelog_dates_and_teams, read_windows
from ..ingest.specs import LINEUP_MEASURES, gamelog_spec, location_split_specs
from ..ingest.storage import read_json, result_set
from .extract import ExtractError
from .load import _copy
from .transform import as_int, collapse_name_variants, join_measures, player_key

SPLIT_WINDOW = "pre_asb"
SPLIT_COLUMNS = ["n_source_rows", "gp", "seconds", "poss", "opp_poss", "opp_poss_method", "pts", "opp_pts",
                 "plus_minus", "nba_off_rating", "nba_def_rating", "nba_net_rating"]


def has_location_splits(raw_dir: Path, season: str) -> bool:
    windows = read_windows(raw_dir, season)
    gl = read_json(gamelog_spec(season).cache_path(raw_dir))
    if windows is None or gl is None:
        return False
    _, team_ids = gamelog_dates_and_teams(gl)
    return all(s.cache_path(raw_dir).exists() for s in location_split_specs(season, windows[SPLIT_WINDOW], team_ids))


def transform_location_splits(raw_dir: Path, season: str) -> pd.DataFrame:
    """One row per (lineup, split) with the same columns as lineup_window_stats (subset)."""
    windows = read_windows(raw_dir, season)
    gl = read_json(gamelog_spec(season).cache_path(raw_dir))
    if windows is None or gl is None:
        raise ExtractError(f"{season}: season not ingested")
    _, team_ids = gamelog_dates_and_teams(gl)
    specs = location_split_specs(season, windows[SPLIT_WINDOW], team_ids)
    missing = [s.key for s in specs if not s.cache_path(raw_dir).exists()]
    if missing:
        raise ExtractError(f"{season}: {len(missing)} location-split files missing (e.g. {missing[0]})")

    def frame(spec):
        headers, rows = result_set(read_json(spec.cache_path(raw_dir)))
        return pd.DataFrame(rows, columns=headers)

    out = []
    for split in ("home", "road"):
        by_measure = {m: pd.concat([frame(s) for s in specs if s.split == split and s.measure == m], ignore_index=True)
                      for m in LINEUP_MEASURES}
        lw = collapse_name_variants(join_measures(*(by_measure[m] for m in LINEUP_MEASURES)))
        lw = lw.assign(split=split, player_key=lw.GROUP_ID.map(player_key), seconds=lw.SUM_TIME_PLAYED / 50)
        out.append(lw)
    df = pd.concat(out, ignore_index=True).rename(columns={
        "TEAM_ID": "team_id", "N_SOURCE_ROWS": "n_source_rows", "GP": "gp", "POSS": "poss", "OPP_POSS": "opp_poss",
        "OPP_POSS_METHOD": "opp_poss_method", "PTS": "pts", "OPP_PTS": "opp_pts", "PLUS_MINUS": "plus_minus",
        "OFF_RATING": "nba_off_rating", "DEF_RATING": "nba_def_rating", "NET_RATING": "nba_net_rating"})
    df = df.assign(season_id=season, window_type=SPLIT_WINDOW)
    df["opp_poss"] = df.opp_poss.astype("Int64")
    as_int(df, ["n_source_rows", "gp", "poss", "pts", "opp_pts", "plus_minus"], "lineup_split_stats")
    return df[["season_id", "team_id", "player_key", "window_type", "split"] + SPLIT_COLUMNS]


# Violating rows for each reconciliation rule (empty = pass).
_RECONCILE = """
WITH s AS (
    SELECT lineup_id, sum(poss) AS poss, sum(opp_poss) AS opp_poss, sum(pts) AS pts, sum(opp_pts) AS opp_pts,
           sum(seconds) AS seconds, count(*) FILTER (WHERE opp_poss IS NULL) AS unknown_opp
    FROM lineup_split_stats WHERE season_id = %(season)s GROUP BY lineup_id)
SELECT w.lineup_id
FROM lineup_window_stats w LEFT JOIN s USING (lineup_id)
WHERE w.season_id = %(season)s AND w.window_type = 'pre_asb' AND w.seconds > 0
  AND (s.lineup_id IS NULL OR s.poss <> w.poss OR s.pts <> w.pts OR s.opp_pts <> w.opp_pts
       OR s.seconds <> w.seconds OR (s.unknown_opp = 0 AND s.opp_poss <> w.opp_poss))
"""


# Un-merged split rows must reproduce NBA's published split ratings (half-up rounding, as in Phase 3).
_RATINGS = """
SELECT lineup_id FROM lineup_split_stats
WHERE season_id = %(season)s AND n_source_rows = 1 AND poss > 0 AND opp_poss > 0
  AND (round(per100(pts, poss), 1) <> nba_off_rating OR round(per100(opp_pts, opp_poss), 1) <> nba_def_rating
       OR round(per100(pts, poss) - per100(opp_pts, opp_poss), 1) <> nba_net_rating)
"""


class SplitReconciliationError(Exception):
    pass


def load_location_splits(conn: psycopg.Connection, season: str, df: pd.DataFrame) -> dict[str, int]:
    """Replace the season's split rows atomically; roll back unless home + road == window totals."""
    with conn.transaction(), conn.cursor() as cur:
        neutral = cur.execute("SELECT count(*) FROM team_games WHERE season_id = %s AND is_home IS NULL",
                              (season,)).fetchone()[0]
        if neutral:
            raise SplitReconciliationError(f"{season}: {neutral} neutral-site team-games; home/road do not partition")
        cur.execute("DELETE FROM lineup_split_stats WHERE season_id = %s", (season,))
        cur.execute(f"""CREATE TEMP TABLE stg_lss ON COMMIT DROP AS
                        SELECT l.season_id, l.team_id, l.player_key, s.window_type, s.split, {", ".join("s." + c for c in SPLIT_COLUMNS)}
                        FROM lineup_split_stats s JOIN lineups l USING (lineup_id) WITH NO DATA""")
        _copy(cur, "stg_lss", df, ["season_id", "team_id", "player_key", "window_type", "split"] + SPLIT_COLUMNS)
        unmatched = cur.execute("""SELECT count(*) FROM stg_lss s LEFT JOIN lineups l USING (season_id, team_id, player_key)
                                   WHERE l.lineup_id IS NULL""").fetchone()[0]
        if unmatched:
            raise SplitReconciliationError(f"{season}: {unmatched} split rows for lineups absent from the window table")
        cur.execute(f"""INSERT INTO lineup_split_stats (lineup_id, season_id, window_type, split, {", ".join(SPLIT_COLUMNS)})
                        SELECT l.lineup_id, s.season_id, s.window_type, s.split, {", ".join("s." + c for c in SPLIT_COLUMNS)}
                        FROM stg_lss s JOIN lineups l USING (season_id, team_id, player_key)""")
        cur.execute("ANALYZE lineup_split_stats")
        bad = cur.execute(_RECONCILE, {"season": season}).fetchall()
        if bad:
            raise SplitReconciliationError(f"{season}: {len(bad)} lineups where home + road != window total "
                                           f"(e.g. lineup_id {bad[0][0]})")
        bad = cur.execute(_RATINGS, {"season": season}).fetchall()
        if bad:
            raise SplitReconciliationError(f"{season}: {len(bad)} split rows do not reproduce NBA's ratings")
        n = cur.execute("SELECT count(*) FROM lineup_split_stats WHERE season_id = %s", (season,)).fetchone()[0]
    return {"lineup_split_stats": n}
