"""Extract: read one season's bronze files into DataFrames.

Completeness is checked against the same RequestSpec plan the ingester uses,
so "what we expect to have" is defined in exactly one place.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ..ingest.pipeline import gamelog_dates_and_teams
from ..ingest.specs import LINEUP_MEASURES, LINEUPS, PLAYERS, TEAMS, gamelog_spec, season_specs
from ..ingest.storage import read_json, result_set
from ..ingest.windows import WINDOW_NAMES, DateWindow


class ExtractError(Exception):
    pass


@dataclass
class BronzeSeason:
    season: str
    windows: dict[str, DateWindow]
    gamelog: pd.DataFrame
    team_stats: dict[str, pd.DataFrame]            # window -> frame
    player_stats: dict[str, pd.DataFrame]          # window -> frame
    lineups: dict[tuple[str, str], pd.DataFrame]   # (window, measure) -> all 30 teams concatenated


def _frame(payload: dict) -> pd.DataFrame:
    headers, rows = result_set(payload)
    return pd.DataFrame(rows, columns=headers)


def read_season(raw_dir: Path, season: str) -> BronzeSeason:
    gl_payload = read_json(gamelog_spec(season).cache_path(raw_dir))
    windows_file = raw_dir / season / "windows.json"
    if gl_payload is None or not windows_file.exists():
        raise ExtractError(f"{season}: game log or windows.json missing; run ingestion first")
    windows = {k: DateWindow(v["name"], date.fromisoformat(v["date_from"]), date.fromisoformat(v["date_to"]))
               for k, v in json.loads(windows_file.read_text()).items()}
    _, team_ids = gamelog_dates_and_teams(gl_payload)

    specs = season_specs(season, windows, team_ids)
    missing = [s.key for s in specs if not s.cache_path(raw_dir).exists()]
    if missing:
        raise ExtractError(f"{season}: {len(missing)} raw files missing (e.g. {missing[0]}); rerun ingestion")

    frames = {s: _frame(read_json(s.cache_path(raw_dir))) for s in specs}
    by = lambda endpoint, window: next(f for s, f in frames.items() if s.endpoint == endpoint and s.window == window)
    lineups = {(w, m): pd.concat([f for s, f in frames.items()
                                  if s.endpoint == LINEUPS and s.window == w and s.measure == m], ignore_index=True)
               for w in WINDOW_NAMES for m in LINEUP_MEASURES}
    return BronzeSeason(
        season=season, windows=windows, gamelog=_frame(gl_payload),
        team_stats={w: by(TEAMS, w) for w in WINDOW_NAMES},
        player_stats={w: by(PLAYERS, w) for w in WINDOW_NAMES},
        lineups=lineups,
    )
