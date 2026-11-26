"""The public demo's synthetic league through the REAL pipeline into a throwaway database, and the demo-mode API."""
from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from nba_lineups.demo import build as demo_build
from nba_lineups.demo.league import DEMO_SEASONS


def test_demo_builds_through_the_real_pipeline_and_passes_every_quality_check(conn, test_db_url):
    counts = demo_build.build_demo(test_db_url)
    assert set(counts) == set(DEMO_SEASONS)
    for c in counts.values():
        assert c["team_games"] == 2460 and c["lineups"] > 1000 and c["team_window_stats"] == 60
    assert demo_build.build_demo(test_db_url) == {}                        # idempotent: nothing left to load
    n = conn.execute("SELECT count(*) FROM lineup_window_stats").fetchone()[0]
    assert conn.execute("SELECT count(*) FROM (SELECT lineup_id, window_type FROM lineup_window_stats "
                        "GROUP BY 1, 2 HAVING count(*) > 1) d").fetchone()[0] == 0 and n > 3000


def test_interrupted_seed_resumes_with_the_missing_season(conn, test_db_url, monkeypatch):
    first = dict(list(DEMO_SEASONS.items())[:1])
    monkeypatch.setattr(demo_build, "DEMO_SEASONS", first)
    demo_build.build_demo(test_db_url)
    monkeypatch.setattr(demo_build, "DEMO_SEASONS", DEMO_SEASONS)
    done = demo_build.build_demo(test_db_url)
    assert set(done) == set(DEMO_SEASONS) - set(first)
    assert {r[0] for r in conn.execute("SELECT season_id FROM seasons")} == set(DEMO_SEASONS)


def test_refuses_to_write_into_a_database_with_real_seasons(conn, test_db_url):
    conn.execute("INSERT INTO seasons (season_id, start_year, is_irregular, first_game_date, last_game_date) "
                 "VALUES ('2018-19', 2018, false, '2018-10-16', '2019-04-10')")
    with pytest.raises(RuntimeError, match="non-demo seasons"):
        demo_build.build_demo(test_db_url)


def test_demo_mode_api_labels_everything_synthetic_and_serves_the_dashboard(conn, test_db_url, tmp_path):
    from nba_lineups.api.main import create_app
    from nba_lineups.api.settings import Settings

    demo_build.build_demo(test_db_url)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Lineup Lab</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    s = Settings.from_env()
    settings = Settings(**{**s.__dict__, "database_url": test_db_url, "demo_mode": True, "static_dir": dist,
                           "require_git_freeze": False})
    with TestClient(create_app(settings)) as c:
        c.app.state.pool.wait(timeout=10)
        h = c.get("/health").json()
        assert h["mode"] == "demo" and h["database"] == "ok" and h["status"] == "ok"
        assert {x["role"] for x in c.get("/api/v1/seasons").json()} == {"demo"}
        r = c.get("/api/v1/rankings/predictions?season=2025-26&page_size=1").json()
        assert r["notes"][0].startswith("SYNTHETIC DEMO DATA")
        lid = r["items"][0]["lineup_id"]
        p = c.get(f"/api/v1/lineups/{lid}/prediction").json()
        assert p["notes"][0].startswith("SYNTHETIC DEMO DATA") and p["baselines"]["team_prior"] is not None
        # same-origin dashboard: client routes fall back to index.html; API and asset misses stay 404
        for path in ("/", "/rankings", "/lineups/123"):
            res = c.get(path)
            assert res.status_code == 200 and "Lineup Lab" in res.text
        assert c.get("/assets/app.js").headers["cache-control"].startswith("public, max-age=31536000")
        assert c.get("/api/v1/nope").status_code == 404 and c.get("/api/v1/nope").json()["error"]["code"] == "not_found"
        assert "[project]" not in c.get("/../pyproject.toml").text


def test_seeding_health_state(conn, test_db_url):
    from nba_lineups.api.main import create_app
    from nba_lineups.api.settings import Settings

    s = Settings.from_env()
    settings = Settings(**{**s.__dict__, "database_url": test_db_url, "demo_mode": True, "require_git_freeze": False})
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        c.app.state.pool.wait(timeout=10)
        r = c.get("/health")
        assert r.status_code == 503 and r.json()["database"] == "seeding"
