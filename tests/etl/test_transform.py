"""Transform unit tests on small SYNTHETIC frames (structure mirrors the real API; numbers are made up)."""
import math

import pandas as pd
import pytest

from nba_lineups.etl.transform import (BASE_ADDITIVE, OPP_ADDITIVE, TransformError, collapse_name_variants,
                                       join_measures, player_key)

GID = "-101-202-303-404-505-"


def measures(rows):
    """rows: list of dicts with GROUP_NAME, STP, GP, POSS, PTS, FGM, FG3M, FTM, OPP_PTS, OPP_FGM, DEF_RATING."""
    adv, base, opp = [], [], []
    for r in rows:
        key = {"TEAM_ID": 1, "GROUP_ID": r.get("GROUP_ID", GID), "GROUP_NAME": r["GROUP_NAME"]}
        common = key | {"SUM_TIME_PLAYED": r["STP"], "GP": r["GP"]}
        adv.append(common | {"POSS": r["POSS"], "OFF_RATING": 100.0, "DEF_RATING": r["DEF_RATING"],
                             "NET_RATING": 0.0, "PACE": 99.0})
        b = {c: 0 for c in BASE_ADDITIVE} | {"PTS": r["PTS"], "FGM": r["FGM"], "FGA": r["FGM"] + 5,
                                             "FG3M": r["FG3M"], "FG3A": r["FG3M"], "FTM": r["FTM"],
                                             "FTA": r["FTM"], "PLUS_MINUS": r["PTS"] - r["OPP_PTS"]}
        base.append(common | b)
        o = {c: 0 for c in OPP_ADDITIVE} | {"OPP_PTS": r["OPP_PTS"], "OPP_FGM": r["OPP_PTS"] // 2,
                                            "OPP_FGA": r["OPP_PTS"]}
        opp.append(common | o)
    return pd.DataFrame(adv), pd.DataFrame(base), pd.DataFrame(opp)


ROW_A = dict(GROUP_NAME="A. Smith - B. Jones", STP=60000, GP=10, POSS=50, PTS=55, FGM=20, FG3M=5, FTM=10,
             OPP_PTS=50, DEF_RATING=100.0)
ROW_B = dict(GROUP_NAME="A. Smith Sr. - B. Jones", STP=3000, GP=1, POSS=4, PTS=4, FGM=2, FG3M=0, FTM=0,
             OPP_PTS=5, DEF_RATING=125.0)


def test_player_key_is_numeric_order_without_outer_dashes():
    assert player_key("-1000-999-5-20-1-") == "1-5-20-999-1000"


def test_name_variants_are_summed_and_ratings_dropped():
    out = collapse_name_variants(join_measures(*measures([ROW_A, ROW_B])))
    assert len(out) == 1
    r = out.iloc[0]
    assert (r.N_SOURCE_ROWS, r.GP, r.SUM_TIME_PLAYED, r.POSS, r.PTS, r.OPP_PTS) == (2, 11, 63000, 54, 59, 55)
    assert r.PLUS_MINUS == r.PTS - r.OPP_PTS
    # opponent possessions: 100*50/100 + 100*5/125 = 50 + 4
    assert r.OPP_POSS_IMPLIED == pytest.approx(54.0)
    # NBA's per-row ratings can't be combined, so they are dropped for merged lineups
    assert math.isnan(r.OFF_RATING) and math.isnan(r.DEF_RATING)


def test_single_row_lineup_keeps_nba_ratings():
    r = collapse_name_variants(join_measures(*measures([ROW_A]))).iloc[0]
    assert r.N_SOURCE_ROWS == 1 and r.DEF_RATING == 100.0 and r.OPP_POSS_IMPLIED == pytest.approx(50.0)


def test_undefined_opponent_possessions_make_the_sum_unknown():
    zero = ROW_B | {"OPP_PTS": 0, "DEF_RATING": 0.0, "PTS": 4}
    r = collapse_name_variants(join_measures(*measures([ROW_A, zero]))).iloc[0]
    assert math.isnan(r.OPP_POSS_IMPLIED)  # honest unknown instead of silently under-counting


def test_lineup_missing_from_one_measure_fails():
    adv, base, opp = measures([ROW_A, ROW_B | {"GROUP_ID": "-1-2-3-4-5-"}])
    with pytest.raises(TransformError, match="missing from at least one measure"):
        join_measures(adv, base, opp.iloc[:1])


def test_time_mismatch_between_measures_fails():
    adv, base, opp = measures([ROW_A])
    base.loc[0, "SUM_TIME_PLAYED"] += 1
    with pytest.raises(TransformError, match="time played"):
        join_measures(adv, base, opp)
