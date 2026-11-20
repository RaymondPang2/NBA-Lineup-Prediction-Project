"""A small, internally consistent FAKE NBA season for offline refresh tests. Not real data.

The league is defined by games and, inside each game, three 16-minute stints per team (one per five-man
combination). Every endpoint the refresh calls is answered by summing those stints over the requested date
range and team, the way stats.nba.com does. So the totals reconcile exactly across the game log, the lineup
feed and the team feed, and the pipeline's error-level data-quality checks pass. Tests then change the
league (publish more games, correct a box score, postpone a game, break an endpoint) and refresh again.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Any

import requests

from nba_lineups.config import CURRENT_SEASON
from nba_lineups.ingest.specs import GAMELOG, LINEUPS, PLAYERS, TEAMS, RequestSpec
from tests.conftest import echo, make_payload

getcontext().prec = 40
TEAM_IDS = list(range(1610612737, 1610612767))
STINT_MIN = 16
COMBOS = ((0, 1, 2, 3, 4), (0, 1, 2, 5, 6), (2, 3, 4, 5, 6))   # roster indexes of each team's three lineups


def abbr(tid: int) -> str:
    i = tid - TEAM_IDS[0]
    return "T" + chr(65 + i // 26) + chr(65 + i % 26)


def roster(tid: int) -> list[int]:
    return [2_000_000 + (tid - TEAM_IDS[0]) * 100 + k for k in range(7)]


def r1(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass
class Side:
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    ast: int
    tov: int
    poss: int

    @property
    def pts(self) -> int:
        return 2 * self.fgm + self.fg3m + self.ftm


def _side(seed: str) -> Side:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    fgm, fg3m, ftm = 10 + h % 5, (h >> 4) % 4, (h >> 8) % 5
    return Side(fgm, fgm + 8, fg3m, fg3m + 3, ftm, ftm + 1, 2, 6, 5, 3, 30 + (h >> 12) % 5)


@dataclass
class Game:
    game_id: str
    day: date
    home: int
    away: int
    # stints[k] = (home side, away side); home's combo k plays away's combo k
    stints: list[tuple[Side, Side]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stints:
            self.stints = [(_side(f"{self.game_id}-{k}-h"), _side(f"{self.game_id}-{k}-a")) for k in range(3)]
            if self.score(self.home) == self.score(self.away):         # no ties in basketball
                h = self.stints[2][0]
                h.ftm, h.fta = h.ftm + 1, h.fta + 1

    def side_of(self, tid: int, k: int) -> tuple[Side, Side]:
        h, a = self.stints[k]
        return (h, a) if tid == self.home else (a, h)

    def score(self, tid: int) -> int:
        return sum(self.side_of(tid, k)[0].pts for k in range(3))


class FakeLeague:
    def __init__(self, season: str = CURRENT_SEASON) -> None:
        self.season = season
        self.games: list[Game] = []
        self.in_progress: list[Game] = []          # listed in the game log without a result
        self.lineup_lag: set[str] = set()          # games the lineup feed does not include yet

    # ---------------------------------------------------------------- schedule
    def add_day(self, day: date, teams: list[int] | None = None) -> list[Game]:
        teams = teams or TEAM_IDS
        out = []
        for i in range(0, len(teams) - 1, 2):
            g = Game(f"0022{len(self.games) + len(self.in_progress):06d}", day, teams[i], teams[i + 1])
            self.games.append(g)
            out.append(g)
        return out

    def add_days(self, start: date, n: int) -> None:
        for d in range(n):
            rot = TEAM_IDS[d % 30:] + TEAM_IDS[:d % 30]              # different pairings each day
            self.add_day(start + timedelta(days=d), rot)

    def game(self, game_id: str) -> Game:
        return next(g for g in self.games if g.game_id == game_id)

    # ---------------------------------------------------------------- endpoints
    def _games(self, spec: RequestSpec, lineups: bool = False) -> list[Game]:
        p = spec.kwargs
        lo = _mdy(p.get("date_from_nullable")) or date.min
        hi = _mdy(p.get("date_to_nullable")) or date.max
        return [g for g in self.games if lo <= g.day <= hi and not (lineups and g.game_id in self.lineup_lag)]

    def answer(self, spec: RequestSpec) -> dict[str, Any]:
        if spec.endpoint == GAMELOG:
            return self._gamelog(spec)
        if spec.endpoint == LINEUPS:
            return self._lineups(spec)
        if spec.endpoint == TEAMS:
            return self._teams(spec)
        if spec.endpoint == PLAYERS:
            return self._players(spec)
        raise AssertionError(spec.endpoint)

    def _gamelog(self, spec: RequestSpec) -> dict[str, Any]:
        cols = ["SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME", "GAME_ID", "GAME_DATE", "MATCHUP", "WL",
                "MIN", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "PF",
                "PTS", "PLUS_MINUS"]
        rows = []
        for g in sorted(self.games + self.in_progress, key=lambda g: (g.day, g.game_id)):
            done = g in self.games
            for tid, opp, sep in ((g.home, g.away, " vs. "), (g.away, g.home, " @ ")):
                own = [g.side_of(tid, k)[0] for k in range(3)]
                tot = {c: sum(getattr(s, c) for s in own) for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
                                                                    "oreb", "dreb", "ast", "tov")}
                pts, opp_pts = g.score(tid), g.score(opp)
                rows.append(["2" + self.season[:4], tid, abbr(tid), f"Team {abbr(tid)}", g.game_id, g.day.isoformat(),
                             f"{abbr(tid)}{sep}{abbr(opp)}", ("W" if pts > opp_pts else "L") if done else None, 240,
                             tot["fgm"], tot["fga"], tot["fg3m"], tot["fg3a"], tot["ftm"], tot["fta"], tot["oreb"],
                             tot["dreb"], tot["ast"], 7, 4, tot["tov"], 18, pts, pts - opp_pts])
        return make_payload(cols, rows, echo(spec), GAMELOG)

    def _lineup_totals(self, spec: RequestSpec, tid: int) -> dict[int, dict]:
        acc: dict[int, dict] = defaultdict(lambda: defaultdict(int))
        for g in self._games(spec, lineups=True):
            if tid not in (g.home, g.away):
                continue
            for k in range(3):
                own, opp = g.side_of(tid, k)
                a = acc[k]
                a["GP"] += 1
                a["STP"] += STINT_MIN * 3000
                for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "tov", "poss", "pts"):
                    a[c] += getattr(own, c)
                    a["opp_" + c] += getattr(opp, c)
        return acc

    def _lineups(self, spec: RequestSpec) -> dict[str, Any]:
        tid = spec.team_id
        r = roster(tid)
        rows, headers = [], None
        for k, a in sorted(self._lineup_totals(spec, tid).items()):
            ids = sorted(r[i] for i in COMBOS[k])
            row = _rating_cols(a) | {
                "GROUP_ID": "-" + "-".join(map(str, ids)) + "-", "GROUP_NAME": " - ".join(f"P{i}" for i in ids),
                "TEAM_ID": tid, "TEAM_ABBREVIATION": abbr(tid), "GP": a["GP"], "MIN": round(a["STP"] / 3000),
                "SUM_TIME_PLAYED": a["STP"], "POSS": a["poss"], "PLUS_MINUS": a["pts"] - a["opp_pts"]}
            for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "tov", "pts"):
                row[c.upper()] = a[c]
                row["OPP_" + c.upper()] = a["opp_" + c]
            headers = headers or sorted(row)
            rows.append([row[h] for h in headers])
        return make_payload(headers or ["GROUP_ID"], rows, echo(spec), LINEUPS)

    def _teams(self, spec: RequestSpec) -> dict[str, Any]:
        rows, headers = [], None
        for tid in TEAM_IDS:
            a = defaultdict(int)
            for t in self._lineup_totals(spec, tid).values():
                for c, v in t.items():
                    a[c] += v
            if not a:
                continue
            a["GP"] //= 3
            row = _rating_cols(a) | {"TEAM_ID": tid, "TEAM_NAME": f"Team {abbr(tid)}", "GP": a["GP"],
                                     "MIN": a["STP"] / 3000, "POSS": a["poss"]}
            headers = headers or sorted(row)
            rows.append([row[h] for h in headers])
        return make_payload(headers or ["TEAM_ID"], rows, echo(spec), TEAMS)

    def _players(self, spec: RequestSpec) -> dict[str, Any]:
        cols = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN", "POSS", "OFF_RATING", "DEF_RATING",
                "NET_RATING", "USG_PCT", "TS_PCT"]
        rows = []
        for tid in TEAM_IDS:
            tot = self._lineup_totals(spec, tid)
            if not tot:
                continue
            r = roster(tid)
            for i, pid in enumerate(r):
                ks = [k for k, combo in enumerate(COMBOS) if i in combo and k in tot]
                if not ks:
                    continue
                poss = sum(tot[k]["poss"] for k in ks)
                rows.append([pid, f"P{pid}", tid, max(tot[k]["GP"] for k in ks), sum(tot[k]["STP"] for k in ks) / 3000,
                             poss, 110.0, 108.0, 2.0, 0.2, 0.55])
        return make_payload(cols, rows, echo(spec), PLAYERS)


def _rating_cols(a: dict) -> dict:
    off = Decimal(100 * a["pts"]) / a["poss"]
    de = Decimal(100 * a["opp_pts"]) / a["opp_poss"]
    minutes = Decimal(a["STP"]) / 3000
    pace = (Decimal(48) * (a["poss"] + a["opp_poss"]) / 2 / minutes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"OFF_RATING": r1(off), "DEF_RATING": r1(de), "NET_RATING": r1(off - de), "PACE": float(pace)}


def _mdy(s: str | None) -> date | None:
    if not s:
        return None
    m, d, y = map(int, s.split("/"))
    return date(y, m, d)


class LeagueTransport:
    """Answers RequestSpecs from a FakeLeague. Can fail chosen endpoints (timeouts) a number of times."""

    def __init__(self, league: FakeLeague) -> None:
        self.league = league
        self.calls: list[RequestSpec] = []
        self.fail: dict[str, int] = {}             # spec key (or endpoint name) -> remaining failures
        self.error: type[Exception] = requests.Timeout

    def get(self, spec: RequestSpec) -> dict[str, Any]:
        self.calls.append(spec)
        for k in (spec.key, spec.endpoint):
            if self.fail.get(k, 0) > 0:
                self.fail[k] -= 1
                raise self.error("synthetic timeout")
        return self.league.answer(spec)

    def keys(self) -> list[str]:
        return [s.key for s in self.calls]
