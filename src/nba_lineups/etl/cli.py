"""Bronze -> silver ETL entry point.

    python -m nba_lineups.etl                    # every season that has been ingested
    python -m nba_lineups.etl --seasons 2023-24
    python -m nba_lineups.etl --reset            # drop & recreate tables first (raw files untouched)

Seasons whose home/road location splits have been ingested (Phase 4) also get
lineup_split_stats, loaded after the season (reloading a season cascades its splits away).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ..config import ALL_SEASONS, DEFAULT_DATA_DIR
from ..db.connection import apply_schema, connect, reset_schema
from .extract import ExtractError, read_season
from .load import DataQualityError, load_ingestion_log, load_season
from .splits import SplitReconciliationError, has_location_splits, load_location_splits, transform_location_splits
from .transform import TransformError, transform_season

log = logging.getLogger("nba_lineups.etl")


def ingested_seasons(raw_dir: Path) -> list[str]:
    return [s for s in ALL_SEASONS if (raw_dir / s / "windows.json").exists()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m nba_lineups.etl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seasons", nargs="+", choices=ALL_SEASONS, metavar="SEASON")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--reset", action="store_true", help="drop and recreate all tables before loading")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    raw_dir = args.data_dir / "raw"
    seasons = args.seasons or ingested_seasons(raw_dir)
    with connect(autocommit=True) as conn:
        (reset_schema if args.reset else apply_schema)(conn)
        n_log = load_ingestion_log(conn, args.data_dir / "ingestion_log.jsonl")
        log.info("ingestion_log: %d new records", n_log)
        run_id = conn.execute("INSERT INTO etl_runs (seasons) VALUES (%s) RETURNING etl_run_id", (seasons,)).fetchone()[0]

        all_counts, all_dq, failed = {}, {}, []
        for season in seasons:
            try:
                counts, dq = load_season(conn, transform_season(read_season(raw_dir, season)))
            except (ExtractError, TransformError, DataQualityError) as exc:
                log.error("%s", exc)
                failed.append(season)
                continue
            if has_location_splits(raw_dir, season):
                try:
                    counts |= load_location_splits(conn, season, transform_location_splits(raw_dir, season))
                except (ExtractError, TransformError, SplitReconciliationError) as exc:
                    log.error("%s", exc)
                    failed.append(season)
            all_counts[season] = counts
            all_dq[season] = [r.__dict__ for r in dq]
            warn = [f"{r.name}={r.violations}" for r in dq if not r.passed]
            log.info("%s loaded: %s | DQ errors: 0 | warnings: %s", season, counts, ", ".join(warn) or "none")

        conn.execute("""UPDATE etl_runs SET finished_at = now(), status = %s, row_counts = %s, dq_results = %s,
                        error = %s WHERE etl_run_id = %s""",
                     ("failed" if failed else "success", json.dumps(all_counts), json.dumps(all_dq),
                      f"failed seasons: {failed}" if failed else None, run_id))
    print(f"etl_run {run_id}: loaded {len(all_counts)}/{len(seasons)} seasons" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
