"""The season in progress: data cutoff, season-to-date windows and change detection.

Everything here is a pure function of (game-log payload, cutoff), shared by the refresh (which decides what
to request) and the ETL (which re-derives the same plan to check the files on disk). Nothing after the
cutoff is ever used:

* the cutoff is the last day whose games are certainly final: "yesterday" in US Eastern time, and only once
  it is past 06:00 ET (late West-coast games finish after midnight ET, dated the previous day);
* game-log rows after the cutoff, or without a result (WL), are dropped before anything else sees them;
* windows end at the last game played on or before the cutoff; each team's lineup requests end at that
  team's own last game (identical totals; unchanged teams reuse their cached files).
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .storage import result_set
from .windows import DateWindow, live_windows

NBA_TZ = ZoneInfo("America/New_York")
FINAL_AFTER_HOUR_ET = 6
# Box-score columns whose change means a game was corrected (or completed) since the last refresh.
FINGERPRINT_COLUMNS = ("GAME_ID", "GAME_DATE", "TEAM_ID", "MATCHUP", "WL", "MIN", "FGM", "FGA", "FG3M", "FG3A",
                       "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "PF", "PTS", "PLUS_MINUS")


def data_cutoff(now: datetime) -> date:
    """Last game date whose games are all final at `now` (timezone-aware)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (now.astimezone(NBA_TZ) - timedelta(days=1, hours=FINAL_AFTER_HOUR_ET)).date()


def completed_games(payload: dict, cutoff: date) -> pd.DataFrame:
    """Game-log rows of games played on or before the cutoff that have a result."""
    headers, rows = result_set(payload)
    df = pd.DataFrame(rows, columns=headers)
    if df.empty:
        return df
    d = pd.to_datetime(df.GAME_DATE).dt.date
    keep = (d <= cutoff) & df.WL.isin(["W", "L"])
    # a game counts only if BOTH team rows are complete
    complete = keep.groupby(df.GAME_ID).transform("sum") == 2
    return df[keep & complete].reset_index(drop=True)


def team_last_dates(windows: Mapping[str, DateWindow], games: pd.DataFrame) -> dict[tuple[str, int], date]:
    d = pd.to_datetime(games.GAME_DATE).dt.date
    out: dict[tuple[str, int], date] = {}
    for w in windows.values():
        inside = games[(d >= w.date_from) & (d <= w.date_to)]
        for tid, dates in pd.to_datetime(inside.GAME_DATE).dt.date.groupby(inside.TEAM_ID):
            out[(w.name, int(tid))] = max(dates)
    return out


def team_fingerprints(games: pd.DataFrame) -> dict[int, str]:
    """One hash per team over its completed games' box-score lines (order-independent)."""
    cols = [c for c in FINGERPRINT_COLUMNS if c in games.columns]
    out = {}
    for tid, g in games.groupby("TEAM_ID"):
        lines = sorted("|".join(str(v) for v in row) for row in g[cols].itertuples(index=False, name=None))
        out[int(tid)] = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return out


@dataclass(frozen=True)
class LivePlan:
    season: str
    cutoff: date
    games: pd.DataFrame                              # completed game-log rows up to the cutoff
    windows: dict[str, DateWindow]
    team_ids: list[int]
    team_last: dict[tuple[str, int], date]

    @property
    def last_game_date(self) -> date:
        return max(w.date_to for w in self.windows.values())

    @property
    def n_games(self) -> int:
        return int(self.games.GAME_ID.nunique())


def plan(season: str, gamelog_payload: dict, cutoff: date) -> LivePlan:
    games = completed_games(gamelog_payload, cutoff)
    if games.empty:
        raise ValueError(f"{season}: no completed games on or before {cutoff}")
    windows = live_windows(season, pd.to_datetime(games.GAME_DATE).dt.date)
    return LivePlan(season, cutoff, games, windows, sorted(int(t) for t in games.TEAM_ID.unique()),
                    team_last_dates(windows, games))
