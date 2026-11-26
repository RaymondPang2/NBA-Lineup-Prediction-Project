"""SYNTHETIC league for the public demo. Every team, player and number here is FICTIONAL.

Why: NBA.com's terms allow its statistics only for private, non-commercial use, so the public website cannot show the
real warehouse. The demo runs the SAME pipeline on generated data: this module answers the four stats.nba.com
endpoints the ingester calls (game log, lineup, team and player dashboards) from a simulated season, so the real
validation, ETL, data-quality gate, rating views, frozen model and dashboard all run unchanged.

Simulation (deterministic for a seed):
* 30 fictional teams, 13 fictional players each, a strength per team and an offensive/defensive effect per player;
* each team rotates through ~25 five-man combinations with Zipf-like weights (starters play most);
* each game is 12 four-minute segments; in each, both teams field a combination and play ~8 possessions with
  shooting, free throws, rebounds and turnovers drawn from probabilities that depend on the ten players on court;
* the schedule runs October to April with a 6-day All-Star break in mid-February (82 games per team).
Totals for any date range are sums of segments, exactly how the real endpoints aggregate, so lineup points equal
game-log points, lineup minutes equal team minutes, and opponent possessions are recoverable from pace.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Any

from ..ingest.specs import GAMELOG, LINEUPS, PLAYERS, TEAMS, RequestSpec
from ..ingest.validate import _ECHO_NAMES

getcontext().prec = 40
SEG_MIN = 4                     # 12 segments x 4 minutes = 48
N_SEG = 12
TEAM_ID0 = 1_000_001            # fictional ids, far from NBA's 1610612737+
PLAYER_ID0 = 9_000_000

CITIES = ["Harbor City", "Red Rock", "Lakeshore", "Pine Valley", "Iron Bay", "Sun Mesa", "North Ridge", "Cedar Falls",
          "Granite Point", "Silver Lake", "Eastport", "Westbrook Hills", "Copper Canyon", "Bluewater", "Stonebridge",
          "Maple Grove", "Highland", "Riverside Bend", "Summit", "Clearwater", "Fox Hollow", "Ashford", "Brightwater",
          "Kingsport", "Oak Harbor", "Willow Creek", "Starling", "Elm Park", "Thunder Plains", "Coral Coast"]
NICKS = ["Meteors", "Foxes", "Tides", "Owls", "Anchors", "Scorpions", "Foxhounds", "Cascades", "Miners", "Herons",
         "Lanterns", "Stallions", "Jackals", "Barracudas", "Sentinels", "Maples", "Kestrels", "Otters", "Peaks",
         "Albatrosses", "Badgers", "Archers", "Embers", "Voyagers", "Sailors", "Bison", "Starlings", "Elks", "Gales",
         "Corals"]
FIRST = ["Avery", "Jalen", "Marcus", "Theo", "Darius", "Quinn", "Rowan", "Malik", "Elias", "Cyrus", "Dorian", "Jonah",
         "Kellan", "Andre", "Silas", "Tobias", "Emeka", "Lucas", "Isaiah", "Ronan", "Nico", "Felix", "Omar", "Rafael",
         "Cole", "Bastian", "Idris", "Mateo", "Soren", "Zion", "Caleb", "Hugo", "Levi", "Dante", "Kofi", "Arlo"]
LAST = ["Ashgrove", "Brightwell", "Calloway", "Dunmore", "Everhart", "Fairbanks", "Galloway", "Hartwell", "Ivers",
        "Jessup", "Kingsley", "Lockhart", "Merriweather", "Northcott", "Oakes", "Pemberton", "Quill", "Ravensworth",
        "Sterling", "Thorne", "Underwood", "Vance", "Whitlock", "Yardley", "Zeller", "Ambrose", "Blackwood",
        "Crestfield", "Dalloway", "Ellsworth", "Fennimore", "Greystone", "Holloway", "Inglewood", "Marlowe", "Wexford"]

COUNTS = ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "tov", "poss")


def r1(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass
class Side:
    fgm: int = 0
    fga: int = 0
    fg3m: int = 0
    fg3a: int = 0
    ftm: int = 0
    fta: int = 0
    oreb: int = 0
    dreb: int = 0
    ast: int = 0
    tov: int = 0
    poss: int = 0

    @property
    def pts(self) -> int:
        return 2 * self.fgm + self.fg3m + self.ftm


@dataclass
class Team:
    team_id: int
    abbr: str
    name: str
    strength: float
    players: list[int]
    combos: list[tuple[int, ...]]            # sorted player-id tuples
    weights: list[float]


@dataclass
class Segment:
    home_combo: tuple[int, ...]
    away_combo: tuple[int, ...]
    home: Side
    away: Side


@dataclass
class Game:
    game_id: str
    day: date
    home: int
    away: int
    segments: list[Segment] = field(default_factory=list)

    def score(self, tid: int) -> int:
        return sum((s.home if tid == self.home else s.away).pts for s in self.segments)


class SyntheticSeason:
    def __init__(self, season: str, seed: int, start: date, end: date, break_start: date, break_days: int = 6,
                 games_per_team: int = 82) -> None:
        self.season = season
        self.rng = random.Random(seed)
        self.player_name: dict[int, str] = {}
        self.player_off: dict[int, float] = {}
        self.player_def: dict[int, float] = {}
        self.player_usg: dict[int, float] = {}
        self.teams = self._teams()
        self.games: list[Game] = []
        self._schedule(start, end, break_start, break_days, games_per_team)
        for g in self.games:
            self._play(g)

    # ---------------------------------------------------------------- league
    def _teams(self) -> list[Team]:
        rng, teams, used = self.rng, [], set()
        abbrs: set[str] = set()
        for i in range(30):
            tid = TEAM_ID0 + i
            city, nick = CITIES[i], NICKS[i]
            words = city.split()
            base = (words[0][0] + words[1][0] if len(words) > 1 else words[0][:2]).upper() + nick[0].upper()
            abbr = base
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if abbr not in abbrs:
                    break
                abbr = base[:2] + ch
            abbrs.add(abbr)
            players = []
            surnames = rng.sample(LAST, 13)                         # distinct surnames within a team
            for k in range(13):
                pid = PLAYER_ID0 + i * 100 + k
                while True:
                    nm = f"{rng.choice(FIRST)} {surnames[k]}"
                    if nm not in used:
                        used.add(nm)
                        break
                self.player_name[pid] = nm
                star = 1.0 if k < 5 else 0.55 if k < 9 else 0.25        # starters better on average
                self.player_off[pid] = rng.gauss(1.2 * star - 0.6, 1.4)
                self.player_def[pid] = rng.gauss(1.0 * star - 0.5, 1.2)
                self.player_usg[pid] = max(0.1, rng.gauss(0.2 + 0.04 * star, 0.04))
                players.append(pid)
            combos: list[tuple[int, ...]] = [tuple(sorted(players[:5]))]
            while len(combos) < 40:
                # bench mixes: keep 2-4 starters, fill from the bench, weighted toward the rotation
                keep = rng.sample(players[:5], rng.randint(2, 4))
                pool = players[5:11] if rng.random() < 0.8 else players[5:]
                fill = rng.sample(pool, 5 - len(keep))
                c = tuple(sorted(keep + fill))
                if c not in combos:
                    combos.append(c)
            weights = [1 / (j + 1) ** 1.15 for j in range(len(combos))]
            teams.append(Team(tid, abbr, f"{city} {nick}", rng.gauss(0, 2.2), players, combos, weights))
        return teams

    def _schedule(self, start: date, end: date, break_start: date, break_days: int, per_team: int) -> None:
        """Pair teams day by day (a team plays at most once a day) until each has `per_team` games."""
        rng = self.rng
        days = [start + timedelta(d) for d in range((end - start).days + 1)]
        days = [d for d in days if not (break_start <= d < break_start + timedelta(break_days))]
        left = {t.team_id: per_team for t in self.teams}
        by_day: dict[date, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(days):
            remaining = len(days) - i
            avail = [t for t, k in left.items() if k > 0 and rng.random() < min(1.0, 2.2 * k / remaining)]
            rng.shuffle(avail)
            for a, b in zip(avail[::2], avail[1::2]):
                by_day[d].append((a, b))
                left[a] -= 1
                left[b] -= 1
        for d in reversed(days):                                    # top up stragglers on late days
            busy = {t for g in by_day[d] for t in g}
            need = [t for t, k in left.items() if k > 0 and t not in busy]
            rng.shuffle(need)
            for a, b in zip(need[::2], need[1::2]):
                by_day[d].append((a, b))
                left[a] -= 1
                left[b] -= 1
            if not any(left.values()):
                break
        n = 0
        for d in days:
            for a, b in by_day[d]:
                home, away = (a, b) if rng.random() < 0.5 else (b, a)
                self.games.append(Game(f"00{self.season[2:4]}{n:05d}", d, home, away))
                n += 1

    def _side(self, off: tuple[int, ...], de: tuple[int, ...], strength: float, opp_strength: float, poss: int) -> Side:
        rng = self.rng
        o = sum(self.player_off[p] for p in off) / 5 + strength / 2
        d = sum(self.player_def[p] for p in de) / 5 + opp_strength / 2
        edge = (o - d) / 100
        s = Side(poss=poss)
        for _ in range(poss):
            if rng.random() < 0.13:
                s.tov += 1
                continue
            if rng.random() < 0.11:                                  # trip to the line
                s.fta += 2
                s.ftm += sum(rng.random() < 0.78 for _ in range(2))
                continue
            while True:                                              # shots until a make or a defensive rebound
                three = rng.random() < 0.39
                s.fga += 1
                if three:
                    s.fg3a += 1
                made = rng.random() < (0.36 if three else 0.53) + edge
                if made:
                    s.fgm += 1
                    if three:
                        s.fg3m += 1
                    if rng.random() < 0.62:
                        s.ast += 1
                    break
                if rng.random() < 0.26:
                    s.oreb += 1
                    continue
                break
        s.dreb = max(0, s.fga - s.fgm - s.oreb)                     # the other side's misses rebounded (approx.)
        return s

    def _play(self, g: Game) -> None:
        rng = self.rng
        th = next(t for t in self.teams if t.team_id == g.home)
        ta = next(t for t in self.teams if t.team_id == g.away)
        for _ in range(N_SEG):
            hc = rng.choices(th.combos, th.weights)[0]
            ac = rng.choices(ta.combos, ta.weights)[0]
            p = rng.randint(7, 9)
            q = p + rng.choice((-1, 0, 0, 1))
            g.segments.append(Segment(hc, ac, self._side(hc, ac, th.strength + 1.0, ta.strength, p),
                                      self._side(ac, hc, ta.strength, th.strength + 1.0, q)))
        while g.score(g.home) == g.score(g.away):                   # no ties: add a made free throw
            last = g.segments[-1].home
            last.fta += 1
            last.ftm += 1

    # ---------------------------------------------------------------- endpoints
    def answer(self, spec: RequestSpec) -> dict[str, Any]:
        return {GAMELOG: self._gamelog, LINEUPS: self._lineups, TEAMS: self._team_dash, PLAYERS: self._players}[
            spec.endpoint](spec)

    def _games(self, spec: RequestSpec) -> list[Game]:
        p = spec.kwargs
        lo = _mdy(p.get("date_from_nullable")) or date.min
        hi = _mdy(p.get("date_to_nullable")) or date.max
        return [g for g in self.games if lo <= g.day <= hi]

    def _sides(self, g: Game, tid: int):
        for s in g.segments:
            yield (s.home_combo, s.home, s.away) if tid == g.home else (s.away_combo, s.away, s.home)

    def _gamelog(self, spec: RequestSpec) -> dict[str, Any]:
        cols = ["SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME", "GAME_ID", "GAME_DATE", "MATCHUP", "WL",
                "MIN", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "PF",
                "PTS", "PLUS_MINUS"]
        team = {t.team_id: t for t in self.teams}
        rows = []
        for g in self.games:
            for tid, opp, sep in ((g.home, g.away, " vs. "), (g.away, g.home, " @ ")):
                tot = defaultdict(int)
                for _, own, _o in self._sides(g, tid):
                    for c in COUNTS:
                        tot[c] += getattr(own, c)
                pts, opp_pts = g.score(tid), g.score(opp)
                rows.append(["2" + self.season[:4], tid, team[tid].abbr, team[tid].name, g.game_id, g.day.isoformat(),
                             f"{team[tid].abbr}{sep}{team[opp].abbr}", "W" if pts > opp_pts else "L", 240,
                             tot["fgm"], tot["fga"], tot["fg3m"], tot["fg3a"], tot["ftm"], tot["fta"], tot["oreb"],
                             tot["dreb"], tot["ast"], 7, 5, tot["tov"], 19, pts, pts - opp_pts])
        return _payload(cols, rows, spec)

    def _totals(self, spec: RequestSpec, tid: int) -> dict[tuple[int, ...], dict]:
        acc: dict[tuple[int, ...], dict] = defaultdict(lambda: defaultdict(int))
        for g in self._games(spec):
            if tid not in (g.home, g.away):
                continue
            seen = set()
            for combo, own, opp in self._sides(g, tid):
                a = acc[combo]
                if combo not in seen:
                    a["GP"] += 1
                    seen.add(combo)
                a["STP"] += SEG_MIN * 3000
                for c in COUNTS:
                    a[c] += getattr(own, c)
                    a["opp_" + c] += getattr(opp, c)
                a["pts"] += own.pts
                a["opp_pts"] += opp.pts
        return acc

    def _lineups(self, spec: RequestSpec) -> dict[str, Any]:
        rows, headers = [], None
        for combo, a in sorted(self._totals(spec, spec.team_id).items()):
            row = _ratings(a) | {
                "GROUP_ID": "-" + "-".join(map(str, combo)) + "-",
                "GROUP_NAME": " - ".join(self.player_name[p] for p in combo),
                "TEAM_ID": spec.team_id, "TEAM_ABBREVIATION": self._abbr(spec.team_id), "GP": a["GP"],
                "MIN": round(a["STP"] / 3000), "SUM_TIME_PLAYED": a["STP"], "POSS": a["poss"],
                "PLUS_MINUS": a["pts"] - a["opp_pts"]}
            for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "ast", "tov", "pts"):
                row[c.upper()] = a[c]
                row["OPP_" + c.upper()] = a["opp_" + c]
            headers = headers or sorted(row)
            rows.append([row[h] for h in headers])
        return _payload(headers or ["GROUP_ID"], rows, spec)

    def _abbr(self, tid: int) -> str:
        return next(t.abbr for t in self.teams if t.team_id == tid)

    def _team_dash(self, spec: RequestSpec) -> dict[str, Any]:
        rows, headers = [], None
        for t in self.teams:
            tot = self._totals(spec, t.team_id)
            if not tot:
                continue
            a = defaultdict(int)
            for v in tot.values():
                for c, x in v.items():
                    a[c] += x
            games = len([g for g in self._games(spec) if t.team_id in (g.home, g.away)])
            row = _ratings(a) | {"TEAM_ID": t.team_id, "TEAM_NAME": t.name, "GP": games, "MIN": a["STP"] / 3000,
                                 "POSS": a["poss"]}
            headers = headers or sorted(row)
            rows.append([row[h] for h in headers])
        return _payload(headers or ["TEAM_ID"], rows, spec)

    def _players(self, spec: RequestSpec) -> dict[str, Any]:
        cols = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN", "POSS", "OFF_RATING", "DEF_RATING", "NET_RATING",
                "USG_PCT", "TS_PCT"]
        rows = []
        for t in self.teams:
            tot = self._totals(spec, t.team_id)
            on = defaultdict(lambda: defaultdict(int))
            for combo, a in tot.items():
                for p in combo:
                    for c in ("STP", "poss", "opp_poss", "pts", "opp_pts", "GP"):
                        on[p][c] += a[c]
            games = len([g for g in self._games(spec) if t.team_id in (g.home, g.away)])
            for p, a in on.items():
                off = 100 * a["pts"] / a["poss"] if a["poss"] else 0.0
                de = 100 * a["opp_pts"] / a["opp_poss"] if a["opp_poss"] else 0.0
                rows.append([p, self.player_name[p], t.team_id, min(games, a["GP"]), round(a["STP"] / 3000, 1),
                             a["poss"], round(off, 1), round(de, 1), round(off - de, 1),
                             round(self.player_usg[p], 3), 0.56])
        return _payload(cols, rows, spec)


def _ratings(a: dict) -> dict:
    off = Decimal(100 * a["pts"]) / a["poss"] if a["poss"] else Decimal(0)
    de = Decimal(100 * a["opp_pts"]) / a["opp_poss"] if a["opp_poss"] else Decimal(0)
    minutes = Decimal(a["STP"]) / 3000
    pace = (Decimal(48) * (a["poss"] + a["opp_poss"]) / 2 / minutes).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"OFF_RATING": r1(off), "DEF_RATING": r1(de), "NET_RATING": r1(off - de), "PACE": float(pace)}


def _mdy(s: str | None) -> date | None:
    if not s:
        return None
    m, d, y = map(int, s.split("/"))
    return date(y, m, d)


def _payload(headers: list[str], rows: list[list[Any]], spec: RequestSpec) -> dict[str, Any]:
    echo = {theirs: spec.kwargs[ours] for ours, theirs in _ECHO_NAMES.items() if ours in spec.kwargs}
    return {"resource": "synthetic-demo", "parameters": echo,
            "resultSets": [{"name": "SyntheticDemo", "headers": headers, "rowSet": rows}]}


class SyntheticTransport:
    """Ingester transport backed by synthetic seasons (never touches the network)."""

    def __init__(self, seasons: dict[str, SyntheticSeason]) -> None:
        self.seasons = seasons

    def get(self, spec: RequestSpec) -> dict[str, Any]:
        return self.seasons[spec.season].answer(spec)


# The demo's seasons: fictional data under two season labels the app understands. They are NOT the real seasons.
DEMO_SEASONS = {
    "2024-25": dict(seed=2425, start=date(2024, 10, 22), end=date(2025, 4, 13), break_start=date(2025, 2, 14)),
    "2025-26": dict(seed=2526, start=date(2025, 10, 21), end=date(2026, 4, 12), break_start=date(2026, 2, 13)),
}


def build(seasons: dict[str, dict] = DEMO_SEASONS) -> dict[str, SyntheticSeason]:
    return {s: SyntheticSeason(s, **kw) for s, kw in seasons.items()}
