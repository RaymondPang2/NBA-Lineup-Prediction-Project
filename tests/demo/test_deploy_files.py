"""Deployment files for the public demo (Render): Blueprint, Docker image contents, licensing guard. Offline."""
from __future__ import annotations

import yaml

from nba_lineups.config import PROJECT_ROOT
from nba_lineups.demo.league import CITIES, NICKS, build

# NBA and WNBA team nicknames and NBA cities: none may appear in the fictional league.
PRO_NICKNAMES = {"Hawks", "Celtics", "Nets", "Hornets", "Bulls", "Cavaliers", "Mavericks", "Nuggets", "Pistons",
                 "Warriors", "Rockets", "Pacers", "Clippers", "Lakers", "Grizzlies", "Heat", "Bucks", "Timberwolves",
                 "Wolves", "Pelicans", "Knicks", "Thunder", "Magic", "76ers", "Suns", "Trail Blazers", "Blazers",
                 "Kings", "Spurs", "Raptors", "Jazz", "Wizards", "Dream", "Sky", "Sun", "Wings", "Fever", "Aces",
                 "Sparks", "Lynx", "Liberty", "Mercury", "Storm", "Mystics", "Valkyries", "Comets", "Monarchs"}
NBA_CITIES = {"Atlanta", "Boston", "Brooklyn", "Charlotte", "Chicago", "Cleveland", "Dallas", "Denver", "Detroit",
              "Golden State", "Houston", "Indiana", "Los Angeles", "Memphis", "Miami", "Milwaukee", "Minnesota",
              "New Orleans", "New York", "Oklahoma City", "Orlando", "Philadelphia", "Phoenix", "Portland",
              "Sacramento", "San Antonio", "Toronto", "Utah", "Washington"}


def test_blueprint_uses_free_plans_health_check_and_private_database():
    bp = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text())
    (svc,) = bp["services"]
    (db,) = bp["databases"]
    assert svc["runtime"] == "docker" and svc["plan"] == "free" and db["plan"] == "free"   # no paid resource
    assert svc["healthCheckPath"] == "/health" and svc["autoDeployTrigger"] == "commit" and svc["branch"] == "main"
    env = {e["key"]: e for e in svc["envVars"]}
    assert env["DATABASE_URL"]["fromDatabase"] == {"name": db["name"], "property": "connectionString"}
    assert env["NBA_DEMO_MODE"]["value"] == "1"
    assert db["ipAllowList"] == []                      # database reachable only from the private network


def test_image_never_contains_real_data_or_secrets():
    ignored = {l.strip() for l in (PROJECT_ROOT / ".dockerignore").read_text().splitlines() if l and not l.startswith("#")}
    assert {"data/", ".env", "web/src/test/fixtures", ".git"} <= ignored
    docker = (PROJECT_ROOT / "Dockerfile").read_text()
    assert "COPY data" not in docker and "VITE_DEMO_MODE=1" in docker and "NBA_DEMO_MODE=1" in docker
    assert "nba_lineups.demo.seed" in docker


def test_synthetic_league_uses_fictional_names_only():
    assert not set(NICKS) & PRO_NICKNAMES
    assert not set(CITIES) & NBA_CITIES
    lg = build({"2025-26": __import__("nba_lineups.demo.league", fromlist=["DEMO_SEASONS"]).DEMO_SEASONS["2025-26"]})
    season = lg["2025-26"]
    assert {t.team_id for t in season.teams}.isdisjoint(range(1610612737, 1610612767))     # not NBA team ids
    assert len({t.abbr for t in season.teams}) == 30
    for t in season.teams:                                   # no two teammates share a surname
        surnames = [season.player_name[p].split()[-1] for p in t.players]
        assert len(set(surnames)) == len(surnames)


def test_synthetic_league_is_deterministic_and_complete():
    from nba_lineups.demo.league import DEMO_SEASONS
    a = build({"2025-26": DEMO_SEASONS["2025-26"]})["2025-26"]
    b = build({"2025-26": DEMO_SEASONS["2025-26"]})["2025-26"]
    assert [(g.game_id, g.home, g.score(g.home)) for g in a.games] == [(g.game_id, g.home, g.score(g.home)) for g in b.games]
    per_team = {}
    for g in a.games:
        for t in (g.home, g.away):
            per_team[t] = per_team.get(t, 0) + 1
    assert set(per_team.values()) == {82}
    days = {}
    for g in a.games:
        for t in (g.home, g.away):
            assert (t, g.day) not in days, "a team plays twice on one day"
            days[(t, g.day)] = 1
