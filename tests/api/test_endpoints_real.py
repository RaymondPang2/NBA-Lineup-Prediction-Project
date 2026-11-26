"""Endpoints against the REAL database (eight seasons), through the API's read-only connection pool.

Includes the two central checks of Phase 7:
  - predictions served by the API are the frozen Phase 6 model's predictions, reproducing the held-out
    RMSE recorded in reports/phase6/holdout/holdout_findings.json;
  - building predictions reads pre-break data only (SQL audit), and the API cannot write to the database.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import psycopg
import pytest

from nba_lineups.analysis.data import HeldOutDataError
from nba_lineups.config import CURRENT_SEASON, DEV_SEASONS, HELDOUT_SEASONS, LIVE_SEASONS, PROJECT_ROOT
from nba_lineups.modeling import final, raw
from nba_lineups.modeling.features import FeatureBuilder
from nba_lineups.modeling.models import weighted_rmse

pytestmark = [pytest.mark.db, pytest.mark.realdata]
V1 = "/api/v1"
HOLDOUT = json.loads((PROJECT_ROOT / "reports/phase6/holdout/holdout_findings.json").read_text())["evaluations"]


def get(client, url, status=200):
    r = client.get(V1 + url)
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture(scope="module")
def lineup(client):
    """The most-used 2025-26 lineup (pre-break), with post-break minutes too."""
    return get(client, "/lineups?season=2025-26&min_pre_poss=200&min_post_poss=50&page_size=1")["items"][0]


# ---------------------------------------------------------------- catalog

def test_seasons(client):
    s = get(client, "/seasons")
    ids = [x["season_id"] for x in s]
    assert ids[:8] == list(DEV_SEASONS + HELDOUT_SEASONS) and set(ids[8:]) <= set(LIVE_SEASONS)
    assert {x["season_id"] for x in s if x["role"] == "held_out"} == set(HELDOUT_SEASONS)
    assert {x["season_id"] for x in s if x["role"] == "current"} == set(ids[8:])
    assert {x["season_id"] for x in s if x["is_irregular"]} == {"2019-20", "2020-21"}
    for x in s[:8]:
        assert [w["window_type"] for w in x["windows"]] == ["pre_asb", "post_asb"] and x["n_lineups"] > 10_000


def test_data_status_is_read_only_and_describes_the_season_in_progress(client):
    d = get(client, "/data-status")
    assert d["season_id"] == CURRENT_SEASON and d["freshness"] in ("current", "stale", "unknown")
    assert d["refresh_command"] == "python -m nba_lineups.refresh"
    if d["data_cutoff"]:
        with psycopg.connect(client.app.state.settings.database_url) as c:
            last = c.execute("SELECT max(game_date) FROM team_games WHERE season_id = %s", (CURRENT_SEASON,)).fetchone()[0]
            windows = c.execute("SELECT max(date_to) FROM stat_windows WHERE season_id = %s", (CURRENT_SEASON,)).fetchone()[0]
        assert last <= date.fromisoformat(d["data_cutoff"]) and windows <= date.fromisoformat(d["data_cutoff"])
    # no route can trigger a refresh: nothing but GET exists for it
    assert client.post("/api/v1/data-status").status_code == 405
    assert not [r for r in client.app.routes if "refresh" in getattr(r, "path", "")]


def test_current_season_predictions_are_provisional_with_baseline_and_intervals(client):
    page = get(client, f"/lineups?season={CURRENT_SEASON}&sort=pre_poss&order=desc&page_size=1")
    if not page["items"]:
        pytest.skip(f"{CURRENT_SEASON} not loaded")
    lid = page["items"][0]["lineup_id"]
    p = get(client, f"/lineups/{lid}/prediction")
    assert p["provisional"] is True and p["data_cutoff"] and p["season_used_for_training"] is False
    assert p["baselines"]["team_prior"] is not None and p["uncertainty"]["true_rating_interval_95"]
    assert any(n.startswith("PROVISIONAL") for n in p["notes"])
    assert get(client, f"/lineups/{lid}/prediction") == p                # reproducible
    old = get(client, "/lineups?season=2025-26&sort=pre_poss&order=desc&page_size=1")["items"][0]["lineup_id"]
    assert get(client, f"/lineups/{old}/prediction")["provisional"] is False


def test_teams(client):
    assert len(get(client, "/teams")) == 30 and len(get(client, "/teams?season=2025-26")) == 30
    get(client, "/teams?season=1999-00", 404)


# ---------------------------------------------------------------- lineups

def test_lineup_filters_sorting_and_pagination(client):
    q = "/lineups?season=2024-25&team_id=1610612738&min_pre_poss=30&min_post_poss=25&sort=post_net&page_size=20"
    p1, p2 = get(client, q), get(client, q + "&page=2")
    assert p1["total"] == p2["total"] and p1["total_pages"] == -(-p1["total"] // 20)
    ids1, ids2 = {x["lineup_id"] for x in p1["items"]}, {x["lineup_id"] for x in p2["items"]}
    assert ids1 and not ids1 & ids2
    nets = [x["post_break"]["net_rating"] for x in p1["items"] + p2["items"]]
    assert nets == sorted(nets, reverse=True)
    for x in p1["items"]:
        assert x["season_id"] == "2024-25" and x["team_id"] == 1610612738 and len(x["players"]) == 5
        assert min(x["pre_break"]["poss"], x["pre_break"]["opp_poss"]) >= 30
        assert min(x["post_break"]["poss"], x["post_break"]["opp_poss"]) >= 25
    assert get(client, q + "&page=999")["items"] == []


def test_lineup_ratings_and_change(client, lineup):
    for w in ("pre_break", "post_break"):
        b = lineup[w]
        assert b["off_rating"] == pytest.approx(100 * b["pts"] / b["poss"])
        assert b["def_rating"] == pytest.approx(100 * b["opp_pts"] / b["opp_poss"])
        assert b["net_rating"] == pytest.approx(b["off_rating"] - b["def_rating"])
    c = lineup["change"]
    assert c["net_rating"] == pytest.approx(lineup["post_break"]["net_rating"] - lineup["pre_break"]["net_rating"])
    assert c["net_rating_sampling_sd"] > 0 and isinstance(c["exceeds_noise"], bool)


def test_lineup_detail_and_season_total(client, lineup):
    d = get(client, f"/lineups/{lineup['lineup_id']}")
    assert d["players"] == lineup["players"]
    t = d["season_total"]
    assert t["poss"] == d["pre_break"]["poss"] + d["post_break"]["poss"]
    assert t["net_rating"] == pytest.approx(100 * t["pts"] / t["poss"] - 100 * t["opp_pts"] / t["opp_poss"])
    get(client, "/lineups/999999999", 404)
    get(client, "/lineups/999999999/prediction", 404)


def test_player_filter(client, lineup):
    a, b = (p["player_id"] for p in lineup["players"][:2])
    one = get(client, f"/lineups?player_id={a}&page_size=200")
    both = get(client, f"/lineups?player_id={a}&player_id={b}&season=2025-26&page_size=200")
    assert both["total"] <= one["total"] and both["total"] >= 1
    for x in both["items"]:
        assert {a, b} <= {p["player_id"] for p in x["players"]}
    assert get(client, "/lineups?season=2025-26&player_id=1")["total"] == 0          # nonexistent player


# ---------------------------------------------------------------- players and teams

def test_players(client, lineup):
    pid = lineup["players"][0]["player_id"]
    rows = get(client, f"/players?season=2025-26&team_id={lineup['team_id']}&page_size=200")["items"]
    me = next(r for r in rows if r["player_id"] == pid)
    assert me["pre_break"]["poss"] >= lineup["pre_break"]["poss"]           # pooled over all their lineups
    assert me["usage_pre_break"]["usg_pct"] is not None
    assert me["pre_break"]["on_off_net"] == pytest.approx(
        me["pre_break"]["net_rating"] - me["pre_break"]["off_court_net_rating"])
    name = lineup["players"][0]["player_name"]
    hits = get(client, f"/players?season=2025-26&search={name.split()[-1][:5]}")["items"]
    assert any(h["player_id"] == pid for h in hits)
    detail = get(client, f"/players/{pid}")
    assert any(s["season_id"] == "2025-26" for s in detail["seasons"])
    get(client, "/players/1", 404)
    get(client, "/players?season=1999-00", 404)


def test_traded_player_has_one_row_per_team(client):
    """Vucevic 2020-21 (the Phase 4 last_team_id example): every pre-break game for ORL; traded to CHI at the
    25 March deadline, after the early-March break. The player endpoint's last_team_id says CHI even for the
    pre-break window; lineup-derived rows put his pre-break minutes with ORL only."""
    d = get(client, "/players/202696?season=2020-21")
    teams = {s["team_abbreviation"]: s for s in d["seasons"]}
    assert set(teams) == {"ORL", "CHI"}
    assert teams["ORL"]["pre_break"]["minutes"] > 0 and teams["CHI"]["pre_break"] is None
    assert teams["CHI"]["post_break"]["minutes"] > 0


def test_team_stats(client):
    rows = get(client, "/teams/stats?season=2023-24")
    assert len(rows) == 30
    for t in rows:
        pre, post = t["pre_break"], t["post_break"]
        assert pre["wins"] + pre["losses"] == pre["games"] and pre["games"] + post["games"] == 82
        assert t["change"]["net_rating"] == pytest.approx(post["net_rating"] - pre["net_rating"])
    one = get(client, f"/teams/{rows[0]['team_id']}/stats?season=2023-24")
    assert one == rows[0]
    get(client, "/teams/1/stats?season=2023-24", 404)


# ---------------------------------------------------------------- predictions: equal to the frozen model

@pytest.mark.parametrize("season", ["2023-24", "2025-26"])
def test_api_predictions_equal_frozen_model(client, predictor, season):
    """Independent recomputation: load the artifact afresh and predict with the Phase 6 code path."""
    model = final.load(PROJECT_ROOT / "models" / "final")
    with psycopg.connect(client.app.state.settings.database_url) as c:
        tables = raw.load_pre_break_tables(c, [season], key=predictor._key)
        targets = raw.load_targets(c, [season], key=predictor._key)
    expected = model.predict(tables, targets)
    sample = targets.sample(25, random_state=0)
    for lid in sample.lineup_id:
        p = get(client, f"/lineups/{lid}/prediction")
        assert p["predicted_net_rating"] == pytest.approx(expected[lid], abs=1e-9)
        assert p["intercept"] + sum(c["contribution"] for c in p["contributions"]) == pytest.approx(
            p["predicted_net_rating"], abs=1e-9)
        assert p["season_used_for_training"] is (season in DEV_SEASONS)


def test_served_predictions_reproduce_holdout_evaluation(client, predictor):
    """Served predictions + team prior, scored on the held-out targets, give the recorded held-out RMSEs."""
    with psycopg.connect(client.app.state.settings.database_url) as c:
        targets = raw.load_targets(c, HELDOUT_SEASONS, key=predictor._key)
        frames = [predictor.season(c, s).frame for s in HELDOUT_SEASONS]
    f = targets.join(pd.concat(frames)[["predicted", "team_prior"]], on="lineup_id")
    assert len(f) == HOLDOUT["pooled"]["n"] and f.predicted.notna().all()
    for name, d in [(s, f[f.season_id == s]) for s in HELDOUT_SEASONS] + [("pooled", f)]:
        m = HOLDOUT[name]["metrics"]
        assert round(weighted_rmse(d.y, d.predicted, d.w), 4) == m["linear|weighted|rmse"][0]
        assert round(weighted_rmse(d.y, d.team_prior, d.w), 4) == m["team_prior|weighted|rmse"][0]


def test_prediction_payload(client, lineup):
    p = get(client, f"/lineups/{lineup['lineup_id']}/prediction?possessions=200&include_observed=true")
    assert p["baselines"]["team_prior"] and p["model_minus_team_prior"] == pytest.approx(
        p["predicted_net_rating"] - p["baselines"]["team_prior"])
    u = p["uncertainty"]
    assert u["possessions"] == 200 and u["total_sd"] > u["sampling_sd"] > 0 and u["model_sd"] > 0
    assert any("GIVEN that its coach plays it after the break" in n for n in p["notes"])
    assert any("indistinguishable from the team prior" in n for n in p["notes"])
    assert p["pre_break"]["poss"] == lineup["pre_break"]["poss"]
    o = p["observed_post_break"]
    assert o["poss"] == lineup["post_break"]["poss"] and o["net_rating"] == pytest.approx(lineup["post_break"]["net_rating"])
    assert "observed_post_break" not in get(client, f"/lineups/{lineup['lineup_id']}/prediction") or \
        get(client, f"/lineups/{lineup['lineup_id']}/prediction")["observed_post_break"] is None


def test_custom_lineup_predictions(client, lineup, predictor):
    ids = [p["player_id"] for p in lineup["players"]]
    body = {"season_id": "2025-26", "team_id": lineup["team_id"], "player_ids": ids[::-1]}
    same = client.post(V1 + "/predictions", json=body).json()
    assert same["lineup_id"] == lineup["lineup_id"]
    assert same["predicted_net_rating"] == get(client, f"/lineups/{lineup['lineup_id']}/prediction")["predicted_net_rating"]

    # swap in a teammate so the five never played together
    with client.app.state.pool.connection() as c:
        sd = predictor.season(c, "2025-26")
    roster = sorted(set(sd.tables.members.loc[sd.tables.members.team_id == lineup["team_id"], "player_id"]) - set(ids))
    new = next(ids[:4] + [int(r)] for r in roster if (lineup["team_id"], tuple(sorted(ids[:4] + [int(r)]))) not in sd.by_key)
    r = client.post(V1 + "/predictions", json=body | {"player_ids": new})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["lineup_id"] is None and p["pre_break"]["poss"] == 0 and p["pre_break"]["reliability"] == 0
    assert any("No pre-break minutes together" in n for n in p["notes"])
    assert p["intercept"] + sum(c["contribution"] for c in p["contributions"]) == pytest.approx(p["predicted_net_rating"])

    bad = client.post(V1 + "/predictions", json=body | {"team_id": 1610612737 if lineup["team_id"] != 1610612737 else 1610612738})
    assert bad.status_code == 400 and bad.json()["error"]["details"]["not_on_team"]
    assert client.post(V1 + "/predictions", json=body | {"season_id": "1999-00"}).status_code == 404
    assert client.post(V1 + "/predictions", json=body | {"team_id": 42}).status_code == 404


def test_team_predictions_ranked(client, lineup):
    r = get(client, f"/teams/{lineup['team_id']}/predictions?season=2025-26&min_pre_poss=50&page_size=10")
    preds = [x["predicted_net_rating"] for x in r["items"]]
    assert preds == sorted(preds, reverse=True) and r["total"] >= len(preds) > 0
    assert all(x["pre_break"]["poss"] >= 50 and "team_prior" in x["baselines"] for x in r["items"])


# ---------------------------------------------------------------- leakage and safety

class RecordingConnection:
    """Wraps a connection and records every SQL statement executed through it."""

    def __init__(self, conn):
        self._c, self.sql = conn, []

    def execute(self, query, params=None, **kw):
        self.sql.append(str(query))
        return self._c.execute(query, params, **kw)

    def cursor(self, *a, **kw):
        cur = self._c.cursor(*a, **kw)
        outer = self

        class C:
            def __enter__(self):
                cur.__enter__()
                return self

            def __exit__(self, *e):
                return cur.__exit__(*e)

            def execute(self, q, p=None):
                outer.sql.append(str(q))
                return cur.execute(q, p)

            def __getattr__(self, n):
                return getattr(cur, n)
        return C()


@pytest.mark.parametrize("season", ["2024-25", CURRENT_SEASON])
def test_prediction_features_read_pre_break_only(client, predictor, season):
    """Rebuild a season's predictions through a recording connection: no statement may touch post-break rows.
    Includes the season in progress (provisional predictions)."""
    with psycopg.connect(client.app.state.settings.database_url) as c:
        if c.execute("SELECT 1 FROM seasons WHERE season_id = %s", (season,)).fetchone() is None:
            pytest.skip(f"{season} not loaded")
        rec = RecordingConnection(c)
        for k in [k for k in predictor._cache if k[0] == season]:
            predictor._cache.pop(k)
        sd = predictor.season(rec, season)
    stats_sql = [q for q in rec.sql if "window_stats" in q]
    assert stats_sql and all("pre_asb" in q and "post_asb" not in q for q in stats_sql)
    assert not any("last_team_id" in q or "v_lineup_window_ratings" in q for q in rec.sql)
    assert (sd.tables.lineups.window_type == "pre_asb").all() and (sd.tables.usage.window_type == "pre_asb").all()


def test_leakage_guards_still_hold(client):
    with psycopg.connect(client.app.state.settings.database_url) as c:
        with pytest.raises(HeldOutDataError):
            raw.load_pre_break_tables(c, ["2025-26"])                  # no key -> refused
        with pytest.raises(HeldOutDataError):
            raw.load_targets(c, ["2024-25"])
        tables = client.app.state.predictor.season(c, "2025-26").tables      # the API's own (keyed) tables
    with pytest.raises(HeldOutDataError):
        FeatureBuilder().fit(tables, ["2025-26"])                         # a key never permits fitting


def test_api_database_sessions_are_read_only(client):
    with client.app.state.pool.connection() as c:
        assert c.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert c.execute("SHOW statement_timeout").fetchone()[0] == "10s"
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("UPDATE teams SET team_name = team_name WHERE false")   # would change nothing anyway


def test_health_ok_and_model_unchanged(client, predictor):
    h = client.get("/health")
    assert h.status_code == 200 and h.json() == {"status": "ok", "mode": "full", "database": "ok", "model": "ok",
                                                 "model_artifact_sha256": predictor.spec["artifact"]["sha256"]}
    assert predictor.verify() and final.sha256(predictor.artifact_path) == predictor.spec["artifact"]["sha256"]
