# Phase 4: Exploratory analysis, statistical reliability and selection

**Scope:** development seasons 2018-19 to 2023-24 only. 2024-25 and 2025-26 were never read: every query filters to the development seasons in SQL, and `analysis.data.require_dev` re-checks the result. No prediction model was trained.
**Reproduce:** `.venv/bin/python scripts/phase4/eda_reliability.py` (about 20 s). It writes `reports/phase4/figures/*.png`, `reports/phase4/findings.json` (every number below, for React and Power BI) and `reports/phase4/reliability_curve.csv`.
**Code:** `src/nba_lineups/analysis/` contains `reliability.py` (measurement model, shrinkage, split-half, bootstrap), `continuation.py` (selection model) and `data.py` (guarded queries). The tests are in `tests/analysis/` and `tests/db/test_splits_real.py`.

## Headline findings
1. **A lineup's net rating is mostly noise.** The true-talent SD across lineups is **τ ≈ 6.1** points per 100 possessions (95% CI 5.1–6.8). The sampling noise of one rating is **SE ≈ 100·1.21·√(1/poss + 1/opp_poss)**, about 17 points at 100 possessions.
2. **Reliability reaches 50% only at about 790 possessions** (CI 630–1,140), and 70% at about 1,850. That is about 7 lineups per season before the break. At the modeling threshold of 25 possessions, reliability is **0.03**.
3. **The measurement model is confirmed on independent data.** Home and road games are disjoint halves of each lineup's sample. They reproduce the sampling constant (K = 14,015 vs 14,573) and the signal variance (τ² = 39.7 vs 36.9), and give **95.3% coverage** for nominal 95% intervals.
4. **Shrinkage fixes the raw rating's worst failure, but lineup history adds little.** The raw pre-break rating predicts the post-break rating *worse than the league average* (RMSE 24.2 vs 17.6). Empirical-Bayes shrinkage removes that penalty, and a **team-level prior** helps most (17.2). Almost all of the remaining error is noise in the target itself (noise floor RMSE **16.3**).
5. **Selection is strong and predictable.** Of pre-break lineups with ≥ 25 possessions, only **10%** reach 25 post-break possessions (29% appear at all). Out-of-season **AUC is 0.76** with good calibration. The driver is usage, not quality, and **44%** of the post-break modeling sample's possessions come from lineups that **didn't exist before the break**.
6. **A post-break leak in an NBA field was found and blocked.** The player feed's team field ignores the date filter (see *Leakage finding* below).

---

## 1. Distributions (fig01–fig03)
| Min. possessions | Lineup-windows | Share of all possessions | Pooled ORtg | Pooled DRtg | SD ORtg | SD DRtg | SD Net | Net 5th–95th pct |
|---|---|---|---|---|---|---|---|---|
| all | 98,218 | 100% | 107.6 | 107.4 | 57.7 | 58.5 | 84.4 | −150 to 123 |
| 25 | 12,215 | 58.7% | 110.6 | 108.0 | 18.8 | 18.6 | 26.6 | −43 to 45 |
| 100 | 1,806 | 27.9% | 112.3 | 108.8 | 10.8 | 10.2 | 14.8 | −22 to 26 |
| 300 | 332 | 12.2% | 113.6 | 108.8 | 7.3 | 6.6 | 9.4 | −11 to 19 |

- **Sample sizes are extremely skewed.** The median lineup-window has **6 possessions**; the 90th percentile has 28 and the 99th 147. The top 1% of lineups play 22% of all possessions, and the top 20% play 70%. Minutes and possessions carry the same information (median 0.45 minutes per possession).
- **Every rating's spread shrinks as the sample grows** (fig02). At 300+ possessions the net-rating SD is 9.4, of which roughly 6 is real. Bigger lineups also look *better* (pooled ORtg rises from 107.6 to 113.6), because coaches give good lineups more minutes: playing time is **selected on performance**.
- **Offense and defense are uncorrelated** across lineups with ≥ 100 possessions (r = 0.01, fig03). A lineup's offensive rating says nothing about its defense, so net rating is the sum of two independent signals.

## 2. Measurement model, standard errors and reliability (fig04–fig06)
**Model.** For lineup *i*, x_i = θ_i + e_i:
- x_i is the observed net rating.
- θ_i is the true rating, with mean μ and between-lineup variance τ².
- e_i is the sampling error, with variance K·h_i, where h_i = 1/poss + 1/opp_poss.

A rating is 100 × the average points per possession, so K = 100²·σ², where σ² is the variance of points on a single possession.

