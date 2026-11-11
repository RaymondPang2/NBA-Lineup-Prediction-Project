# Database and ETL (Phase 2)

## Run it
```bash
docker compose up -d                          # PostgreSQL 17.6 on 127.0.0.1:5432 (password in git-ignored .env)
.venv/bin/python -m nba_lineups.etl           # load every ingested season (idempotent)
.venv/bin/python -m nba_lineups.etl --reset   # drop and recreate tables first (raw files untouched)
docker exec -i nba_lineups_db psql -U nba -d nba_lineups < sql/examples.sql
.venv/bin/python -m pytest                    # db tests use a throwaway database and are skipped if Postgres is down
```

## Layers
| Layer | Where | What |
|---|---|---|
| Bronze | `data/raw/**.json` | API responses exactly as received (Phase 1) |
| **Silver** | PostgreSQL tables | Typed, cleaned, normalized, constraint-checked (this phase) |
| Gold | Views / feature tables (Phases 3–5, 9) | Ratings, model features, Power BI star schema |

## Entity-relationship overview
```
seasons 1──* stat_windows 1──* lineup_window_stats *──1 lineups *──1 teams
   │                     │                                 │
   │                     ├──* player_window_stats *──1 players *──┐
   │                     └──* team_window_stats  *──1 teams       │
   └──* team_games *──1 teams                    lineups 1──* lineup_players (bridge)
ingestion_log, etl_runs: lineage / audit (no FKs)
lineup_window_stats 1──* lineup_split_stats   (Phase 4: home / road halves of the pre-break window)
```
`lineup_window_stats` has two composite foreign keys:
- `(lineup_id, season_id) → lineups` means a stats row's season must equal its lineup's season.
- `(season_id, window_type) → stat_windows` means it must name a real window.

## Constraints and what each prevents
| Constraint | Prevents |
|---|---|
| `EXCLUDE USING gist (season_id WITH =, daterange(...) WITH &&)` on `stat_windows` | Overlapping pre/post windows. This is a leakage guard enforced by the database itself. |
| `CHECK (pts = 2*fgm + fg3m + ftm)` (and the same for opponents) | Internally inconsistent box scores |
| `CHECK (plus_minus = pts - opp_pts)` | Inconsistent scoring margin |
| `CHECK (n_source_rows = 1 OR nba_*_rating IS NULL)` | Keeping NBA ratings that no longer describe a merged lineup |
| `UNIQUE (season_id, team_id, player_key)` + `CHECK (player_key ~ 5 ids)` | Duplicate or malformed lineups |
| FKs with `ON DELETE CASCADE` from windows to stats | Orphaned stats when a season's facts are replaced |

## ETL rules
1. **Name-variant splits are summed, not deduplicated.** The API can return one lineup as several rows when a player's display name changed, e.g. `L. Doncic`/`L. Dončić`, `E. Kanter`/`E. Freedom`, `M. Morris`/`M. Morris Sr.`. Those rows cover different games. Counts are summed and `n_source_rows` records the merge.
2. **Ratings are never stored**; they're computed in `v_lineup_window_ratings` from totals. ORtg = 100·PTS/POSS (own possessions). DRtg = 100·OPP_PTS/opp_poss_implied (opponent possessions).
3. **Opponent possessions** are backed out per source row as `100·OPP_PTS/DEF_RATING`, before merging. They're `NULL` when undefined (opponent scored 0). Phase 3 validates this derivation.
4. **Count columns are cast to integers only if the cast is lossless.** The API sends some counts as floats, such as `3.0`.
5. **Silver doesn't drop small samples.** 0-possession lineups and extreme ratios (one real lineup has an NBA pace of 28,794) are kept as facts. Analysis queries exclude them explicitly.
6. **Each season loads in one transaction:** upsert dimensions, replace facts using `COPY` into staging tables, run DQ checks, then commit. Any error-level DQ failure rolls back the entire season.

