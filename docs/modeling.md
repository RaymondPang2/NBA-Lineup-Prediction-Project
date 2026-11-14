# Machine learning: training, evaluation and interpretability (Phase 6)

```bash
.venv/bin/python scripts/phase6/train_evaluate.py        # development: nested CV, interpretability, selection, freeze
git add models/final && git commit ...                   # the freeze must be committed before the next step
.venv/bin/python scripts/phase6/holdout_evaluation.py    # final test, run once (refuses unless the freeze is committed)
```
The development script is deterministic: two consecutive runs produced byte-identical reports.

## Conclusion
**Machine learning does not beat the simple baselines in any way we can statistically detect.**
- **Every model beats the league mean.** This holds clearly in cross-validation and on the held-out seasons.
- **No model beats the team prior with a confidence interval that excludes zero.** On the held-out seasons, the frozen linear regression's possession-weighted RMSE is **0.08 lower** than the team prior's (95% CI −0.29 to +0.12).
- **The ceiling explains why.** The target's measurement noise leaves an R² ceiling of 0.10 in cross-validation and 0.21 on the held-out seasons. The best models reach about 0.04 and 0.07 respectively: about a third of what any predictor could explain, the same share the team prior achieves.

| Final test (frozen linear regression, possession-weighted) | 2024-25 | 2025-26 | Pooled |
|---|---|---|---|
| Lineups (effective n) | 674 (321) | 695 (298) | 1,369 (619) |
| RMSE: model | 23.31 | 25.18 | 24.23 |
| RMSE: team prior | 23.35 | 25.30 | 24.31 |
| RMSE: league mean | 23.99 | 26.33 | 25.15 |
| RMSE noise floor (perfect predictor) | 21.74 | 22.83 | 22.27 |
| **Model − team prior** (RMSE, 95% CI) | −0.04 (−0.31, +0.23) | −0.11 (−0.42, +0.17) | **−0.08 (−0.29, +0.12)** |
| Model − league mean | −0.68 (−1.20, −0.20) | −1.15 (−1.76, −0.52) | −0.91 (−1.30, −0.54) |
| R²: model / team prior / ceiling | 0.054 / 0.051 / 0.177 | 0.084 / 0.076 / 0.247 | 0.070 / 0.064 / 0.214 |

The pre-registered primary question, whether the model's weighted RMSE minus the team prior's is below zero with a CI excluding zero, is answered **no**.

## 1. Design
**Nested chronological cross-validation** (`modeling/tuning.py`):
- **Outer loop.** The Phase 5 expanding-window folds validate 2019-20 through 2023-24, and estimate out-of-sample performance.
- **Inner loop.** For each outer fold, hyperparameters are chosen by a *second* expanding-window CV over that fold's training seasons only. Features are refit per inner fold too. The outer validation season never influences tuning, feature fitting, preprocessing or selection.
- **Criterion:** pooled possession-weighted RMSE over the inner validation rows.
- **Exception:** the first outer fold (validating 2019-20) has one training season, so chronological tuning is impossible there. It uses **pre-registered defaults**, written in `models.py` before any result existed: ridge α = 100; forest depth 5, at least 50 lineups per leaf, `max_features` 0.33.
- **Determinism:**
  - Exact ties in tuning go to the simplest grid entry.
  - The forest predicts single-threaded: parallel prediction sums trees in a random order, and that flipped an exact tie between two runs during development.

**Models** (`modeling/models.py`). Every preprocessing step is part of a scikit-learn `Pipeline`, so it is fitted on the training fold only. Sample weights are post-break possessions, normalized to mean 1, which makes ridge's α independent of fold size.

| Model | Pipeline | Tuned |
|---|---|---|
| Linear regression | median imputer → **VIF selector** (drop the highest-VIF feature until all ≤ 10; never sees y) → scaler → OLS | nothing (the VIF threshold was fixed in advance) |
| Ridge | median imputer → scaler → ridge, all 16 features | α ∈ 12 values, 0.1 to 31,623 (log-spaced) |
| Random forest | median imputer → 300 trees, all 16 features | max depth {3, 5, 8, none} × min lineups per leaf {200, 100, 50, 25} × max features {0.33, 0.66} |

