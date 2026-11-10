"""Possession-based basketball metrics: one definition of every formula.

All functions are vectorized (accept scalars, numpy arrays, or pandas Series)
and follow two rules:

1. Undefined is NaN, never 0. A rating with zero possessions is undefined.
   (NBA's API reports such ratings as 0.0, which would silently bias averages.)
2. Aggregate, then divide. The rating of a combined sample is
   100 * sum(points) / sum(possessions), never the mean of per-row ratings.

The SQL function `per100()` and the rating views in db/schema.sql implement
the same definitions. tests/db/test_metrics_real.py checks that they agree.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

ArrayLike = float | np.ndarray | pd.Series

# Rounding bound for recovering integer opponent possessions from PACE (see opp_poss_from_pace).
INTEGER_RECOVERY_TOLERANCE = 0.25


def _arr(x: ArrayLike) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _like(template: ArrayLike, values: np.ndarray) -> ArrayLike:
    """Return values in the same container type as the input (Series keeps its index)."""
    if isinstance(template, pd.Series):
        return pd.Series(values, index=template.index)
    return values if np.ndim(values) else float(values)


def per100(numerator: ArrayLike, possessions: ArrayLike) -> ArrayLike:
    """100 * numerator / possessions; NaN when possessions <= 0 or missing.

    Raises ValueError on negative possessions or numerators (impossible values signal a bug upstream).
    """
    num, poss = _arr(numerator), _arr(possessions)
    if np.any(poss < 0) or np.any(num < 0):
        raise ValueError("points and possessions must be non-negative")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(poss > 0, 100.0 * num / np.where(poss > 0, poss, 1.0), np.nan)
    return _like(possessions, out)


def offensive_rating(pts: ArrayLike, poss: ArrayLike) -> ArrayLike:
    """Points scored per 100 OWN possessions."""
    return per100(pts, poss)


def defensive_rating(opp_pts: ArrayLike, opp_poss: ArrayLike) -> ArrayLike:
    """Points allowed per 100 OPPONENT possessions."""
    return per100(opp_pts, opp_poss)


def net_rating(pts: ArrayLike, poss: ArrayLike, opp_pts: ArrayLike, opp_poss: ArrayLike) -> ArrayLike:
    """ORtg - DRtg. NaN if either side is undefined."""
    o, d = _arr(offensive_rating(pts, poss)), _arr(defensive_rating(opp_pts, opp_poss))
    return _like(poss, o - d)


def possessions_estimate(fga: ArrayLike, fta: ArrayLike, oreb: ArrayLike, tov: ArrayLike,
                         ft_weight: float = 0.44) -> ArrayLike:
    """Textbook box-score estimate: FGA + 0.44*FTA - OREB + TOV.

    0.44 approximates the share of free-throw attempts that end a possession
    (and-ones, technicals and three-shot fouls mean that share isn't 0.5).
    """
    return _like(fga, _arr(fga) + ft_weight * _arr(fta) - _arr(oreb) + _arr(tov))


def opp_poss_from_pace(pace: ArrayLike, minutes: ArrayLike, poss: ArrayLike) -> ArrayLike:
    """Recover NBA's integer opponent possessions from PACE (route B).

    NBA defines PACE = 48 * (poss + opp_poss) / 2 / minutes, so
    opp_poss = 2 * PACE * minutes / 48 - poss. PACE is published to 2 decimals, so the
    reconstruction error is at most 0.005 * 2 * minutes / 48 < 0.5 for any lineup under
    2,400 minutes, and rounding recovers the exact integer. Values that aren't within
    INTEGER_RECOVERY_TOLERANCE of an integer (or have no playing time) are returned as NaN.
    """
    p, m, own = _arr(pace), _arr(minutes), _arr(poss)
    raw = 2.0 * p * m / 48.0 - own
    rounded = np.round(raw)
    ok = (m > 0) & (np.abs(raw - rounded) <= INTEGER_RECOVERY_TOLERANCE) & (rounded >= 0)
    return _like(poss, np.where(ok, rounded, np.nan))


def opp_poss_from_def_rating(opp_pts: ArrayLike, def_rating: ArrayLike) -> ArrayLike:
    """Recover opponent possessions from NBA DEF_RATING = 100 * OPP_PTS / OPP_POSS (route A).

    Fallback for zero-time rows (where PACE is undefined). Undefined when DEF_RATING is 0.
    Less precise than route B for large samples because DEF_RATING has only 1 decimal.
    """
    pts, d = _arr(opp_pts), _arr(def_rating)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(d > 0, 100.0 * pts / np.where(d > 0, d, 1.0), np.nan)
    return _like(opp_pts, np.round(raw))


def round_half_up(x: ArrayLike, decimals: int = 1) -> ArrayLike:
    """Round like NBA.com (2.25 -> 2.3), not like numpy/pandas 'banker's rounding' (2.25 -> 2.2).

    Needed to compare our exact ratings with NBA's published, rounded ones.
    """
    q = Decimal(1).scaleb(-decimals)
    f = lambda v: np.nan if np.isnan(v) else float(Decimal(repr(float(v))).quantize(q, rounding=ROUND_HALF_UP))
    return _like(x, np.vectorize(f, otypes=[float])(_arr(x)))


def aggregate_ratings(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Ratings of grouped samples: SUM the totals, THEN divide (the ratio of sums)."""
    g = df.groupby(by, as_index=False)[["pts", "poss", "opp_pts", "opp_poss"]].sum(min_count=1)
    g["off_rating"] = offensive_rating(g.pts, g.poss)
    g["def_rating"] = defensive_rating(g.opp_pts, g.opp_poss)
    g["net_rating"] = g.off_rating - g.def_rating
    return g
