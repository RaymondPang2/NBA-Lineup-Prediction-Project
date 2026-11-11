"""Leakage and held-out guards, the continuation feature builder, and season-grouped CV."""
import numpy as np
import pandas as pd
import pytest

from nba_lineups.analysis import continuation as cont
from nba_lineups.analysis import reliability as rel
from nba_lineups.analysis.data import HeldOutDataError, require_dev

VC = rel.VarianceComponents((1.0,), tau2=40.0, k=14500.0, n=1000)


def synthetic(n_per_team=12, seasons=("2021-22", "2022-23", "2023-24"), seed=0):
    """Pre-break lineup rows, matching player rows, and post-break rows for a few fake teams."""
    rng = np.random.default_rng(seed)
    pre, players, post = [], [], []
    lid = 0
    for s in seasons:
        for team in range(1, 7):
            for _ in range(n_per_team):
                lid += 1
                poss = int(rng.integers(5, 600))
                opp = poss + int(rng.integers(-3, 4))
                pts, opp_pts = int(poss * rng.normal(1.12, 0.1)), int(opp * rng.normal(1.12, 0.1))
                pre.append({"season_id": s, "team_id": team, "lineup_id": lid, "window_type": "pre_asb",
                            "poss": poss, "opp_poss": opp, "pts": pts, "opp_pts": opp_pts,
                            "net_rating": 100 * pts / poss - 100 * opp_pts / opp})
                for k in range(5):
                    players.append({"season_id": s, "team_id": team, "lineup_id": lid, "player_id": 1000 * team + k,
                                    "player_on_court_poss": 2000 + 100 * k, "n_teams": 1 + (k == 0 and lid % 7 == 0)})
                # post-break: heavily used lineups more likely to continue
                if rng.random() < min(0.95, poss / 400):
                    post.append({"season_id": s, "team_id": team, "lineup_id": lid, "window_type": "post_asb",
                                 "poss": int(rng.integers(0, 300)), "opp_poss": 50, "pts": 50, "opp_pts": 50,
                                 "net_rating": 0.0})
    return pd.DataFrame(pre), pd.DataFrame(players), pd.DataFrame(post)


def test_require_dev_rejects_held_out_seasons():
    require_dev(pd.DataFrame({"season_id": ["2018-19", "2023-24"]}))
    for s in ("2024-25", "2025-26"):
        with pytest.raises(HeldOutDataError):
            require_dev(pd.DataFrame({"season_id": ["2023-24", s]}))


def test_feature_builder_refuses_post_break_rows():
    pre, players, post = synthetic()
    with pytest.raises(cont.LeakageError):
        cont.build_features(pd.concat([pre, post]), players, VC)


def test_feature_builder_refuses_the_leaky_last_team_column():
    pre, players, _ = synthetic()
    with pytest.raises(cont.LeakageError, match="last_team_id"):
        cont.build_features(pre, players.assign(last_team_id=players.team_id), VC)


def test_features_do_not_depend_on_post_break_data():
    pre, players, post = synthetic()
    X = cont.build_features(pre, players, VC)
    assert set(X.columns) >= set(cont.FEATURES) and len(X) == ((pre.poss >= 25) & (pre.opp_poss >= 25)).sum()
    # Labels come from post-break rows only; scrambling them changes labels, never features.
    lw = pd.concat([pre, post])
    y1 = cont.labels(lw, X.index)
    post2 = post.assign(poss=post.poss[::-1].to_numpy())
    y2 = cont.labels(pd.concat([pre, post2]), X.index)
    X2 = cont.build_features(pre, players, VC)
    pd.testing.assert_frame_equal(X, X2)
    assert not y1.equals(y2)
    assert y1.continues.isin([0, 1]).all() and (y1.post_poss[y1.continues == 1] >= cont.MIN_POST_POSS).all()


def test_traded_player_and_player_share_features():
    pre, players, _ = synthetic()
    X = cont.build_features(pre, players, VC)
    traded = set(players.loc[players.n_teams >= 2, "lineup_id"])
    assert traded and set(X.index[X.has_traded_player == 1]) == traded & set(X.index)
    assert ((X.min_player_share > 0) & (X.min_player_share <= 1)).all()


def test_cv_never_trains_on_the_validation_season(monkeypatch):
    pre, players, post = synthetic(n_per_team=30)
    X = cont.build_features(pre, players, VC)
    y = cont.labels(pd.concat([pre, post]), X.index).continues
    seen = []
    real = cont.make_model

    def spy():
        m = real()
        fit = m.fit

        def fit_spy(Xtr, ytr):
            seen.append(set(X.loc[Xtr.index, "season_id"]))
            return fit(Xtr, ytr)
        m.fit = fit_spy
        return m
    monkeypatch.setattr(cont, "make_model", spy)
    loso = cont.cross_validate(X, y, "loso")
    assert [s not in tr for s, tr in zip(loso.folds.season, seen)] == [True] * 3
    seen.clear()
    fwd = cont.cross_validate(X, y, "forward")
    assert all(max(tr) < s for s, tr in zip(fwd.folds.season, seen))     # forward chaining: past seasons only
    assert loso.predictions.notna().all()


def test_standardized_mean_difference_and_ipw_balance():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(size=20000))
    p = 1 / (1 + np.exp(-(x - 1)))                       # selection depends on x
    sel = pd.Series((rng.random(20000) < p).astype(int))
    assert cont.standardized_mean_difference(x, sel) > 0.5           # selected sample is shifted
    assert abs(cont.standardized_mean_difference(x, sel, 1 / p)) < 0.05   # IPW with the true propensity rebalances
