# Features, chronological validation and baselines (Phase 5)

Development seasons only (2018-19 to 2023-24). 2024-25 and 2025-26 were never read: every loader refuses them, and a test proves it (below). No Phase 6 model (linear regression, ridge, random forest) was trained.

```bash
.venv/bin/python -m nba_lineups.modeling.build            # feature table + manifest -> data/features/ (git-ignored)
.venv/bin/python scripts/phase5/features_baselines.py      # reports/phase5/ (CSVs, findings.json, fig12–fig15)
```
Both are deterministic: two builds produce a byte-identical file (SHA-256 in `data/features/manifest.json`), and the bootstrap uses fixed seeds.

## Headline findings
1. **The modeling sample:** 3,706 lineups with ≥ 25 post-break possessions on each end (effective n 1,550).
   - **55%** of these lineups (**44%** of the possessions) had **no pre-break history**. Player- and team-level features are the only information available for them.
2. **Every useful baseline is close to the measurement-noise floor.** In cross-validated, possession-weighted terms:
   - the league mean has RMSE 22.20;
   - the best baseline has 21.79;
   - a *perfect* predictor of true post-break quality would still have **21.04**, because the target itself is noisy.
   - The **R² ceiling is 0.10** (95% CI 0.05–0.15), and the best baseline reaches 0.037, about 36% of what is explainable.
3. **The team prior does most of the work.** It beats the league mean by +0.40 RMSE (0.21–0.61).
   - Lineup history shrunk toward the team prior adds **+0.017** (−0.018 to 0.051).
   - The player composite adds **+0.019** (−0.086 to 0.112).
   - Neither is distinguishable from the team prior on its own. Phase 6 has to show that *combining* the signals helps.
4. **The irregular seasons don't hurt training.** On the same validation seasons (2021-22 to 2023-24), training with and without 2019-20 and 2020-21 differs by ≤ 0.02 RMSE for every baseline.
5. **2019-20 (the bubble) is unpredictable.** All baselines have zero skill on it, and its R² ceiling is only 0.025.
6. **Collinearity:** the player ORtg, DRtg and net features are nearly linearly dependent (VIF up to 1,761). Phase 6's unpenalized linear regression must drop one of them; ridge and random forest tolerate them.

## 1. Design: two stages, so nothing learned can leak across folds

| Stage | Code | What it contains | Learned? |
|---|---|---|---|
| 1. Raw pre-break aggregates | `modeling/raw.py` | Sums of one season's **pre-break** totals: lineup rows, the lineup–player bridge, player usage, on- and off-court totals per player and team, pair co-possessions | No. These are deterministic, so they are computed once. |
| 2. Fold-fitted features | `modeling/features.py` (`FeatureBuilder`) | EB-shrunk player and lineup ratings, plus the aggregations over the five players | Yes. `fit(tables, train_seasons)` uses only the **training seasons'** pre-break data. |
| Labels | `raw.load_targets` | Post-break net rating, possessions and weight | This is the **only** function that reads post-break data. |

`cv.fold_frames` assembles each fold: it fits the builder on the training seasons, then the *same fitted builder* transforms the training and validation lineups. Phase 6 models will use the same function.

**What is fitted per fold, on training seasons only:**
- the player EB models (prior mean, τ², K) for on-court ORtg, DRtg, net, on-off and usage;
- the lineup EB model (μ, τ², K);
- the baseline intercepts and the calibration slope (from training targets);
- in Phase 6, the scaler and imputer, inside the model pipeline.

Nothing currently needs imputation. Missing information is represented by the EB prior plus an explicit indicator, so "no data" is never confused with "average."

## 2. The modeling sample
| Season | Lineups | Effective n | No history (lineups) | No history (possessions) | Weighted mean target |
|---|---|---|---|---|---|
| 2018-19 | 592 | 237 | 49.8% | 39.3% | +2.40 |
| 2019-20* | 389 | 212 | 48.1% | 39.2% | +4.12 |
| 2020-21* | 935 | 380 | 64.7% | 53.2% | +2.92 |
| 2021-22 | 558 | 262 | 53.0% | 43.5% | +2.43 |
| 2022-23 | 572 | 219 | 53.7% | 42.7% | +3.27 |
| 2023-24 | 660 | 268 | 52.7% | 41.1% | +2.61 |

