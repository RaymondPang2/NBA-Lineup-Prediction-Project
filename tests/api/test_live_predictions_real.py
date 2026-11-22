"""Provisional predictions for the season in progress, against the REAL warehouse and the frozen model:
partial pre-break windows are handled, recorded and hypothetical fives work, results are reproducible,
nothing after the data cutoff is read, and the historical predictions and evaluation are unchanged."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import psycopg
import pytest

from nba_lineups.config import CURRENT_SEASON, PROJECT_ROOT
from nba_lineups.modeling import partial

pytestmark = pytest.mark.realdata
V1 = "/api/v1"


def get(client, url, status=200):
    r = client.get(V1 + url)
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture(scope="module")
def live(client, predictor):
    with psycopg.connect(client.app.state.settings.database_url) as c:
        if c.execute("SELECT 1 FROM seasons WHERE season_id = %s", (CURRENT_SEASON,)).fetchone() is None:
            pytest.skip(f"{CURRENT_SEASON} not loaded")
        return predictor.season(c, CURRENT_SEASON)


def test_partial_window_inputs_are_complete_and_finite(client, predictor, live):
    f = live.frame
    with psycopg.connect(client.app.state.settings.database_url) as c:
        n = c.execute("SELECT count(*) FROM lineups WHERE season_id = %s", (CURRENT_SEASON,)).fetchone()[0]
    assert len(f) == n                                          # every recorded lineup is scored
    assert np.isfinite(f.predicted).all() and np.isfinite(f.team_prior).all()
    z = predictor.model.pipeline[:-1].transform(f[list(predictor.model.features)])
    assert np.isfinite(np.asarray(z, float)).all()              # imputer + scaler accept every partial-window row
    assert (live.tables.lineups.window_type == "pre_asb").all()
    assert 0 < live.progress["fraction"] < 1                    # genuinely partial window


def test_inputs_never_extend_past_the_data_cutoff(client, live):
    status = get(client, "/data-status")
    with psycopg.connect(client.app.state.settings.database_url) as c:
        last_game = c.execute("SELECT max(game_date) FROM team_games WHERE season_id = %s", (CURRENT_SEASON,)).fetchone()[0]
        windows = c.execute("SELECT window_type, date_to FROM stat_windows WHERE season_id = %s", (CURRENT_SEASON,)).fetchall()
    cutoff = date.fromisoformat(status["data_cutoff"])
    assert live.data_cutoff <= cutoff and last_game <= cutoff and all(d <= cutoff for _, d in windows)


def test_recorded_and_hypothetical_fives_are_provisional_with_baseline_and_intervals(client, live):
    lid = int(live.frame[np.minimum(live.frame.lu_poss, live.frame.lu_opp_poss) >= 50].predicted.idxmax())
    rec = get(client, f"/lineups/{lid}/prediction")
    team = rec["team_id"]
    roster = [p["player_id"] for p in get(client, f"/players?season={CURRENT_SEASON}&team_id={team}&page_size=200"
                                                  "&sort=pre_minutes&order=desc")["items"]]
    # a five that never played together: the five least-used players with pre-break minutes, if unseen
    for start in range(len(roster) - 4):
        five = sorted(roster[start:start + 5])
        if (team, tuple(five)) not in live.by_key:
            break
    else:
        pytest.skip("every candidate five was a recorded lineup")
    r = client.post(V1 + "/predictions", json={"season_id": CURRENT_SEASON, "team_id": team, "player_ids": five,
                                                "possessions": 100})
    assert r.status_code == 200, r.text
    hyp = r.json()
    for p in (rec, hyp):
        assert p["provisional"] is True and p["data_cutoff"] == str(live.data_cutoff)
        assert p["season_progress"]["fraction"] == pytest.approx(live.progress["fraction"])
        assert np.isfinite(p["predicted_net_rating"]) and np.isfinite(p["baselines"]["team_prior"])
        assert p["model_minus_team_prior"] == pytest.approx(p["predicted_net_rating"] - p["baselines"]["team_prior"])
        u = p["uncertainty"]
        assert u["true_rating_interval_95"]["lo"] < p["predicted_net_rating"] < u["true_rating_interval_95"]["hi"]
        assert any("Incomplete pre-break information reduces accuracy" in n for n in p["notes"])
        assert p.get("observed_post_break") is None
    assert rec["lineup_id"] == lid and hyp["lineup_id"] is None


def test_predictions_are_reproducible_across_calls_and_cache_rebuilds(client, predictor, live):
    lid = int(live.frame.index[0])
    a = get(client, f"/lineups/{lid}/prediction")
    for k in [k for k in predictor._cache if k[0] == CURRENT_SEASON]:
        predictor._cache.pop(k)                                 # force a recompute from the warehouse
    b = get(client, f"/lineups/{lid}/prediction")
    assert a == b
    with psycopg.connect(client.app.state.settings.database_url) as c:
        again = predictor.season(c, CURRENT_SEASON).frame
    pd.testing.assert_series_equal(again.predicted.sort_index(), live.frame.predicted.sort_index())


def test_volume_counterfactual_is_only_a_diagnostic_and_identity_at_full_volume(client, predictor):
    """partial.scaled_tables with factor 1 reproduces the served predictions exactly (sanity of the audit tool),
    and the served frame is never the counterfactual."""
    with psycopg.connect(client.app.state.settings.database_url) as c:
        sd = predictor.season(c, "2025-26")
    same = partial.scaled_tables(sd.tables, {t: 1.0 for t in sd.frame.team_id.unique()})
    re = predictor._score(same, sd.frame.reset_index()[["lineup_id", "season_id", "team_id"]])
    np.testing.assert_allclose(re.predicted.sort_index(), sd.frame.predicted.sort_index(), atol=1e-9)


def test_historical_predictions_and_evaluation_are_unchanged(client, predictor):
    """The Phase 9 export froze every historical prediction; the served values must still equal it, and the
    held-out evaluation still names the same frozen artifact."""
    path = PROJECT_ROOT / "data" / "powerbi" / "csv" / "fact_prediction.csv"
    if not path.exists():
        pytest.skip("Phase 9 export not present")
    old = pd.read_csv(path)
    old = old[old.season_id.isin(["2024-25", "2025-26"])].set_index("lineup_id")
    with psycopg.connect(client.app.state.settings.database_url) as c:
        now = pd.concat([predictor.season(c, s).frame for s in ("2024-25", "2025-26")])
    common = old.index.intersection(now.index)
    assert len(common) > 1000
    np.testing.assert_allclose(now.predicted[common], old.predicted_net[common], atol=1e-6)
    spec = json.loads((PROJECT_ROOT / "models/final/frozen_spec.json").read_text())
    assert predictor.artifact_sha256 == spec["artifact"]["sha256"] and predictor.verify()


def test_audit_report_matches_the_frozen_model():
    path = PROJECT_ROOT / "reports" / "live" / "partial_window_audit.json"
    r = json.loads(path.read_text())
    spec = json.loads((PROJECT_ROOT / "models/final/frozen_spec.json").read_text())
    assert r["model_artifact_sha256"] == spec["artifact"]["sha256"] and r["model_unchanged"] is True
    assert r["heldout_volume_backtest"]["rmse_volume_shrunk"] > r["heldout_volume_backtest"]["rmse_full_window"]
