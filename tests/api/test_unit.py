"""API behaviour that needs no database: validation, error handling, settings, uncertainty, docs, CORS."""
from __future__ import annotations

import dataclasses
import json
import math
import re

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from nba_lineups.api import deps
from nba_lineups.api.main import create_app
from nba_lineups.api.schemas import PredictionRequest
from nba_lineups.api.services.common import PageParams, change, like_pattern, page
from nba_lineups.api.settings import Settings
from nba_lineups.config import PROJECT_ROOT

HOLDOUT = json.loads((PROJECT_ROOT / "reports/phase6/holdout/holdout_findings.json").read_text())["evaluations"]


def _error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code and body["error"]["message"]
    return body["error"]


# ---------------------------------------------------------------- settings

def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("NBA_API_CORS_ORIGINS", "https://a.example, https://b.example ,")
    monkeypatch.setenv("NBA_API_REQUIRE_GIT_FREEZE", "0")
    monkeypatch.setenv("NBA_API_POOL_MAX", "3")
    s = Settings.from_env()
    assert s.cors_origins == ("https://a.example", "https://b.example")
    assert s.require_git_freeze is False and s.pool_max == 3


def test_settings_defaults_are_safe(monkeypatch):
    for v in ("NBA_API_CORS_ORIGINS", "NBA_API_REQUIRE_GIT_FREEZE"):
        monkeypatch.delenv(v, raising=False)
    s = Settings.from_env()
    assert s.require_git_freeze is True
    assert all(o.startswith("http://localhost") or o.startswith("http://127.0.0.1") for o in s.cors_origins)


def test_database_url_never_in_source():
    """Credentials come from the environment / .env only: no real connection string in the API source."""
    url_with_secret = re.compile(r"postgres(?:ql)?://[^\s:/]+:(?!password@)[^\s@]+@")
    for f in (PROJECT_ROOT / "src/nba_lineups/api").rglob("*.py"):
        text = f.read_text()
        assert not url_with_secret.search(text) and "change_me" not in text, f


# ---------------------------------------------------------------- request validation

@pytest.mark.parametrize("body", [
    {"season_id": "2025-26", "team_id": 1, "player_ids": [1, 2, 3, 4]},             # four players
    {"season_id": "2025-26", "team_id": 1, "player_ids": [1, 2, 3, 4, 5, 6]},       # six
    {"season_id": "2025-26", "team_id": 1, "player_ids": [1, 1, 2, 3, 4]},          # duplicate
    {"season_id": "2025-26", "team_id": 1, "player_ids": [0, 1, 2, 3, 4]},          # non-positive
    {"season_id": "2025", "team_id": 1, "player_ids": [1, 2, 3, 4, 5]},             # bad season format
    {"season_id": "2025-26", "team_id": -5, "player_ids": [1, 2, 3, 4, 5]},         # bad team
    {"season_id": "2025-26", "team_id": 1, "player_ids": [1, 2, 3, 4, 5], "possessions": 5},
])
def test_prediction_request_rejected(offline_client, body):
    _error(offline_client.post("/api/v1/predictions", json=body), 422, "validation_error")


def test_prediction_request_sorts_players():
    r = PredictionRequest(season_id="2025-26", team_id=1, player_ids=[5, 3, 1, 4, 2])
    assert r.player_ids == [1, 2, 3, 4, 5] and r.possessions == 100


@pytest.mark.parametrize("url", [
    "/api/v1/lineups?season=2025", "/api/v1/lineups?season=2025-26&page=0",
    "/api/v1/lineups?season=2025-26&page_size=500", "/api/v1/lineups?season=2025-26&sort=bogus",
    "/api/v1/lineups?season=2025-26&order=up", "/api/v1/lineups?season=2025-26&min_pre_poss=-1",
    "/api/v1/lineups/0", "/api/v1/lineups/abc", "/api/v1/lineups/5/prediction?possessions=1",
    "/api/v1/players", "/api/v1/players?season=2025-26&search=a", "/api/v1/teams/stats",
    "/api/v1/teams/1/predictions",
])
def test_invalid_query_parameters_return_422(offline_client, url):
    err = _error(offline_client.get(url), 422, "validation_error")
    assert err["details"] and all({"location", "message", "type"} <= set(d) for d in err["details"])


