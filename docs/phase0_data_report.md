# Phase 0 — Data Availability Report

**Date:** 2026-11-10 · **Source:** stats.nba.com via `nba_api==1.12.0`, endpoint `LeagueDashLineups`
**Sample:** 2022-23 and 2023-24 regular seasons, 5-man lineups, per-team requests, three date windows
**Reproduce:** `.venv/bin/python scripts/phase0/fetch_spike.py` then `.venv/bin/python scripts/phase0/analyze_spike.py`

Every number below is copied from the output of `analyze_spike.py`. Nothing here is estimated by hand.

## 1. Access

| Check | Result |
|---|---|
| Requests from a residential Mac IP | Worked. 182 requests (2 game logs, 2 league-wide, 180 per-team, 2 Base/Opponent) in 7 min 44 s with a 1 s pause between calls. No blocks and no retries needed. |
| Cloud IPs (GitHub Actions, Render) | Not tested. Other developers report blocking, so **ingestion stays local** and CI uses recorded fixtures. |
| All-Star break detection | Found from the largest February gap in game dates. 2022-23: pre ≤ 02/16/2023, post ≥ 02/23/2023. 2023-24: pre ≤ 02/15/2024, post ≥ 02/22/2024. |

## 2. Findings

### 2.1 Silent 2,000-row cap ⚠️
A request for the whole league with no team filter returns exactly **2,000 rows**: the lineups with the most minutes, all with MIN ≥ 12.
- 2022-23: 2,000 rows returned, but `L_RANK` goes up to 16,782.
- 2023-24: 2,000 rows returned, but `L_RANK` goes up to 15,901.

**Per-team requests fix this.** Summing the per-team rows gives exactly 16,782 and 15,901, which match the rank maximums. The largest single team response was 985 rows. → *Ingestion must request each team separately and check that the row count is below the cap.*

### 2.2 Lineup identifiers
- `GROUP_ID` looks like `-203484-203932-203999-1627750-1629008-`. All 68,385 rows contain exactly 5 player IDs.
- The IDs are **sorted numerically, not as strings**. pbpstats uses string sorting, so if we ever join the two sources we must normalize keys.
- There are no duplicate (season, window, team, GROUP_ID) rows.
- In these two seasons, no 5-player set appears under more than one team. We still key lineups on (team, season, players) because a traded player creates a new team context.

### 2.3 Minutes are rounded
`MIN` is always an integer, and it's within 0.5 of `SUM_TIME_PLAYED / 3000` in 100% of rows. `SUM_TIME_PLAYED` is the five players' combined time in tenths of a second (5 × 60 × 10 = 3000). → *Use `SUM_TIME_PLAYED / 3000` for exact minutes.*

### 2.4 Ratings and possessions
- `NET_RATING = OFF_RATING − DEF_RATING` to within rounding (max gap 0.10).
- No nulls in POSS, OFF/DEF/NET_RATING or MIN.
- **1,833 lineup-window rows have POSS = 0**, which makes any rating meaningless for them.
- **11,068 rows have |NET_RATING| > 100**, with a median of only 3 possessions. These are tiny-sample artifacts, not real performance.
- Checked against counting stats (Base + Opponent measures, Denver 2023-24, 28 lineups with ≥ 50 possessions):
  - `100 × PTS / POSS` reproduces `OFF_RATING` (max gap 0.05).
  - `PTS − OPP_PTS = PLUS_MINUS` in every row.
  - The textbook estimate `FGA + 0.44·FTA − OREB + TOV` gives a median of 0.984 × POSS (range 0.903–1.052). NBA counts possessions from play-by-play, so the formula is close but not exact.
  - **`DEF_RATING` divides by opponent possessions**, which the API doesn't return. Backing it out (`100 × OPP_PTS / DEF_RATING`) differs from POSS by −17.9 to +8.0, with a median of 0. That implied value reproduces `PACE` (max gap 0.03), so the explanation is internally consistent. The 17.9 gap at lineup level is surprisingly large, and Phase 3 should look into it.

### 2.5 Date filters are exactly additive ✅
For all 32,683 (season, team, lineup) keys, full-season POSS, exact minutes and GP equal pre-break plus post-break, with zero mismatches. → *We don't need to download the `full` window for counting stats. Get full-season values as pre + post, and recompute ratings from the summed totals. Never average two ratings.* This cuts about a third of future requests.

### 2.6 Sample sizes (both seasons combined)

| Window | Lineup rows | Median poss | ≥ 50 poss | ≥ 100 | ≥ 200 |
|---|---|---|---|---|---|
| full | 32,683 | 6 | 1,707 | 621 | 230 |
| pre_asb | 23,619 | 6 | 1,165 | 432 | 156 |
| post_asb | 12,083 | 6 | 448 | 159 | 62 |

Most lineups barely play. The post-break window has about 30% of the possessions (72,069 of 256,764 in 2022-23; 84,236 of 255,082 in 2023-24).

## 3. Selection into the post-All-Star-break target

The plan was to start from lineups with ≥ 50 pre-break possessions and predict their post-break net rating. Here's how many of those lineups the target can actually cover:

