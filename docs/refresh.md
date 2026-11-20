# Season in progress and the daily refresh

The warehouse holds the eight completed seasons (2018-19 to 2025-26) and the **season in progress, 2026-27**, season to date. A macOS launchd job refreshes 2026-27 every morning at 07:00 (America/Toronto). The dashboard picks up new data by itself.

Everything here runs **locally and privately**. Nothing is deployed, and nothing touches AWS or any other cloud service.

## Quick reference

| Task | Command (run from the project root) |
|---|---|
| Refresh now (the manual "Refresh Data" command) | `.venv/bin/python -m nba_lineups.refresh` |
| Refresh now and refetch every team (correction sweep) | `.venv/bin/python -m nba_lineups.refresh --full` |
| Status: last refreshes, freshness, whether a run is due | `.venv/bin/python -m nba_lineups.refresh --status` |
| Enable the daily schedule | `scripts/refresh/install_schedule.sh` |
| Check the schedule | `scripts/refresh/schedule_status.sh` |
| Disable the daily schedule | `scripts/refresh/uninstall_schedule.sh` |
| Logs | `data/logs/refresh.log`, plus launchd's `data/logs/launchd-refresh.{out,err}.log` |

A refresh needs PostgreSQL running (`docker compose up -d`) and internet access from a non-cloud IP. The API and the dashboard do not have to be running.

## Data source: terms and technical limits

