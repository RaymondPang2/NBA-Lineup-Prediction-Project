# Metrics: definitions and validation (Phase 3)

The code lives in `src/nba_lineups/metrics.py` (Python) and in `src/nba_lineups/db/schema.sql` (SQL function `per100()` plus rating views). The tests check that the two give identical results on real data.
Validation report: `.venv/bin/python scripts/phase3/validate_metrics.py`.

## Definitions
| Metric | Formula | Undefined when |
|---|---|---|
| Offensive rating (ORtg) | 100 · PTS / **own** possessions | own possessions = 0 |
| Defensive rating (DRtg) | 100 · OPP_PTS / **opponent** possessions | opponent possessions = 0 or unknown |
| Net rating | ORtg − DRtg | either side undefined |
| Pace | 48 · (poss + opp_poss) / 2 / minutes | minutes = 0 |
| Possession estimate (box score) | FGA + 0.44·FTA − OREB + TOV | n/a. Used only as an independent check. |

**Rules**
1. **Undefined is NULL/NaN, never 0.** NBA's API publishes `0.0` for undefined ratings (8 such lineup rows); averaging those would bias the results.
2. **Aggregate, then divide.** A group's rating is Σpts / Σposs. An unweighted mean of lineup ratings gives team ORtg **9.2 points per 100 too low** (98.0 vs 107.2, dev seasons), because tiny lineups dominate it.
3. **Keep numerator and denominator on the same rows.** SQL `SUM()` skips NULLs, so aggregated DRtg is `per100(sum(opp_pts) FILTER (WHERE opp_poss IS NOT NULL), sum(opp_poss))`.
4. **Never round before aggregating.** Views hold exact values; round only for display.
5. **Compare with NBA using half-up rounding.** numpy/pandas use banker's rounding (2.25 → 2.2), but NBA rounds half up (2.25 → 2.3). With banker's rounding, 0.45% of rows look like false mismatches.

## Opponent possessions: the API doesn't publish them
| Route | Formula | Role |
|---|---|---|
| A | 100 · OPP_PTS / DEF_RATING | Kept for validation (`opp_poss_implied`). Undefined when the opponent scored 0; precision limited by DEF_RATING's single decimal. |
| **B (canonical)** | round(2 · PACE · minutes / 48 − POSS) | PACE has 2 decimals, so the error is ≤ 0.005·2·min/48, below 0.5 for any lineup under 2,400 min. **Rounding recovers NBA's exact integer**: 100% of 143,017 rows with playing time were within 0.25 of an integer. |
| C | OPP_FGA + 0.44·OPP_FTA − OPP_OREB + OPP_TOV | Independent sanity check: r = 0.9997 with B (≥ 100 poss), median ratio 0.994 |

Canonical `opp_poss` = B, falling back to rounded A for zero-second rows, otherwise NULL. It's computed **per source row before merging** name variants, then summed.

**Coverage (all seasons):** 142,994 rows via PACE, 16 via DEF_RATING, and **162 unknown**. All 162 are zero-second appearances, holding 87 of 1.99 M own possessions and 2 opponent points.

## Validation against NBA-published values
| Check | Result |
|---|---|
| Lineup ORtg, DRtg and net rating (un-merged lineups, half-up to 0.1), all 8 seasons | **137,227 compared, 0 mismatches.** This is now the error-level DQ check `ratings_match_nba`. |
| NBA net rating construction | round(ORtg − DRtg): 100% match. round(ORtg) − round(DRtg): 90.4%. |
| Route A vs canonical | Within DEF_RATING rounding (max 0.72 at 300+ poss) |
| Team ratings from lineup totals vs team endpoint (480 team-windows) | ORtg −4.45, DRtg −4.66, **Net +0.22** (sd 0.62, r = 0.994) |
| Player on-court (per team) vs player endpoint (5,223 player-windows, ≥ 500 poss) | ORtg −3.11, DRtg −3.33, **Net +0.22** (r = 0.994) |

**Interpretation:** the lineup feed counts about 3–4% more possessions than the team and player endpoints (see `database.md`). That lowers ORtg *and* DRtg by about 3–5 points, so those **levels aren't comparable across feeds.** Net rating is nearly unaffected, because both sides inflate about equally. The modeling rule stands: every rating comes from lineup totals.

## The two 2018-19 opponent-possession warnings (investigated)
1. **DET merged lineup (159 own poss). Resolved.** One 6-second partial row (`R. Bullock Jr.` name variant) allowed 0 points, so route A was 0/0. Route B gives exactly 2 opponent possessions (1.999865), and the lineup's total is now defined. The warning disappeared.
2. **BOS lineup (Horford–Hayward–Irving–Morris–Tatum, 2018-19 pre-break): 127 own vs 106 opponent possessions. Real, not an error.** Three independent routes agree: A = 106.02, B = 106.00, and the box-score formula C = 100.7 (which uses no NBA rating). The raw box score shows the imbalance too: 99 own FGA vs 86 opponent FGA. *Hypothesis (untestable with season totals):* substitution timing, with the unit entering or leaving around its own possessions. It's the most extreme case among lineups with ≥ 100 possessions in 8 seasons, and it stays a documented warning.

## Small samples (development seasons only)
| Possessions | Lineup-windows | Share of all possessions | SD of net rating | Share with \|net\| > 50 |
|---|---|---|---|---|
| < 25 | 86,003 | 41.2% | 89.6 | 46.7% |
| 25–99 | 10,409 | 30.8% | 28.2 | 8.0% |
| 100–299 | 1,474 | 15.7% | 15.8 | 0.3% |
| 300+ | 332 | 12.3% | 9.4 | 0.0% |

Most possessions are played by lineups too small to rate reliably. That supports building features from **pooled player-level** data. Phase 4 turned this into an explicit reliability model (standard errors, split-half reliability, shrinkage) using only 2018-19 to 2023-24. See `eda_reliability.md`. Phase 5 builds the shrunk player, team and lineup features and the baselines on top of it; see `features_baselines.md`.

## Known NBA data limitations (cumulative)
- No opponent possessions in the API; recovered exactly via PACE (above).
- Undefined ratings published as `0.0`.
- Lineups split across player-name variants (Phase 2).
- The lineup feed's possession count differs from the team and player endpoints by about 3–4% (Phase 2).
- One box-score point not credited to any lineup: game `0022500704` (Phase 2).
- 162 zero-second lineup appearances with unknowable opponent possessions (negligible).
