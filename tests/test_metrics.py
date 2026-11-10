"""Unit tests for metrics.py: mathematical correctness and edge cases (synthetic numbers)."""
import math

import numpy as np
import pandas as pd
import pytest

from nba_lineups import metrics as m


def test_per100_basic_and_zero_denominator():
    assert m.per100(55, 50) == pytest.approx(110.0)
    assert math.isnan(m.per100(3, 0))          # undefined, NOT 0.0 like the NBA API reports
    assert math.isnan(m.per100(0, 0))
    assert m.per100(0, 10) == 0.0              # scoring nothing in 10 possessions is a real 0


def test_per100_missing_and_vectorized():
    out = m.per100(np.array([10, 20, np.nan]), np.array([10, np.nan, 5]))
    assert out[0] == 100.0 and np.isnan(out[1]) and np.isnan(out[2])
    s = m.per100(pd.Series([1.0, 2.0], index=["a", "b"]), pd.Series([2.0, 4.0], index=["a", "b"]))
    assert list(s.index) == ["a", "b"] and s.tolist() == [50.0, 50.0]


@pytest.mark.parametrize("num,poss", [(-1, 10), (10, -1)])
def test_per100_rejects_impossible_values(num, poss):
    with pytest.raises(ValueError):
        m.per100(num, poss)


def test_net_rating_uses_separate_denominators():
    # 110 pts on 100 own possessions, 100 allowed on 95 opponent possessions
    assert m.net_rating(110, 100, 100, 95) == pytest.approx(110 - 100 * 100 / 95)
    assert math.isnan(m.net_rating(10, 5, 4, 0))   # one side undefined -> net undefined


def test_ratio_of_sums_is_not_mean_of_ratios():
    # A tiny lucky sample and a large ordinary one:
    df = pd.DataFrame({"k": ["x", "x"], "pts": [6, 1000], "poss": [2, 1000],
                       "opp_pts": [0, 1000], "opp_poss": [2, 1000]})
    agg = m.aggregate_ratings(df, ["k"]).iloc[0]
    mean_of_ratios = np.mean(m.per100(df.pts, df.poss))                 # (300 + 100) / 2 = 200
    assert mean_of_ratios == pytest.approx(200.0)
    assert agg.off_rating == pytest.approx(100 * 1006 / 1002)           # ~100.4: the honest answer


def test_opp_poss_from_pace_recovers_integer():
    # A lineup with 500 own and 497 opponent possessions over 1000 minutes:
    true_pace = 48 * (500 + 497) / 2 / 1000                          # 23.928
    published = round(true_pace, 2)                                  # NBA publishes 2 decimals
    assert m.opp_poss_from_pace(published, 1000.0, 500) == 497.0


def test_opp_poss_from_pace_edge_cases():
    assert math.isnan(m.opp_poss_from_pace(0.0, 0.0, 1))           # zero playing time: undefined
    # 2 * 99.6 * 10 / 48 - 5 = 36.5: exactly between integers -> inconsistent inputs, refuse to guess
    assert math.isnan(m.opp_poss_from_pace(99.6, 10.0, 5))
    # 2 * 100.37 * 10 / 48 - 5 = 36.82: within 0.25 of 37 -> accepted
    assert m.opp_poss_from_pace(100.37, 10.0, 5) == 37.0


def test_opp_poss_from_def_rating():
    assert m.opp_poss_from_def_rating(50, 100.0) == 50.0
    assert math.isnan(m.opp_poss_from_def_rating(0, 0.0))          # 0 points allowed: route A undefined


@pytest.mark.parametrize("x,expected", [(2.25, 2.3), (2.35, 2.4), (-2.25, -2.3), (110.05, 110.1), (0.04, 0.0)])
def test_round_half_up_matches_nba(x, expected):
    assert m.round_half_up(x) == expected


def test_numpy_uses_bankers_rounding():
    # Why round_half_up exists: numpy rounds exact halves to the nearest EVEN digit.
    assert np.round(0.5) == 0.0 and np.round(1.5) == 2.0 and np.round(2.5) == 2.0


def test_possessions_estimate():
    assert m.possessions_estimate(80, 25, 10, 14) == pytest.approx(80 + 11 - 10 + 14)
