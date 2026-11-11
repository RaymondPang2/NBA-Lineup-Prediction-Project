# Ingestion Pipeline (Phase 1)

## Run it
```bash
.venv/bin/python -m nba_lineups.ingest                    # default: 2022-23 and 2023-24
.venv/bin/python -m nba_lineups.ingest --seasons 2021-22  # more seasons later
.venv/bin/python -m pytest                                # offline test suite
```
Run it from your Mac, not from CI or the cloud, because stats.nba.com blocks many datacenter IPs. Rerunning the same command is always safe. Requests that were already cached and valid are skipped, and only missing, failed or corrupt ones are fetched again.

## Flow per season
```
LeagueGameLog ──► detect All-Star break from game-date gaps ──► windows.json {pre_asb, post_asb}
                                                                   │
        ┌──────────────────────────────────────────────────────────┘
        ▼
 2  LeagueDashTeamStats    (Advanced, per window)
 2  LeagueDashPlayerStats  (Advanced, per window)
180 LeagueDashLineups      (2 windows × {Advanced, Base, Opponent} × 30 teams)

for each request:  valid cache? ─yes─► skip
                      │no
                      ▼
          rate limit (≥1s + jitter) ─► fetch ─► retry w/ exponential backoff (max 4 attempts)
                      ▼
                  validate ─ok─► atomic write data/raw/…json      ─► log success
                      │bad
                      └────────► data/quarantine/…json            ─► log invalid
```

## Layout (all of `data/` is git-ignored)
```
data/raw/<season>/windows.json
data/raw/<season>/leaguegamelog/league.json
data/raw/<season>/leaguedashteamstats/<window>/advanced/league.json
data/raw/<season>/leaguedashplayerstats/<window>/advanced/league.json
data/raw/<season>/leaguedashlineups/<window>/<measure>/team_<id>.json
data/quarantine/…          payloads that failed validation (same paths)
data/ingestion_log.jsonl   one JSON record per fetch outcome → `ingestion_runs` table in Phase 2
```

## Validation rules
| Rule | Severity | Why |
|---|---|---|
| `resultSets[0]` exists, rows match header width, required columns present | error | Structure |
| Echoed `Season`/`MeasureType`/`DateFrom`/`DateTo`/`TeamID`/… equal what we requested | error | A silently ignored date filter would leak post-break data into features |
| Dashboard response has ≥ 2,000 rows | error | Silent truncation (Phase 0 finding) |
| Lineup `GROUP_ID` has 5 distinct numeric IDs in numeric order, no duplicates, correct `TEAM_ID` | error | Stable lineup keys |
| Negative GP / MIN / SUM_TIME_PLAYED / POSS | error | Impossible values |
| Empty lineup response for a team and window | error | Every team plays in both windows |
| Team table has exactly 30 teams; game log has exactly 2 rows per game and 30 teams | error | Completeness |
| `POSS == 0` lineups | warning | Real data, but ratings are undefined; excluded later |
| `MIN` vs `SUM_TIME_PLAYED/3000` differs by > 0.5 | warning | Rounding check |
| `NET_RATING ≠ OFF − DEF` beyond 0.2 | warning | Internal consistency |

## Known limitations
- `LeagueDashPlayerStats` returns **one row per player per window**. A traded player's stats are combined across teams, labeled with their latest team. Player features *per team* will therefore come from lineup data, by pooling a player's on-court possessions for that team. The player table is used only for rate stats like USG% and TS%.
- The API doesn't return opponent possessions. They're derived in Phase 3 (see the analytical contract in `project_plan.md`).
- The break-detection rule (largest gap between Feb 1 and Mar 20) is tested against 2020-21-style (March) and 2019-20-style (COVID suspension) calendars. Each real season's detected dates are still logged and should be checked when that season is added.

## Phase 1 run results (2026-11-10, run `b1cdd2919e21`)
| Check | Result |
|---|---|
| Requests | 370 planned, **370 success**, 0 failed, 0 invalid, 0 retries, 0 quarantined. About 8 minutes total. |
| Inventory | 185/185 expected files per season, all re-validated OK. 30 teams each. 164 (2022-23) and 160 (2023-24) game dates. |
| Windows | 2022-23: 2022-10-18 → 2023-02-16 / 2023-02-23 → 2023-04-09. 2023-24: 2023-10-24 → 2024-02-15 / 2024-02-22 → 2024-04-14. |
| Row cap | Largest single lineup response: 679 rows (cap 2,000) |
| Cross-check vs Phase 0 | Pre-break lineup rows 12,569 + 11,050 = 23,619 and post-break 5,612 + 6,471 = 12,083. Both identical to the Phase 0 spike. |
| Warnings | 965 lineup-window rows with POSS = 0 (expected; excluded later) |
| Idempotent rerun | 370/370 served from cache in about 1 s, 0 network calls, manifest unchanged |

## Sample-size gate for modeling (from `scripts/phase1/coverage_check.py`)
Post-break lineups with all 5 players present in pre-break data, which is the primary feature set:

| Season | ≥ 25 post poss | ≥ 50 | ≥ 100 | Effective n, all lineups ≥ 25 (possession-weighted) |
|---|---|---|---|---|
| 2022-23 | 493 (of 591) | 169 (of 192) | 68 | 224 |
| 2023-24 | 615 (of 686) | 236 (of 256) | 81 | 276 |

Effective n uses Kish's formula, (Σw)² / Σw². Weighting by possessions gives most of the influence to heavily used lineups, so the information content is less than the raw count.

Power (α = 0.05, 80%): detecting r = 0.15 needs n ≥ 347, r = 0.20 needs ≥ 194, and r = 0.25 needs ≥ 124.

**Gate (all must hold before Phase 6):**
1. Training seasons: effective n ≥ 1,000 at the chosen possession threshold.
2. Held-out test seasons (pooled): effective n ≥ 347.
3. Irregular seasons (2019-20, 2020-21) are reported separately, as well as pooled.

**Current status: NOT MET.** Two seasons give about 500 effective observations in total, which can't support both a training set and a test set. The remaining six seasons must be ingested first. If later seasons look like these two (an assumption to verify, not a measurement), 2018-19 to 2023-24 for training and 2024-25 to 2025-26 for testing would meet the gate.

## Phase 4: home/road location splits
`python -m nba_lineups.ingest --location-splits --seasons <dev seasons>` re-requests the pre-break lineup dashboards per team with `Location=Home` and `Location=Road` (3 measures × 30 teams × 2 locations = 180 requests per season). The cached season's game log and `windows.json` are reused. The server's echoed `Location` is validated like `DateFrom`/`DateTo`, and the files are cached at `data/raw/<season>/leaguedashlineups/pre_asb/{home,road}/...`. Run 2026-11-11 for 2018-19 to 2023-24: **1,080 requests fetched, 0 failed, 0 invalid.** The held-out seasons were not requested.
