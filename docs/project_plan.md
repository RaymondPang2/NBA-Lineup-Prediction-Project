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
   - The same rule applies to SQL views and Power BI DAX, e.g. `DIVIDE(SUM(opp_pts), SUM(opp_poss)) * 100`.
4. **Models:** Linear Regression, Ridge Regression and Random Forest in Phase 6, compared against the baselines.
5. **Sample-size gate before Phase 6.** Model development starts only after the training data has been confirmed sufficient. See `docs/ingestion.md` for the current measured coverage and the gate thresholds.

## Phases (each needs approval before it starts)
| # | Phase | Status |
|---|---|---|
| 0 | Setup + data spike | Done (approved 2026-11-10) |
| 1 | Ingestion (cached, resumable, per team, row-cap guard, `ingestion_runs`) | Done, awaiting review |
| 2 | PostgreSQL schema, cleaning, validation, loading | |
| 3 | Metric recomputation and checks | |
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
