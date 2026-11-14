"""Phase 6 models: in-fold preprocessing, nested chronological tuning, selection rule, final bundle."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from nba_lineups.modeling import evaluation as ev
from nba_lineups.modeling import final, models, tuning
from nba_lineups.modeling.models import FEATURES, SPECS, VIFSelector, fit_model
from nba_lineups.modeling.splits import expanding_window_folds

from . import synthetic


@pytest.fixture
def small_specs(monkeypatch):
    """Small grids so the integration tests run in seconds."""
    small = {
        "linear": SPECS["linear"],
        "ridge": dataclasses.replace(SPECS["ridge"], grid=({"alpha": 0.1}, {"alpha": 10.0}, {"alpha": 1000.0})),
        "forest": dataclasses.replace(SPECS["forest"], grid=(
            {"max_depth": 3, "min_samples_leaf": 10, "max_features": 0.5, "n_estimators": 20},
            {"max_depth": 5, "min_samples_leaf": 20, "max_features": 0.5, "n_estimators": 20}),
            default={"max_depth": 3, "min_samples_leaf": 10, "max_features": 0.5, "n_estimators": 20}),
    }
    for mod in (models, tuning, final):
        monkeypatch.setattr(mod, "SPECS", small)
    return small


@pytest.fixture(scope="module")
def data():
    return synthetic.make()


# ------------------------------------------------------------------ preprocessing
def test_vif_selector_removes_an_exact_linear_combination_and_ignores_y():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(300, 3)), columns=["off", "def", "other"])
    X["net"] = X["off"] - X["def"] + rng.normal(0, 1e-3, 300)       # near-exact: net = off - def
    a = VIFSelector().fit(X)
    b = VIFSelector().fit(X, y=rng.normal(size=300))
    assert a.selected_ == b.selected_                                 # unsupervised
    assert len(a.selected_) == 3 and "other" in a.selected_
    assert ev_vif_ok(X[a.selected_])


def ev_vif_ok(X: pd.DataFrame) -> bool:
    return bool((models.vif(X.to_numpy()) <= models.VIF_THRESHOLD).all())


def test_vif_selector_drops_constant_columns():
    X = pd.DataFrame({"a": np.arange(10.0), "b": np.ones(10), "c": np.arange(10.0) ** 2})
    assert "b" not in VIFSelector().fit(X).selected_


def test_preprocessing_is_fitted_on_training_rows_only(data):
    tables, targets = data
    fold = expanding_window_folds(synthetic.SEASONS)[-1]
    train, val, _ = tuning.FoldCache(tables, targets).get(fold)
    pipe = fit_model(SPECS["ridge"], {"alpha": 1.0}, train)
    np.testing.assert_allclose(pipe.named_steps["scale"].mean_, train[FEATURES].mean().to_numpy())
    np.testing.assert_allclose(pipe.named_steps["impute"].statistics_, train[FEATURES].median().to_numpy())
    lr = fit_model(SPECS["linear"], {}, train)
    assert lr.named_steps["select"].selected_ == VIFSelector().fit(train[FEATURES]).selected_


def test_weights_are_normalized_so_alpha_is_scale_free(data):
    tables, targets = data
    fold = expanding_window_folds(synthetic.SEASONS)[-1]
    train, _, _ = tuning.FoldCache(tables, targets).get(fold)
    a = fit_model(SPECS["ridge"], {"alpha": 5.0}, train).named_steps["model"].coef_
    b = fit_model(SPECS["ridge"], {"alpha": 5.0}, train.assign(w=train.w * 37)).named_steps["model"].coef_
    np.testing.assert_allclose(a, b)


# ------------------------------------------------------------------ nested tuning: leakage
def test_tuning_never_sees_the_outer_validation_season(data, small_specs, monkeypatch):
    tables, targets = data
    cache = tuning.FoldCache(tables, targets)
    seen = []
    real_get = cache.get
    monkeypatch.setattr(cache, "get", lambda f: seen.append(f) or real_get(f))
    train_seasons = synthetic.SEASONS[:2]
    params, curve = tuning.tune(small_specs["ridge"], cache, train_seasons)
    assert seen and all(set(f.train_seasons + (f.val_season,)) <= set(train_seasons) for f in seen)
    assert all(max(f.train_seasons) < f.val_season for f in seen)
    assert params == small_specs["ridge"].grid[int(curve.weighted_rmse.to_numpy().argmin())]


def test_tuning_breaks_exact_ties_toward_the_first_simplest_entry(data, monkeypatch):
    tables, targets = data
    spec = dataclasses.replace(SPECS["ridge"], grid=({"alpha": 1.0}, {"alpha": 1.0}, {"alpha": 1.0}))
    params, curve = tuning.tune(spec, tuning.FoldCache(tables, targets), synthetic.SEASONS[:2])
    assert curve.weighted_rmse.nunique() == 1 and params == {"alpha": 1.0}
    simplest = models.RF_GRID[0]
    assert simplest["max_depth"] == 3 and simplest["min_samples_leaf"] == 200 and simplest["max_features"] == 0.33


def test_one_training_season_uses_the_preregistered_default(data, small_specs):
    tables, targets = data
    params, curve = tuning.tune(small_specs["forest"], tuning.FoldCache(tables, targets), synthetic.SEASONS[:1])
    assert params == small_specs["forest"].default and curve is None


def test_model_predictions_do_not_depend_on_validation_targets(data, small_specs):
    tables, targets = data
    folds = expanding_window_folds(synthetic.SEASONS)
    last = folds[-1].val_season
    scrambled = targets.copy()
    v = scrambled.season_id == last
    scrambled.loc[v, "y"] = -scrambled.loc[v, "y"] * 3 + 50
    a = tuning.run_models(tuning.FoldCache(tables, targets), folds, "a").oof
    b = tuning.run_models(tuning.FoldCache(tables, scrambled), folds, "b").oof
    for m in small_specs:
        np.testing.assert_allclose(a[m], b[m])


# ------------------------------------------------------------------ integration
def test_nested_cv_produces_complete_out_of_fold_predictions(data, small_specs):
    tables, targets = data
    folds = expanding_window_folds(synthetic.SEASONS)
    run = tuning.run_models(tuning.FoldCache(tables, targets), folds, "test")
    val_rows = targets[targets.season_id.isin([f.val_season for f in folds])]
    assert len(run.oof) == len(val_rows) and set(run.oof.lineup_id) == set(val_rows.lineup_id)
    for m in small_specs:
        assert np.isfinite(run.oof[m]).all()
    assert len(run.folds) == len(folds) * len(small_specs)
    assert not run.folds[run.folds.val_season == folds[0].val_season].tuned.any()   # 1 training season: default


# ------------------------------------------------------------------ selection rule
def _oof(rng, n=600, gap=0.0):
    y = rng.normal(0, 20, n)
    signal = y * 0.2
    return pd.DataFrame({"season_id": "2023-24", "team_id": rng.integers(0, 30, n), "y": y, "w": rng.uniform(25, 300, n),
                         "linear": signal + rng.normal(0, 1, n) + gap, "ridge": signal + rng.normal(0, 1, n) + gap,
                         "forest": signal + rng.normal(0, 1, n)})


def test_one_standard_error_rule():
    order = ["linear", "ridge", "forest"]
    rmse = {"linear": 21.80, "ridge": 21.78, "forest": 21.75}
    assert final.one_se_choice(rmse, {"linear": 0.06, "ridge": 0.01, "forest": 0.0}, order) == "linear"   # within 1 SE
    assert final.one_se_choice(rmse, {"linear": 0.04, "ridge": 0.04, "forest": 0.0}, order) == "ridge"
    assert final.one_se_choice(rmse, {"linear": 0.01, "ridge": 0.01, "forest": 0.0}, order) == "forest"


def test_selection_picks_the_best_model_when_it_is_clearly_better():
    sel = final.select_model(_oof(np.random.default_rng(2), gap=15.0), n_boot=200)
    assert sel["best"] == sel["chosen"] == "forest"


# ------------------------------------------------------------------ metrics added in Phase 6
def test_paired_differences_and_calibration_slope_by_hand():
    df = pd.DataFrame({"y": [0.0, 2.0, 4.0], "w": [1.0, 1.0, 1.0], "a": [0.0, 2.0, 4.0], "b": [1.0, 2.0, 3.0]})
    d = ev.paired_differences(df, ["a"], ["b"])
    rmse_b = np.sqrt(2 / 3)
    assert d["a|weighted|rmse_minus_b"] == pytest.approx(0 - rmse_b)
    assert d["a|unweighted|mae_minus_b"] == pytest.approx(0 - 2 / 3)
    assert d["a|weighted|calibration_slope"] == pytest.approx(1.0)
    assert ev.calibration_slope(df.y, df.b) == pytest.approx(2.0)     # predictions too compressed -> slope > 1


# ------------------------------------------------------------------ final bundle
def test_final_bundle_round_trips_and_records_the_plan(data, small_specs, tmp_path):
    tables, targets = data
    targets_dev = targets.copy()
    model = final.fit_final("ridge", {"alpha": 10.0}, tables, targets_dev)
    sel = {"chosen": "ridge", "best": "ridge"}
    spec = final.freeze(model, tmp_path, sel, {"note": "test"})
    assert spec["status"] == "frozen" and spec["artifact"]["sha256"] == final.sha256(tmp_path / final.ARTIFACT)
    assert "no_retuning" in spec["evaluation_plan"] and spec["model"]["trained_seasons"] == list(model.trained_seasons)
    loaded = final.load(tmp_path)
    t = targets[targets.season_id == synthetic.SEASONS[-1]]
    pd.testing.assert_series_equal(model.predict(tables, t), loaded.predict(tables, t))
    assert loaded.baseline_params == model.baseline_params


def test_final_fit_refuses_held_out_targets(data):
    tables, targets = data
    with pytest.raises(ValueError):
        final.fit_final("linear", {}, tables, targets.assign(season_id="2024-25"))
