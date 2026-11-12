"""FeatureBuilder: correctness by hand, shrinkage behaviour, and leakage guards (synthetic data)."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from nba_lineups.analysis.data import HeldOutDataError
from nba_lineups.modeling import raw
from nba_lineups.modeling.features import FIT_MIN_POSS, FeatureBuilder
from nba_lineups.modeling.registry import AUXILIARY, FEATURE_NAMES

from . import synthetic

TRAIN = ("2018-19", "2019-20")
VAL = "2020-21"


@pytest.fixture(scope="module")
def data():
    return synthetic.make()


@pytest.fixture(scope="module")
def fitted(data):
    tables, targets = data
    b = FeatureBuilder().fit(tables, TRAIN)
    return b, b.transform(tables, targets)


def _rebuild(tables: raw.PreBreakTables, lineups: pd.DataFrame | None = None, usage: pd.DataFrame | None = None):
    return raw.build_tables(tables.lineups if lineups is None else lineups, tables.members,
                            tables.usage if usage is None else usage)


# ------------------------------------------------------------------ correctness
def test_columns_match_registry_and_nothing_is_missing(data, fitted):
    _, targets = data
    _, X = fitted
    assert list(X.columns[:len(FEATURE_NAMES)]) == list(FEATURE_NAMES)
    assert set(AUXILIARY) <= set(X.columns)
    assert len(X) == len(targets) and set(X.index) == set(targets.lineup_id)
    assert not X[list(FEATURE_NAMES)].isna().any().any()


def test_on_court_plus_off_court_equals_team_totals(data):
    tables, _ = data
    pt = tables.player_team
    for c in ("poss", "opp_poss", "pts", "opp_pts"):
        assert (pt[f"on_{c}"] + pt[f"off_{c}"] == pt[f"team_{c}"]).all()
    # spot check one player's on-court possessions by hand
    row = pt.iloc[0]
    ids = tables.members[tables.members.player_id == row.player_id].lineup_id
    lw = tables.lineups[(tables.lineups.season_id == row.season_id) & (tables.lineups.team_id == row.team_id)]
    assert lw[lw.lineup_id.isin(ids)].poss.sum() == row.on_poss


def test_team_prior_leaves_the_lineup_out(data, fitted):
    tables, _ = data
    _, X = fitted
    lid = X[X.lu_poss > 50].index[0]
    lw = tables.lineups
    me = lw[lw.lineup_id == lid].iloc[0]
    others = lw[(lw.season_id == me.season_id) & (lw.team_id == me.team_id) & (lw.lineup_id != lid)]
    expected = 100 * others.pts.sum() / others.poss.sum() - 100 * others.opp_pts.sum() / others.opp_poss.sum()
    assert X.loc[lid, "team_net_loo"] == pytest.approx(expected)


def test_lineup_without_history_gets_exactly_the_team_prior(fitted):
    b, X = fitted
    none = X[X.lu_no_history == 1]
    assert len(none) > 0
    assert np.allclose(none.lu_net_eb_team, none.team_net_loo + b.lineup_vc_.mu)
    assert (none.lu_reliability == 0).all() and none.lu_net_raw.isna().all()
    # "No history" = rating undefined: no possessions on offense OR on defense (a few lineups have one end only).
    assert ((none.lu_poss == 0) | (none.lu_opp_poss == 0)).all()
    assert np.allclose(none.lu_log_poss, np.log1p(none.lu_poss))


def test_shrinkage_pulls_toward_prior_and_less_with_more_data(fitted):
    b, X = fitted
    h = X[X.lu_no_history == 0]
    prior = h.team_net_loo + b.lineup_vc_.mu
    assert (np.abs(h.lu_net_eb_team - prior) <= np.abs(h.lu_net_raw - prior) + 1e-9).all()
    rel = b.lineup_vc_.reliability_at(np.array([10, 100, 1000]))
    assert rel[0] < rel[1] < rel[2]


def test_player_without_any_pre_break_data_gets_prior_and_is_counted(data, fitted):
    tables, _ = data
    b, X = fitted
    newcomers = tables.members[tables.members.player_id >= 999_000].lineup_id.unique()
    assert len(newcomers) > 0
    assert (X.loc[X.index.isin(newcomers), "p_n_no_history"] >= 1).all()
    assert (X.loc[X.index.isin(newcomers), "p_n_new_to_team"] >= 1).all()
    m = b.player_models_["net_rating"]
    assert m.prior(np.array([0.0]))[0] == pytest.approx(m.vc.beta[0] + m.vc.beta[1] * np.log(FIT_MIN_POSS))


def test_pair_familiarity_by_hand(data, fitted):
    tables, _ = data
    _, X = fitted
    lid = X.index[0]
    five = sorted(tables.members[tables.members.lineup_id == lid].player_id)
    season, team = X.loc[lid, ["season_id", "team_id"]]
    lw = tables.lineups[(tables.lineups.season_id == season) & (tables.lineups.team_id == team)]
    vals = []
    for i in range(5):
        for j in range(i + 1, 5):
            both = set(tables.members[tables.members.player_id == five[i]].lineup_id) & \
                   set(tables.members[tables.members.player_id == five[j]].lineup_id)
            vals.append(np.log1p(lw[lw.lineup_id.isin(both)].poss.sum()))
    assert X.loc[lid, "lu_pair_familiarity"] == pytest.approx(np.mean(vals))


def test_traded_player_pools_both_teams_for_ratings_but_not_for_team_share(data):
    from nba_lineups.modeling.features import player_season_rates
    tables, _ = data
    pt = tables.player_team
    per_player = pt.groupby(["season_id", "player_id"]).on_poss.agg(["size", "sum"])
    season, player = per_player[per_player["size"] == 2].index[0]          # the synthetic trade
    rates = player_season_rates(tables).set_index(["season_id", "player_id"])
    assert rates.loc[(season, player), "on_poss"] == per_player.loc[(season, player), "sum"]   # pooled for ratings
    rows = pt[(pt.season_id == season) & (pt.player_id == player)]
    assert len(rows) == 2 and set(rows.team_id) == {synthetic.TEAMS[0], synthetic.TEAMS[1]}   # per team for team share


# ------------------------------------------------------------------ leakage guards
def test_fit_ignores_validation_season_data(data):
    tables, _ = data
    lw = tables.lineups.copy()
    v = lw.season_id == VAL
    lw.loc[v, ["pts", "opp_pts"]] = lw.loc[v, ["opp_pts", "pts"]].to_numpy() * 3    # wreck the validation season
    a = FeatureBuilder().fit(tables, TRAIN).params()
    b = FeatureBuilder().fit(_rebuild(tables, lineups=lw), TRAIN).params()
    assert a == b


def test_transform_of_a_season_uses_only_that_season(data):
    tables, targets = data
    lw = tables.lineups.copy()
    v = lw.season_id == VAL
    lw.loc[v, "pts"] = lw.loc[v, "pts"] * 2
    b = FeatureBuilder().fit(tables, TRAIN)
    t0 = targets[targets.season_id == TRAIN[0]]
    pd.testing.assert_frame_equal(b.transform(tables, t0), b.transform(_rebuild(tables, lineups=lw), t0))


def test_features_do_not_depend_on_the_target(data, fitted):
    tables, targets = data
    b, X = fitted
    scrambled = targets.assign(y=-targets.y * 7, post_poss=1, w=1.0)
    pd.testing.assert_frame_equal(X, b.transform(tables, scrambled))


def test_post_break_rows_are_rejected(data):
    tables, _ = data
    lw = tables.lineups.copy()
    lw.loc[0, "window_type"] = "post_asb"
    with pytest.raises(raw.LeakageError, match="post-break"):
        _rebuild(tables, lineups=lw)


def test_last_team_id_is_rejected(data):
    tables, _ = data
    with pytest.raises(raw.LeakageError, match="last_team_id"):
        _rebuild(tables, usage=tables.usage.assign(last_team_id=1))


def test_held_out_rows_are_rejected(data):
    tables, _ = data
    lw = tables.lineups.copy()
    lw.loc[0, "season_id"] = "2024-25"
    with pytest.raises(HeldOutDataError):
        _rebuild(tables, lineups=lw)
    with pytest.raises(HeldOutDataError):
        dataclasses.replace(tables, usage=tables.usage.assign(season_id="2025-26")).validate()


@pytest.mark.parametrize("season", ["2024-25", "2025-26"])
def test_loaders_refuse_held_out_seasons_before_touching_the_database(season):
    class NoConnection:
        def execute(self, *a, **k):
            raise AssertionError("the database must not be queried")
    with pytest.raises(HeldOutDataError):
        raw.load_pre_break_tables(NoConnection(), ["2023-24", season])
    with pytest.raises(HeldOutDataError):
        raw.load_targets(NoConnection(), [season])
