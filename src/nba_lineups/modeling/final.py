"""Final model: pre-registered selection rule, the deployable bundle, and the frozen specification.

SELECTION RULE (pre-registered before any Phase 6 result):
  1. Candidates: linear regression, ridge, random forest.
  2. Criterion: pooled possession-weighted RMSE over the out-of-fold predictions of the `all` variant
     (validation seasons 2019-20 .. 2023-24, nested chronological CV).
  3. One-standard-error rule: pick the SIMPLEST model (linear < ridge < forest) whose RMSE is within one
     bootstrap standard error (team-season clusters, paired) of the best model's RMSE.
  4. Final hyperparameters: chronological CV over all six development seasons (the expanding folds).
  5. Final fit: FeatureBuilder and model fitted on all development seasons. Baseline parameters are
     frozen alongside, so the held-out comparison uses baselines fitted on exactly the same data.
"""
from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from ..config import DEV_SEASONS, HELDOUT_SEASONS
from . import baselines as bl
from .features import FeatureBuilder
from .models import FEATURES, SPECS, fit_model, predict, weighted_rmse
from .raw import PreBreakTables

SELECTION_RULE = __doc__[__doc__.index("SELECTION RULE"):].strip()
ARTIFACT = "model.joblib"
SPEC = "frozen_spec.json"


def one_se_choice(rmse: dict[str, float], se: dict[str, float], simplest_first: list[str]) -> str:
    """The simplest model whose RMSE is within one SE (of its difference from the best) of the best RMSE."""
    best = min(rmse, key=rmse.get)
    return next(m for m in simplest_first if m == best or rmse[m] - rmse[best] <= se[m])


def select_model(oof: pd.DataFrame, n_boot: int = 1000, seed: int = 21) -> dict:
    """Apply the one-standard-error rule to pooled out-of-fold predictions (columns = model names)."""
    names = sorted(SPECS, key=lambda m: SPECS[m].complexity)
    rmse = {m: weighted_rmse(oof.y, oof[m], oof.w) for m in names}
    best = min(rmse, key=rmse.get)
    groups = [g for _, g in oof.groupby(["season_id", "team_id"], sort=False)]
    rng = np.random.default_rng(seed)
    diffs = {m: [] for m in names}
    for _ in range(n_boot):
        d = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))], ignore_index=True)
        rb = weighted_rmse(d.y, d[best], d.w)
        for m in names:
            diffs[m].append(weighted_rmse(d.y, d[m], d.w) - rb)
    se = {m: float(np.std(v, ddof=1)) for m, v in diffs.items()}
    chosen = one_se_choice(rmse, se, names)
    return {"rule": "one-standard-error, simplest first", "rmse_weighted": rmse, "best": best,
            "se_of_difference_from_best": se, "chosen": chosen}


@dataclass
class LineupModel:
    """Everything needed to predict a lineup's post-break net rating from pre-break tables."""
    model_name: str
    params: dict
    builder: FeatureBuilder
    pipeline: object
    baseline_params: dict
    trained_seasons: tuple[str, ...]
    features: list[str] = field(default_factory=lambda: list(FEATURES))
    versions: dict = field(default_factory=dict)

    def feature_frame(self, tables: PreBreakTables, lineups: pd.DataFrame) -> pd.DataFrame:
        x = self.builder.transform(tables, lineups).drop(columns=["season_id", "team_id"])
        return lineups.join(x, on="lineup_id")

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        return predict(self.pipeline, frame)

    def predict(self, tables: PreBreakTables, lineups: pd.DataFrame) -> pd.Series:
        f = self.feature_frame(tables, lineups)
        return pd.Series(self.predict_frame(f), index=f.lineup_id, name="pred_net_rating")

    def baseline_predictions(self, frame: pd.DataFrame) -> pd.DataFrame:
        return bl.predict(self.baseline_params, frame)

    @property
    def noise_k(self) -> float:
        return self.builder.lineup_vc_.k


def fit_final(model_name: str, params: dict, tables: PreBreakTables, targets: pd.DataFrame) -> LineupModel:
    if set(targets.season_id) - set(DEV_SEASONS):
        raise ValueError("the final model is trained on development seasons only")
    builder = FeatureBuilder().fit(tables, DEV_SEASONS)
    frame = targets.join(builder.transform(tables, targets).drop(columns=["season_id", "team_id"]), on="lineup_id")
    pipe = fit_model(SPECS[model_name], params, frame)
    return LineupModel(model_name, params, builder, pipe, bl.fit(frame), tuple(DEV_SEASONS),
                       versions={"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                                 "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__})


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(model: LineupModel, out_dir: Path, selection: dict, cv_summary: dict) -> dict:
    """Write the artifact and the frozen specification + evaluation plan. Commit both BEFORE unlocking
    the held-out seasons; holdout.unlock() verifies they are committed and unchanged."""
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_dir / ARTIFACT, compress=3)
    spec = {
        "status": "frozen",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prediction_target": "post-All-Star-break lineup net rating (per 100 possessions), conditional on the "
                             "lineup playing >= 25 post-break possessions on each end",
        "model": {"name": model.model_name, "label": SPECS[model.model_name].label, "params": model.params,
                  "features_in": model.features,
                  "features_used": list(model.pipeline[:-1].get_feature_names_out())
                  if hasattr(model.pipeline[:-1], "get_feature_names_out") else model.features,
                  "trained_seasons": list(model.trained_seasons), "sample_weight": "post-break possessions"},
        "selection": selection | {"rule_text": SELECTION_RULE},
        "development_cv_summary": cv_summary,
        "feature_builder_parameters": model.builder.params(),
        "baseline_parameters": model.baseline_params,
        "evaluation_plan": {
            "held_out_seasons": list(HELDOUT_SEASONS),
            "report": "each held-out season separately, and both pooled",
            "sample": "lineups with >= 25 post-break possessions on each end",
            "metrics": ["MAE", "RMSE", "R2"], "weightings": ["possession-weighted (primary)", "unweighted"],
            "comparisons": "model minus each baseline (league mean, team prior, calibrated team prior, "
                           "EB lineup -> team prior, player composite), paired",
            "uncertainty": "team-season cluster bootstrap, 2000 resamples, 95% percentile intervals, seed 2025",
            "noise_floor": "K from the frozen FeatureBuilder (development seasons)",
            "primary_question": "is the weighted RMSE of the model minus the team prior below 0 (CI excludes 0)?",
            "no_retuning": "the model and this plan are not changed after the held-out seasons are read",
        },
        "artifact": {"file": ARTIFACT, "sha256": sha256(out_dir / ARTIFACT)},
        "versions": model.versions,
    }
    (out_dir / SPEC).write_text(json.dumps(spec, indent=1, default=float) + "\n")
    return spec


def load(out_dir: Path) -> LineupModel:
    return joblib.load(Path(out_dir) / ARTIFACT)
