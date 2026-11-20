"""Validation of raw payloads before they are accepted into the cache.

Errors mean the payload is rejected (quarantined, never cached as good).
Warnings are recorded in the manifest but the payload is still accepted.
They flag real but expected data properties, such as lineups with 0 possessions.

Each rule here comes from a Phase 0 finding or a basic integrity
requirement. See docs/phase0_data_report.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import LIVE_SEASONS, N_TEAMS, ROW_CAP
from .specs import GAMELOG, LINEUPS, PLAYERS, TEAMS, RequestSpec
from .storage import result_set

_LINEUP_COMMON = {"GROUP_ID", "GROUP_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GP", "MIN", "SUM_TIME_PLAYED"}
REQUIRED_COLUMNS: dict[tuple[str, str | None], set[str]] = {
    (GAMELOG, None): {"SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "PTS"},
    (LINEUPS, "Advanced"): _LINEUP_COMMON | {"POSS", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"},
    (LINEUPS, "Base"): _LINEUP_COMMON | {"FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "TOV", "PTS", "PLUS_MINUS"},
    (LINEUPS, "Opponent"): _LINEUP_COMMON | {"OPP_FGM", "OPP_FGA", "OPP_FG3M", "OPP_FG3A", "OPP_FTM", "OPP_FTA",
                                            "OPP_OREB", "OPP_DREB", "OPP_TOV", "OPP_PTS"},
    (PLAYERS, "Advanced"): {"PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN", "POSS",
                            "OFF_RATING", "DEF_RATING", "NET_RATING", "USG_PCT", "TS_PCT"},
    (TEAMS, "Advanced"): {"TEAM_ID", "TEAM_NAME", "GP", "MIN", "POSS", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"},
}

# Our nba_api keyword -> the parameter name the server echoes back.
_ECHO_NAMES = {
    "season": "Season", "season_type_all_star": "SeasonType", "measure_type_detailed_defense": "MeasureType",
    "per_mode_detailed": "PerMode", "date_from_nullable": "DateFrom", "date_to_nullable": "DateTo",
    "team_id_nullable": "TeamID", "group_quantity": "GroupQuantity", "player_or_team_abbreviation": "PlayerOrTeam",
    "location_nullable": "Location",
}


@dataclass
class ValidationReport:
    row_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_payload(spec: RequestSpec, payload: Any) -> ValidationReport:
    report = ValidationReport()

    # 1. Structure
    try:
        headers, rows = result_set(payload)
    except (KeyError, IndexError, TypeError):
        report.errors.append("malformed payload: missing resultSets[0].headers/rowSet")
        return report
    report.row_count = len(rows)
    if any(len(r) != len(headers) for r in rows):
        report.errors.append("row width does not match header width")
        return report
    missing = REQUIRED_COLUMNS[(spec.endpoint, spec.measure)] - set(headers)
    if missing:
        report.errors.append(f"missing required columns: {sorted(missing)}")
        return report

    # 2. The server applied the filters we asked for
    _check_echoed_parameters(spec, payload, report)

    # 3. Silent truncation (dashboard endpoints only; the game log legitimately has 2,460 rows)
    if spec.endpoint != GAMELOG and len(rows) >= ROW_CAP:
        report.errors.append(f"{len(rows)} rows >= {ROW_CAP}: response is probably truncated")

    df = pd.DataFrame(rows, columns=headers)
    {GAMELOG: _check_gamelog, LINEUPS: _check_lineups, PLAYERS: _check_players, TEAMS: _check_teams}[spec.endpoint](
        spec, df, report)
    return report


def _check_echoed_parameters(spec: RequestSpec, payload: dict[str, Any], report: ValidationReport) -> None:
    echoed = payload.get("parameters")
    if not isinstance(echoed, dict):
        report.warnings.append("response has no 'parameters' echo; filters could not be verified")
        return
    for ours, theirs in _ECHO_NAMES.items():
        if ours in spec.kwargs and theirs in echoed and str(echoed[theirs]) != str(spec.kwargs[ours]):
            report.errors.append(f"server applied {theirs}={echoed[theirs]!r}, requested {spec.kwargs[ours]!r}")


def _check_gamelog(spec: RequestSpec, df: pd.DataFrame, report: ValidationReport) -> None:
    if df.empty:
        report.errors.append("empty game log")
        return
    if pd.to_datetime(df.GAME_DATE, errors="coerce").isna().any():
        report.errors.append("unparseable GAME_DATE values")
    per_game = df.groupby("GAME_ID").size()
    if (per_game != 2).any():
        report.errors.append(f"{int((per_game != 2).sum())} games do not have exactly 2 team rows")
    # A season in progress may not have every team in it yet (opening days); a completed one must.
    n = df.TEAM_ID.nunique()
    if (n > N_TEAMS) if spec.season in LIVE_SEASONS else (n != N_TEAMS):
        report.errors.append(f"expected {N_TEAMS} teams, found {n}")


def parse_group_id(group_id: str) -> list[int]:
    """'-203484-203932-...-' -> [203484, 203932, ...]"""
    return [int(p) for p in group_id.strip("-").split("-")]


def _check_lineups(spec: RequestSpec, df: pd.DataFrame, report: ValidationReport) -> None:
    if df.empty:
        # Every team plays lineups in both windows, so an empty response is suspicious.
        report.errors.append("no lineups returned for a team/window that must have games")
        return
    try:
        ids = df.GROUP_ID.map(parse_group_id)
    except (ValueError, AttributeError):
        report.errors.append("GROUP_ID contains non-numeric player ids")
        return
    if (ids.map(len) != 5).any():
        report.errors.append(f"{int((ids.map(len) != 5).sum())} GROUP_IDs do not contain exactly 5 players")
    if (ids.map(lambda xs: len(set(xs))) != ids.map(len)).any():
        report.errors.append("GROUP_ID with a repeated player")
    if not ids.map(lambda xs: xs == sorted(xs)).all():
        report.errors.append("GROUP_ID player ids not in numeric order (lineup keys would be unstable)")
    dup = df[df.GROUP_ID.duplicated(keep=False)]
    if not dup.empty:
        # Phase 2 finding: the API splits one lineup into several rows when a player's display
        # name changed (e.g. 'L. Doncic' / 'L. Dončić', 'E. Kanter' / 'E. Freedom'). Those rows are
        # partial totals over different games and are summed in the transform step. A repeated
        # (GROUP_ID, GROUP_NAME) pair, however, is a true duplicate and is rejected.
        if dup.duplicated(["GROUP_ID", "GROUP_NAME"]).any():
            report.errors.append(f"{int(dup.duplicated(['GROUP_ID', 'GROUP_NAME']).sum())} duplicate "
                                 "(GROUP_ID, GROUP_NAME) rows")
        else:
            report.warnings.append(f"{dup.GROUP_ID.nunique()} GROUP_IDs split across player-name variants "
                                   "(partial totals; summed during transform)")
    if spec.team_id is not None and (df.TEAM_ID != spec.team_id).any():
        report.errors.append(f"rows for a team other than {spec.team_id}")

    nonneg = ["GP", "MIN", "SUM_TIME_PLAYED"] + (["POSS"] if spec.measure == "Advanced" else [])
    for col in nonneg:
        if (df[col] < 0).any():
            report.errors.append(f"negative {col}")
    # MIN is rounded to whole minutes; SUM_TIME_PLAYED/3000 is exact (Phase 0 finding)
    drift = (df.MIN - df.SUM_TIME_PLAYED / 3000).abs()
    if (drift > 0.51).any():
        report.warnings.append(f"{int((drift > 0.51).sum())} rows where MIN differs from SUM_TIME_PLAYED/3000 by >0.5")

    if spec.measure == "Advanced":
        zero = int((df.POSS == 0).sum())
        if zero:
            report.warnings.append(f"{zero} lineups with POSS == 0 (ratings undefined)")
        bad_net = (df.OFF_RATING - df.DEF_RATING - df.NET_RATING).abs() > 0.2
        if bad_net.any():
            report.warnings.append(f"{int(bad_net.sum())} rows where NET != OFF - DEF (beyond rounding)")


def _check_players(spec: RequestSpec, df: pd.DataFrame, report: ValidationReport) -> None:
    if df.empty:
        report.errors.append("empty player table")
        return
    if df.PLAYER_ID.duplicated().any():
        report.errors.append("duplicate PLAYER_IDs")
    if (df.MIN < 0).any():
        report.errors.append("negative MIN")


def _check_teams(spec: RequestSpec, df: pd.DataFrame, report: ValidationReport) -> None:
    if spec.season in LIVE_SEASONS:
        # Season in progress: only teams that have played in the window are listed (e.g. the first days
        # after the All-Star break). Still no duplicates and never more than 30.
        if df.empty or len(df) > N_TEAMS or df.TEAM_ID.duplicated().any():
            report.errors.append(f"expected 1-{N_TEAMS} unique teams, found {len(df)} rows / {df.TEAM_ID.nunique()} ids")
        return
    if len(df) != N_TEAMS or df.TEAM_ID.nunique() != N_TEAMS:
        report.errors.append(f"expected {N_TEAMS} unique teams, found {len(df)} rows / {df.TEAM_ID.nunique()} ids")
