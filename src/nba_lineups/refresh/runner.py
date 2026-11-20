"""One refresh of the season in progress: NBA API -> raw cache -> PostgreSQL, safely.

Order of operations (each step can fail without harming what is already published):

 1. lock        - one refresh at a time (file lock + PostgreSQL advisory lock);
 2. database    - checked BEFORE any NBA request, so a stopped database costs no API traffic;
 3. game log    - always refetched (1 request); trimmed to the data cutoff (live.py);
 4. detect      - per-team fingerprints of the box-score lines vs the last refresh: teams with new or
                  corrected games. Nothing new and the warehouse already matches -> 'no_change', done;
 5. fetch       - only what changed: league-wide team/player tables, and lineup totals of changed teams
                  (unchanged teams reuse their cached files); a full sweep every FULL_SWEEP_DAYS days
                  catches corrections that do not show in the box score. Throttled, retried (client.py);
 6. load        - only if EVERY request succeeded: the season is replaced in ONE transaction with the
                  error-level data-quality checks inside it (etl/load.py), so the dashboard sees either the
                  previous complete snapshot or the new complete one, never a mix, and never duplicates;
 7. record      - data_refreshes row (read by the API for "Last updated") and the local state file.

Historical seasons are never requested or rewritten.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg

from ..config import CURRENT_SEASON, IngestSettings
from ..db.connection import apply_schema, connect
from ..etl.extract import ExtractError, read_season
from ..etl.load import DataQualityError, load_ingestion_log, load_season
from ..etl.transform import TransformError, transform_season
from ..ingest import live
from ..ingest.client import NbaApiTransport, Transport
from ..ingest.pipeline import Ingestor, RunSummary, read_live_state
from . import schedule
from .lock import AlreadyRunning, RefreshLock

log = logging.getLogger("nba_lineups.refresh")

FULL_SWEEP_DAYS = 7
ADVISORY_KEY = 7_202_627          # arbitrary constant: pg_try_advisory_lock key for "refresh running"

SUCCESS, NO_CHANGE, FAILED, NOT_DUE, LOCKED = "success", "no_change", "failed", "not_due", "locked"


@dataclass
class Outcome:
    status: str
    message: str
    season: str = CURRENT_SEASON
    data_cutoff: date | None = None
    last_game_date: date | None = None
    games_total: int | None = None
    changed_teams: list[int] = field(default_factory=list)
    full_sweep: bool = False
    summary: RunSummary | None = None

    @property
    def ok(self) -> bool:
        return self.status in (SUCCESS, NO_CHANGE, NOT_DUE, LOCKED)


@dataclass
class Paths:
    data_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "refresh" / "state.json"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "refresh" / "refresh.lock"


def _db_windows(conn: psycopg.Connection, season: str) -> dict[str, tuple[date, date]]:
    rows = conn.execute("SELECT window_type, date_from, date_to FROM stat_windows WHERE season_id = %s", (season,))
    return {w: (a, b) for w, a, b in rows.fetchall()}


def _start_row(conn: psycopg.Connection, run_id: str, season: str, trigger: str) -> int:
    return conn.execute("INSERT INTO data_refreshes (run_id, season_id, trigger) VALUES (%s, %s, %s) "
                        "RETURNING refresh_id", (run_id, season, trigger)).fetchone()[0]


def _finish_row(conn: psycopg.Connection, refresh_id: int, o: Outcome) -> None:
    s = o.summary
    conn.execute("""
        UPDATE data_refreshes SET finished_at = now(), status = %s, data_cutoff = %s, last_game_date = %s,
               games_total = %s, changed_teams = %s, full_sweep = %s, requests_fetched = %s, requests_cached = %s,
               requests_failed = %s, message = %s
        WHERE refresh_id = %s""",
        (o.status, o.data_cutoff, o.last_game_date, o.games_total, len(o.changed_teams), o.full_sweep,
         s.fetched if s else None, s.cached if s else None, (s.failed + s.invalid) if s else None,
         o.message[:2000], refresh_id))


def _load(conn: psycopg.Connection, data_dir: Path, season: str) -> dict[str, int]:
    """Bronze -> silver for the season in progress, atomically (same path as `python -m nba_lineups.etl`)."""
    load_ingestion_log(conn, data_dir / "ingestion_log.jsonl")
    run_id = conn.execute("INSERT INTO etl_runs (seasons) VALUES (%s) RETURNING etl_run_id", ([season],)).fetchone()[0]
    try:
        counts, dq = load_season(conn, transform_season(read_season(data_dir / "raw", season)))
    except Exception as exc:
        conn.execute("UPDATE etl_runs SET finished_at = now(), status = 'failed', error = %s WHERE etl_run_id = %s",
                     (str(exc)[:2000], run_id))
        raise
    conn.execute("UPDATE etl_runs SET finished_at = now(), status = 'success', row_counts = %s, dq_results = %s "
                 "WHERE etl_run_id = %s",
                 (json.dumps({season: counts}), json.dumps({season: [r.__dict__ for r in dq]}), run_id))
    return counts


def refresh(*, now: datetime, data_dir: Path, trigger: str = "manual", season: str = CURRENT_SEASON,
            only_if_due: bool = False, full: bool = False,
            transport_factory: Callable[[IngestSettings], Transport] = lambda st: NbaApiTransport(st.timeout_s),
            connect_db: Callable[[], psycopg.Connection] = lambda: connect(autocommit=True, connect_timeout=5),
            settings: IngestSettings = IngestSettings(), ingestor_kwargs: dict[str, Any] | None = None) -> Outcome:
    paths = Paths(data_dir)
    state = schedule.LocalState.load(paths.state_file)
    if only_if_due:
        due, why = schedule.is_due(state, now)
        if not due:
            log.info("not due: %s", why)
            return Outcome(NOT_DUE, why, season)
    try:
        with RefreshLock(paths.lock_file):
            outcome = _refresh_locked(now=now, paths=paths, trigger=trigger, season=season, full=full,
                                      transport_factory=transport_factory, connect_db=connect_db,
                                      settings=settings, ingestor_kwargs=ingestor_kwargs or {})
    except AlreadyRunning as exc:
        log.warning("%s; skipping", exc)
        return Outcome(LOCKED, str(exc), season)
    # Only real attempts count toward the daily retry cap.
    schedule.record_attempt(state, now, outcome.status, outcome.message, success=outcome.ok).save(paths.state_file)
    return outcome


def _refresh_locked(*, now, paths: Paths, trigger, season, full, transport_factory, connect_db, settings,
                    ingestor_kwargs) -> Outcome:
    cutoff = live.data_cutoff(now)
    # 2. database first: no NBA traffic if we could not store the result anyway
    try:
        conn = connect_db()
        conn.execute("SELECT 1")
    except psycopg.Error as exc:
        msg = f"database unavailable, nothing fetched: {str(exc).strip().splitlines()[0] if str(exc) else exc!r}"
        log.error(msg)
        return Outcome(FAILED, msg, season, data_cutoff=cutoff)

    with conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_KEY,)).fetchone()[0]:
            raise AlreadyRunning("another refresh holds the database advisory lock")
        apply_schema(conn)                                   # idempotent; creates data_refreshes on first use
        ingestor = Ingestor(transport_factory(settings), paths.data_dir, settings, **ingestor_kwargs)
        refresh_id = _start_row(conn, ingestor.run_id, season, trigger)
        outcome = Outcome(FAILED, "unexpected error", season, data_cutoff=cutoff)
        try:
            outcome = _run(conn, ingestor, paths, season, cutoff, full)
        except (ExtractError, TransformError, DataQualityError) as exc:
            outcome.message = f"load rejected, previous data kept: {exc}"
            log.error(outcome.message)
        except Exception as exc:                                       # noqa: BLE001 - record, never crash silently
            outcome.message = f"{type(exc).__name__}: {exc}"
            log.exception("refresh failed")
        finally:
            try:
                _finish_row(conn, refresh_id, outcome)
            except psycopg.Error:
                log.exception("could not record the refresh outcome (database went away?)")
        return outcome


def _run(conn, ingestor: Ingestor, paths: Paths, season: str, cutoff: date, full: bool) -> Outcome:
    summary = RunSummary(ingestor.run_id)
    p = ingestor.live_plan(season, cutoff, summary)
    if p is None:
        return Outcome(FAILED, "; ".join(summary.problems) or "game log unavailable", season, cutoff, summary=summary)

    prev = read_live_state(paths.raw_dir, season) or {}
    old_fp = {int(k): v for k, v in prev.get("team_fingerprints", {}).items()}
    new_fp = live.team_fingerprints(p.games)
    changed = sorted(t for t in new_fp if old_fp.get(t) != new_fp[t]) + sorted(set(old_fp) - set(new_fp))
    last_sweep = prev.get("last_full_sweep")
    sweep = full or last_sweep is None or (cutoff - date.fromisoformat(last_sweep)).days >= FULL_SWEEP_DAYS
    in_db = _db_windows(conn, season) == {w.name: (w.date_from, w.date_to) for w in p.windows.values()}
    base = dict(season=season, data_cutoff=cutoff, last_game_date=p.last_game_date, games_total=p.n_games,
                changed_teams=changed, full_sweep=sweep, summary=summary)

    if not changed and not sweep and in_db:
        ingestor.commit_live_plan(p, prev | {"team_fingerprints": {str(k): v for k, v in new_fp.items()}})
        msg = f"no new or corrected games up to {cutoff}; data confirmed current"
        log.info(msg)
        return Outcome(NO_CHANGE, msg, **base)

    log.info("%s: cutoff %s, %d games, %d teams changed%s", season, cutoff, p.n_games, len(changed),
             ", full correction sweep" if sweep else "")
    ingestor.ingest_live_season(p, summary, force_all=sweep, force_league=True, force_teams=changed)
    if not summary.ok:
        msg = (f"{summary.failed} requests failed, {summary.invalid} invalid; previous data kept "
               f"(the next attempt reuses what was fetched)" + ("; " + "; ".join(summary.problems) if summary.problems else ""))
        log.error(msg)
        return Outcome(FAILED, msg, **base)

    # The plan files must exist for the load to read; the fingerprints, though, describe what the WAREHOUSE
    # holds, so they advance only after the load commits. If the load is rejected (e.g. one feed lags), the
    # next run still sees those teams as changed and refetches them instead of reusing the lagging files.
    ingestor.commit_live_plan(p, prev | {"games_total": p.n_games, "last_game_date": p.last_game_date.isoformat()})
    counts = _load(conn, paths.data_dir, season)
    ingestor.commit_live_plan(p, prev | {"team_fingerprints": {str(k): v for k, v in new_fp.items()},
                                         "last_full_sweep": cutoff.isoformat() if sweep else last_sweep,
                                         "games_total": p.n_games, "last_game_date": p.last_game_date.isoformat()})
    msg = (f"loaded {season} through {cutoff}: {p.n_games} games, {counts.get('lineups', 0)} lineups; "
           f"{summary.fetched} requests fetched, {summary.cached} reused")
    log.info(msg)
    return Outcome(SUCCESS, msg, **base)
