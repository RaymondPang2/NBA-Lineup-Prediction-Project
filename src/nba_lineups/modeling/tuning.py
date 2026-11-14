"""Nested chronological cross-validation.

Outer loop: the Phase 5 expanding-window folds; they estimate out-of-sample performance.
Inner loop: for each outer fold, hyperparameters are chosen by ANOTHER expanding-window CV over that
fold's TRAINING seasons only (features refitted per inner fold, too). The outer validation season is
never seen by tuning, feature fitting or preprocessing.

Selection criterion: pooled possession-weighted RMSE over the inner validation rows (the primary metric).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import cv
from .models import SPECS, ModelSpec, fit_model, predict, weighted_rmse
from .raw import PreBreakTables
from .splits import Fold, expanding_window_folds


class FoldCache:
    """Memoizes cv.fold_frames: an inner fold of one outer fold is often an outer fold of another."""

    def __init__(self, tables: PreBreakTables, targets: pd.DataFrame):
        self.tables, self.targets, self._c = tables, targets, {}

    def get(self, fold: Fold):
        key = (fold.train_seasons, fold.val_season)
        if key not in self._c:
            self._c[key] = cv.fold_frames(self.tables, self.targets, fold)
        return self._c[key]


def tune(spec: ModelSpec, cache: FoldCache, train_seasons: tuple[str, ...]) -> tuple[dict, pd.DataFrame | None]:
    """Best hyperparameters for `spec` using only `train_seasons`. Returns (params, validation curve)."""
    if len(spec.grid) == 1:
        return dict(spec.grid[0]), None
    if len(train_seasons) < 2:
        return dict(spec.default), None      # pre-registered default: chronological tuning impossible
    inner = expanding_window_folds(train_seasons)
    preds = {i: [] for i in range(len(spec.grid))}
    ys, ws = [], []
    for f in inner:
        tr, va, _ = cache.get(f)
        assert f.val_season in train_seasons and max(f.train_seasons) < f.val_season
        ys.append(va.y.to_numpy(float))
        ws.append(va.w.to_numpy(float))
        for i, params in enumerate(spec.grid):
            preds[i].append(predict(fit_model(spec, params, tr), va))
    y, w = np.concatenate(ys), np.concatenate(ws)
    curve = pd.DataFrame([{**spec.grid[i], "weighted_rmse": weighted_rmse(y, np.concatenate(p), w)}
                          for i, p in preds.items()])
    r = curve.weighted_rmse.to_numpy()
    best = int(np.flatnonzero(r <= r.min() + 1e-9)[0])     # exact ties -> first (simplest) grid entry
    return dict(spec.grid[best]), curve.assign(inner_folds=len(inner), train_seasons=",".join(train_seasons))


@dataclass
class ModelRun:
    variant: str
    oof: pd.DataFrame                                 # validation rows: ids, target, features, baselines, model preds
    folds: pd.DataFrame                               # per outer fold x model: params, train/val RMSE
    curves: list[pd.DataFrame] = field(default_factory=list)
    fitted: dict = field(default_factory=dict)        # (model, val_season) -> fitted Pipeline
    frames: dict = field(default_factory=dict)        # val_season -> (train frame, val frame)


def run_models(cache: FoldCache, folds: list[Fold], variant: str, model_names=tuple(SPECS)) -> ModelRun:
    from . import baselines as bl
    out, rows, curves, fitted, frames = [], [], [], {}, {}
    for fold in folds:
        train, val, builder = cache.get(fold)
        bpred, _ = bl.fit_predict(train, val)
        val = val.join(bpred)
        val["k"] = builder.lineup_vc_.k
        for name in model_names:
            spec = SPECS[name]
            params, curve = tune(spec, cache, fold.train_seasons)
            pipe = fit_model(spec, params, train)
            val[name] = predict(pipe, val)
            fitted[(name, fold.val_season)] = pipe
            rows.append({"variant": variant, "val_season": fold.val_season, "model": name,
                         "n_train_seasons": len(fold.train_seasons), "params": params,
                         "tuned": curve is not None,
                         "train_rmse_w": weighted_rmse(train.y, predict(pipe, train), train.w),
                         "val_rmse_w": weighted_rmse(val.y, val[name], val.w)})
            if curve is not None:
                curves.append(curve.assign(model=name, outer_val_season=fold.val_season, variant=variant))
        frames[fold.val_season] = (train, val)
        out.append(val)
    return ModelRun(variant, pd.concat(out, ignore_index=True), pd.DataFrame(rows), curves, fitted, frames)