def test_lineup_list_needs_a_filter(offline_client):
    """Checked before the database is touched: no 503 here."""
    _error(offline_client.get("/api/v1/lineups"), 400, "bad_request")
    _error(offline_client.get("/api/v1/lineups?player_id=1&player_id=1"), 400, "bad_request")
    _error(offline_client.get("/api/v1/lineups?" + "&".join(f"player_id={i}" for i in range(1, 7))), 400, "bad_request")


# ---------------------------------------------------------------- error handling

def test_missing_database_is_503(offline_settings):
    """No override: the real dependency with DATABASE_URL unset."""
    with TestClient(create_app(offline_settings), raise_server_exceptions=False) as c:
        _error(c.get("/api/v1/seasons"), 503, "database_unavailable")
        _error(c.post("/api/v1/predictions", json={"season_id": "2025-26", "team_id": 1,
                                                   "player_ids": [1, 2, 3, 4, 5]}), 503, "database_unavailable")


def test_unknown_route_and_method(offline_client):
    _error(offline_client.get("/api/v1/nope"), 404, "not_found")
    _error(offline_client.delete("/api/v1/predictions"), 405, "method_not_allowed")


@pytest.mark.parametrize("exc, status, code", [
    (psycopg.OperationalError("connection refused: postgresql://nba:SECRET@host/db"), 503, "database_unavailable"),
    (PoolTimeout("no connection"), 503, "database_unavailable"),
    (psycopg.errors.QueryCanceled("canceling statement due to statement timeout"), 504, "query_timeout"),
    (RuntimeError("SECRET internal detail"), 500, "internal_error"),
])
def test_database_failures_map_to_clean_errors(offline_settings, exc, status, code):
    app = create_app(offline_settings)

    def broken():
        raise exc
        yield  # pragma: no cover

    app.dependency_overrides[deps.get_conn] = broken
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/seasons")
    _error(r, status, code)
    assert "SECRET" not in r.text            # internals and credentials are never echoed


def test_model_not_loaded_is_503(offline_settings):
    with TestClient(create_app(offline_settings, load_model=False), raise_server_exceptions=False) as c:
        _error(c.get("/api/v1/model"), 503, "model_unavailable")
        _error(c.get("/api/v1/lineups/1/prediction"), 503, "database_unavailable")   # connection resolved first
        h = c.get("/health")
    assert h.status_code == 503 and h.json()["model"] == "unavailable"


def test_health_without_database(offline_client):
    r = offline_client.get("/health")
    assert r.status_code == 503
    assert r.json()["database"] == "not_configured" and r.json()["model"] == "ok"


# ---------------------------------------------------------------- model card and performance (no DB needed)

def test_model_card(offline_client):
    card = offline_client.get("/api/v1/model").json()
    spec = json.loads((PROJECT_ROOT / "models/final/frozen_spec.json").read_text())
    assert card["name"] == "linear" and card["artifact_verified"] is True
    assert card["artifact_sha256"] == spec["artifact"]["sha256"]
    assert [c["feature"] for c in card["coefficients"]] and \
        sorted(c["feature"] for c in card["coefficients"]) == sorted(spec["model"]["features_used"])
    assert card["held_out_seasons"] == ["2024-25", "2025-26"]
    assert "GIVEN that its coach plays it after the break" in card["prediction_target"]
    assert card["limitations"] and card["not_for"]


