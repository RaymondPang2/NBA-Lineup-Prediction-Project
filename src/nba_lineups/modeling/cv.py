"""Run baselines (and, in Phase 6, models) through the chronological folds.

`fold_frames` is the single place where a fold's data is assembled: the FeatureBuilder is fitted on the
fold's training seasons, then the same fitted builder transforms the training and validation lineups.
Phase 6 models plug into the same function, so features and baselines are always built identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import baselines
from .features import FeatureBuilder
from .raw import PreBreakTables
from .splits import Fold

ID_COLS = ["season_id", "team_id", "lineup_id"]
TARGET_COLS = ["y", "w", "post_poss", "post_opp_poss", "is_irregular"]


def fold_frames(tables: PreBreakTables, targets: pd.DataFrame, fold: Fold
                ) -> tuple[pd.DataFrame, pd.DataFrame, FeatureBuilder]:
    builder = FeatureBuilder().fit(tables, fold.train_seasons)
    frames = []
    for seasons in (fold.train_seasons, (fold.val_season,)):
        t = targets[targets.season_id.isin(seasons)][ID_COLS + TARGET_COLS]
        x = builder.transform(tables, t).drop(columns=["season_id", "team_id"])
        frames.append(t.join(x, on="lineup_id").reset_index(drop=True))
    return frames[0], frames[1], builder


@dataclass
class CVRun:
    variant: str
    folds: list[Fold]
    oof: pd.DataFrame                    # validation rows of every fold: ids, target, features, predictions, k
    params: list[dict] = field(default_factory=list)

    def restrict(self, val_seasons) -> pd.DataFrame:
        return self.oof[self.oof.season_id.isin(val_seasons)]


def run_baselines(tables: PreBreakTables, targets: pd.DataFrame, folds: list[Fold], variant: str) -> CVRun:
    out, params = [], []
    for fold in folds:
        train, val, builder = fold_frames(tables, targets, fold)
        preds, bparams = baselines.fit_predict(train, val)
        val = val.join(preds)
        val["k"] = builder.lineup_vc_.k        # sampling constant for the noise floor, from TRAINING pre-break data
        val["fold_train_seasons"] = len(fold.train_seasons)
        out.append(val)
        params.append({"val_season": fold.val_season, "n_train": len(train), "n_val": len(val),
                       "features": builder.params(), "baselines": bparams})
    return CVRun(variant, folds, pd.concat(out, ignore_index=True), params)