**Assumptions:**
- possessions are independent;
- σ² is equal on offense and defense and the same for every lineup;
- the true rating is independent of the noise.

The split-half analysis (§3) tests these assumptions on real data.

**Estimation (method of moments).** Since E[(x−μ)²] = τ² + K·h, regressing squared residuals on h gives τ² as the intercept and K as the slope. The regression uses iteratively reweighted least squares with weights 1/(τ² + Kh)². It is fitted on pre-break lineups with ≥ 10 possessions on each end (n = 21,912), and the confidence intervals come from a **cluster bootstrap over 180 team-seasons**, 300 replicates.

| Parameter | Estimate | 95% CI |
|---|---|---|
| μ (mean net, lineups ≥ 10 poss) | 1.91 | 1.23 – 2.64 |
| τ (true-talent SD) | 6.07 | 5.07 – 6.80 |
| K | 14,573 | 14,278 – 14,937 |
| σ, the implied SD of points on one possession | 1.207 | 1.195 – 1.222 |
| Possessions for reliability 0.5 | 791 | 628 – 1,142 |
| Possessions for reliability 0.7 | 1,845 | 1,466 – 2,664 |

**Robustness.** The parameters barely move when the minimum-possession filter for the fit ranges from 5 to 100 (τ 5.8–6.5, K 14,100–15,000). They are similar fitted one season at a time (τ 5.1–6.9) and without the irregular seasons (τ 6.04, K 14,651). Fitted separately, offense has τ = 6.1 and defense τ = 5.1: **defense is less reliable** (50% at about 540 vs 375 possessions on that end).

**Goodness of fit (fig05).** One two-parameter model reproduces the observed SD in *every* possession bin, including the tiny-lineup bins that were not used in the fit: 112 observed vs 114 predicted at 0–4 possessions, and 9.2 vs 9.2 at 400+. The funnel plot (fig04) shows that **95% of lineups, and 92% of those with ≥ 100 possessions, sit inside the band that pure noise around an average lineup would produce.**

**Standard errors and intervals** (equal possessions on both ends):
| Possessions | SE | 95% CI ± | Reliability | EB posterior SD | EB 95% interval ± |
|---|---|---|---|---|---|
| 25 | 34.1 | 66.9 | 0.03 | 6.0 | 11.7 |
| 100 | 17.1 | 33.5 | 0.11 | 5.7 | 11.2 |
| 250 | 10.8 | 21.2 | 0.24 | 5.3 | 10.4 |
| 500 | 7.6 | 15.0 | 0.39 | 4.8 | 9.3 |
| 1,000 | 5.4 | 10.6 | 0.56 | 4.0 | 7.9 |

- The *frequentist* interval x ± 1.96·SE describes what one lineup's data alone can say. At 100 possessions a +15 lineup has a 95% CI of roughly −18 to +48.
- The *empirical-Bayes* interval also uses what we know about lineups in general. It is never wider than the prior (±12) and narrows as data accumulate. Both intervals assume approximate normality, which the central limit theorem justifies for sums over many possessions; the coverage check in §3 holds even at 25 possessions per half.

**Reliability curve (fig06, `reliability_curve.csv`).** Reliability = τ²/(τ² + K·2/n). This share of observed variance that is signal is also the EB shrinkage weight. Reliability is 0.03 at 25 possessions, 0.11 at 100 and 0.27 at 300.

## 3. Split-half reliability (fig07)
**Why this needed new data.** The silver layer holds only window *totals*, so a split-half correlation can't be computed from it: there are no two halves to correlate. Odd/even-game splits would need per-game lineup data that the API doesn't provide efficiently. Instead, Phase 4 ingested the **same per-team lineup requests with `Location=Home` and `Location=Road`** for the pre-break window of the six development seasons (1,080 requests, 0 failures).

**How the halves are constructed.**
- **Disjoint:** no possession is in both halves. Their sampling errors are therefore independent, and that independence is what makes split-half valid.
- **Interleaved:** home and road games alternate through the season, so there is no time trend between the halves, unlike a first-half vs second-half split.
- **Exact:** for every lineup, home + road equals the window total for possessions, points, opponent possessions and seconds. This is an error-level ETL check. Every un-merged split row (85,347 split rows in total) must also reproduce NBA's published split ratings, another error-level check that passed for all six seasons. The development seasons have no neutral-site games.
- **Not identical:** home lineups are better by +4.8 net on average (home-court advantage on both ends). A constant shift doesn't affect a correlation. Lineup-specific home effects show up as the τ² of the difference model, which is small.

