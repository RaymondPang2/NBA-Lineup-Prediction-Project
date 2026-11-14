"""Model card and performance, read from the Phase 6 artifacts. Nothing here is typed in by hand.

Numbers come from three committed files:
  models/final/frozen_spec.json                 what was frozen (model, features, selection, plan)
  reports/phase6/findings_dev.json              nested development cross-validation (2019-20 .. 2023-24)
  reports/phase6/holdout/holdout_findings.json  the one-time held-out evaluation (2024-25, 2025-26)

The prose (appropriate use, limitations) mirrors docs/model_card.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...modeling.registry import AUXILIARY, FEATURES

WEIGHTING = "weighted"     # possession-weighted: the pre-registered primary weighting
MODEL = "linear"

DESCRIPTIONS = {f.name: f.description for f in FEATURES} | dict(AUXILIARY)

ESTIMAND = ("Expected post-All-Star-break net rating (points per 100 possessions, own minus opponent) of a "
            "five-man lineup GIVEN that its coach plays it after the break, from pre-break information only. "
            "It does not predict whether, or how much, the lineup will be used.")

APPROPRIATE_USE = [
    "Ranking candidate lineups within the team-strength context.",
    "A shrunk, noise-aware expectation for a lineup with little or no pre-break history.",
    "Showing why raw small-sample lineup ratings mislead.",
    "Always shown with its uncertainty and next to the team-prior baseline.",
]
NOT_FOR = [
    "Betting, contracts, player evaluation, or any decision about individuals.",
    "Playoff performance (different opponents and rotations; not tested).",
    "Seasons, leagues or eras outside 2018-19 to 2025-26.",
    "Claims that a specific lineup 'is' +X: with R² ≈ 0.07, one lineup's point prediction is mostly uninformative.",
]
LIMITATIONS = [
    "Noise-dominated target: most variation in post-break lineup ratings is sampling noise; only more possessions fix that.",
    "Not statistically better than the team-prior baseline (see /model/performance).",
    "Calibration drift: in 2025-26 predictions were too conservative (slope 1.48): real differences were larger than predicted.",
    "Season effects are not modeled; league scoring drift is carried only by the team rating features and the intercept.",
    "Players without pre-break data (injury returns, late signings) get a fringe-player prior, so lineups with a returning star are biased low.",
    "The irregular seasons 2019-20 and 2020-21 are in the training data.",
    "NBA.com lineup aggregates only (no play-by-play): no opponent-quality or schedule adjustment.",
]


@dataclass(frozen=True)
class ModelReports:
    spec: dict
    dev: dict          # metric key -> [estimate, lo, hi]
    dev_n: int | None
    holdout: dict      # evaluation name -> {"n":..., "metrics": {...}}

    @classmethod
    def load(cls, model_dir: Path, reports_dir: Path) -> ModelReports:
        spec = json.loads((model_dir / "frozen_spec.json").read_text())
        dev_path, ho_path = reports_dir / "findings_dev.json", reports_dir / "holdout" / "holdout_findings.json"
        dev, dev_n = spec["development_cv_summary"], None
        if dev_path.exists():
            d = json.loads(dev_path.read_text())
            dev, dev_n = d["comparison"]["all"], d["comparison_n"]["all"]["n"]
        holdout = json.loads(ho_path.read_text())["evaluations"] if ho_path.exists() else {}
        return cls(spec, dev, dev_n, holdout)

    # ------------------------------------------------------------------ uncertainty
    def model_error_sd(self) -> tuple[float, str]:
        """SD of the prediction error about the lineup's TRUE rating: sqrt(MSE − mean noise variance).

        The observed error mixes two independent parts, (y − ŷ) = (θ − ŷ) + (y − θ); the second has variance
        K·h (the noise floor²). Uses the pooled held-out evaluation when available: it is out-of-sample for the
        frozen model and larger (more conservative) than the development estimate."""
        for src, m in (("held-out evaluation 2024-25 + 2025-26 (pooled)", self.holdout.get("pooled", {}).get("metrics")),
                       ("development cross-validation 2019-20 .. 2023-24", self.dev)):
            if m:
                rmse = m[f"{MODEL}|{WEIGHTING}|rmse"][0]
                floor = m[f"noise_floor|{WEIGHTING}|rmse_floor"][0]
                return float(max(rmse ** 2 - floor ** 2, 0.0) ** 0.5), src
        raise RuntimeError("no evaluation results found")

    # ------------------------------------------------------------------ performance
    @staticmethod
    def _est(m: dict, key: str) -> dict | None:
        v = m.get(key)
        return None if v is None else {"estimate": v[0], "lo": v[1], "hi": v[2]}

    def _summary(self, name: str, m: dict, n: int | None) -> dict:
        w = WEIGHTING
        return {"evaluation": name, "n_lineups": n,
                "rmse_model": self._est(m, f"{MODEL}|{w}|rmse"),
                "rmse_team_prior": self._est(m, f"team_prior|{w}|rmse"),
                "rmse_league_mean": self._est(m, f"league_mean|{w}|rmse"),
                "rmse_noise_floor": self._est(m, f"noise_floor|{w}|rmse_floor"),
                "r2_model": self._est(m, f"{MODEL}|{w}|r2"),
                "r2_ceiling": self._est(m, f"noise_floor|{w}|r2_ceiling"),
                "model_minus_team_prior": self._est(m, f"{MODEL}|{w}|rmse_minus_team_prior"),
                "model_minus_league_mean": self._est(m, f"{MODEL}|{w}|rmse_minus_league_mean"),
                "calibration_slope": self._est(m, f"{MODEL}|{w}|calibration_slope")}

    def performance(self) -> dict:
        held = [self._summary(k, v["metrics"], v.get("n")) for k, v in self.holdout.items()]
        pooled = self.holdout.get("pooled", {}).get("metrics") or self.dev
        tp = pooled[f"{MODEL}|{WEIGHTING}|rmse_minus_team_prior"]
        lm = pooled.get(f"{MODEL}|{WEIGHTING}|rmse_minus_league_mean")
        beats_tp, beats_lm = tp[2] < 0, lm is not None and lm[2] < 0
        conclusion = (f"On the held-out seasons the model's possession-weighted RMSE minus the team prior's is "
                      f"{tp[0]:+.2f} (95% CI {tp[1]:+.2f} to {tp[2]:+.2f}): "
                      + ("the model is better than the team prior." if beats_tp else
                         "statistically indistinguishable from the team prior. ")
                      + (f"It does beat the league mean ({lm[0]:+.2f}, CI {lm[1]:+.2f} to {lm[2]:+.2f})."
                         if beats_lm else ""))
        return {"weighting": "possession-weighted (post-break possessions)",
                "development_cv": self._summary("development CV 2019-20..2023-24", self.dev, self.dev_n),
                "held_out": held, "beats_team_prior": bool(beats_tp), "beats_league_mean": bool(beats_lm),
                "conclusion": conclusion.strip()}

    def team_prior_note(self) -> str:
        p = self.performance()
        return ("Not shown to beat the team-prior baseline. " if not p["beats_team_prior"] else "") + p["conclusion"]
