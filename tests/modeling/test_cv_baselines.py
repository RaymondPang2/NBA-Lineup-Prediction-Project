"""Chronological folds, fold isolation of fitted steps, baselines and metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nba_lineups.analysis.data import HeldOutDataError
from nba_lineups.config import DEV_SEASONS, HELDOUT_SEASONS, IRREGULAR_SEASONS
from nba_lineups.modeling import baselines as bl
from nba_lineups.modeling import cv
from nba_lineups.modeling import evaluation as ev
from nba_lineups.modeling.features import FeatureBuilder
from nba_lineups.modeling.splits import expanding_window_folds

from . import synthetic


# ------------------------------------------------------------------ folds
def test_expanding_window_never_trains_on_the_future_or_held_out():
    folds = expanding_window_folds()
    assert [f.val_season for f in folds] == list(DEV_SEASONS[1:])
    for f in folds:
        assert all(s < f.val_season for s in f.train_seasons)
        assert list(f.train_seasons) == [s for s in DEV_SEASONS if s < f.val_season]   # expanding
        assert not set(f.train_seasons + (f.val_season,)) & set(HELDOUT_SEASONS)


def test_regular_only_variant_drops_irregular_seasons_everywhere():
    folds = expanding_window_folds(exclude_irregular=True)
    assert [f.val_season for f in folds] == ["2021-22", "2022-23", "2023-24"]
    assert all(not set(f.train_seasons) & IRREGULAR_SEASONS for f in folds)


def test_folds_refuse_held_out_and_unordered_seasons():
    with pytest.raises(HeldOutDataError):
        expanding_window_folds(list(DEV_SEASONS) + ["2024-25"])
    with pytest.raises(ValueError):
        expanding_window_folds(list(reversed(DEV_SEASONS)))


# ------------------------------------------------------------------ fold isolation (spy)
def test_cv_fits_every_learned_step_on_training_seasons_only(monkeypatch):
    tables, targets = synthetic.make()
    calls = []

    class SpyBuilder(FeatureBuilder):
        def fit(self, t, train_seasons):
            calls.append(tuple(sorted(train_seasons)))
            return super().fit(t, train_seasons)

    fits = []
    real_fit_predict = bl.fit_predict

    def spy_fit_predict(train, val):
        fits.append((set(train.season_id), set(val.season_id)))
        return real_fit_predict(train, val)

    monkeypatch.setattr(cv, "FeatureBuilder", SpyBuilder)
    monkeypatch.setattr(cv.baselines, "fit_predict", spy_fit_predict)
    folds = expanding_window_folds(synthetic.SEASONS)
    run = cv.run_baselines(tables, targets, folds, "test")
    assert calls == [f.train_seasons for f in folds]
    for (tr, va), f in zip(fits, folds):
        assert tr == set(f.train_seasons) and va == {f.val_season} and max(tr) < f.val_season
    assert set(run.oof.season_id) == {f.val_season for f in folds}


def test_baselines_are_unaffected_by_validation_targets():
    tables, targets = synthetic.make()
    fold = expanding_window_folds(synthetic.SEASONS)[-1]
    train, val, _ = cv.fold_frames(tables, targets, fold)
    p1, params1 = bl.fit_predict(train, val)
    p2, params2 = bl.fit_predict(train, val.assign(y=val.y * -5 + 100))
    pd.testing.assert_frame_equal(p1, p2)
    assert params1 == params2


# ------------------------------------------------------------------ baselines
def _frame(season, y, w, **cols):
    n = len(y)
    return pd.DataFrame({"season_id": season, "y": y, "w": w, "team_net_loo": cols.get("team", np.zeros(n)),
                         "lu_net_eb_team": cols.get("eb", np.zeros(n)), "p_net_rating_eb_mean": cols.get("p", np.zeros(n)),
                         "lu_net_raw": cols.get("raw", np.full(n, np.nan))})


def test_league_mean_and_offsets_are_possession_weighted_training_quantities():
    train = _frame("2018-19", [0.0, 10.0], [1.0, 3.0], team=np.array([-2.0, 2.0]))
    val = _frame("2019-20", [5.0], [1.0], team=np.array([1.0]), raw=np.array([np.nan]))
    p, params = bl.fit_predict(train, val)
    assert params["league_mean"] == pytest.approx(7.5)                 # (0*1 + 10*3) / 4
    assert params["team_prior_offset"] == pytest.approx((2 * 1 + 8 * 3) / 4)
    assert p.team_prior.iloc[0] == pytest.approx(1.0 + 6.5)
    assert p.raw_lineup.iloc[0] == 1.0                                 # no history -> team prior (no offset)
    a, b = params["team_prior_calibrated"]["intercept"], params["team_prior_calibrated"]["slope"]
    assert a + b * -2 == pytest.approx(0.0) and a + b * 2 == pytest.approx(10.0)   # 2 points: exact fit


def test_baselines_refuse_overlapping_seasons():
    f = _frame("2018-19", [1.0], [1.0])
    with pytest.raises(ValueError):
        bl.fit_predict(f, f)


# ------------------------------------------------------------------ metrics
def test_regression_metrics_by_hand():
    m = ev.regression_metrics([0.0, 2.0], [1.0, 1.0], [1.0, 3.0])
    # weighted mean y = 1.5; SST = (1*2.25 + 3*0.25)/4 = 0.75; MSE = 1
    assert m["mae"] == pytest.approx(1.0) and m["rmse"] == pytest.approx(1.0)
    assert m["r2"] == pytest.approx(1 - 1 / 0.75)
    u = ev.regression_metrics([0.0, 2.0], [1.0, 1.0])
    assert u["r2"] == pytest.approx(0.0)


def test_noise_floor_formula():
    df = pd.DataFrame({"k": [10_000.0] * 2, "post_poss": [100, 100], "post_opp_poss": [100, 100], "y": [0.0, 10.0]})
    f = ev.noise_floor(df)
    assert f["rmse_floor"] == pytest.approx(np.sqrt(200))             # K*h = 10000 * (1/100 + 1/100)
    assert f["mae_floor"] == pytest.approx(np.sqrt(2 / np.pi * 200))
    assert f["r2_ceiling"] == pytest.approx(1 - 200 / 25)             # Var(y) = 25


def test_noise_floor_is_what_a_perfect_predictor_achieves():
    rng = np.random.default_rng(3)
    n, k = 200_000, 14_500.0
    poss = rng.integers(25, 400, n)
    theta = rng.normal(2, 6, n)
    y = theta + rng.normal(0, np.sqrt(k * 2 / poss))
    df = pd.DataFrame({"y": y, "theta": theta, "k": k, "post_poss": poss, "post_opp_poss": poss, "w": poss.astype(float)})
    for w in (None, df.w):
        floor = ev.noise_floor(df, w)
        m = ev.regression_metrics(df.y, df.theta, w)
        assert m["rmse"] == pytest.approx(floor["rmse_floor"], rel=0.01)
        assert m["mae"] == pytest.approx(floor["mae_floor"], rel=0.01)
        assert m["r2"] == pytest.approx(floor["r2_ceiling"], abs=0.01)


def test_metric_table_gains_are_paired_differences():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"y": rng.normal(0, 10, 50), "w": rng.uniform(25, 200, 50), "k": 14_500.0,
                       "post_poss": 100, "post_opp_poss": 100})
    df["league_mean"], df["team_prior"] = 0.0, df.y * 0.3
    t = ev.metric_table(df, ["league_mean", "team_prior"])
    for wt in ev.WEIGHTINGS:
        assert t[f"team_prior|{wt}|rmse_gain_lm"] == pytest.approx(t[f"league_mean|{wt}|rmse"] - t[f"team_prior|{wt}|rmse"])
        assert t[f"team_prior|{wt}|rmse_gain_tp"] == 0
    assert t["league_mean|weighted|skill_lm"] == 0


def test_weighted_corr_matches_numpy_when_unweighted():
    rng = np.random.default_rng(1)
    x, y = rng.normal(size=100), rng.normal(size=100)
    assert ev.weighted_corr(x, y, np.ones(100)) == pytest.approx(np.corrcoef(x, y)[0, 1])
