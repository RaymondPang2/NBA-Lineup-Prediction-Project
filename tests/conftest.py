"""Shared test helpers.

All payloads here are SYNTHETIC. They mimic the structure of stats.nba.com
responses (same column names as the real ones observed in Phase 0) so that we
can test pipeline behaviour offline. The numbers are NOT real NBA data.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from nba_lineups.config import IngestSettings
from nba_lineups.ingest.specs import GAMELOG, LINEUPS, PLAYERS, TEAMS, RequestSpec
from nba_lineups.ingest.validate import _ECHO_NAMES, REQUIRED_COLUMNS

TEAM_IDS = list(range(1610612737, 1610612767))  # 30 ids, same range as the real NBA team ids
SEASON = "2023-24"
BREAK_START, BREAK_END = date(2024, 2, 16), date(2024, 2, 21)  # synthetic break: no games these days


def make_payload(headers: list[str], rows: list[list[Any]], parameters: dict[str, Any] | None = None,
                 resource: str = "synthetic") -> dict[str, Any]:
    return {"resource": resource, "parameters": parameters or {},
            "resultSets": [{"name": "Synthetic", "headers": headers, "rowSet": rows}]}


def echo(spec: RequestSpec) -> dict[str, Any]:
    return {theirs: spec.kwargs[ours] for ours, theirs in _ECHO_NAMES.items() if ours in spec.kwargs}


def synthetic_game_dates(start: date = date(2023, 10, 24), end: date = date(2024, 4, 14)) -> list[date]:
    d, out = start, []
    while d <= end:
        if not (BREAK_START <= d <= BREAK_END):
            out.append(d)
        d += timedelta(days=1)
    return out


def gamelog_payload(spec: RequestSpec) -> dict[str, Any]:
    headers = ["SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "PTS"]
    rows = []
    for g, d in enumerate(synthetic_game_dates()):
        home, away = TEAM_IDS[g % 30], TEAM_IDS[(g + 1) % 30]
        for tid in (home, away):
            rows.append(["22023", tid, f"T{tid % 100}", f"00{g:08d}", d.isoformat(), 100])
    return make_payload(headers, rows, echo(spec), GAMELOG)


def lineup_rows(team_id: int, headers: list[str], n: int = 3) -> list[list[Any]]:
    rows = []
    for i in range(n):
        players = sorted(team_id % 1000 * 1000 + i + k for k in range(5))
        values = {
            "GROUP_ID": "-" + "-".join(map(str, players)) + "-", "GROUP_NAME": f"lineup {i}",
            "TEAM_ID": team_id, "TEAM_ABBREVIATION": "SYN", "GP": 10, "MIN": 20, "SUM_TIME_PLAYED": 60000,
            "POSS": 50, "OFF_RATING": 110.0, "DEF_RATING": 105.0, "NET_RATING": 5.0, "PACE": 100.0,
        }
        rows.append([values.get(h, 1) for h in headers])
    return rows


def dashboard_payload(spec: RequestSpec) -> dict[str, Any]:
    headers = sorted(REQUIRED_COLUMNS[(spec.endpoint, spec.measure)])
    if spec.endpoint == LINEUPS:
        rows = lineup_rows(spec.team_id, headers)
    elif spec.endpoint == TEAMS:
        rows = [[tid if h == "TEAM_ID" else 1 for h in headers] for tid in TEAM_IDS]
    else:  # PLAYERS
        rows = [[pid if h == "PLAYER_ID" else 1 for h in headers] for pid in (1, 2, 3)]
    return make_payload(headers, rows, echo(spec), spec.endpoint)


def synthetic_payload(spec: RequestSpec) -> dict[str, Any]:
    return gamelog_payload(spec) if spec.endpoint == GAMELOG else dashboard_payload(spec)


class FakeTransport:
    """Records calls. Can fail N times per key, return invalid data, or simulate Ctrl-C."""

    def __init__(self, fail_times: dict[str, int] | None = None, invalid_keys: set[str] | None = None,
                 interrupt_after: int | None = None, error: type[Exception] = ConnectionError) -> None:
        self.calls: list[str] = []
        self.fail_times = dict(fail_times or {})
        self.invalid_keys = invalid_keys or set()
        self.interrupt_after = interrupt_after
        self.error = error

    def get(self, spec: RequestSpec) -> dict[str, Any]:
        if self.interrupt_after is not None and len(self.calls) >= self.interrupt_after:
            raise KeyboardInterrupt
        self.calls.append(spec.key)
        if self.fail_times.get(spec.key, 0) > 0:
            self.fail_times[spec.key] -= 1
            raise self.error("synthetic network failure")
        payload = synthetic_payload(spec)
        if spec.key in self.invalid_keys:
            payload["resultSets"][0]["rowSet"] = payload["resultSets"][0]["rowSet"] * 700  # >= 2000 rows
        return payload


class FakeClock:
    """Deterministic time: sleeping advances the clock instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fast_settings() -> IngestSettings:
    return IngestSettings(min_interval_s=1.0, jitter_s=0.0, max_attempts=3, backoff_base_s=2.0, backoff_max_s=60.0)
