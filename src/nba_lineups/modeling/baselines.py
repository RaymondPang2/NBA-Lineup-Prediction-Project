"""Baselines: simple, transparent predictors every Phase 6 model must beat.

Each baseline is a pre-break quantity plus parameters fitted on the TRAINING fold's targets only
(possession-weighted). The intercept matters: lineups that keep playing after the break are better than
the average lineup (Phase 4 selection analysis), so an uncorrected team prior is biased low.

  league_mean            training-fold weighted mean of the target (ignores every feature)
  team_prior             team_net_loo + c                    (c = training weighted mean of y − team_net_loo)
  team_prior_calibrated  a + b·team_net_loo                  (1-variable WLS; Phase 4 slope 0.67 < 1 motivates it)
  eb_lineup_team         lu_net_eb_team + c                  (lineup history shrunk toward the team prior)
  player_composite       p_net_rating_eb_mean + c            (Phase 4: 44% of target possessions have no
                                                              lineup history, so player-level information is needed)
  raw_lineup             lu_net_raw, team prior if no history (naive reference: no shrinkage, no intercept)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASELINES = {
    "league_mean": "League mean",
    "team_prior": "Team prior",
    "team_prior_calibrated": "Team prior, calibrated",
    "eb_lineup_team": "EB lineup → team prior",
    "player_composite": "Player composite (EB on-court net)",
    "raw_lineup": "Raw pre-break lineup net (naive)",
}
PRIMARY = ["league_mean", "team_prior", "team_prior_calibrated", "eb_lineup_team", "player_composite"]


def _offset(train: pd.DataFrame, col: str) -> float:
    return float(np.average(train.y - train[col], weights=train.w))


def _wls(x, y, w) -> tuple[float, float]:
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    b = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
    return float(ym - b * xm), float(b)


def fit_predict(train: pd.DataFrame, val: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fit every baseline on `train` (needs y, w and the feature columns), predict `val`."""
    if set(train.season_id) & set(val.season_id):
        raise ValueError("training and validation rows share a season")
    p = pd.DataFrame(index=val.index)
    params = {"league_mean": float(np.average(train.y, weights=train.w))}
    p["league_mean"] = params["league_mean"]
    for name, col in (("team_prior", "team_net_loo"), ("eb_lineup_team", "lu_net_eb_team"),
                      ("player_composite", "p_net_rating_eb_mean")):
        params[f"{name}_offset"] = _offset(train, col)
        p[name] = val[col] + params[f"{name}_offset"]
    a, b = _wls(train.team_net_loo.to_numpy(float), train.y.to_numpy(float), train.w.to_numpy(float))
    params["team_prior_calibrated"] = {"intercept": a, "slope": b}
    p["team_prior_calibrated"] = a + b * val.team_net_loo
    p["raw_lineup"] = val.lu_net_raw.fillna(val.team_net_loo)
    return p, params