**Results** (lineups with at least the given possessions on each end in each half; 95% team-season cluster-bootstrap CIs):
| Min. per half | n | Observed r | Model-predicted r | Spearman–Brown (full window) | Cov(home, road) = τ² | K from home − road | z-SD | 95% coverage |
|---|---|---|---|---|---|---|---|---|
| 25 | 1,928 | 0.069 (0.025–0.118) | 0.063 | 0.13 | 39.7 (14–67) | 14,015 (12,697–15,344) | 0.99 | 95.3% |
| 50 | 790 | 0.159 (0.086–0.229) | 0.115 | 0.27 | 50.0 (27–71) | 12,893 (10,614–15,723) | 0.98 | 95.3% |
| 100 | 309 | 0.154 (0.041–0.247) | 0.198 | 0.27 | 25.7 (6–42) | 12,133 (6,942–16,086) | 0.99 | 95.1% |

**Interpretation.**
- **Cov(home, road) estimates τ² without any sampling model**, because the errors are independent. It agrees with the funnel estimate (36.9).
- **Var(home − road) estimates K**, and agrees with the funnel estimate (14,573).
- The standardized differences have SD of about 1, and nominal 95% intervals cover 95%. **The standard errors are calibrated.**
- Every observed r lies inside the model's CI. The split-half and model-based reliabilities agree, so the model-based curve can be used where split-half data doesn't exist, such as the post-break window and held-out seasons.
- **Spearman–Brown** (ρ_full = 2r/(1+r)) assumes equal-length halves. Home and road halves are only roughly equal in size, so treat that column as approximate.
- **Not claimed:** a lineup-level split-half r for *odd/even games*. It isn't identifiable from this data.
- **Team-level contrast:** at the team level, a classic odd/even-game split of pre-break point differential *is* identifiable from `team_games`. It gives r = 0.71 and Spearman–Brown 0.83 (180 team-seasons). Teams play about 7,000 possessions before the break; lineups play dozens.

## 4. Empirical-Bayes shrinkage (fig08)
**Method.** The posterior mean is prior + B·(x − prior), where B = τ²/(τ² + K·h) is the reliability.
- Hyperparameters (μ, τ², K) are estimated from **pre-break data of the other development seasons** (leave-one-season-out), so no post-break data is ever used to fit them.
- The evaluation target is the post-break net rating of lineups with ≥ 25 post-break possessions, weighted by post-break possessions. The CIs come from a team-season cluster bootstrap.

**Priors compared:**
- league mean;
- a possession-informed prior (μ + β·log poss, because used lineups are better);
- a team prior: the team's pre-break net rating from all **other** lineups, so the lineup isn't counted twice.

**Population:** pre-break ≥ 25 possessions; n = 803, effective n = 331.
| Predictor | Weighted RMSE | Gain vs raw | Gain vs league mean (95% CI) | Calibration slope (95% CI) |
|---|---|---|---|---|
| League mean | 17.60 | +6.62 | n/a | n/a |
| Raw pre-break rating | 24.23 | n/a | −6.62 | 0.08 (0.02–0.15) |
| EB → league mean | 17.49 | +6.74 | +0.11 (−0.10 to 0.37) | 0.40 (−0.06 to 0.89) |
| EB → possession-informed prior | 17.44 | +6.78 | +0.16 (−0.07 to 0.44) | 0.41 (−0.04 to 0.88) |
| Team prior only | 17.23 | +6.99 | +0.37 (0.03 to 0.71) | 0.67 (0.43 to 0.88) |
| **EB → team prior** | **17.19** | +7.04 | **+0.41 (0.07 to 0.80)** | 0.67 (0.42 to 0.90) |

With every lineup that has any pre-break history included (n = 1,668), the raw rating is catastrophic (RMSE 50.6) and the ranking of the shrinkage predictors is the same.

**Interpretation.**
- **Raw ratings must never be used as features.** Their slope of 0.08 means that a +20 pre-break lineup is expected to be only about +1.6 better than average after the break.
- **Shrinkage toward the league mean is safe but adds nothing significant over the mean.** The useful information is at the *team* level, which is significant (+0.41, CI excludes 0). This supports the approved plan to use team- and player-level features as primary.
- **A noise floor limits Phase 6.** A *perfect* predictor of true post-break talent would still have RMSE 16.3, because the post-break target is itself a noisy small-sample rating. Relative to the league mean, the **maximum achievable R² on this target is about 0.14** (0.08 including tiny lineups). The best simple predictor reaches 0.046, about a third of what is achievable. **Phase 6 R² values should be judged against this ceiling, not against 1.**
- **Calibration slopes below 1 for the team prior** (0.67, CI 0.42–0.90) mean that pre-break information also *decays* across the break (injuries, rotation changes, schedule, end-of-season incentives). Reliability (within a period) is not the same as stability (across periods).