def test_performance_does_not_overclaim(offline_client):
    p = offline_client.get("/api/v1/model/performance").json()
    tp = HOLDOUT["pooled"]["metrics"]["linear|weighted|rmse_minus_team_prior"]
    assert p["beats_team_prior"] is (tp[2] < 0) is False          # pre-registered answer: no
    assert p["beats_league_mean"] is True
    assert "indistinguishable from the team prior" in p["conclusion"]
    pooled = next(e for e in p["held_out"] if e["evaluation"] == "pooled")
    assert pooled["model_minus_team_prior"] == {"estimate": tp[0], "lo": tp[1], "hi": tp[2]}
    assert {e["evaluation"] for e in p["held_out"]} == {"2024-25", "2025-26", "pooled"}


# ---------------------------------------------------------------- uncertainty

def test_uncertainty_components(offline_client):
    pred = offline_client.app.state.predictor
    m = HOLDOUT["pooled"]["metrics"]
    expected_model_sd = math.sqrt(m["linear|weighted|rmse"][0] ** 2 - m["noise_floor|weighted|rmse_floor"][0] ** 2)
    assert pred.model_sd == pytest.approx(expected_model_sd)
    u25, u300 = pred.uncertainty(0.0, 25), pred.uncertainty(0.0, 300)
    # the model card's sampling-only 95% half-widths: ±67 at 25 possessions per end, ±19 at 300
    assert round(1.96 * u25["sampling_sd"]) == 67 and round(1.96 * u300["sampling_sd"]) == 19
    for u in (u25, u300):
        assert u["total_sd"] == pytest.approx(math.hypot(u["model_sd"], u["sampling_sd"]))
        assert u["observed_rating_interval_95"]["hi"] - u["true_rating_interval_95"]["hi"] > 0
    assert u25["model_sd"] == u300["model_sd"] and u25["sampling_sd"] > u300["sampling_sd"]


# ---------------------------------------------------------------- helpers

def test_change_and_noise_flag():
    pre = {"off_rating": 110.0, "def_rating": 100.0, "net_rating": 10.0, "poss": 400, "opp_poss": 400}
    post = {"off_rating": 105.0, "def_rating": 108.0, "net_rating": -3.0, "poss": 100, "opp_poss": 100}
    d = change(pre, post, 14639.0)
    assert d["net_rating"] == -13.0 and d["def_rating"] == 8.0
    assert d["net_rating_sampling_sd"] == pytest.approx(math.sqrt(14639 * (2 / 400 + 2 / 100)))
    assert d["exceeds_noise"] is False                      # a 13-point swing is within noise at 100 possessions
    assert change(pre, None, 1.0) is None


def test_pagination_math():
    assert page([], 0, PageParams(1, 50))["total_pages"] == 0
    assert page([1], 101, PageParams(3, 50))["total_pages"] == 3
    assert PageParams(3, 50).offset == 100


def test_like_pattern_escapes_wildcards():
    assert like_pattern("a_b%c") == r"%a\_b\%c%"


# ---------------------------------------------------------------- docs and CORS

def test_openapi_documents_every_endpoint(offline_client):
    spec = offline_client.get("/openapi.json").json()
    paths = set(spec["paths"])
    assert {"/api/v1/seasons", "/api/v1/teams", "/api/v1/lineups", "/api/v1/lineups/{lineup_id}",
            "/api/v1/lineups/{lineup_id}/prediction", "/api/v1/players", "/api/v1/players/{player_id}",
            "/api/v1/teams/stats", "/api/v1/teams/{team_id}/stats", "/api/v1/teams/{team_id}/predictions",
            "/api/v1/predictions", "/api/v1/model", "/api/v1/model/performance", "/health"} <= paths
    assert "Prediction" in spec["components"]["schemas"]
    assert offline_client.get("/docs").status_code == 200


def test_cors(offline_settings):
    app = create_app(dataclasses.replace(offline_settings, cors_origins=("http://localhost:5173",)))
    with TestClient(app) as c:
        ok = c.options("/api/v1/model", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        bad = c.options("/api/v1/model", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers
