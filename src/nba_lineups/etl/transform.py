"""Transform: bronze DataFrames -> table-shaped silver DataFrames (pure pandas, no I/O).

Key cleaning decisions (see docs/database.md):
  * Name-variant splits: the API can return one lineup as several rows when a
    player's display name changed. Those rows are partial totals over different
    games, so they are SUMMED. Ratings are recomputed later from the sums and
    never averaged.
  * Measures are joined on (TEAM_ID, GROUP_ID, GROUP_NAME) BEFORE collapsing,
    so each partial row's NBA DEF_RATING can still be used to back out its
    opponent possessions.
  * Nothing is filtered out for being small (e.g. 0-possession lineups). Silver
    keeps every fact, and exclusions happen in analysis (gold) queries, where
    they are visible and adjustable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import metrics
from ..config import IRREGULAR_SEASONS
from ..ingest.validate import parse_group_id
from .extract import BronzeSeason

BASE_ADDITIVE = ["FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "TOV", "PTS", "PLUS_MINUS"]
OPP_ADDITIVE = ["OPP_FGM", "OPP_FGA", "OPP_FG3M", "OPP_FG3A", "OPP_FTM", "OPP_FTA",
                "OPP_OREB", "OPP_DREB", "OPP_TOV", "OPP_PTS"]
ROW_KEY = ["TEAM_ID", "GROUP_ID", "GROUP_NAME"]   # unique per source row (name variants differ in GROUP_NAME)
LINEUP_KEY = ["TEAM_ID", "GROUP_ID"]             # unique per lineup


class TransformError(Exception):
    pass


def player_key(group_id: str) -> str:
    """'-203484-203932-...-' -> '203484-203932-...' (numeric order, no outer dashes)."""
    return "-".join(str(p) for p in sorted(parse_group_id(group_id)))


def join_measures(adv: pd.DataFrame, base: pd.DataFrame, opp: pd.DataFrame) -> pd.DataFrame:
    """One row per source row with Advanced + Base + Opponent columns. Fails loudly on any mismatch."""
    a = adv[ROW_KEY + ["GP", "SUM_TIME_PLAYED", "POSS", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"]]
    b = base[ROW_KEY + ["SUM_TIME_PLAYED", "GP"] + BASE_ADDITIVE].rename(
        columns={"SUM_TIME_PLAYED": "STP_BASE", "GP": "GP_BASE"})
    o = opp[ROW_KEY + ["SUM_TIME_PLAYED"] + OPP_ADDITIVE].rename(columns={"SUM_TIME_PLAYED": "STP_OPP"})
    try:
        m = a.merge(b, on=ROW_KEY, how="outer", validate="one_to_one", indicator="_ab")
        m = m.merge(o, on=ROW_KEY, how="outer", validate="one_to_one", indicator="_abo")
    except pd.errors.MergeError as exc:
        raise TransformError(f"duplicate source rows within a measure: {exc}") from exc
    unmatched = (m._ab != "both") | (m._abo != "both")
    if unmatched.any():
        raise TransformError(f"{int(unmatched.sum())} lineup rows missing from at least one measure")
    if not ((m.SUM_TIME_PLAYED == m.STP_BASE) & (m.SUM_TIME_PLAYED == m.STP_OPP) & (m.GP == m.GP_BASE)).all():
        raise TransformError("time played or GP differs between measures for the same lineup")
    if not (m.PTS - m.OPP_PTS == m.PLUS_MINUS).all():
        raise TransformError("PTS - OPP_PTS != PLUS_MINUS")
    # Opponent possessions per source row (Phase 3, see docs/metrics.md):
    #   route A: 100 * OPP_PTS / DEF_RATING (unrounded; kept for validation; NaN if DEF_RATING is 0)
    #   route B: integer recovered from PACE; exact for every row with playing time
    #   canonical OPP_POSS = route B, else rounded route A (zero-time rows), else NaN (unknown)
    m["OPP_POSS_IMPLIED"] = np.where(m.DEF_RATING > 0, 100 * m.OPP_PTS / m.DEF_RATING.where(m.DEF_RATING > 0), np.nan)
    via_pace = metrics.opp_poss_from_pace(m.PACE, m.SUM_TIME_PLAYED / 3000, m.POSS)
    via_def = metrics.opp_poss_from_def_rating(m.OPP_PTS, m.DEF_RATING)
    m["OPP_POSS"] = via_pace.fillna(via_def)
    m["OPP_POSS_METHOD"] = np.select([via_pace.notna(), via_def.notna()], ["pace", "def_rating"], default=None)
    return m.drop(columns=["STP_BASE", "STP_OPP", "GP_BASE", "_ab", "_abo"])


def collapse_name_variants(rows: pd.DataFrame) -> pd.DataFrame:
    """Sum partial rows that share (TEAM_ID, GROUP_ID). Ratings survive only for single-row lineups."""
    additive = ["GP", "SUM_TIME_PLAYED", "POSS"] + BASE_ADDITIVE + OPP_ADDITIVE
    g = rows.groupby(LINEUP_KEY, sort=False)
    out = g[additive].sum().reset_index()
    out["N_SOURCE_ROWS"] = g.size().values
    # min_count=... makes the sum NaN if ANY partial row is undefined (an honest "unknown").
    out["OPP_POSS_IMPLIED"] = g.OPP_POSS_IMPLIED.sum(min_count=1).values
    out.loc[g.OPP_POSS_IMPLIED.apply(lambda s: s.isna().any()).values, "OPP_POSS_IMPLIED"] = np.nan
    # Canonical opponent possessions: a sum of exact integers, unknown if any partial row is unknown.
    out["OPP_POSS"] = g.OPP_POSS.agg(lambda s: s.sum() if s.notna().all() else np.nan).values
    methods = g.OPP_POSS_METHOD.agg(lambda s: None if s.isna().any() else (s.iloc[0] if s.nunique() == 1 else "mixed"))
    out["OPP_POSS_METHOD"] = methods.values
    single = out.N_SOURCE_ROWS == 1
    firsts = g[["OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"]].first().reset_index(drop=True)
    for col in firsts.columns:
        out[col] = firsts[col].where(single)
    return out


def as_int(df: pd.DataFrame, columns: list[str], what: str) -> pd.DataFrame:
    """Cast count columns to int64, but only if that loses nothing (the API sends some counts as floats, e.g. 3.0)."""
    for c in columns:
        values = df[c]
        if values.isna().any() or not (values % 1 == 0).all():
            raise TransformError(f"{what}.{c}: non-integer or missing values in a count column")
        df[c] = values.astype("int64")
    return df


@dataclass
class SilverSeason:
    season: str
    tables: dict[str, pd.DataFrame]


def _lineup_window_frame(bronze: BronzeSeason, window: str) -> pd.DataFrame:
    rows = join_measures(*(bronze.lineups[(window, m)] for m in ("Advanced", "Base", "Opponent")))
    lw = collapse_name_variants(rows)
    lw["player_key"] = lw.GROUP_ID.map(player_key)
    lw["season_id"], lw["window_type"] = bronze.season, window
    lw["seconds"] = lw.SUM_TIME_PLAYED / 50   # 5 players x deciseconds -> lineup seconds
    rename = {c: c.lower() for c in BASE_ADDITIVE + OPP_ADDITIVE + ["GP", "POSS"]}
    rename |= {"TEAM_ID": "team_id", "N_SOURCE_ROWS": "n_source_rows", "OPP_POSS_IMPLIED": "opp_poss_implied",
               "OPP_POSS": "opp_poss", "OPP_POSS_METHOD": "opp_poss_method",
               "OFF_RATING": "nba_off_rating", "DEF_RATING": "nba_def_rating", "NET_RATING": "nba_net_rating",
               "PACE": "nba_pace"}
    out = lw.rename(columns=rename).drop(columns=["GROUP_ID", "SUM_TIME_PLAYED"])
    counts = ["n_source_rows", "gp", "poss", "plus_minus"] + [c.lower() for c in BASE_ADDITIVE + OPP_ADDITIVE]
    out["opp_poss"] = out.opp_poss.astype("Int64")   # nullable integer: NaN -> <NA> -> SQL NULL
    return as_int(out, counts, f"lineup_window_stats[{window}]")


def transform_season(bronze: BronzeSeason) -> SilverSeason:
    s = bronze.season
    gl = bronze.gamelog.copy()
    gl["game_date"] = pd.to_datetime(gl.GAME_DATE).dt.date

    seasons = pd.DataFrame([{
        "season_id": s, "start_year": int(s[:4]), "is_irregular": s in IRREGULAR_SEASONS,
        "first_game_date": gl.game_date.min(), "last_game_date": gl.game_date.max(),
    }])
    windows = pd.DataFrame([{"season_id": s, "window_type": w.name, "date_from": w.date_from, "date_to": w.date_to}
                            for w in bronze.windows.values()])

    abbrev = gl.groupby("TEAM_ID").TEAM_ABBREVIATION.last()
    names = pd.concat(bronze.team_stats.values()).groupby("TEAM_ID").TEAM_NAME.last()
    teams = pd.DataFrame({"team_id": abbrev.index, "abbreviation": abbrev.values,
                          "team_name": names.reindex(abbrev.index).values})

    # 'BOS vs. NYK' = home, 'BOS @ NYK' = away. Neutral-site games (NBA Cup semifinals, international
    # games) list BOTH teams with '@', so neither is home: is_home = NULL (unknown/not applicable).
    home = gl.MATCHUP.str.contains(" vs. ", regex=False)
    neutral = home.groupby(gl.GAME_ID).transform("sum") == 0
    team_games = pd.DataFrame({
        "game_id": gl.GAME_ID, "team_id": gl.TEAM_ID, "season_id": s, "game_date": gl.game_date,
        "is_home": home.astype(object).where(~neutral, None), "won": gl.WL.eq("W"),
        "minutes": gl.MIN, "pts": gl.PTS, "plus_minus": gl.PLUS_MINUS,
    })

    # Players: post window last so the most recent display name wins.
    pstats = pd.concat([bronze.player_stats[w].assign(window_type=w) for w in ("pre_asb", "post_asb")], ignore_index=True)
    players = (pstats[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates("PLAYER_ID", keep="last")
               .rename(columns={"PLAYER_ID": "player_id", "PLAYER_NAME": "player_name"}))
    player_window = pd.DataFrame({
        "player_id": pstats.PLAYER_ID, "season_id": s, "window_type": pstats.window_type,
        "last_team_id": pstats.TEAM_ID.where(pstats.TEAM_ID != 0), "gp": pstats.GP, "minutes": pstats.MIN,
        "poss": pstats.POSS, "off_rating": pstats.OFF_RATING, "def_rating": pstats.DEF_RATING,
        "net_rating": pstats.NET_RATING, "usg_pct": pstats.USG_PCT, "ts_pct": pstats.TS_PCT,
    })
    tstats = pd.concat([bronze.team_stats[w].assign(window_type=w) for w in ("pre_asb", "post_asb")], ignore_index=True)
    team_window = pd.DataFrame({
        "team_id": tstats.TEAM_ID, "season_id": s, "window_type": tstats.window_type, "gp": tstats.GP,
        "minutes": tstats.MIN, "poss": tstats.POSS, "off_rating": tstats.OFF_RATING,
        "def_rating": tstats.DEF_RATING, "net_rating": tstats.NET_RATING, "pace": tstats.PACE,
    })

    as_int(team_games, ["team_id", "minutes", "pts", "plus_minus"], "team_games")
    as_int(player_window, ["gp", "poss"], "player_window_stats")
    as_int(team_window, ["gp", "poss"], "team_window_stats")

    lineup_window = pd.concat([_lineup_window_frame(bronze, w) for w in ("pre_asb", "post_asb")], ignore_index=True)
    lineups = lineup_window[["season_id", "team_id", "player_key"]].drop_duplicates(ignore_index=True)
    lineup_players = lineups.assign(player_id=lineups.player_key.str.split("-")).explode("player_id")
    lineup_players["player_id"] = lineup_players.player_id.astype(int)

    unknown = set(lineup_players.player_id) - set(players.player_id)
    if unknown:
        raise TransformError(f"{s}: {len(unknown)} lineup players absent from player stats (e.g. {sorted(unknown)[:3]})")

    return SilverSeason(s, {
        "seasons": seasons, "stat_windows": windows, "teams": teams, "players": players,
        "team_games": team_games, "lineups": lineups, "lineup_players": lineup_players,
        "lineup_window_stats": lineup_window, "player_window_stats": player_window,
        "team_window_stats": team_window,
    })