**Selection rule** (`modeling/final.py`, pre-registered):
- Lowest pooled weighted out-of-fold RMSE in the `all` variant.
- One-standard-error rule: take the simplest model (linear, then ridge, then forest) whose RMSE is within one paired bootstrap SE of the best.
- Final hyperparameters come from chronological CV over all six development seasons. Then the feature builder, model and baselines are fit on all development seasons.

**Freeze protocol** (`modeling/final.py`, `modeling/holdout.py`, `modeling/access.py`):
- **The spec.** `models/final/frozen_spec.json` records the model, its features, the selection evidence, the hyperparameters, the baseline parameters, the full evaluation plan (seasons, metrics, references, bootstrap settings, primary question) and the artifact's SHA-256.
- **The gate.** Every loader refuses 2024-25 and 2025-26 without a `HoldoutKey`. `holdout.unlock()` issues one only if the spec says "frozen", the artifact hash matches, and both files are committed to git and unchanged.
- **The history.** The freeze was committed and pushed as `68c312f` (2026-11-13 20:35 −05:00) **before** the held-out evaluation ran. Even with a key, the feature builder refuses to be *fitted* on held-out seasons.

## 2. Development results (nested CV, validation 2019-20 to 2023-24: 3,114 lineups, effective n 1,318)
**Possession-weighted**, with team-season cluster bootstrap 95% CIs (1,000 resamples). Differences are paired:

| Predictor | RMSE | MAE | R² | RMSE − team prior | RMSE − league mean |
|---|---|---|---|---|---|
| League mean | 22.20 | 16.59 | −0.000 | +0.40 | n/a |
| Team prior | 21.81 | 16.17 | 0.035 | n/a | −0.40 |
| Team prior, calibrated | 21.82 | 16.20 | 0.034 | +0.015 | −0.38 |
| EB lineup → team prior | 21.79 | 16.16 | 0.036 | −0.017 | −0.41 |
| Player composite | 21.79 | 16.16 | 0.037 | −0.019 | −0.41 |
| **Linear regression** | **21.73** | **16.09** | **0.042 (0.023–0.058)** | **−0.074 (−0.201, +0.047)** | −0.470 (−0.676, −0.264) |
| Ridge | 21.81 | 16.22 | 0.034 | +0.008 (−0.139, +0.145) | −0.388 (−0.563, −0.212) |
| Random forest | 21.80 | 16.22 | 0.035 | −0.005 (−0.144, +0.124) | −0.401 (−0.581, −0.217) |
| Noise floor / R² ceiling | 21.04 | 15.47 | 0.101 (0.054–0.147) | −0.76 (best possible) | n/a |

**Unweighted:**

| Predictor | RMSE | MAE | R² | RMSE − team prior |
|---|---|---|---|---|
| League mean | 27.07 | 21.11 | −0.001 | +0.32 |
| Team prior | 26.75 | 20.81 | 0.023 | n/a |
| Linear | 26.71 | 20.76 | 0.026 | −0.042 (−0.163, +0.075) |
| Ridge | 26.74 | 20.81 | 0.024 | −0.008 (−0.132, +0.106) |
| Random forest | 26.71 | 20.77 | 0.026 | −0.041 (−0.166, +0.071) |
| Noise floor / ceiling | 26.23 | 20.24 | 0.061 | n/a |

Linear regression vs the other baselines (weighted): vs EB lineup −0.057 (−0.173, +0.057); vs player composite −0.055 (−0.144, +0.035).

**By validation season** (weighted RMSE; model − team prior with 95% CI; fig17):

