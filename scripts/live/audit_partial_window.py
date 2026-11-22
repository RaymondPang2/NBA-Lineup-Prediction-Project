"""Audit: can the frozen model safely score a PARTIAL pre-break window (the 2026-27 season in progress)?

    .venv/bin/python scripts/live/audit_partial_window.py      # -> reports/live/partial_window_audit.json

Read-only. The frozen model is loaded through the API's FrozenPredictor (hash-verified) and only predicts.
Three measurements (docs/partial_window_audit.md):
 1. feature drift: each model feature's mean, standardized by the model's own training scaler, for the season in
    progress vs a completed held-out season;
 2. volume counterfactual (diagnostic only): predictions if the season-to-date rates had been observed over a full
    pre-break window, vs the served predictions;
 3. held-out backtest of the volume effect: 2025-26 pre-break totals shrunk to the season in progress's fraction
    (same rates, less volume), scored against 2025-26's real post-break outcomes. It isolates the volume/prior
    effect; the extra noise of early-season rates is NOT simulated, so it is a lower bound on the accuracy cost.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from nba_lineups.api.services.predictions import FrozenPredictor
from nba_lineups.config import CURRENT_SEASON, PROJECT_ROOT
from nba_lineups.db.connection import connect
from nba_lineups.modeling import partial, raw
from nba_lineups.modeling.models import weighted_rmse

warnings.filterwarnings("ignore")
OUT = PROJECT_ROOT / "reports" / "live" / "partial_window_audit.json"
REFERENCE = "2025-26"
MIN_PRE = 25


def main() -> None:
    pred = FrozenPredictor(PROJECT_ROOT / "models" / "final", PROJECT_ROOT / "reports" / "phase6")
    pipe = pred.model.pipeline
    used = pred.features_used
    scale = pd.Series(pipe.named_steps["scale"].scale_, index=used)
    mean = pd.Series(pipe.named_steps["scale"].mean_, index=used)
    with connect() as conn:
        prog = partial.season_progress(conn, CURRENT_SEASON)
        cur, ref = pred.season(conn, CURRENT_SEASON), pred.season(conn, REFERENCE)
        cutoff = cur.data_cutoff

        def eligible(f):
            return f[np.minimum(f.lu_poss, f.lu_opp_poss) >= MIN_PRE]

        # 1. drift in training-SD units (pre-imputation inputs, eligible lineups)
        drift = {}
        for name in used:
            col = name if name in cur.frame else None
            if col is None:
                continue
            drift[name] = {"current_z": float((eligible(cur.frame)[col].mean() - mean[name]) / scale[name]),
                           "reference_z": float((eligible(ref.frame)[col].mean() - mean[name]) / scale[name])}

        # 2. counterfactual full-window volume for the season in progress
        factors = {t: prog.typical_full_window / max(n, 1) for t, n in prog.per_team_games.items()}
        cf_tables = partial.scaled_tables(cur.tables, factors)
        lineups = cur.frame.reset_index()[["lineup_id", "season_id", "team_id"]]
        cf = pred._score(cf_tables, lineups)
        e = eligible(cur.frame)
        sens = partial.volume_sensitivity(e.predicted, cf.predicted.reindex(e.index), e.team_id)

        # 3. held-out backtest: shrink 2025-26 volume to the current fraction
        y = raw.load_targets(conn, [REFERENCE], key=pred._key).set_index("lineup_id")
        frac = prog.fraction
        shrunk = partial.scaled_tables(ref.tables, {t: frac for t in ref.frame.team_id.unique()})
        sp = pred._score(shrunk, ref.frame.reset_index()[["lineup_id", "season_id", "team_id"]]).predicted
        full = ref.frame.predicted
        idx = y.index.intersection(full.index)
        backtest = {
            "season": REFERENCE, "volume_fraction": frac, "n": int(len(idx)),
            "rmse_full_window": float(weighted_rmse(y.y[idx], full[idx], y.w[idx])),
            "rmse_volume_shrunk": float(weighted_rmse(y.y[idx], sp[idx], y.w[idx])),
            "rmse_team_prior_full_window": float(weighted_rmse(y.y[idx], ref.frame.team_prior[idx], y.w[idx])),
            "mean_shift_shrunk_minus_full": float((sp[idx] - full[idx]).mean()),
            "spearman_shrunk_vs_full": float(sp[idx].rank().corr(full[idx].rank())),
        }

    report = {
        "season": CURRENT_SEASON, "data_cutoff": str(cutoff),
        "progress": {"team_games_mean": prog.team_games_mean, "typical_full_window": prog.typical_full_window,
                     "fraction": prog.fraction},
        "model_artifact_sha256": pred.artifact_sha256, "model_unchanged": pred.verify(),
        "eligible_lineups_current": int(len(e)), "min_pre_poss": MIN_PRE,
        "feature_drift_z": drift, "volume_counterfactual": sens, "heldout_volume_backtest": backtest,
        "interval_half_width": 1.959963984540054 * pred.model_sd,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, default=float) + "\n")
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
