"""Regression metrics, the measurement-noise floor of the target, and cluster-bootstrap uncertainty.

Every metric comes in two versions: unweighted (each lineup counts once) and possession-weighted
(weight = post-break possessions, the approved design: it emphasizes lineups whose target is measured
precisely and that matter most on the court).

R² = 1 − SSE / SST, with SST around the (weighted) mean of the evaluated rows. Out of sample it can be
negative. Skill vs a baseline = 1 − MSE_model / MSE_baseline.

Noise floor: the target is itself a noisy measurement, y = θ + e with Var(e) = K·h_post, where
h_post = 1/post_poss + 1/post_opp_poss (Phase 4 measurement model). Even a perfect predictor of θ has
MSE = mean(K·h_post), so
    RMSE floor = sqrt(mean K·h),  MAE floor = mean(sqrt(2/π)·sqrt(K·h))  (normal errors),
    R² ceiling = 1 − mean(K·h) / Var(y).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..analysis import reliability as rel

WEIGHTINGS = ("weighted", "unweighted")


def _w(df: pd.DataFrame, weighting: str) -> np.ndarray:
    return df.w.to_numpy(float) if weighting == "weighted" else np.ones(len(df))


def regression_metrics(y, pred, w=None) -> dict[str, float]:
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    w = np.ones_like(y) if w is None else np.asarray(w, float)
    e = pred - y
    mse = np.average(e**2, weights=w)
    sst = np.average((y - np.average(y, weights=w)) ** 2, weights=w)
    return {"mae": float(np.average(np.abs(e), weights=w)), "rmse": float(np.sqrt(mse)), "r2": float(1 - mse / sst),
            "mse": float(mse), "var_y": float(sst)}


def noise_floor(df: pd.DataFrame, w=None) -> dict[str, float]:
    """df needs k (sampling constant from the fold's TRAINING data), post_poss, post_opp_poss, y."""
    v = df.k.to_numpy(float) * rel.sampling_h(df.post_poss, df.post_opp_poss)
    w = np.ones(len(df)) if w is None else np.asarray(w, float)
    y = df.y.to_numpy(float)
    var_y = np.average((y - np.average(y, weights=w)) ** 2, weights=w)
    mse = np.average(v, weights=w)
    return {"rmse_floor": float(np.sqrt(mse)), "mae_floor": float(np.average(np.sqrt(2 / np.pi * v), weights=w)),
            "r2_ceiling": float(1 - mse / var_y)}


REFERENCES = {"league_mean": "lm", "team_prior": "tp"}


def metric_table(df: pd.DataFrame, predictors: list[str]) -> dict[str, float]:
    """Flat dict of every metric for every predictor and weighting (the statistic the bootstrap resamples).

    Improvements over the references (positive = better): rmse_gain_lm / mae_gain_lm / skill_lm vs the league
    mean, and the same with _tp vs the team prior. Computed on the SAME resampled rows, so their bootstrap
    intervals are paired comparisons."""
    out = {}
    for wt in WEIGHTINGS:
        w = _w(df, wt)
        ms = {p: regression_metrics(df.y, df[p], w) for p in predictors}
        for p, m in ms.items():
            for k in ("mae", "rmse", "r2"):
                out[f"{p}|{wt}|{k}"] = m[k]
            for ref, tag in REFERENCES.items():
                if ref in ms:
                    r = ms[ref]
                    out[f"{p}|{wt}|rmse_gain_{tag}"] = r["rmse"] - m["rmse"]
                    out[f"{p}|{wt}|mae_gain_{tag}"] = r["mae"] - m["mae"]
                    out[f"{p}|{wt}|skill_{tag}"] = 1 - m["mse"] / r["mse"]
        for k, v in noise_floor(df, w).items():
            out[f"noise_floor|{wt}|{k}"] = v
    return out


def tidy(flat: pd.DataFrame) -> pd.DataFrame:
    """Index 'predictor|weighting|metric' -> columns predictor, weighting, metric."""
    t = flat.copy()
    t[["predictor", "weighting", "metric"]] = pd.Series(t.index, index=t.index).str.split("|", expand=True)
    return t.reset_index(drop=True)[["predictor", "weighting", "metric"] + list(flat.columns)]


def bootstrap_metrics(df: pd.DataFrame, predictors: list[str], n_boot: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Point estimates and 95% percentile CIs, resampling whole TEAM-SEASONS (lineups of one team share
    players and opponents, so they aren't independent). Predictions are held fixed: the intervals cover
    sampling variability of the evaluation set, not refitting variability."""
    return tidy(rel.cluster_bootstrap(df, ["season_id", "team_id"], lambda d: metric_table(d, predictors),
                                      n_boot=n_boot, seed=seed))


def per_fold(df: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    rows = []
    for s, d in df.groupby("season_id"):
        for (p, wt, m), v in ((tuple(k.split("|")), v) for k, v in metric_table(d, predictors).items()):
            rows.append({"val_season": s, "n": len(d), "predictor": p, "weighting": wt, "metric": m, "value": v})
    return pd.DataFrame(rows)


def weighted_corr(x, y, w) -> float:
    x, y, w = (np.asarray(v, float) for v in (x, y, w))
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    c = np.average((x - xm) * (y - ym), weights=w)
    return float(c / np.sqrt(np.average((x - xm) ** 2, weights=w) * np.average((y - ym) ** 2, weights=w)))
