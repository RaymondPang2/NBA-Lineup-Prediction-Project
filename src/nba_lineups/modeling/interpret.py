"""Interpretability: coefficients, permutation importance (single and grouped), residual diagnostics.

Permutation importance is computed on VALIDATION folds (never on training rows, where an overfitted
model would look important for the wrong reasons): shuffle one feature (or a GROUP of correlated
features together), and measure how much the possession-weighted RMSE rises. Correlated features share
credit, so single-feature importance understates a redundant group; grouped permutation fixes that.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from .models import FEATURES, weighted_rmse

GROUPS = {
    "team ratings": ["team_off_rating_loo", "team_def_rating_loo"],
    "player ratings (ORtg/DRtg/net/on-off)": ["p_off_rating_eb_mean", "p_def_rating_eb_mean", "p_net_rating_eb_mean",
                                              "p_on_off_eb_mean"],
    "player usage": ["p_usage_eb_mean", "p_usage_eb_max"],
    "player role / roster": ["p_log_poss_mean", "p_team_share_min", "p_n_new_to_team", "p_n_no_history"],
    "lineup history": ["lu_log_poss", "lu_no_history", "lu_net_eb_team"],
    "familiarity": ["lu_pair_familiarity"],
}
assert sorted(sum(GROUPS.values(), [])) == sorted(FEATURES)


def coefficients(pipe: Pipeline) -> pd.Series:
    """Coefficients on STANDARDIZED features: net-rating points per 1 SD of the feature (training-fold SD)."""
    names = pipe[:-1].get_feature_names_out()
    return pd.Series(pipe.named_steps["model"].coef_, index=names)


def permutation_importance(pipe: Pipeline, frame: pd.DataFrame, columns: dict[str, list[str]],
                           n_repeats: int = 20, seed: int = 0) -> pd.DataFrame:
    """Increase in weighted RMSE when each column group is shuffled (rows permuted jointly within a group)."""
    rng = np.random.default_rng(seed)
    X = frame[FEATURES]
    base = weighted_rmse(frame.y, pipe.predict(X), frame.w)
    rows = []
    for name, cols in columns.items():
        inc = []
        for _ in range(n_repeats):
            Xp = X.copy()
            idx = rng.permutation(len(X))
            Xp[cols] = X[cols].to_numpy()[idx]
            inc.append(weighted_rmse(frame.y, pipe.predict(Xp), frame.w) - base)
        rows.append({"feature": name, "rmse_increase": float(np.mean(inc)), "sd": float(np.std(inc))})
    return pd.DataFrame(rows)