## Phase 4 addition: `lineup_split_stats` (home / road)
Grain: one lineup × pre-break window × game location, development seasons only. The data comes from the same per-team `LeagueDashLineups` requests with `Location=Home|Road` (the server's echoed `Location` is validated), and it reuses the main transform, so opponent possessions and name-variant merging follow identical rules. It's loaded by `etl/splits.py` in one transaction per season, and the main ETL loads it automatically when the split files exist. Error-level checks:
- home + road equal the window total for **every** lineup (poss, opp_poss, pts, opp_pts, seconds). No neutral-site games exist in 2018-19 to 2023-24; seasons with neutral games are refused.
- every un-merged split row reproduces NBA's published split ORtg/DRtg/net (half-up rounding).

Reloading a season deletes its split rows by cascade, and they're reloaded right after.

## Phase 4 finding: `player_window_stats.last_team_id` leaks post-break information
The player endpoint fills `TEAM_ID` with the player's **latest** team even when the request has a pre-break date filter. Nikola Vučević (2020-21) played every pre-break game for ORL, yet his pre-break row says CHI, because he was traded on 25 Mar 2021, after that season's break. Between 21 and 72 players per season have a pre-break `last_team_id` that matches none of their pre-break lineups. Rule: **never use `last_team_id` as a feature.** Derive a player's team(s) from lineup data (`v_player_window_on_court`). `analysis.continuation.build_features` raises `LeakageError` if the column is passed in.

## Data-quality checks (`src/nba_lineups/etl/dq.py`)
| Check | Severity |
|---|---|
| lineup has exactly 5 players; every lineup has stats; every team has lineups in both windows | error |
| every game has exactly 2 consistent team rows; every game date falls in exactly one window | error |
| lineup **points** and **plus-minus** sum *exactly* to the game log, per team and window | error |
| lineup time sums to team minutes (±1 min), per team and window | error |
| lineup-feed possessions ÷ team-endpoint possessions within [1.00, 1.08] | warning |
| lineup players have player stats for the window; implied opp. possessions within 15% of own (≥ 100 poss) | warning |

## Finding: two possession definitions
For every team, summing lineup possessions gives about **3–4% more** than the team endpoint's `POSS`. In 2023-24 pre-break the ratios ranged from 1.031 to 1.043 for the first five teams; see `sql/examples.sql` query 4. Points reconcile exactly, so only the denominator differs. Lineup-derived team ORtg is therefore about 4 points lower than the endpoint's.

**Rule:** team-level features are built from summed lineup totals, never from `team_window_stats` ratings. That way lineup and team ratings share one possession definition. *Hypothesis, not verified:* possessions interrupted by substitutions are credited to more than one lineup.

### Investigation (2022-23 + 2023-24; 120 team-windows)
| Evidence | Result |
|---|---|
| Lineup-sum ÷ team-endpoint possessions | 1.028 to 1.066 (median 1.038). Systematic, not noise. |
| corr(excess per minute, lineup-game appearances per minute) | **0.625**. Teams that change lineups more often have more excess possessions, controlling for time. |
| OLS: excess ~ lineup-game appearances + minutes | R² = 0.91. About **0.20 extra possessions per lineup-game appearance**, a lower bound on stints. |
| Textbook formula `FGA + 0.44·FTA − OREB + TOV` on team totals | 1.017 × team endpoint and 0.980 × lineup sum. It sits between the two feeds. |
| Implied opponent possessions ÷ own possessions (lineup totals) | 0.988. Partly explained by 0-point lineups whose opponent possessions are undefined (median 31 per team-window). Phase 3 will resolve this. |

**Conclusion:** the evidence is *consistent with* possessions being split across lineups at substitutions. It isn't proof, which would require play-by-play data (pbpstats, a stretch goal). The modeling rule is unchanged: every rating used in a model comes from lineup-feed totals.

## Full eight-season load (2026-11-10, `etl_runs` id 3)
- **8/8 seasons, 0 error-level DQ failures.** 143,172 lineup-window rows, 1,278 players, 30 teams. Load time 16.9 s.
- **Neutral-site games (10, five each in 2024-25 and 2025-26):** both game-log rows list the team as away (`@`), as in the NBA Cup semifinals and international games. They're stored with `is_home = NULL`, and `game_rows_consistent` accepts either exactly one home team or a neutral site. The first eight-season run failed on this and rolled both seasons back (`etl_runs` id 2, status `failed`).
- **One-point source discrepancy:** game `0022500704` (2026-02-01, BKN @ DET). The box score has BKN 77, but BKN's lineups for that game sum to 76; this was confirmed with single-game API calls. The point and plus-minus checks are errors beyond ±2 per team-window, and warnings (`points_exact`, `plus_minus_exact`) for any difference.
- **Name-variant merges:** 23 lineup-windows, all in 2018-19 pre-break (BOS, DAL, NYK, DET).
- **Open for Phase 3** (`opp_poss_close_to_poss` warnings, 2018-19): one merged DET lineup has undefined opponent possessions, and one BOS lineup has 127 own vs 106 implied opponent possessions.
- **Performance:** the DQ queries took about 80 s per season inside the load transaction, because planner statistics didn't yet reflect the freshly loaded rows. Running `ANALYZE` before the checks brought it under 1 s.
