"""Phase 6 model specifications: linear regression, ridge, random forest.

Every learned preprocessing step (imputation, VIF-based feature selection, scaling) is a step of the
scikit-learn Pipeline, so it is fitted on exactly the rows the model is fitted on: the training fold.

Sample weights are post-break possessions, normalized to mean 1 within the training rows, so ridge's
alpha has a per-observation scale and doesn't depend on the total possessions in a fold.

PRE-REGISTERED (written before any Phase 6 result existed):
- grids and the a-priori `default` hyperparameters, used only for an outer fold with fewer than two
  training seasons (validating 2019-20), where chronological tuning is impossible;
- linear regression drops features by in-fold VIF elimination (threshold 10; target never used);
- `complexity` orders models for the one-standard-error selection rule (simplest first);
- exact ties in tuning (within 1e-9 RMSE) go to the first, i.e. simplest, grid entry.
"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .registry import FEATURE_NAMES

FEATURES: list[str] = list(FEATURE_NAMES)
VIF_THRESHOLD = 10.0
RANDOM_STATE = 0


def vif(X: np.ndarray) -> np.ndarray:
    """Variance inflation factors: diagonal of the inverse correlation matrix. VIF_j = 1 / (1 − R²_j)."""
    c = np.corrcoef(np.asarray(X, float), rowvar=False)
    return np.diag(np.linalg.pinv(np.atleast_2d(c)))


class VIFSelector(BaseEstimator, TransformerMixin):
    """Backward elimination: repeatedly drop the feature with the largest VIF until all are <= threshold.

    Unsupervised (never sees y), deterministic, and fitted inside the training fold like any other step.
    Constant columns are dropped first (their correlation is undefined)."""

    def __init__(self, threshold: float = VIF_THRESHOLD):
        self.threshold = threshold

    def fit(self, X, y=None):
        names = list(X.columns) if isinstance(X, pd.DataFrame) else [f"x{i}" for i in range(np.shape(X)[1])]
        A = np.asarray(X, float)
        keep = [i for i in range(A.shape[1]) if np.std(A[:, i]) > 0]
        self.dropped_ = [(names[i], np.inf) for i in range(A.shape[1]) if i not in keep]
        while len(keep) > 1:
            v = vif(A[:, keep])
            j = int(np.argmax(v))
            if v[j] <= self.threshold:
                break
            self.dropped_.append((names[keep[j]], float(v[j])))
            keep.pop(j)
        self.support_ = keep
        self.feature_names_in_ = np.array(names, dtype=object)
        self.selected_ = [names[i] for i in keep]
        return self

    def transform(self, X):
        return X.iloc[:, self.support_] if isinstance(X, pd.DataFrame) else np.asarray(X)[:, self.support_]

    def get_feature_names_out(self, input_features=None):
        return np.array(self.selected_, dtype=object)


def _linear(params: dict) -> Pipeline:
    return Pipeline([("impute", SimpleImputer(strategy="median")),
                     ("select", VIFSelector(params.get("vif_threshold", VIF_THRESHOLD))),
                     ("scale", StandardScaler()), ("model", LinearRegression())]).set_output(transform="pandas")


def _ridge(params: dict) -> Pipeline:
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                     ("model", Ridge(alpha=params["alpha"]))]).set_output(transform="pandas")


def _forest(params: dict) -> Pipeline:
    rf = RandomForestRegressor(n_estimators=params.get("n_estimators", 300), max_depth=params["max_depth"],
                               min_samples_leaf=params["min_samples_leaf"], max_features=params["max_features"],
                               random_state=RANDOM_STATE, n_jobs=-1)
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", rf)]).set_output(transform="pandas")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    build: Callable[[dict], Pipeline]
    grid: tuple[dict, ...]
    default: dict
    complexity: int


RIDGE_ALPHAS = tuple(float(a) for a in np.round(np.logspace(-1, 4.5, 12), 4))
# Ordered SIMPLEST FIRST (shallow, large leaves, fewer features per split): exact ties in tuning go to the
# earlier, simpler configuration. Ties are real: with one ~600-lineup training season and >= 200 lineups per
# leaf, every depth limit grows identical trees.
RF_GRID = tuple({"max_depth": d, "min_samples_leaf": m, "max_features": f}
                for d, m, f in itertools.product((3, 5, 8, None), (200, 100, 50, 25), (0.33, 0.66)))

SPECS: dict[str, ModelSpec] = {
    "linear": ModelSpec("linear", "Linear regression (VIF-pruned)", _linear, ({},), {}, 1),
    "ridge": ModelSpec("ridge", "Ridge regression", _ridge, tuple({"alpha": a} for a in RIDGE_ALPHAS),
                       {"alpha": 100.0}, 2),
    "forest": ModelSpec("forest", "Random forest", _forest, RF_GRID,
                        {"max_depth": 5, "min_samples_leaf": 50, "max_features": 0.33}, 3),
}
MODEL_NAMES = list(SPECS)


def fit_model(spec: ModelSpec, params: dict, frame: pd.DataFrame) -> Pipeline:
    """Fit on training rows (needs FEATURES, y, w). Weights normalized to mean 1."""
    w = frame.w.to_numpy(float)
    pipe = spec.build(params).fit(frame[FEATURES], frame.y.to_numpy(float), model__sample_weight=w / w.mean())
    if hasattr(pipe.named_steps["model"], "n_jobs"):
        # Fit in parallel, PREDICT sequentially: parallel prediction sums the trees in a nondeterministic order,
        # which changes results in the last bits and can flip an exact tie during tuning.
        pipe.named_steps["model"].n_jobs = 1
    return pipe


def predict(pipe: Pipeline, frame: pd.DataFrame) -> np.ndarray:
    return pipe.predict(frame[FEATURES])


def weighted_rmse(y, pred, w) -> float:
    return float(np.sqrt(np.average((np.asarray(y, float) - np.asarray(pred, float)) ** 2, weights=w)))