These were checked before automating anything (NBA.com Terms of Use, last updated July 13, 2026, https://www.nba.com/terms).

**Section 9, "NBA Statistics":**
- Statistics "may only be used, displayed, or published for legitimate news reporting or private, non-commercial purposes".
- Any use must include "a prominent attribution to NBA.com".
- They may not be used "in connection with any website, product, or service that features a database … of comprehensive, regularly updated statistics … without the Operator's express prior consent."

**What this project does about it:**
- It stays a private, local, non-commercial project.
- The dashboard footer credits NBA.com/stats on every page.
- Raw and processed data stay out of git (`data/` is ignored).
- **A daily-refreshed database must not be exposed publicly without NBA consent.** That constrains any future deployment.

**Section 1:** you may download material "to any single computer only for your personal, noncommercial use".

**Automated access:**
- The Terms contain no clause about robots, scraping or rate limits.
- `www.nba.com/robots.txt` doesn't disallow `/stats/` paths for generic user agents.
- The stats JSON API (`stats.nba.com/stats/…`, used through the open-source `nba_api` client) is undocumented and unsupported. It can change or block clients without notice.

**Technical limits observed (docs/phase0_data_report.md):**
- Datacenter IPs are blocked.
- Dashboard endpoints silently truncate at 2,000 rows.
- There is no per-game lineup feed. Lineup totals come only as sums over a date range.

**Request behaviour, given those limits:**
- At least 1 second plus random jitter between requests.
- Up to 4 attempts with exponential backoff (`IngestSettings`).
- Per-team lineup requests, to stay under the row cap.
- A normal day costs one game-log request plus the teams that played: roughly 30–60 small requests. Historical seasons are never requested again.

## What a refresh does

The steps are in `src/nba_lineups/refresh/runner.py`.

1. **Lock.** A file lock (`data/refresh/refresh.lock`, released by the kernel even after a crash) and a PostgreSQL advisory lock ensure one refresh at a time. A second run exits immediately with `locked`.
2. **Check the database first.** If PostgreSQL is down, the run fails before making any NBA request.
3. **Fetch the game log** (always one request) and apply the data cutoff:
   - The cutoff is yesterday in US Eastern time, counted only after 06:00 ET. Late West-coast games finish after midnight ET.
   - Rows after the cutoff are dropped, as are games without a result or without both team rows.
   - Postponed games simply aren't in the log until they're played. A make-up game is picked up on the day it's played.
4. **Build the windows** from the games played. Until the All-Star break only `pre_asb` exists, ending at the last game played. After the break, `post_asb` grows daily. The break is detected from the schedule gap, the same way as for past seasons.
5. **Detect changes.** Each team gets a fingerprint of its box-score lines, compared with the last successful load:
   - A team with a **new game** gets a new request, because its request now ends at its new last game.
   - A team whose **earlier games changed** (a stat correction) is refetched as well.
   - Unchanged teams reuse their cached files. Their request is identical, because each team's request ends at its own last game, which returns the same totals as ending at the window's end.
   - Corrections that don't show in the box score (for example, points moved between lineups) are caught by a **full sweep every 7 days**, or on demand with `--full`.
6. **Nothing new?** If no team changed, the warehouse already matches, and no sweep is due, the result is `no_change`. The data is confirmed current and nothing is rewritten.
7. **Fetch** only what changed: the league-wide team and player tables, plus the changed teams' lineup totals.
   - All requests are throttled and retried.
   - **If any request fails, nothing is loaded.** The run fails, the previous data stays published, and the files already fetched are reused by the next attempt.
8. **Load** the season in **one transaction** (the same code as `python -m nba_lineups.etl`):
   - Dimensions are upserted and the season's facts are replaced, so there are never duplicates.
   - The error-level data-quality checks run inside the transaction, so a failure rolls everything back. One example is lineup points that don't reconcile with the game log because one feed lags behind the other.
   - The fingerprints advance only after the commit, so a rejected load is retried properly.
   - Historical seasons are never rewritten.
9. **Record** the run: a row in `data_refreshes`, the local state file `data/refresh/state.json`, and the log.

One known source error is repaired in a documented way: a game-log row with fewer team minutes than its opponent row. Game 0022600231 on 2026-11-14 lists Denver with 168 minutes against New Orleans' 240. Both teams play the same length of game, so the larger value is used, and each repair is logged. Only the minutes field changes. Points, results and every lineup total come from the source unchanged.

## Scheduling (macOS launchd)

`scripts/refresh/install_schedule.sh` installs a per-user LaunchAgent: `~/Library/LaunchAgents/com.lineuplab.daily-refresh.plist`, generated from `scripts/refresh/com.lineuplab.daily-refresh.plist.template`.

It starts `python -m nba_lineups.refresh --if-due`:
- at **07:00** local time (`StartCalendarInterval`);
- **every hour** (`StartInterval`);
- when the agent loads: at login or on install (`RunAtLoad`).

Each start asks one question: has a refresh succeeded since today's 07:00 America/Toronto? If yes, it exits at once with no network or database use. If no, it refreshes. That single rule handles every case:

| Situation | What happens |
|---|---|
| Mac awake at 07:00 | Runs at 07:00 |
| Asleep at 07:00 | launchd runs the missed calendar job on wake. If not, the next hourly start runs it |
| Shut down at 07:00 | Runs at the next login (`RunAtLoad`) |
| NBA API down, or PostgreSQL (Docker) not running | Fails, previous data stays. Retried at each hourly start, at most 8 attempts per day |
| Already refreshed today | Hourly starts exit immediately |
| Two runs at once (scheduled plus manual) | launchd never starts a second copy of a running job, and the lock stops a manual run |

The Mac has to be awake for a run to happen. Nothing wakes it.

The job runs as your user, inside the project folder. On this Mac a test run under launchd had access to `~/Documents`. If macOS ever blocks it, see Troubleshooting.

### Checking that the schedule is enabled

```
scripts/refresh/schedule_status.sh
```

It prints the launchd state:
- `LOADED` when the job is installed;
- `runs`, the number of starts so far;
- `last exit code` (0 = refreshed, nothing new, or not due);
- `run interval = 3600`, the hourly catch-up.

It then prints the refresh status: whether the data is current, its cutoff, and the last five runs. Each run is marked `scheduled` or `manual`.

To check with launchd directly:
```
launchctl print gui/$(id -u)/com.lineuplab.daily-refresh | grep -E "state|runs|last exit"
```

## The API and the dashboard

**`GET /api/v1/data-status` (read-only)** reports:
- `last_updated_at` and `data_cutoff`;
- `freshness`: `current`, or `stale` when the data hasn't reached the cutoff that the latest 07:00 run should have produced, with a 2-hour grace period;
- `stale_reason`;
- the last attempt;
- `data_version`, the id of the last refresh that loaded data.

**There is deliberately no endpoint that starts a refresh.** Refreshes run only from launchd or the terminal, so nobody with access to the API can trigger NBA requests.

**Cache invalidation, without restarts or rebuilds:**
- *API:* the frozen model's per-season prediction cache is keyed by `data_version` for the season in progress. The first request after a refresh recomputes the provisional predictions from the new inputs. Completed seasons stay cached.
- *Dashboard:* the header polls `data-status` every 60 seconds, and again when the tab regains focus. When `data_version` changes, every cached API response is invalidated, so open pages refetch the new numbers. A refresh with no new data changes nothing.

**Dashboard display:**
- The header shows **"Data through ‹date› · updated ‹time›"** with a green (current) or amber (stale) dot.
- A banner explains stale data and shows the refresh command.
- 2026-27 appears in every season selector as *in progress*, and is the default season.
- Pages show season-to-date pre-break numbers. Post-break panels explain that the break is still ahead.

## Provisional predictions for 2026-27

The frozen linear model (SHA-256 `a15b0c7f…`) is used **as is**: it is not retrained, its parameters don't change, and the API checks its fingerprint.

**What stays the same:**
- **Target:** the expected post-All-Star-break net rating, conditional on the lineup playing after the break.
- **Inputs:** the season's pre-break data up to the cutoff only. The leakage guards and `PreBreakTables.validate` apply unchanged, and nothing after the cutoff is read or extrapolated.
- **Reported alongside every prediction:** the team-prior baseline and both 95% intervals.

**Every 2026-27 prediction is labelled provisional:**
- The API sets `provisional: true` and `data_cutoff`, and adds notes.
- The dashboard shows a badge and a notice.

**Why provisional:** the model was developed and evaluated on *completed* pre-break windows, about 55 games per team. Early in a season the inputs are far noisier. The predictions, and the intervals calibrated on completed windows, are therefore not independently validated at this point and are likely too narrow.

2026-27 is not part of the modeling universe. `ALL_SEASONS`, the development and held-out splits, and every reported metric are unchanged. The season is listed separately as `CURRENT_SEASON` / `LIVE_SEASONS` in `src/nba_lineups/config.py`. The Power BI export stays on the eight evaluated seasons.

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Dashboard says **stale** | `.venv/bin/python -m nba_lineups.refresh --status` | Read the last attempt's message. Then run the manual refresh |
| `database unavailable, nothing fetched` | `docker ps` (is `nba_lineups_db` running?) | Start Docker Desktop, then `docker compose up -d`. The next hourly start retries |
| `N requests failed …` | `data/logs/refresh.log` (timeouts, HTTP errors) | Usually temporary. The next attempt reuses what was fetched. Check that you're not on a VPN or cloud IP, which stats.nba.com blocks |
| `load rejected, previous data kept: … points_reconcile …` | Usually one NBA feed lagging another right after games end | Wait. The next attempt refetches the affected teams. If it persists for days, run `--full` |
| `locked` | Another refresh is running, or launchd is mid-run | Wait for it to finish. The lock can't go stale |
| `not due` in the logs | A refresh already succeeded since 07:00 | Normal. Use the manual command to force one |
| Schedule shows `NOT loaded` | `scripts/refresh/schedule_status.sh` | `scripts/refresh/install_schedule.sh` |
| launchd log shows `Operation not permitted` | macOS privacy control on `~/Documents` | System Settings → Privacy & Security → Full Disk Access: add the Python binary that `.venv/bin/python` points to (`readlink -f .venv/bin/python`), or move the project out of `~/Documents` |
| 8 failed attempts today | `--status` shows the cap | Fix the cause, then run the manual refresh. The cap resets at the next 07:00 |
| New season starts (2027-28) | | Set `CURRENT_SEASON` in `config.py`. The finished season can then be added to the completed seasons with the regular ingestion and ETL |

## Tests

**`tests/refresh/` (offline):**
- the cutoff rule, including the DST day and midnight;
- trimming rows after the cutoff and in-progress games;
- windows before and after the break;
- per-team request dates, with cache reuse and invalidation;
- fingerprints that detect corrections;
- relaxed validation for a partially played window;
- schedule logic: the 07:00 slot, catching up after sleep or shutdown, the daily retry cap;
- the lock and the launchd agent definition.

**`tests/db/test_refresh_db.py`** runs against a throwaway PostgreSQL database and a fake, internally consistent league:
- first ingestion, daily incremental ingestion, and running twice with no duplicates;
- games after the cutoff, and postponed games;
- corrections, both visible and invisible in the box score (the latter caught by the sweep);
- a lagging source feed rejected by the quality gate and recovered on the next run;
- NBA API timeouts, and database downtime (no NBA requests made);
- overlapping runs, and current versus stale freshness;
- the frozen model scoring the season: identical predictions when games after the cutoff appear, updated predictions after a refresh without a restart, and model parameters unchanged.

**Real warehouse:**
- `tests/api/test_endpoints_real.py`: data-status, provisional predictions, pre-break-only feature queries for 2026-27, and no refresh route;
- `tests/powerbi`: the eight evaluated seasons still reconcile exactly.

**Web:** the header status, the stale banner, the version-change refetch, the current-season overview, the provisional prediction, and an end-to-end test against the live API.

The macOS sleep and restart behaviour was verified by the scheduling-logic tests and on this Mac by running the installed agent under launchd. Actual sleep and shutdown can't be simulated in automated tests.