## 5. Regression to the mean among continuing lineups (fig09)
Among lineups with ≥ 25 possessions both before and after the break (possession-weighted, n = 803):
- **Pre-break raw mean: +6.0. EB-shrunk mean: +3.1. Post-break mean: +4.9.** Continuing lineups really are above average, but their raw pre-break numbers exaggerate by how much.
- **Stability of true quality across the break: not identifiable.** The observed correlation is 0.06 (CI −0.00 to 0.13), and Cov(pre, post) = 34.8 (CI −1 to 69). The disattenuated "true" correlation (Spearman's correction) is 0.6 as a point estimate, but its bootstrap interval runs from below 0 to far above 1, because the estimated signal variances are close to zero in many replicates. We therefore don't report a stability number. This is a lesson in when corrections for attenuation break down.

## 6. Selection: which lineups continue? (fig10, fig11)
**Unit:** pre-break lineups with ≥ 25 possessions on each end (n = 8,120). **Label:** *continues* means ≥ 25 post-break possessions, i.e. entry into the modeling sample (10.1%); *appears* means any post-break possession (29.0%).

**Features, all pre-break.** The feature builder raises `LeakageError` if it receives post-break rows or the leaky team column:
| Feature | Odds ratio per 1 SD (95% CI) |
|---|---|
| log pre-break possessions | **1.90** (1.80–2.05) |
| EB-shrunk pre-break net rating | 1.09 (1.03–1.16) |
| team pre-break net rating (from lineup totals) | 1.30 (1.14–1.52) |
| least-used player's share of team possessions | 1.15 (1.01–1.29) |
| includes a player who played for 2+ teams pre-break | **0.56** (0.48–0.66) |

**Model:** unpenalized logistic regression on standardized features (`C=∞`), so each coefficient is a log odds ratio per standard deviation. CIs come from a team-season cluster bootstrap with 300 replicates.

**Validation.** Season-grouped cross-validation, so no season ever appears in both training and validation:
- **Leave-one-season-out:** AUC 0.73–0.79 in every season (pooled 0.756). Brier score 0.078 vs 0.091 for the base rate, with log loss improved in every fold.
- **Forward chaining** (train on earlier seasons only): the same, 0.73–0.79.
- **Calibration:** deciles of out-of-season predictions lie on the diagonal (fig10).
- **Without the irregular seasons:** mean AUC 0.774 vs 0.759 with all seasons.

**What drives continuation.** Usage dominates. The continuation rate rises from 5% (25–49 possessions) to 52% (400+). Quality matters much less: the best EB quintile continues at 17%, the others at 8–10%. A traded player roughly halves the odds. Coaches keep lineups they already use, built from players who are still on the team.

**How selection affects machine learning.**
1. **The target sample is not a random sample of lineups.** Continuers have much higher pre-break usage than eligible lineups (standardized mean difference +0.84), better quality (+0.31), better teams (+0.35) and fewer traded players (−0.46). The model's estimand stays *conditional*: "given that a coach plays this lineup after the break". The model must not be advertised for lineups that are never played.
2. **Most of the target has no usable lineup history.** *(Sample here: 3,706 post-break lineups with ≥ 25 possessions on each end. Phase 2's 3,029 additionally required all five players to have pre-break data for the team.)* **44%** of the post-break modeling sample's possessions come from lineups with *zero* pre-break possessions, and another 20% from lineups with 1–24. Only 21% have 100+. Lineup-level features would be missing or pure noise for most targets. **Player- and team-level features are necessary, not optional.**
3. **Inverse-probability weighting isn't needed, and is fragile here.** With 1/p̂ weights, three of the five features balance (|SMD| < 0.1). Two get *worse*: least-used player's share −0.50 and traded player +0.26. Some continuers have p̂ as low as 0.007, giving weights up to 145 and cutting the effective n from 820 to 272. Capping each weight at 20 by trimming p̂ at 0.05 restores most of the balance (|SMD| ≤ 0.16) with effective n 536.

   The root cause is the "played for 2+ teams" feature, which is ambiguous: a player traded *to* this team keeps the lineup alive. Its direction can't be recovered without post-break information (see the leakage finding below). Because the Phase 6 estimand is conditional, IPW isn't required. It would only be needed to generalize to *all* pre-break lineups.

## Leakage finding: `player_window_stats.last_team_id`
The NBA player endpoint fills `TEAM_ID` with the player's **latest** team, even under a pre-break date filter. Nikola Vučević (2020-21) played every pre-break game for ORL, yet his pre-break row says CHI: he was traded on 25 Mar 2021, *after* that season's break. In each season, 21–72 players have a pre-break `last_team_id` that matches none of their pre-break lineups.

A first draft of the selection model used this field. That draft looked too good: "includes a departed player" was 40% prevalent, its continuation rate was 0.6%, and AUC jumped to 0.83. The too-good result prompted the check that exposed the leak. The feature was removed. `build_features` now raises `LeakageError` if the column is present, a unit test enforces that, and the schema comment warns about it.

## Concepts (interview notes)
- **Reliability vs validity vs stability.** Reliability is the share of observed variance that is true variance within one period. Stability is whether the true value persists across periods. Validity is whether we measure the thing we mean. Lineup net rating has low reliability, unknown stability, and good validity (it matches NBA exactly, Phase 3).
- **Method-of-moments variance components.** Observed variance = signal + noise. If the noise variance is known as a function of sample size (K·h), the signal variance is what is left over. This is the same idea as random-effects meta-analysis (DerSimonian–Laird) and as "stabilization points" in sports analytics.
- **Why split-half needs disjoint halves.** Shared observations create correlated errors and inflate r. Covariance between independent halves estimates signal variance directly.
- **Spearman–Brown:** the reliability of a measure k times longer is kr/(1+(k−1)r). It assumes parallel halves.
- **Empirical Bayes (James–Stein).** Shrinking noisy estimates toward a well-chosen prior lowers total squared error, even though each individual estimate becomes biased toward the prior. The shrinkage factor equals the reliability. The prior's hyperparameters are estimated from the data ("empirical"), here only from development seasons and from other seasons in each fold.
- **Cluster bootstrap.** Lineups of one team share players and opponents, so they aren't independent. Resampling whole team-seasons gives honest CIs; resampling individual lineups would make them too narrow.
- **Regression to the mean** is what happens when you select on a noisy measure. Selecting the top raw ratings selects lucky noise, and a calibration slope below 1 measures how much.
- **Noise floor / R² ceiling.** When the target is itself measured with error, even a perfect model has positive RMSE. Report model performance relative to that ceiling.
- **Selection bias vs the estimand.** Reweighting (IPW) generalizes a selected sample to a population. You only need it if your estimand is about that population. Positivity (p̂ bounded away from 0) and correct specification are required. When they fail, weights explode; trimming trades bias for variance.
- **Leakage through metadata.** A "pre-break" request isn't guaranteed to return pre-break-only fields. Validate the semantics of every column. A result that is too good is a signal to look for leaks.

## Implications for Phase 5 (features and baselines)
*Implemented in Phase 5; see `features_baselines.md`. On the full modeling sample (which includes lineups with no pre-break history), the bar is the team prior's weighted RMSE of 21.81 against a noise floor of 21.04.*

1. **Primary features:** player-level pre-break ratings, shrunk with this phase's player-level analogue of the model, plus team-level pre-break ratings. **Lineup-level history:** optional, EB-shrunk only, with a "has history" indicator, because 44% of the target has none.
2. **Baselines must include** the league mean, the team prior and EB → team prior. The bar to clear is RMSE 17.2 on the comparable population, against a noise floor of 16.3.
3. **Every metric** should be reported alongside the R² ceiling. Possession weighting stays the primary design.
4. **Never use** `player_window_stats.last_team_id`, raw lineup ratings, or anything derived from the post-break window.
5. **Note for the possession weights:** the post-break target's sampling variance is K·h_post. Phase 6 can compare possession weights with inverse-variance weights 1/(τ² + K·h_post), choosing between them inside development-season cross-validation only.

## Inputs for the dashboards
| Use | Source |
|---|---|
| Reliability flag / slider (Power BI page 2, React) | `reliability_curve.csv`, `findings.json → reliability` |
| Net-rating standard error measure (DAX) | `SE = 100 * 1.207 * SQRT(1/poss + 1/opp_poss)` (σ from `measurement_model.sigma_per_poss`) |
| Shrunk rating | prior + B·(x − prior), with B = τ²/(τ² + K·h), τ² = 36.9, K = 14,573 (development-season estimates) |
| Selection-bias page | `continuation_by_possessions`, `continuation_odds_ratios_per_sd`, `modeling_sample_pre_break_history` |
| Static figures | `reports/phase4/figures/fig01`–`fig11` |