| Season | Team prior | Linear | Floor | Linear − TP | Ridge − TP | Forest − TP |
|---|---|---|---|---|---|---|
| 2019-20* | 22.30 | 22.49 | 21.96 | +0.18 (−0.25, +0.55) | +0.18 | +0.28 |
| 2020-21* | 21.44 | 21.39 | 20.99 | −0.05 (−0.28, +0.18) | +0.20 | +0.15 |
| 2021-22 | 22.52 | 22.36 | 20.92 | −0.16 (−0.42, +0.11) | −0.11 | −0.11 |
| 2022-23 | 21.38 | 21.35 | 21.04 | −0.03 (−0.27, +0.20) | −0.06 | −0.05 |
| 2023-24 | 21.79 | 21.58 | 20.72 | −0.22 (−0.55, +0.09) | −0.19 | −0.24 |

\* Irregular seasons. All three models are *worse* than the team prior on 2019-20, the bubble. That fold also trains on a single season with default hyperparameters, so the two causes can't be separated. From 2021-22 on, every model is ahead of the team prior in every season, but no single season's interval excludes zero.

**By pre-break history** (weighted):

| Subgroup | Lineups | Team prior | Linear | Floor | Linear − TP |
|---|---|---|---|---|---|
| No pre-break history | 1,743 | 24.43 | 24.43 | 23.39 | −0.01 (−0.18, +0.16) |
| History < 100 poss | 1,098 | 21.86 | 21.72 | 21.61 | −0.14 (−0.30, +0.03) |
| History ≥ 100 poss | 273 | 14.60 | 14.45 | 13.51 | −0.15 (−0.54, +0.20) |

The models add nothing for brand-new lineups (45% of possessions): their team and player features are the only information, and the team prior already uses most of it. The small gains come from lineups with history.

**With and without the irregular seasons** (weighted; validation 2021-22 to 2023-24; n = 1,790; effective n 744):

| Training | Team prior | Linear | Ridge | Forest | Linear − TP |
|---|---|---|---|---|---|
| All development seasons | 21.89 | 21.75 | 21.77 | 21.75 | −0.14 (−0.31, +0.03) |
| Without 2019-20 and 2020-21 | 21.89 | 21.77 | 21.79 | 21.85 | −0.13 (−0.32, +0.06) |

Excluding the irregular seasons from training doesn't help; the forest gets slightly worse with less data. The intervals sit closest to excluding zero on the regular seasons, but none excludes it.

## 3. Interpretability (fig18, fig19)
**Final model** (linear regression, trained on all six development seasons). Coefficients are in net-rating points per 1 SD of each feature:

| Feature | Coefficient | Feature | Coefficient |
|---|---|---|---|
| `team_off_rating_loo` | +3.05 | `p_def_rating_eb_mean` | −2.01 |
| `p_usage_eb_max` | +1.93 | `lu_no_history` | −1.85 |
| `p_on_off_eb_mean` | +1.79 | `lu_log_poss` | −0.96 |
| `p_n_no_history` | +1.20 | `team_def_rating_loo` | −0.63 |
| `p_usage_eb_mean` | +0.38 | `p_n_new_to_team` | −0.46 |
| | | `p_team_share_min` | −0.27 |

The intercept is +2.24.

