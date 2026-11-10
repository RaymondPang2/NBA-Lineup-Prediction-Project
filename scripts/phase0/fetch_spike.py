"""Phase 0 data spike -- FETCH step (exploratory, not production code).

Pulls a small sample from stats.nba.com via nba_api and caches every raw
response as JSON under data/raw/phase0/. Re-running the script reuses the
cache, so we only hit the API once per request.

Phase 1 will replace this with a proper, tested ingestion module.

Usage:  .venv/bin/python scripts/phase0/fetch_spike.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashlineups, leaguegamelog
from nba_api.stats.static import teams as static_teams

RAW_DIR = Path("data/raw/phase0")
SEASONS = ["2022-23", "2023-24"]
SLEEP_SECONDS = 1.0  # be polite: stats.nba.com throttles aggressive clients


def cached_call(name: str, fn) -> dict:
    """Return the raw JSON for a request, fetching it only if not cached."""
    path = RAW_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(3):
        try:
            payload = fn().get_dict()
            break
        except Exception as exc:  # network errors, timeouts
            print(f"  retry {attempt + 1} for {name}: {exc}")
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"failed: {name}")
    path.write_text(json.dumps(payload))
    time.sleep(SLEEP_SECONDS)
    return payload


def to_df(payload: dict, idx: int = 0) -> pd.DataFrame:
    rs = payload["resultSets"][idx]
    return pd.DataFrame(rs["rowSet"], columns=rs["headers"])


def nba_date(d: pd.Timestamp) -> str:
    return d.strftime("%m/%d/%Y")  # format the stats API expects


def find_windows(season: str) -> dict[str, tuple[str, str]]:
    """Derive pre/post All-Star-break windows from actual game dates.

    The break is the largest gap between consecutive game dates in Feb,
    so we don't rely on hard-coded (possibly mis-remembered) dates.
    """
    log = to_df(cached_call(
        f"gamelog_{season}",
        lambda: leaguegamelog.LeagueGameLog(season=season, player_or_team_abbreviation="T", timeout=60),
    ))
    dates = pd.Series(sorted(pd.to_datetime(log["GAME_DATE"]).unique()))
    feb = dates[dates.dt.month == 2].reset_index(drop=True)
    gaps = feb.diff()
    i = gaps.idxmax()
    last_pre, first_post = feb[i - 1], feb[i]
    return {
        "full": (nba_date(dates.min()), nba_date(dates.max())),
        "pre_asb": (nba_date(dates.min()), nba_date(last_pre)),
        "post_asb": (nba_date(first_post), nba_date(dates.max())),
    }


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    team_ids = [t["id"] for t in static_teams.get_teams()]
    windows_by_season = {}

    for season in SEASONS:
        windows = find_windows(season)
        windows_by_season[season] = windows
        print(season, windows)

        # 1) League-wide call with no team filter (to measure the row cap)
        cached_call(f"lineups_{season}_league_full_adv", lambda: leaguedashlineups.LeagueDashLineups(
            season=season, group_quantity=5, measure_type_detailed_defense="Advanced",
            per_mode_detailed="Totals", timeout=60))

        # 2) Per-team calls for each window (workaround for the cap)
        for w, (d_from, d_to) in windows.items():
            for n, tid in enumerate(team_ids, 1):
                name = f"lineups_{season}_{tid}_{w}_adv"
                print(f"  {name} ({n}/30)", end="\r")
                cached_call(name, lambda: leaguedashlineups.LeagueDashLineups(
                    season=season, group_quantity=5, measure_type_detailed_defense="Advanced",
                    per_mode_detailed="Totals", team_id_nullable=tid,
                    date_from_nullable=d_from, date_to_nullable=d_to, timeout=60))
            print()

    # 3) Base (counting stats) + Opponent measures for one team/season, to test
    #    whether we can recompute possessions and ratings ourselves.
    for measure in ["Base", "Opponent"]:
        cached_call(f"lineups_2023-24_1610612743_full_{measure.lower()}", lambda: leaguedashlineups.LeagueDashLineups(
            season="2023-24", group_quantity=5, measure_type_detailed_defense=measure,
            per_mode_detailed="Totals", team_id_nullable=1610612743, timeout=60))

    (RAW_DIR / "windows.json").write_text(json.dumps(windows_by_season, indent=2))
    print("done")


if __name__ == "__main__":
    main()
