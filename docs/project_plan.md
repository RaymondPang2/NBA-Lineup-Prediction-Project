# Project Plan — NBA Lineup Analytics & Prediction Platform

Approved 2026-11-09. Changes since approval are marked **(Phase 0 update)**.

## Scope
- Seasons: 2018-19 through 2025-26 (regular season). 2019-20 (bubble) and 2020-21 (72 games, March All-Star break) are flagged as irregular, and results are reported with and without them.
- Start with 2022-23 and 2023-24 only, and expand once the pipeline is tested.
- Data: `nba_api` → `LeagueDashLineups` (per team, `pre_asb`/`post_asb` date windows), plus player and team dashboards. pbpstats is a stretch goal.

## Prediction target (approved 2026-11-10)
Post-All-Star-break lineup net rating (per 100 possessions). Features come from the pre-break window: **player-level and team-level** features are primary, and the lineup's own history is optional and shrunk toward the mean. Observations are weighted by post-break possessions. Validation is chronological by season. See `docs/phase0_data_report.md` §5.

## Analytical contract (binding for all later phases)
1. **The target is conditional.** It's defined only for lineups that appear after the All-Star break. The estimand is: *"Given that a coach plays this lineup after the break, what will its net rating be?"* It is **not** a prediction for every possible lineup. The model card, API docs and dashboard must all say so.
2. **No post-break information in any input feature.** This is enforced in three places:
   (a) the date windows are disjoint (`pre_asb.date_to < post_asb.date_from`, unit-tested);
   (b) ingestion rejects any response whose echoed `DateFrom`/`DateTo` don't match the request;
   (c) the Phase 5 feature builder will read only `window = 'pre_asb'` rows and will include a test asserting that.
   "Lineup appears after the break" defines the *sample*. It must never become a *feature*.
3. **Possession denominators.**
   - ORtg = 100 × SUM(PTS) / SUM(**own** POSS).
   - DRtg = 100 × SUM(OPP_PTS) / SUM(**opponent** POSS).
   - Net = ORtg − DRtg.
   - Opponent possessions are stored as their own column (`opp_poss`, derived in Phase 3 and checked against `DEF_RATING`/`PACE`). They are never assumed equal to own possessions.
   - Aggregation always sums totals first and then divides. Ratings are never averaged.
   - **(Phase 2)** The lineup feed and the team endpoint count possessions differently: lineup sums are about 3–4% higher. Team-level features and benchmarks must be built from summed **lineup** totals, so every rating in a model shares one possession definition. See `docs/database.md`.
   - The same rule applies to SQL views and Power BI DAX, e.g. `DIVIDE(SUM(opp_pts), SUM(opp_poss)) * 100`.
4. **Models:** Linear Regression, Ridge Regression and Random Forest in Phase 6, compared against the baselines.
5. **Sample-size gate before Phase 6.** Model development starts only after the training data has been confirmed sufficient. See `docs/ingestion.md` for the current measured coverage and the gate thresholds.

## Phases (each needs approval before it starts)
| # | Phase | Status |
|---|---|---|
| 0 | Setup + data spike | Done (approved 2026-11-10) |
| 1 | Ingestion (cached, resumable, per team, row-cap guard, `ingestion_runs`) | Done (approved 2026-11-10) |
| 2 | PostgreSQL schema, cleaning, validation, loading | Done (approved 2026-11-10) |
| 3 | Metric recomputation and checks | Done, awaiting review |
| 4 | EDA, reliability and selection analysis (Matplotlib) | |
| 5 | Features + baselines + chronological splits | |
| 6 | Linear / Ridge / Random Forest, evaluation, model card | |
| 7 | FastAPI | |
| 8 | React + TypeScript + Tailwind + Recharts dashboard | |
| 9 | Power BI datasets + report | |
| 10 | CI/CD, deployment, documentation | |

## Power BI report requirements
The authoring environment is still to be decided: Power BI Service in the browser, a Windows lab PC, or a Windows 11 ARM VM on this Apple Silicon Mac. The report must show:
- **Star schema:** `fact_lineup_window` (grain: one lineup in one window) and `fact_prediction` (grain: one lineup in one model run). Dimensions are `dim_team`, `dim_player`, `dim_season`, `dim_window` and `dim_lineup`. A `bridge_lineup_player` table handles the many-to-many link between lineups and players.
- **DAX measures:** possession-weighted ORtg, DRtg and net rating calculated from summed totals (`DIVIDE(SUM(pts), SUM(poss)) * 100`, never an average of ratings), the standard error of net rating, a reliability flag based on possession thresholds, prediction error (MAE), and pre-vs-post change.
- **Interactive filters:** season, team, player (through the bridge table), minimum-possession slider, window, and model.
- **Insights pages:** (1) team lineup overview, (2) how sample size affects reliability, (3) model performance against baselines, (4) a write-up of the selection-bias finding.

## Visualization roles
- **Matplotlib:** static figures for analysis and reports.
- **Recharts:** interactive charts in the product.
- **Power BI:** BI modeling and self-serve reporting.

## Sample-size gate status (measured 2026-11-10, after Phase 2)
Post-break lineups whose 5 players all have pre-break possessions for the same team. Effective n uses Kish's formula with possession weights (`scripts/phase2/sample_size_report.py`).

| Split | Seasons | n (≥ 25 poss) | eff. n (≥ 25) | eff. n (≥ 50) |
|---|---|---|---|---|
| Train | 2018-19 to 2023-24 | 3,029 | **1,251** | 668 |
| Train, excluding irregular seasons | 2018-19, 2021-22 to 2023-24 | 2,126 | 867 | 464 |
| Validation | 2024-25 | 600 | 276 | 136 |
| Final test (never used for training) | 2025-26 | 563 | 230 | 92 |
| *Validation + test pooled* | 2024-25 + 2025-26 | 1,163 | *506* | *227* |

Gate checks at the ≥ 25 threshold:
1. Train effective n ≥ 1,000: **met** with all seasons (1,251). **Not met** without the irregular seasons (867), so the sensitivity analysis that excludes them will be less precise.
2. Held-out effective n ≥ 347: **not met by either single season.** It is met only if 2024-25 and 2025-26 are pooled (506). With 230 observations, the final test can detect r ≥ 0.18 at 80% power. Phase 0's player-feature signal was r ≈ 0.24.
3. Possession threshold: ≥ 50 roughly halves effective n. **≥ 25 with possession weights** stays the primary design.

**Evaluation design (decided 2026-11-10, Modified Option A):**
- **Model selection:** expanding-window cross-validation inside 2018-19 to 2023-24 only. For example, train ≤ 2019-20 → validate 2020-21, train ≤ 2020-21 → validate 2021-22, and so on.
- **Held out during all development:** 2024-25 and 2025-26. They're never used for training, tuning, feature selection or threshold choices. **2025-26 is never used for training or tuning, even after selection.**
- **Final evaluation** of the selected model: reported separately on 2024-25 and on 2025-26, and on both pooled.
- **Metrics:** MAE, RMSE and R², each unweighted and possession-weighted, with every baseline alongside, and with bootstrap confidence intervals (resampling lineups) for each metric and for model-minus-baseline differences.
- **Sensitivity:** the whole procedure is repeated with and without the irregular 2019-20 and 2020-21 seasons.