**Dropped by VIF pruning**, in order with the VIF at the time of dropping:
1. `p_net_rating_eb_mean` (1,761; it's ≈ ORtg − DRtg)
2. `lu_net_eb_team` (43; it contains the team prior)
3. `p_log_poss_mean` (20)
4. `p_off_rating_eb_mean` (18)
5. `lu_pair_familiarity` (10.6)

Across the five outer folds, the same four were always dropped, and familiarity was kept in 2 of 5 folds.

**Reading the coefficients:**
- **Better team offense and defense predict a better lineup.** Strong own-team offense helps (+3.05). Better player defense (a lower DRtg) helps (−2.01 on DRtg, i.e. a better defense raises the prediction). On-off adds to that.
- **Usage concentration matters.** The highest usage among the five gets +1.93: lineups built around a high-usage creator do better.
- **Correlated features can't be read one at a time.** `lu_no_history` and `lu_log_poss` (r = −0.86) are only interpretable jointly. `p_n_no_history` is positive because players without data are assigned a fringe-player *prior*; the coefficient corrects that prior upward. It's a correction term, not "unknown players are good."

**Ridge shows why collinearity matters.** In the fold where inner CV picked α = 0.1, the player net and ORtg coefficients were +13.2 and −13.1. They cancel, because net ≈ ORtg − DRtg. Their single-feature permutation importances are inflated for the same reason (1.62 and 1.41): shuffling one half of a cancelling pair breaks the cancellation. Grouped importance avoids this artifact.

**Grouped permutation importance.** This is the weighted RMSE increase on validation folds when a group of features is shuffled together, averaged over the five folds:

| Group | Linear | Ridge | Forest |
|---|---|---|---|
| Player ratings (ORtg, DRtg, net, on-off) | 0.32 | 0.58 | 0.34 |
| Team ratings | 0.21 | 0.17 | 0.02 |
| Player usage | 0.19 | 0.15 | 0.06 |
| Lineup history | 0.06 | 0.04 | 0.04 |
| Player role and roster | 0.01 | 0.32 | −0.00 |
| Familiarity | 0.02 | 0.00 | −0.00 |

Player ratings matter most in every model. The forest leans almost entirely on `p_net_rating_eb_mean`, which carries the team and player signal in one feature. Familiarity and roster-role features add essentially nothing beyond the ratings.

## 4. Diagnostics (fig20, fig21)
- **Calibration** (weighted slope of the outcome on the prediction; 1 is ideal):
  - Team prior 0.93, linear 1.04 (0.81–1.25), ridge 1.05, forest 1.09.
  - Decile plots track the diagonal within their intervals.
  - Ridge and the forest shrink predictions more (prediction SD 3.9 and 3.8, vs 4.3 for linear).
- **Residuals vs noise.** Residuals divided by the target's own sampling SD have a weighted RMS of **1.04** for linear (1.00 would mean pure noise), and 93.5% lie inside ±1.96 sampling SD. **Almost all remaining error is measurement noise in the target**, which no model can remove.
- **Overfitting.** Mean training vs validation weighted RMSE: linear 20.73 vs 21.83, ridge 20.76 vs 21.89, forest 20.58 vs 21.89.
  - The forest has the largest gap (1.32), despite tuning choosing shallow trees (depth 3) with at least 100 lineups per leaf.
  - Part of every gap is not overfitting: training and validation seasons have different noise floors.
- **Tuning curves.** Ridge's inner-CV curve is flat (within 0.03 RMSE) for α up to about 1,000, so the choice of α barely matters.
  - The exception is the outer fold validating 2020-21, whose only inner validation season is 2019-20. Nothing predicted the bubble, so the maximum penalty won (α = 10,000).
  - Chosen α by fold: 100 (default), 10,000, 0.1, 316, 316. This instability is itself a finding: with five seasons, regularization strength isn't well identified.

## 5. Final test protocol and results (fig22)
1. **Development.** Model selection, hyperparameters and the evaluation plan were finalized on development seasons only.
2. **Freeze.** The artifact and spec were written, and then committed and pushed (`68c312f`).
3. **Final test.** `holdout_evaluation.py` unlocked the held-out seasons, transformed them with the frozen feature builder (fit on 2018-19 to 2023-24), and scored the frozen model and the frozen baselines. Nothing was refit.

**Results:** see the table at the top. A few more details:
- **Calibration on the held-out seasons.** The pooled slope is 1.22 (0.94–1.49), and in 2025-26 alone it is 1.48 (1.00–1.86). In 2025-26 the predictions were *too conservative*: true differences between lineups were larger than predicted. The R² ceiling is also higher in the held-out seasons (0.21 vs 0.10), meaning more real lineup-to-lineup variation.
- **By history (pooled, weighted RMSE minus the team prior):** no history −0.05 (−0.34, +0.23); history < 100 possessions −0.06 (−0.34, +0.21); history ≥ 100 possessions −0.29 (−0.73, +0.17).
- **Unweighted pooled:** model minus team prior +0.02 (−0.17, +0.22).

**Not done, by design:**
- No other model was evaluated on the held-out seasons.
- Nothing was retuned after seeing them.
- No model was retrained on 2024-25. If one is trained for deployment, it is a separate deployment experiment, not the reported test.

## 6. Leakage audit (Phase 6 additions to the Phase 5 audit)
| Risk | Control | Test |
|---|---|---|
| Hyperparameters tuned on the outer validation season | Inner expanding-window CV over training seasons only | `test_tuning_never_sees_the_outer_validation_season` |
| Preprocessing (imputer, VIF selection, scaler) fit on validation rows | All are `Pipeline` steps fit on the training fold | `test_preprocessing_is_fitted_on_training_rows_only` |
| Validation targets influencing predictions | Predictions computed without them | `test_model_predictions_do_not_depend_on_validation_targets` |
| Feature selection using the target | VIF selection is unsupervised | `test_vif_selector_removes_an_exact_linear_combination_and_ignores_y` |
| Model selection peeking at the holdout | The rule uses development out-of-fold predictions only; holdout access requires the committed freeze | `test_unlock_requires_the_model_to_be_committed`, `test_unlock_rejects_edits_after_the_freeze`, `test_unlock_rejects_a_swapped_artifact`, `test_key_cannot_be_forged` |
| Fitting on held-out seasons | `FeatureBuilder.fit` and `fit_final` refuse non-development seasons, even with a key | `test_key_admits_held_out_seasons_but_fitting_on_them_is_still_refused`, `test_final_fit_refuses_held_out_targets` |
| Noise floor using validation information | K is estimated from training pre-break data | Phase 5 |

**One remaining item is a design property, not a leak.** The modeling sample is "lineups that play ≥ 25 post-break possessions." That uses post-break information to define *which* lineups are predicted, not as an input. It makes the prediction conditional (see the model card).

## 7. Concepts (interview notes)
- **Nested cross-validation.** Tuning and performance estimation need separate data. If you tune on the same folds you report, the reported score is optimistically biased by the selection itself.
- **One-standard-error rule.** When models are statistically tied, prefer the simplest. Here linear regression was both the best and the simplest.
- **Pre-registration and freezing.** Writing the selection rule and evaluation plan down, hashed and committed, *before* seeing the test set removes "forking paths": the many small choices that quietly tune a model to its test set.
- **VIF selection vs regularization.** OLS cannot identify coefficients of near-linear combinations, so drop them. Ridge keeps them but shrinks; with a tiny α it doesn't, as the ±13 coefficients show.
- **Permutation importance on validation data**, and why correlated features break it. Shuffle groups instead.
- **Calibration slope.** Above 1 means predictions are too conservative; below 1 means too extreme. Shrinkage-style models tend toward conservative.
- **A noisy target bounds R².** Here the residuals are about 1.04× pure noise. The honest claim is "the model captures about a third of the explainable variance," not "R² = 0.07 is bad."
- **Statistically indistinguishable is a result.** A more complex model that doesn't beat a transparent baseline shouldn't replace it on accuracy grounds. It can still be kept for consistency with the API, but with that caveat.

## 8. Outputs
| File | Contents |
|---|---|
| `models/final/model.joblib`, `frozen_spec.json` | The frozen model (feature builder + pipeline + baseline parameters) and its specification |
| `reports/phase6/model_comparison.csv` | Every metric and paired difference, three evaluations (all, all_regular_val, regular_only) |
| `reports/phase6/by_season_and_history.csv` | Per season and per history group, with CIs |
| `reports/phase6/chosen_hyperparameters_by_fold.csv`, `tuning_curves.csv` | Tuning |
| `reports/phase6/coefficients_by_fold.csv`, `*permutation_importance_by_fold.csv` | Interpretability |
| `reports/phase6/calibration_bins.csv`, `overfitting_by_fold.csv` | Diagnostics |
| `reports/phase6/findings_dev.json` | Development numbers |
| `reports/phase6/holdout/` | Final test: metrics, by-history results, calibration, findings |
| `reports/phase6/figures/fig16–fig22` | Figures |
