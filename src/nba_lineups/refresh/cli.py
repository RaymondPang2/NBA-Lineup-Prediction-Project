"""Refresh the season in progress from NBA.com/stats into the local PostgreSQL warehouse.

    python -m nba_lineups.refresh              # manual refresh now (the "Refresh Data" command)
    python -m nba_lineups.refresh --full       # also refetch every team's lineup totals (correction sweep)
    python -m nba_lineups.refresh --status     # show the last refreshes and whether one is due
    python -m nba_lineups.refresh --if-due     # what launchd runs: work only if no success since 07:00 Toronto

Exit status: 0 = refreshed, nothing new, not due, or another refresh already running; 1 = failed (the
previous data stays published; the scheduler retries at its next hourly start). Logs: data/logs/refresh.log.
Personal, non-commercial use of NBA.com statistics only; never point a public service at this.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psycopg

from ..config import CURRENT_SEASON, DEFAULT_DATA_DIR, IngestSettings
from ..db.connection import connect
from . import freshness, runner, schedule


def _logging(data_dir: Path, verbose: bool) -> None:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    file = RotatingFileHandler(data_dir / "logs" / "refresh.log", maxBytes=2_000_000, backupCount=5)
    console = logging.StreamHandler()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in (file, console):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def status(data_dir: Path) -> int:
    now = datetime.now(UTC)
    st = schedule.LocalState.load(runner.Paths(data_dir).state_file)
    due, why = schedule.is_due(st, now)
    print(f"season in progress: {CURRENT_SEASON}")
    local = lambda iso: datetime.fromisoformat(iso).astimezone(schedule.LOCAL_TZ).strftime("%Y-%m-%d %H:%M") if iso else "never"
    print(f"last success {local(st.last_success_at)}; last attempt {local(st.last_attempt_at)} "
          f"({st.last_status or '-'}: {(st.last_message or '-').splitlines()[0][:110]})")
    print(f"scheduled refresh due now: {'yes' if due else 'no'} ({why})")
    try:
        with connect(connect_timeout=3) as conn:
            if conn.execute("SELECT to_regclass('data_refreshes') IS NULL").fetchone()[0]:
                rows, fresh = [], None
            else:
                rows = conn.execute("""SELECT refresh_id, trigger, status, started_at, data_cutoff, games_total,
                                              changed_teams, requests_fetched, message
                                       FROM data_refreshes ORDER BY refresh_id DESC LIMIT 5""").fetchall()
                fresh = freshness.status(conn, now)
    except psycopg.Error as exc:
        print(f"database: unavailable ({str(exc).strip().splitlines()[0] if str(exc) else exc!r})")
        return 1
    if fresh:
        print(f"data: {fresh['freshness'].upper()} - through {fresh['data_cutoff']} "
              f"(expected through {fresh['expected_cutoff']})" + (f"; {fresh['stale_reason']}" if fresh['stale_reason'] else ""))
    print("\nlast refreshes (newest first, local time):")
    for r in rows:
        msg = (r[8] or "").splitlines()[0][:110] if r[8] else ""
        print(f"  #{r[0]} {r[1]:9} {r[2]:9} {r[3].astimezone(schedule.LOCAL_TZ):%Y-%m-%d %H:%M} cutoff {r[4]} "
              f"games {r[5]} changed {r[6]} fetched {r[7]} | {msg}")
    if not rows:
        print("  none yet")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m nba_lineups.refresh", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if-due", action="store_true", help="scheduled mode: run only if a refresh is due")
    p.add_argument("--full", action="store_true", help="refetch every team's lineup totals (correction sweep)")
    p.add_argument("--status", action="store_true", help="print refresh status and exit")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--min-interval", type=float, default=IngestSettings.min_interval_s,
                   help="minimum seconds between NBA requests (default %(default)s)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.status:
        return status(args.data_dir)
    _logging(args.data_dir, args.verbose)
    outcome = runner.refresh(now=datetime.now(UTC), data_dir=args.data_dir,
                             trigger="scheduled" if args.if_due else "manual", only_if_due=args.if_due,
                             full=args.full, settings=IngestSettings(min_interval_s=args.min_interval))
    logging.getLogger("nba_lineups.refresh").info("outcome: %s - %s", outcome.status, outcome.message)
    print(f"{outcome.status}: {outcome.message}")
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