| Of the 1,165 pre-break lineups with ≥ 50 poss | Share |
|---|---|
| Appear after the break at all | 34.5% |
| Have ≥ 50 post-break poss (target observed) | **10.3%** |
| All 5 players still played for the team after the break | 55.5% |
| Target observed, given all 5 were available | 18.6% |

Observed rate by pre-break net rating (quintiles):

| Quintile | n | Observed | Median pre net | Median pre poss |
|---|---|---|---|---|
| Q1 worst | 233 | 6.4% | −21.1 | 70 |
| Q2 | 235 | 7.2% | −6.1 | 81 |
| Q3 | 233 | 13.7% | 3.0 | 101 |
| Q4 | 231 | 14.7% | 12.4 | 94 |
| Q5 best | 233 | 9.4% | 27.5 | 69 |

Observed rate by pre-break possessions (quartiles): 3.5%, 6.5%, 9.6% and 22.0% from fewest to most.

**What this means:**
1. **Missing targets are not random.** Whether a lineup is observed depends on its earlier performance and, most strongly, on how much it had already played. Models trained only on observed lineups learn about lineups coaches trust, not lineups in general.
2. **Roster changes are a separate cause.** 44.5% of lineups lose a player to a trade, injury or rotation change. (By definition, a lineup can't be observed if one of its players stopped playing for the team, so the 0% observed rate in that group is mechanical, not a finding.)
3. **The selection probably also depends on the outcome itself.** Coaches likely pull lineups that start badly after the break, so those never reach 50 possessions. That would bias observed targets upward. This is a hypothesis, and with season totals alone we can't test it directly.
4. The top quintile is observed less often than Q3/Q4. Its median possessions are lower (69), so many of those extreme ratings come from small samples.

## 4. Is there any signal? (preliminary exploration, not model results)

| Relationship (≥ 50 poss in the relevant windows) | n | Pearson r (95% bootstrap CI) |
|---|---|---|
| Lineup pre net → same lineup post net | 120 | **0.004** |
| Lineup pre ORtg → post ORtg | 120 | −0.024 (−0.227 to 0.182) |
| Lineup pre DRtg → post DRtg | 120 | 0.108 (−0.126 to 0.353) |
| Average of the 5 players' pre on-court net → post lineup net | 405 | **0.238 (0.148 to 0.321)** |
| Team pre net → post lineup net | 405 | 0.195 (0.107 to 0.282) |

For those 120 lineups, the MAE of persistence (predicting post = pre) is 17.91. That's **worse** than always predicting 0 (13.54). This is regression to the mean: at 50–100 possessions, a lineup's own rating is mostly noise.

The player feature is the possession-weighted on-court net rating across all of a player's pre-break lineups for that team. It pools far more possessions, so it carries more signal. It's available for 90.4% of post-break lineups with ≥ 50 possessions.

Caveats: two seasons, simple correlations, no controls. Treat this as a direction for Phase 4 and 5, not a conclusion.

## 5. Proposed handling of selection bias and the target (for approval before Phase 5)

1. **Make the estimand explicit.** Predict *"the net rating of a lineup that a coach plays after the All-Star break"*. This is a conditional question, and it's the one coaches and analysts actually face. Document it in the model card.
2. **Build the sample from post-break lineups, not pre-break ones.** The unit is every lineup with post-break possessions. Features come from **players and the team** in the pre-break window, which 90% of those lineups have. The lineup's own pre-break history becomes an optional feature with a `has_pre_history` flag and shrinkage. This removes the 10% coverage problem.
3. **Replace the hard cutoff with weights.** Weight observations by post-break possessions, which roughly matches the inverse of the target's noise variance. Use a low minimum (e.g. 25 poss), and test sensitivity at 0, 25, 50 and 100. Report possession-weighted MAE, RMSE and R².
4. **Measure the selection.** Fit a logistic model of P(observed after the break | pre-break features) and report it in the EDA.
5. **Sensitivity analysis, not the main method:** inverse-probability weighting using that model. Check whether the conclusions change.
6. **Baselines stay:** predict 0, team pre net, average player prior, and empirical-Bayes shrinkage. Phase 0 already suggests "predict 0" will be hard to beat with lineup history alone.

## 6. Implications for later phases

| Topic | Decision or note |
|---|---|
| Ingestion | Request per team. Only the `pre_asb` and `post_asb` windows. Advanced + Base + Opponent measures. That's about 30 × 2 × 3 = 180 requests per season, roughly 1,440 for 8 seasons, or about 1 hour at the observed rate. Cache everything. Make it resumable. |
| Row-cap guard | Fail loudly if any response has ≥ 2,000 rows. |
| All-Star break dates | The February-gap method won't work for **2020-21** (break was in March) or the **2019-20** bubble. Store verified dates in the `seasons` table and test them. |
| Cleaning | Keep POSS = 0 rows for counting, but they can never be used as model targets. Never treat raw ratings from small samples as reliable. |
| Metrics | Recompute ORtg from PTS/POSS. Keep NBA's DEF_RATING alongside ours, and look into the opponent-possession gap. |
| Licensing | Raw data is git-ignored. Personal, non-commercial use with NBA.com attribution. |