\* Irregular seasons. Unit: a lineup with ≥ 25 post-break possessions on each end. Weight: post-break possessions. Effective n is Kish's (Σw)²/Σw². The weighted mean target is positive in every season: lineups that keep playing are better than average (the Phase 4 selection effect). This is why every baseline has a training-fold intercept. SQL query 13 in `sql/examples.sql` reproduces the no-history columns independently.

## 3. Feature dictionary
Every feature uses `window_type = 'pre_asb'` data only. It is **available at the end of the last pre-break game day** (`stat_windows.date_to` of the pre-break window). Machine-readable version: `reports/phase5/feature_dictionary.csv`, generated from `modeling/registry.py`.

| Feature | Group | Definition | Fitted on training folds | Without data |
|---|---|---|---|---|
| `team_off_rating_loo` | team | Team ORtg from all **other** lineups (100·Σpts/Σposs) | none | never missing |
| `team_def_rating_loo` | team | Team DRtg from all other lineups (100·Σopp_pts/Σopp_poss) | none | never missing |
| `p_off_rating_eb_mean` | player | EB-shrunk on-court ORtg, mean of the five | prior β0 + β1·log(poss), τ², K | prior of a 10-poss player |
| `p_def_rating_eb_mean` | player | EB-shrunk on-court DRtg, mean of the five | same | same |
| `p_net_rating_eb_mean` | player | EB-shrunk on-court net, mean of the five | same | same |
| `p_on_off_eb_mean` | player | EB-shrunk on-off net (on-court net − off-court net), mean of the five | same | same |
| `p_usage_eb_mean` | player | EB-shrunk usage % (player endpoint), mean of the five | same | same |
| `p_usage_eb_max` | player | Highest EB-shrunk usage % among the five | same | same |
| `p_log_poss_mean` | player | Mean log(1 + pre-break on-court possessions): role and experience | none | 0 |
| `p_team_share_min` | player | Least-used player's share of **this team's** pre-break possessions | none | 0 |
| `p_n_new_to_team` | player | Players with no pre-break possessions for this team | none | counted |
| `p_n_no_history` | player | Players with no pre-break possessions for any team | none | counted |
| `lu_log_poss` | lineup | log(1 + the lineup's own pre-break possessions) | none | 0 |
| `lu_no_history` | lineup | 1 if the lineup has no pre-break possessions on offense **or** defense (rating undefined) | none | 1 |
| `lu_net_eb_team` | lineup | The lineup's pre-break net, EB-shrunk toward the team prior (`team_net_loo` + μ) | μ, τ², K | exactly the team prior |
| `lu_pair_familiarity` | lineup | Mean over the 10 player pairs of log(1 + pre-break possessions the pair shared) | none | 0 for a pair that never shared the floor |

**Design choices:**
- **Leave-lineup-out team ratings.** These keep "team context" and "the lineup's own history" from double-counting the same possessions. For a starting unit with 1,300 possessions, the full-team rating partly *is* the lineup.
- **Player ratings are pooled over every team the player played for before the break.** Team share is computed per team. Teams come from the lineup feed, never from `last_team_id` (see §5).
- **Player shrinkage uses a playing-time-informed prior:**
  - **The prior.** The prior mean is β0 + β1·log(poss). Coaches give better players more minutes, so playing time carries information. With all six dev seasons, β1 = +2.15 net points per log-possession.
  - **The fit.** Hyperparameters are fit on training players with ≥ 10 possessions.
  - **Players with no data.** They get the prior of a 10-possession player, i.e. a fringe player. For a star returning from injury this is wrong but unknowable from pre-break data; `p_n_no_history` flags it.
- **ORtg and DRtg are shrunk separately, and net is shrunk too.** Each has its own τ and K, so `p_net_rating_eb_mean` is close to, but not exactly, ORtg − DRtg (VIF 1,761).
- **Minutes were considered and left out.** Minutes and possessions are nearly collinear (pace is roughly constant), so only possessions are used: the denominator of every rating.
- **Usage comes from the player endpoint** and is pooled across teams. The endpoint's team label leaks, but its statistics respect the date window (§6).

**Fitted parameters with all development seasons** (the per-fold values are in `reports/phase5/fold_parameters.csv`):

| EB model | τ (true SD) | K | β1 per log poss | n fitted |
|---|---|---|---|---|
| Player on-court ORtg | 4.03 | 13,296 | +3.12 | 3,087 player-seasons |
| Player on-court DRtg | 3.64 | 13,532 | +0.99 | 3,086 |
| Player on-court net | 4.53 | 13,239 | +2.15 | 3,087 |
| Player on-off net | 2.96 | 16,431 | +2.25 | 3,085 |
| Player usage % | 5.02 | 677 | +1.25 | 3,086 |
| Lineup net vs team prior | 4.80 (μ = +1.75) | 14,639 | n/a | 21,912 lineups |

Note the K values: the lineup and player models estimate K independently, and both land near Phase 4's lineup estimate (14,573). With the team prior removed, a lineup needs about **1,270 possessions** before its own history is 50% reliable. Phase 4 found 790 against the league mean; the team prior already explains part of the signal.

**Fold stability ("all" folds):**
- The lineup τ ranges from 3.30 (trained on 2018-19 only) to 4.58, and K from 14,570 to 14,956.
- The player net τ ranges from 4.42 to 4.83.
- The team-prior intercept ranges from +2.01 to +2.47.
- The calibration slope ranges from 0.61 to 0.87.
- The usage K is the least stable parameter (269–705). Usage is reliable even in small samples, so its sampling variance is hard to pin down. This has little effect, because the shrinkage factor stays near 1 for rotation players.

## 4. Chronological validation
- **Expanding window** (`modeling/splits.py`): fold *k* trains on every season before its validation season. The folds validate 2019-20, 2020-21, 2021-22, 2022-23 and 2023-24, so the first fold trains on 2018-19 alone. No fold ever trains on its own season or a later one, and seasons are whole units, so a team-season is never split.
- **Sensitivity to the irregular seasons:**
  - **`all`:** every development season.
  - **`regular_only`:** 2019-20 and 2020-21 removed from training *and* validation.
  - **`all_regular_val`:** the `all` models evaluated on the same validation seasons as `regular_only` (2021-22 to 2023-24). Comparing these two isolates the effect of *training* on irregular seasons.
- **Metrics** (`modeling/evaluation.py`):
  - MAE, RMSE and R², each unweighted and possession-weighted.
  - Skill vs the league mean (1 − MSE/MSE_league mean).
  - Paired RMSE and MAE gains vs the league mean and vs the team prior.
- **Uncertainty:** 95% percentile intervals from a cluster bootstrap over pooled out-of-fold predictions, with 1,000 resamples of whole team-seasons, because lineups of one team share players and opponents. Differences are computed on the same resampled rows (paired). The predictions themselves are held fixed, so the intervals cover evaluation-sample variability, not refitting variability.
- **Noise floor:**
  - The target is y = θ + e with Var(e) = K·h_post (h_post = 1/post_poss + 1/post_opp_poss). K comes from the fold's training data.
  - Even a predictor that knew θ exactly would have RMSE floor √mean(K·h) and MAE floor mean(√(2/π)·√(K·h)).
  - The R² ceiling is 1 − mean(K·h)/Var(y).
  - A simulation test confirms that a perfect predictor attains these bounds to within 1%.

## 5. Leakage audit
| Risk | Control | Proof (test) |
|---|---|---|
| Post-break statistics as features | All feature SQL filters `window_type = 'pre_asb'`. `PreBreakTables.validate` raises `LeakageError` on any other window. Only `load_targets` reads post-break data. | `test_post_break_rows_are_rejected`. The **poisoning test** deletes every post-break row and gets identical features. |
| `player_window_stats.last_team_id` (the API reports the *latest* team even under a date filter) | Never selected. Any table carrying the column raises `LeakageError`. Player teams come from the per-team lineup feed. | `test_last_team_id_is_rejected`. The poisoning test blanks the column with no effect. |
| Held-out seasons read during development | `check_seasons` refuses them **before any query runs**. `require_dev` re-checks every frame. Folds can't contain them. | `test_loaders_refuse_held_out_seasons_before_touching_the_database`. The poisoning test adds a decoy 2024-25 season (a relabelled copy of 2023-24, so no real held-out data is loaded) and gets identical features. |
| Team assignment | `lineups.team_id` comes from the request team of the lineup feed, which was validated in Phase 1 against the request's echoed parameters. Traded players are handled per team. | `test_traded_player_pools_both_teams_for_ratings_but_not_for_team_share` |
| Player statistics from the endpoint | Only `usg_pct` and `poss` are used. Its pre-break possessions match on-court lineup possessions within the known 3% feed difference (median ratio 0.972, p1–p99 0.955–0.988; traded players 0.936–0.986). The **stats** respect the date window; the team label does not. | Recomputed in every report run (`findings.json → usage_source_check`) |
| Shrinkage hyperparameters learned on validation data | `FeatureBuilder.fit` uses the training seasons only. | `test_fit_ignores_validation_season_data`, `test_cv_fits_every_learned_step_on_training_seasons_only` (a spy on every fold) |
| Transform of one season using another's data | `transform` subsets the tables to the requested lineups' seasons. | `test_transform_of_a_season_uses_only_that_season` |
| Target information in features | `transform` never receives the target. | `test_features_do_not_depend_on_the_target` (scrambling y leaves the features unchanged) |
| Baseline intercepts and slopes using validation targets | `fit_predict` refuses overlapping seasons. Validation targets are never read. | `test_baselines_are_unaffected_by_validation_targets`, `test_baselines_refuse_overlapping_seasons` |
| Target-driven feature selection | **No feature was dropped or chosen by its correlation with the target.** Quality flags are coverage, drift and collinearity only. | n/a (a process rule) |

**The poisoning test is not vacuous.** Removing the pre-break filter from the usage query makes it fail (verified by hand during development).

## 6. Feature quality (`reports/phase5/feature_quality.csv`, fig14, fig15)
- **Coverage:**
  - Player features are backed by real data for 98.6% of player slots.
  - Lineup history exists for 45% of lineups.
  - Pair familiarity is non-zero for 99.4%: even a brand-new lineup usually contains pairs that played together.
- **Correlation with the target** (possession-weighted, pooled, descriptive only):
  - The largest are the player net composite (0.20), lineup EB (0.19), player ORtg (0.16) and max usage (0.14).
  - All are small, as a noise floor this close to the total variance predicts.
  - Ten features keep the same sign in all six seasons. The six that don't (team share, new-to-team, no-history counts, lineup log-possessions, lineup no-history, pair familiarity) all have pooled |r| ≤ 0.11.
- **Collinearity** (VIF, from the inverse correlation matrix):
  - The player ORtg, DRtg and net group has VIFs of 1,612, 837 and 1,761 (net ≈ ORtg − DRtg).
  - The other groups: lineup EB 43 (it contains the team prior); team ORtg and DRtg 37 and 34; player log-possessions 32.
  - Pairs with |r| ≥ 0.8: team DRtg vs player DRtg (0.87); player net vs lineup EB (0.85); player on-off vs player log-possessions (0.91); lineup log-possessions vs no-history (−0.86).
- **Drift across seasons:**
  - The team and player rating *levels* move by up to 1.7 SD between seasons. The season-average team ORtg in the sample spans 6.1 points per 100.
  - Net features barely drift (player net 0.36 SD, lineup EB 0.17 SD), because both ends move together. Player on-off drifts more (0.81 SD).
  - **Phase 6 implication:** ORtg and DRtg features carry a season-level offset that net features don't. Prefer net and on-off forms, or center ratings on the season's league average.

## 7. Baselines (`modeling/baselines.py`)
Each baseline is a pre-break quantity plus parameters fitted on the training fold's targets (possession-weighted):

| Baseline | Prediction | Why it's here |
|---|---|---|
| League mean | Training weighted mean of y | Floor of usefulness |
| Team prior | `team_net_loo` + c | Phase 4: the best single prior |
| Team prior, calibrated | a + b·`team_net_loo` (one-variable WLS) | Phase 4 calibration slope 0.67 < 1 |
| EB lineup → team prior | `lu_net_eb_team` + c | The requested lineup-history baseline |
| Player composite | `p_net_rating_eb_mean` + c | Phase 4: 44% of target possessions have no lineup history |
| Raw pre-break lineup net (naive) | Raw rating; team prior if no history | What not to do: no shrinkage |

## 8. Results (all folds: 3,114 validation lineups, effective n 1,318; fig12)
**Possession-weighted**, with 95% cluster-bootstrap intervals:

| Predictor | RMSE | MAE | R² | Gain vs league mean (RMSE) | Gain vs team prior (RMSE) |
|---|---|---|---|---|---|
| League mean | 22.20 (21.55–22.91) | 16.59 | −0.000 | n/a | −0.40 (−0.61 to −0.21) |
| Team prior | 21.81 (21.20–22.46) | 16.17 | 0.035 (0.017–0.052) | **+0.40 (0.21 to 0.61)** | n/a |
| Team prior, calibrated | 21.82 (21.20–22.50) | 16.20 | 0.034 (0.019–0.047) | +0.38 (0.23 to 0.55) | −0.015 (−0.073 to 0.034) |
| EB lineup → team prior | 21.79 (21.18–22.45) | 16.16 | 0.036 (0.018–0.054) | +0.41 (0.21 to 0.63) | +0.017 (−0.018 to 0.051) |
| Player composite | 21.79 (21.19–22.44) | 16.16 | 0.037 (0.023–0.049) | +0.41 (0.27 to 0.57) | +0.019 (−0.086 to 0.112) |
| Raw lineup net (naive) | 41.08 (37.92–44.52) | 25.98 | −2.43 | −18.9 | −19.3 |
| **Noise floor (perfect predictor)** | **21.04 (20.66–21.39)** | **15.47** | **0.101 (0.053–0.149)** ceiling | n/a | n/a |

**Unweighted** (each lineup counts once; dominated by small, noisy lineups):

| Predictor | RMSE | MAE | R² |
|---|---|---|---|
| League mean | 27.07 | 21.11 | −0.001 |
| Team prior | 26.75 | 20.81 | 0.023 |
| Team prior, calibrated | 26.76 | 20.82 | 0.023 |
| EB lineup → team prior | 26.74 | 20.80 | 0.024 |
| Player composite | 26.73 | 20.77 | 0.025 (0.015–0.033) |
| Raw lineup net (naive) | 45.80 | 30.78 | −1.86 |
| Noise floor | 26.23 | 20.24 | 0.061 ceiling |

**Per fold** (weighted skill vs league mean; fig13):

| Validation season | Team prior | EB lineup | Player composite | R² ceiling |
|---|---|---|---|---|
| 2019-20* | −0.001 | −0.000 | −0.003 | 0.025 |
| 2020-21* | 0.040 | 0.044 | 0.043 | 0.081 |
| 2021-22 | 0.036 | 0.035 | 0.039 | 0.167 |
| 2022-23 | 0.039 | 0.032 | 0.044 | 0.069 |
| 2023-24 | 0.045 | 0.053 | 0.043 | 0.136 |

**Where lineup history helps** (weighted RMSE by subgroup):

| Subgroup | Lineups | Possession share | League mean | Team prior | EB lineup | Player composite | Floor |
|---|---|---|---|---|---|---|---|
| No pre-break history | 1,743 | 45% | 25.01 | 24.43 | 24.43 | 24.48 | 23.39 |
| History < 100 poss | 1,098 | 33% | 22.14 | 21.86 | 21.86 | 21.81 | 21.61 |
| History ≥ 100 poss | 273 | 21% | 14.68 | 14.60 | 14.52 | 14.43 | 13.51 |

Lineup EB equals the team prior when there's no history, by construction. It helps only where history is substantial, and even there the gain is small: about 0.08 RMSE against a gap to the floor of about 1.1.

**Irregular seasons** (weighted, validation 2021-22 to 2023-24, n = 1,790, effective n 744):

| Training | League mean | Team prior | EB lineup | Player composite | Floor | R² ceiling |
|---|---|---|---|---|---|---|
| All dev seasons (`all_regular_val`) | 22.34 | 21.89 | 21.89 | 21.87 | 20.88 | 0.126 |
| Without 2019-20 and 2020-21 (`regular_only`) | 22.34 | 21.89 | 21.88 | 21.86 | 21.02 | 0.115 |

The floors differ slightly because K is estimated from each variant's training data.

## 9. What this means for Phase 6
- **The bar.** A model is useful only if it beats the **team prior**, not just the league mean, with a paired interval that excludes zero. The most it can gain is about 0.76 weighted RMSE (21.81 → 21.04). Realistically it's much less, because "perfect knowledge of true quality" isn't available from pre-break data.
- **Collinearity.** For linear regression, use one of {player net} or {player ORtg, DRtg}, not all three; ridge can keep all of them. Expect ridge ≥ linear regression; random forest has little room with an effective n of about 1,300.
- **Report against the noise floor.** Report skill as a share of the R² ceiling, as well as raw R².
- **Weight choice matters.** Weighted and unweighted results rank the baselines the same way, but at different scales. Keep reporting both.

## 10. Concepts (interview notes)
- **Fit/transform discipline.** Anything *learned* (a mean, a variance, a shrinkage factor, a scaler) is part of the model. It must be fit inside each training fold, or validation scores are optimistic. Deterministic per-row transformations (sums, logs) can be computed once.
- **Expanding-window CV.** Time-ordered data needs time-ordered validation. Random K-fold would train on 2023-24 to predict 2019-20, and would split a team-season across folds.
- **Leave-one-out team prior.** Excluding a unit's own data from its context feature prevents double-counting and target-like leakage at the team level.
- **Empirical Bayes as feature engineering.** Shrinkage turns noisy rates into the expected true value. It handles missing data naturally: no data means the prior, plus an indicator so the model knows.
- **Noise floor and R² ceiling.** When the target is measured with known noise, the best achievable error is known in advance. Low R² here is a property of the target, not a failure of the model.
- **Paired bootstrap comparisons.** Two models evaluated on the same rows have correlated errors. Bootstrapping the *difference* is far more precise than comparing two marginal intervals: here, overlapping marginal RMSE intervals hide a significant +0.40 gain.
- **Cluster bootstrap.** Resample the unit of dependence (team-season), not the row.
- **VIF.** 1/(1 − R²) of a feature regressed on all the others. It reveals multi-way dependencies (net ≈ ORtg − DRtg) that pairwise correlations miss.
- **Poisoning (metamorphic) tests.** Change data the code must not use; the output must not change. This proves the absence of a leak instead of assuming it.

## 11. Outputs (for Phase 6, React and Power BI)
| File | Contents |
|---|---|
| `reports/phase5/feature_dictionary.csv` | The table in §3 |
| `reports/phase5/feature_quality.csv`, `feature_correlation.csv` | §6 |
| `reports/phase5/baseline_metrics.csv` | Tidy: evaluation × predictor × weighting × metric, with estimate, lo, hi |
| `reports/phase5/baseline_per_fold.csv` | The same metrics per validation season |
| `reports/phase5/fold_parameters.csv` | Fitted hyperparameters per fold |
| `reports/phase5/findings.json` | Every number in this document |
| `reports/phase5/figures/fig12–fig15` | Baselines vs the noise floor, per-fold skill, feature–target correlations, feature correlations |
| `data/features/` (git-ignored) | `lineup_features_dev.csv.gz` and `manifest.json` (commit, seasons, parameters, SHA-256) |
