"""Immutable descriptions of API requests.

Separating "what to request" (a RequestSpec) from "how to request it" (the
transport) means the request plan can be built, counted, and tested without
touching the network.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .windows import DateWindow

GAMELOG = "leaguegamelog"
LINEUPS = "leaguedashlineups"
PLAYERS = "leaguedashplayerstats"
TEAMS = "leaguedashteamstats"

# Advanced: POSS, ratings, PACE. Base: our own counting stats (PTS, FGA, FTA,
# OREB, TOV). Opponent: OPP_PTS etc., needed for defensive rating.
LINEUP_MEASURES = ("Advanced", "Base", "Opponent")
REGULAR_SEASON = "Regular Season"


@dataclass(frozen=True)
class RequestSpec:
    endpoint: str
    season: str
    params: tuple[tuple[str, Any], ...]  # sorted, so equal requests compare equal and are hashable
    window: str | None = None
    measure: str | None = None
    team_id: int | None = None

    @classmethod
    def make(cls, endpoint: str, season: str, params: Mapping[str, Any], **meta: Any) -> RequestSpec:
        return cls(endpoint, season, tuple(sorted(params.items())), **meta)

    @property
    def kwargs(self) -> dict[str, Any]:
        """Keyword arguments for the nba_api endpoint class."""
        return dict(self.params)

    @property
    def key(self) -> str:
        """Stable, human-readable identifier; also the cache path."""
        parts = [self.season, self.endpoint]
        if self.window:
            parts.append(self.window)
        if self.measure:
            parts.append(self.measure.lower())
        parts.append(f"team_{self.team_id}" if self.team_id else "league")
        return "/".join(parts)

    def cache_path(self, raw_dir: Path) -> Path:
        return raw_dir / f"{self.key}.json"


def gamelog_spec(season: str) -> RequestSpec:
    return RequestSpec.make(GAMELOG, season, {
        "season": season,
        "season_type_all_star": REGULAR_SEASON,
        "player_or_team_abbreviation": "T",
    })


def _dashboard_params(season: str, window: DateWindow, measure: str) -> dict[str, Any]:
    return {
        "season": season,
        "season_type_all_star": REGULAR_SEASON,
        "measure_type_detailed_defense": measure,
        "per_mode_detailed": "Totals",  # totals add across windows; per-game/per-100 values don't
        "date_from_nullable": window.nba_from,
        "date_to_nullable": window.nba_to,
    }


def lineup_specs(season: str, windows: Mapping[str, DateWindow], team_ids: Iterable[int]) -> list[RequestSpec]:
    """One request per (window, measure, team). Per-team requests avoid the 2,000-row cap."""
    team_ids = sorted(team_ids)
    specs = []
    for window in windows.values():
        for measure in LINEUP_MEASURES:
            for tid in team_ids:
                params = _dashboard_params(season, window, measure) | {"group_quantity": 5, "team_id_nullable": tid}
                specs.append(RequestSpec.make(LINEUPS, season, params, window=window.name, measure=measure, team_id=tid))
    return specs


def player_specs(season: str, windows: Mapping[str, DateWindow]) -> list[RequestSpec]:
    return [RequestSpec.make(PLAYERS, season, _dashboard_params(season, w, "Advanced"), window=w.name, measure="Advanced")
            for w in windows.values()]


def team_specs(season: str, windows: Mapping[str, DateWindow]) -> list[RequestSpec]:
    return [RequestSpec.make(TEAMS, season, _dashboard_params(season, w, "Advanced"), window=w.name, measure="Advanced")
            for w in windows.values()]


def season_specs(season: str, windows: Mapping[str, DateWindow], team_ids: Iterable[int]) -> list[RequestSpec]:
    """Every request for a season once its windows are known (the game log comes first)."""
    team_ids = list(team_ids)
    return team_specs(season, windows) + player_specs(season, windows) + lineup_specs(season, windows, team_ids)
