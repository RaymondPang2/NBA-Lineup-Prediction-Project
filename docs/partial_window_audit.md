# Audit: the frozen model on a partial pre-break window (2026-27)

**Question:** can the frozen Phase 6 linear model, which was developed on *completed* pre-All-Star-break windows of about 55 games per team, safely score the 2026-27 season while it is in progress?

**Answer:** yes, as a **provisional** prediction with a disclosed bias and accuracy cost. There is no blocker, and nothing in the model or its feature definitions was changed.

Reproduce:
```
.venv/bin/python scripts/live/audit_partial_window.py
```
This writes `reports/live/partial_window_audit.json`. The script only reads data. The model is loaded through the API's hash-verified `FrozenPredictor` and only predicts.

Numbers below are as of the data cutoff of **2026-11-20**:
- about **15.7 of a typical 56.5** pre-break games per team (**28%**);
- **352** lineups with ≥ 25 pre-break possessions per end.

## 1. Can every feature be computed on a partial window?

Yes. All 11 model features (`models/final/frozen_spec.json`, `features_used`) are defined for any number of possessions:
- the pipeline's imputer and scaler accept every 2026-27 row;
- every prediction is finite;
- every recorded lineup is scored.

The tests that check this are in `tests/api/test_live_predictions_real.py`. The features fall into four groups by how a short window affects them:

| Feature group | Features | Effect of a partial window |
|---|---|---|
| Rates | `team_off_rating_loo`, `team_def_rating_loo`, `p_team_share_min` | Unbiased definition, but noisier. Team ratings rest on about 28% of the usual possessions. Early rotations are tighter, so the least-used player's share is higher |
| Volume | `lu_log_poss` (coefficient −0.50 per log unit) | Smaller early in the season |
| Counts of missing history | `p_n_no_history`, `p_n_new_to_team`, `lu_no_history` | Players with no possessions *yet*, such as those injured to date, count as having no history |
| EB player rates | `p_def_rating_eb_mean`, `p_on_off_eb_mean`, `p_usage_eb_mean`, `p_usage_eb_max` | Shrunk toward a prior whose mean **rises with log(possessions)** (β₁ = 2.25 for on-off, 0.99 for DRtg, 1.25 for usage). Early in the season every player has fewer possessions, so starters get a weaker-player prior, and their thin data is shrunk hard toward it |

The last row is the substantive concern. The model reads volume as a signal of role, and early in a season volume is low for everybody.

## 2. How far do the inputs drift?

The table shows the mean of each feature over eligible lineups, in units of the model's own training standard deviation. A completed held-out season, 2025-26, is shown for reference.

| Feature | 2026-27 (partial) | 2025-26 (complete) |
|---|---|---|
| `p_on_off_eb_mean` | **−1.13** | +0.38 |
| `p_def_rating_eb_mean` | −0.11 | +0.83 |
| `team_off_rating_loo` | +0.26 | +0.62 |
| `team_def_rating_loo` | +0.09 | +0.67 |
| `p_team_share_min` | +1.25 | +0.81 |
| `lu_log_poss` | +1.24 | +1.26 |
| `p_usage_eb_max` | +0.29 | +0.12 |

The on-off feature moves by 1.5 SD against the reference. That is the volume-dependent prior at work. The other features stay within the range a completed season also shows. These shifts come from restricting the sample to lineups with ≥ 25 possessions; they aren't out-of-range values.

## 3. How much does the partial window bias the predictions? (diagnostic counterfactual)

The diagnostic multiplies each team's season-to-date totals by (typical full window ÷ games played). The rates stay the same; only the volume changes. It then re-scores with the same frozen model. This counterfactual is **only a measurement** and is never served.

| Measure (352 eligible lineups) | Value |
|---|---|
| Served minus full-window counterfactual, mean | **−1.9 points** (served predictions run low) |
| SD of the difference | 1.9 |
| 10th–90th percentile of the counterfactual minus served | −0.7 to +4.3 |
| Rank correlation, league-wide | 0.98 |
| Rank correlation within teams, median | 0.91 |
| Top-25 overlap | 20 of 25 |
| For scale: 95% interval half-width of every prediction | ±18.7 |

So the bias is a modest, mostly uniform downward shift. It is about a tenth of the interval width, and it barely changes the ranking.

## 4. What does reduced volume cost in accuracy? (held-out backtest)

The backtest takes held-out 2025-26 pre-break totals, shrinks them to 28% (same rates, 28% of the volume), scores them with the frozen model, and compares the result with 2025-26's real post-break outcomes. It uses the possession-weighted RMSE on the model's target sample (≥ 25 post-break possessions per end, n = 695).

| | RMSE |
|---|---|
| Frozen model, completed window (as evaluated in Phase 6) | 25.18 |
| Frozen model, volume shrunk to 28% | **25.41** |
| Team-prior baseline, completed window | 25.30 |

At this volume, the model's small edge over the team prior disappears. Predictions also shift down by 1.6 points, which agrees with section 3.

This is a **lower bound** on the accuracy cost, because the extra noise of early-season *rates* isn't simulated. That would need historical partial-window data, meaning about 180 additional NBA API requests per season, which this audit doesn't make.

## Decision

- **Serve 2026-27 predictions, labelled PROVISIONAL.** They come from the unchanged frozen model and pre-break games up to the data cutoff only. They cover recorded lineups and hypothetical fives, and appear in the Prediction Lab and on the Rankings page.
- **Do not correct the bias, and do not change any feature definition.** Rescaling volumes or re-fitting priors would change the model, and it couldn't be validated on held-out data without the partial-window history above.
- **Disclose it with every prediction** (API `notes`, `season_progress` and the dashboard's provisional notice):
  - the data cutoff;
  - the share of the pre-break window played;
  - the roughly 2-point downward bias and the largely unaffected rank order;
  - that the 95% intervals are likely too narrow;
  - that at this volume the model did not beat the team-prior baseline, so the baseline should be treated as at least as good.
- **Re-run the audit** as the season advances. The bias and the accuracy cost shrink as the fraction of the window grows, and both vanish at the All-Star break, when the window is complete.

## Leakage and reproducibility

- **Leakage:**
  - Features are read only from `pre_asb` rows, through `PreBreakTables.validate` and a recording-connection test.
  - The season-in-progress window ends at the last game on or before the data cutoff.
  - Games published after the cutoff change nothing. This is tested for recorded lineups and hypothetical fives in `tests/db/test_refresh_db.py`.
- **Reproducibility:** the same data version gives identical predictions, even after a cache rebuild.
- **Updates:** a new successful refresh changes `data_version`, and the next request recomputes the predictions.
- **Historical predictions are unchanged.** The 2024-25 and 2025-26 predictions equal the Phase 9 export to within 1e-6, and the artifact hash still matches `frozen_spec.json`.
