# Model card: post-All-Star-break lineup net rating

| | |
|---|---|
| Model | Linear regression on 11 VIF-pruned features, with possession weights |
| Artifact | `models/final/model.joblib` (SHA-256 in `models/final/frozen_spec.json`) |
| Frozen | 2026-11-14 01:34 UTC, commit `68c312f`, before the held-out evaluation |
| Trained on | Regular seasons 2018-19 to 2023-24 (3,706 lineups) |
| Tested on | 2024-25 and 2025-26 (1,369 lineups), evaluated once |
| Software | Python 3.12.3, scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.1 |
| Owner | Personal portfolio project (non-commercial); data from NBA.com/stats via `nba_api` |

## What it predicts
**Estimand:** given that a coach plays a specific five-man lineup after the All-Star break, its expected post-break net rating (points per 100 possessions, own minus opponent), using only information available at the break.
- **Conditional.** Training and evaluation use lineups that played **≥ 25 possessions on each end** after the break. The model does **not** predict whether a lineup will be used. Phase 4 showed that heavily used lineups are a selected, better-than-average group.
- **The weight** is post-break possessions: lineups that play more count more.
- **The inputs** come from pre-break data of the same season only (`docs/features_baselines.md`):
  - team offense and defense from the team's other lineups;
  - the five players' shrunk defensive rating, on-off and usage;
  - roster indicators;
  - the lineup's own pre-break volume.

## Performance
**Final test**, held-out seasons, possession-weighted, with 95% team-season cluster-bootstrap intervals:

| | 2024-25 | 2025-26 | Pooled |
|---|---|---|---|
| RMSE | 23.31 | 25.18 | 24.23 |
| MAE | 17.49 | 19.05 | 18.25 |
| R² | 0.054 | 0.084 | 0.070 (0.033–0.098) |
| R² ceiling (measurement noise) | 0.177 | 0.247 | 0.214 |
| RMSE vs **team prior** | −0.04 (−0.31, +0.23) | −0.11 (−0.42, +0.17) | **−0.08 (−0.29, +0.12)** |
| RMSE vs league mean | −0.68 (−1.20, −0.20) | −1.15 (−1.76, −0.52) | −0.91 (−1.30, −0.54) |

Development cross-validation (2019-20 to 2023-24) agrees: weighted RMSE 21.73 vs 21.81 for the team prior, a difference of −0.07 (−0.20, +0.05).

**How to read this:**
- **The ceiling.** Post-break ratings of real lineups are measured from a few dozen to a few hundred possessions, so most of their variation is sampling noise. A predictor that knew every lineup's *true* quality would still have RMSE ≈ 22.3 and R² ≈ 0.21 on the held-out seasons.
- **What the model achieves.** It reaches about a third of that explainable variance.
- **Against the baselines.** It clearly beats predicting the league average. It is **statistically indistinguishable from a simple team-strength prior** (the team's pre-break net rating from its other lineups, plus an intercept).

## Appropriate use
- **Good for:**
  - ranking candidate lineups *within the team-strength context*;
  - giving a shrunk, noise-aware expectation for a lineup that has little or no history;
  - showing why raw small-sample lineup ratings mislead. The raw pre-break rating has RMSE about 41, vs 21.8 in cross-validation.
- **Always show alongside a prediction:** its uncertainty. From sampling noise alone, a lineup's observed post-break rating varies by ±67 net points at 25 possessions and ±19 at 300 (95% interval, 1.96·√(K·(1/poss + 1/opp_poss))) and the team-prior baseline.
- **Not for:**
  - betting, contracts, player evaluation, or any decision about individuals;
  - predicting playoff performance (different opponents and rotations; not tested);
  - lineups from seasons, leagues or eras outside 2018-19 to 2025-26;
  - claims that a specific lineup "is" +X. With R² ≈ 0.07, a point prediction for one lineup is mostly uninformative.

## Limitations
- **Noise-dominated target.** In development cross-validation, 93.5% of residuals (possession-weighted) fell within the target's own ±1.96 sampling SD. Better modeling can't fix that; only more possessions can.
- **No significant gain over the team prior.** The extra features (player shrunk ratings, usage, lineup history) are justified for interpretability and for new lineups, not for proven accuracy.
- **Calibration drift.** In 2025-26 the predictions were too conservative (calibration slope 1.48, CI 1.00–1.86): real lineup differences were larger than predicted.
- **Season effects are not modeled.** Rating levels drift as league scoring changes. The team ORtg and DRtg features carry this drift, which is partly absorbed by the intercept.
- **Players without pre-break data** (injury returns, late signings) get a fringe-player prior. Predictions for lineups containing a returning star are biased low. `p_n_no_history` flags them.
- **The irregular seasons** (2019-20 bubble, 2020-21) are in the training data. Excluding them didn't help (`docs/modeling.md` §2), but 2019-20 was unpredictable for every method.
- **Data constraints:**
  - Lineup data comes from NBA.com aggregates (no play-by-play), so there's no opponent-quality or schedule adjustment.
  - Possession counts follow the lineup feed's own definition (about 3% higher than the team endpoint).

## Ethical and data considerations
- **No personal data beyond public sports statistics.** NBA data is owned by the NBA and used for personal, non-commercial education under the NBA.com terms. Raw data isn't redistributed.
- **Players are not ranked or judged by this model.** Player-level inputs are aggregated and shrunk, and the outputs describe lineups, with large uncertainty.

## Reproducibility
```bash
.venv/bin/python -m nba_lineups.modeling.build                 # features (deterministic, SHA-256 in manifest)
.venv/bin/python scripts/phase6/train_evaluate.py              # nested CV + selection + freeze (deterministic)
.venv/bin/python scripts/phase6/holdout_evaluation.py          # final test; requires the committed freeze
```
To load the model in Python: `nba_lineups.modeling.final.load("models/final")` returns a `LineupModel`. Use `.predict(tables, lineups)` with pre-break tables from `modeling.raw`. The same scikit-learn version is required to unpickle it.

Full evaluation, interpretability and the leakage audit: `docs/modeling.md`.

**Serving:** the REST API (`docs/api.md`) serves this exact artifact read-only. Each prediction comes with the team-prior baseline, model and sampling uncertainty, and the notes above. `GET /api/v1/model` re-verifies the SHA-256.
